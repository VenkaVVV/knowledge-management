# 银行知识管理系统

基于 RAG 技术的银行知识管理系统，支持文档上传、智能问答、知识盲区分析等功能。

## 本地启动步骤

### 1. 环境准备

编辑 `.env` 文件，填入你的 OpenAI baseurl 和 API Key
当然我这个版本是配合我的proxy项目使用的，只需要填baseurl为proxy项目启动的代理地址就好

### 2. 后端启动

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

验证后端是否启动成功：
```bash
curl http://localhost:8000/ping
# 应返回：{"status":"ok","message":"pong"}
```

### 3. 前端启动

```bash
cd frontend
npm install
npm run dev
```

访问 http://localhost:3000 查看前端页面。

## 注意事项

- **4GB内存** 电脑演示前建议关闭其他程序
- 首次启动可能需要下载依赖，请耐心等待