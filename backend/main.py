import os
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import Optional, List
import os
import shutil
from dotenv import load_dotenv
load_dotenv()

# 导入knowledge模块的函数
from knowledge import (
    parse_document, chunk_text, save_to_knowledge_base, 
    delete_document, search_knowledge, init_sqlite, SQLITE_PATH,
    generate_questions
)
from memory import get_memory_status, write_memory, _extract_insights_from_conversation, read_memory, init_db
from feedback import (
    get_health_stats, get_blind_spots, mark_handled,
    log_feedback, get_sop_list, verify_sop, log_query,
    check_sop_staleness
)
from llm import assemble_prompt, call_llm_stream, parse_source_tags
import sqlite3
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pydantic import BaseModel
from typing import List
from fastapi.responses import StreamingResponse

_question_executor = ThreadPoolExecutor(max_workers=2)

# 初始化数据库表
print("[main] 初始化数据库表...")
init_db()
init_sqlite()
print("[main] 数据库初始化完成")

app = FastAPI(
    title="Medical Knowledge API",
    description="银行知识管理系统后端API",
    version="1.0.0",
    docs_url="/swagger",  # 这里就是/swagger，不要乱改我的代码
    redoc_url="/redoc"
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 上传文件保存路径
UPLOAD_DIR = "./data/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.get("/ping")
async def ping():
    """健康检查接口"""
    return {"status": "ok", "message": "pong"}

@app.post("/upload")
async def upload(
    file: UploadFile = File(...),
    source_type: str = Form("knowledge"),
    process_name: str = Form(None),
    applicable_role: str = Form(None),
    effective_date: str = Form(None)):
    try:
        # 修复Windows文件名编码问题
        original_filename = file.filename
        
        # 尝试修复可能的编码问题
        # FastAPI在Windows上可能错误地将UTF-8文件名解析为latin-1
        try:
            # 如果文件名是乱码，尝试将其从latin-1编码还原为UTF-8
            fixed_filename = original_filename.encode('latin-1').decode('utf-8')
            print(f"[upload] 文件名编码修复：{original_filename} -> {fixed_filename}")
            filename = fixed_filename
        except (UnicodeEncodeError, UnicodeDecodeError):
            # 如果修复失败，使用原始文件名
            filename = original_filename
        
        print(f"[upload] 收到文件：{filename}")
        save_path = f"./data/uploads/{filename}"
        with open(save_path, "wb") as f:
            f.write(await file.read())
        print(f"[upload] 文件保存完成")
        
        try:
            texts = parse_document(save_path)
            print(f"[upload] 解析完成，共{len(texts)}页/段")
        except Exception as e:
            print(f"[upload] 文件解析失败：{e}")
            import traceback
            traceback.print_exc()
            return JSONResponse(
                status_code=500,
                content={"error": True, "message": "文件解析失败，请确认文件格式正确"}
            )
        
        chunks = chunk_text(texts, source_type)
        print(f"[upload] 切块完成，共{len(chunks)}个chunk")
        
        save_to_knowledge_base(
            chunks, filename, source_type,
            process_name, applicable_role, effective_date,
            generate_questions_flag=False)
        print(f"[upload] 入库完成，准备返回")
        
        loop = asyncio.get_event_loop()
        loop.run_in_executor(
            _question_executor,
            lambda: generate_questions(chunks, source_type, filename)
        )
        print(f"[upload] 问题生成任务已提交到线程池")
        
        return {
            "status": "success",
            "filename": filename,
            "chunks_count": len(chunks),
            "source_type": source_type,
            "message": "文档解析入库成功，问题索引正在后台生成"
        }
    except Exception as e:
        print(f"[upload] Exception报错：{e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": True, "message": f"上传失败: {str(e)}"}
        )

