# RegIntel AI — v3.1 Detailed Design

> Airflow 定时调度 + Ansible 自动修复 · 调度预留接口

---

## 一、系统模块与服务关系图

```mermaid
graph TB
    subgraph Docker["Docker Compose"]
        direction TB
        FA["regintel-app<br/>FastAPI + Uvicorn"]
        RD["redis"]
        CW["celery-worker"]
        AS["airflow-scheduler"]
        AW["airflow-webserver<br/>:8080"]
        AR["ansible-runner<br/>(容器化)"]
        PG["postgres<br/>pgvector/pg16"]
        AFDB["airflow-db<br/>postgres:16"]
    end

    subgraph External["外部系统"]
        FCA["FCA API"]
        PRA["PRA API"]
        MAS["MAS API"]
        TARGET["目标系统<br/>SSH/API"]
    end

    subgraph Airflow["Airflow 层 (新增)"]
        DAG1["pull_regulations_daily<br/>每日 8:00"]
        DAG2["compliance_check_weekly<br/>每周一 9:00"]
        DAG3["ansible_remediate<br/>手动触发"]
    end

    subgraph Ansible["Ansible 层 (新增)"]
        PB1["check_access_control.yml"]
        PB2["check_data_protection.yml"]
    end

    subgraph Existing["已有"]
        SVC["services/ (v1-v3 复用)"]
        DB["PostgreSQL<br/>regintel 业务表"]
    end

    FCA --> DAG1
    PRA --> DAG1
    MAS --> DAG1
    DAG1 --> DB

    DAG2 --> DB
    DAG2 --> SVC

    DAG3 --> DB
    DAG3 --> AR
    AR --> PB1
    AR --> PB2
    PB1 --> TARGET
    PB2 --> TARGET
    TARGET --> DB

    AS --> AFDB
    AW --> AFDB

    AS --> Airflow
    AW --> Airflow

    FA --> Existing

    style Docker fill:#fff3e0
    style External fill:#e1f5fe
    style Airflow fill:#ffcdd2
    style Ansible fill:#d1c4e9
    style Existing fill:#e8f5e9
```

**服务间数据流：**

```text
Celery 负责: 用户触发的实时分析 (v3)
Airflow 负责: 系统触发的定时任务 (v3.1)

二者不重叠，通过同一 PostgreSQL 耦合:

  1. pull_regulations_daily ──写入──▶ regulations 表
  2. compliance_check_weekly ──读取──▶ regulations → pipeline.run()
  3. ansible_remediate ────────读取──▶ gaps 表 → 执行 → 回写 evidence
```

---

## 二、DAG 设计

### 2.1 DAG: `pull_regulations_daily`

```python
from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime

default_args = {
    "owner": "regintel",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    "pull_regulations_daily",
    default_args=default_args,
    schedule="0 8 * * *",          # 每天 8:00 UTC
    start_date=datetime(2026, 7, 1),
    catchup=False,
    description="每日从外部监管 API 拉取新规",
) as dag:

    pull_fca = PythonOperator(
        task_id="pull_fca",
        python_callable=lambda: fetch_and_store(
            source="FCA",
            api_url=FCA_API_URL,
            api_key=FCA_API_KEY,
        ),
    )

    pull_pra = PythonOperator(
        task_id="pull_pra",
        python_callable=lambda: fetch_and_store(
            source="PRA",
            api_url=PRA_API_URL,
            api_key=PRA_API_KEY,
        ),
    )

    pull_mas = PythonOperator(
        task_id="pull_mas",
        python_callable=lambda: fetch_and_store(
            source="MAS",
            api_url=MAS_API_URL,
            api_key=MAS_API_KEY,
        ),
    )

    mark_pending = PythonOperator(
        task_id="mark_pending",
        python_callable=flag_new_regulations_for_analysis,
    )

    [pull_fca, pull_pra, pull_mas] >> mark_pending
```

### 2.2 DAG: `compliance_check_weekly`

