# RegIntel AI — Software Architecture

> **版本: v3.1 — 2026-06-29 — +Airflow 定时调度 + Ansible 自动修复 + 后续探索方向**

基于 GenAI + NLP + 语义搜索的 AI 合规助手 · 两周 Hackathon 架构方案
---

## 一、架构总览

```
+───────────────────────────────────────────────────────────────────+
|                    Streamlit App (app.py)                         |
|   Upload    |    Dashboard    |    Gap View    |    Export       |
+──────────────────────────┬───────────────────────────────────────+
                           |
+──────────────────────────▼───────────────────────────────────────+
|                   Pipeline Orchestrator                           |
|   (pipeline.py — 编排所有处理步骤, Session State 管理上下文)      |
+──────┬────────┬───────────┬──────────┬──────────┬────────────────+
       |        |           |          |          |
+──────▼──┐ +──▼──────┐ +──▼─────┐ +──▼────┐ +──▼──────────────+
| Doc     | |Compliance| |Embedding| |Gap    | |Recommendation   |
| Parser  | |Extractor | |Service  | |Analyzer| |Engine           |
+────────+ +─────────+ +───────+ +───────+ +───────────────+
                |            |
                +─────┬──────+
                 +────▼────+
                 | Matcher |  ← 语义匹配(余弦相似度)
                 +─────────+
                           |
+──────────────────────────▼───────────────────────────────────────+
|                        Data Layer                                 |
|   Mock Controls (JSON)    |    Uploads (tmp)    |    Cache        |
+───────────────────────────────────────────────────────────────────+
```

---

## 二、核心设计决策(2 周 Hackathon 导向)

| 决策 | 选择 | 理由 |
|------|------|------|
| **数据持久化** | 无 DB, Streamlit Session State + JSON | 2 周项目, 去掉运维复杂度 |
| **语义匹配** | 余弦相似度(embedding 向量) | 展示真实工程能力, 比纯 LLM 判断更快 |
| **Embedding 模型** | sentence-transformers all-MiniLM-L6-v2(本地 fallback)或内部 API embedding endpoint | 够用, 轻量, 不依赖网络 |
| **LLM 调用** | JSON mode / 函数调用(structured output) | 解决"LLM 输出不稳定"问题 |
| **Mock 数据** | 25-30 条内控 + 1 份模拟 FCA 监管文件 | Demo 叙事完备: 有已覆盖, 部分覆盖, 未覆盖三种场景 |
| **缓存** | 嵌入向量预计算 + LLM 结果缓存(@functools.lru_cache / 磁盘 JSON) | Demo 时避免等待, 流畅展示 |

---

## 三、组件详解

### 3.1 数据模型 — src/models.py

用 Pydantic 定义所有核心数据结构, 贯穿整个管线:

```
Regulation             -> { id, title, source, published_date, content, summary }
ComplianceObligation   -> { id, description, source_ref, category, risk_level }
InternalControl        -> { id, name, description, category, frequency, owner, status }
MappingResult          -> { obligation, control, similarity_score, coverage_status }
GapAnalysis            -> { obligation, coverage_status, gap_description, risk_impact }
Recommendation         -> { gap_id, action_items, priority, estimated_effort }
AnalysisReport         -> { regulation, summary, gaps[], recommendations[], coverage_stats }
```

关键设计: **所有 LLM 输出都经过 Pydantic 校验**, 确保下游组件收到的是结构化数据而非自由文本.

### 3.2 文档解析 — src/document_parser.py

```
输入: PDF / DOCX / TXT 文件
流程: FileType 判断 -> 对应解析器(PyMuPDF / python-docx / 原生文本)
      -> 章节切分(按标题/编号)-> 段落级 chunk(保留引用来源)
输出: 带章节标记的纯文本
```

Hackathon 策略: PDF 解析只用最基本的 text extraction(不处理表格/复杂排版), 注明日志中.

### 3.3 合规义务提取 — src/compliance_extractor.py

```
输入: 监管文本(分章节)
流程: 对每个章节调用 LLM(structured output), 提取:
      - 明确的新增/变更合规义务
      - 义务的类别, 风险等级, 涉及的监管条款编号
      - deduplication(合并跨章节的同一义务)
输出: List[ComplianceObligation]
```

Prompt 设计核心: 要求 LLM **直接引用原文条款编号**, 确保可溯源.

### 3.4 Embedding 服务 — src/embedding_service.py

```
优先: 内部 API embedding endpoint(如果支持)
回退: sentence-transformers (all-MiniLM-L6-v2) 本地运行

功能:
  1. embed(text) -> 返回向量
  2. embed_batch(texts) -> 批量生成
  3. 预计算 mock 内控库的全部 embedding(启动时加载, 无需反复计算)
```

缓存策略: embedding 向量序列化为 JSON/parquet, 下次启动直接加载.

### 3.5 语义匹配 — src/matcher.py

```
输入: 提取的合规义务 embedding + 内控库 embedding
流程:
  1. 构建内控 embedding 矩阵(N_controls x embedding_dim)
  2. 对每个义务 embedding, 计算与所有内控的 cosine similarity
  3. 返回 Top-3 匹配结果 + 相似度分
  4. 相似度阈值:
     >= 0.85 -> "已覆盖"
     >= 0.65 -> "部分覆盖"
     < 0.65  -> "未覆盖"
输出: List[MappingResult]
```

阈值对 Demo 效果影响大. Mock 数据时会故意设计: 一部分明显匹配(>0.85), 一部分临界(0.65-0.85), 一部分无匹配(<0.65), 演示效果层次分明.

### 3.6 差距分析 — src/gap_analyzer.py

```
输入: MappingResult[]
流程:
  1. 从 MappingResult 提取 coverage_status
  2. 对 "部分覆盖" 和 "未覆盖" 的:
     a. 规则层: 频率, 范围, 责任人的自动对比(基于结构化字段)
     b. LLM 增强层: 对复杂差距, 调 LLM 详细描述差距性质
  3. 组装 GapAnalysis
输出: List[GapAnalysis]
```

### 3.7 建议生成 — src/recommendation_engine.py

```
输入: GapAnalysis[]
流程: 对每个 Gap, 构造 prompt 包含:
      - 监管要求原文
      - 现有控制描述
      - 已识别的差距描述
      -> LLM 生成: 具体行动计划 + 优先级 + 建议时间线
输出: List[Recommendation]
```

### 3.8 报告生成 — src/report_generator.py

```
输入: AnalysisReport
流程: 组装 Markdown 报告(结构化模板): 执行摘要 -> 覆盖概览 -> 详细差距 -> 建议
输出: Markdown 文件(可下载) + 可选 PDF(weasyprint / pandoc)
```

Hackathon: Markdown 是最安全的选择. 有余力再加 PDF.

### 3.9 管线编排 — src/pipeline.py

```python
class RegIntelPipeline:
    def __init__(self, llm_client, embedding_service):
        self.parser = DocumentParser()
        self.extractor = ComplianceExtractor(llm_client)
        self.matcher = SemanticMatcher(embedding_service)
        self.gap_analyzer = GapAnalyzer(llm_client)
        self.recommender = RecommendationEngine(llm_client)
        self.reporter = ReportGenerator()

    def run(file_path) -> AnalysisReport:
        1. parse document -> regulation text
        2. extract obligations <- LLM
        3. embed & match obligations vs controls <- embedding + cosine
        4. analyze gaps <- LLM (for partial/missing)
        5. generate recommendations <- LLM
        6. assemble AnalysisReport
        7. return report
```

