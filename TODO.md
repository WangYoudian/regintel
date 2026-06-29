# RegIntel AI — Production Readiness TODO

> 当前进度：v1 原型可本地运行。
> embedding 默认使用 scikit-learn TF-IDF（无需 PyTorch），如需更好的语义质量可切换到 sentence-transformers 或内部 LLM API。

---

## 🔴 P0 — 阻塞项（上线前必须完成）

- [ ] **切换到内部 LLM API 做 embedding**（当前：TF-IDF fallback，效果够用但不如语义模型）
  - [ ] 确认内部 LLM API 是否提供 `/v1/embeddings` 端点
  - [ ] 有 → `config.py` 追加 `EMBEDDING_METHOD=api`，`embedding_service.py` 自动切换
  - [ ] 没有 → 安装 sentence-transformers：`uv sync --extra sbert`，`config.py` 设 `EMBEDDING_METHOD=sbert`
  - [ ] `sentence-transformers` 始终保持 optional（`pyproject.toml` 的 `[sbert]` extra）

- [ ] **确认 LLM 结构化输出支持**
  - [ ] 内部 API 是否支持 `response_format={"type": "json_object"}` 或 function calling
  - [ ] 不支持 → 修改 `services/llm_client.py`：改为 prompt 约束 + Pydantic 后解析
  - [ ] 不支持 → `config.py` 追加 `LLM_JSON_MODE: bool`

- [ ] **配置生效**
  - [ ] 确认 `config.py` 中 `LLM_API_ENDPOINT` / `LLM_API_KEY` 指向正确的内部 API
  - [ ] 端到端测试：上传样本 → 提取义务 → 匹配 → 分析 → 建议

---

## 🟡 P1 — 重要项

- [ ] **单元测试覆盖核心管线**
  - [ ] `test_document_parser.py`
  - [ ] `test_embedding_service.py`
  - [ ] `test_matcher.py`
  - [ ] `test_pipeline.py`

- [ ] **Mock 数据验证**
  - [ ] 26 条内控是否覆盖所有 Demo 场景
  - [ ] 样本监管文件是否覆盖三种状态（covered / partial / missing）

- [ ] **Streamlit 前端联调**
  - [ ] 侧边栏交互流
  - [ ] 处理中状态提示
  - [ ] 错误状态兜底 UI

---

## 🟢 P2 — 打磨项

- [ ] **gap_analyzer 传入真实义务文本**
  - 当前 `_generate_gap()` 中的 `ob_text` 是 obligation_id，需改为实际 description
  - 在 `pipline.py` 的 `run()` 中构建 `ob_text_map` 传入

- [ ] **pyproject.toml 清理**
  - `sentence-transformers` 始终为 optional extra
  - `scikit-learn` 保持为核心依赖

- [ ] **异常处理加固**
  - `llm_client.py`：超时回退
  - `compliance_extractor.py`：LLM 返回空时的兜底
  - `matcher.py`：embedding 为空时的处理（已处理 ✅）

- [ ] **README.md 中的配置说明**
  - 补充内部 API 的配置示例

---

## 版本映射

| 版本 | 对应 TODO |
|------|-----------|
| **v1 ✅** | 全部 P0-P2 — embedding 已用 TF-IDF 解决，无需 PyTorch |
| v2 | P0 + DB 层配置 (`DATABASE_URL`) |
| v3 | P0 + Redis 配置 (`REDIS_URL`) |
| v3.1 | P0 + Airflow 连接配置 |