@app.get("/documents")
async def list_documents():
    """
    获取所有文档统计信息
    
    返回 doc_stats 表中的所有记录
    同时从 Qdrant 统计实际的问题数量，确保数据准确性
    """
    try:
        # 1. 从 SQLite 获取基础数据
        conn = sqlite3.connect(SQLITE_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, filename, chunk_count, question_count, 
                   hit_count, uploaded_at 
            FROM doc_stats 
            ORDER BY uploaded_at DESC
        """)
        
        rows = cursor.fetchall()
        conn.close()
        
        # 2. 从 Qdrant 统计每个文件的实际问题数量
        print("[documents] 从 Qdrant 统计问题数量...")
        try:
            from knowledge import qdrant_client
            
            # 获取所有问题数据
            results = qdrant_client.scroll(
                collection_name='questions',
                limit=10000,
                with_payload=True
            )
            
            # 统计每个文件的问题数量
            qdrant_question_counts = {}
            if results and results[0]:
                from collections import Counter
                source_files = [p.payload.get('source_file', 'unknown') for p in results[0]]
                qdrant_question_counts = dict(Counter(source_files))
                print(f"[documents] Qdrant 中共有 {len(results[0])} 条问题记录，涉及 {len(qdrant_question_counts)} 个文件")
        except Exception as e:
            print(f"[documents] 从 Qdrant 统计失败: {e}")
            qdrant_question_counts = {}
        
        # 3. 合并数据，优先使用 Qdrant 的统计结果
        documents = []
        for row in rows:
            filename = row["filename"]
            sqlite_question_count = row["question_count"] or 0
            
            # 优先使用 Qdrant 的统计结果
            if filename in qdrant_question_counts:
                actual_question_count = qdrant_question_counts[filename]
                if actual_question_count != sqlite_question_count:
                    print(f"[documents] 修正 {filename} 的问题数量: {sqlite_question_count} -> {actual_question_count}")
            else:
                actual_question_count = sqlite_question_count
            
            documents.append({
                "id": row["id"],
                "filename": filename,
                "chunk_count": row["chunk_count"] or 0,
                "question_count": actual_question_count,
                "hit_count": row["hit_count"] or 0,
                "uploaded_at": row["uploaded_at"],
                "status": "completed"
            })
        
        return {
            "status": "success",
            "count": len(documents),
            "documents": documents
        }
        
    except Exception as e:
        print(f"[documents] 异常: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": True, "message": "获取文档列表失败"}
        )

@app.get("/documents/{filename}/questions")
async def get_document_questions(filename: str):
    """
    获取指定文档生成的所有问题
    
    - filename: 文档名
    """
    try:
        from knowledge import qdrant_client
        
        questions = []
        all_questions = []
        
        try:
            # 先获取所有questions（不使用filter，因为Qdrant本地存储可能有问题）
            results = qdrant_client.scroll(
                collection_name="questions",
                limit=1000,
                with_payload=True
            )
            
            if results and results[0]:
                all_questions = results[0]
                print(f"[questions] 总共找到 {len(all_questions)} 条问题记录")
                
                # 打印前3条的source_file用于调试
                for i, point in enumerate(all_questions[:3]):
                    sf = point.payload.get('source_file', 'N/A')
                    print(f"  记录{i}: source_file={sf}")
                
                # 手动过滤匹配的文件名
                for point in all_questions:
                    source_file = point.payload.get("source_file", "")
                    # 支持部分匹配（处理编码问题）
                    if source_file == filename or filename in source_file or source_file in filename:
                        content = point.payload.get("content", "")
                        chunk_id = point.payload.get("source_chunk_id", "")
                        if content:
                            questions.append({
                                "question": content,
                                "chunk_id": chunk_id
                            })
            else:
                print("[questions] questions collection为空")
                
        except Exception as e:
            print(f"[questions] 查询失败: {e}")
            import traceback
            traceback.print_exc()
        
        return {
            "status": "success",
            "filename": filename,
            "total_questions_in_db": len(all_questions),
            "questions_count": len(questions),
            "questions": questions
        }
        
    except Exception as e:
        print(f"[documents/questions] 异常: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": True, "message": "获取文档问题列表失败"}
        )

@app.get("/docs/{filename}/chunks")
async def get_document_chunks(filename: str):
    """
    获取指定文档的所有chunks（用于前端预览）
    
    - filename: 文档名
    """
    try:
        from knowledge import qdrant_client
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        
        # 修复可能的编码问题（URL路径参数编码）
        original_filename = filename
        try:
            # 尝试修复文件名编码
            if '%' in filename:
                # URL编码的文件名，需要解码
                from urllib.parse import unquote
                decoded_filename = unquote(filename)
                filename = decoded_filename
            else:
                # 尝试修复Windows乱码
                fixed_filename = filename.encode('latin-1').decode('utf-8')
                filename = fixed_filename
        except (UnicodeEncodeError, UnicodeDecodeError):
            # 如果修复失败，使用原始文件名
            pass
        
        print(f"[chunks] 查询文件名: 原始={original_filename}, 修复后={filename}")
        
        chunks = []
        all_files_in_qdrant = set()  # 用于调试：收集所有不同的source_file
        
        # 从knowledge和sop_library两个collection查询
        for coll_name in ["knowledge", "sop_library"]:
            try:
                # 先获取所有记录用于调试
                debug_results = qdrant_client.scroll(
                    collection_name=coll_name,
                    limit=100,
                    with_payload=True
                )
                
                if debug_results and debug_results[0]:
                    for point in debug_results[0]:
                        sf = point.payload.get("source_file", "")
                        if sf:
                            all_files_in_qdrant.add(sf)
                
                # 实际查询 - 在本地模式下不使用filter，获取所有数据后手动过滤
                results = qdrant_client.scroll(
                    collection_name=coll_name,
                    limit=10000,  # 获取足够多的数据
                    with_payload=True
                )
                
                if results and results[0]:
                    matched_count = 0
                    for point in results[0]:
                        # 手动过滤：检查 source_file 是否匹配
                        point_source_file = point.payload.get("source_file", "")
                        if point_source_file == filename or filename in point_source_file or point_source_file in filename:
                            matched_count += 1
                            content = point.payload.get("content", "")
                            chunk_id = point.payload.get("chunk_id", point.id)
                            chunks.append({
                                "chunk_id": chunk_id,
                                "content": content[:200] + "..." if len(content) > 200 else content,
                                "full_length": len(content)
                            })
                    print(f"[chunks] 从 {coll_name} 找到 {len(results[0])} 条记录，匹配 {matched_count} 条")
                else:
                    print(f"[chunks] 从 {coll_name} 未找到记录")
            except Exception as e:
                print(f"[chunks] 从 {coll_name} 查询失败: {e}")
                import traceback
                traceback.print_exc()
                continue
        
        # 按chunk_id排序
        chunks.sort(key=lambda x: x["chunk_id"])
        
        # 调试信息
        debug_info = {
            "original_query": original_filename,
            "fixed_query": filename,
            "all_files_in_qdrant_sample": list(all_files_in_qdrant)[:5] if all_files_in_qdrant else []
        }
        
        return {
            "status": "success",
            "filename": filename,
            "chunks_count": len(chunks),
            "chunks": chunks,
            "debug": debug_info
        }
        
    except Exception as e:
        print(f"[docs/chunks] 异常: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": True, "message": "获取文档chunks失败"}
        )

@app.get("/debug/qdrant_payload")
async def debug_qdrant_payload(limit: int = 5):
    """
    调试接口：查看Qdrant中实际的payload数据结构
    """
    try:
        from knowledge import qdrant_client
        
        result = {}
        
        for coll_name in ["knowledge", "sop_library"]:
            try:
                results = qdrant_client.scroll(
                    collection_name=coll_name,
                    limit=limit,
                    with_payload=True
                )
                
                samples = []
                if results and results[0]:
                    for point in results[0]:
                        payload = point.payload
                        samples.append({
                            "point_id": str(point.id),
                            "source_file": payload.get("source_file", "NOT_FOUND"),
                            "source_file_bytes": repr(payload.get("source_file", "").encode('utf-8', errors='replace')),
                            "source_file_length": len(payload.get("source_file", "")),
                            "source_type": payload.get("source_type", "NOT_FOUND"),
                            "chunk_id": payload.get("chunk_id", "NOT_FOUND"),
                            "content_preview": payload.get("content", "")[:50] + "..." if payload.get("content") else "NO_CONTENT"
                        })
                
                result[coll_name] = {
                    "total_count": len(results[0]) if results and results[0] else 0,
                    "samples": samples
                }
            except Exception as e:
                result[coll_name] = {"error": str(e)}
        
        return {
            "status": "success",
            "data": result
        }
        
    except Exception as e:
        print(f"[debug/qdrant_payload] 异常: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": True, "message": f"调试接口失败: {str(e)}"}
        )

@app.get("/documents/{filename}/preview")
async def get_document_preview(filename: str):
    """
    获取文档预览信息（包含 chunks 和 questions）
    
    - filename: 文档名
    返回完整的文档预览数据，包括：
    - 文档基本信息
    - 所有 chunk 列表
    - 所有生成的索引问题
    """
    try:
        from knowledge import qdrant_client, SQLITE_PATH
        import sqlite3
        from collections import defaultdict
        
        print(f"[preview] 开始获取文档预览: {filename}")
        
        # 1. 从 SQLite 获取文档基础信息
        conn = sqlite3.connect(SQLITE_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, filename, chunk_count, question_count, hit_count, uploaded_at
            FROM doc_stats
            WHERE filename = ?
        """, (filename,))
        
        doc_row = cursor.fetchone()
        conn.close()
        
        if not doc_row:
            return JSONResponse(
                status_code=404,
                content={"error": True, "message": f"文档 {filename} 不存在"}
            )
        
        # 2. 从 Qdrant 获取所有 chunks
        print(f"[preview] 从 Qdrant 获取 chunks...")
        chunks = []
        chunk_id_map = {}  # 用于关联问题和 chunk
        
        for collection in ["knowledge", "sop_library"]:
            try:
                results = qdrant_client.scroll(
                    collection_name=collection,
                    limit=10000,
                    with_payload=True
                )
                
                if results and results[0]:
                    for point in results[0]:
                        source_file = point.payload.get("source_file", "")
                        # 匹配文件名
                        if source_file == filename or filename in source_file or source_file in filename:
                            chunk_data = {
                                "chunk_id": point.payload.get("chunk_id", str(point.id)),
                                "content": point.payload.get("content", ""),
                                "source_type": point.payload.get("source_type", "knowledge"),
                                "created_at": point.payload.get("created_at", "")
                            }
                            chunks.append(chunk_data)
                            chunk_id_map[chunk_data["chunk_id"]] = chunk_data
                            
            except Exception as e:
                print(f"[preview] 从 {collection} 查询失败: {e}")
                continue
        
        # 按 chunk_id 排序
        chunks.sort(key=lambda x: x["chunk_id"])
        print(f"[preview] 找到 {len(chunks)} 个 chunks")
        
        # 3. 从 Qdrant 获取所有问题
        print(f"[preview] 从 Qdrant 获取 questions...")
        questions = []
        
        try:
            results = qdrant_client.scroll(
                collection_name="questions",
                limit=10000,
                with_payload=True
            )
            
            if results and results[0]:
                for point in results[0]:
                    source_file = point.payload.get("source_file", "")
                    # 匹配文件名
                    if source_file == filename or filename in source_file or source_file in filename:
                        question_data = {
                            "question": point.payload.get("content", ""),
                            "chunk_id": point.payload.get("source_chunk_id", ""),
                            "source_type": point.payload.get("source_type", "knowledge")
                        }
                        questions.append(question_data)
                        
        except Exception as e:
            print(f"[preview] 从 questions 查询失败: {e}")
        
        print(f"[preview] 找到 {len(questions)} 个问题")
        
        # 4. 组装返回数据
        preview_data = {
            "status": "success",
            "filename": doc_row["filename"],
            "file_type": chunks[0]["source_type"] if chunks else "knowledge",
            "upload_time": doc_row["uploaded_at"],
            "total_chunks": len(chunks),
            "total_questions": len(questions),
            "hit_count": doc_row["hit_count"] or 0,
            "chunks": chunks,
            "questions": questions
        }
        
        print(f"[preview] 成功返回文档预览数据")
        return preview_data
        
    except Exception as e:
        print(f"[preview] 异常: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": True, "message": f"获取文档预览失败: {str(e)}"}
        )

