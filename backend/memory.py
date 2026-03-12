import os, sqlite3, json, uuid, requests
from datetime import datetime
from typing import List, Optional
import jieba.analyse
import httpx
from qdrant_client_singleton import get_qdrant_client
from qdrant_client.models import (Distance, VectorParams, 
    PointStruct, Filter, FieldCondition, MatchValue)

SQLITE_PATH = os.getenv("SQLITE_PATH", "./data/memory.db")
qdrant = get_qdrant_client()

existing = [c.name for c in qdrant.get_collections().collections]
if "insights" not in existing:
    qdrant.create_collection(
        collection_name="insights",
        vectors_config=VectorParams(size=1024, distance=Distance.COSINE))

def init_db():
    conn = sqlite3.connect(SQLITE_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS meta_rules(
        user_id TEXT PRIMARY KEY,
        rule_content TEXT,
        updated_at TEXT,
        conversation_count INTEGER DEFAULT 0)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS facts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT, entity TEXT, fact_content TEXT,
        source_session TEXT, created_at TEXT,
        last_accessed TEXT, access_count INTEGER DEFAULT 0,
        weight REAL DEFAULT 1.0)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS session_store(
        session_id TEXT PRIMARY KEY,
        user_id TEXT, messages TEXT, updated_at TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS insights(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT, content TEXT,
        vector_id TEXT,
        created_at TEXT)""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_facts_user_entity 
        ON facts(user_id, entity)""")
    conn.commit()
    conn.close()
init_db()

## Layer0：元规则
def get_meta_rules(user_id: str) -> str:
    conn = sqlite3.connect(SQLITE_PATH)
    row = conn.execute(
        "SELECT rule_content FROM meta_rules WHERE user_id=?",
        (user_id,)).fetchone()
    conn.close()
    if row:
        return row[0]
    # 根据user_id推断默认规则
    if "柜员" in user_id:
        default = "该用户是柜员岗位，回答需包含具体操作步骤"
    elif "客服" in user_id:
        default = "该用户是客服岗位，回答需简洁易懂便于向客户解释"
    elif "审批" in user_id:
        default = "该用户是审批岗位，回答需严谨、有依据、注明风险点"
    else:
        default = "该用户正在使用企业知识助手"
    conn = sqlite3.connect(SQLITE_PATH)
    conn.execute("""INSERT OR IGNORE INTO meta_rules
        (user_id, rule_content, updated_at, conversation_count)
        VALUES(?,?,?,0)""", (user_id, default, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return default

def maybe_update_meta_rules(user_id: str, conversation: str):
    conn = sqlite3.connect(SQLITE_PATH)
    row = conn.execute(
        "SELECT rule_content, conversation_count FROM meta_rules WHERE user_id=?",
        (user_id,)).fetchone()
    if not row:
        conn.close()
        return
    current_rule, count = row
    new_count = count + 1
    conn.execute(
        "UPDATE meta_rules SET conversation_count=? WHERE user_id=?",
        (new_count, user_id))
    conn.commit()
    conn.close()
    # 每1轮更新一次（临时改为1，便于测试）
    if new_count % 1 != 0:
        return
    try:
        from config import CONFIG
        from client_factory import default_openai_client
        client = default_openai_client
        resp = client.chat.completions.create(
            model=CONFIG["chat_model"],
            messages=[{"role":"user","content":
                f"根据以下对话历史，用一句话提炼该用户的沟通偏好和角色特征，"
                f"作为AI助手的行为准则。如当前规则已准确则原文返回。\n"
                f"当前规则：{current_rule}\n近期对话：{conversation}\n"
                f"只返回规则文本，不要其他内容。"}])
        new_rule = resp.choices[0].message.content.strip()
        print(f"[meta_rules] LLM返回：{new_rule[:100]}")
        print(f"[meta_rules] 准备写入：{new_rule[:100]}")
        conn = sqlite3.connect(SQLITE_PATH)
        conn.execute(
            "UPDATE meta_rules SET rule_content=?, updated_at=? WHERE user_id=?",
            (new_rule, datetime.now().isoformat(), user_id))
        conn.commit()
        conn.close()
        print(f"[meta_rules] 写入完成")
    except Exception as e:
        print(f"[memory] 元规则更新失败: {e}")


def _embed(text: str) -> List[float]:
    from config import CONFIG
    resp = requests.post(
        f"{CONFIG['embedding_base_url']}/embeddings",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {CONFIG['embedding_api_key']}"
        },
        json={"model": CONFIG["embedding_model"], "input": [text]},
        timeout=30
    )
    resp.raise_for_status()
    return resp.json()["data"][0]["embedding"]


def _extract_insights_from_conversation(conversation: str) -> List[str]:
    try:
        from config import CONFIG
        print(f"{CONFIG['chat_base_url']}/chat/completions")
        resp = requests.post(
            f"{CONFIG['chat_base_url']}/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {CONFIG['api_key']}",
                "Accept-Encoding": "identity"  # 加这行，禁用 gzip
            },
            json={
                "model": CONFIG["chat_model"],
                "messages": [{"role": "user", "content":
                    f"提取用户的行为模式和关注方向，"
                    f"重点是用户反复关注什么、提问习惯是什么、有什么偏好，\n"
                    f"不要提取用户的基本身份信息（岗位职责等由其他模块处理），\n"
                    f"如果对话中没有明显的行为模式，返回空数组[]\n\n"
                    f"以JSON数组返回，每项是一句话描述用户的行为模式，如：\n"
                    f"[\"用户反复询问贷款审批时效问题\",\"用户偏好了解具体操作步骤\"]\n\n"
                    f"只返回JSON数组，不要其他内容。\n对话内容：{conversation}"
                }]
            },
            timeout=30
        )
        print(resp)
        resp.raise_for_status()
        result = resp.json()
        content = result["choices"][0]["message"]["content"].strip()
        if content.startswith("["):
            return json.loads(content)
        return []
    except Exception as e:
        print(f"[memory] insight提取失败: {e}")
        return []


def after_conversation(user_id: str, conversation_text: str):
    try:
        insights = _extract_insights_from_conversation(conversation_text)
        now = datetime.now().isoformat()
        
        # 查询最近7天的已有insights进行去重
        conn = sqlite3.connect(SQLITE_PATH)
        existing = conn.execute("""
            SELECT content FROM insights 
            WHERE user_id=? 
            AND created_at > datetime('now', '-7 days')
        """, (user_id,)).fetchall()
        existing_contents = [r[0] for r in existing]
        
        # 简单去重：内容相似度超过80%不写入
        def is_similar(a, b):
            a_words = set(a)
            b_words = set(b)
            if not a_words or not b_words:
                return False
            overlap = len(a_words & b_words) / max(len(a_words), len(b_words))
            return overlap > 0.8
        
        inserted_count = 0
        for insight in insights:
            # 检查是否与已有内容相似
            if any(is_similar(insight, e) for e in existing_contents):
                print(f"[insight] 跳过重复内容：{insight[:30]}")
                continue
            
            vector = _embed(insight)
            point_id = str(uuid.uuid4())
            qdrant.upsert(
                collection_name="insights",
                points=[PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={
                        "user_id": user_id,
                        "content": insight,
                        "created_at": now
                    }
                )]
            )
            conn.execute("""INSERT INTO insights
                (user_id, content, vector_id, created_at)
                VALUES(?,?,?,?)""",
                (user_id, insight, point_id, now))
            inserted_count += 1
            # 添加到已有内容列表，防止同一批内重复
            existing_contents.append(insight)
        
        conn.commit()
        conn.close()
        print(f"[memory] 存储了{inserted_count}条insight（去重后）")
    except Exception as e:
        print(f"[memory] insight存储失败: {e}")


def search_insights(query: str, user_id: str, top_k: int=3) -> List[str]:
    try:
        query_vector = _embed(query)
        results = qdrant.query_points(
            collection_name="insights",
            query=query_vector,
            query_filter=Filter(must=[
                FieldCondition(
                    key="user_id",
                    match=MatchValue(value=user_id))]),
            limit=top_k,
            with_payload=True
        ).points
        return [r.payload["content"] for r in results]
    except Exception as e:
        print(f"[memory] insight检索失败: {e}")
        return []


def get_all_insights(user_id: str, limit: int=5) -> List[dict]:
    conn = sqlite3.connect(SQLITE_PATH)
    rows = conn.execute("""
        SELECT content, created_at FROM insights
        WHERE user_id=? ORDER BY created_at DESC LIMIT ?
    """, (user_id, limit)).fetchall()
    conn.close()
    return [{"content": r[0], "created_at": r[1]} for r in rows]


## Layer2：事实库
def search_facts(user_id: str, query: str, 
                 days: int=30) -> List[dict]:
    entities = jieba.analyse.extract_tags(query, topK=3)
    if not entities:
        return []
    placeholders = ",".join("?" * len(entities))
    conn = sqlite3.connect(SQLITE_PATH)
    rows = conn.execute(f"""
        SELECT id, entity, fact_content, created_at FROM facts
        WHERE user_id=? AND entity IN ({placeholders})
        AND created_at > datetime('now', '-{days} days')
        AND weight > 0.5
        ORDER BY last_accessed DESC LIMIT 5
    """, (user_id, *entities)).fetchall()
    now = datetime.now().isoformat()
    for row in rows:
        conn.execute("""UPDATE facts SET 
            last_accessed=?, access_count=access_count+1
            WHERE id=?""", (now, row[0]))
    conn.commit()
    conn.close()
    return [{"entity":r[1],"fact_content":r[2],"created_at":r[3]}
            for r in rows]


def extract_facts(user_id: str, session_id: str,
                  conversation: str):
    try:
        from config import CONFIG
        from client_factory import default_openai_client
        client = default_openai_client
        resp = client.chat.completions.create(
            model=CONFIG["chat_model"],
            messages=[{"role":"user","content":
                f"从以下对话中提取具体发生的事件、用户遇到的问题、用户的反馈意见。\n"
                f"要求：\n"
                f"1. 实体必须是业务对象，如：提前还款、开户流程、贷款审批、某个产品名称\n"
                f"   不能是'用户'这种泛指\n"
                f"2. 事实必须是具体发生的事情，如：用户反映XX有问题、用户遇到XX报错\n"
                f"   不能是用户的身份信息或岗位描述\n"
                f"3. 如果对话中没有具体事件，返回空数组[]\n"
                f"   宁可返回空，也不要编造或提取无意义的内容\n"
                f"返回JSON格式：\n"
                f"[{{\"entity\":\"业务对象名\",\"fact\":\"具体发生的事情\"}}]\n"
                f"只返回JSON数组。\n"
                f"对话内容：{conversation}"}]
        )
        raw_content = resp.choices[0].message.content.strip()
        print(f"[facts] LLM原始返回：{raw_content[:200]}")
        
        # 处理markdown代码块，提取JSON内容
        content = raw_content
        if content.startswith("```"):
            # 去掉开头的 ``` 或 ```json
            lines = content.split("\n")
            # 找到第一个非空行且不是 ``` 开头的行
            json_lines = []
            in_code_block = False
            for line in lines:
                if line.strip().startswith("```"):
                    in_code_block = not in_code_block
                    continue
                if in_code_block or (not in_code_block and line.strip()):
                    json_lines.append(line)
            content = "\n".join(json_lines).strip()
        
        print(f"[facts] 提取后的内容：{content[:200]}")
        
        if not content.startswith("["):
            print(f"[facts] 返回格式错误，不以[开头，实际开头：{content[:50]}")
            return
        facts = json.loads(content)
        now = datetime.now().isoformat()
        conn = sqlite3.connect(SQLITE_PATH)
        for f in facts:
            conn.execute("""INSERT INTO facts
                (user_id,entity,fact_content,source_session,
                 created_at,last_accessed,access_count,weight)
                VALUES(?,?,?,?,?,?,0,1.0)""",
                (user_id, f.get("entity",""), f.get("fact",""),
                 session_id, now, now))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[memory] 事实提取失败: {e}")


## 短期记忆
def get_short_term(session_id: str, last_n: int=5) -> List[dict]:
    conn = sqlite3.connect(SQLITE_PATH)
    row = conn.execute(
        "SELECT messages FROM session_store WHERE session_id=?",
        (session_id,)).fetchone()
    conn.close()
    if not row:
        return []
    messages = json.loads(row[0])
    return messages[-(last_n*2):]


def update_short_term(session_id: str, user_id: str,
                       user_msg: str, ai_msg: str):
    conn = sqlite3.connect(SQLITE_PATH)
    
    # 先找该用户最新的会话记录（用于持久化历史）
    row = conn.execute(
        "SELECT session_id, messages FROM session_store WHERE user_id=? ORDER BY updated_at DESC LIMIT 1",
        (user_id,)).fetchone()
    
    if row:
        # 用户已有历史记录，追加到最新的会话中
        existing_session_id, existing_messages_json = row
        messages = json.loads(existing_messages_json)
        messages.append({"role":"user","content":user_msg})
        messages.append({"role":"assistant","content":ai_msg})
        messages = messages[-20:]  # 最多保留10轮
        now = datetime.now().isoformat()
        # 更新到用户最新的会话中（不是当前session_id！）
        conn.execute("""UPDATE session_store 
            SET messages=?, updated_at=?
            WHERE session_id=?""",
            (json.dumps(messages, ensure_ascii=False), now, existing_session_id))
    else:
        # 用户没有历史记录，创建新的
        messages = [
            {"role":"user","content":user_msg},
            {"role":"assistant","content":ai_msg}
        ]
        now = datetime.now().isoformat()
        conn.execute("""INSERT OR REPLACE INTO session_store
            (session_id, user_id, messages, updated_at)
            VALUES(?,?,?,?)""",
            (session_id, user_id, json.dumps(messages, ensure_ascii=False), now))
    
    conn.commit()
    conn.close()


## 统一对外接口
def read_memory(query: str, user_id: str, session_id: str) -> dict:
    return {
        "meta_rules": get_meta_rules(user_id),
        "insights": search_insights(query, user_id),
        "facts": search_facts(user_id, query),
        "short_term": get_short_term(session_id)
    }


def write_memory(user_id: str, session_id: str,
                 user_msg: str, ai_msg: str):
    print(f"[write_memory] 开始执行，user_id={user_id}, session_id={session_id}")
    get_meta_rules(user_id)  # 加这一行，确保user记录存在
    conversation_text = f"用户：{user_msg}\nAI：{ai_msg}"
    
    for fn, args in [
        (after_conversation, (user_id, conversation_text)),
        (extract_facts, (user_id, session_id, conversation_text)),
        (maybe_update_meta_rules, (user_id, conversation_text)),
        (update_short_term, (session_id, user_id, user_msg, ai_msg))
    ]:
        try:
            print(f"[write_memory] 执行 {fn.__name__}...")
            fn(*args)
            print(f"[write_memory] {fn.__name__} 完成")
        except Exception as e:
            print(f"[write_memory] {fn.__name__} 失败: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"[write_memory] 全部执行完毕")


def get_memory_status(user_id: str, session_id: str) -> dict:
    conn = sqlite3.connect(SQLITE_PATH)
    rule_row = conn.execute(
        "SELECT rule_content,updated_at,conversation_count FROM meta_rules WHERE user_id=?",
        (user_id,)).fetchone()
    facts_rows = conn.execute("""
        SELECT id, entity, fact_content, created_at FROM facts
        WHERE user_id=? AND weight>0.5
        ORDER BY last_accessed DESC""", (user_id,)).fetchall()
    session_row = conn.execute(
        "SELECT messages FROM session_store WHERE session_id=?",
        (session_id,)).fetchone()
    conn.close()
    
    # 转换 facts 为前端期望的扁平数组格式
    facts_flat = []
    for row in facts_rows:
        facts_flat.append({
            "id": str(row[0]),
            "entity": row[1],
            "content": row[2]
        })
    
    session_count = 0
    if session_row:
        session_count = len(json.loads(session_row[0])) // 2
    
    # 获取 insights 并转换为前端期望的格式
    insights_raw = get_all_insights(user_id, limit=5)
    insights_formatted = []
    for idx, insight in enumerate(insights_raw):
        insights_formatted.append({
            "id": str(idx + 1),
            "date": insight.get("created_at", "") if insight.get("created_at") else "",
            "content": insight.get("content", "")
        })
    
    # 返回前端期望的数据结构（只包含四个必需字段）
    return {
        "meta_rule": {
            "content": rule_row[0] if rule_row else "你是专业的企业知识助手，回答要准确、简洁、有依据。",
            "updated_at": rule_row[1] if rule_row else datetime.now().isoformat(),
            "conversation_count": rule_row[2] if rule_row else 0
        },
        "insights": insights_formatted,
        "facts": facts_flat,
        "short_term_count": session_count
    }