```python
with DAG(
    "compliance_check_weekly",
    schedule="0 9 * * 1",          # 每周一 9:00 UTC
    start_date=datetime(2026, 7, 6),
    catchup=False,
):

    fetch_pending = PythonOperator(
        task_id="fetch_pending",
        python_callable=get_unanalyzed_regulations,
    )

    run_analyses = PythonOperator(
        task_id="run_analyses",
        python_callable=batch_run_analysis_pipeline,
    )

    generate_summary = PythonOperator(
        task_id="generate_summary",
        python_callable=build_weekly_compliance_digest,
    )

    fetch_pending >> run_analyses >> generate_summary
```

### 2.3 DAG: `ansible_remediate`

```python
with DAG(
    "ansible_remediate",
    schedule=None,                  # 手动触发
    description="按需执行 Ansible playbook 修复合规差距",
):

    fetch_gaps = PythonOperator(
        task_id="fetch_actionable_gaps",
        python_callable=get_gaps_with_auto_remediation,
    )

    run_playbook = BashOperator(
        task_id="run_ansible_playbook",
        bash_command=(
            "docker run --rm "
            "-v $(pwd)/playbooks:/playbooks "
            "-v $(pwd)/playbooks/inventory:/inventory "
            "ansible/ansible-runner "
            "run /playbooks/{{ dag_run.conf['playbook'] }}.yml "
            "-i /inventory/prod.ini "
            "--extra-vars '{{ dag_run.conf | tojson }}'"
        ),
    )

    verify_result = PythonOperator(
        task_id="verify_and_update",
        python_callable=check_result_and_update_gap,
    )

    fetch_gaps >> run_playbook >> verify_result
```

### 2.4 DAG 依赖关系总览

```mermaid
graph LR
    subgraph Daily["每日 8:00"]
        D1["pull_regulations_daily"]
        FCA["FCA API"] --> D1
        PRA["PRA API"] --> D1
        MAS["MAS API"] --> D1
        D1 --> REG["regulations 表"]
    end

    subgraph Weekly["每周一 9:00"]
        D2["compliance_check_weekly"]
        REG --> D2
        D2 --> PL["pipeline.run()"]
        PL --> RES["分析结果表"]
    end

    subgraph OnDemand["手动触发"]
        D3["ansible_remediate"]
        GAPS["gaps 表"] --> D3
        D3 --> AR["Ansible Runner"]
        AR --> SYS["目标系统"]
        SYS --> EVIDENCE["回写 evidence"]
    end
```

---

## 三、Ansible 集成设计

### 3.1 架构

```text
Airflow Scheduler
  │
  └── BashOperator: docker run ansible/ansible-runner ...
        │
        ├── playbooks/check_access_control.yml
        ├── playbooks/inventory/prod.ini
        └── --extra-vars '{gap_id, control_id, target_host}'

Ansible Runner 执行后:
  1. 在目标系统执行合规检查 playbook
  2. 捕获 stdout + rc
  3. POST 结果到 regintel API /api/internal/gaps/{id}/evidence
     (或直接写 PostgreSQL)
  4. Airflow verify_result task 读取结果, 更新 gap 状态
```

### 3.2 Playbook 示例

```yaml
# playbooks/check_access_control.yml
- name: Automated Access Control Compliance Check
  hosts: "{{ target_host | default('all') }}"
  vars:
    regintel_api: "http://regintel-app:8000"
  tasks:
    - name: Check privileged user list
      command: cat /etc/security/access.conf
      register: access_conf
      ignore_errors: yes

    - name: Verify MFA enforcement
      shell: grep -r "pam_google_authenticator" /etc/pam.d/ 2>/dev/null
      register: mfa_status
      ignore_errors: yes

    - name: Check sudoers file permissions
      stat:
        path: /etc/sudoers
      register: sudoers_stat

    - name: Report findings to RegIntel
      uri:
        url: "{{ regintel_api }}/api/internal/gaps/{{ gap_id }}/evidence"
        method: POST
        headers:
          Content-Type: application/json
        body_format: json
        body:
          playbook: check_access_control
          target: "{{ inventory_hostname }}"
          findings:
            access_conf_exists: "{{ access_conf.stat.exists | default(false) }}"
            mfa_enforced: "{{ mfa_status.rc == 0 }}"
            sudoers_perms: "{{ sudoers_stat.stat.mode | default('unknown') }}"
          timestamp: "{{ ansible_date_time.iso8601 }}"
        status_code: 200,201
```

