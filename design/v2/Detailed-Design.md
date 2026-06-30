# RegIntel AI — v2 Detailed Design

> FastAPI + PostgreSQL + pgvector + Docker Compose + Jinja2/HTMX
> 持久化存储，标准 API 层，容器化部署

---

## 一、系统模块与服务关系图

```mermaid
graph TB
    subgraph Client["客户端"]
        B["浏览器<br/>HTML + HTMX + Chart.js"]
        API_C["第三方 API 调用"]
    end

    subgraph Infrastructure["基础设施 (Docker Compose)"]
        direction LR
        FA["regintel-app<br/>Uvicorn + FastAPI"]
        PG["postgres<br/>pgvector/pg16"]
    end

    subgraph FastAPI_Layer["FastAPI 应用层"]
        direction TB
        Router["Routers<br/>HTTP 校验 + 响应"]
        Jinja["Jinja2 Templates<br/>HTML 渲染"]
    end

    subgraph Service_Layer["服务层 (v1 复用)"]
        PL["pipeline.py<br/>管线编排"]
        DP["document_parser.py<br/>文档解析"]
        LLM["llm_client.py<br/>LLM API 客户端"]
        CE["compliance_extractor.py<br/>合规义务提取"]
        ES["embedding_service.py<br/>Embedding 生成"]
        MT["matcher.py<br/>语义匹配"]
        GA["gap_analyzer.py<br/>差距分析"]
        RE["recommendation_engine.py<br/>建议生成"]
        RG["report_generator.py<br/>报告生成"]
    end

    subgraph DB_Layer["数据库层"]
        Repo["repository.py<br/>psycopg2 raw SQL"]
        Conn["connection.py<br/>连接池管理"]
    end

    subgraph Models["数据模型层"]
        DM["domain.py<br/>Pydantic 领域模型"]
        SCHEMA["schemas.py<br/>API 请求/响应 Schema"]
    end

    B -- "HTTP/HTTPS" --> Router
    API_C -- "HTTP/JSON" --> Router

    Router --> Jinja
    Router --> PL

    PL --> DP
    PL --> CE
    PL --> ES
    PL --> MT
    PL --> GA
    PL --> RE
    PL --> RG

    CE --> LLM
    GA --> LLM
    RE --> LLM

    PL --> Repo
    Repo --> Conn
    Conn --> PG

    Router --> SCHEMA
    SCHEMA --> DM
    PL --> DM
    Repo --> DM
    PL --> MT

    style Client fill:#e1f5fe
    style Infrastructure fill:#fff3e0
    style FastAPI_Layer fill:#f3e5f5
    style Service_Layer fill:#e8f5e9
    style DB_Layer fill:#ffebee
    style Models fill:#e0f7fa
```

**服务依赖图：**

```text
浏览器 ──HTTP──▶ regintel-app ──▶ PostgreSQL (pgvector)
                            │
                     ┌──────┴──────┐
                     │  Services/  │ (与 v1 共用)
                     │  Models/    │ (与 v1 共用)
                     │  Data/      │ (与 v1 共用)
                     └─────────────┘
```

---

## 二、ER 图（PostgreSQL 表结构）

