"""
客户端工厂 - 统一管理各种API客户端的初始化
消除重复的网络请求配置代码
"""
import os
import httpx
from openai import OpenAI, AsyncOpenAI
from config import CONFIG

def _setup_environment():
    """统一设置环境变量，避免重复配置"""
    os.environ["NO_PROXY"] = "localhost,127.0.0.1"
    os.environ["no_proxy"] = "localhost,127.0.0.1"

def create_openai_client(is_async: bool = False, use_embedding_config: bool = False):
    """
    创建统一配置的OpenAI客户端

    Args:
        is_async: 是否创建异步客户端
        use_embedding_config: 是否使用embedding模型的配置（默认使用聊天模型配置）

    Returns:
        OpenAI 或 AsyncOpenAI 客户端实例
    """
    _setup_environment()

    if use_embedding_config:
        api_key = CONFIG["embedding_api_key"]
        base_url = CONFIG["embedding_base_url"]
    else:
        api_key = CONFIG["api_key"]
        base_url = CONFIG["chat_base_url"]

    http_client = httpx.Client(
        headers={"Accept-Encoding": "identity"},
        proxy=None  # 明确不用代理
    ) if not is_async else httpx.AsyncClient(
        headers={"Accept-Encoding": "identity"},
        proxy=None
    )

    client_class = AsyncOpenAI if is_async else OpenAI

    return client_class(
        api_key=api_key,
        base_url=base_url,
        http_client=http_client
    )

def get_embedding_headers():
    """获取embedding API请求的统一headers"""
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {CONFIG['embedding_api_key']}"
    }

# 预创建常用客户端实例，避免重复创建
# 同步聊天客户端
default_openai_client = create_openai_client(is_async=False)
# 异步聊天客户端
async_openai_client = create_openai_client(is_async=True)
# Embedding客户端
embedding_openai_client = create_openai_client(is_async=False, use_embedding_config=True)
