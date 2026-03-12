import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

def load_config():
    """从环境变量加载大模型配置"""
    
    # 大语言模型配置
    llm_api_key = os.getenv("LLM_API_KEY", "dummy")
    llm_base_url = os.getenv("LLM_BASE_URL", "http://localhost:9001/v1")
    llm_model = os.getenv("LLM_MODEL", "Pro/deepseek-ai/DeepSeek-V3")
    
    # Embedding模型配置
    embedding_api_key = os.getenv("EMBEDDING_API_KEY", "dummy")
    embedding_base_url = os.getenv("EMBEDDING_BASE_URL", "http://localhost:9001/v1")
    embedding_model = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
    
    # 网关配置（向后兼容）
    gateway_url = os.getenv("GATEWAY_URL", "http://localhost:9001")
    
    return {
        # LLM配置
        "llm_api_key": llm_api_key,
        "llm_base_url": llm_base_url,
        "llm_model": llm_model,
        
        # Embedding配置
        "embedding_api_key": embedding_api_key,
        "embedding_base_url": embedding_base_url,
        "embedding_model": embedding_model,
        
        # 向后兼容
        "api_key": llm_api_key,
        "chat_base_url": llm_base_url,
        "chat_model": llm_model,
        "gateway_url": gateway_url,
    }

CONFIG = load_config()