@app.delete("/docs/{filename}")
async def remove_document(filename: str):
    """
    删除指定文档
    
    - filename: 要删除的文档名
    """
    try:
        delete_document(filename)
        
        return {
            "status": "success",
            "message": "文档已删除"
        }
    except Exception as e:
        print(f"[remove_document] 删除失败: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": True, "message": f"删除失败: {str(e)}"}
        )

@app.delete("/admin/delete_all_documents")
async def delete_all_documents():
    """
    删除所有文档（用于测试清理）
    """
    try:
        from knowledge import qdrant_client, SQLITE_PATH
        import sqlite3
        import os
        import glob
        
        deleted_count = 0
        errors = []
        
        # 1. 从SQLite获取所有文档列表
        try:
            conn = sqlite3.connect(SQLITE_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT filename FROM doc_stats")
            files = cursor.fetchall()
            conn.close()
            
            # 2. 逐个删除文档
            for (filename,) in files:
                try:
                    delete_document(filename)
                    deleted_count += 1
                    print(f"[delete_all] 已删除: {filename}")
                except Exception as e:
                    errors.append(f"删除 {filename} 失败: {str(e)}")
                    
        except Exception as e:
            errors.append(f"获取文档列表失败: {str(e)}")
        
        # 3. 清理上传目录中的文件（保留目录结构）
        upload_dir = "./data/uploads"
        if os.path.exists(upload_dir):
            files = glob.glob(os.path.join(upload_dir, "*"))
            for f in files:
                try:
                    if os.path.isfile(f):
                        os.remove(f)
                        print(f"[delete_all] 已清理文件: {f}")
                except Exception as e:
                    errors.append(f"清理文件失败 {f}: {str(e)}")
        
        return {
            "status": "success",
            "message": f"已删除 {deleted_count} 个文档",
            "deleted_count": deleted_count,
            "errors": errors if errors else None
        }
        
    except Exception as e:
        print(f"[delete_all_documents] 异常: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": True, "message": f"删除失败: {str(e)}"}
        )

