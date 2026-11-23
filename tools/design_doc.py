"""Generate the design-proposal PDF (≤ 20 pages) from a stored batch.

Every number in the document comes from the batch, the test run or the calibration
simulation performed during generation, so the PDF can be rebuilt for the contest
batch with one command:

  python -m tools.design_doc --db outputs/study.sqlite3 --run-id <id> \\
      --data-label 赛题模拟学情数据 --out outputs/智慧学伴-设计方案.pdf

Requires the optional ``docs`` extra (PyMuPDF).
"""

import argparse
import html
import io
import unittest
from datetime import date
from pathlib import Path

import fitz

from app._analysis import index
from app.cli import case_examples
from app.diagnosis.followup import followup_view
from app.diagnosis.paths import learning_paths
from app.rules import batch_rules
from app.storage import Store
from tools.mastery_calibration import simulate

ROOT = Path(__file__).resolve().parents[1]
MAX_PAGES = 20
KIND = {"practice_needed": "针对性巩固", "strength": "变式练习", "observe_more": "补充观察"}
FINDING = {"practice_needed": "失分", "strength": "已有表现", "observe_more": "证据不足"}
LEVEL = {"mastered": "已掌握", "developing": "正在形成", "needs_support": "需要支持",
         "insufficient_evidence": "证据不足"}
STATUS = {"supported": "有作答证据", "insufficient": "已测·证据不足", "not_assessed": "该节点未测"}

CSS = """
@font-face { font-family: cjk; src: url(cjk.ttf); }
body { font-family: cjk; font-size: 10pt; line-height: 1.45; color: #1d2733; }
h1 { font-size: 20pt; margin: 0 0 6pt 0; }
h2 { font-size: 14pt; margin: 14pt 0 4pt 0; color: #0d4f8b; }
h3 { font-size: 11.5pt; margin: 9pt 0 3pt 0; }
p { margin: 3pt 0; }
li { margin: 1pt 0; }
table { margin: 4pt 0; }
td, th { border: 0.5pt solid #9aa7b4; padding: 2pt 4pt; font-size: 9pt; vertical-align: top; }
th { background-color: #e8eef4; }
.note { color: #5b6773; font-size: 9pt; }
.box { border: 0.5pt solid #c9a227; background-color: #fff8e1; padding: 4pt; margin: 6pt 0; }
code { font-family: cjk; font-size: 9pt; color: #6b3fa0; }
"""


def esc(value):
    return html.escape(str(value))


def table(headers, rows):
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table><tr>{head}</tr>{body}</table>"


def pct(value):
    return "—" if value is None else f"{value:.0%}"


def run_tests():
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    return result.testsRun, len(result.failures) + len(result.errors), len(result.skipped)