```mermaid
erDiagram
    internal_controls ||--o{ mapping_results : matches
    regulations ||--o{ obligations : contains
    regulations ||--o{ analysis_runs : triggers
    obligations ||--o{ mapping_results : maps_to
    analysis_runs ||--o{ mapping_results : includes
    mapping_results ||--o{ gap_analyses : leads_to
    gap_analyses ||--o{ recommendations : generates

    internal_controls {
        uuid id PK
        varchar name
        text description
        varchar category "Access Control / Data Protection / ..."
        varchar frequency "Daily / Weekly / Quarterly / ..."
        varchar owner
        varchar status "Active / Draft / Deprecated"
        vector embedding "pgvector, 384维"
    }

    regulations {
        uuid id PK
        varchar title
        varchar source "FCA / PRA / MAS / RBI"
        date published_date
        text content
        text summary
        varchar file_path
        timestamptz created_at
    }

    obligations {
        uuid id PK
        uuid regulation_id FK
        text description
        varchar source_ref "条款编号"
        varchar category
        varchar risk_level "High / Medium / Low"
        vector embedding "pgvector, 384维"
        timestamptz created_at
    }

    analysis_runs {
        uuid id PK
        uuid regulation_id FK
        varchar status "processing / completed / failed"
        text summary
        timestamptz created_at
    }

    mapping_results {
        uuid id PK
        uuid analysis_run_id FK
        uuid obligation_id FK
        uuid control_id FK
        float similarity_score
        varchar coverage_status "covered / partial / missing"
        timestamptz created_at
    }

    gap_analyses {
        uuid id PK
        uuid mapping_result_id FK
        text gap_description
        text risk_impact
        timestamptz created_at
    }

    recommendations {
        uuid id PK
        uuid gap_analysis_id FK
        jsonb action_items
        varchar priority "High / Medium / Low"
        varchar estimated_effort
        timestamptz created_at
    }
```

**索引设计：**

```sql
-- pgvector IVFFlat 索引 (近似最近邻搜索)
CREATE INDEX idx_controls_embedding ON internal_controls
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- 外键索引 (加速 JOIN)
CREATE INDEX idx_obligations_regulation ON obligations(regulation_id);
CREATE INDEX idx_analysis_runs_regulation ON analysis_runs(regulation_id);
CREATE INDEX idx_mapping_results_run ON mapping_results(analysis_run_id);
CREATE INDEX idx_mapping_results_obligation ON mapping_results(obligation_id);
CREATE INDEX idx_gap_analyses_mapping ON gap_analyses(mapping_result_id);
CREATE INDEX idx_recommendations_gap ON recommendations(gap_analysis_id);
```

---

## 三、UML 类图

### 3.1 领域模型 (models/domain.py)

```mermaid
classDiagram
    class Regulation {
        +UUID id
        +str title
        +str source
        +date published_date
        +str content
        +str summary
        +str file_path
        +datetime created_at
        +summarize() str
    }

    class ComplianceObligation {
        +UUID id
        +UUID regulation_id
        +str description
        +str source_ref
        +str category
        +str risk_level
        +list~float~ embedding
        +datetime created_at
    }

    class InternalControl {
        +UUID id
        +str name
        +str description
        +str category
        +str frequency
        +str owner
        +str status
        +list~float~ embedding
    }

    class MappingResult {
        +UUID id
        +UUID analysis_run_id
        +UUID obligation_id
        +UUID control_id
        +float similarity_score
        +str coverage_status
        +datetime created_at
    }

    class GapAnalysis {
        +UUID id
        +UUID mapping_result_id
        +str gap_description
        +str risk_impact
        +datetime created_at
    }

    class Recommendation {
        +UUID id
        +UUID gap_analysis_id
        +list~str~ action_items
        +str priority
        +str estimated_effort
        +datetime created_at
    }

    class AnalysisRun {
        +UUID id
        +UUID regulation_id
        +str status
        +str summary
        +datetime created_at
    }

    class AnalysisReport {
        +UUID id
        +Regulation regulation
        +list~ComplianceObligation~ obligations
        +list~MappingResult~ mappings
        +list~GapAnalysis~ gaps
        +list~Recommendation~ recommendations
        +datetime generated_at
        +coverage_summary() dict
        +to_markdown() str
    }

    Regulation --> ComplianceObligation : contains
    Regulation --> AnalysisRun : triggers
    AnalysisRun --> MappingResult : includes
    MappingResult --> GapAnalysis : leads to
    GapAnalysis --> Recommendation : generates
    AnalysisReport --> Regulation : based on
```

### 3.2 API Schema (models/schemas.py)