@app.get("/debug/collections")
async def get_collections_debug():
    """
    获取所有collection的详细信息
    """
    try:
        from knowledge import qdrant_client
        
        result = {}
        collections = ["knowledge", "sop_library", "questions"]
        
        for coll_name in collections:
            try:
                count_result = qdrant_client.count(collection_name=coll_name)
                count = count_result.count
                
                results = qdrant_client.scroll(
                    collection_name=coll_name,
                    limit=3,
                    with_payload=True
                )
                
                samples = []
                if results and results[0]:
                    for point in results[0]:
                        samples.append(point.payload.get("content", ""))
                
                result[coll_name] = {
                    "count": count,
                    "sample": samples
                }
            except Exception as e:
                print(f"获取collection {coll_name} 信息失败: {e}")
                result[coll_name] = {
                    "count": 0,
                    "sample": []
                }
        
        return result
        
    except Exception as e:
        print(f"[debug/collections] 异常: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": True, "message": "获取collections信息失败"}
        )


@app.get("/memory/status")
async def memory_status(user_id: str, session_id: str):
    """
    获取用户记忆状态
    """
    try:
        result = get_memory_status(user_id, session_id)
        return {"status": "success", "data": result}
    except Exception as e:
        print(f"[memory/status] 异常: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": True, "message": "获取记忆状态失败"}
        )