def section_cases(batch, plans):
    items = index(batch["catalog"]["items"], "item_id")
    indicators = index(batch["catalog"]["indicators"], "indicator_id")
    chosen = case_examples(batch["diagnoses"], plans, batch_rules(batch))
    found = {case["kind"] for case in chosen}
    parts = [] if len(chosen) == 3 else [
        "<div class='box'>本批次只找到 " + str(len(chosen)) + " 类代表案例，缺少："
        + "、".join(KIND[k] for k in KIND if k not in found)
        + "（该类活动在本批次不存在，例如没有学生有两次独立满分作答）。</div>"]
    for number, case in enumerate(chosen, 1):
        summary, activity = case["diagnosis"], case["activity"]
        indicator = indicators[summary["indicator_id"]]["description"]
        mastery = summary.get("mastery") or {}
        parts.append(f"<h3>案例 {number}：学生 {esc(case['student_id'])} · 测验 {esc(case['node_id'])} · "
                     f"{esc(indicator)}（{KIND[case['kind']]}）</h3>")
        parts.append(f"<p>覆盖：有效 {summary['valid_count']}/{summary['eligible_item_count']} 题，"
                     f"得分 {summary['score_sum']}/{summary['max_score_sum']}（{pct(summary['score_rate'])}），"
                     f"证据状态 {STATUS[summary['evidence_status']]}；得分比例指数 "
                     f"{pct(mastery.get('estimate'))}，{LEVEL.get(mastery.get('level'), '—')}"
                     f"（{mastery.get('evidence_count', 0)} 条有效作答）。</p>")
        for finding in summary["findings"]:
            cites = []
            for evidence in finding["evidence"]:
                record = batch["records"].get(evidence["record_id"], {})
                steps = record.get("steps") or []
                step_text = "；".join(f"第 {n} 步「{esc(steps[n - 1])}」"
                                     for n in evidence.get("step_numbers", []) if n <= len(steps))
                cites.append(f"{esc(evidence['record_id'])}（题目 {esc(record.get('item_id', ''))}「"
                             f"{esc(items.get(record.get('item_id'), {}).get('prompt', ''))}」，最终作答「"
                             f"{esc(record.get('final_answer', ''))}」，评分点 "
                             f"{esc('、'.join(evidence['rubric_point_ids']) or '—')}"
                             + (f"，{step_text}" if step_text else "") + "）")
            parts.append(f"<p>发现（{FINDING[finding['kind']]}）：{esc(finding['summary'])}</p>")
            if cites:
                parts.append("<p class='note'>证据：" + "；".join(cites) + "</p>")
        parts.append(f"<p>建议活动：{esc(activity['reason'])} 提示："
                     + "；".join(esc(h) for h in activity["hints"])
                     + f"。复查条件：{esc(activity['recheck_condition'])}</p>")
        if case["kind"] == "practice_needed":
            view = followup_view(batch, case["student_id"], case["node_id"], summary["indicator_id"])
            if view["questions"]:
                parts.append("<p>错因追问：" + "；".join(
                    f"{esc(q['dimension_label'])}{'（关联失分点）' if q['focus'] else ''}：{esc(q['prompt'])}"
                    for q in view["questions"]) + "</p>")
            path = next((p for p in learning_paths(batch["catalog"], batch["diagnoses"][case["student_id"]],
                                                   case["node_id"])["paths"]
                         if p["target_indicator_id"] == summary["indicator_id"]), None)
            if path:
                parts.append("<p>补学路径：" + " → ".join(
                    esc(indicators[s["indicator_id"]]["description"]) for s in path["steps"])
                    + f"。{esc(path['note'] or '')}</p>")
    return "".join(parts) or "<p>本批次没有可作为案例的学习活动。</p>"


def section_classes(batch):
    indicators = index(batch["catalog"]["indicators"], "indicator_id")
    parts = []
    for node_id, report in sorted(batch["comparisons"].items()):
        parts.append(f"<h3>测验 {esc(node_id)}：共同有效题 {len(report['comparison_item_ids'])} 道"
                     f"（{esc('、'.join(report['comparison_item_ids']) or '无')}）</h3>")
        rows = []
        for row in report["indicators"]:
            name = esc(indicators[row["indicator_id"]]["description"])
            if row["comparison_status"] != "comparable":
                status = {"no_common_items": "无共同题，不可比较", "not_assessed": "该节点未测"}[row["comparison_status"]]
                rows.append([name, status, "", "", "", ""])
                continue
            for cls in row["classes"]:
                rows.append([name, esc(cls["class_id"]), f"{cls['covered_students']}/{cls['class_size']}",
                             str(cls["valid_count"]), f"{cls['score_sum']}/{cls['max_score_sum']}",
                             pct(cls["score_rate"])])
                name = ""
        parts.append(table(["指标", "班级", "覆盖人数/名册", "有效作答", "得分/满分", "得分率"], rows))
        commons = [f for row in report["indicators"] for f in row["findings"] if f["kind"] == "common_miss"]
        if commons:
            parts.append("<p>共性失分（同班同题同一评分点 ≥ 2 人）：" + "；".join(
                f"{esc(f['class_id'])} 班 {esc(f['item_id'])} 的 {esc(f['rubric_point_id'])}，"
                f"{len(f['missed_students'])} 人失分" for f in commons) + "</p>")
    return "".join(parts)


