# 企业知识库智能助手（kb-server）

基于 **Python + LangChain + Chroma + 通义千问** 的企业内部文档知识库问答服务。
由 Java 后端 `aicontent`（:8080）通过 `/api/kb/*` 代理调用，**不暴露公网、不解析 JWT**，安全边界交给 Java 侧。

---

## 一、整体架构

```
浏览器(Vue :5173)
   │  /api/kb/*  (Vite 代理 → aicontent :8080)
   ▼
aicontent :8080  (KbController：校验 JWT → 内部 HTTP 带 user_id 调 Python)
   │  http://localhost:8001/kb/*
   ▼
kb-server (Python FastAPI :8001)  ── 复用 qwen LLM + 通义 text-embedding-v3
   ├── loader.py       文档解析（pdf/docx/xlsx/md/txt）
   ├── splitter.py     中文切分
   ├── vectorstore.py  Chroma 向量库（按 library_id 隔离 collection，本地持久化）
   └── rag.py          检索 + 生成（SSE 流式 + 来源引用）
```

**设计要点**
- **多租户隔离**：每个用户可建多个知识库（`library_id`），Chroma 中每个库对应一个独立 collection（`kb_{library_id}`），向量互相不可见。
- **命令与查询分离**：文档向量存 Chroma（Python 侧），元信息（`kb_library` / `kb_document`）存 MySQL（Java 侧），通过 `doc_id` 关联。
- **Java 代理**：Python 不解析 JWT、不直连公网；所有请求由 `aicontent` 校验身份后转发，并以服务端可信身份覆盖 `user_id` / `library_id`，防止越权。

---

## 二、功能

- 上传企业文档（PDF / Word / Excel / Markdown / TXT），自动解析 → 中文切分 → 向量化入库
- 基于 RAG 的智能问答，支持 **SSE 流式输出** + **来源引用**（文件名 + 片段）
- 多知识库：每用户可建多个库，问答时指定 `library_id`
- 严格守界：资料无答案时明确告知「无法回答」，不编造（prompt 已约束）

---

## 三、目录结构

```
kb/
├── app/
│   ├── main.py          # FastAPI 入口，挂路由 + /kb/health 健康检查
│   ├── config.py        # 配置：通义 Key、Chroma 路径、模型参数（环境变量注入）
│   ├── schemas.py       # Pydantic 请求/响应模型
│   ├── llm.py           # 通义 qwen 流式对话 + text-embedding-v3 封装
│   ├── vectorstore.py   # Chroma 封装：按 library_id 建 collection、增删查
│   ├── loader.py        # 文档解析（pdf/docx/xlsx/md/txt）
│   ├── splitter.py      # 中文切分（RecursiveCharacterTextSplitter，按句号/段落）
│   ├── rag.py           # RAG 核心：检索 + 拼 prompt + 流式生成
│   └── routers/
│       ├── document.py  # 上传 / 删除文档
│       └── chat.py      # 问答（SSE 流式）
├── requirements.txt     # 依赖（FastAPI / Chroma / LangChain / openai / 解析库）
├── .env.example         # 环境变量模板（复制为 .env 填 Key）
├── .gitignore           # 忽略 .env / venv / chroma_data
└── README.md
```

---

## 四、快速开始

```bash
cd kb
# 1. 虚拟环境
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 2. 装依赖
pip install -r requirements.txt

# 3. 配置密钥
cp .env.example .env              # 编辑 .env，填入 QWEN_API_KEY

# 4. 启动（独立窗口常驻）
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

- 健康检查：`GET http://localhost:8001/kb/health` → `{"status":"ok","service":"kb-server"}`
- API 文档（自动生成）：`http://localhost:8001/docs`

---

