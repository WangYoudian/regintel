# RegIntel AI

GenAI + NLP 驱动的合规助手。自动解析监管文件，提取合规义务，语义匹配内控措施，识别差距并生成整改建议。

---

## 核心目录（版本间复用）

| 目录 | 说明 |
|------|------|
| `services/` | 核心管线：解析 → 提取 → 匹配 → 分析 → 建议，版本间不重写 |
| `models/` | Pydantic 数据模型，版本间不重写 |
| `data/` | Mock 内控库 + 示例监管文件，版本间不重写 |

---

## 快速启动

选择当前使用的版本执行：

| 版本 | 启动命令 | 前置条件 |
|------|----------|----------|
| **v1** (当前) | `uv run streamlit run app.py` | Python >= 3.12 + uv |
| v2 | `docker compose up` | Docker + Docker Compose |
| v3 | `docker compose up` | 同上 |
| v3.1 | `docker compose up` + `celery worker` | 同上 |

## 配置

各版本的配置项和说明见对应设计文档：

| 版本 | 配置文件 | 设计文档 |
|------|----------|----------|
| **v1** | `config.py` (LLM API endpoint/key) | `design/v1/Detailed-Design.md` |
| v2 | `.env` (LLM + DATABASE_URL) | `design/v2/` |
| v3 | `.env` (LLM + DATABASE_URL + REDIS_URL) | `design/v3/` |

---

## 项目结构

```
regintel/
├── services/              # 核心管线 (版本间复用)
├── models/                # 数据模型 (版本间复用)
├── data/                  # Mock 数据 (版本间复用)
│
├── design/                # 架构设计文档
│   ├── v1/                #   v1 详细设计
│   └── ...
│
├── ARCHITECTURE.md        # 架构设计总览 (全版本)
└── README.md              # 本文件
```

更多文件见各版本的详细设计文档。

---

## 依赖

| 包 | 用途 | 引入版本 |
|------|------|----------|
| streamlit | 前端 UI | v1 |
| pydantic | 数据模型 | v1 |
| sentence-transformers | Embedding 生成 | v1 |
| httpx | LLM API 调用 | v1 |
| fastapi / uvicorn | API 框架 | v2 |
| psycopg2-binary / pgvector | PostgreSQL 接入 | v2 |
| celery / redis | 异步任务队列 | v3 |

完整依赖清单见各版本的 `pyproject.toml`。

---

## 版本演进

| 版本 | 架构 | 状态 |
|------|------|------|
| **v1** | Streamlit + Session State + Mock | **当前** |
| v2 | FastAPI + PostgreSQL + Docker Compose | 规划 |
| v3 | +Celery + Redis 异步编排 | 规划 |
| v3.1 | +Airflow + Ansible 定时调度 | 规划 |

架构决策和版本演进详情见 `ARCHITECTURE.md`。各版本的详细设计（ER 图、时序图、UML 类图等）见 `design/<version>/Detailed-Design.md`。