def build_html(batch, plans, data_label, tests, calibration):
    manifest, quality = batch["manifest"], batch["quality_report"]
    rules = batch_rules(batch)
    counts = quality.get("latest_scoring_status_counts", {})
    tests_run, failed, skipped = tests
    calib_rows = [[str(r), str(p), f"{a[0]:.1%} / {a[1]:.2f}", f"{b[0]:.1%} / {b[1]:.2f}"]
                  for (r, p), (a, b) in calibration]
    sources = manifest.get("upstream_source_files") or manifest.get("source_files") or []
    return f"""
<h1>智慧学伴 · 设计方案</h1>
<p>七年级数学学情诊断、班级对比与学习建议系统</p>
<p class="note">生成日期 {date.today().isoformat()} ｜ 数据：{esc(data_label)} ｜ 批次 {esc(manifest['run_id'])} ｜
规则摘要 {esc(manifest.get('rules_sha256', '')[:16])} ｜ 追问题组 {esc(manifest.get('followup_probe_version', ''))}</p>
<div class="box">本文所有统计、案例和班级数据均由上述批次自动生成；测验结果与模拟数字在生成本文时实际运行得到。
使用合成数据生成的版本只用于检查版式和流程，正式提交须用赛题批次重新生成（命令见第 8 节）。</div>

<h2>1 问题与边界</h2>
<p>测验后教师通常只看到总分，难以回答：学生具体错在哪一题、哪个评分点、哪一步；两个班的差异在题目和交卷人数都不同时是否可比；下一步练什么、能否落到课标、教材和具体材料。原始作答还存在多次修订、待评分、分数越界、评分点合计不一致、重复记录等问题。</p>
<p><b>做：</b>赛题给定的七年级代数三个主题、九个观察指标；数据接入与质量控制、个人证据诊断、得分比例指数、两班共同题对比、学习建议与教师调整、错因追问与补学路径、成果包导出。
<b>不做：</b>自动判分；跨学科通用诊断；用大模型生成诊断结论或提示（可选的本地模型只能在规则校验过的候选材料中挑选）；把追问结果或教师评价当作诊断准确率、教学效果的证明。</p>

<h2>2 数据与质量控制</h2>
<p>原始 CSV 与标准化输入经过同一套目录校验：题目必须映射到已知指标且不重复、主题一致、评分点合计等于满分；测验节点题目非空且存在；出处与学习关系可定位。任何一项不通过，构建失败，当前批次保持不变。</p>
{table(["项目", "数值"], [
    ["原始行数", esc(quality.get("raw_rows") if quality.get("raw_rows") is not None else "标准化输入未提供")],
    ["作答事件数", esc(quality.get("event_count"))],
    ["最新版本评分状态", esc("，".join(f"{k} {v}" for k, v in counts.items()))],
    ["进入分析的有效作答", esc(quality.get("usable_count"))],
    ["质量问题条目", esc(len(quality["issues"]) if quality.get("issues") is not None else "标准化输入未提供")],
])}
<p class="note">每个作答事件只取最新修订；冲突的最高修订进入人工复核，不静默丢弃。复核决定与原始作答摘要绑定，质量报告保留更正前后的值与理由。</p>

<h2>3 方法</h2>
<h3>3.1 证据化诊断</h3>
<p>以评分点为最小证据单位。失分评分点生成“针对性巩固”发现，得分评分点生成“已有表现”，已测但无有效作答生成“补充观察”。简单整式题中，若只差结果评分点、过程末行与参考答案一致而最终填写仅符号不同，自动定位到出错步骤。每条发现带作答记录编号、评分点编号和步骤号，可在网页逐条回查。</p>
<h3>3.2 得分比例指数（掌握度）</h3>
<p>每条有效作答按得分比例记一次证据，以 Beta({rules['mastery']['prior'][0]},{rules['mastery']['prior'][1]}) 先验平滑，累计本测验及更早测验，给出均值和 {rules['mastery']['interval_level']:.0%} 区间。有效作答少于 {rules['mastery']['min_evidence']} 条为“证据不足”；区间下限 ≥ {rules['mastery']['mastered_lower']} 为“已掌握”；均值 ≥ {rules['mastery']['developing_mean']} 为“正在形成”。<b>该指数描述得分比例，未经外部标准校准，不是掌握概率。</b>证据单位的选择见 6.2。</p>
<h3>3.3 两班对比</h3>
<p>只在两个班都有有效作答的共同题上比较，并同时给出覆盖人数和得分两个分母；同班同题同一评分点至少 2 人失分才列为共性问题；没有共同题时明确标注不可比较。</p>
<h3>3.4 学习建议、教师调整与防泄题</h3>
<p>有失分先巩固；至少两次独立满分才给变式；已测无有效证据先补充观察；未测指标不生成活动。教师可替换材料、提示与顺序，系统保留原计划，用版本号防止并发覆盖。提示优先选用审阅过的模板；自拟文字标记“未审阅”。所有提示先做短语与字面检查，再做等价式检查：整式按多项式比较，不等式与方程组按规范化关系比较，例如参考答案 3m-n 时，“−n+3m”“3·m−n”“3m+(-n)”都会被拦截。</p>
<h3>3.5 错因追问与补学路径</h3>
<p>失分评分点的评分标准按配置映射到概念理解、计算执行、条件理解三个维度，相关维度的小题排在最前；已定位出错步骤时，用学生本人的过程与填写生成一道核对题。追问结果只作核查线索，不改原测验得分。补学路径沿课程目录中的前置关系排列，每步链接原作答、学习卡和教材页码。</p>
<h3>3.6 批次冻结与可复算</h3>
<p>构建时把完整规则与各指标的追问题组写入批次，manifest 记录规则摘要和追问题组版本；修改配置只影响新批次。成果包携带 rules.json 与 followup_probes.json，从成果包重建时使用它们，摘要不符时拒绝构建。</p>

<h2>4 三名学生案例</h2>
{section_cases(batch, plans)}

<h2>5 两班分析</h2>
{section_classes(batch)}

<h2>6 验证</h2>
<h3>6.1 自动化测试</h3>
<p>生成本文时运行全部测试：共 {tests_run} 个，失败 {failed} 个，跳过 {skipped} 个。跳过的测试需要本地赛题资料包（设置 STUDY_CONTEST_SOURCE 后运行），赛题资料不随代码分发。测试覆盖：目录校验的六类边界输入及失败后旧批次可用；规则与追问题组冻结、成果包重建一致、篡改与冲突拒绝；等价答案拦截与方法类提示放行；证据权重不随分值缩放变化；同一输入重复构建的分析结果一致；权限、并发保存与版本冲突。</p>
<h3>6.2 证据权重模拟</h3>
<p>同一道题内的评分点高度相关。按评分点计证据会高估证据量：下表为模拟中 90% 区间覆盖真实目标值的比例与平均宽度（每格 3000 名模拟学生；生成假设见 docs/掌握度证据权重说明.md）。</p>
{table(["每生作答数", "每题评分点", "按评分点计：覆盖率 / 宽度", "按作答计：覆盖率 / 宽度"], calib_rows)}
<p class="note">按作答计的覆盖率高于名义 90%，属于偏保守；结论依赖模拟假设，不代表真实课堂中的覆盖率。</p>
<h3>6.3 教师对照评价（方案已备，尚未开展）</h3>
<p>设计了三组对照：A 仅按得分率推荐；B 增加评分点依据；C 再增加追问和补学路径。同一案例的三种呈现随机标为甲、乙、丙，由不参与开发的教师独立评分（依据是否充分、建议是否可执行、是否针对实际错误）。统计以案例为单位，用精确符号检验。<b>目前没有教师评分结果，本文不宣称诊断准确率或教学效果。</b></p>

<h2>7 成果包字段</h2>
{table(["文件", "内容"], [
    ["manifest.json", "批次编号、输入批次、源文件 SHA-256、规则摘要 rules_sha256、追问题组版本、构建与导出时间、教师调整版本"],
    ["rules.json / followup_probes.json", "批次冻结的完整规则与追问题组（重建时使用）"],
    ["catalog.json / learning_requirements.json", "主题、指标、题目、评分点、材料、课标与教材定位、指标关系"],
    ["students.json / responses.jsonl", "名册；最新作答（修订版本、评分状态、步骤、评分点得分）"],
    ["quality_report.json", "原始行数、事件数、状态计数、质量问题与复核记录"],
    ["diagnosis.json", "学生×测验×指标：覆盖五类计数、得分、证据状态、发现与证据、mastery（得分比例指数）"],
    ["class_comparison.json", "测验×指标：共同题、两班覆盖与得分、共性失分"],
    ["recommendations.json", "原始与有效学习活动、提示审阅标记 hint_review、调整版本"],
    ["followups.json / learning_paths.json", "追问作答与反馈；前置知识补学路径"],
    ["cases.json", "代表性案例"],
    ["contracts.md / integration.md / README.md", "字段说明、构建与复核步骤"],
])}

<h2>8 复算说明</h2>
<p>环境：Python 3.11 及以上；安装 <code>python -m pip install -e '.[test,docs]'</code>。</p>
<p>1）从赛题资料包构建：<code>python -m app.cli build --source data/赛题资料包</code>（命令打印批次编号）。<br/>
2）导出成果包：<code>python -m app.cli export --run-id &lt;批次编号&gt; --out outputs/成果包</code>。<br/>
3）从成果包复算：<code>python -m app.cli build --source outputs/成果包</code>，诊断、班级对比和初始计划与原批次一致；不导入教师调整和追问作答。<br/>
4）重新生成本文：<code>python -m tools.design_doc --run-id &lt;批次编号&gt; --data-label 赛题模拟学情数据 --out outputs/智慧学伴-设计方案.pdf</code>。<br/>
5）运行测试：<code>python -m unittest discover -s tests -v</code>；赛题回归测试需设置 STUDY_CONTEST_SOURCE。</p>
<p class="note">一致性说明：同一输入两次构建，诊断、对比、计划、规则与题组完全相同，只有批次编号和构建时间不同。若设置 STUDY_MODEL 启用本地模型挑选材料，计划可能因模型输出不同而变化，manifest 的 recommendation_mode 会记录这一点。</p>
<p class="note">本批次输入文件：{esc('；'.join(f"{s['path']} {s['sha256'][:12]}" for s in sources[:12]))}{' 等' if len(sources) > 12 else ''}</p>

<h2>9 局限</h2>
<p>1）诊断按规则判断，步骤定位只覆盖简单整式符号错误；2）得分比例指数未按题目难度调整、未做时间衰减，阈值是经验设定；3）追问每维度一道小题，只提供核查线索；4）数据为模拟学情，教师评价尚未开展；5）共享部署需配置账号与 HTTPS。</p>
"""


