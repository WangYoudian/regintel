# RegIntel AI — v3 Detailed Design

> Celery + Redis 异步编排 · 后台管线 · 前端进度轮询

---

## 一、系统模块与服务关系图

```mermaid
graph TB
    subgraph Client["客户端"]
        B["浏览器<br/>HTML + HTMX + Chart.js"]
    end

    subgraph Docker["Docker Compose"]
        direction TB
        FA["regintel-app<br/>FastAPI + Uvicorn"]
        RD["redis<br/>7-alpine"]
        CW["celery-worker<br/>--concurrency=2"]
        PG["postgres<br/>pgvector/pg16"]
    end

    subgraph FastAPI["FastAPI 应用"]
        R["Routers"]
        T["Templates<br/>Jinja2 + HTMX"]
    end

    subgraph Task["任务层 (新增)"]
        TK["tasks.py<br/>Celery 任务定义"]
    end

    subgraph Services["服务层 (v1/v2 复用)"]
        PL["pipeline.py<br/>+ 逐级写进度"]
        SVC["其余 8 个服务文件<br/>(不变)"]
    end

    subgraph DB["数据层"]
        REPO["repository.py<br/>+ progress 读写"]
        CONN["connection.py"]
    end

    B -- HTTP --> FA

    FA --> R
    R --> T
    R --> PL

    PL --> SVC

    FA -- enqueue --> RD
    RD -- dequeue --> CW
    CW --> TK
    TK --> PL

    PL --> REPO
    REPO --> CONN
    CONN --> PG
    PL --> REPO

    style Client fill:#e1f5fe
    style Docker fill:#fff3e0
    style FastAPI fill:#f3e5f5
    style Task fill:#ffcdd2
    style Services fill:#e8f5e9
    style DB fill:#e0f7fa
```

**关键数据流（同步 vs 异步对比）：**

```text
v2 (同步):  POST /api/analyze ──▶ pipeline.run() ──────────────────▶ 30-60s 后返回

v3 (异步):  POST /api/analyze ──▶ enqueue Celery ──▶ 50ms 返回 {run_id}
                                       │
                                  ┌────▼────┐
                                  │  Redis  │
                                  └────┬────┘
                                       │
                                  ┌────▼────┐
                                  │  Worker │ ──▶ pipeline.run() ──▶ 每步写 DB
                                  └─────────┘

前端:       POST 返回 → 跳转进度页 → HTMX 每 2s 轮询 → 自动切为看板
```

---

## 二、ER 图变更

仅 `analysis_runs` 表新增一个字段：

```mermaid
erDiagram
    analysis_runs {
        uuid id PK
        uuid regulation_id FK
        varchar status "processing / completed / failed"
        jsonb progress "新增! {step, percent}"
        text summary
        timestamptz created_at
    }
```

```sql
-- v3 变更
ALTER TABLE analysis_runs
    ADD COLUMN progress JSONB NOT NULL DEFAULT '{"step": "", "percent": 0}';

-- 数据示例
-- {"step": "Matching controls", "percent": 55}
-- {"step": "Complete", "percent": 100}
```

其余 7 张表不变。

---

## 三、UML 类图（新增/变更类）

### 3.1 任务定义 (`app/tasks.py`)

```mermaid
classDiagram
    class CeleryApp {
        +str name
        +str broker "redis://redis:6379/0"
        +str backend
        +task()
        +conf
    }

    class RunAnalysisTask {
        +bind=True
        +max_retries=3
        +default_retry_delay=60
        +run(run_id: str)
        +on_failure(exc, task_id, args, kwargs, einfo)
    }

    class AutoPullRegulationsTask {
        +schedule "预留, v3.1 实现"
        +run()
    }

    CeleryApp --> RunAnalysisTask : registers
    CeleryApp --> AutoPullRegulationsTask : registers
```

### 3.2 Pipeline 变更 (`services/pipeline.py`)

```mermaid
classDiagram
    class RegIntelPipeline {
        +run(run_id) AnalysisReport
        +_progress(run_id, step, percent)
        +_update_progress_in_db(run_id, progress)
    }

    note for RegIntelPipeline: 每步执行后调用 _progress()<br/>更新 DB 中的 progress 字段
```

### 3.3 Router 变更 (`routers/upload.py`)

```mermaid
classDiagram
    class UploadRouter {
        +POST /api/analyze
        +_create_analysis_run(reg_id) UUID
        +_enqueue_task(run_id)
        +__init__()
    }

    note for UploadRouter: run_analysis_task.delay(run_id)<br/>代替直接 pipeline.run()<br/>响应时间从 30-60s 降至 50ms
```

### 3.4 新增 Progress Router (`routers/analysis.py`)

```mermaid
classDiagram
    class AnalysisRouter {
        +GET /api/analyses
        +GET /api/analyses/{id}
        +DELETE /api/analyses/{id}
        +GET /api/analyses/{id}/progress
    }

    class ProgressResponse {
        +str status
        +dict progress
        +Optional~HTMLResponse~ dashboard
    }

    AnalysisRouter --> ProgressResponse : returns
```

---

## 四、核心时序图

