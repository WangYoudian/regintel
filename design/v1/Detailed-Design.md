# RegIntel AI — v1 Detailed Design

> Streamlit + Session State + Mock Data 版本
> 快速原型，验证核心管线逻辑

---

## 一、系统模块与服务关系图

```mermaid
graph TB
    subgraph Frontend["前端层 (Streamlit)"]
        UI["app.py<br/>页面布局 + 交互"]
        CSS["custom.css<br/>样式"]
    end

    subgraph Orchestration["编排层"]
        PL["pipeline.py<br/>管线编排"]
    end

    subgraph Services["服务层"]
        LLM["llm_client.py<br/>LLM API 客户端"]
        DP["document_parser.py<br/>文档解析"]
        CE["compliance_extractor.py<br/>合规义务提取"]
        ES["embedding_service.py<br/>Embedding 生成"]
        MT["matcher.py<br/>语义匹配"]
        GA["gap_analyzer.py<br/>差距分析"]
        RE["recommendation_engine.py<br/>建议生成"]
        RG["report_generator.py<br/>报告生成"]
    end

    subgraph Models["数据模型层"]
        DM["domain.py<br/>Pydantic 领域模型"]
    end

    subgraph Data["数据层"]
        MC["mock/<br/>internal_controls.json"]
        SR["mock/<br/>sample_regulation.md"]
        SS["Streamlit Session State"]
    end

    UI --> PL
    PL --> DP
    PL --> CE
    PL --> ES
    PL --> MT
    PL --> GA
    PL --> RE
    PL --> RG

    CE --> LLM
    RE --> LLM
    GA --> LLM

    DP --> DM
    CE --> DM
    MT --> DM
    GA --> DM
    RE --> DM
    RG --> DM

    MT --> ES
    CE --> MC
    MT --> MC

    UI --> SS
    PL --> SS
    RG --> SS

    style Frontend fill:#e1f5fe
    style Orchestration fill:#fff3e0
    style Services fill:#e8f5e9
    style Models fill:#f3e5f5
    style Data fill:#fce4ec
```

---

## 二、ER 图（数据模型关系）

v1 无数据库，数据存在于 Pydantic 对象和图中的 Streamlit Session State。以下展示各模型的逻辑关系：

```mermaid
erDiagram
    Regulation ||--o{ ComplianceObligation : contains
    ComplianceObligation ||--o{ MappingResult : maps_to
    InternalControl ||--o{ MappingResult : matched_by
    MappingResult ||--o{ GapAnalysis : leads_to
    GapAnalysis ||--o{ Recommendation : generates
    AnalysisReport ||--|| Regulation : based_on
    AnalysisReport ||--o{ ComplianceObligation : includes
    AnalysisReport ||--o{ MappingResult : includes
    AnalysisReport ||--o{ GapAnalysis : includes
    AnalysisReport ||--o{ Recommendation : includes

    Regulation {
        uuid id PK
        string title
        string source "FCA / PRA / MAS / RBI"
        date published_date
        string content
        string summary
    }

    ComplianceObligation {
        uuid id PK
        uuid regulation_id FK
        string description
        string source_ref "条款编号"
        string category "Access Control / Data Protection / ..."
        string risk_level "High / Medium / Low"
        vector embedding "384维向量"
    }

    InternalControl {
        uuid id PK
        string name
        string description
        string category
        string frequency "Daily / Weekly / Quarterly / ..."
        string owner
        string status "Active / Draft / Deprecated"
        vector embedding "384维向量"
    }

    MappingResult {
        uuid id PK
        uuid obligation_id FK
        uuid control_id FK
        float similarity_score
        string coverage_status "covered / partial / missing"
    }

    GapAnalysis {
        uuid id PK
        uuid mapping_result_id FK
        string gap_description
        string risk_impact
    }

    Recommendation {
        uuid id PK
        uuid gap_analysis_id FK
        jsonb action_items "['item1', 'item2', ...]"
        string priority "High / Medium / Low"
        string estimated_effort
    }

    AnalysisReport {
        uuid id PK
        uuid regulation_id FK
        string summary
        int total_obligations
        jsonb coverage_summary "{covered: 3, partial: 3, missing: 2}"
        datetime generated_at
    }
```

