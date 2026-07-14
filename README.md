# 企业知识库智能助手（kb-server）

基于 **Python + LangChain + Chroma + 通义千问** 的企业内部文档知识库问答服务。
由 Java 后端 `aicontent`（:8080）通过 `/api/kb/*` 代理调用，不暴露公网、不解析 JWT。

## 功能
- 上传企业文档（PDF / Word / Excel / Markdown / TXT），自动切分 + 向量化入库
- 基于 RAG 的智能问答，支持 SSE 流式输出 + 来源引用
- 多租户：每个用户可建多个知识库（`kb_id`），向量互相隔离

## 目录结构
```
app/
  main.py          FastAPI 入口
  config.py        配置（通义 Key、Chroma 路径、模型）
  schemas.py       Pydantic 请求/响应
  llm.py           通义 qwen 对话(流式) + text-embedding-v3 封装
  vectorstore.py   Chroma 封装（按 kb_id 建 collection、增删查）
  loader.py        文档解析（pdf/docx/xlsx/md/txt）
  splitter.py      中文切分
  rag.py           检索 + 生成核心
  routers/
    document.py    上传/删除文档
    chat.py        问答（SSE 流式）
```

## 快速开始
```bash
cd kb
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # 填入 QWEN_API_KEY
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```
健康检查：`GET http://localhost:8001/kb/health`

## 接口（内部调用，由 Java 代理）
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/kb/documents/upload` | multipart(file) + `user_id` + `library_id` |
| DELETE | `/kb/documents/{doc_id}?user_id=&library_id=` | 删除文档并清向量 |
| POST | `/kb/chat` | `{user_id, library_id, question, history?}`，SSE 流式 |

## 部署为独立仓库（推送到 GitHub）
```bash
cd kb
git init
git add -A
git commit -m "init knowledge-base service"
git branch -M main
git remote add origin https://github.com/lhy157/knowledge-base.git
git push -u origin main
```
