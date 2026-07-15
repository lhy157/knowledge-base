# 企业知识库智能助手 + 多模型接入服务（kb monorepo）

本仓库是一个 **monorepo**，包含两个相互独立、可单独部署运行的 Python 服务（模块）：

| 模块 | 目录 | 端口 | 职责 |
|---|---|---|---|
| 知识库 RAG 服务 | `kb/` | 8002 | 企业文档知识库问答（RAG） |
| 多模型接入网关 | `ai_service/` | 8000 | 统一接入 6 家大模型厂商 |

两个模块共享同一份根目录 `.env`（密钥集中管理），但各自是独立进程、独立端口，互不干扰。

> 从零跑起来（配置 + 启动分步操作）请读 [`docs/知识库配置与启动清单.md`](./docs/知识库配置与启动清单.md)。
> 最关键的一步：**去 [阿里云百炼控制台](https://dashscope.console.aliyun.com/) 创建 API Key，填进 `kb/.env` 的 `DASHSCOPE_API_KEY`**。

---

## 一、整体架构（流程图）

```mermaid
flowchart TB
    Browser["浏览器 / Vue 前端 (:5173)"]
    Browser -->|"/api/kb/* 经 Vite 代理"| Java["Java 后端 aicontent (:8080)<br/>校验 JWT → 内部可信转发"]
    Java -->|"http://localhost:8002/kb/*"| KB["kb 知识库 RAG 服务 (:8002)"]
    Java -->|"http://localhost:8000"| AIS["ai_service 多模型网关 (:8000)"]

    KB --> Backend{{"向量后端<br/>(VECTOR_BACKEND 切换)"}}
    Backend -->|chroma（默认）| Chroma[("本地 Chroma 向量库<br/>kb_{library_id} 按库隔离")]
    Backend -->|tencent（线上）| Tencent[("腾讯云向量库<br/>服务端内置 embedding")]
    KB --> Qwen["通义 qwen 对话生成"]

    AIS --> P1["阿里-通义千问"]
    AIS --> P2["腾讯-混元"]
    AIS --> P3["豆包-火山引擎"]
    AIS --> P4["DeepSeek"]
    AIS --> P5["OpenAI"]
    AIS --> P6["Anthropic-Claude"]
```

**设计要点**
- **多租户隔离**：每个用户可建多个知识库（`library_id`），Chroma 中每个库对应独立 collection（`kb_{library_id}`），向量互相不可见。
- **命令与查询分离**：文档向量存 Chroma（Python 侧），元信息（`kb_library` / `kb_document`）存 MySQL（Java 侧），通过 `doc_id` 关联。
- **Java 代理**：Python 不解析 JWT、不直连公网；所有请求由 `aicontent` 校验身份后转发，并以服务端可信身份覆盖 `user_id` / `library_id`，防止越权。
- **端口约定**：知识库 **8002**，多模型网关 **8000**，互不冲突。

---

## 二、模块一：kb（企业知识库 RAG 服务，:8002）

基于 **Python + LangChain + Chroma + 通义千问** 的企业内部文档知识库问答服务。
由 Java 后端 `aicontent`（:8080）通过 `/api/kb/*` 代理调用，**不暴露公网、不解析 JWT**，安全边界交给 Java 侧。

### 1. 功能
- 上传企业文档（PDF / Word / Excel / Markdown / TXT），自动解析 → 中文切分 → 向量化入库
- 基于 RAG 的智能问答，支持 **SSE 流式输出** + **来源引用**（文件名 + 片段）
- 多知识库：每用户可建多个库，问答时指定 `library_id`
- 严格守界：资料无答案时明确告知「无法回答」，不编造（prompt 已约束）

### 2. 目录结构
```
kb/
├── main.py          # FastAPI 入口，挂路由 + /kb/health 健康检查
├── config.py        # 配置：通义 Key、Chroma 路径、模型参数（环境变量注入）
├── schemas.py       # Pydantic 请求模型（ChatRequest）
├── llm.py           # 通义 qwen 流式对话 + text-embedding-v3 封装
├── loader.py        # 文档解析（pdf/docx/xlsx/md/txt）
├── splitter.py      # 中文切分（RecursiveCharacterTextSplitter，按句号/段落）
├── rag.py           # RAG 核心：检索 + 拼 prompt + 流式生成
├── vectorstore.py   # Chroma 封装：按 library_id 建 collection、增删查
├── chroma_data/     # 向量持久化目录（运行时生成，已 gitignore）
└── routers/
    ├── chat.py      # 问答（SSE 流式）
    └── document.py  # 上传 / 删除文档
```

### 3. 配置项（.env，见 `.env.example`）
| 变量 | 默认值 | 说明 |
|---|---|---|
| `DASHSCOPE_API_KEY` | 空 | 通义百炼 API Key，用于 qwen 对话 + text-embedding-v3（**必填**） |
| `KB_PORT` | `8002` | 服务端口（Java 侧 `kb.python-url` 需对应） |
| `CHROMA_DIR` | `./chroma_data` | Chroma 向量持久化目录（相对/绝对均可） |
| `LLM_MODEL` | `qwen-turbo` | 对话模型，可换 `qwen-plus` / `qwen-max` |
| `EMBEDDING_MODEL` | `text-embedding-v3` | 向量化模型 |
| `EMBEDDING_DIM` | `1024` | 向量维度（换 embedding 模型需同步改） |
| `RETRIEVE_TOP_K` | `5` | 每次检索召回的相关片段数 |

> 通义兼容端点：`https://dashscope.aliyuncs.com/compatible-mode/v1`（见 `kb/config.py`）。

### 3.1 向量后端切换（Chroma / 腾讯云向量库）

知识库支持两套向量后端，通过 `.env` 的 `VECTOR_BACKEND` 切换，代码层面对上层（RAG / 路由）完全透明：

| 取值 | 后端 | 嵌入方式 |
|---|---|---|
| `chroma`（默认） | 本地 Chroma（`./chroma_data`） | 客户端调用通义 `text-embedding-v3` |
| `tencent` | 腾讯云向量库 | 服务端内置 embedding（默认 `multilingual-e5-base`） |

切换为腾讯云时，在 `.env` 设置：

```env
VECTOR_BACKEND=tencent
TENCENT_VECTOR_URL=http://10.0.6.14
TENCENT_VECTOR_USERNAME=root
TENCENT_VECTOR_KEY=你的密钥
TENCENT_VECTOR_TIMEOUT=30
TENCENT_VECTOR_POOL_SIZE=2
TENCENT_VECTOR_SHARD_NUM=1
TENCENT_VECTOR_REPLICA_NUM=0
TENCENT_VECTOR_DATABASE=ai-database-test
TENCENT_VECTOR_DIM=768
TENCENT_EMBEDDING_MODEL=multilingual-e5-base
```

要点：
- 腾讯云后端**无需客户端 embedding**，写入只传 `text`，向量由服务端内置模型生成；多租户隔离仍为每个 `library_id` 一个 `kb_{library_id}` collection。
- 需安装 SDK：`pip install tcvectordb`（已加入 `requirements.txt`）。
- 嵌入模型名映射到腾讯云枚举：`multilingual-e5-base` / `bge-base-zh-v1.5` / `m3e-base` / `e5-large-v2` / `text2vec-large-chinese` 等（注意：`EmbeddingModel` 枚举**没有** `bge-large-zh-v1.5`，不要写错），维度需与所选模型一致（如 `multilingual-e5-base` 为 768）。

#### Windows 安装 `tcvectordb` 的注意事项（已踩坑）

`pip install tcvectordb` 在 **Windows + Python 3.8** 上会因为其依赖 `tcvdb-text`（57MB 源码包，需本地编译 torch/C++ 扩展）和 `crcmod` 编译失败，导致**整个安装回滚**。而我们的代码只用 `VectorDBClient`，并不需要 `tcvdb-text`（那是客户端 embedding 库，服务端内置 embedding 用不到）。正确装法是只装核心包 + 补齐纯 Python 依赖：

```bash
pip install --no-deps tcvectordb
pip install --no-deps cos-python-sdk-v5
pip install ujson cachetools
```

> - `tencent` 后端下**不再需要** `chromadb` / `langchain-text-splitters` / `openai`（通义 embedding）也能跑（检索与向量化都在服务端完成）；但本仓库 `requirements.txt` 仍一并装齐，便于随时切回 `chroma`。
> - 若你用的是 Linux / macOS 或 Python 3.10+，`pip install -r requirements.txt` 通常一次成功，无需上述 `--no-deps` 步骤。

### 4. 启动
```bash
cd kb
uvicorn kb.main:app --host 0.0.0.0 --port 8002 --reload
```
- 健康检查：`GET http://localhost:8002/kb/health` → `{"status":"ok","service":"kb-server","port":8002}`
- API 文档（自动生成）：`http://localhost:8002/docs`

### 5. 接口契约（内部调用，由 Java 代理）
**上传文档**
```
POST /kb/documents/upload
Content-Type: multipart/form-data
Body: file(文件), user_id(表单), library_id(表单)
```
响应：
```json
{ "docId": "uuid", "filename": "手册.pdf", "chunkCount": 42, "status": "ready", "createdAt": "2026-07-14T22:00:00.000000" }
```
**删除文档（同步清向量）**
```
DELETE /kb/documents/{doc_id}?user_id={uid}&library_id={libId}
```
响应：`{"deleted": true}`

**问答（SSE 流式）**
```
POST /kb/chat
Content-Type: application/json
Body: {"user_id": 1, "library_id": 7, "question": "退货流程？", "history": [{"role":"user","content":"..."}]}
```
SSE 事件（每行 `data: <json>`）：
```
data: {"type":"content","text":"根据"}          # 多次，拼接为完整回答
data: {"type":"done","sources":[{"filename":"手册.pdf","snippet":"..."}]}
data: {"type":"error","text":"..."}             # 异常时
```

### 6. 数据流
1. **入库**：前端上传 → `aicontent` 验 JWT → 转发文件到 `/kb/documents/upload` → Python 解析切分 → Chroma 写入 `kb_{library_id}` → 返回 `docId` → Java 落 `kb_document` 元信息。
2. **问答**：前端 → `aicontent /api/kb/chat`（SSE）→ 覆盖可信 `user_id/library_id` → 转发 `/kb/chat` → Python 对问题向量化 → Chroma 检索 top-k → 拼 prompt → qwen 流式生成 → 透传回前端。

### 7. 排错
| 现象 | 排查 |
|---|---|
| 启动报 `DASHSCOPE_API_KEY` 相关错误 | 确认 `.env` 已填且路径正确（`kb/config.py` 读取同目录 `.env`） |
| 上传后 `chunkCount=0` | 文档可能是扫描版 PDF / 纯图片，无文本层；或格式未支持（见 loader） |
| 问答返回 `error` | 检查通义 Key 额度、网络；看 Python 控制台堆栈 |
| 删除文档 Java 端报 400 | Java 用查询参数调用，Python 必须 `Query(...)` 接收（已对齐） |
| Chroma 写入慢 | 首次会下载模型/建索引；后续增量快 |

---

## 三、模块二：ai_service（多模型统一接入网关，:8000）

对前端 / 其他服务提供**统一的模型调用入口**，屏蔽各家厂商 SDK 差异，支持流式（SSE）与非流式。模型名按前缀或 `厂商:模型` 语法自动路由到对应厂商。

### 1. 接口
```
POST /generate      统一生成（流式 SSE / 非流式，可指定任意厂商模型）
POST /doubao_chat   豆包专用接口（默认豆包模型）
GET  /providers     查看已接入厂商及配置、Key 获取地址、文档地址
```
- `/generate` 请求体：`{"prompt": "...", "model": "qwen-plus", "stream": true, "max_tokens": 2048}`
- `/providers` 会直接返回各厂商的 `console_url`（拿 Key 地址）与 `doc_url`（文档地址），等价于本文「五、相关信息获取地址」。

### 2. 模型路由
| 前缀 / 写法 | 厂商 | 默认模型 |
|---|---|---|
| `qwen*` | 阿里-通义千问 | qwen-plus |
| `hunyuan*` | 腾讯-混元 | hunyuan-turbo |
| `doubao*` | 豆包-火山引擎 | doubao-seed-2-0-pro-260215 |
| `deepseek*` | DeepSeek | deepseek-chat |
| `gpt*` / `o1*` / `o3*` / `codex*` | OpenAI | gpt-4o-mini |
| `claude*` | Anthropic-Claude | claude-sonnet-4-0 |
| `厂商key:模型`（如 `openai:gpt-4o`） | 显式指定厂商 | — |

### 3. 配置（ai_service/config.py，读根目录 `.env`）
- `AI_SERVICE_PORT`（默认 8000），与 `KB_PORT` 互不冲突
- 各家密钥见 `.env.example`：`DASHSCOPE_API_KEY` / `HUNYUAN_API_KEY` / `ARK_API_KEY` / `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`

> 注意：向量后端切换（Chroma / 腾讯云）只与 **kb 知识库服务** 有关，见本文「二、模块一」§3.1；ai_service 多模型网关不参与向量存储，无需关心。

### 4. 启动
```bash
cd kb
uvicorn ai_service.main:app --host 0.0.0.0 --port 8000 --reload
```
- API 文档：`http://localhost:8000/docs`

### 5. 排错
| 现象 | 排查 |
|---|---|
| 调用某厂商返回鉴权错误 | 确认对应环境变量（如 `ARK_API_KEY`）已在 `.env` 填好 |
| `claude*` 调用报未安装 SDK | `pip install anthropic` |
| 模型名无法路由 | 检查前缀是否在上表；或用 `厂商key:模型` 显式指定 |

---

## 四、仓库目录结构（总览）

```
kb/                                  # 仓库根（monorepo）
├── kb/                              # 模块一：知识库 RAG 服务（:8002）
│   ├── main.py                      # FastAPI 入口 + /kb/health
│   ├── config.py                    # 配置（通义 Key / Chroma / 模型）
│   ├── schemas.py                   # Pydantic 请求模型
│   ├── llm.py                       # 通义 qwen 流式 + text-embedding-v3
│   ├── loader.py                    # 文档解析（pdf/docx/xlsx/md/txt）
│   ├── splitter.py                  # 中文切分
│   ├── vectorstore.py               # Chroma 封装（按 library_id 隔离）
│   ├── rag.py                       # 检索 + 拼 prompt + 流式生成
│   ├── pyproject.toml               # 打包配置（包名 kb-server，命令入口 kb-server）
│   ├── chroma_data/                 # 向量持久化（运行时生成，gitignore）
│   └── routers/
│       ├── chat.py                  # 问答（SSE）
│       └── document.py              # 上传 / 删除文档
├── ai_service/                      # 模块二：多模型接入网关（:8000）
│   ├── main.py                      # 路由 /generate /doubao_chat /providers
│   ├── config.py                    # 端口配置
│   ├── providers.py                 # 厂商配置 + Provider 抽象 + 路由
│   └── pyproject.toml               # 打包配置（包名 ai-service，命令入口 ai-service）
├── docs/
│   └── 知识库配置与启动清单.md        # 从零跑起来分步清单
├── requirements.txt                 # 依赖（FastAPI / Chroma / LangChain / openai / anthropic / 解析库）
├── .env.example                     # 环境变量模板（复制为 .env 填 Key）
├── .gitignore                       # 忽略 .env / venv / chroma_data / 日志 / 临时文件
└── README.md
```

---

## 五、相关信息获取地址（去哪里拿 Key / 文档）

### 1. 大模型厂商（ai_service 与各模型调用）
| 厂商 | API Key 获取地址（控制台） | 接口文档 |
|---|---|---|
| 阿里-通义千问 | https://dashscope.console.aliyun.com/ | https://help.aliyun.com/zh/dashscope/developer-reference/quick-start |
| 腾讯-混元 | https://console.cloud.tencent.com/hunyuan | https://cloud.tencent.com/document/product/1729 |
| 豆包-火山引擎 | https://console.volcengine.com/ark | https://www.volcengine.com/docs/82379/ |
| DeepSeek | https://platform.deepseek.com/ | https://api-docs.deepseek.com/zh-cn/ |
| OpenAI | https://platform.openai.com/ | https://platform.openai.com/docs/api-reference |
| Anthropic-Claude | https://console.anthropic.com/ | https://docs.anthropic.com/en/api/messages |

> 通义百炼 OpenAI 兼容端点：`https://dashscope.aliyuncs.com/compatible-mode/v1`（见 `kb/config.py` 与 `ai_service/providers.py`）。
> 以上地址同时可由 `GET /providers` 接口在运行时返回。

### 2. 知识库服务依赖
- **通义百炼**（qwen 对话 + text-embedding-v3 向量化）：见上表「阿里-通义千问」；需在「模型广场」开通 `qwen-turbo`、`text-embedding-v3` 并保有额度。
- **Chroma**（本地向量库，随 `pip install` 自动安装，无需注册）。
- **Java 后端 aicontent**（:8080，代理 + JWT 校验，独立仓库）。

### 3. 本仓库文档
- 从零跑起来（配置 + 启动分步）：[`docs/知识库配置与启动清单.md`](./docs/知识库配置与启动清单.md)
- 接口自动文档（服务启动后）：`http://localhost:8002/docs`、`http://localhost:8000/docs`

---

## 六、快速开始（两个模块一起跑）

```bash
cd kb
# 0. 准备通义百炼 API Key（必填）：
#    打开 https://dashscope.console.aliyun.com/ → 右上角 API-KEY → 创建
#    并在「模型广场」开通 qwen-turbo、text-embedding-v3（需有额度）

# 1. 虚拟环境（建议 Python 3.10+；本机 3.8.9 可跑但兼容性边缘）
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 2. 装依赖（二选一）
#    方式 A：一次性装全部（最简单，只跑服务用这个即可）
pip install -r requirements.txt
#    方式 B：按包安装（更规范，每个模块是独立可分发包，并生成命令行入口）
#    注意：务必在“已激活的虚拟环境”里执行，否则会装到系统 Python，
#         命令入口不在 PATH 上，导致 kb-server / ai-service 敲不出来。
#    -e 为可编辑安装（editable）：改代码即时生效，无需重装。
pip install -e ./kb -e ./ai_service

# 3. 配置密钥
cp .env.example .env              # 编辑 .env，把 DASHSCOPE_API_KEY 等改成你的真实 Key

# 4. 启动两个服务（各开一个独立窗口常驻）
uvicorn kb.main:app --host 0.0.0.0 --port 8002 --reload
uvicorn ai_service.main:app --host 0.0.0.0 --port 8000 --reload

# 若用方式 B 安装，可直接用包提供的命令入口启动（等价于上面的 uvicorn）：
#   kb-server        # 由 kb/pyproject.toml 的 [project.scripts] 生成，端口读 KB_PORT
#   ai-service       # 由 ai_service/pyproject.toml 的 [project.scripts] 生成，端口读 AI_SERVICE_PORT
# 命令入口安装在 <venv>/Scripts/（Windows）或 <venv>/bin/（Linux/macOS），
# 需先激活该 venv 才能直接调用；用 `where kb-server`（Windows）/ `which kb-server` 可确认位置。
```

---

## 七、部署为独立仓库（推送到 GitHub）

本目录是独立 git 仓库，推送到 `https://github.com/lhy157/knowledge-base.git`：

```bash
cd kb
git add -A
git commit -m "feat: 知识库 + 多模型接入 monorepo (FastAPI + Chroma + 通义)"
git branch -M main
git remote add origin https://github.com/lhy157/knowledge-base.git
git push -u origin main        # 用户名 lhy157，密码处粘贴 GitHub Personal Access Token
```

> 注意：`.env`（真实 Key）、`venv/`、`chroma_data/`（向量）、`*.log`、`.tmp/` 已在 `.gitignore` 中忽略，不会上传。
> 拉取后在本地 `cp .env.example .env` 填 Key 即可运行。

---

## 八、连通性自测脚本（排错专用，长期保留）

仓库内置 `scripts/test_tencent_conn.py`，**不依赖 kb-server 进程**，直接调用底层接口独立验证「kb 服务 → 腾讯云向量库」的连通性与读写/检索能力，跑完自动清理测试数据。日常排错、换机器部署、升级 SDK 后都建议先跑一遍。

```bash
cd kb
# 用默认测试库 990001 验证（写入并删除一条 __selftest__ 临时文档，不影响真实数据）
python scripts/test_tencent_conn.py

# 验证指定的真实知识库
python scripts/test_tencent_conn.py --library-id 7

# 顺带验证 chroma 后端
python scripts/test_tencent_conn.py --also-chroma
```

脚本会逐项打印 `[PASS]/[FAIL]`：配置读取 → 向量库连通/列 collection → add_chunks（服务端 embedding）→ 统计 → query 语义检索 → get_document_chunks → delete_document 清理。退出码 0 = 全部通过，1 = 有失败项（脚本末尾会给出常见修复提示）。

---

## 九、部署与启动完整说明

### 9.1 前置要求

| 项 | 说明 |
|---|---|
| Python | 建议 **3.10+**；本机 3.8.9 已验证可跑（但 chromadb / tcvectordb 对 3.8 兼容性边缘，推荐升级） |
| 依赖 | `kb/requirements.txt`（FastAPI / Chroma / LangChain / openai / anthropic / 文档解析 / tcvectordb） |
| 密钥 | `DASHSCOPE_API_KEY`（通义百炼，qwen 对话 + 可选 chroma 向量化）；腾讯云向量库 `TENCENT_VECTOR_*`；ai_service 各家 Key |
| Java 侧 | `aicontent`(:8080) 已运行并含 `KbController`，通过 `kb.python-url`（默认 `http://localhost:8002`）转发 |

### 9.1.1 建库建表（MySQL 前置）

知识库所需的元信息表（`kb_library` / `kb_document`）位于 **Java 侧 MySQL 库 `ai_content`** 中（与 `aicontent` 共用同一库）。建表脚本在仓库根 `docs/`（`lhy-gzh/docs/`），执行顺序务必为「先 `init.sql` → 再 `extend.sql` → 最后 `kb.sql`」：

```bash
# 路径相对仓库根（lhy-gzh/）；若当前在 kb/ 目录则改为 ../docs/init.sql
mysql -uroot -p ai_content < docs/init.sql      # 建库建表（user/template/generation_history/user_oauth/pay_order/pay_refund 等）
mysql -uroot -p ai_content < docs/extend.sql    # 扩展 DDL（模板模式/用户公众号/任务/订阅/素材库）
mysql -uroot -p ai_content < docs/kb.sql        # 知识库表（kb_library / kb_document）
```

- 三个脚本均用 `CREATE TABLE IF NOT EXISTS`，可**重复执行、不破坏已有数据**。
- 每个表、每个字段都带 `COMMENT`，便于后期维护；字段含义、枚举取值、外键关联均已写明。
- ⚠️ **补注释提醒**：若 `ai_content` 库**已先行创建（历史库）**，重跑上面脚本**不会更新已有字段的 `COMMENT`**（MySQL 的 `IF NOT EXISTS` 行为）。此时请额外执行脚本末尾的「为已存在表补字段注释」段落（`init.sql` 与 `kb.sql` 末尾已附 `ALTER ... MODIFY COLUMN ... COMMENT` 语句），可安全重复执行、直接覆盖原注释。

### 9.2 安装依赖

```bash
cd kb
python -m venv venv
venv\Scripts\activate            # Windows；Linux/macOS 用 source venv/bin/activate

# 方式 A：一次性装全部（推荐）
pip install -r requirements.txt

# 方式 B：按可编辑包安装（生成 kb-server / ai-service 命令入口）
pip install -e ./kb -e ./ai_service
```

> **Windows + Python 3.8 装 `tcvectordb` 会整体回滚**（见本文「二、模块一」§3.1 末尾）。若 `pip install -r requirements.txt` 报 `tcvectordb` 相关编译错误，改用：
> ```bash
> pip install --no-deps tcvectordb
> pip install --no-deps cos-python-sdk-v5
> pip install ujson cachetools
> ```

### 9.3 配置 `.env`

复制模板并填写（关键项已加注释，详见 `.env.example`）：

```bash
cp .env.example .env
```

- **Chroma 后端（默认，本地）**：`VECTOR_BACKEND=chroma`，需填 `DASHSCOPE_API_KEY`（客户端向量化）。
- **腾讯云后端（线上，服务端 embedding）**：`VECTOR_BACKEND=tencent`，填 `TENCENT_VECTOR_URL/USERNAME/KEY/DATABASE` 与 `TENCENT_EMBEDDING_MODEL`（默认 `multilingual-e5-base`，维度 768）。
- 端口：`KB_PORT=8002`（知识库）、`AI_SERVICE_PORT=8000`（多模型网关），互不冲突。

### 9.4 先跑连通性自测（强烈建议）

```bash
python scripts/test_tencent_conn.py --library-id <你的某个真实库ID>
# 全绿再启动服务；若红，按脚本提示修 .env / 网络 / SDK
```

### 9.5 启动服务

每个服务各开一个**常驻窗口**：

```bash
# 知识库 RAG 服务（:8002）
uvicorn kb.main:app --host 0.0.0.0 --port 8002 --log-level info

# 多模型接入网关（:8000，可选，前端/其他服务才用到）
uvicorn ai_service.main:app --host 0.0.0.0 --port 8000 --log-level info
```

- 健康检查：`GET http://localhost:8002/kb/health` → `{"status":"ok","service":"kb-server","port":8002}`
- 自动 API 文档：`http://localhost:8002/docs`、`http://localhost:8000/docs`
- 若用「方式 B」安装过，也可直接 `kb-server` / `ai-service`（端口读 `KB_PORT` / `AI_SERVICE_PORT`）。

> ⚠️ **进程常驻**：在交互终端前台启动的服务会随窗口关闭 / SSH 断开而退出。生产环境必须用下方守护方式。

### 9.6 生产守护（systemd / supervisor 示例）

以 kb-server 为例（`/opt/kb` 为仓库根，`venv` 已建好）：

```ini
# /etc/systemd/system/kb-server.service
[Unit]
Description=KB RAG Server
After=network.target

[Service]
WorkingDirectory=/opt/kb
ExecStart=/opt/kb/venv/bin/python -m uvicorn kb.main:app --host 127.0.0.1 --port 8002
Restart=always
User=www-data

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now kb-server
curl -s http://127.0.0.1:8002/kb/health
```

> 知识库服务**只应监听内网 / 127.0.0.1**，由 `aicontent` 经内网转发，不要暴露到公网 0.0.0.0（除非有内网隔离）。

### 9.7 与 Java 联动验证

1. 确认 `aicontent` 的 `application.yml` 中 `kb.python-url: ${KB_PYTHON_URL:http://localhost:8002}` 指向实际地址（跨机部署设环境变量 `KB_PYTHON_URL=http://<ip>:8002` 后重启 aicontent）。
2. 前端 `:5173` 登录 → 「知识库」→ 新建库 → 上传 `.txt/.md/.pdf` → 问答测试（应流式返回并标注来源）。
3. 命令行冒烟（已有 JWT 时）：

```bash
curl -X POST http://localhost:8080/api/kb/chat \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"libraryId":<库ID>,"question":"你的文档里的问题"}'
# 返回 text/event-stream，逐行 data: {"type":"content","text":"..."}
```

### 9.8 常见问题速查

| 现象 | 排查 |
|---|---|
| 启动报 `DASHSCOPE_API_KEY` / 腾讯云 Key 错误 | 确认 `.env` 已填且路径正确（`kb/config.py` 读取仓库根 `.env`） |
| `ImportError: No module named tcvectordb` | 按 9.2 的 `--no-deps` 方式补装 |
| 上传后 `chunkCount=0` | 扫描版 PDF / 图片无文本层；或格式未支持 |
| 问答返回 `error` | 查通义 Key 额度 / 网络；看 Python 控制台堆栈 |
| `curl :8002/health` 连不上 | Python 服务没启动 / 端口被占，回到 9.5 |
| 前端 502 Bad Gateway | aicontent 转发到 kb-server 失败，见 `docs/知识库部署与运维清单.md` 第二节 |
| 切回 chroma 后维度报错 | `EMBEDDING_DIM` 改用 chroma 对应值（text-embedding-v3 合法 64/128/256/512/768/1024） |

---

## 十、目录结构总览（更新）

```
kb/                                  # 仓库根（monorepo）
├── kb/                              # 模块一：知识库 RAG 服务（:8002，包名 kb）
│   ├── main.py                      # FastAPI 入口 + /kb/health
│   ├── config.py                    # 配置（通义 Key / 端口 / 向量后端 / 腾讯云 / 模型）
│   ├── schemas.py                   # Pydantic 请求模型
│   ├── llm.py                       # 通义 qwen 流式 + text-embedding-v3（chroma 后端用）
│   ├── loader.py                    # 文档解析（pdf/docx/xlsx/md/txt）
│   ├── splitter.py                  # 中文切分
│   ├── vectorstore.py               # 向量存储门面（按 VECTOR_BACKEND 切换 chroma/tencent）
│   ├── vectorstore_chroma.py        # Chroma 后端实现
│   ├── vectorstore_tencent.py       # 腾讯云向量库后端实现（服务端 embedding）
│   ├── rag.py                       # 检索 + 拼 prompt + 流式生成
│   ├── pyproject.toml               # 打包配置（包名 kb-server，命令入口 kb-server）
│   ├── chroma_data/                 # 向量持久化（仅 chroma 后端用，gitignore）
│   └── routers/
│       ├── chat.py                  # 问答（SSE）
│       └── document.py              # 上传 / 删除 / 统计 / 切片查看
├── ai_service/                      # 模块二：多模型接入网关（:8000）
│   ├── main.py                      # 路由 /generate /doubao_chat /providers
│   ├── config.py                    # 端口配置
│   ├── providers.py                 # 厂商配置 + Provider 抽象 + 路由
│   └── pyproject.toml               # 打包配置（包名 ai-service，命令入口 ai-service）
├── scripts/
│   └── test_tencent_conn.py         # 腾讯云向量库连通性自测（排错用，长期保留）
├── docs/
│   └── 知识库配置与启动清单.md        # 从零跑起来分步清单（Java 侧视角）
├── requirements.txt                 # 依赖
├── .env.example                     # 环境变量模板（复制为 .env 填 Key）
├── .gitignore                       # 忽略 .env / venv / chroma_data / 日志 / 临时文件
└── README.md
```

> 注：早期版本曾用 `kb/app/` 作为知识库包名，现已统一为 `kb/kb/`（包名 `kb`），启动命令为 `uvicorn kb.main:app`。如仓库中仍残留 `kb/app/` 目录（无 `__init__.py`、属历史遗留），请直接删除，不要引用。
