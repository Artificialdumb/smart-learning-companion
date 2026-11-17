# 数据契约

JSON 和 JSONL 使用 UTF-8。编号为字符串，分数和计数为整数，无法计算的得分率为 `null`。批次内业务编号唯一，跨批次按 `run_id` 限定。HTTP 成功响应带 `run_id`，导出目录内的目录表、名册和作答共用该目录的 `manifest.json`。

## 输入、诊断与比较

| 文件 | 定位字段 | 内容 |
|---|---|---|
| `manifest.json` | `run_id` | `schema_version`、`rules_version`、`source_files` 和 `built_at`。源文件含路径和 SHA-256。构建增加 `input_run_id`、`recommendation_rules_version`、`recommendation_mode`，导出增加 `exported_at` 和 `adjustment_versions`。 |
| `catalog.json` | 各集合业务编号 | `topics`、`indicators`、`items`、`resources`、`nodes`、`learning_relations`。指标有 `topic_id`、`description` 和材料引用。题目有 `indicator_ids`、题干、题型、选项、满分和评分点。材料有类型、标题、适用指标和资料定位。节点以 `item_ids` 规定测验范围。 |
| `students.json` | `student_id` | 完整名册。包含 `class_id` 和可用的年级。 |
| `responses.jsonl` | `record_id` | 最新作答。含事件号、修订版本、学生、节点、题目、`scoring_status`、`validation_status`、总得分、满分、最终作答、步骤和评分点得分。冲突的最高修订可留多条记录供复核。 |
| `usable_responses.jsonl`（A 快照可选） | `record_id` | `responses.jsonl` 中 `graded + valid` 的完整记录子集。提供此文件时，统一构建与 B 独立构建均核对记录编号与内容。 |
| `quality_report.json` | `run_id` | 原始行数、事件数、最新评分状态计数、有效记录数和问题明细。A 的报告还含 `response_source_sha256`、`reviews` 和 `unresolved_review_count`。输入只含最新作答时，缺少的原始行数和问题明细为 `null`。 |
| `learning_requirements.json` | `run_id` | 主题、指标和学习内容间的关系。 |
| `diagnosis.json` | `student_id + node_id` | 个人指标覆盖、有效得分、证据状态和诊断发现。发现中的证据按 `record_id`、评分点编号和从 1 起算的步骤编号回查。 |
| `class_comparison.json` | `node_id` | 同节点两班共同题、覆盖人数、名册分母、有效作答数、得分分子分母和共性失分证据。 |

作答评分状态分为 `graded`（已评分）、`pending`（待评分）、`unanswered`（未作答）。校验状态为 `valid` 或 `needs_review`。分析使用最新且 `graded + valid` 的作答，零分照常计入。指标状态分为 `supported`（有作答证据）、`insufficient`（已测但证据不足）、`not_assessed`（本节点未测）。个人覆盖和班级得分计算见 [integration.md](integration.md)。

题目满分和各评分点满分须为正整数，评分点满分之和须等于题目满分。作答修订须为正整数，`steps` 须为字符串数组，无步骤时用 `[]`。有效作答的事件编号须对应学生、节点与题目，已隔离的待复核记录可保留原始身份或评分异常。

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

共享模式使用 HTTP Basic 认证。凭据错误或缺失返回 401，当前账号没有相应权限时返回 403。例外：`GET /api/records/{record_id}` 对无权访问的记录与不存在的记录一律返回 404 `record_not_found`，避免借此探测记录编号。`GET /api/context` 只列出可访问学生，并返回 `can_compare` 和 `can_adjust`，供网页决定是否显示班级对比与教师调整入口。实际权限由服务端在读写时检查。

| 方法 | 路径 |
|---|---|
| GET | `/api/context`、`/api/catalog` |
| GET | `/api/students/{student_id}/diagnosis` |
| GET | `/api/students/{student_id}/recommendations` |
| GET | `/api/classes/compare` |
| GET | `/api/records/{record_id}` |
| GET | `/api/resources/{resource_id}` |
| PUT | `/api/plans/{plan_id}/teacher-adjustment` |
| GET | `/api/students/{student_id}/learning-paths` |
| GET / PUT | `/api/students/{student_id}/followups/{indicator_id}` |