### 3.3 Playbook 目录结构

```
playbooks/
├── inventory/
│   └── prod.ini               # 目标主机清单
├── check_access_control.yml   # 访问控制检查
├── check_data_protection.yml  # 数据保护检查
├── check_aml_kyc.yml          # AML/KYC 检查
└── shared/
    └── report_to_regintel.yml # 回写结果到 API (可被其他 playbook include)
```

---

## 四、Docker Compose 新增

```yaml
services:
  # ... 已有: regintel-app, postgres, redis, celery-worker ...

  airflow-db:                                           # ← 新增
    image: postgres:16
    environment:
      - POSTGRES_DB=airflow
      - POSTGRES_USER=airflow
      - POSTGRES_PASSWORD=airflow
    volumes:
      - airflow_db_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U airflow -d airflow"]
      interval: 5s
      timeout: 3s
      retries: 5
    restart: unless-stopped

  airflow-scheduler:                                    # ← 新增
    build:
      context: .
      dockerfile: Dockerfile.airflow
    command: >
      bash -c "
        airflow db init &&
        airflow scheduler
      "
    environment:
      - AIRFLOW__CORE__EXECUTOR=LocalExecutor
      - AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=postgresql+psycopg2://airflow:airflow@airflow-db:5432/airflow
      - AIRFLOW__CORE__LOAD_EXAMPLES=False
      - AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION=True
    volumes:
      - ./dags:/opt/airflow/dags
      - ./playbooks:/opt/airflow/playbooks
    depends_on:
      airflow-db:
        condition: service_healthy
      postgres:
        condition: service_healthy
    restart: unless-stopped

  airflow-webserver:                                    # ← 新增
    build:
      context: .
      dockerfile: Dockerfile.airflow
    command: airflow webserver
    ports:
      - "8080:8080"
    environment:
      - AIRFLOW__CORE__EXECUTOR=LocalExecutor
      - AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=postgresql+psycopg2://airflow:airflow@airflow-db:5432/airflow
      - AIRFLOW__CORE__LOAD_EXAMPLES=False
    volumes:
      - ./dags:/opt/airflow/dags
    depends_on:
      - airflow-scheduler
    restart: unless-stopped

volumes:
  # ... 已有 ...
  airflow_db_data:                                      # ← 新增
```

**Dockerfile.airflow：**

```dockerfile
FROM apache/airflow:2.10-slim
RUN pip install --no-cache-dir ansible-runner
USER airflow
```

---

## 五、目录结构变更

```
regintel/
├── app/
│   └── tasks.py              # 变更: +auto_pull_regulations() 占位任务
│
├── dags/                     # ← 新增: Airflow DAG 定义
│   ├── pull_regulations_daily.py
│   ├── compliance_check_weekly.py
│   ├── ansible_remediate.py
│   └── shared/
│       └── db_hooks.py       # 连接 regintel PostgreSQL 工具函数
│
├── playbooks/                # ← 新增: Ansible playbooks
│   ├── inventory/
│   │   └── prod.ini
│   ├── check_access_control.yml
│   ├── check_data_protection.yml
│   └── shared/
│       └── report_to_regintel.yml
│
├── Dockerfile.airflow        # ← 新增: Airflow 容器镜像
├── docker-compose.yml        # 变更: +airflow-db, +scheduler, +webserver
│
├── design/
│   ├── v3.1/
│   │   └── Detailed-Design.md  # 本文件
│   └── ...
```

**已有文件零改动清单：**

```
services/          ← 8 个服务文件不变
models/domain.py   ← 数据模型不变
app/routers/       ← API 路由不变
app/templates/     ← 前端模板不变
app/db/            ← 数据库层不变
data/              ← Mock 数据不变
```

Airflow 通过直接读写 `regulations` / `gaps` 等 PostgreSQL 表与现有系统耦合，不经过 FastAPI。