### 4.1 异步全流程

```mermaid
sequenceDiagram
    actor User as 用户
    participant F as FastAPI
    participant RD as Redis
    participant CW as Celery Worker
    participant R as Repository
    participant DB as PostgreSQL

    User->>F: POST /api/analyze (file)

    F->>R: save_regulation(conn, reg)
    R->>DB: INSERT INTO regulations
    F->>R: create_analysis_run(conn, reg_id)
    R->>DB: INSERT INTO analysis_runs

    F->>RD: run_analysis.delay(run_id)
    Note over F,RD: enqueue → 50ms

    F-->>User: 200 {run_id, status:"processing", redirect_url}

    Note over User: 浏览器跳转进度页

    User->>F: GET /analyses/{run_id}

    loop 每 2s (HTMX poll)
        User->>F: GET /api/analyses/{run_id}/progress
        F->>R: get_analysis_run(conn, run_id)
        R-->>F: {status, progress}
        F-->>User: HTML 进度条 / HTML 看板
    end

    Note over CW: Celery Worker 在后台执行

    RD-->>CW: dequeue run_analysis task
    CW->>R: update_progress(conn, run_id, {"Parsing", 5})
    CW->>CW: parser.parse()
    CW->>R: update_progress(conn, run_id, {"Extracting", 20})
    CW->>CW: extractor.extract()
    CW->>R: save_obligations(conn, obligations)
    CW->>R: update_progress(conn, run_id, {"Embedding", 35})
    CW->>CW: embedder.embed_batch()
    CW->>R: update_progress(conn, run_id, {"Matching", 55})
    CW->>CW: matcher.match_all()
    CW->>R: save_mappings(conn, mappings)
    CW->>R: update_progress(conn, run_id, {"Analyzing", 75})
    CW->>CW: gap_analyzer.analyze()
    CW->>R: save_gaps(conn, gaps)
    CW->>R: update_progress(conn, run_id, {"Recommendations", 90})
    CW->>CW: recommender.generate()
    CW->>R: save_recommendations(conn, recs)
    CW->>R: update_run_status(conn, run_id, "completed")
    CW->>R: update_progress(conn, run_id, {"Complete", 100})
```

### 4.2 HTMX 轮询子流程

```mermaid
sequenceDiagram
    participant B as 浏览器 (HTMX)
    participant F as FastAPI
    participant R as Repository
    participant DB as PostgreSQL

    Note over B: 页面加载时,<br/>进度条区域有 hx-trigger="every 2s"

    B->>F: GET /api/analyses/{id}/progress
    F->>R: get_analysis_run(conn, id)
    R->>DB: SELECT status, progress FROM analysis_runs WHERE id = %s
    DB-->>R: {status:"processing", progress:{step:"Matching", percent:55}}
    R-->>F: run dict

    alt status == "processing"
        F-->>B: <div id="progress-section"><br/>  进度条 55% "Matching"<br/></div>
        Note over B: hx-trigger 仍在 DOM 中,<br/>2s 后继续轮询
    else status == "completed"
        F-->>B: <div id="results-section"><br/>  完整看板 HTML<br/></div>
        Note over B: 返回的 HTML 不带 hx-trigger<br/>轮询自动停止
    end
```

### 4.3 并发任务调度

```mermaid
sequenceDiagram
    participant FA as FastAPI
    participant RD as Redis

    FA->>RD: run_analysis.delay(run_id_1)
    FA->>RD: run_analysis.delay(run_id_2)
    FA->>RD: run_analysis.delay(run_id_3)

    Note over RD: Redis 队列<br/>[task_1, task_2, task_3]

    participant CW1 as Worker (concurrency=2)
    participant CW2 as Worker (concurrency=2)

    RD-->>CW1: dequeue task_1
    RD-->>CW2: dequeue task_2

    Note over CW1: 分析 run_id_1
    Note over CW2: 分析 run_id_2

    CW1-->>RD: 完成, ack

    RD-->>CW1: dequeue task_3

    Note over CW1: 分析 run_id_3
```

---

## 五、Docker Compose 变更

```yaml
services:
  regintel-app:
    # ... (同 v2)
    environment:
      - DATABASE_URL=postgresql://regintel:regintel@postgres:5432/regintel
      - REDIS_URL=redis://redis:6379/0                    # ← 新增
      - LLM_API_ENDPOINT=${LLM_API_ENDPOINT}
      - LLM_API_KEY=${LLM_API_KEY}
    depends_on:
      postgres:
        condition: service_healthy
      redis:                                               # ← 新增
        condition: service_started

  postgres:
    # ... (同 v2, 无变化)

  redis:                                                   # ← 新增
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5
    restart: unless-stopped

  celery-worker:                                           # ← 新增
    build: .
    command: celery -A app.tasks worker --loglevel=info --concurrency=2
    environment:
      - DATABASE_URL=postgresql://regintel:regintel@postgres:5432/regintel
      - REDIS_URL=redis://redis:6379/0
      - LLM_API_ENDPOINT=${LLM_API_ENDPOINT}
      - LLM_API_KEY=${LLM_API_KEY}
    volumes:
      - uploads_data:/app/data/uploads
    depends_on:
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
    restart: unless-stopped

volumes:
  postgres_data:
  uploads_data:
  redis_data:                                              # ← 新增
```

