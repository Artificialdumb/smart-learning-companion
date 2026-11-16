# 数据契约

JSON 和 JSONL 使用 UTF-8。编号为字符串，分数和计数为整数，无法计算的得分率为 `null`。批次内业务编号唯一，跨批次按 `run_id` 限定。HTTP 成功响应带 `run_id`，导出目录内的目录表、名册和作答共用该目录的 `manifest.json`。

## 输入、诊断与比较

| 文件 | 定位字段 | 内容 |
|---|---|---|
| `manifest.json` | `run_id` | `schema_version`、`rules_version`、`source_files` 和 `built_at`。源文件含路径和 SHA-256。构建增加 `input_run_id`、`recommendation_rules_version`、`recommendation_mode`，导出增加 `exported_at` 和 `adjustment_versions`。 |
| `catalog.json` | 各集合业务编号 | `topics`、`indicators`、`items`、`resources`、`nodes`、`learning_relations`。指标有 `topic_id`、`description` 和材料引用。题目有 `indicator_ids`、题干、题型、选项、满分和评分点。材料有类型、标题、适用指标和资料定位。节点以 `item_ids` 规定测验范围。 |
| `students.json` | `student_id` | 完整名册。包含 `class_id` 和可用的年级。 |
| `responses.jsonl` | `record_id` | 最新作答。含事件号、修订版本、学生、节点、题目、`scoring_status`、`validation_status`、总得分、满分、最终作答、步骤和评分点得分。冲突的最高修订可留多条记录供复核。 |
| `quality_report.json` | `run_id` | 原始行数、事件数、最新评分状态计数、有效记录数和问题明细。A 的报告还含 `response_source_sha256`、`reviews` 和 `unresolved_review_count`。输入只含最新作答时，缺少的原始行数和问题明细为 `null`。 |
| `learning_requirements.json` | `run_id` | 主题、指标和学习内容间的关系。 |
| `diagnosis.json` | `student_id + node_id` | 个人指标覆盖、有效得分、证据状态和诊断发现。发现中的证据按 `record_id`、评分点编号和从 1 起算的步骤编号回查。 |
| `class_comparison.json` | `node_id` | 同节点两班共同题、覆盖人数、名册分母、有效作答数、得分分子分母和共性失分证据。 |

作答评分状态分为 `graded`（已评分）、`pending`（待评分）、`unanswered`（未作答）。校验状态为 `valid` 或 `needs_review`。分析使用最新且 `graded + valid` 的作答，零分照常计入。指标状态分为 `supported`（有作答证据）、`insufficient`（已测但证据不足）、`not_assessed`（本节点未测）。个人覆盖和班级得分计算见 [integration.md](integration.md)。

A 生成的目录引用含可直接展示的 `locator`。已核实版本的课标引用另含 `section`、`clauses`，教材引用另含 `section`、`pdf_pages` 和 `printed_page_range`。PDF 页码从 1 开始，区间包含两端。学习关系的 `references` 指向支撑关系的指标与同一目录资源。

## 学习计划

`recommendations.json` 按 `run_id + student_id + node_id` 定位，包含 `plan_id`、`original_activities`、`effective_activities`、`adjustment_version` 和空计划说明 `empty_reason`。`cases.json` 按活动类型选取可用案例，带诊断、此次导出的有效活动和调整版本。

| 活动字段 | 含义 |
|---|---|
| `recommendation_id` | 计划内的活动编号。教师调整沿用该编号。 |
| `indicator_id`、`kind` | 活动对应指标和需求类型。类型为 `practice_needed`、`strength` 或 `observe_more`。 |
| `finding_ids`、`evidence_record_ids` | 同批诊断发现和对应作答编号。补充观察的作答编号可为空。 |
| `resource_id` | 该指标的题目、学习卡或教材。题目须在该节点范围内。 |
| `sequence`、`reason` | 从 1 开始连续的顺序，以及选择材料的理由。 |
| `hints`、`recheck_condition` | 按顺序展示的分步提示和完成后可复查的条件。 |

调整按整份计划提交，带 `expected_version` 和每个活动的 `recommendation_id`、`resource_id`、`sequence`、`hints`、`recheck_condition`。版本初始为 0，成功写入后加一。原始活动随批次保留。

## HTTP

除 `GET /api/context` 外，以下请求提供 `?run_id=<编号>`。个人诊断、个人建议和班级对比另外提供 `node_id`。

| 方法 | 路径 |
|---|---|
| GET | `/api/context`、`/api/catalog` |
| GET | `/api/students/{student_id}/diagnosis` |
| GET | `/api/students/{student_id}/recommendations` |
| GET | `/api/classes/compare` |
| GET | `/api/records/{record_id}` |
| GET | `/api/resources/{resource_id}` |
| PUT | `/api/plans/{plan_id}/teacher-adjustment` |

错误格式为 `{"error":{"code":"…","message":"…","details":{}}}`，`details` 可省。404 表示未找到数据，409 表示调整版本过期，422 表示参数或调整内容不合规，503 表示当前没有可访问批次。学生练习资源接口按字段白名单返回内容，参考答案和解析留在批次输入中。
