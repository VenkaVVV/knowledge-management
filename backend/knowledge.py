"""
知识管理模块 - 文档解析、切块、检索、存储
"""
import os
import sqlite3
import json
import threading
from uuid import uuid4
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import re
import httpx

from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
import uuid
from rank_bm25 import BM25Okapi
import jieba

from qdrant_client_singleton import get_qdrant_client

qdrant_client = get_qdrant_client()

VECTOR_SIZE = 1024  # bge-m3的维度

# Qdrant 线程锁
_qdrant_lock = threading.Lock()

# 硅基流动 Embedding 函数 - 通过本地HTTP服务
from config import CONFIG
import requests

from typing import Any, List

class SiliconFlowEmbeddingFunction:
    
    def __init__(self, api_base: str | None = None, model: str | None = None, api_key: str | None = None):
        self.api_base = (api_base or CONFIG.get("embedding_base_url", "http://localhost:9001/v1")).rstrip('/')
        self.model = model or CONFIG.get("embedding_model", "BAAI/bge-m3")
        self.api_key = api_key or CONFIG.get("embedding_api_key", "dummy")
    
    def __call__(self, input: Any) -> List[List[float]]:
        """
        调用本地 embedding 接口
        
        Args:
            input: 文本列表
            
        Returns:
            embedding 向量列表
        """
        if isinstance(input, str):
            input = [input]
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        payload = {
            "model": self.model,
            "input": input
        }
        
        try:
            response = requests.post(
                f"{self.api_base}/embeddings",
                headers=headers,
                json=payload,
                timeout=60
            )
            response.raise_for_status()
            
            data = response.json()
            
            # 提取 embedding 向量
            if "data" in data:
                # OpenAI 格式
                embeddings = [item["embedding"] for item in data["data"]]
            else:
                # 尝试其他格式
                embeddings = data.get("embeddings", [])
            
            return embeddings
            
        except Exception as e:
            print(f"Embedding API 调用失败: {e}")
            # 返回零向量作为 fallback
            return [[0.0] * 1024 for _ in input]  # 假设 1024 维

# SQLite 数据库路径 - 使用相对于当前文件的绝对路径
_base_dir = os.path.dirname(os.path.abspath(__file__))
SQLITE_PATH = os.getenv("SQLITE_PATH", os.path.join(_base_dir, "data", "memory.db"))

def _get_embeddings(texts: List[str]) -> List[List[float]]:
    """手动调用embedding API，带超时控制"""
    from config import CONFIG
    import requests
    from client_factory import get_embedding_headers

    api_base = CONFIG.get("embedding_base_url", "").rstrip('/')
    model = CONFIG.get("embedding_model", "BAAI/bge-m3")

    print(f"[embedding] 请求地址：{api_base}/embeddings，文本数量：{len(texts)}")

    # 分批处理，每批5个
    all_embeddings = []
    batch_size = 5
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        print(f"[embedding] 处理batch {i}-{i+len(batch)}...")
        try:
            resp = requests.post(
                f"{api_base}/embeddings",
                headers=get_embedding_headers(),
                json={"model": model, "input": batch},
                timeout=30  # 30秒超时
            )
            resp.raise_for_status()
            data = resp.json()
            embeddings = [item["embedding"] for item in data["data"]]
            all_embeddings.extend(embeddings)
            print(f"[embedding] batch完成，维度：{len(embeddings[0])}")
        except requests.Timeout:
            print(f"[embedding] 超时！检查proxy和硅基流动连接")
            raise RuntimeError("Embedding API超时，请检查网络连接")
        except Exception as e:
            print(f"[embedding] 失败：{e}")
            raise
    
    return all_embeddings