```mermaid
classDiagram
    class AnalyzeRequest {
        +UploadFile file
        +bool use_sample
    }

    class AnalyzeResponse {
        +UUID run_id
        +str status
        +str progress_url
    }

    class HistoryItem {
        +UUID run_id
        +str title
        +str source
        +str status
        +datetime created_at
        +dict coverage_stats
    }

    class ProgressResponse {
        +str status
        +dict progress
    }

    class AnalysisDetailResponse {
        +Regulation regulation
        +list~ComplianceObligation~ obligations
        +list~MappingResult~ mappings
        +list~GapAnalysis~ gaps
        +list~Recommendation~ recommendations
        +dict coverage_summary
    }

    class ErrorResponse {
        +str detail
        +str error_code
    }

    AnalyzeRequest ..> AnalyzeResponse : produces
    AnalysisDetailResponse ..> HistoryItem : summarized by
```

### 3.3 服务类 (services/)

```mermaid
classDiagram
    class DocumentParser {
        +parse(file_path) Regulation
        +_parse_pdf(path) str
        +_parse_docx(path) str
    }

    class ComplianceExtractor {
        +LLMClient llm
        +extract(regulation) list~ComplianceObligation~
    }

    class EmbeddingService {
        +embed(text) list~float~
        +embed_batch(texts) list~list~float~~
    }

    class SemanticMatcher {
        +match(obligation, controls) list~MappingResult~
        +match_all(obligations, controls) list~MappingResult~
    }

    class GapAnalyzer {
        +LLMClient llm
        +analyze(mappings) list~GapAnalysis~
    }

    class RecommendationEngine {
        +LLMClient llm
        +generate(gaps) list~Recommendation~
    }

    class ReportGenerator {
        +generate(report) str
    }

    class RegIntelPipeline {
        -DocumentParser parser
        -ComplianceExtractor extractor
        -EmbeddingService embedder
        -SemanticMatcher matcher
        -GapAnalyzer gap_analyzer
        -RecommendationEngine recommender
        -ReportGenerator reporter
        +run(run_id) AnalysisReport
        +get_analysis(run_id) AnalysisReport
    }

    class LLMClient {
        +str endpoint
        +str api_key
        +chat(messages) str
        +chat_structured(messages, model) T
        +embed(text) list~float~
    }

    RegIntelPipeline --> DocumentParser : uses
    RegIntelPipeline --> ComplianceExtractor : uses
    RegIntelPipeline --> EmbeddingService : uses
    RegIntelPipeline --> SemanticMatcher : uses
    RegIntelPipeline --> GapAnalyzer : uses
    RegIntelPipeline --> RecommendationEngine : uses
    RegIntelPipeline --> ReportGenerator : uses
    ComplianceExtractor --> LLMClient : calls
    GapAnalyzer --> LLMClient : calls
    RecommendationEngine --> LLMClient : calls
```

### 3.4 数据库层 (db/)

```mermaid
classDiagram
    class ConnectionPool {
        +get_connection() connection
        +return_connection(conn)
        -_pool ThreadedConnectionPool
    }

    class AnalysisRepository {
        +init_schema(conn)
        +seed_controls(conn, controls)
        +save_regulation(conn, reg) UUID
        +save_obligations(conn, obligations, reg_id)
        +save_embeddings(conn, obligations)
        +save_mappings(conn, run_id, mappings)
        +save_gaps(conn, gaps)
        +save_recommendations(conn, recs)
        +get_analysis_run(conn, run_id) dict
        +get_analysis_detail(conn, run_id) AnalysisReport
        +get_analysis_history(conn, limit) list~dict~
        +find_similar_controls(conn, embedding, threshold, top_k) list~dict~
        +delete_analysis(conn, run_id)
    }

    ConnectionPool <.. AnalysisRepository : uses
```

### 3.5 API 路由 (routers/)

```mermaid
classDiagram
    class UploadRouter {
        +POST /api/analyze
        +POST /api/seed
    }

    class AnalysisRouter {
        +GET /api/analyses
        +GET "/api/analyses/:id"
        +DELETE "/api/analyses/:id"
    }

    class ReportRouter {
        +GET "/api/analyses/:id/report"
    }

    class PageRouter {
        +GET /
        +GET /analyses
        +GET "/analyses/:id"
    }

    class MainApp {
        +FastAPI app
        +lifespan()
        +include_routers()
        +serve_static()
    }

    MainApp --> UploadRouter : includes
    MainApp --> AnalysisRouter : includes
    MainApp --> ReportRouter : includes
    MainApp --> PageRouter : includes
    UploadRouter --> RegIntelPipeline : calls
    AnalysisRouter --> RegIntelPipeline : calls
    ReportRouter --> RegIntelPipeline : calls
    PageRouter --> RegIntelPipeline : calls
```