---

## 六、配置新增

```python
# app/config.py (新增, 被 dags/shared/db_hooks.py 引用)
AIRFLOW_SHARED_DB_URL: str = "postgresql://regintel:regintel@postgres:5432/regintel"
```

```toml
# pyproject.toml (Airflow 容器使用 Dockerfile.airflow, 不加入主依赖)
# 主 pyproject.toml 不变
```

---

## 七、服务依赖总图（v3.1 完整版）

```text
                                ┌──────────────────┐
                                │   External APIs   │
                                │  FCA / PRA / MAS  │
                                └────────┬─────────┘
                                         │ HTTP pull (Airflow)
                                         ▼
┌──────────────┐   ┌──────────┐   ┌──────────────┐
│ regintel-app  │   │  redis   │   │  airflow-sch │
│ (FastAPI)     │──▶│ (broker) │   │  eduler      │
└──────┬───────┘   └──────────┘   └──────┬───────┘
       │                                 │
       │  ┌──────────────┐   ┌──────────▼───────┐
       │  │ celery-worker│   │  airflow-websrv  │
       │  └──────────────┘   │  (:8080)         │
       │                     └──────────┬───────┘
       │                                │
       └──────────┬─────────────────────┘
                  │
       ┌──────────▼─────────────────────┐
       │         PostgreSQL              │
       │   - regintel 业务表 (共用)       │
       │   - airflow 元数据 (独立)        │
       └────────────────────────────────┘
                  │
       ┌──────────▼─────────────────────┐
       │      Ansible Runner            │
       │  (airflow BashOperator 触发)   │
       │  → SSH 到目标系统              │
       │  → 回写 evidence 到业务表      │
       └────────────────────────────────┘
```

---

## 八、后续探索方向（来自 ARCHITECTURE.md）

| 方向 | 涉及组件 | 说明 |
|------|----------|------|
| **外部监管源对接** | `dags/pull_regulations_daily.py` | 各监管源 API 认证不同, 需分别实现 `fetch_and_store()` |
| **Ansible playbook 扩展** | `playbooks/` | 需按实际合规领域补充更多 playbook |
| **合规证据回写协议** | regintel API `/api/internal/gaps/{id}/evidence` | 定义证据格式标准和 gap 状态映射 |
| **Airflow → Celery 桥接** | DAG2 调度管线 | 批量分析用 Airflow 自带 Worker 还是回调 Celery? |
| **DB 共享 vs 隔离** | Airflow 元数据 DB | 当前独立, 长期评估是否与业务 DB 共用 |
| **合规报告自动分发** | DAG 下游 | 邮件/Teams/Slack 推送 |
| **增量分析策略** | DAG1 dedup | 同一份文件被多次拉取时跳过已分析内容 |
| **Airflow RBAC 权限** | webserver | 多人协作时的界面权限控制 |
| **CI/CD 集成** | Ansible + CMDB | 合规修复 playbook 复用公司配置管线 |
| **性能基线** | 全链路 | 100/1000 条场景下的耗时和资源基线 |

---

## 九、v3 → v3.1 演进要点

| 维度 | v3 | v3.1 | 迁移影响 |
|------|-----|------|----------|
| 实时分析 | Celery | 同 v3 | **不变** |
| 定时调度 | 预留接口 | Airflow DAG | **新增** dags/, Dockerfile.airflow |
| 自动修复 | 不支持 | Ansible Runner | **新增** playbooks/ |
| 用户分析 | 同 v2/v3 | 同 v3 | **不变** |
| services/ | 同 v1 | 同 v1 | **零改动** |
| models/ | 同 v1 | 同 v1 | **零改动** |
| data/ | 同 v1 | 同 v1 | **零改动** |
| app/ | 同 v2 | 同 v2 | **仅 tasks.py 加 1 个占位任务** |

---

## 修订记录

| 版本 | 日期 | 变更说明 |
|------|------|----------|
| v3.1 | 2026-06-29 | Airflow + Ansible 详细设计: DAG/Playbook/Docker/目录 |