## 五、配置项（.env）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `QWEN_API_KEY` | 空 | 通义百炼 API Key，用于 qwen 对话 + text-embedding-v3（**必填**） |
| `KB_PORT` | `8001` | 服务端口（Java 侧 `kb.python-url` 需对应） |
| `CHROMA_DIR` | `./chroma_data` | Chroma 向量持久化目录（相对/绝对均可） |
| `LLM_MODEL` | `qwen-turbo` | 对话模型，可换 `qwen-plus` / `qwen-max` |
| `EMBEDDING_MODEL` | `text-embedding-v3` | 向量化模型 |
| `EMBEDDING_DIM` | `1536` | 向量维度（换 embedding 模型需同步改） |
| `RETRIEVE_TOP_K` | `5` | 每次检索召回的相关片段数 |

> 通义兼容端点：`https://dashscope.aliyuncs.com/compatible-mode/v1`（见 `config.py`）。

---

## 六、接口契约（内部调用，由 Java 代理）

### 1. 上传文档
```
POST /kb/documents/upload
Content-Type: multipart/form-data
Body: file(文件), user_id(表单), library_id(表单)
```
响应：
```json
{
  "docId": "uuid",
  "filename": "手册.pdf",
  "chunkCount": 42,
  "status": "ready",
  "createdAt": "2026-07-14T22:00:00.000000"
}
```

### 2. 删除文档（同步清向量）
```
DELETE /kb/documents/{doc_id}?user_id={uid}&library_id={libId}
```
响应：`{"deleted": true}`

### 3. 问答（SSE 流式）
```
POST /kb/chat
Content-Type: application/json
Body: {"user_id": 1, "library_id": 7, "question": "退货流程？", "history": [{"role":"user","content":"..."}]}
```
SSE 事件（每行 `data: <json>`）：
```text
data: {"type":"content","text":"根据"}          # 多次，拼接为完整回答
data: {"type":"done","sources":[{"filename":"手册.pdf","snippet":"..."}]}
data: {"type":"error","text":"..."}             # 异常时
```

### 4. 健康检查
```
GET /kb/health  →  {"status":"ok","service":"kb-server"}
```

---

## 七、数据流

1. **入库**：前端上传 → `aicontent` 验 JWT → 转发文件到 `/kb/documents/upload` → Python 解析切分 → Chroma 写入 `kb_{library_id}` → 返回 `docId` → Java 落 `kb_document` 元信息。
2. **问答**：前端 → `aicontent /api/kb/chat`（SSE）→ 覆盖可信 `user_id/library_id` → 转发 `/kb/chat` → Python 对问题向量化 → Chroma 检索 top-k → 拼 prompt → qwen 流式生成 → 透传回前端。

---

## 八、排错

| 现象 | 排查 |
|---|---|
| 启动报 `QWEN_API_KEY` 相关错误 | 确认 `.env` 已填且路径正确（`config.py` 读取同目录 `.env`） |
| 上传后 `chunkCount=0` | 文档可能是扫描版 PDF / 纯图片，无文本层；或格式未支持（见 loader） |
| 问答返回 `error` | 检查通义 Key 额度、网络；看 Python 控制台堆栈 |
| 删除文档 Java 端报 400 | Java 用查询参数调用，Python 必须 `Query(...)` 接收（已对齐） |
| Chroma 写入慢 | 首次会下载模型/建索引；后续增量快 |

---

## 九、部署为独立仓库（推送到 GitHub）

本目录是独立 git 仓库，推送到 `https://github.com/lhy157/knowledge-base.git`：

```bash
cd kb
git add -A
git commit -m "feat: 知识库 Python 服务骨架 (FastAPI + Chroma + 通义)"
git branch -M main
git remote add origin https://github.com/lhy157/knowledge-base.git
git push -u origin main        # 用户名 lhy157，密码处粘贴 GitHub Personal Access Token
```

> 注意：`.env`（真实 Key）、`venv/`、`chroma_data/`（向量）已在 `.gitignore` 中忽略，不会上传。
> 拉取后在本地 `cp .env.example .env` 填 Key 即可运行。