@app.post("/memory/test_write")
async def test_write_memory(background_tasks: BackgroundTasks):
    # 使用与页面相同的 user_id 和 session_id
    background_tasks.add_task(
        write_memory,
        "user_001",
        "c9f5e729-ace1-4c65-af63-f45b1557552a",
        "我是零售业务柜员，主要处理贷款审批和提前还款业务",
        "好的，我了解了，您是零售业务柜员，我会针对贷款审批和提前还款相关问题为您提供详细的操作步骤"
    )
    return {"status": "ok", "message": "记忆写入任务已加入队列，5秒后查询验证"}

class MarkHandledRequest(BaseModel):
    blind_spot_id: str


class LogFeedbackRequest(BaseModel):
    user_id: str
    query: str
    session_id: str
    feedback_type: str


class VerifySopRequest(BaseModel):
    sop_id: int
    action: str


class CheckSopStalenessRequest(BaseModel):
    sop_id: int


class ChatRequest(BaseModel):
    user_id: str
    session_id: str
    query: str


@app.get("/feedback/health_stats")
async def feedback_health_stats():
    """获取知识健康度统计"""
    try:
        stats = get_health_stats()
        return {"status": "success", "data": stats}
    except Exception as e:
        print(f"[feedback/health_stats] 异常: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": True, "message": "获取健康统计失败"}
        )


@app.get("/feedback/blind_spots")
async def feedback_blind_spots(force_refresh: bool = False):
    """获取盲区聚类分析（响应可能较慢，超时60秒）
    Args:
        force_refresh: 是否强制刷新缓存，默认false
    """
    try:
        result = get_blind_spots(force_refresh=force_refresh)
        blind_spots = result["data"]
        generated_at = result["generated_at"]
        query_count = result["query_count"]

        # 规范化类型字段，确保只有 'knowledge' 或 'sop'
        for spot in blind_spots:
            if spot.get('type') and '/' in spot['type']:
                # 如果类型是 'sop/knowledge' 等混合类型，默认取第一个
                spot['type'] = spot['type'].split('/')[0]
            elif not spot.get('type') or spot['type'] not in ['knowledge', 'sop']:
                spot['type'] = 'knowledge'

        return {
            "status": "success",
            "data": blind_spots,
            "generated_at": generated_at,
            "query_count": query_count
        }
    except Exception as e:
        print(f"[feedback/blind_spots] 异常: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": True, "message": "盲区分析失败"}
        )


