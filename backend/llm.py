# llm.py - 大语言模型接口模块
# 功能包括：
# - LLM API封装（支持多种模型）
# - 提示词工程和管理
# - 流式响应处理
# - Token消耗统计
# - 模型切换和降级策略

from typing import List, Dict, Any, AsyncGenerator
from config import CONFIG
from client_factory import async_openai_client, create_openai_client

client = async_openai_client


def assemble_prompt(query: str, knowledge_results: List[dict], memory: dict) -> List[dict]:
    """
    按指定顺序组装messages
    
    Args:
        query: 用户查询
        knowledge_results: 知识库检索结果
        memory: 记忆数据
        
    Returns:
        组装好的messages列表
    """
    messages = []
    
    meta_rules = memory.get("meta_rules", "该用户正在使用企业知识助手")
    
    system_prompt = f"""你是一个企业知识助手，专注于帮助银行员工解答业务问题。
用户行为准则：{meta_rules}
回答要求：
- 优先基于提供的知识库内容回答
- 如有操作步骤，按序号列出
- 回答结尾标注信息来源
- 如知识库中没有相关内容，明确说明并建议联系相关部门
"""
    messages.append({"role": "system", "content": system_prompt})
    
    facts = memory.get("facts", [])
    if facts and len(facts) > 0:
        facts_formatted = "\n".join([
            f"- {f.get('entity', '')}：{f.get('fact_content', '')}"
            for f in facts
        ])
        messages.append({
            "role": "system",
            "content": f"用户相关历史事实：\n{facts_formatted}"
        })
    
    insights = memory.get("insights", [])
    if insights and len(insights) > 0:
        insights_formatted = "\n".join([f"- {i}" for i in insights])
        messages.append({
            "role": "system",
            "content": f"用户历史行为模式（供参考）：\n{insights_formatted}"
        })
    
    if knowledge_results and len(knowledge_results) > 0:
        knowledge_parts = []
        for r in knowledge_results:
            source_type = r.get("source_type", "knowledge")
            source_type_label = "操作手册" if source_type == "sop" else "知识文档"
            source_file = r.get("source_file", "未知来源")
            content = r.get("content", "")
            knowledge_parts.append(f"[来源：{source_file}（{source_type_label}）]\n{content}\n")
        
        knowledge_formatted = "\n".join(knowledge_parts)
        messages.append({
            "role": "system",
            "content": f"相关知识库内容：\n{knowledge_formatted}"
        })
    
    short_term = memory.get("short_term", [])
    if short_term:
        for msg in short_term:
            messages.append(msg)
    
    messages.append({"role": "user", "content": query})
    
    return messages


async def call_llm_stream(messages):
    import asyncio
    import json
    from concurrent.futures import ThreadPoolExecutor
    from client_factory import default_openai_client

    q = __import__('queue').Queue()

    def _stream():
        try:
            client = default_openai_client
            resp = client.chat.completions.create(
                model=CONFIG["chat_model"],
                messages=messages,
                stream=True
            )
            for chunk in resp:
                if chunk.choices and chunk.choices[0].delta.content:
                    q.put(chunk.choices[0].delta.content)
        except Exception as e:
            q.put(f"__ERROR__:{e}")
        finally:
            q.put(None)

    executor = ThreadPoolExecutor(max_workers=1)
    executor.submit(_stream)

    loop = asyncio.get_event_loop()
    while True:
        item = await loop.run_in_executor(None, lambda: q.get(timeout=60))
        if item is None:
            break
        if str(item).startswith("__ERROR__:"):
            raise Exception(str(item)[10:])
        yield item

def parse_source_tags(knowledge_results: List[dict], memory: dict) -> dict:
    """
    解析来源标签
    
    Args:
        knowledge_results: 知识库检索结果
        memory: 记忆数据
        
    Returns:
        包含来源信息的字典
    """
    meta_rule_used = memory.get("meta_rules", "") != "该用户正在使用企业知识助手"
    
    insights = memory.get("insights", [])
    
    facts_list = []
    for f in memory.get("facts", []):
        facts_list.append(f"{f.get('entity', '')}：{f.get('fact_content', '')}")
    
    sop_files = []
    knowledge_files = []
    for r in knowledge_results:
        source_type = r.get("source_type", "")
        source_file = r.get("source_file", "")
        if source_type == "sop" and source_file not in sop_files:
            sop_files.append(source_file)
        elif source_type == "knowledge" and source_file not in knowledge_files:
            knowledge_files.append(source_file)
    
    return {
        "meta_rule_used": meta_rule_used,
        "insights": insights,
        "facts": facts_list,
        "sop_files": sop_files,
        "knowledge_files": knowledge_files
    }