Pipeline 支持 **步进式执行**(在 UI 展示每一步进展), 也支持 **一键全跑**(Demo 场景预缓存全部结果).

### 3.10 Streamlit 前端 — app.py

**页面结构(单页多区, 减少页面跳转的割裂感):**

| UI 区域 | 内容 |
|---------|------|
| **侧边栏** | 文件上传; 示例文档加载按钮; 处理触发; 缓存管理 |
| **Step 1** | 文件预览 + 摘要卡片(读取后即刻显示) |
| **Step 2** | 提取的合规义务列表(可展开, 展示原文引用) |
| **Step 3** | 匹配结果矩阵: 义务 x 控制, 颜色编码热力图(绿/黄/红) |
| **Step 4** | 差距详情 + AI 建议(每个 Gap 一个卡片) |
| **Step 5** | 管理看板: 覆盖度雷达图, 饼图, KPI 卡片 |
| **Step 6** | 报告预览 + 一键下载 |

**视觉风格:** 安静的仪表盘风格, 色彩克制(绿色覆盖 / 琥珀色部分 / 红色缺失), 不花哨, 突出信息密度.

---

## 四、项目结构

```
regintel/
+-- app.py                          # Streamlit 入口, 页面布局
+-- config.py                       # API endpoint, model name, 阈值等
+-- pyproject.toml              # 依赖声明 (uv)
+-- README.md                       # 启动指南
|
+-- data/
|   +-- mock/
|   |   +-- internal_controls.json  # 25-30 条 Mock 内控措施
|   |   +-- sample_regulation.md    # 模拟 FCA 监管文件
|   +-- uploads/                    # gitignored, 运行时上传
|
+-- src/
|   +-- __init__.py
|   +-- models.py                   # Pydantic 数据模型
|   +-- llm_client.py               # 内部 LLM API 客户端
|   +-- document_parser.py          # PDF/DOCX/TXT 解析
|   +-- compliance_extractor.py     # 合规义务提取
|   +-- embedding_service.py        # Embedding 生成 + 缓存
|   +-- matcher.py                  # 语义匹配引擎
|   +-- gap_analyzer.py             # 差距分析
|   +-- recommendation_engine.py    # 建议生成
|   +-- report_generator.py         # 报告导出
|   +-- pipeline.py                 # 管线编排
|
+-- styles/
|   +-- custom.css                  # Streamlit 自定义样式
|
+-- tests/
    +-- test_document_parser.py
    +-- test_compliance_extractor.py
    +-- test_matcher.py
    +-- test_gap_analyzer.py
```

---

## 五、Mock 数据设计思路

**内部控件库(25-30 条)** — 覆盖 8 个合规领域, 每条包含结构化字段:

| 类别 | 示例控制 | 条数 |
|------|----------|------|
| 访问控制 | 季度特权访问审查 | 4 |
| 数据保护 | PII 加密存储与密钥轮换 | 4 |
| 报告披露 | 季度监管报告自动生成 | 3 |
| 风控 | 月度 VaR 监控 | 4 |
| AML/KYC | 客户尽职调查年审 | 3 |
| 第三方管理 | 供应商年度评估 | 3 |
| 运营韧性 | 年度 BCP 演练 | 3 |
| 行为文化 | 交易行为监控 | 2 |

**模拟监管文件(FCA 运营韧性新规)** — 包含三类义务:

- **已覆盖**(审查频率一致): 现有季度审查符合新规月审要求 -> 但部分已覆盖
- **部分覆盖**(审查周期不一致, 缺少证据留存流程, 责任人未更新)
- **完全缺失**(自动化事件响应测试, 第三方韧性报告等全新要求)

这样 Demo 叙事自然: "上传 -> 发现 8 个义务 -> 3 个已覆盖(绿), 3 个部分覆盖(黄), 2 个缺失(红) -> 点击黄/红 -> AI 给出具体整改方案."

---

## 六、两周执行路线

**Week 1 — 核心 AI 管线**

| 天数 | 交付物 | 重点 |
|------|--------|------|
| Day 1 | models.py, config.py, mock 数据 | 数据结构定型 |
| Day 2 | llm_client.py, document_parser.py | LLM 接入调通 |
| Day 3 | compliance_extractor.py | Structured output 联调 |
| Day 4 | embedding_service.py, matcher.py | 语义匹配联调 |
| Day 5 | gap_analyzer.py | 规则 + LLM 混合分析 |
| Day 6 | recommendation_engine.py | 建议生成 |
| Day 7 | pipeline.py 整合 + 单元测试 | 管线端到端跑通 |

**Week 2 — 前端 & 打磨**

| 天数 | 交付物 | 重点 |
|------|--------|------|
| Day 8 | app.py 骨架 + 上传/文件预览 | UI 框架 |
| Day 9 | Step 2-3 UI(义务列表 + 匹配矩阵) | 数据可视化 |
| Day 10 | Step 4-6(看板, 建议, 报告导出) | 报告模板 |
| Day 11 | 集成联调 + 端到端测试 | Bug fix |
| Day 12 | 风格打磨 + Demo 交互脚本 | 演示流畅度 |
| Day 13 | 预留缓冲 | 修意外问题 |
| Day 14 | 演示排练 + 展板制作 | 现场展示 |

---

## 七、关键技术风险与应对

| 风险 | 影响 | 应对方案 |
|------|------|----------|
| LLM API 延迟 3-5s/调用 | Demo 节奏被打断 | streaming + step-by-step 逐步展示 + 缓存命中时零延迟 |
| Embedding API 不可用 | 语义匹配阻塞 | 备选 sentence-transformers 本地运行(all-MiniLM-L6-v2, < 200MB) |
| PDF 解析不准 | 义务提取遗漏 | 准备一个干净的 Markdown 版本做 "demo mode" 兜底 |
| LLM 输出格式不一致 | 下游组件崩溃 | Pydantic 校验 + retry(最多 2 次)+ fallback 默认值 |
| 依赖安装耗时 | 现场演示翻车 | pyproject.toml 锁版本 + uv sync + uv.lock 提交 git |

---

## 八、Demo 过程应有的样子

1. 用户点开 Streamlit 链接 (or localhost) -> 干净简洁的页面
2. 点击 "加载示例文档"(或拖入一个 PDF)
3. 页面逐步展示流水线: 文件摘要 -> 提取出 8 条合规义务(可展开看原文引用)-> 语义匹配矩阵(热力图: 绿黄红)-> 差距分析详情 -> AI 建议卡片
4. 左侧看板: 覆盖率雷达图, 饼图, KPI(8 个义务, 3 covered / 3 partial / 2 missing)
5. 点击 "导出报告" -> 下载 Markdown/PDF 报告
6. 全过程约 30-60 秒(含 LLM 调用), 平缓的逐步动画呈现而非一次性白屏

---

## 九、假设与默认选择