> 注：`vector` 和 `jsonb` 是 v2 引入 PostgreSQL + pgvector 后的实际类型。v1 中对应为 `list[float]` 和 `dict`/`list`。

---

## 三、UML 类图

```mermaid
classDiagram
    class Regulation {
        +UUID id
        +str title
        +str source
        +date published_date
        +str content
        +str summary
        +summarize() str
    }

    class ComplianceObligation {
        +UUID id
        +str description
        +str source_ref
        +str category
        +str risk_level
        +list~float~ embedding
        +to_dict() dict
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
        +ComplianceObligation obligation
        +InternalControl control
        +float similarity_score
        +str coverage_status
    }

    class GapAnalysis {
        +UUID id
        +MappingResult mapping_result
        +str gap_description
        +str risk_impact
    }

    class Recommendation {
        +UUID id
        +GapAnalysis gap
        +list~str~ action_items
        +str priority
        +str estimated_effort
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

    class DocumentParser {
        +parse(file_path) Regulation
        +_parse_pdf(path) str
        +_parse_docx(path) str
        +_chunk_by_sections(text) list~str~
    }

    class ComplianceExtractor {
        +LLMClient llm
        +extract(regulation) list~ComplianceObligation~
        +_deduplicate(obligations) list~ComplianceObligation~
    }

    class EmbeddingService {
        +embed(text) list~float~
        +embed_batch(texts) list~list~float~~
        +_model SentenceTransformer
    }

    class SemanticMatcher {
        +EmbeddingService embedder
        +list~InternalControl~ controls
        +match(obligation) list~MappingResult~
        +match_all(obligations) list~MappingResult~
        +_cosine_similarity(a, b) float
    }

    class GapAnalyzer {
        +LLMClient llm
        +analyze(mappings) list~GapAnalysis~
        +_rule_based_analysis(mapping) GapAnalysis
        +_llm_enhanced_analysis(mapping) GapAnalysis
    }

    class RecommendationEngine {
        +LLMClient llm
        +generate(gaps) list~Recommendation~
    }

    class ReportGenerator {
        +generate(report) str
        +_build_markdown(report) str
    }

    class RegIntelPipeline {
        -DocumentParser parser
        -ComplianceExtractor extractor
        -EmbeddingService embedder
        -SemanticMatcher matcher
        -GapAnalyzer gap_analyzer
        -RecommendationEngine recommender
        -ReportGenerator reporter
        +run(file_path) AnalysisReport
        +_progress(step, percent)
    }

    class LLMClient {
        +str endpoint
        +str api_key
        +chat(messages) str
        +chat_structured(messages, response_model) T
        +embed(text) list~float~
    }

    Regulation "1" --> "*" ComplianceObligation : contains
    ComplianceObligation "1" --> "*" MappingResult : maps to
    InternalControl "1" --> "*" MappingResult : matched by
    MappingResult "1" --> "*" GapAnalysis : leads to
    GapAnalysis "1" --> "*" Recommendation : generates
    AnalysisReport "1" --> "1" Regulation : based on
    AnalysisReport "1" --> "*" ComplianceObligation : includes
    AnalysisReport "1" --> "*" MappingResult : includes
    AnalysisReport "1" --> "*" GapAnalysis : includes
    AnalysisReport "1" --> "*" Recommendation : includes

    DocumentParser ..> Regulation : produces
    ComplianceExtractor ..> ComplianceObligation : extracts
    EmbeddingService ..> ComplianceObligation : enriches
    EmbeddingService ..> InternalControl : enriches
    SemanticMatcher ..> MappingResult : produces
    GapAnalyzer ..> GapAnalysis : produces
    RecommendationEngine ..> Recommendation : produces
    ReportGenerator ..> AnalysisReport : produces

    RegIntelPipeline --> DocumentParser
    RegIntelPipeline --> ComplianceExtractor
    RegIntelPipeline --> EmbeddingService
    RegIntelPipeline --> SemanticMatcher
    RegIntelPipeline --> GapAnalyzer
    RegIntelPipeline --> RecommendationEngine
    RegIntelPipeline --> ReportGenerator
    ComplianceExtractor --> LLMClient
    GapAnalyzer --> LLMClient
    RecommendationEngine --> LLMClient
    EmbeddingService --> LLMClient
```

---

