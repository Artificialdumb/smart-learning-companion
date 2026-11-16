# 模块接入与统计口径

批次入口接收 A 提供的目录、完整名册和同批作答视图。两个模块均可独立调用，C 的批次入口统一补 `run_id` 后存储或序列化。

```python
from app.diagnosis import diagnose_students
from app.class_analysis import compare_classes

diagnoses = diagnose_students(catalog, students, latest_responses, usable_responses)
comparisons = compare_classes(catalog, students, usable_responses)

student_report = {"run_id": run_id, **diagnoses[student_id][node_id]}
class_report = {"run_id": run_id, **comparisons[node_id]}
```

- 输入为 JSON 反序列化后的字典记录。目录、名册和评分点集合可传记录列表或按业务编号索引的字典，作答可传字典记录的可迭代对象。名册含全体学生，班级比较要求两个班。目录须含 `indicators`、`items`、`nodes` 及其题目映射。
- `latest_responses` 保留原评分状态与校验状态，复核冲突可留下多条关联记录。 `usable_responses` 为 A 提供的最新且 `graded + valid` 的视图，须包含总分、目录满分及评分点成绩。B 检查学生、节点、题号、分数范围、评分点和记录唯一性，避免同一学生在同节点同题重复计分。
- 作答引用按同批 `record_id` 回查。样例的 `responses.jsonl` 保存最新版本，交接时由 A/C 按 `run_id + record_id` 提供详情。记录中的 `revision` 可用于验证证据版本。
- 函数内存返回分别按 `student_id → node_id` 和 `node_id` 索引。导出文件均为 JSON 数组，每个顶层对象带 `run_id`。字段的示例值可用 [合成输入](../fixtures/synthetic/) 生成。

## 个人诊断字段

| 字段 | 计算或含义 |
|---|---|
| `eligible_item_ids`、`eligible_item_count` | 节点题库中映射到此指标的不同题号及题数。范围表示题目可以出现在节点中。 |
| `valid_count`、`pending_count`、`unanswered_count`、`review_count`、`missing_record_count` | 每个范围内题号占且只占一项。以最新版本判断，待复核优先。节点之外的异常题保留在质量报告。五项合计等于可用题数。 |
| `score_sum`、`max_score_sum`、`score_rate` | 只汇总有效记录。有效零分正常计入。无有效记录时两个合计为 0、得分率为 `null`。 |
| `evidence_status` | `supported` 有至少一条有效作答，可以描述已观察到的表现。 `insufficient` 已测但无有效作答。 `not_assessed` 节点题库未覆盖。 |
| `findings` | `strength` 描述已完成的题或得分评分点，`practice_needed` 标出本次作答的失分和依据，`observe_more` 说明证据不足及缺证据分类。 |
| `finding_id`、`evidence` | 发现编号在批次内可定位。证据项含 `record_id`、`rubric_point_ids`，步骤如已定位则带 `step_numbers`，按 `steps` 数组从 1 编号。补充观察证据为空。 |

一条有效作答可以支持描述该题的实际过程、得分或失分。汇总可以并列列出多次表现及各自证据。关于反复出现的问题，需要多个不同作答事件，本版在个人结果中逐题列举失分。通用评分点如“答案正确”只能定位本题表现。只有末行化简结果与参考结果一致、前序评分点全得、结果评分点失分、最终表达式逐项仅符号不同的简单情况，才自动定位末行与最终填答的差异。其他失分以评分点为证据。

## 班级对比字段

| 字段 | 计算或含义 |
|---|---|
| `comparison_item_ids` | 各指标共同有效题号的去重并集。 |
| `eligible_item_ids`、`item_ids` | 指标可用题；其中两班各至少有一条有效作答的题进入 `item_ids`。 |
| `comparison_status` | `comparable` 有共同题，`no_common_items` 已测但无共同题，`not_assessed` 未测。 |
| `class_size`、`covered_students`、`coverage_rate` | 名册人数、共同比较范围内有效作答的学生去重数、两者比值（覆盖人数除以班级人数）。 |
| `valid_count`、`score_sum`、`max_score_sum`、`score_rate` | 共同题范围的有效作答数、总得分、相应满分、两者比值（总得分除以相应满分）。无共同题时前三项为 0，得分率为 `null`。 |
| `findings` | `observed_difference` 给出同范围内有差异的分数与覆盖。 `common_miss` 要求同班同题同一评分点至少 2 名学生失分，提供 `class_id`、`item_id`、`rubric_point_id`、`missed_students`、`scored_students`、`record_ids`。 `not_comparable` 说明无比较范围的原因。 |

同题可映射多个指标，对应指标可重复引用该题。计算主题或节点汇总时按作答事件去重，使用题号并集回筛记录。分数比较为观察到的同节点结果，共同题中的作答人数可因题、因班变化。跨节点若要判断变化，需要为同题或明确可比题组另做统计。