---

## 六、目录结构变更

```
regintel/
├── ... (同 v2)
│
├── app/
│   ├── main.py                  # 变更: +Redis 连接初始化
│   ├── config.py                # 变更: +REDIS_URL
│   ├── tasks.py                 # ← 新增: Celery 任务定义 + 调度预留
│   │
│   ├── routers/
│   │   ├── upload.py            # 变更: delay() 替代同步 run()
│   │   ├── analysis.py          # 变更: +progress 端点
│   │   └── ...
│   │
│   ├── services/
│   │   ├── pipeline.py          # 变更: 每步调用 _progress() 写 DB
│   │   └── ...                  # 其余不变
│   │
│   ├── db/
│   │   └── repository.py        # 变更: +update_progress(), +get_progress()
│   │
│   └── templates/
│       └── dashboard.html       # 变更: +进度条 HTMX 轮询
│
├── docker-compose.yml           # 变更: +redis, +celery-worker
├── .env.example                 # 变更: +REDIS_URL
├── pyproject.toml               # 变更: +celery, +redis
│
├── design/
│   ├── v1/
│   ├── v2/
│   └── v3/
│       └── Detailed-Design.md   # 本文件
```

---

## 七、配置新增

```python
# app/config.py (新增字段)
REDIS_URL: str = "redis://redis:6379/0"
```

```bash
# .env.example (新增)
REDIS_URL=redis://redis:6379/0
```

```toml
# pyproject.toml (新增依赖)
dependencies = [
    # ... v2 依赖不变 ...
    "celery>=5.4",
    "redis>=5.0",
]
```

---

## 八、pyproject.toml（完整 v3）

```toml
[project]
name = "regintel"
version = "0.3.0"
description = "AI-powered compliance assistant (v3)"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "sentence-transformers>=3.0",
    "PyMuPDF>=1.24",
    "python-docx>=1.1",
    "httpx>=0.27",
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "jinja2>=3.1",
    "python-multipart>=0.0.12",
    "aiofiles>=24.1",
    "psycopg2-binary>=2.9.9",
    "pgvector>=0.3.0",
    "celery>=5.4",              # ← v3 新增
    "redis>=5.0",               # ← v3 新增
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

---

## 九、v2 → v3 演进要点

| 维度 | v2 (同步) | v3 (异步) | 迁移影响 |
|------|-----------|-----------|----------|
| API 响应 | 30-60s 阻塞 | 50ms 立即返回 | upload.py 改一行 (delay) |
| 管线执行 | FastAPI 进程内 | Celery Worker 后台 | 新增 tasks.py + pipeline 加进度调用 |
| 进度反馈 | 无 (白屏等待) | DB progress 字段 + HTMX 轮询 | analysis.py 新增端点 + dashboard.html 改模板 |
| 消息队列 | 无 | Redis (broker) | 新增 redis + celery-worker 服务 |
| 并发能力 | 单任务 | --concurrency=2, 可水平扩展 | 加 worker 容器即可 |
| 失败重试 | 用户手动重来 | max_retries=3, 60s 间隔 | Celery 内置 |
| services/ | 所有服务 | 同 v2 | **仅 pipeline.py 改 1 个方法 (加 _progress)** |
| models/ | 所有模型 | 同 v2 | **零改动** |
| data/ | Mock 数据 | 同 v2 | **零改动** |

---

## 十、前端 HTMX 轮询代码片段

```html
<!-- dashboard.html — 进度条区域 -->
{% if analysis.status != "completed" %}
<div id="progress-section"
     hx-get="/api/analyses/{{ analysis.id }}/progress"
     hx-trigger="every 2s"
     hx-target="#progress-section"
     hx-swap="outerHTML">
  <div class="card">
    <div class="card-body">
      <h5 class="card-title">分析进行中</h5>
      <div class="progress" style="height: 28px;">
        <div class="progress-bar progress-bar-striped progress-bar-animated"
             role="progressbar"
             style="width: {{ analysis.progress.percent }}%">
          {{ analysis.progress.step }}
          ({{ analysis.progress.percent }}%)
        </div>
      </div>
      <div class="mt-2 text-muted small">
        <span class="spinner-border spinner-border-sm" role="status"></span>
        自动更新中，每 2 秒刷新
      </div>
    </div>
  </div>
</div>
{% endif %}

<!-- 完成后: progress 端点返回完整看板, 此 HTML 被替换掉 -->
<!-- 无 hx-trigger → 轮询停止 -->
{% if analysis.status == "completed" %}
<div id="results-section">
  <!-- 完整结果看板: 覆盖度图表 + 义务列表 + 匹配矩阵 + 差距 + 建议 -->
</div>
{% endif %}
```

---

## 修订记录

| 版本 | 日期 | 变更说明 |
|------|------|----------|
| v3.0 | 2026-06-29 | 异步编排详细设计: Celery + Redis + 进度轮询 |