## 四、核心时序图

### 4.1 文件上传 → 分析完成（全流程）

```mermaid
sequenceDiagram
    actor User as 用户
    participant UI as Streamlit UI<br/>(app.py)
    participant PL as Pipeline<br/>(pipeline.py)
    participant DP as DocumentParser
    participant LLM as LLM Client
    participant ES as EmbeddingService
    participant MT as SemanticMatcher
    participant GA as GapAnalyzer
    participant RE as RecommendationEngine
    participant RG as ReportGenerator
    participant SS as Session State

    User->>UI: 上传文件 / 点击示例
    UI->>PL: pipeline.run(file_path)

    PL->>DP: parse(file_path)
    DP-->>PL: Regulation (content, metadata)

    PL->>UI: 显示摘要卡片
    UI->>User: ✅ 文件已解析

    PL->>LLM: chat_structured(提取义务)
    LLM-->>PL: List[ComplianceObligation]
    PL->>UI: 显示义务列表
    UI->>User: ✅ 已提取 8 条义务

    PL->>ES: embed_batch(obligations)
    ES-->>PL: List[embedding vectors]
    PL->>ES: embed_batch(controls)
    ES-->>PL: List[embedding vectors]

    PL->>MT: match_all(obligations, controls)
    MT->>MT: cosine_similarity 矩阵
    MT-->>PL: List[MappingResult]

    PL->>UI: 显示匹配热力图
    UI->>User: ✅ 匹配完成 (3 绿 / 3 黄 / 2 红)

    PL->>LLM: chat_structured(分析差距)
    LLM-->>PL: List[GapAnalysis]
    PL->>UI: 显示差距详情
    UI->>User: ✅ 差距分析完成

    PL->>LLM: chat_structured(生成建议)
    LLM-->>PL: List[Recommendation]
    PL->>UI: 显示建议卡片
    UI->>User: ✅ 建议已生成

    PL->>RG: generate(report)
    RG-->>PL: Markdown string
    PL->>SS: 保存 AnalysisReport
    PL-->>UI: 显示管理看板

    UI->>User: 🎉 分析完成 (30-60s)
    UI->>User: 覆盖度雷达图 / KPI 卡片 / 导出按钮
```

### 4.2 语义匹配子流程

```mermaid
sequenceDiagram
    participant PL as Pipeline
    participant ES as EmbeddingService
    participant MT as SemanticMatcher
    participant NUMPY as numpy

    PL->>ES: embed(obligation.description)
    ES-->>PL: v_obligation (384维)

    PL->>ES: embed(control_1.description)
    ES-->>PL: v_control_1

    PL->>ES: embed(control_N.description)
    ES-->>PL: v_control_N

    PL->>MT: match_all([v_obligation], [v_controls])

    MT->>MT: 构建矩阵 M = [v_control_1, ..., v_control_N]
    Note over MT: M.shape = (N_controls, 384)

    MT->>NUMPY: cosine_similarity(v_obligation, M)
    NUMPY-->>MT: similarities (N_controls,)

    MT->>MT: 判断阈值, 分类 all similarities:
    Note over MT: >= 0.85 → "covered"<br/>>>= 0.65 → "partial"<br/>< 0.65 → "missing"

    MT->>MT: 取 top-3 (covered + partial)

    MT-->>PL: [MappingResult × 3]
```

### 4.3 LLM 结构化输出子流程

```mermaid
sequenceDiagram
    participant CE as ComplianceExtractor
    participant LLM as LLM API
    participant PD as Pydantic

    CE->>CE: 构造 System Prompt
    Note over CE: "你是合规分析师,<br/>从监管文本中提取合规义务,<br/>返回结构化 JSON"

    CE->>CE: 构造 User Prompt
    Note over CE: 监管文本 + 条款编号

    CE->>LLM: chat(messages, response_format={type:"json_object"})

    LLM-->>CE: raw_json

    CE->>PD: ComplianceObligation(**raw_json)

    alt 校验通过
        PD-->>CE: ✅ ComplianceObligation instance
    else 校验失败
        CE->>LLM: retry (max 2 次)
        LLM-->>CE: raw_json (修正后)
        CE->>PD: ComplianceObligation(**raw_json)
        alt 再次失败
            CE->>CE: fallback 默认值
            CE-->>CE: ⚠️ ComplianceObligation (带默认值)
        end
    end

    CE-->>CE: deduplicate(合并跨章节同一义务)
    CE-->>Pipeline: List[ComplianceObligation]
```