- **Embedding 方案**: 默认用 sentence-transformers all-MiniLM-L6-v2 本地跑(不依赖内部 API 是否有 embedding 端点). 如果内部 API 提供 embedding 且延迟更低, 可切换.
- **LLM structured output**: 假设内部 API 支持 JSON mode 或 function calling. 如果不支持, 回退到 prompt 约束 + Pydantic 后处理解析.
- **Demo 依赖预缓存**: 启动时 pre-compute mock 内控的 embedding, 避免现场等待.
- **前端配色**: 设备/信息面板风格, 不花哨.
- **依赖管理**: 使用 uv (Astral) 替代 pip。`uv sync` 安装依赖, `uv lock` 生成锁定版本,
  `uv add <pkg>` 添加新依赖。`uv.lock` 提交 git 确保环境一致性。
  Docker 构建时使用 `uv sync --frozen` 加速。

---

## 修订记录

| 版本 | 日期 | 变更说明 |
|------|------|----------|
| v2.0 | 2026-06-29 | FastAPI + PostgreSQL + pgvector + Docker Compose + Jinja2/HTMX |
| v1.0 | 2026-06-29 | 初版架构定稿 (Streamlit + 内存) |

---

# RegIntel AI — Software Architecture (v2)

> **版本: v2.0 — 2026-06-29 — FastAPI + PostgreSQL + pgvector + Docker Compose + Jinja2/HTMX**

基于 GenAI + NLP + 语义搜索的 AI 合规助手 · 两周 Hackathon 架构方案

---

## 一、v1 → v2 演进摘要

| 维度 | v1 | v2 |
|------|-----|-----|
| **Web 框架** | Streamlit (单进程 UI+逻辑) | FastAPI + Uvicorn (标准三层架构) |
| **前端** | Streamlit 内置组件 | Jinja2 模板 + HTMX + Bootstrap 5 |
| **API** | 无 | RESTful + OpenAPI/Swagger |
| **持久化** | Session State (重启丢失) | PostgreSQL 8 张表 |
| **向量搜索** | numpy cosine_similarity (内存) | pgvector `<=>` operator (SQL 层) |
| **部署** | `streamlit run app.py` | `docker compose up` |
| **认证扩展** | 困难 (需反向代理) | OAuth2 Depends() 一行注入 |

---

## 二、架构总览

```text
+----------------------------------------------------------------------------+
|                           Docker Compose                                    |
|                                                                            |
|  +----------------------------------------------------------------------+  |
|  |                    regintel-app                                      |  |
|  |  +------------------+   +-----------------------------------------+  |  |
|  |  |  Jinja2 Templates |   |  FastAPI Routers                         |  |  |
|  |  |  + HTMX           |   |                                          |  |  |
|  |  |                   |   |  POST /api/analyze (upload)              |  |  |
|  |  |  base.html        |   |  GET  /api/analyses (list)               |  |  |
|  |  |  index.html       |   |  GET  /api/analyses/{id}                 |  |  |
|  |  |  dashboard.html   |   |  DEL  /api/analyses/{id}                 |  |  |
|  |  |  history.html     |   |  GET  /api/report/{id}                   |  |  |
|  |  |                   |   |  GET  /docs (Swagger)                    |  |  |
|  |  +------------------+   +---------------------+--------------------+  |  |
|  |                                               |                        |  |
|  |                                        +------v------+                 |  |
|  |                                        |  Services    |                 |  |
|  |                                        |  (pipeline)  |                 |  |
|  |                                        +------+------+                 |  |
|  |                                               |                        |  |
|  |                                        +------v------+                 |  |
|  |                                        |  DB Layer    |                 |  |
|  |                                        |  psycopg2    |                 |  |
|  |                                        +------+------+                 |  |
|  +-----------------------------------------------+------------------------+  |
|                                                  |                          |
|                               +------------------v------------------+       |
|                               |  postgres (pgvector/pg16)           |       |
|                               |  8 tables + IVFFlat index           |       |
|                               +-------------------------------------+       |
|                                                                            |
|  持久卷: postgres_data -> /var/lib/postgresql/data                         |
|          uploads_data  -> /app/data/uploads                                |
+----------------------------------------------------------------------------+
```

---

## 三、API 设计

| 方法 | 路径 | 说明 | 响应 |
|------|------|------|------|
| GET | `/` | 首页 (上传 + 示例加载) | HTML |
| GET | `/analyses` | 历史分析列表页 | HTML |
| GET | `/analyses/{id}` | 分析结果详情页 | HTML |
| POST | `/api/analyze` | 上传文件 + 触发管线 | JSON |
| GET | `/api/analyses` | 历史分析列表 | JSON |
| GET | `/api/analyses/{id}` | 分析结果详情 | JSON |
| DELETE | `/api/analyses/{id}` | 删除分析 (级联) | JSON |
| GET | `/api/analyses/{id}/report` | 下载报告 | Markdown |
| POST | `/api/seed` | 加载 Mock 数据 | JSON |
| GET | `/docs` | Swagger UI 文档 | HTML |

---

## 四、项目结构

```text
regintel/
+-- docker-compose.yml          # 容器编排
+-- Dockerfile                  # 应用容器化
+-- .env.example                # 环境变量模板
+-- requirements.txt            # 依赖列表
+-- README.md                   # 启动指南
|
+-- app/                        # FastAPI 应用根目录
|   +-- __init__.py
|   +-- main.py                 # FastAPI app 入口 + 生命周期事件
|   +-- config.py               # Pydantic Settings
|   |
|   +-- db/                     # 数据库层
|   |   +-- __init__.py
|   |   +-- connection.py       # psycopg2 连接池
|   |   +-- repository.py       # 数据访问 (bare SQL)
|   |   +-- seed.py             # Mock 数据初始化
|   |
|   +-- routers/                # API 路由层
|   |   +-- __init__.py
|   |   +-- upload.py           # POST /api/analyze
|   |   +-- analysis.py         # GET/DEL /api/analyses/*
|   |   +-- report.py           # GET /api/report/{id}
|   |   +-- pages.py            # GET / GET /analyses (HTML)
|   |
|   +-- services/               # 业务逻辑层
|   |   +-- __init__.py
|   |   +-- llm_client.py
|   |   +-- document_parser.py
|   |   +-- compliance_extractor.py
|   |   +-- embedding_service.py
|   |   +-- matcher.py
|   |   +-- gap_analyzer.py
|   |   +-- recommendation_engine.py
|   |   +-- report_generator.py
|   |   +-- pipeline.py
|   |
|   +-- models/                 # Pydantic 模型
|   |   +-- __init__.py
|   |   +-- domain.py           # 内部领域模型
|   |   +-- schemas.py          # API 请求/响应 Schema
|   |
|   +-- templates/              # Jinja2 前端模板
|       +-- base.html           # 布局模板
|       +-- index.html          # 首页 + 上传
|       +-- dashboard.html      # 分析结果看板
|       +-- history.html        # 历史记录
|
+-- static/
|   +-- css/
|   |   +-- styles.css
|   +-- js/
|       +-- htmx.min.js
|
+-- db/
|   +-- init.sql                # DDL + pgvector EXTENSION
|
+-- data/
|   +-- mock/
|   |   +-- internal_controls.json
|   |   +-- sample_regulation.md
|   +-- uploads/
|
+-- tests/
```

---

## 五、PostgreSQL 表结构

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE internal_controls (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(200) NOT NULL,
    description TEXT NOT NULL,
    category    VARCHAR(100),
    frequency   VARCHAR(50),
    owner       VARCHAR(200),
    status      VARCHAR(50) DEFAULT 'active',
    embedding   vector(384)
);