---

## 四、核心时序图

### 4.1 全流程：上传 → 分析 → 结果

```mermaid
sequenceDiagram
    actor User as 用户 (浏览器)
    participant F as FastAPI
    participant R as Repository
    participant PL as Pipeline
    participant LLM as LLM Client
    participant ES as Embedding
    participant MT as Matcher
    participant PG as PostgreSQL

    User->>F: POST /api/analyze (file/use_sample)

    F->>R: save_regulation(conn, reg)
    R->>PG: INSERT INTO regulations
    PG-->>R: regulation_id

    F->>R: create_analysis_run(conn, reg_id)
    R->>PG: INSERT INTO analysis_runs
    PG-->>R: run_id

    F->>PL: pipeline.run(run_id)
    PL-->>F: ✅ (background)

    F-->>User: 202 {run_id, status:"processing", progress_url}

    Note over User: 前端轮询进度

    loop every 2s
        User->>F: GET /api/analyses/{run_id}/progress
        F->>R: get_analysis_run(conn, run_id)
        R-->>F: {status, progress}
        alt status == "processing"
            F-->>User: 200 {progress}
        else status == "completed"
            F-->>User: HTML (看板页面)
        end
    end

    Note over PL: 后台管线执行

    PL->>PL: 更新进度 5% "Parsing"
    PL->>PL: _progress(run_id, "Parsing", 5)
    PL->>R: update_progress(conn, run_id, {step, percent})

    PL->>PL: parse(file_path) → Regulation
    PL->>R: update_progress(conn, run_id, {"Extracting", 20})

    PL->>LLM: chat_structured(extract obligations)
    LLM-->>PL: List[ComplianceObligation]
    PL->>R: save_obligations(conn, obligations)

    PL->>R: update_progress(conn, run_id, {"Embedding", 35})
    PL->>ES: embed_batch(obligations + controls)

    PL->>R: update_progress(conn, run_id, {"Matching", 55})
    PL->>MT: match_all(obligations, controls)
    MT->>PG: SELECT 1-(embedding <=> %s) >= 0.65 ...
    PG-->>MT: matched controls
    MT-->>PL: List[MappingResult]
    PL->>R: save_mappings(conn, run_id, mappings)

    PL->>R: update_progress(conn, run_id, {"Analyzing gaps", 75})
    PL->>LLM: chat_structured(analyze gaps)
    LLM-->>PL: List[GapAnalysis]
    PL->>R: save_gaps(conn, gaps)

    PL->>R: update_progress(conn, run_id, {"Generating recommendations", 90})
    PL->>LLM: chat_structured(generate suggestions)
    LLM-->>PL: List[Recommendation]
    PL->>R: save_recommendations(conn, recs)

    PL->>R: update_run_status(conn, run_id, "completed")
    PL->>R: update_progress(conn, run_id, {"Complete", 100})
```

### 4.2 pgvector 语义匹配子流程

```mermaid
sequenceDiagram
    participant PL as Pipeline
    participant MT as Matcher
    participant R as Repository
    participant PG as PostgreSQL

    PL->>MT: match_all(obligations, controls)

    loop 每个 ComplianceObligation
        MT->>R: find_similar_controls(conn, embedding, 0.65, 3)
        Note over R,PG: pgvector 余弦相似度查询<br/>1-(embedding #lt;=#gt; %s) #gt;= 0.65<br/>ORDER BY similarity DESC LIMIT 3
        R->>PG: 查询相似控制项
        PG-->>R: [{control_id, name, similarity}, ...]

        R-->>MT: top-3 matched controls

        MT->>MT: 判断覆盖率
        Note over MT: 相似度 #gt;= 0.85 → covered<br/>相似度 #gt;= 0.65 → partial<br/>相似度 #lt; 0.65 → missing

        MT->>MT: 组装 MappingResult
    end

    MT-->>PL: List[MappingResult]
```