def init_sqlite():
    """初始化SQLite数据库和表"""
    conn = sqlite3.connect(SQLITE_PATH)
    cursor = conn.cursor()
    
    # 文档统计表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS doc_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT UNIQUE,
            chunk_count INTEGER DEFAULT 0,
            question_count INTEGER DEFAULT 0,
            hit_count INTEGER DEFAULT 0,
            uploaded_at TEXT
        )
    """)
    
    # SOP注册表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sop_registry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            process_name TEXT,
            filename TEXT,
            applicable_role TEXT,
            effective_date TEXT,
            last_verified TEXT,
            verify_count INTEGER DEFAULT 0,
            version INTEGER DEFAULT 1,
            status TEXT DEFAULT 'latest',
            uploaded_at TEXT,
            needs_review INTEGER DEFAULT 0
        )
    """)
    
    # 添加 needs_review 列（如果表已存在但没有该列）
    try:
        cursor.execute("ALTER TABLE sop_registry ADD COLUMN needs_review INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    
    # 查询日志表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS query_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            query TEXT,
            hit_knowledge INTEGER DEFAULT 0,
            top_score REAL,
            returned_chunks_count INTEGER DEFAULT 0,
            session_id TEXT,
            created_at TEXT
        )
    """)
    
    try:
        cursor.execute("ALTER TABLE query_log ADD COLUMN returned_chunks_count INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    
    try:
        cursor.execute("ALTER TABLE query_log ADD COLUMN session_id TEXT")
    except sqlite3.OperationalError:
        pass
    
    conn.commit()
    conn.close()
    print("SQLite数据库初始化完成")


def log_query(user_id: str, query: str, chunks: List[dict], session_id: Optional[str] = None):
    """
    记录查询日志
    
    Args:
        user_id: 用户ID
        query: 查询文本
        chunks: 检索结果chunk列表
        session_id: 会话ID（可选）
    """
    hit_knowledge = len(chunks) > 0 and chunks[0]["score"] > 0.75
    top_score = chunks[0]["score"] if len(chunks) > 0 else 0.0
    returned_chunks_count = len(chunks)
    now = datetime.now().isoformat()
    
    try:
        conn = sqlite3.connect(SQLITE_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO query_log (user_id, query, hit_knowledge, top_score, returned_chunks_count, session_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, query, 1 if hit_knowledge else 0, top_score, returned_chunks_count, session_id, now))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"记录查询日志失败: {e}")

def parse_document(file_path: str) -> List[str]:
    """
    解析文档内容
    
    Args:
        file_path: 文件路径
        
    Returns:
        文本内容列表（PDF为每页内容）
    """
    import pdfplumber
    from docx import Document
    
    ext = os.path.splitext(file_path)[1].lower()
    
    if ext == '.pdf':
        texts = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text and text.strip():
                    texts.append(text.strip())
        return texts
        
    elif ext == '.docx':
        doc = Document(file_path)
        full_text = []
        for para in doc.paragraphs:
            if para.text.strip():
                full_text.append(para.text)
        # 合并为单个字符串返回
        return ['\n'.join(full_text)]
        
    elif ext == '.txt':
        with open(file_path, 'r', encoding='utf-8') as f:
            return [f.read()]
            
    else:
        raise ValueError(f"不支持的文件格式: {ext}")

def chunk_text(texts: List[str], source_type: str = "knowledge") -> List[Dict]:
    """
    将文本切块
    
    Args:
        texts: 文本列表
        source_type: 文档类型 (knowledge/sop)
        
    Returns:
        chunk列表，每个chunk包含content和chunk_id
    """
    chunks = []
    
    if source_type == "sop":
        # SOP文档按步骤切块
        step_patterns = [
            r'^第[一二三四五六七八九十\d]+步',
            r'^\d+\.',
            r'^Step\d+',
            r'^【第\d+步】'
        ]
        
        for text in texts:
            lines = text.split('\n')
            current_step = None
            current_content = []
            step_num = 0
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                    
                # 检查是否是步骤标识
                is_step = False
                for pattern in step_patterns:
                    if re.match(pattern, line):
                        is_step = True
                        step_num += 1
                        break
                
                if is_step:
                    # 保存上一个步骤
                    if current_step:
                        chunks.append({
                            "content": f"第{step_num-1}步\n" + '\n'.join(current_content),
                            "chunk_id": str(uuid4())
                        })
                    current_content = [line]
                else:
                    current_content.append(line)
            
            # 保存最后一个步骤
            if current_content:
                chunks.append({
                    "content": f"第{step_num}步\n" + '\n'.join(current_content),
                    "chunk_id": str(uuid4())
                })
    else:
        # 普通知识文档用RecursiveCharacterTextSplitter
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=100,
            length_function=len,
            separators=["\n\n", "\n", "。", ". ", " ", ""]
        )
        
        full_text = "\n".join(texts)
        split_chunks = text_splitter.split_text(full_text)
        
        for chunk_text in split_chunks:
            chunks.append({
                "content": chunk_text,
                "chunk_id": str(uuid4())
            })
    
    return chunks

def generate_questions(chunks: List[Dict], source_type: str, filename: str):
    """
    批量生成问题索引

    Args:
        chunks: chunk列表
        source_type: 文档类型
        filename: 文件名
    """
    from client_factory import default_openai_client

    client = default_openai_client
    
    # 每次取5个chunk
    batch_size = 5
    total_questions = 0
    
    for i in range(0, len(chunks), batch_size):
        batch_chunks = chunks[i:i+batch_size]
        
        # 构建prompt
        system_msg = "你是企业知识助手，负责生成检索问题"
        
        operation_prefix = ""
        if source_type == "sop":
            operation_prefix = "问题应以'怎么''如何''流程''步骤'等操作性词汇开头。"
        
        chunks_json = json.dumps([{"index": idx, "content": c["content"][:500]} for idx, c in enumerate(batch_chunks)])
        
        user_msg = f"""对以下每段文本，生成3个用户可能提问的问题。
{operation_prefix}
以JSON数组返回：
[{{"chunk_index":0,"questions":["问题1","问题2","问题3"]}},...]