CREATE TABLE regulations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           VARCHAR(500) NOT NULL,
    source          VARCHAR(50),
    published_date  DATE,
    content         TEXT NOT NULL,
    summary         TEXT,
    file_path       VARCHAR(500),
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE obligations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    regulation_id   UUID REFERENCES regulations(id) ON DELETE CASCADE,
    description     TEXT NOT NULL,
    source_ref      VARCHAR(200),
    category        VARCHAR(100),
    risk_level      VARCHAR(20),
    embedding       vector(384),
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE analysis_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    regulation_id   UUID REFERENCES regulations(id) ON DELETE CASCADE,
    status          VARCHAR(50) DEFAULT 'processing',
    summary         TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE mapping_results (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_run_id     UUID REFERENCES analysis_runs(id) ON DELETE CASCADE,
    obligation_id       UUID REFERENCES obligations(id) ON DELETE CASCADE,
    control_id          UUID REFERENCES internal_controls(id) ON DELETE CASCADE,
    similarity_score    FLOAT NOT NULL,
    coverage_status     VARCHAR(20) NOT NULL,
    created_at          TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE gap_analyses (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mapping_result_id   UUID REFERENCES mapping_results(id) ON DELETE CASCADE,
    gap_description     TEXT,
    risk_impact         TEXT,
    created_at          TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE recommendations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    gap_analysis_id     UUID REFERENCES gap_analyses(id) ON DELETE CASCADE,
    action_items        JSONB NOT NULL DEFAULT '[]',
    priority            VARCHAR(20),
    estimated_effort    VARCHAR(100),
    created_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_controls_embedding ON internal_controls
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```

---

## 六、Docker Compose 编排

**docker-compose.yml:**

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

**Dockerfile:**

```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p data/uploads

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**requirements.txt:**

```
fastapi>=0.115
uvicorn[standard]>=0.30
jinja2>=3.1
python-multipart>=0.0.12
aiofiles>=24.1
pydantic>=2.0
pydantic-settings>=2.0
psycopg2-binary>=2.9.9
pgvector>=0.3.0
sentence-transformers>=3.0
PyMuPDF>=1.24
python-docx>=1.1
httpx>=0.27
```

---

## 七、组件调用链

```
请求                                                                     响应
 |                                                                        |
 v                                                                        |
+------------------------------------------------------------------+
| routers/ (HTTP 校验 + 响应序列化)                                    |
|   @router.get("/api/analyses/{id}")                                   |
|   def get_analysis(id: UUID):                                         |
|       report = pipeline.get_analysis(id)                              |
|       return AnalysisResponse(...)                                    |
+-----------------------------+----------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
| services/pipeline.py (业务逻辑编排)                                |
|   class RegIntelPipeline:                                           |
|       def get_analysis(run_id):                                     |
|           reg = repo.get_regulation(conn, run_id)                   |
|           obs = repo.get_obligations(conn, run_id)                  |
|           maps = repo.get_mappings(conn, run_id)                    |
|           gaps = repo.get_gaps(conn, run_id)                        |
|           recs = repo.get_recommendations(conn, run_id)              |
|           return Report(reg, obs, maps, gaps, recs)                 |
+-----------------------------+----------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
| db/repository.py (psycopg2 bare SQL)                               |
|   SELECT o.* FROM obligations o                                     |
|   JOIN analysis_runs ar ON ar.regulation_id = o.regulation_id       |
|   WHERE ar.id = %s                                                   |
+------------------------------------------------------------------+
```

---

## 八、Mock 数据设计

**内部控件库 (25-30 条, 覆盖 8 个合规领域):**

| 类别 | 示例控制 | 条数 |
|------|----------|------|
| 访问控制 | 季度特权访问审查 | 4 |
| 数据保护 | PII 加密存储与密钥轮换 | 4 |
| 报告披露 | 季度监管报告自动生成 | 3 |
| 风控 | 月度 VaR 监控 | 4 |
| AML/KYC | 客户尽职调查年审 | 3 |
| 第三方管理 | 供应商年度评估 | 3 |
| 运营韧性 | 年度 BCP 演练 | 3 |
| 行为文化 | 交易行为监控 | 2 |

**模拟监管文件 (FCA 运营韧性新规):**
- 已覆盖 (频率/范围完全匹配)
- 部分覆盖 (审查周期不一致/缺少证据留存/责任人未更新)
- 完全缺失 (全新要求, 无对应控制)

---

## 九、两周执行路线

**Week 1 — 核心 AI 管线**

| 天数 | 交付物 | 重点 |
|------|--------|------|
| Day 1 | FastAPI 骨架 + config + DB schema + mock 数据 | 基础设施 |
| Day 2 | db/connection + db/repository + db/seed | 数据层 |
| Day 3 | document_parser + compliance_extractor | LLM 提取 |
| Day 4 | embedding_service + matcher (pgvector) | 语义匹配 |
| Day 5 | gap_analyzer + recommendation_engine | 分析建议 |
| Day 6 | pipeline 整合 + routers 端点 | 管线端到端 |
| Day 7 | 单元测试 + Docker Compose 集成 | 容器化验证 |

**Week 2 — 前端 & 打磨**

| 天数 | 交付物 | 重点 |
|------|--------|------|
| Day 8 | base.html + index.html + Bootstrap 5 | 模板搭建 |
| Day 9 | 文件上传 + HTMX 异步触发 + history.html | 前端交互 |
| Day 10 | dashboard.html: 覆盖度看板 + Chart.js | 数据可视化 |
| Day 11 | 差距详情 + 建议卡片 + 报告导出 | 完整功能链 |
| Day 12 | 端到端集成测试 + Bug fix | 稳定性 |
| Day 13 | 风格打磨 + Demo 交互脚本 | 演示准备 |
| Day 14 | 演练 + 展板 | 现场 |

---

## 十、优势总结

**PostgreSQL + pgvector:**

| 维度 | v1 (内存) | v2 (PostgreSQL) | 优势 |
|------|-----------|-----------------|------|
| 持久性 | 重启即丢 | 永久存储 | Demo 重启不丢, 展示历史 |
| 向量搜索 | numpy 全量计算 | pgvector IVFFlat 索引 | 量增大性能不退化 |
| 数据完整性 | 无约束 | 外键 + NOT NULL | 脏数据不会搞崩管线 |
| 跨分析查询 | 无法实现 | SQL JOIN 多张表 | 多维度回溯 |
| 并行支持 | 单 Session | 连接池多 Session | 多人同时试用 |

**FastAPI + Docker Compose:**

| 维度 | v1 (Streamlit) | v2 (FastAPI) | 优势 |
|------|----------------|--------------|------|
| API 能力 | 无 | REST + OpenAPI + Swagger | 可被任何客户端调用 |
| 认证扩展 | 困难 | OAuth2 Depends() | 接入 SSO 无架构障碍 |
| 代码分层 | UI+逻辑混一起 | Router/Service/Repository 三层 | 评审好讲, 扩展性好 |
| 前端灵活性 | 限 Streamlit 组件 | HTML+CSS+HTMX, 完全可控 | 可自定义到任意程度 |
| 启动 | pip install + 手动 | docker compose up | 一行命令零配置 |
| 环境一致性 | 依赖本机配置 | 镜像锁版本 | 评审机器上也跑得起来 |

---

## 十一、Demo 过程

1. 打开浏览器 -> `http://localhost:8000` -> 干净的信息仪表盘
2. 点击 "加载示例文档" 或拖入 PDF
3. 页面逐步展示进度: 解析 -> 提取义务 -> 匹配 -> 分析 -> 建议
4. 覆盖度雷达图: 3 已覆盖 (绿) / 3 部分覆盖 (黄) / 2 缺失 (红)
5. 点击部分覆盖/缺失项 -> HTMX 异步加载 AI 建议, 无整页刷新
6. 侧边栏展示历史分析记录, 一键切回上次结果
7. 点击 "下载报告" -> Markdown 完整报告
8. 打开 `/docs` (Swagger UI) 直接调试所有接口
9. 全过程 30-60 秒,逐步展示而非一次性白屏

---

## 十二、关键技术风险与应对

| 风险 | 影响 | 应对 |
|------|------|------|
| LLM API 延迟 | Demo 节奏打断 | 缓存 + HTMX 逐步展示, 每步骤独立加载 |
| Embedding API 不可用 | 语义匹配阻塞 | 备选 sentence-transformers 本地 (< 200MB) |
| PDF 解析不准 | 义务提取遗漏 | Demo mode 备 Markdown 版本兜底 |
| LLM 输出格式不一致 | 下游组件崩溃 | Pydantic 校验 + retry (最多 2 次) + fallback |
| 依赖安装耗时 | 现场翻车 | requirements.txt 锁版本 + setup.sh + Docker |

---

## 十三、假设与默认选择

- **Embedding 方案**: sentence-transformers all-MiniLM-L6-v2 本地跑 (384 维)
- **LLM structured output**: 假设内部 API 支持 JSON mode / function calling. 不支持则 prompt 约束 + Pydantic 后处理
- **向量索引**: IVFFlat with lists=100
- **前端配色**: Bootstrap 5 信息面板风格, 绿/琥珀/红对应覆盖状态
- **依赖管理**: 使用 uv (Astral) 替代 pip。`uv sync` 安装依赖, `uv lock` 生成锁定版本,
  `uv add <pkg>` 添加新依赖。`uv.lock` 提交 git 确保环境一致性。
  Docker 构建时使用 `uv sync --frozen` 加速。
- **SSO 扩展**: 加一行 middleware + Depends(get_current_user)
- **前端零 JS 策略**: 所有动态交互使用 HTMX HTML 属性驱动, Chart.js CDN 加载

---

## 修订记录

| 版本 | 日期 | 变更说明 |
|------|------|----------|
| v2.0 | 2026-06-29 | FastAPI + PostgreSQL + pgvector + Docker Compose + Jinja2/HTMX |
| v1.0 | 2026-06-29 | 初版架构定稿 (Streamlit + 内存) |

---

# RegIntel AI — Software Architecture (v3)

> **版本: v3.0 — 2026-06-29 — +Celery + Redis 异步编排 + 调度接口预留**

基于 GenAI + NLP + 语义搜索的 AI 合规助手 · 两周 Hackathon 架构方案

---

## 一、v3 演进摘要：为什么选 Celery + Redis 而不是 Airflow

| 维度 | Celery + Redis | Airflow |
|------|---------------|---------|
| **定位** | 异步任务队列 | DAG 工作流调度 |
| **开箱复杂度** | 2 个服务 (Redis + Worker) | 4 个服务 (DB + Scheduler + WebServer + Worker) |
| **适合场景** | LLM 调用/文件处理/短时异步任务 | 多步依赖 DAG/ETL/数据管线 |
| **前端进度反馈** | 天然支持 (DB 写进度 + HTTP 轮询) | 需额外封装 |
| **定时调度** | Celery Beat 一行配置 | 原生支持 |
| **学习成本** | 一个 `@celery.task` 装饰器 | DAG 定义 + Operator 体系 |
| **资源占用** | Redis (~5MB) + Worker | PostgreSQL + Scheduler + WebServer + Worker |

**结论：核心痛点是 "API 不被阻塞" + "能并发跑多个分析"——Celery 精准解决，Airflow 引入过多复杂度。**

---

## 二、同步 vs 异步流变化

**v2 (同步 —— API 被阻塞 30-60s):**

```text
POST /api/analyze -> pipeline.run() -> LLM(3-5s) -> embed -> match -> LLM -> LLM
                                         ↑ 整个请求等在这里                          ↑ 30-60s 后返回
```

**v3 (异步 —— API 立即返回，前端轮询进度):**

```text
POST /api/analyze -> DB 创建记录 -> enqueue Celery task -> 返回 {run_id, status: "processing"}
                         ↑ 50ms                                                   ↑ 立即返回

                               Redis (task queue)
                                    |
                          Celery Worker (background)
                                    |
                             pipeline.run() -> 每步写进度到 DB
                                    |
                              10% 解析 -> 30% 提取 -> 55% 匹配 -> ... -> 100% 完成

前端: POST -> 拿到 run_id -> 跳转到 /analyses/{run_id}
      HTMX 每 2s 轮询 /api/analyses/{id}/progress
      进度条: "10% 解析文档" -> "30% 提取义务" -> ... -> 自动切为结果看板
```

---

## 三、架构总览（v3）

```text
+------------------------------------------------------------------------------------------+
|                                    Docker Compose                                          |
|                                                                                            |
|  +---------------------------------------------------------------------------+             |
|  |  regintel-app (FastAPI + Uvicorn)                                         |             |
|  |  POST /api/analyze -> 写入DB -> enqueue Celery -> 立即返回 {run_id}        |             |
|  |  GET  /api/analyses/{id}/progress -> 从 DB 读取进度 JSON                     |             |
|  |  GET  /api/analyses/{id} -> 返回完整分析结果                                   |             |
|  +---------------------------------------+-----------------------------------+             |
|                                          |                                                   |
|                                          v                                                   |
|                               +----------+----------+                                        |
|                               |       Redis         |                                        |
|                               | (Broker: task queue) |                                        |
|                               +----------+----------+                                        |
|                                          |                                                   |
|                   +----------------------+-----------------------+                            |
|                   |                                              |                            |
|                   v                                              v                            |
|  +--------------------------------+        +-----------------------------------------+      |
|  |  celery-worker                 |        |  postgres (pgvector/pg16)                |      |
|  |  --concurrency=2 (默认)         |        |                                         |      |
|  |                                |        |  analysis_runs.progress JSONB            |      |
|  |  从 Redis 取任务 -> 执行管线     |<------|  analysis_runs.status VARCHAR             |      |
|  |  -> 逐级更新进度到 DB            |        |  8 表 + IVFFlat index                    |      |
|  +--------------------------------+        +-----------------------------------------+      |
|                                                                                            |
|  持久卷: postgres_data, uploads_data, redis_data                                           |
|                                                                                            |
|  --- 调度预留 (就绪但默认不启动) ---                                                         |
|  celery-beat: 定时触发 auto_pull_regulations 任务 (v3.1 实现)                                |
+------------------------------------------------------------------------------------------+
```

**服务依赖图：**

```text
postgres ◄──── regintel-app (FastAPI, 读写分析数据)
redis    ◄──── regintel-app (仅 enqueue 任务, 50ms)
redis    ◄──── celery-worker (取任务, 写进度+结果到 DB)
               celery-worker ◄──── postgres
```

---

## 四、新增/变更组件

### 4.1 `app/tasks.py` — Celery 任务定义（新增）

```python
from celery import Celery
from app.config import settings
from app.services.pipeline import RegIntelPipeline
from app.db.repository import update_run_progress, update_run_status

celery_app = Celery(
    "regintel",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def run_analysis(self, run_id: str):
    """后台执行完整分析管线, 每步写入进度到 DB."""
    try:
        pipeline = RegIntelPipeline()
        pipeline.run(run_id)
    except Exception as exc:
        update_run_status(run_id, "failed")
        self.retry(exc=exc)

# ═══════════════════════════════════════════════════
# 调度预留接口 —— v3.1 接入外部系统时实现
# ═══════════════════════════════════════════════════

@celery_app.task
def auto_pull_regulations():
    """定时从外部监管系统拉取新规。调度由 Celery Beat 触发。
       TODO: v3.1 接入时实现具体业务逻辑。"""
    pass  # 接口已就绪

# 取消下面注释即启用每日定时拉取 (需要新增 beat 容器)
# from celery.schedules import crontab
# celery_app.conf.beat_schedule = {
#     "auto-pull-regulations-daily": {
#         "task": "app.tasks.auto_pull_regulations",
#         "schedule": crontab(hour=8, minute=0),
#     },
# }
```

### 4.2 `app/services/pipeline.py` — 管线逐级写进度（变更）

```python
class RegIntelPipeline:
    def run(self, run_id: str):
        repo = AnalysisRepository()

        self._progress(run_id, "Parsing document", 5)
        doc = self.parser.parse(...)

        self._progress(run_id, "Extracting obligations", 20)
        obligations = self.extractor.extract(doc)
        with get_connection() as conn:
            repo.save_obligations(conn, obligations, reg.id)

        self._progress(run_id, "Generating embeddings", 35)
        for ob in obligations:
            ob.embedding = self.embedder.embed(ob.description)

        self._progress(run_id, "Matching controls (pgvector)", 55)
        mappings = self.matcher.match_all(obligations)

        self._progress(run_id, "Analyzing gaps", 75)
        gaps = self.gap_analyzer.analyze(mappings)

        self._progress(run_id, "Generating recommendations", 90)
        recs = self.recommender.generate(gaps)

        self._progress(run_id, "Complete", 100)
        update_run_status(run_id, "completed")

    def _progress(self, run_id, step, percent):
        update_run_progress(run_id, {"step": step, "percent": percent})
```

### 4.3 `app/routers/upload.py` — 上传接口改为异步（变更）

```python
from app.tasks import run_analysis as run_analysis_task

@router.post("/api/analyze")
async def upload_and_analyze(file: UploadFile = None, use_sample: bool = False):
    regulation = save_upload(file or load_sample())
    run_id = create_analysis_run(regulation.id)

    # 异步触发 —— 不阻塞, 50ms 返回
    run_analysis_task.delay(str(run_id))

    return {
        "run_id": str(run_id),
        "status": "processing",
        "progress_url": f"/analyses/{run_id}",
    }
```

### 4.4 新增 progress 端点

```python
@router.get("/api/analyses/{run_id}/progress")
async def get_progress(run_id: UUID):
    with get_connection() as conn:
        run = repo.get_analysis_run(conn, run_id)

    if run["status"] == "completed":
        return HTMLResponse(render_full_dashboard(run_id))

    return {"status": run["status"], "progress": run["progress"]}
```

### 4.5 前端 HTMX 轮询

```html
<!-- 分析中: 进度条, 每 2s 自动更新 -->
{% if analysis.status != "completed" %}
<div id="progress-section"
     hx-get="/api/analyses/{{ analysis.id }}/progress"
     hx-trigger="every 2s"
     hx-target="#progress-section"
     hx-swap="outerHTML">
  <div class="progress" style="height: 24px;">
    <div class="progress-bar progress-bar-striped progress-bar-animated"
         style="width: {{ analysis.progress.percent }}%">
      {{ analysis.progress.step }} ({{ analysis.progress.percent }}%)
    </div>
  </div>
</div>
{% endif %}

<!-- 完成时: 轮询返回的 HTML 替代进度条, 无 hx-trigger 则轮询自动停止 -->
{% if analysis.status == "completed" %}
<div id="results-section">
  ... 完整结果看板 (覆盖度图表 + 匹配矩阵 + 差距 + 建议) ...
</div>
{% endif %}
```

---

## 五、数据库变更

```sql
-- analysis_runs 表新增 progress 字段
ALTER TABLE analysis_runs
  ADD COLUMN progress JSONB NOT NULL DEFAULT '{"step": "", "percent": 0}';

-- progress 示例数据:
-- {"step": "Matching controls (pgvector)", "percent": 55}
-- {"step": "Complete", "percent": 100}
```

---

## 六、Docker Compose（v3 完整版）

```yaml
services:
  regintel-app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://regintel:regintel@postgres:5432/regintel
      - REDIS_URL=redis://redis:6379/0
      - LLM_API_ENDPOINT=${LLM_API_ENDPOINT}
      - LLM_API_KEY=${LLM_API_KEY}
    volumes:
      - uploads_data:/app/data/uploads
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_started
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

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5
    restart: unless-stopped

  celery-worker:
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
  redis_data:
```

---

## 七、项目结构变更

| 文件 | 动作 | 说明 |
|------|------|------|
| `app/tasks.py` | **新增** | Celery 任务定义 + 调度预留接口 |
| `app/main.py` | 变更 | lifespan 事件 (不变, Celery 独立进程) |
| `app/config.py` | 变更 | +REDIS_URL 配置 |
| `app/routers/upload.py` | 变更 | delay() 替代同步 run() |
| `app/routers/analysis.py` | 变更 | +progress 端点 |
| `app/services/pipeline.py` | 变更 | 每步更新进度 |
| `app/db/repository.py` | 变更 | +update_progress(), +get_progress() |
| `app/templates/dashboard.html` | 变更 | +进度条 + HTMX 轮询 |
| `docker-compose.yml` | 变更 | +redis, +celery-worker |
| `.env.example` | 变更 | +REDIS_URL |
| `requirements.txt` | 变更 | +celery, +redis |

---

## 八、执行计划增量

v3 是 v2 基础上的增量，不重写已有工作：

| 内容 | 预计 |
|------|------|
| `app/tasks.py` + `pipeline.py` 进度改造 | 1 天 |
| routers 改造 + progress 端点 | 0.5 天 |
| 前端轮询 + progress 模板 | 0.5 天 |
| Docker Compose + 联调 | 0.5 天 |
| **v3 增量总计** | **~2.5 天** |

调整后的 Week 2：

| 天数 | 交付物 |
|------|--------|
| Day 8 | base.html + index.html + Bootstrap 5 框架 |
| Day 9 | 文件上传 + HTMX + history.html |
| Day 10 | dashboard.html + Chart.js 看板 |
| Day 11 | app/tasks.py + pipeline 进度改造 |
| Day 12 | routers 改造 + progress 端点 + 前端轮询 |
| Day 13 | Docker Compose 集成 + 端到端联调 |
| Day 14 | 演练 + 展板 |

---

## 九、优势

| 场景 | v2 (同步) | v3 (异步) | 优势 |
|------|-----------|-----------|------|
| API 响应时间 | 30-60s | 50ms | 立即返回, 无超时风险 |
| 并发分析 | 一个接一个 | --concurrency=N | 同时处理多个分析 |
| 失败重试 | 用户手动重来 | 自动 3 次重试 | LLM 超时不丢任务 |
| 进度可视化 | 白屏等待 | 实时进度条 | Demo 体验好很多 |
| 定时调度 | 不支持 | Celery Beat 预留 | 取消注释即启用 |
| 扩展性 | 垂直 | 水平加 worker | 加容器 = 加吞吐 |

| 代价 | 说明 |
|------|------|
| +1 服务 (Redis, ~5MB) | 极低开销 |
| +1 服务 (Worker, ~150MB) | 合理 |
| 前端增加轮询逻辑 | HTMX 一个属性搞定 |

---

## 十、调度预留接口说明

v3 留好两个层次的调度接口, 后续不需要改架构:

**接口 1: 任务定义**

```python
@celery_app.task
def auto_pull_regulations():
    """定时从外部系统拉取新规. TODO: v3.1 实现."""
    pass
```

**接口 2: Beat 调度 (取消注释即启用)**

```python
celery_app.conf.beat_schedule = {
    "auto-pull-regulations-daily": {
        "task": "app.tasks.auto_pull_regulations",
        "schedule": crontab(hour=8, minute=0),
    },
}
```

启用时只需:
1. 取消上面代码的注释
2. docker-compose.yml 加一行 `celery -A app.tasks beat` (参考 worker 的配置, command 换成 beat)
3. 实现 `auto_pull_regulations` 的业务逻辑

不需要改任何路由、表结构、前端页面。

---

## 十一、v3 Demo 体验

```text
传统 (v2):  上传 -> 白屏 30s -> 突然看到结果

v3:         上传 -> 跳转到进度页 -> 进度条实时更新:
             5%  "Parsing document"
            20%  "Extracting obligations"
            35%  "Generating embeddings"
            55%  "Matching controls (pgvector)"
            75%  "Analyzing gaps"
            90%  "Generating recommendations"
           100%  "Complete" -> 自动切换为完整看板

            期间可以切页面、开新分析、回看历史记录
```

---


# RegIntel AI — Software Architecture (v3.1)

> **版本: v3.1 — 2026-06-29 — +Airflow 定时调度 + Ansible 自动修复 + 后续探索方向**

---

## 一、v3.1 演进：Celery vs Airflow 分工

```
Celery (已有)        ─  管实时异步：用户上传 → 后台分析 → 进度轮询
Airflow (v3.1新增)   ─  管定时调度：每日拉取监管源 → 触发批量分析 → 编排 Ansible

不重叠。
Celery 处理用户触发的短任务(30-60s)，Airflow 处理系统触发的长流程(分钟~小时级)。
```

---

## 二、架构总览（v3.1）

```text
+------------------------------------------------------------------------------------------+
|                                    Docker Compose                                          |
|                                                                                            |
|                   已有服务 (v3)                                                             |
|  +--------------+  +--------------+  +---------------+  +--------------+                   |
|  | regintel-app |  | celery-worker|  | redis         |  | postgres     |                   |
|  | (FastAPI)    |  |              |  | (broker)      |  | (pgvector)   |                   |
|  +------+-------+  +------+-------+  +-------+-------+  +------+-------+                   |
|         |                 |                   |                 |                            |
|         +--------+--------+-------------------+-----------------+                            |
|                  |                                               |                            |
|                  |              新增服务 (v3.1)                   |                            |
|                  |                                               |                            |
|  +---------------▼--------------+          +---------------------▼----------+                |
|  |  airflow-scheduler           |          |  airflow-db                    |                |
|  |  DAG: pull_regulations_daily |          |  (Airflow 元数据 DB,          |                |
|  |  DAG: compliance_check_weekly|          |   可选与 regintel DB 共用)     |                |
|  |  DAG: ansible_remediate      |          +--------------------------------+                |
|  +---------------┬--------------+                                               |
|                  |                                                               |
|  +---------------▼--------------+                                               |
|  |  airflow-webserver           |                                               |
|  |  (UI, port 8080)             |                                               |
|  +---------------┬--------------+                                               |
|                  |                                                               |
|  +---------------▼--------------+                                               |
|  |  Ansible Runner (容器)       |                                               |
|  |  playbooks/check_*.yml      |──→ 目标系统(SSH/API)                          |
|  +------------------------------+                                               |
|                                                                                    |
|  卷: postgres_data, uploads_data, redis_data, airflow_db_data, dags/, playbooks/   |
+------------------------------------------------------------------------------------------+
```

**服务依赖图：**

```text
外部监管 API (FCA/PRA/MAS)
       │
       │ HTTP pull (定时)
       ▼
airflow-scheduler ──→ 写入 regulations 表 ──→ postgres (regintel)
       │
       ├──→ compliance_check_weekly ──→ 读取 regulations 表
       │       └── 新规? ──→ pipeline.run() (可调 Celery 或 Airflow 自己的 Worker)
       │
       └──→ ansible_remediate ──→ 读取 gaps 表
               └── auto_fixable? ──→ Ansible Runner 容器
                       └── 回写 evidence 到 gap_analyses 表

用户操作 (已有):
regintel-app ──→ Celery ──→ pipeline.run() ──→ 写分析结果到 postgres

三者通过同一 PostgreSQL 的 regulations / gaps 表状态耦合，不直接依赖彼此。
```

---

## 三、三个核心 DAG

### DAG 1: `pull_regulations_daily`

```python
# 每日 8:00
with DAG("pull_regulations_daily", schedule="0 8 * * *"):
    pull_fca = PythonOperator(task_id="pull_fca",
        python_callable=lambda: fetch_and_store("FCA", FCA_API_URL))
    pull_pra = PythonOperator(task_id="pull_pra",
        python_callable=lambda: fetch_and_store("PRA", PRA_API_URL))
    pull_mas = PythonOperator(task_id="pull_mas",
        python_callable=lambda: fetch_and_store("MAS", MAS_API_URL))
    mark_pending = PythonOperator(task_id="mark_pending",
        python_callable=flag_new_regulations_for_analysis)
    [pull_fca, pull_pra, pull_mas] >> mark_pending
```

### DAG 2: `compliance_check_weekly`

```python
# 每周一 9:00
with DAG("compliance_check_weekly", schedule="0 9 * * 1"):
    fetch_pending >> run_analyses >> generate_summary_report
```

### DAG 3: `ansible_remediate`

```python
# 手动触发 (schedule=None)
with DAG("ansible_remediate", schedule=None):
    fetch_gaps >> run_playbook >> verify_result
```

---

## 四、Ansible 集成模式

```
方案选型: Ansible Runner 容器 (推荐)

airflow-scheduler
  └─ BashOperator:
       docker run --rm -v $(pwd)/playbooks:/playbooks \
         ansible/ansible-runner run /playbooks/check_{gap_type}.yml
       → 结果写回 PostgreSQL
       → Airflow 读取结果, 更新 gap 状态

Playbook 示例: playbooks/check_access_control.yml
  - 检查 /etc/security/access.conf 特权用户列表
  - 验证 PAM MFA 配置
  - POST 结果到 regintel API /api/internal/gaps/{id}/evidence
```

---

## 五、Docker Compose 新增服务

```yaml
services:
  # 已有: regintel-app, postgres, redis, celery-worker ...

  airflow-db:
    image: postgres:16
    environment:
      - POSTGRES_DB=airflow
      - POSTGRES_USER=airflow
      - POSTGRES_PASSWORD=airflow
    volumes:
      - airflow_db_data:/var/lib/postgresql/data

  airflow-scheduler:
    build:
      context: .
      dockerfile: Dockerfile.airflow
    command: airflow scheduler
    environment:
      - AIRFLOW__CORE__EXECUTOR=LocalExecutor
      - AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=postgresql+psycopg2://airflow:airflow@airflow-db:5432/airflow
      - AIRFLOW__CORE__LOAD_EXAMPLES=False
    volumes:
      - ./dags:/opt/airflow/dags
      - ./playbooks:/opt/airflow/playbooks
    depends_on: [airflow-db, postgres]

  airflow-webserver:
    build:
      context: .
      dockerfile: Dockerfile.airflow
    command: airflow webserver
    ports:
      - "8080:8080"
    environment:
      - AIRFLOW__CORE__EXECUTOR=LocalExecutor
      - AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=postgresql+psycopg2://airflow:airflow@airflow-db:5432/airflow
    volumes:
      - ./dags:/opt/airflow/dags
    depends_on: [airflow-scheduler]

volumes:
  airflow_db_data:
```

**Dockerfile.airflow:**
```dockerfile
FROM apache/airflow:2.10-slim
RUN pip install ansible-runner
```

**项目新增目录结构：**
```
dags/
├── pull_regulations_daily.py
├── compliance_check_weekly.py
├── ansible_remediate.py
└── shared/
    └── db_hooks.py            # 连接 regintel PostgreSQL

playbooks/
├── inventory/
│   └── prod.ini
├── check_access_control.yml
├── check_data_protection.yml
└── shared/
    └── report_to_regintel.yml
```

---

## 六、数据流全景

```text
定时触发 (Airflow)
  │
  ├── pull_regulations_daily ──→ FCA/PRA/MAS API ──→ regulations 表
  │
  ├── compliance_check_weekly ──→ 读取 regulations 表
  │     ├── 已有分析? ──→ 跳过
  │     └── 新规? ──→ pipeline.run() ──→ obligations/mappings/gaps/recommendations
  │
  └── ansible_remediate ──→ 读取 gaps(coverage_status='missing')
        ├── auto_fixable? ──→ Ansible playbook ──→ 目标系统
        └── 更新 gap 状态 + 回写 evidence

按需触发 (用户)
  ├── FastAPI POST /api/analyze ──→ Celery ──→ pipeline.run()
  └── FastAPI POST /api/analyses/{id}/remediate ──→ 触发 Airflow DAG (REST API)
```

---

## 七、后续探索方向

以下方向在当前架构中已预留接口或位置，但 **v3.1 未实现**，列为后续探索：

| 方向 | 涉及 | 说明 |
|------|------|------|
| **外部监管源对接** | Airflow DAG `pull_regulations_daily` | 对接 FCA/PRA/MAS/RBI 等公开 API，`fetch_and_store()` 需按各源实现不同的认证和解析逻辑 |
| **Ansible playbook 扩展** | `playbooks/` 目录 | 当前仅有 access_control 样板，需按实际合规领域补充 data_protection/aml/operational_resilience 等 playbook |
| **合规证据回写协议** | regintel API `/api/internal/gaps/{id}/evidence` | Ansible 执行结果到 gap 状态的映射标准和证据格式规范 |
| **Airflow → Celery 任务桥接** | compliance_check_weekly DAG | 批量分析使用 Airflow 自己的 Worker 还是回调 Celery 的 task queue？各有优劣 |
| **Airflow 与 regintel DB 共享 vs 隔离** | Docker Compose | 当前设计共用同一 PostgreSQL。长期看 Airflow 元数据 DB 与业务 DB 是否应该分离？ |
| **合规报告自动分发** | DAG 下游 | 每周报告生成后是否自动邮件/Teams/Slack 推送给合规团队？ |
| **批量分析的去重与增量策略** | pull_regulations_daily | 同一份监管文件被多次拉取时如何 dedup？仅分析 diff？ |
| **Airflow 权限与审计** | airflow-webserver | 多人协作时，Airflow UI 的 RBAC 策略和操作审计日志 |
| **与现有 CI/CD 集成** | Ansible playbook + 配置管理 | 合规修复 playbook 是否能复用公司已有的 CMDB / 配置管理管线？ |
| **成本与性能基线** | 全链路 | 100/1000 条监管文件场景下各环节的耗时和资源消耗基线，用于决定何时从 Celery LocalWorker 迁移到 Celery 集群 / Airflow CeleryExecutor |

---

## 修订记录

| 版本 | 日期 | 变更说明 |
|------|------|----------|
| v3.1 | 2026-06-29 | +Airflow 定时调度 + Ansible 自动修复 + 后续探索方向 |
| v3.0 | 2026-06-29 | +Celery + Redis 异步编排 + 进度轮询 + 调度预留接口 |
| v2.0 | 2026-06-29 | FastAPI + PostgreSQL + pgvector + Docker Compose + Jinja2/HTMX |
| v1.0 | 2026-06-29 | 初版架构定稿 (Streamlit + 内存) |

---

## 附录：监管机构缩写对照

| 缩写 | 全称 | 管辖地 | 监管方向 |
|------|------|--------|----------|
| **FCA** | Financial Conduct Authority | 英国 | 行为监管、市场诚信、消费者保护 |
| **PRA** | Prudential Regulation Authority | 英国 | 审慎监管、资本充足率、流动性（英格兰银行下设） |
| **MAS** | Monetary Authority of Singapore | 新加坡 | 综合监管（央行+金融监管合一） |
| **RBI** | Reserve Bank of India | 印度 | 央行职能+银行监管、支付系统、外汇管理 |

---

## 附录：版本演进与目录映射

本文档按版本迭代记录。每个版本只新增/替换文件，不重写已有模块，确保 `services/`、`models/`、`data/` 三个核心目录在版本间完全复用。

```text
          services/   models/   data/   app.py   app/    docker/   dags/
v1           ●          ●        ●       ●        -        -        -
v2           ●          ●        ●       -        ●        ●        -
v3           ●          ●        ●       -        ●        ●        -
v3.1         ●          ●        ●       -        ●        ●        ●
            └── 永不改写 ──┘      └─ 换入口 ─┘  └─ 逐版本追加 ──┘
```

| 版本 | 入口 | 内核共用 | 新增的主要目录/文件 |
|------|------|----------|-------------------|
| v1 | `app.py` (Streamlit) | services/, models/, data/ | styles/, requirements-v1.txt |
| v2 | `app/main.py` (FastAPI) | 同 v1 | app/, db/, static/, Dockerfile, docker-compose.yml |
| v3 | 同 v2 | 同 v1 | app/tasks.py, +redis/+celery-worker |
| v3.1 | 同 v2 | 同 v1 | dags/, playbooks/, +airflow |