错误格式为 `{"error":{"code":"…","message":"…","details":{}}}`，`details` 可省。404 表示未找到数据，409 表示调整版本过期，422 表示参数或调整内容不合规，503 表示当前没有可访问批次。教材详情可含 `indicator_locations`，按指标编号列出小节、PDF 页码区间、印刷页码区间和显示定位。学生练习资源接口按字段白名单返回内容，参考答案和解析留在批次输入中。

## 错因追问

追问 GET / PUT 均需要 `run_id` 和 `node_id`。GET 返回 `student_id`、`node_id`、`indicator_id`、`probe_version`、保存版本 `version`、原诊断 `finding_ids`、`evidence`、`questions`、`result` 和 `unavailable_reason`。无有效失分证据或未覆盖的指标返回空问题与原因，不因缺少数据判为薄弱。

每个问题包含 `question_id`、`dimension`（`concept`、`calculation`、`reading`）、`prompt` 和 `options`。选项含 `option_id` 与 `text`，另可提交 `unsure` 表示不确定。未提交的问题不返回答案或解释。提交格式如下，题号与版本须取自 GET：

```json
{
  "expected_version": 0,
  "probe_version": "screening-1.0",
  "answers": {
    "expressions-concept": "1",
    "expressions-calculation": "unsure",
    "expressions-reading": "1"
  }
}
```

须一次提交当前题组的全部 3 题。错误题号、选项、字段或不完整作答返回 422；保存版本冲突及题组版本冲突返回 409。成功后版本加一。数据库按 `run_id + student_id + node_id + indicator_id` 保存最近一次结果，重新提交替换该指标此前的补充记录。保存不会修改原始作答、得分、诊断或学习计划。

`result` 包含题组版本、提交时间、原失分证据和逐题 `checks`（题干、选项、所选 `selected_option_id`、答案、解释及 `outcome`），以及 `suspected_causes`、`uncertain_dimensions`、`conclusion`、`limitation`。`outcome` 为 `pass`、`gap` 或 `uncertain`。单个维度仅一个问题，错误表示该维度需要进一步核查，不能单独归因为原题的概念混淆、计算失误或审题偏差。全部正确也不据此认定原题是粗心。重复同一题组不用于衡量提升。

导出 `followups.json` 保存每个已提交指标的最近一次补充记录，包含其作答时的完整题干与反馈，便于追溯。构建清单增加 `followup_probe_version`，每次提交同时保存实际使用的版本。原有 SQLite 数据库首次连接时自动新增独立表，保留原批次及教师调整。

## 前置知识补学路径

`learning-paths` 请求同样需要 `run_id` 和 `node_id`。返回 `student_id`、`node_id`、`paths` 与 `empty_reason`，导出文件为 `learning_paths.json`。只针对有有效失分证据的目标指标生成路径。路径含 `target_indicator_id`、`steps`、`relations`、`priority_check_ids` 和说明 `note`。

只使用 `learning_relations` 中 `relation_type=prerequisite` 的边，方向为前置指标 → 后续指标；`transfer` 不作为前置条件。路径按拓扑顺序展开全部前置指标并去重，末尾返回目标指标。构建拒绝前置自环、循环及未知指标。无前置关系时仅返回当前目标，并注明目录缺少关系。

步骤字段包括 `indicator_id`、`action`（`practice` 补学、`check` 补充观察、`continue` 已有表现可继续）、`evidence_status`、`evidence_node_id`、`historical`、`finding_ids`、`evidence`、`resource_ids` 和 `practice_item_ids`。材料来自相应指标的学习卡、教材，最多列出两道当前节点范围内的练习题。缺少材料时由教师补充，不虚构资源。

优先使用当前节点证据。仅在当前指标 `not_assessed` 时，按 `assessment_date` 倒序寻找严格早于当前日期、已测的历史节点；当前 `insufficient` 不以旧得分覆盖，未来或同日其他节点不回填。历史依据显式标记并提示复查。`priority_check_ids` 列出有失分或缺少证据的前置指标，不宣称它们就是本次错误的原因。补学路径和原学习计划分别展示，教师已有调整不受影响。

导出包重建只复算初始诊断与路径，不恢复教师调整或追问记录；两类交互结果均保留在各自的导出快照中。