def render(html_text, out):
    archive = fitz.Archive()
    archive.add(fitz.Font("cjk").buffer, "cjk.ttf")
    story = fitz.Story(html=html_text, user_css=CSS, archive=archive)
    writer = fitz.DocumentWriter(str(out))
    page, frame = fitz.paper_rect("a4"), fitz.paper_rect("a4") + (50, 50, -50, -56)
    more = True
    while more:
        device = writer.begin_page(page)
        more, _ = story.place(frame)
        story.draw(device)
        writer.end_page()
    writer.close()
    with fitz.open(out) as document:
        pages = document.page_count
        for number, pdf_page in enumerate(document, 1):
            pdf_page.insert_text((page.width / 2 - 20, page.height - 30), f"— {number} / {pages} —",
                                 fontsize=8, fontname="china-s", color=(0.4, 0.4, 0.4))
        document.saveIncr()
    return pages


def generate(db, run_id, out, data_label, *, tests=None, students=3000):
    batch, plans = Store(db).snapshot(run_id)
    if "rules" not in batch:
        raise ValueError("该批次构建于规则冻结之前，请重新构建后生成设计方案。")
    tests = tests if tests is not None else run_tests()
    calibration = [((r, p), (lambda s: (s["per_point"], s["per_response"]))(simulate(students, r, p, 7)))
                   for r in (1, 3, 6) for p in (2, 10)]
    out.parent.mkdir(parents=True, exist_ok=True)
    pages = render(build_html(batch, plans, data_label, tests, calibration), out)
    if pages > MAX_PAGES:
        raise ValueError(f"设计方案共 {pages} 页，超过 {MAX_PAGES} 页上限。")
    return pages


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=Path("outputs/study.sqlite3"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--data-label", default="赛题模拟学情数据")
    args = parser.parse_args()
    pages = generate(args.db, args.run_id, args.out, args.data_label)
    print(f"{args.out}（{pages} 页）")


if __name__ == "__main__":
    main()