---

## 五、Streamlit 页面结构

```mermaid
graph TB
    subgraph App["app.py — 单页多区布局"]
        Sidebar["侧边栏<br/>文件上传 / 示例加载<br/>处理触发 / 缓存管理"]

        Step1["Step 1: 文件摘要<br/>预览 + 元数据卡片"]
        Step2["Step 2: 合规义务<br/>可展开列表 + 原文引用"]
        Step3["Step 3: 匹配矩阵<br/>义务 × 控制 热力图<br/>绿/黄/红 颜色编码"]
        Step4["Step 4: 差距分析<br/>每个 Gap 一个卡片<br/>描述 + 风险影响"]
        Step5["Step 5: 管理看板<br/>雷达图 / 饼图 / KPI"]
        Step6["Step 6: 报告导出<br/>预览 + 一键下载"]

        Sidebar --> Step1
        Step1 --> Step2
        Step2 --> Step3
        Step3 --> Step4
        Step4 --> Step5
        Step5 --> Step6
    end

    style Sidebar fill:#f5f5f5
    style Step1 fill:#e3f2fd
    style Step2 fill:#e3f2fd
    style Step3 fill:#e3f2fd
    style Step4 fill:#e3f2fd
    style Step5 fill:#e3f2fd
    style Step6 fill:#e3f2fd
```

---

## 六、目录结构清单

```
regintel/
├── app.py                          # Streamlit 入口
├── config.py                       # 配置项
├── requirements.txt                # 依赖
├── README.md                       # 启动指南
│
├── services/
│   ├── __init__.py
│   ├── llm_client.py               # LLM API 客户端
│   ├── document_parser.py          # PDF/DOCX/TXT 解析
│   ├── compliance_extractor.py     # 合规义务提取
│   ├── embedding_service.py        # Embedding 生成
│   ├── matcher.py                  # 语义匹配 (numpy)
│   ├── gap_analyzer.py             # 差距分析
│   ├── recommendation_engine.py    # 建议生成
│   ├── report_generator.py         # 报告生成
│   └── pipeline.py                 # 管线编排
│
├── models/
│   ├── __init__.py
│   └── domain.py                   # Pydantic 数据模型
│
├── data/
│   ├── mock/
│   │   ├── internal_controls.json  # 25-30 条 Mock 内控
│   │   └── sample_regulation.md    # 模拟 FCA 监管文件
│   └── uploads/                    # 上传文件 (gitignore)
│
├── styles/
│   └── custom.css                  # Streamlit 自定义样式
│
├── tests/
│   ├── test_document_parser.py
│   ├── test_compliance_extractor.py
│   ├── test_matcher.py
│   └── test_gap_analyzer.py
│
└── design/
    └── v1/
        └── Detailed-Design.md      # 本文件
```

---

## 七、版本演进预留说明

v1 的目录结构已为 v2/v3 演进预留接口：

| v1 目录       | v2 变化                                 | v3 变化                    |
| ------------- | --------------------------------------- | -------------------------- |
| `app.py`    | → 替换为`app/main.py` (FastAPI)      | 不变                       |
| `styles/`   | → 替换为`static/` (FastAPI 静态文件) | 不变                       |
| `services/` | **不变，直接复用**                | **不变**             |
| `models/`   | **不变，直接复用**                | **不变**             |
| `data/`     | **不变**                          | **不变**             |
| —            | +`app/` 包 (FastAPI)                  | +`app/tasks.py` (Celery) |
| —            | +`db/` (PostgreSQL init)              | +`dags/` (Airflow)       |
| —            | +`Dockerfile`, `docker-compose.yml` | +`playbooks/` (Ansible)  |

核心原则：**services/、models/、data/ 三个目录在 v1 → v3.1 演进中不作改写，只新增不删改。**

---

## 修订记录

| 版本 | 日期       | 变更说明                                              |
| ---- | ---------- | ----------------------------------------------------- |
| v1.0 | 2026-06-29 | 初版详细设计：系统模块图/ER图/UML类图/时序图/页面结构 |
