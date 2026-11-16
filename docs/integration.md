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

## C 模块联调

安装方式见 [README](../README.md)。在仓库根目录执行下列命令。构建命令打印新批次编号。

```sh
python -m app.cli build --source fixtures/synthetic
python -m app.cli build --source data/赛题资料包
python -m uvicorn app.web.main:app --host 127.0.0.1 --port 8000
python -m app.cli export --run-id <批次编号> --out outputs/成果包
```

- `build --source` 接收赛题资料包根目录或标准化批次目录。原始 CSV 走 A 的课程目录与导入校验。标准化目录含 `manifest.json`、`catalog.json`、`students.json`、`responses.jsonl`，可附 `quality_report.json`。用 `python -m app.a_pipeline --source data/赛题资料包 --out outputs/a_snapshots` 可以独立生成标准化快照，后续构建时传入命令打印的批次路径。`tools.prepare_fixture` 是早期开发适配入口。
- 如用非默认 SQLite 文件，构建和导出传 `--db <路径>`，启动网页时设置 `STUDY_DB=<相同路径>`。默认文件为 `outputs/study.sqlite3`。
- 构建生成新批次号，成功提交后才切换当前批次。已打开的页面按初始化时的批次查询和保存。导出读取所选批次及其同一时刻的教师调整，输出目录使用新路径。
- 规则按指标定位本次具体失分优先给巩固建议。至少两条独立满分作答才给变式练习。已测且无有效证据时安排补充观察，未测指标不生成活动。题目优先从同节点、同指标、该学生未作答的材料中选。教师可用同范围内的其他题目或映射到该指标的学习卡、教材替换。
- 默认离线。可选设置 `STUDY_MODEL` 为本地 OpenAI 兼容模型名，`STUDY_MODEL_PORT` 默认 11434，服务需要凭据时设置 `STUDY_MODEL_KEY`。构建只向回环地址发送活动类别、指标编号和候选材料编号。模型可从已校验的候选中选择，异常或无效结果使用规则首选。提示和复查条件由模板提供。
- 运行于本地演示环境。资源和作答按赛题使用范围保存在本地。提交前按赛题要求核对成果包中的记录及引用材料范围。

### 复核原始作答

在本地 `data/` 保存 UTF-8 复核 JSON。`source_sha256` 填首次构建生成的 `quality_report.json` 中的 `response_source_sha256`。每条 `decisions` 对应一条需复核的最新记录，填写 `record_id`、整数 `revision`、`action` 和 `reason`。确认排除用 `exclude`。确认更正用 `correct`，并在 `changes` 填入原 CSV 字段名及字符串值。可改字段为 `主题编号`、`评分状态`、`得分`、`满分`、`评分点得分`。学生、节点、题目或事件归属冲突应在来源数据核实后重导。复核文件和原始作答的摘要必须匹配。

```sh
python -m app.cli build --source data/赛题资料包 --reviews data/复核决定.json
```

更正后的记录重新校验。质量报告保留原异常、更正前后的值和复核理由。复核失败时构建报错，成功时发布新批次。也可向 `app.a_pipeline` 传同一 `--reviews` 参数生成 A 的独立快照。

### 演示复核

1. 选择 D01、N01，在个人页打开 `DR0001` 检查第 2 步、最终作答和 `Q015P3`，打开计划中的 Q016。打开教师调整，改提示或顺序，保存后刷新检查版本和有效活动。合成批次可以用 S01、NX、X-R01 走同一流程。
2. 切到 D14、N02 查看指标 T03I2 的变式 Q053。再看 D17，分别核对 N01 的一元一次方程补充观察、N01 未测的不等式指标和 N02 的不等式补充观察。
3. 打开班级对比，检查两个班的共同题、覆盖分母和得分分母。打开课程材料，按指标查看配套题目和出处。导出此批次，核对 `cases.json`、`recommendations.json` 中的证据和调整版本与页面一致。