### 4.3 HTMX 前端交互子流程

```mermaid
sequenceDiagram
    actor User as 用户
    participant B as 浏览器
    participant F as FastAPI
    participant R as Repository
    participant DB as PostgreSQL

    User->>B: 点击 "加载示例文档"
    B->>F: POST /api/analyze?use_sample=true
    Note over B,F: hx-post + hx-target="#results"

    F->>R: save_regulation + create_analysis_run
    F->>F: enqueue pipeline (异步)
    F-->>B: {run_id, status:"processing", progress_url}

    B->>B: 自动跳转到 /analyses/{run_id}
    Note over B: window.location.href = progress_url

    loop 每 2s
        B->>F: GET /api/analyses/{run_id}/progress
        Note over B,F: hx-get + hx-trigger="every 2s" + hx-swap="outerHTML"
        F->>R: get_analysis_run(conn, run_id)
        R-->>F: {status, progress}
        alt status == "processing"
            F-->>B: <进度条> 35% "Matching controls"
            B->>B: 更新进度条动画
        else status == "completed"
            F-->>B: <完整看板 HTML>
            Note over B: 返回的 HTML 无 hx-trigger，轮询停止
            B->>B: 渲染覆盖度雷达图 + 表格
        end
    end

    User->>B: 点击 "部分覆盖" 条目
    Note over User,B: hx-get="/api/analyses/{id}/gap/{gap_id}/detail"
    B->>F: GET /api/analyses/{run_id}/gap/{gap_id}/detail
    F-->>B: <差距详情 HTML>
    B->>B: 展开差距详情卡片
```

---

## 五、API 概览

```yaml
# 页面路由 (返回 HTML)
GET  /                       -> index.html
GET  /analyses               -> history.html
GET  /analyses/{id}          -> dashboard.html

# API 路由 (返回 JSON)
POST /api/analyze            -> AnalyzeResponse (立即返回)
GET  /api/analyses           -> List[HistoryItem]
GET  /api/analyses/{id}      -> AnalysisDetailResponse
DEL  /api/analyses/{id}      -> 204 No Content
GET  /api/analyses/{id}/report     -> Markdown 下载
POST /api/seed               -> {status, controls_loaded}

# 进度路由 (返回 HTML 供 HTMX 轮询)
GET  /api/analyses/{id}/progress   -> HTML (进度条 或 完整看板)

# 自动生成文档
GET  /docs                    -> Swagger UI
```

---

## 六、前端页面结构

```mermaid
graph TB
    subgraph base["base.html — 布局模板"]
        NAV["导航栏<br/>RegIntel 标题 + 版本号"]
        SIDEBAR["侧边栏<br/>- 新建分析 (按钮)<br/>- 历史记录 (最近 10 条)"]
        CONTENT["{% block content %}{% endblock %}"]
        FOOTER["页脚"]
    end

    subgraph index["index.html — 首页"]
        UPLOAD["上传区<br/>- 拖拽/点击上传 PDF/DOCX/TXT<br/>- 加载示例文档 按钮<br/>- 可接受文件类型说明"]
    end

    subgraph dashboard["dashboard.html — 分析结果看板"]
        PROGRESS["进度条 (分析中) <br/>逐级显示: 5% / 20% / 35% / 55% / 75% / 90% / 100%"]
        SUMMARY["摘要卡片行<br/>义务总数 · 已覆盖 · 部分覆盖 · 缺失"]
        CHART["覆盖度雷达图<br/>(Chart.js)"]
        TABLE["匹配矩阵表<br/>义务 × 控制<br/>绿/黄/红 颜色编码"]
        GAPS["差距详情<br/>每个 Gap 一个可展开卡片<br/>含 AI 建议"]
        EXPORT["报告导出按钮<br/>Markdown 下载"]
    end

    subgraph history["history.html — 历史记录"]
        LIST["历史列表<br/>- 文件名称 · 监管机构 · 日期 · 状态标签<br/>- 点击跳转到详情<br/>- 空状态提示"]
    end

    NAV --> SIDEBAR
    SIDEBAR --> CONTENT
    CONTENT --> FOOTER

    index -- 上传成功 --> dashboard
    dashboard -. 回到首页 .-> index
    dashboard -- 侧边栏历史 --> history
    history -- 点击条目 --> dashboard
```

