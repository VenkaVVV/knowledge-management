import os
import sqlite3
import json
import requests
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sklearn.cluster import KMeans
from sklearn.metrics.pairwise import euclidean_distances
from config import CONFIG

SQLITE_PATH = os.getenv("SQLITE_PATH", "./data/memory.db")


def init_db():
    conn = sqlite3.connect(SQLITE_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS query_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        query TEXT,
        hit_knowledge INTEGER,
        returned_chunks_count INTEGER,
        top_score REAL,
        session_id TEXT,
        created_at TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS answer_feedback(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        query TEXT,
        session_id TEXT,
        feedback_type TEXT,
        created_at TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS handled_queries(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        query TEXT,
        handled_at TEXT)""")
    # 盲区分析缓存表
    conn.execute("""CREATE TABLE IF NOT EXISTS blind_spot_cache(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        result_data TEXT NOT NULL,
        generated_at TEXT NOT NULL,
        query_count INTEGER DEFAULT 0
    )""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_query_log_user
        ON query_log(user_id, created_at)""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_answer_feedback_user
        ON answer_feedback(user_id, created_at)""")
    
    cursor = conn.execute("PRAGMA table_info(query_log)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'session_id' not in columns:
        conn.execute("ALTER TABLE query_log ADD COLUMN session_id TEXT")
    if 'returned_chunks_count' not in columns:
        conn.execute("ALTER TABLE query_log ADD COLUMN returned_chunks_count INTEGER DEFAULT 0")
    
    conn.commit()
    conn.close()


init_db()


def log_query(user_id: str, query: str, chunks: List[dict], session_id: Optional[str] = None):
    hit_knowledge = 1 if (len(chunks) > 0 and chunks[0]["score"] > 0.75) else 0
    returned_chunks_count = len(chunks)
    top_score = chunks[0]["score"] if chunks else 0.0
    conn = sqlite3.connect(SQLITE_PATH)
    conn.execute("""INSERT INTO query_log
        (user_id, query, hit_knowledge, returned_chunks_count, top_score, session_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (user_id, query, hit_knowledge, returned_chunks_count, top_score, session_id,
         datetime.now().isoformat()))
    conn.commit()
    conn.close()


def add_feedback(user_id: str, query: str, session_id: str, feedback_type: str):
    conn = sqlite3.connect(SQLITE_PATH)
    conn.execute("""INSERT INTO answer_feedback
        (user_id, query, session_id, feedback_type, created_at)
        VALUES (?, ?, ?, ?, ?)""",
        (user_id, query, session_id, feedback_type, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def log_feedback(user_id: str, query: str, session_id: str, feedback_type: str):
    conn = sqlite3.connect(SQLITE_PATH)
    
    # 1. 写入answer_feedback
    conn.execute("""
        INSERT INTO answer_feedback 
        (user_id, query, session_id, feedback_type, created_at)
        VALUES (?, ?, ?, ?, datetime('now'))
    """, (user_id, query, session_id, feedback_type))
    
    # 2. 根据feedback_type执行不同操作
    if feedback_type == "not_answered":
        # 强制把最近一条同query记录的hit_knowledge改为0
        conn.execute("""
            UPDATE query_log SET hit_knowledge = 0
            WHERE query = ? AND user_id = ?
            AND id = (
                SELECT id FROM query_log 
                WHERE query = ? AND user_id = ?
                ORDER BY created_at DESC LIMIT 1
            )
        """, (query, user_id, query, user_id))
    
    if feedback_type in ("not_accurate", "outdated"):
        # 找到该query命中的SOP，标记needs_review
        # 注意：由于query_log表没有source_file列，暂时跳过该功能
        pass
    
    conn.commit()
    conn.close()
    
    # 返回操作结果供前端感知
    result = {"feedback_type": feedback_type}
    
    if feedback_type == "not_accurate":
        result["message"] = "已记录，对应知识文档将被标记待复核"
        result["color"] = "blue"
    elif feedback_type == "outdated":
        result["message"] = "已标记，对应SOP将进入核验队列"
        result["color"] = "yellow"
        result["sop_affected"] = True
    elif feedback_type == "not_answered":
        result["message"] = "已记录，该问题将纳入盲区分析"
        result["color"] = "orange"
        result["trigger_blind_spot"] = True
    
    return result


def add_handled_query(query: str):
    conn = sqlite3.connect(SQLITE_PATH)
    conn.execute("""INSERT INTO handled_queries
        (query, handled_at)
        VALUES (?, ?)""",
        (query, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_query_stats(user_id: Optional[str] = None, days: int = 30) -> Dict[str, Any]:
    conn = sqlite3.connect(SQLITE_PATH)
    if user_id:
        rows = conn.execute("""
            SELECT COUNT(*), SUM(hit_knowledge), AVG(returned_chunks_count), AVG(top_score)
            FROM query_log
            WHERE user_id = ? AND created_at > datetime('now', '-' || ? || ' days')
        """, (user_id, days)).fetchone()
    else:
        rows = conn.execute("""
            SELECT COUNT(*), SUM(hit_knowledge), AVG(returned_chunks_count), AVG(top_score)
            FROM query_log
            WHERE created_at > datetime('now', '-' || ? || ' days')
        """, (days,)).fetchone()
    conn.close()
    total_queries = rows[0] if rows[0] else 0
    hit_count = rows[1] if rows[1] else 0
    avg_chunks = rows[2] if rows[2] else 0
    avg_score = rows[3] if rows[3] else 0
    hit_rate = hit_count / total_queries if total_queries > 0 else 0
    return {
        "total_queries": total_queries,
        "hit_count": hit_count,
        "hit_rate": hit_rate,
        "avg_chunks": avg_chunks,
        "avg_score": avg_score
    }


def get_feedback_stats(user_id: Optional[str] = None, days: int = 30) -> Dict[str, Any]:
    conn = sqlite3.connect(SQLITE_PATH)
    if user_id:
        rows = conn.execute("""
            SELECT feedback_type, COUNT(*)
            FROM answer_feedback
            WHERE user_id = ? AND created_at > datetime('now', '-' || ? || ' days')
            GROUP BY feedback_type
        """, (user_id, days)).fetchall()
    else:
        rows = conn.execute("""
            SELECT feedback_type, COUNT(*)
            FROM answer_feedback
            WHERE created_at > datetime('now', '-' || ? || ' days')
            GROUP BY feedback_type
        """, (days,)).fetchall()
    conn.close()
    stats = {}
    total = 0
    for feedback_type, count in rows:
        stats[feedback_type] = count
        total += count
    return {
        "total_feedback": total,
        "by_type": stats
    }


def get_recent_queries(user_id: Optional[str] = None, limit: int = 20) -> List[Dict]:
    conn = sqlite3.connect(SQLITE_PATH)
    if user_id:
        rows = conn.execute("""
            SELECT user_id, query, hit_knowledge, returned_chunks_count, top_score, created_at
            FROM query_log
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (user_id, limit)).fetchall()
    else:
        rows = conn.execute("""
            SELECT user_id, query, hit_knowledge, returned_chunks_count, top_score, created_at
            FROM query_log
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
    conn.close()
    return [
        {
            "user_id": r[0],
            "query": r[1],
            "hit_knowledge": bool(r[2]),
            "returned_chunks_count": r[3],
            "top_score": r[4],
            "created_at": r[5]
        }
        for r in rows
    ]


def get_unhandled_queries(limit: int = 100) -> List[str]:
    conn = sqlite3.connect(SQLITE_PATH)
    handled = set(row[0] for row in conn.execute("SELECT query FROM handled_queries").fetchall())
    all_queries = conn.execute("""
        SELECT DISTINCT query FROM query_log
        ORDER BY created_at DESC
        LIMIT ?
    """, (limit + len(handled),)).fetchall()
    conn.close()
    unhandled = []
    for row in all_queries:
        query = row[0]
        if query not in handled and len(unhandled) < limit:
            unhandled.append(query)
    return unhandled


def get_health_stats() -> Dict[str, Any]:
    """
    获取知识健康度统计
    
    Returns:
        包含各项统计指标的字典
    """
    conn = sqlite3.connect(SQLITE_PATH)
    
    total_docs = conn.execute("SELECT COUNT(*) FROM doc_stats").fetchone()[0] or 0
    
    total_sop = conn.execute("""
        SELECT COUNT(*) FROM sop_registry WHERE status = 'latest'
    """).fetchone()[0] or 0
    
    total_7d = conn.execute("SELECT COUNT(*) FROM query_log WHERE created_at > datetime('now','-7 days')").fetchone()[0] or 0
    hit_7d = conn.execute("SELECT COUNT(*) FROM query_log WHERE created_at > datetime('now','-7 days') AND hit_knowledge=1").fetchone()[0] or 0
    hit_rate_7d = round(hit_7d / total_7d, 2) if total_7d > 0 else 0.0
    
    total_30d = conn.execute("SELECT COUNT(*) FROM query_log WHERE created_at > datetime('now','-30 days')").fetchone()[0] or 0
    hit_30d = conn.execute("SELECT COUNT(*) FROM query_log WHERE created_at > datetime('now','-30 days') AND hit_knowledge=1").fetchone()[0] or 0
    hit_rate_30d = round(hit_30d / total_30d, 2) if total_30d > 0 else 0.0
    
    total_chunks = conn.execute("SELECT SUM(chunk_count) FROM doc_stats").fetchone()[0] or 0
    total_questions = conn.execute("SELECT SUM(question_count) FROM doc_stats").fetchone()[0] or 0
    
    total_queries_30d = total_30d
    blind_spot_count = total_queries_30d - hit_30d
    
    top_used_docs = conn.execute("""
        SELECT id, filename, chunk_count, question_count, hit_count, uploaded_at
        FROM doc_stats
        ORDER BY hit_count DESC
        LIMIT 5
    """).fetchall()
    top_used_docs_list = [
        {
            "id": r[0],
            "filename": r[1],
            "chunk_count": r[2] or 0,
            "question_count": r[3] or 0,
            "hit_count": r[4] or 0,
            "uploaded_at": r[5]
        }
        for r in top_used_docs
    ]
    
    unused_docs = conn.execute("""
        SELECT id, filename, chunk_count, question_count, hit_count, uploaded_at
        FROM doc_stats
        WHERE hit_count = 0
    """).fetchall()
    unused_docs_list = [
        {
            "id": r[0],
            "filename": r[1],
            "chunk_count": r[2] or 0,
            "question_count": r[3] or 0,
            "hit_count": r[4] or 0,
            "uploaded_at": r[5]
        }
        for r in unused_docs
    ]
    
    sop_total = conn.execute("SELECT COUNT(*) FROM sop_registry").fetchone()[0] or 0
    sop_needs_review = conn.execute("""
        SELECT COUNT(*) FROM sop_registry 
        WHERE last_verified < datetime('now', '-90 days')
    """).fetchone()[0] or 0
    sop_overdue = conn.execute("""
        SELECT COUNT(*) FROM sop_registry 
        WHERE last_verified < datetime('now', '-180 days')
    """).fetchone()[0] or 0
    
    conn.close()
    
    return {
        "total_docs": total_docs,
        "total_sop": total_sop,
        "total_chunks": total_chunks,
        "total_questions": total_questions,
        "hit_rate_7d": hit_rate_7d,
        "hit_rate_30d": hit_rate_30d,
        "total_queries_30d": total_queries_30d,
        "blind_spot_count": blind_spot_count,
        "top_used_docs": top_used_docs_list,
        "unused_docs": unused_docs_list,
        "sop_stats": {
            "total": sop_total,
            "needs_review": sop_needs_review,
            "overdue": sop_overdue
        }
    }


def _get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """批量获取embedding向量"""
    api_base = CONFIG.get("embedding_base_url", "").rstrip('/')
    api_key = CONFIG.get("embedding_api_key", "dummy")
    model = CONFIG.get("embedding_model", "BAAI/bge-m3")
    
    from client_factory import get_embedding_headers
    headers = get_embedding_headers()
    
    payload = {
        "model": model,
        "input": texts
    }
    
    try:
        response = requests.post(
            f"{api_base}/embeddings",
            headers=headers,
            json=payload,
            timeout=60
        )
        response.raise_for_status()
        data = response.json()
        embeddings = [item["embedding"] for item in data["data"]]
        return embeddings
    except Exception as e:
        print(f"Embedding API 调用失败: {e}")
        return [[0.0] * 1024 for _ in texts]


def _call_llm_for_clustering(representative_queries: List[str]) -> Dict[str, str]:
    """调用LLM分析聚类并返回分类结果"""
    prompt = f"""以下是用户频繁查询但未被知识库覆盖的问题：
{chr(10).join(f'- {q}' for q in representative_queries)}

请：
1. 判断类型：knowledge（事实性）或sop（操作性）
2. 用一句话总结知识缺口
3. 给出具体补充建议

返回JSON：
{{"type":"knowledge/sop",
 "summary":"...",
 "suggestion":"建议补充：..."}}
"""
    
    try:
        api_base = CONFIG.get("chat_base_url", "").rstrip('/')
        api_key = CONFIG.get("api_key", "dummy")
        model = CONFIG.get("chat_model", "Pro/deepseek-ai/DeepSeek-V3")
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3
        }
        
        response = requests.post(
            f"{api_base}/chat/completions",
            headers=headers,
            json=payload,
            timeout=60
        )
        response.raise_for_status()
        result = response.json()
        content = result["choices"][0]["message"]["content"].strip()
        
        if content.startswith("{"):
            return json.loads(content)
        else:
            return {
                "type": "knowledge",
                "summary": "知识缺口分析",
                "suggestion": "建议补充相关知识"
            }
    except Exception as e:
        print(f"LLM调用失败: {e}")
        return {
            "type": "knowledge",
            "summary": "知识缺口分析",
            "suggestion": "建议补充相关知识"
        }


def get_blind_spots(force_refresh: bool = False) -> Dict[str, Any]:
    """
    获取盲区聚类分析

    Args:
        force_refresh: 是否强制刷新缓存

    Returns:
        包含结果和生成时间的字典
    """
    conn = sqlite3.connect(SQLITE_PATH)

    # 先查询缓存
    if not force_refresh:
        cache_row = conn.execute("""
            SELECT result_data, generated_at, query_count
            FROM blind_spot_cache
            ORDER BY id DESC
            LIMIT 1
        """).fetchone()

        if cache_row:
            result_data = json.loads(cache_row[0])
            generated_at = cache_row[1]
            query_count = cache_row[2]
            print(f"[blind_spots] 使用缓存结果，生成时间: {generated_at}, 查询数: {query_count}")
            return {
                "data": result_data,
                "generated_at": generated_at,
                "query_count": query_count,
                "from_cache": True
            }
    
    # 先检查 hit_knowledge 的分布情况
    print("\n[blind_spots] 检查 hit_knowledge 分布:")
    dist_rows = conn.execute("""
        SELECT hit_knowledge, COUNT(*) 
        FROM query_log 
        GROUP BY hit_knowledge
    """).fetchall()
    for row in dist_rows:
        print(f"[blind_spots]   hit_knowledge={row[0]}, count={row[1]}")
    
    # 检查 query_log 表结构
    print("\n[blind_spots] query_log 表结构:")
    schema_rows = conn.execute("PRAGMA table_info(query_log)").fetchall()
    for row in schema_rows:
        print(f"[blind_spots]   {row}")
    
    # 查询未命中记录
    print("\n[blind_spots] 查询未命中记录...")
    handled_queries = set(row[0] for row in conn.execute("SELECT query FROM handled_queries").fetchall())
    print(f"[blind_spots] 已处理查询数: {len(handled_queries)}")
    
    rows = conn.execute("""
        SELECT DISTINCT query FROM query_log
        WHERE hit_knowledge = 0
        AND created_at > datetime('now', '-30 days')
        ORDER BY created_at DESC
        LIMIT 100
    """).fetchall()
    
    print(f"[blind_spots] 查询到未命中记录：{len(rows)}条")
    print(f"[blind_spots] 内容：{[r[0] for r in rows]}")
    
    queries = [row[0] for row in rows if row[0] not in handled_queries]
    print(f"[blind_spots] 过滤后查询数：{len(queries)}条")
    conn.close()
    
    if len(queries) < 2:  # 降低阈值到2条就可以分析
        print(f"[blind_spots] 不足2条，返回空")
        # 即使不足2条也返回统一格式
        generated_at = datetime.now().isoformat()
        return {
            "data": [],
            "generated_at": generated_at,
            "query_count": len(queries),
            "from_cache": False
        }
    
    print(f"[blind_spots] 开始聚类，共{len(queries)}条")
    
    embeddings = _get_embeddings_batch(queries)
    embeddings_array = np.array(embeddings)
    
    n_clusters = min(8, max(3, len(queries) // 5))
    
    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = kmeans.fit_predict(embeddings_array)
    
    results = []
    
    for cluster_id in range(n_clusters):
        cluster_indices = np.where(labels == cluster_id)[0]
        cluster_queries = [queries[i] for i in cluster_indices]
        cluster_embeddings = embeddings_array[cluster_indices]
        
        if len(cluster_embeddings) == 0:
            continue
        
        centroid = kmeans.cluster_centers_[cluster_id].reshape(1, -1)
        distances = euclidean_distances(cluster_embeddings, centroid).flatten()
        
        sorted_indices = np.argsort(distances)
        top_indices = sorted_indices[:min(3, len(sorted_indices))]
        representative_queries = [cluster_queries[i] for i in top_indices]
        
        llm_result = _call_llm_for_clustering(representative_queries)
        
        results.append({
            "cluster_id": cluster_id,
            "type": llm_result.get("type", "knowledge"),
            "summary": llm_result.get("summary", ""),
            "count": len(cluster_queries),
            "representative_queries": representative_queries,
            "suggestion": llm_result.get("suggestion", "")
        })
    
    print(f"[blind_spots] 聚类完成，共{len(results)}个聚类结果")
    for idx, r in enumerate(results):
        print(f"[blind_spots]   聚类{idx}: {r}")

    # 保存到缓存
    generated_at = datetime.now().isoformat()
    query_count = len(queries)
    try:
        conn = sqlite3.connect(SQLITE_PATH)
        conn.execute("""
            INSERT INTO blind_spot_cache (result_data, generated_at, query_count)
            VALUES (?, ?, ?)
        """, (json.dumps(results, ensure_ascii=False), generated_at, query_count))
        conn.commit()
        conn.close()
        print(f"[blind_spots] 结果已缓存，生成时间: {generated_at}")
    except Exception as e:
        print(f"[blind_spots] 缓存写入失败: {e}")

    return {
        "data": results,
        "generated_at": generated_at,
        "query_count": query_count,
        "from_cache": False
    }


def mark_handled(queries: List[str]):
    """
    批量标记查询为已处理
    
    Args:
        queries: 查询列表
    """
    conn = sqlite3.connect(SQLITE_PATH)
    now = datetime.now().isoformat()
    
    for query in queries:
        conn.execute("""
            INSERT OR IGNORE INTO handled_queries (query, handled_at)
            VALUES (?, ?)
        """, (query, now))
    
    conn.commit()
    conn.close()


def get_sop_list() -> List[Dict[str, Any]]:
    """
    获取SOP列表及健康状态
    
    Returns:
        SOP列表，包含健康状态
    """
    conn = sqlite3.connect(SQLITE_PATH)
    
    rows = conn.execute("""
        SELECT id, process_name, filename, applicable_role, effective_date,
               last_verified, verify_count, version, status, uploaded_at, needs_review
        FROM sop_registry
        WHERE status = 'latest'
        ORDER BY uploaded_at DESC
    """).fetchall()
    
    result = []
    now = datetime.now()
    
    for row in rows:
        last_verified_str = row[5]
        days_since_verified = 0
        
        if last_verified_str:
            try:
                last_verified = datetime.fromisoformat(last_verified_str)
                days_since_verified = (now - last_verified).days
            except (ValueError, TypeError):
                days_since_verified = 0
        
        if days_since_verified < 90:
            health = "good"
        elif 90 <= days_since_verified < 180:
            health = "warning"
        else:
            health = "overdue"
        
        result.append({
            "id": row[0],
            "process_name": row[1],
            "filename": row[2],
            "applicable_role": row[3],
            "effective_date": row[4],
            "last_verified": row[5],
            "verify_count": row[6],
            "version": row[7],
            "status": row[8],
            "uploaded_at": row[9],
            "needs_review": bool(row[10]),
            "days_since_verified": days_since_verified,
            "health": health
        })
    
    conn.close()
    return result


def verify_sop(sop_id: int, action: str):
    """
    SOP核验操作
    
    Args:
        sop_id: SOP ID
        action: "confirm" 或 "update"
    """
    conn = sqlite3.connect(SQLITE_PATH)
    now = datetime.now().isoformat()
    
    if action == "confirm":
        conn.execute("""
            UPDATE sop_registry
            SET last_verified = ?, verify_count = verify_count + 1, needs_review = 0
            WHERE id = ?
        """, (now, sop_id))
    elif action == "update":
        conn.execute("""
            UPDATE sop_registry
            SET needs_review = 0
            WHERE id = ?
        """, (sop_id,))
    
    conn.commit()
    conn.close()

def check_sop_staleness(sop_id: int) -> dict:
    """
    AI比对SOP是否可能过时
    查找知识库中比该SOP更新的相关文档
    """
    from knowledge import search_knowledge
    import sqlite3
    import requests
    from config import CONFIG
    from datetime import datetime
    
    conn = sqlite3.connect(SQLITE_PATH)
    sop = conn.execute("""
        SELECT process_name, filename, last_verified, uploaded_at
        FROM sop_registry WHERE id=? AND status='latest'
    """, (sop_id,)).fetchone()
    conn.close()
    
    if not sop:
        return {"error": "SOP不存在"}
    
    process_name, filename, last_verified, uploaded_at = sop
    
    # 用流程名搜索相关知识片段
    chunks = search_knowledge(process_name, top_k=5)
    if not chunks:
        return {
            "sop_id": sop_id,
            "process_name": process_name,
            "risk": "low",
            "message": "知识库中未找到相关文档，无法比对"
        }
    
    # 过滤出比SOP更新的文档
    newer_chunks = [c for c in chunks if c.get("source_file") != filename]
    
    if not newer_chunks:
        return {
            "sop_id": sop_id,
            "process_name": process_name,
            "risk": "low",
            "message": "未发现相关的更新文档"
        }
    
    knowledge_text = "\n\n".join([
        f"[来源：{c['source_file']}]\n{c['content'][:300]}"
        for c in newer_chunks[:3]
    ])
    
    try:
        resp = requests.post(
            f"{CONFIG['chat_base_url']}/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {CONFIG['api_key']}",
                "Accept-Encoding": "identity"
            },
            json={
                "model": CONFIG["chat_model"],
                "messages": [{"role": "user", "content":
                    f"以下是知识库中与「{process_name}」相关的文档内容：\n\n"
                    f"{knowledge_text}\n\n"
                    f"该SOP最后核验时间：{last_verified}\n\n"
                    f"请判断：这些文档是否包含可能导致该SOP需要更新的内容？\n"
                    f"以JSON返回：\n"
                    f"{{\"risk\":\"high/medium/low\","
                    f"\"reason\":\"一句话说明原因\","
                    f"\"suggestion\":\"具体建议\"}}\n"
                    f"只返回JSON，不要其他内容。"
                }],
                "stream": False
            },
            timeout=30
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        start = content.find("{")
        end = content.rfind("}") + 1
        result = json.loads(content[start:end])
        result["sop_id"] = sop_id
        result["process_name"] = process_name
        result["related_files"] = list(set([c["source_file"] for c in newer_chunks]))
        return result
    except Exception as e:
        return {"error": str(e)}