@app.get("/feedback/poorly_answered")
async def feedback_poorly_answered():
    """获取命中但没答好的问题列表"""
    import sqlite3
    from feedback import SQLITE_PATH
    
    try:
        conn = sqlite3.connect(SQLITE_PATH)
        
        # 查询answer_feedback表中的所有反馈
        rows = conn.execute("""
            SELECT DISTINCT query, feedback_type, created_at
            FROM answer_feedback
            WHERE feedback_type IN ('not_accurate', 'outdated', 'not_answered')
            ORDER BY created_at DESC
            LIMIT 50
        """).fetchall()
        
        # 同时统计未命中知识的问题数
        unhit_count = conn.execute("""
            SELECT COUNT(DISTINCT query)
            FROM query_log
            WHERE hit_knowledge = 0
            AND created_at > datetime('now', '-30 days')
        """).fetchone()[0] or 0
        
        conn.close()
        
        queries = [row[0] for row in rows]

        # 添加禁止缓存的响应头，避免304
        headers = {
            "Cache-Control": "no-store, no-cache, must-revalidate, proxy-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }

        return JSONResponse(
            content={
                "queries": queries,
                "unhit_count": unhit_count
            },
            headers=headers
        )
    except Exception as e:
        print(f"[feedback/poorly_answered] 异常: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": True, "message": "获取未答好问题失败"}
        )


@app.post("/feedback/mark_handled")
async def feedback_mark_handled(request: MarkHandledRequest):
    """标记盲区为已处理"""
    try:
        mark_handled([request.blind_spot_id])
        return {"status": "success", "message": "已标记为已处理"}
    except Exception as e:
        print(f"[feedback/mark_handled] 异常: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": True, "message": "标记失败"}
        )


@app.post("/feedback/log")
async def feedback_log(request: LogFeedbackRequest):
    """记录答案反馈"""
    try:
        # 记录到 answer_feedback 表并获取结果
        result = log_feedback(request.user_id, request.query, request.session_id, request.feedback_type)
        
        print(f"[feedback/log] 反馈已记录: user_id={request.user_id}, query={request.query}, session_id={request.session_id}, type={request.feedback_type}")
        return {"status": "success", "data": result}
    except Exception as e:
        print(f"[feedback/log] 异常: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": True, "message": "反馈记录失败"}
        )


@app.get("/feedback/sop_list")
async def feedback_sop_list():
    """获取SOP列表及健康状态"""
    try:
        sop_list = get_sop_list()
        return {"status": "success", "data": sop_list}
    except Exception as e:
        print(f"[feedback/sop_list] 异常: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": True, "message": "获取SOP列表失败"}
        )


@app.post("/feedback/verify_sop")
async def feedback_verify_sop(request: VerifySopRequest):
    """SOP核验操作"""
    try:
        verify_sop(request.sop_id, request.action)
        return {"status": "success", "message": "SOP核验完成"}
    except Exception as e:
        print(f"[feedback/verify_sop] 异常: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": True, "message": "SOP核验失败"}
        )


@app.post("/feedback/check_sop_staleness")
async def api_check_sop_staleness(request: CheckSopStalenessRequest):
    """检查SOP是否过时"""
    try:
        result = check_sop_staleness(request.sop_id)
        return {"status": "success", "data": result}
    except Exception as e:
        print(f"[feedback/check_sop_staleness] 异常: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": True, "message": "检查SOP过时状态失败"}
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