**HTMX 交互点：**

| 交互 | HTMX 属性 | 说明 |
|------|-----------|------|
| 文件上传 | `hx-post="/api/analyze" hx-target="#results"` | 异步上传，成功后跳转 |
| 进度轮询 | `hx-get="/api/.../progress" hx-trigger="every 2s"` | 每 2s 更新进度条 |
| 展开差距 | `hx-get="/api/.../gap/{id}" hx-target="#gap-{id}"` | 惰性加载差距详情 |
| 加载建议 | `hx-get="/api/.../recommendation/{id}"` | 惰性加载 AI 建议 |
| 删除分析 | `hx-delete="/api/analyses/{id}" hx-confirm="确定?"` | 确认后删除 |
| 加载历史 | `hx-get="/api/analyses" hx-trigger="load"` | 页面加载时拉取列表 |

---

## 七、目录结构

```
regintel/
├── docker-compose.yml          # 容器编排: app + postgres
├── Dockerfile                  # 应用容器化
├── .env.example                # 环境变量模板
├── pyproject.toml              # 依赖声明 (uv, 与 v1 共用)
├── uv.lock                     # 版本锁定
├── README.md                   # 启动指南
│
├── app/                        # FastAPI 应用 (替换 v1 的 app.py)
│   ├── __init__.py
│   ├── main.py                 # FastAPI app 入口 + 生命周期
│   ├── config.py               # Pydantic Settings
│   │
│   ├── routers/                # API 路由层
│   │   ├── __init__.py
│   │   ├── upload.py           # POST /api/analyze
│   │   ├── analysis.py         # GET/DEL /api/analyses/*
│   │   ├── report.py           # GET /api/report/{id}
│   │   └── pages.py            # GET / (HTML 页面)
│   │
│   ├── db/                     # 数据库层 (新增, 替代 Session State)
│   │   ├── __init__.py
│   │   ├── connection.py       # psycopg2 连接池
│   │   ├── repository.py       # 数据访问 (bare SQL)
│   │   └── seed.py             # Mock 数据初始化
│   │
│   ├── models/                 # Pydantic 模型
│   │   ├── __init__.py
│   │   ├── domain.py           # 内部领域模型 (与 v1 共用)
│   │   └── schemas.py          # API 请求/响应 Schema
│   │
│   ├── services/               # 核心管线 (与 v1 共用, 不变)
│   │   ├── __init__.py
│   │   ├── pipeline.py
│   │   ├── llm_client.py
│   │   ├── document_parser.py
│   │   ├── compliance_extractor.py
│   │   ├── embedding_service.py
│   │   ├── matcher.py          # 变更: numpy → pgvector
│   │   ├── gap_analyzer.py
│   │   ├── recommendation_engine.py
│   │   └── report_generator.py
│   │
│   ├── templates/              # Jinja2 前端模板 (新增)
│   │   ├── base.html
│   │   ├── index.html
│   │   ├── dashboard.html
│   │   └── history.html
│   │
│   └── static/                 # 静态资源 (替换 v1 styles/)
│       ├── css/
│       │   └── styles.css
│       └── js/
│           └── htmx.min.js
│
├── db/                         # DDL 脚本
│   └── init.sql                # CREATE TABLE + pgvector EXTENSION
│
├── data/                       # Mock 数据 (与 v1 共用)
│   ├── mock/
│   │   ├── internal_controls.json
│   │   └── sample_regulation.md
│   └── uploads/
│
├── tests/
│
└── design/                     # 设计文档
    ├── v1/
    │   └── Detailed-Design.md
    └── v2/
        └── Detailed-Design.md  # 本文件
```

