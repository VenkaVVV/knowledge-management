from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
import os

QDRANT_PATH = os.getenv("QDRANT_PATH", "./data/qdrant")

# 全局单例，整个应用只创建一次
_client = None

def get_qdrant_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(path=QDRANT_PATH)
    return _client

def init_collections():
    client = get_qdrant_client()
    existing = [c.name for c in client.get_collections().collections]
    for name, size in [("knowledge", 1024), ("sop_library", 1024), 
                       ("questions", 1024), ("insights", 1024)]:
        if name not in existing:
            client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(
                    size=size, distance=Distance.COSINE))
            print(f"[qdrant] 创建collection: {name}")

init_collections()