文本内容：{chunks_json}"""
        
        try:
            response = client.chat.completions.create(
                model=CONFIG["chat_model"],
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg}
                ],
                temperature=0.7
            )
            
            raw_content = response.choices[0].message.content
            print(f"[questions] LLM原始返回：{raw_content[:200]}")

            if not raw_content or not raw_content.strip():
                print(f"[questions] LLM返回空内容，跳过本batch")
                continue

            # 处理markdown代码块
            content = raw_content.strip()
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            # 找到JSON数组部分
            start = content.find("[")
            end = content.rfind("]") + 1
            if start == -1 or end == 0:
                print(f"[questions] 未找到JSON数组，原始内容：{content[:200]}")
                continue

            content = content[start:end]
            print(f"[questions] 解析内容：{content[:200]}")

            try:
                question_list = json.loads(content)
                if not isinstance(question_list, list):
                    question_list = []
            except Exception as parse_err:
                print(f"[questions] JSON解析失败：{parse_err}，内容：{content[:200]}")
                continue
            
            # 存储到Qdrant
            points = []
            
            for item in question_list:
                chunk_idx = item.get("chunk_index", 0)
                questions = item.get("questions", [])
                
                if chunk_idx < len(batch_chunks):
                    chunk_id = batch_chunks[chunk_idx]["chunk_id"]
                    
                    for q in questions:
                        points.append(PointStruct(
                            id=str(uuid4()),
                            vector=[0.0] * VECTOR_SIZE,  # 占位，后面计算
                            payload={
                                "content": q,
                                "type": "question",
                                "source_chunk_id": chunk_id,
                                "source_file": filename,
                                "source_type": source_type
                            }
                        ))
                        total_questions += 1
            
            # 批量计算embedding并写入
            if points:
                print(f"[generate_questions] 计算 {len(points)} 个问题的embedding...")
                all_questions = [p.payload["content"] for p in points]
                question_embeddings = _get_embeddings(all_questions)
                
                # 更新vector
                for i, emb in enumerate(question_embeddings):
                    points[i].vector = emb
                
                print(f"[generate_questions] 等待Qdrant写入锁...")
                with _qdrant_lock:
                    print(f"[generate_questions] 获得锁，写入中...")
                    qdrant_client.upsert(
                        collection_name="questions",
                        points=points
                    )
                    print(f"[generate_questions] 写入完成")
                        
        except Exception as e:
            print(f"生成问题失败 (batch {i}): {e}")
            continue
    
    # 更新doc_stats表中的question_count
    if total_questions > 0:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                conn = sqlite3.connect(SQLITE_PATH)
                cursor = conn.cursor()
                
                # 先检查记录是否存在
                cursor.execute("SELECT COUNT(*) FROM doc_stats WHERE filename = ?", (filename,))
                count = cursor.fetchone()[0]
                
                if count == 0:
                    print(f"[generate_questions] 警告: doc_stats 中不存在 filename={filename} 的记录")
                    conn.close()
                    break
                
                # 更新 question_count
                cursor.execute(
                    "UPDATE doc_stats SET question_count = ? WHERE filename = ?",
                    (total_questions, filename)
                )
                conn.commit()
                
                # 验证更新是否成功
                cursor.execute("SELECT question_count FROM doc_stats WHERE filename = ?", (filename,))
                updated_count = cursor.fetchone()[0]
                
                conn.close()
                
                if updated_count == total_questions:
                    print(f"[generate_questions] 成功更新 {filename} 的 question_count 为 {total_questions}")
                    break
                else:
                    print(f"[generate_questions] 更新验证失败: 期望 {total_questions}, 实际 {updated_count}")
                    if attempt < max_retries - 1:
                        import time
                        time.sleep(0.5)
                        
            except Exception as e:
                print(f"[generate_questions] 第 {attempt + 1} 次尝试更新 question_count 失败: {e}")
                import traceback
                traceback.print_exc()
                if attempt < max_retries - 1:
                    import time
                    time.sleep(0.5)
    
    print(f"共生成 {total_questions} 个问题")
    return total_questions

def save_to_knowledge_base(chunks: List[Dict], filename: str,
                          source_type: str = "knowledge",
                          process_name: str = None,
                          applicable_role: str = None,
                          effective_date: str = None,
                          generate_questions_flag: bool = True):
    """
    保存文档到知识库
    
    Args:
        chunks: chunk列表
        filename: 文件名
        source_type: 类型 (knowledge/sop)
        process_name: SOP流程名
        applicable_role: 适用角色
        effective_date: 生效日期
        generate_questions_flag: 是否生成问题索引
    """
    print(f"[1] 开始入库，文件：{filename}，chunks数量：{len(chunks)}")
    
    # 确定collection名称
    collection_name = "sop_library" if source_type == "sop" else "knowledge"
    
    print(f"[2] collection获取完成：{collection_name}")
    
    now = datetime.now().isoformat()
    documents = [c["content"] for c in chunks]
    metadatas = [{"source_file": filename, "source_type": source_type,
                   "created_at": now, "hit_count": 0,
                   "process_name": process_name or "",
                   "applicable_role": applicable_role or "",
                   "effective_date": effective_date or "",
                   "last_verified": now} for c in chunks]
    ids = [c["chunk_id"] for c in chunks]
    
    print(f"[3] 开始计算embedding...")
    embeddings = _get_embeddings(documents)
    print(f"[3] embedding完成，写入Qdrant...")
    
    points = [
        PointStruct(
            id=str(uuid.uuid4()),
            vector=embeddings[i],
            payload={**metadatas[i], "content": documents[i], "chunk_id": ids[i]}
        )
        for i in range(len(documents))
    ]
    
    qdrant_client.upsert(
        collection_name=collection_name,
        points=points
    )
    print(f"[3] Qdrant写入完成")
    
    print(f"[4] Qdrant写入完成，开始写SQLite...")
    
    # 写入SQLite
    conn = sqlite3.connect(SQLITE_PATH)
    cursor = conn.cursor()
    
    # 插入或更新doc_stats
    cursor.execute("""
        INSERT INTO doc_stats (filename, chunk_count, uploaded_at)
        VALUES (?, ?, ?)
        ON CONFLICT(filename) DO UPDATE SET
            chunk_count = ?,
            uploaded_at = ?
    """, (filename, len(chunks), now, len(chunks), now))
    
    # 如果是SOP，写入sop_registry
    if source_type == "sop" and process_name:
        # 检查是否已有同名流程
        cursor.execute("""
            SELECT id, version FROM sop_registry 
            WHERE process_name = ? AND status = 'latest'
        """, (process_name,))
        
        existing = cursor.fetchone()
        new_version = 1
        
        if existing:
            old_id, old_version = existing
            new_version = old_version + 1
            # 更新旧记录状态
            cursor.execute("""
                UPDATE sop_registry 
                SET status = 'archived' 
                WHERE id = ?
            """, (old_id,))
        
        # 插入新记录
        cursor.execute("""
            INSERT INTO sop_registry 
            (process_name, filename, applicable_role, effective_date, 
             last_verified, version, status, uploaded_at)
            VALUES (?, ?, ?, ?, ?, ?, 'latest', ?)
        """, (process_name, filename, applicable_role or '', 
                effective_date or '', now, new_version, now))
    
    conn.commit()
    conn.close()
    
    print(f"[5] 全部完成，文件{filename}入库成功")

# 全局BM25索引
_bm25_index = None
_bm25_chunk_ids = []
_bm25_documents = []

def _build_bm25_index():
    """从Qdrant构建BM25索引"""
    global _bm25_index, _bm25_chunk_ids, _bm25_documents
    
    # 获取所有collection
    collections = ["knowledge", "sop_library"]
    all_documents = []
    all_ids = []
    
    for coll_name in collections:
        try:
            with _qdrant_lock:
                results = qdrant_client.scroll(
                    collection_name=coll_name,
                    limit=10000,
                    with_payload=True,
                    with_vectors=False
                )
            if results and results[0]:
                for point in results[0]:
                    all_ids.append(point.payload.get("chunk_id", str(point.id)))
                    all_documents.append(point.payload.get("content", ""))
        except Exception as e:
            print(f"获取collection {coll_name}失败: {e}")
            continue
    
    if not all_documents:
        _bm25_index = None
        return
    
    # 分词
    tokenized_docs = []
    for doc in all_documents:
        # 使用jieba分词
        tokens = list(jieba.cut(doc))
        tokenized_docs.append(tokens)
    
    _bm25_index = BM25Okapi(tokenized_docs)
    _bm25_chunk_ids = all_ids
    _bm25_documents = all_documents
    
    print(f"BM25索引构建完成，共 {len(all_documents)} 个文档")

def search_knowledge(query: str, top_k: int = 5,
                    source_type: str = "all") -> List[Dict]:
    """
    混合检索知识库
    
    Args:
        query: 查询文本
        top_k: 返回结果数量
        source_type: 检索范围 (all/knowledge/sop)
        
    Returns:
        检索结果列表
    """
    # 意图判断
    trigger_words = ["怎么", "如何", "流程", "步骤", "操作", "处理", "办理", "需要什么"]
    is_sop_query = any(w in query for w in trigger_words)
    
    # 确定检索范围
    collections_to_search = []
    if source_type == "all":
        if is_sop_query:
            collections_to_search = [("sop_library", 10), ("knowledge", 5)]
        else:
            collections_to_search = [("knowledge", 10)]
    elif source_type == "sop":
        collections_to_search = [("sop_library", top_k)]
    else:
        collections_to_search = [("knowledge", top_k)]
    
    # 语义检索（Qdrant）
    semantic_results = []
    for coll_name, k in collections_to_search:
        try:
            query_embedding = _get_embeddings([query])[0]
            results = qdrant_client.query_points(
                collection_name=coll_name,
                query=query_embedding,
                limit=k,
                with_payload=True
            ).points
            
            # 结果格式转换
            for r in results:
                semantic_results.append({
                    "chunk_id": r.payload.get("chunk_id", ""),
                    "content": r.payload.get("content", ""),
                    "score": r.score,
                    "source_file": r.payload.get("source_file", ""),
                    "source_type": r.payload.get("source_type", "knowledge"),
                    "process_name": r.payload.get("process_name"),
                    "retrieval_type": "semantic"
                })
        except Exception as e:
            print(f"语义检索失败 ({coll_name}): {e}")
            continue
    
    # BM25关键词检索
    global _bm25_index, _bm25_chunk_ids
    
    # 如果索引未构建，先构建
    if _bm25_index is None:
        _build_bm25_index()
    
    bm25_results = []
    if _bm25_index:
        try:
            # 分词
            query_tokens = list(jieba.cut(query))
            
            # 获取BM25分数
            bm25_scores = _bm25_index.get_scores(query_tokens)
            
            # 排序并获取top_k
            top_indices = sorted(range(len(bm25_scores)), 
                               key=lambda i: bm25_scores[i], 
                               reverse=True)[:top_k*2]  # 多取一些用于融合
            
            for idx in top_indices:
                if idx < len(_bm25_chunk_ids):
                    chunk_id = _bm25_chunk_ids[idx]
                    score = bm25_scores[idx] / max(bm25_scores) if max(bm25_scores) > 0 else 0
                    
                    # 获取文档内容（需要查询Qdrant）
                    try:
                        # 尝试从已有结果中找，或查询Qdrant
                        found = False
                        
                        # 由于我们已经在_build_bm25_index中保存了文档内容
                        # 直接使用_bm25_documents和_bm25_chunk_ids
                        doc_idx = None
                        for idx, stored_id in enumerate(_bm25_chunk_ids):
                            if stored_id == chunk_id and idx < len(_bm25_documents):
                                doc_idx = idx
                                break
                        
                        if doc_idx is not None:
                            # 从语义检索结果中查找metadata
                            doc_metadata = None
                            for r in semantic_results:
                                if r["chunk_id"] == chunk_id:
                                    doc_metadata = r
                                    break
                            
                            if doc_metadata:
                                bm25_results.append({
                                    "chunk_id": chunk_id,
                                    "content": _bm25_documents[doc_idx],
                                    "score": score,
                                    "source_file": doc_metadata["source_file"],
                                    "source_type": doc_metadata["source_type"],
                                    "process_name": doc_metadata.get("process_name"),
                                    "retrieval_type": "bm25"
                                })
                            else:
                                bm25_results.append({
                                    "chunk_id": chunk_id,
                                    "content": _bm25_documents[doc_idx],
                                    "score": score,
                                    "source_file": "",
                                    "source_type": "knowledge",
                                    "retrieval_type": "bm25"
                                })
                            found = True
                        
                        if not found:
                            # 记录存在但查不到详情
                            bm25_results.append({
                                "chunk_id": chunk_id,
                                "content": "",
                                "score": score,
                                "source_file": "",
                                "source_type": "knowledge",
                                "retrieval_type": "bm25"
                            })
                    except Exception as e:
                        print(f"获取BM25文档详情失败: {e}")
                        continue
                        
        except Exception as e:
            print(f"BM25检索失败: {e}")
    
    # RRF融合
    def rrf_score(rank: int, k: int = 60) -> float:
        """RRF分数计算"""
        return 1.0 / (k + rank)
    
    # 合并所有结果
    all_results = {}
    
    # 处理语义检索结果
    for rank, result in enumerate(sorted(semantic_results, key=lambda x: x["score"], reverse=True)):
        chunk_id = result["chunk_id"]
        if chunk_id not in all_results:
            all_results[chunk_id] = {
                "content": result["content"],
                "source_file": result["source_file"],
                "source_type": result["source_type"],
                "process_name": result.get("process_name"),
                "rrf_score": 0.0,
                "semantic_rank": rank + 1,
                "bm25_rank": None
            }
        all_results[chunk_id]["rrf_score"] += rrf_score(rank + 1)
    
    # 处理BM25结果
    for rank, result in enumerate(sorted(bm25_results, key=lambda x: x["score"], reverse=True)):
        chunk_id = result["chunk_id"]
        if chunk_id not in all_results:
            all_results[chunk_id] = {
                "content": result["content"],
                "source_file": result["source_file"],
                "source_type": result["source_type"],
                "process_name": result.get("process_name"),
                "rrf_score": 0.0,
                "semantic_rank": None,
                "bm25_rank": rank + 1
            }
        all_results[chunk_id]["rrf_score"] += rrf_score(rank + 1)
        all_results[chunk_id]["bm25_rank"] = rank + 1
    
    # 按RRF分数排序并返回top_k
    sorted_results = sorted(all_results.items(), key=lambda x: x[1]["rrf_score"], reverse=True)
    
    final_results = []
    for chunk_id, data in sorted_results[:top_k]:
        final_results.append({
            "content": data["content"],
            "source_file": data["source_file"],
            "source_type": data["source_type"],
            "process_name": data.get("process_name"),
            "score": data["rrf_score"]
        })
        
        # 更新hit_count
        _update_hit_count(data["source_file"])
    
    return final_results

def _update_hit_count(filename: str):
    """更新文档命中次数"""
    try:
        conn = sqlite3.connect(SQLITE_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE doc_stats SET hit_count = hit_count + 1 WHERE filename = ?",
            (filename,)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"更新hit_count失败: {e}")

def delete_document(filename: str):
    """
    删除文档及其相关问题
    
    Args:
        filename: 文件名
    """
    from qdrant_client.models import Filter, FieldCondition, MatchValue
    
    for coll_name in ["knowledge", "sop_library", "questions"]:
        qdrant_client.delete(
            collection_name=coll_name,
            points_selector=Filter(
                must=[FieldCondition(
                    key="source_file",
                    match=MatchValue(value=filename)
                )]
            )
        )
    
    # 从SQLite删除
    conn = sqlite3.connect(SQLITE_PATH)
    cursor = conn.cursor()
    
    # 删除doc_stats记录
    cursor.execute("DELETE FROM doc_stats WHERE filename = ?", (filename,))
    
    # 更新sop_registry状态
    cursor.execute(
        "UPDATE sop_registry SET status = 'deleted' WHERE filename = ?",
        (filename,)
    )
    
    conn.commit()
    conn.close()
    
    print(f"文档 {filename} 删除完成")

# 初始化SQLite
init_sqlite()