@app.post("/chat")
async def chat_endpoint(request: ChatRequest, background_tasks: BackgroundTasks):
    """
    聊天接口 - 支持流式响应
    
    Args:
        request: 聊天请求（session_id, user_id, query）
        background_tasks: 后台任务
    
    Returns:
        流式响应
    """
    try:
        loop = asyncio.get_event_loop()
        # 1. 检索知识库与记忆
        knowledge_results = await loop.run_in_executor(None, search_knowledge, request.query)
        
        # 记忆接口调用失败时静默处理
        memory_data = {}
        try:
            memory_data = read_memory(request.query, request.user_id, request.session_id)
        except Exception as e:
            print(f"[chat] 记忆接口调用失败，静默处理: {e}")
            import traceback
            traceback.print_exc()
            memory_data = {
                "meta_rules": "该用户正在使用企业知识助手",
                "insights": [],
                "facts": [],
                "short_term": []
            }
        
        # 2. 记录查询日志 (对应你 feedback.py 中的功能)
        try:
            log_query(request.user_id, request.query, knowledge_results)
        except Exception as e:
            print(f"[chat] 查询日志记录失败，静默处理: {e}")
        
        # 3. 组装 Prompt
        messages = assemble_prompt(request.query, knowledge_results, memory_data)
        
        # 定义生成器（直接闭包引用 request，减少默认参数带来的 Bug）
        async def generate():
            full_response = ""
            try:
                chunk_count = 0
                async for chunk in call_llm_stream(messages):
                    if chunk:
                        chunk_count += 1
                        full_response += chunk
                        yield f"data: {json.dumps({'type':'text','content':chunk}, ensure_ascii=False)}\n\n"
                
                print(f"[generate] 流式结束，共{chunk_count}个chunk")
            except Exception as e:
                print(f"[generate] OpenAI API 调用异常: {e}")
                import traceback
                traceback.print_exc()
                yield f"data: {json.dumps({'type':'text','content':'AI服务暂时不可用，请重试'}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
                return
            
            # 发送引用来源
            try:
                sources = parse_source_tags(knowledge_results, memory_data)
                yield f"data: {json.dumps({'type':'sources','content':sources}, ensure_ascii=False)}\n\n"
            except Exception as e:
                print(f"[generate] 来源解析失败，静默处理: {e}")
            yield "data: [DONE]\n\n"
            
            # 4. 关键修正：确保 background_tasks 拿到正确的 id
            print(f"[chat] full_response length: {len(full_response)}, content: {full_response[:100]}...")
            if full_response:
                print(f"[chat] 添加后台任务 write_memory, session_id={request.session_id}")
                background_tasks.add_task(
                    write_memory, 
                    request.user_id,    # 显式使用 request 对象
                    request.session_id, 
                    request.query, 
                    full_response
                )
            else:
                print(f"[chat] full_response 为空，不保存历史记录")
        
        return StreamingResponse(generate(), media_type="text/event-stream")

    except Exception as e:
        print(f"[chat] 启动阶段异常: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": True, "message": "AI服务暂时不可用，请重试"}
        )

# 测试接口 TODO：后面人工删除
@app.get("/debug/test_insight")
def test_insight():
    from config import CONFIG
    print(f"[debug] chat_base_url={CONFIG['chat_base_url']}")
    print(f"[debug] chat_model={CONFIG['chat_model']}")
    conversation = "用户：我是零售业务柜员\nAI：好的我了解了"
    result = _extract_insights_from_conversation(conversation)
    return {
        "insights": result,
        "count": len(result),
        "config": {
            "base_url": CONFIG["chat_base_url"],
            "model": CONFIG["chat_model"]
        }
    }

@app.post("/debug/seed_feedback")
def seed_feedback():
    from feedback import log_query, log_feedback
    import sqlite3
    
    # 写入5条query_log，3条命中，2条未命中
    log_query("柜员-张三", "贷款审批流程是什么", 
              [{"score": 0.9, "source_file": "test.pdf", 
                "source_type": "knowledge", "content": "..."}])
    log_query("柜员-张三", "提前还款怎么操作",
              [{"score": 0.85, "source_file": "sop.docx",
                "source_type": "sop", "content": "..."}])
    log_query("柜员-张三", "利率调整通知在哪里", [])
    log_query("客服-李四", "客户投诉处理流程", [])
    log_query("客服-李四", "产品说明书怎么查", 
              [{"score": 0.8, "source_file": "test.pdf",
                "source_type": "knowledge", "content": "..."}])
    log_query("柜员-张三", "利率调整通知在哪里", [])
    log_query("客服-李四", "客户投诉处理流程", [])
    log_query("柜员-张三", "审批时效标准是什么", [])
    log_query("客服-李四", "提前还款违约金怎么算", [])
    log_query("审批岗-王五", "大额贷款审批权限是多少", [])
    log_query("审批岗-王五", "风险评级标准在哪里查", [])
    
    # 写入1条answer_feedback
    log_feedback("柜员-张三", "利率调整通知在哪里", 
                 "test123", "not_answered")
    
    return {"status": "ok", "message": "测试数据写入完成"}

@app.get("/debug/test_llm")
def test_llm():
    import os
    import httpx
    from openai import OpenAI
    from config import CONFIG

    # 强制 localhost 不走 VPN 代理
    os.environ["NO_PROXY"] = "localhost,127.0.0.1"
    os.environ["no_proxy"] = "localhost,127.0.0.1"

    client = OpenAI(
        api_key=CONFIG["api_key"],
        base_url=CONFIG["chat_base_url"],
        http_client=httpx.Client(
            headers={"Accept-Encoding": "identity"},
            proxy=None  # 明确不用代理
        )
    )

    try:
        resp = client.chat.completions.create(
            model=CONFIG["chat_model"],
            messages=[{"role": "user", "content": "你好，回复一个字"}]
        )
        return {"result": resp.choices[0].message.content}
    except Exception as e:
        import traceback
        return {"error": str(e), "trace": traceback.format_exc()}