**v1 → v2 目录变化：**

| 变化 | 说明 |
|------|------|
| `app.py` → `app/main.py` | Streamlit 单文件 → FastAPI 包结构 |
| `styles/` → `app/static/` | 样式文件从顶层移到应用包内 |
| — → `app/routers/` | 新增 API 路由层 |
| — → `app/db/` | 新增数据库层 (connection/repository/seed) |
| — → `app/templates/` | 新增 Jinja2 HTML 模板 |
| — → `db/init.sql` | 新增 DDL 脚本 |
| — → `docker-compose.yml` | 新增容器编排 |
| — → `Dockerfile` | 新增容器化构建 |
| — → `.env.example` | 新增环境变量模板 |
| `services/` | **不变**, 与 v1 共用 |
| `models/domain.py` | **不变**, 与 v1 共用 |
| `data/` | **不变**, 与 v1 共用 |

---

## 八、配置与启动

### docker-compose.yml

```yaml
services:
  regintel-app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://regintel:regintel@postgres:5432/regintel
      - LLM_API_ENDPOINT=${LLM_API_ENDPOINT}
      - LLM_API_KEY=${LLM_API_KEY}
    volumes:
      - uploads_data:/app/data/uploads
    depends_on:
      postgres:
        condition: service_healthy
    restart: unless-stopped

  postgres:
    image: pgvector/pgvector:pg16
    environment:
      - POSTGRES_USER=regintel
      - POSTGRES_PASSWORD=regintel
      - POSTGRES_DB=regintel
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./db/init.sql:/docker-entrypoint-initdb.d/01-init.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U regintel -d regintel"]
      interval: 5s
      timeout: 5s
      retries: 10
    restart: unless-stopped

volumes:
  postgres_data:
  uploads_data:
```

### Dockerfile

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml uv.lock .
RUN uv sync --frozen
COPY . .
RUN mkdir -p data/uploads
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 快速启动

```bash
# 首次: 配置环境变量
cp .env.example .env
# 编辑 .env 填入 LLM_API_ENDPOINT 和 LLM_API_KEY

# 启动
docker compose up

# 打开浏览器
open http://localhost:8000
# API 文档
open http://localhost:8000/docs
```

---

## 九、v1 → v2 演进要点

| 维度 | v1 | v2 | 迁移影响 |
|------|-----|-----|----------|
| 前端框架 | Streamlit | Jinja2 + HTMX | 完全重写, 但交互逻辑一致 |
| 数据存储 | Session State (内存) | PostgreSQL (持久化) | 新增 db/ 层, services/ 不变 |
| 向量搜索 | numpy cosine_similarity | pgvector `<=>` | 仅 matcher.py 内实现替换 |
| 部署方式 | `uv run streamlit run app.py` | `docker compose up` | 基础设施变更, 应用代码不变 |
| API | 无 | REST + Swagger | 新增 routers/ 层 |
| 配置 | `config.py` | `.env` + `config.py` | 配置项拆分 |
| services/ | 所有服务 | 同 v1 | **零改动** |
| models/domain.py | 数据模型 | 同 v1 | **零改动** |
| data/ | Mock 数据 | 同 v1 | **零改动** |

**services/ 中唯一需要改动的文件是 matcher.py**：将 `from sklearn.metrics.pairwise import cosine_similarity` 改为调用 `repository.find_similar_controls()`，后者执行 pgvector SQL。其余 8 个服务文件不变。

---

## 十、工具链

同 v1，使用 uv (Astral) 管理依赖。详细说明见 `design/v1/Detailed-Design.md` 第八章。

v2 新增的 Docker 构建阶段引入了一个额外步骤：

```dockerfile
# Docker 构建时使用 frozen lockfile 加速
RUN uv sync --frozen
```

这比 `pip install -r requirements.txt` 快 10-20 倍。

---

## 修订记录

| 版本 | 日期 | 变更说明 |
|------|------|----------|
| v2.0 | 2026-06-29 | FastAPI + PostgreSQL + pgvector + Docker Compose + Jinja2/HTMX 详细设计 |
