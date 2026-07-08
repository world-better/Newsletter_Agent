# 🔍 任意门聚合简报

> AI Agent 多源 RSS 聚合 → 自动生成结构化简报。输入主题，拿到带来源链接的简报。

**在线 Demo：** [部署中]

---

## 项目概述

这是一个基于 AI Agent 的智能信息聚合工具。用户通过 Web 界面输入关注的主题，AI Agent 自动从多个 RSS 订阅源抓取最新内容，整合生成一份带来源链接的结构化简报。

**核心价值：** 多源信息的一站式聚合，减少信息过载。适合技术招聘 HR、产品经理、开发者等需要快速了解行业动态的人。

**技术验证：** 36/36 端到端测试通过（3 种用户角色 × 10 个场景）。[测试报告](tests/test_log.md)

---

## 架构

```
Streamlit (Web UI)  ──httpx──→  FastAPI (API)  ──→  Agent (Agno)  ──→  SQLite
  :8501                         :8001              + RSS tools        persistent
```

**分层设计（热插拔）：**

```
app/
├── data/              ← Data Access Layer
│   └── db_service.py       SQLite — 换 PostgreSQL 只改此文件
├── services/          ← Agent Layer
│   ├── agent_core.py       工具定义 + Agent 工厂 — 换框架只改此文件
│   ├── agent_pipeline.py   事件翻译 + 流式 + 持久化 — 换框架只改此文件
│   ├── agent_context.py    上下文组装（纯数据，框架无关）
│   └── agent_service.py    超薄协议层（上游是 routes，下游是 pipeline）
├── routes/            ← HTTP Layer
│   └── messages.py         SSE 流式端点 — 从不 import agno
├── schemas.py              Pydantic 协议 schema — 框架无关
└── main.py                 启动入口，依赖注入
web/
├── app.py              ← Streamlit 前端（通过 httpx 调 API）
├── start.py            本地一键启动
└── start.sh            容器启动脚本
client.py               终端 CLI 客户端
Dockerfile              容器化部署
```

**热插拔原则：** 换 Agent 框架（Agno → LangChain 等）只需替换 `agent_core.py` + `agent_pipeline.py`。HTTP 层、数据层、Web 前端都不动。

---

## 工具清单

| 工具 | 说明 |
|------|------|
| `add_rss_subscription` | 添加 RSS 订阅源（高信心度要求） |
| `delete_rss_subscription` | 删除 RSS 订阅源 |
| `fetch_subscribed_feeds` | 遍历所有订阅源，抓取并聚合 RSS/Atom 内容 |

默认预置 6 个订阅源：HackerNews 头条、Show HN、NYT Technology、BBC Technology、知乎日报、V2EX 最新。

---

## 快速开始

### 本地开发

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env   # 编辑 .env 填入 OPENROUTER_API_KEY

# 3. 一键启动
python web/start.py

# 或者分别启动
uvicorn app.main:app --port 8001 --reload
streamlit run web/app.py --server.port 8501
```

浏览器打开 `http://localhost:8501`

### Docker

```bash
docker build -t newsletter-agent .
docker run -p 8501:8501 -e OPENROUTER_API_KEY=your-key newsletter-agent
```

### CLI 客户端

```bash
python client.py -u 1    # 选 persona #1，命令行交互
```

---

## 运行测试

```bash
# 端到端测试（启动服务 → 模拟 3 个真实用户 → 验证 DB）
python tests/test_web_e2e.py

# 后端验证
python tests/test_phase1.py
```

[测试报告 →](tests/test_log.md)

---

## 部署到 Sealos

1. Push 代码到 GitHub
2. 登录 [Sealos](https://hzh.sealos.run/) → 应用管理 → 部署源码
3. 连接仓库，Sealos 自动读取 `Dockerfile` 构建
4. 环境变量设置 `OPENROUTER_API_KEY` 和 `OPENROUTER_MODEL_ID`
5. 暴露端口 `8501` → 拿到公网 URL

---

## 技术栈

| 层 | 技术 | 可替换为 |
|----|------|---------|
| Agent | Agno 2.6 + DeepSeek V4 Flash | LangChain, CrewAI |
| API | FastAPI + SSE | 任何 Python 框架 |
| 前端 | Streamlit | Gradio, Next.js |
| 数据库 | SQLite (WAL) | PostgreSQL (改 1 个文件) |
| 模型 API | OpenRouter | 直接 DeepSeek/OpenAI API |