@app.get("/debug/test_stream")
async def test_stream():
    import requests
    from config import CONFIG
    from fastapi.responses import StreamingResponse
    
    def _generate():
        resp = requests.post(
            f"{CONFIG['chat_base_url']}/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {CONFIG['api_key']}",
                "Accept-Encoding": "identity"
            },
            json={
                "model": CONFIG["chat_model"],
                "messages": [{"role":"user","content":"用三句话介绍银行开户流程"}],
                "stream": True
            },
            stream=True,
            timeout=60
        )
        for line in resp.iter_lines():
            if line:
                decoded = line.decode("utf-8")
                yield f"{decoded}\n"
    
    return StreamingResponse(_generate(), media_type="text/plain")


@app.get("/chat/history")
async def get_chat_history(user_id: str):
    """
    获取用户历史记录（按用户维度，不按会话）
    """
    try:
        import sqlite3
        import json
        from memory import SQLITE_PATH
        
        conn = sqlite3.connect(SQLITE_PATH)
        # 查找该用户最新的会话记录
        row = conn.execute(
            "SELECT messages FROM session_store WHERE user_id=? ORDER BY updated_at DESC LIMIT 1",
            (user_id,)
        ).fetchone()
        conn.close()
        
        if row:
            messages = json.loads(row[0])
            return {"status": "success", "messages": messages}
        else:
            return {"status": "success", "messages": []}
    except Exception as e:
        print(f"[chat/history] 异常: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": True, "message": "获取历史记录失败"}
        )


@app.get("/feedback/poorly_answered")
async def feedback_poorly_answered():
    """获取回答质量较差的问题列表"""
    try:
        import sqlite3
        from datetime import datetime, timedelta
        
        conn = sqlite3.connect(SQLITE_PATH)
        
        # 查询过去30天内命中知识库但回答质量差的问题
        thirty_days_ago = (datetime.now() - timedelta(days=30)).isoformat()
        
        rows = conn.execute("""
            SELECT DISTINCT af.query 
            FROM answer_feedback af
            JOIN query_log ql ON af.query = ql.query
            WHERE af.feedback_type IN ('not_accurate', 'not_answered')
            AND ql.hit_knowledge = 1
            AND af.created_at > ?
            ORDER BY af.created_at DESC
            LIMIT 20
        """, (thirty_days_ago,)).fetchall()
        
        # 验证：统计过去30天hit_knowledge=0的记录数
        unhit_count = conn.execute("""
            SELECT COUNT(*) FROM query_log 
            WHERE hit_knowledge=0 
            AND created_at > datetime('now', '-30 days')
        """).fetchone()[0]
        
        print(f"[feedback/poorly_answered] 过去30天未命中查询数: {unhit_count}")
        
        conn.close()
        
        queries = [row[0] for row in rows]
        
        return {
            "status": "success",
            "queries": queries,
            "count": len(queries),
            "unhit_count": unhit_count
        }
    except Exception as e:
        print(f"[feedback/poorly_answered] 异常: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": True, "message": "获取回答质量问题列表失败"}
        )


@app.post("/admin/regenerate_questions")
async def regenerate_questions():
    import sqlite3
    from knowledge import SQLITE_PATH, parse_document, chunk_text, generate_questions
    
    conn = sqlite3.connect(SQLITE_PATH)
    docs = conn.execute(
        "SELECT filename FROM doc_stats"
    ).fetchall()
    conn.close()
    
    # 从文件名推断source_type（knowledge或sop）
    def infer_source_type(filename: str) -> str:
        # 这里可以根据文件名规则推断，默认使用"knowledge"
        # 也可以从其他表或元数据中获取
        return "knowledge"
    
    results = []
    for (filename,) in docs:
        try:
            file_path = f"./data/uploads/{filename}"
            if not os.path.exists(file_path):
                results.append({"filename": filename, "status": "文件不存在"})
                continue
            print(f"[regenerate] 开始处理：{filename}")
            texts = parse_document(file_path)
            # 从文件名推断source_type
            source_type = "knowledge"  # 默认为knowledge
            chunks = chunk_text(texts, source_type)
            count = generate_questions(chunks, source_type, filename)
            results.append({"filename": filename, "status": "success", "questions": count})
        except Exception as e:
            results.append({"filename": filename, "status": f"失败:{str(e)}"})
    
    return {"results": results}