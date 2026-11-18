"""Evidence-linked screening, kept separate from assessment scores."""

import re
import unicodedata
from datetime import datetime, timezone

from app._analysis import index, rubric_points
from app.contracts import ContractError
from app.diagnosis.probes import LABELS, PROBE_VERSION, criterion_dimension, questions_for

PUBLIC_FIELDS = ("question_id", "dimension", "dimension_label", "prompt", "options", "focus", "rubric_point_ids")


def indicator_context(batch, student_id, node_id, indicator_id):
    reports = batch["diagnoses"].get(student_id)
    if reports is None:
        raise ContractError("student_not_found", "找不到学生。", 404)
    if node_id not in reports:
        raise ContractError("node_not_found", "找不到测验节点。", 404)
    indicator = index(batch["catalog"]["indicators"], "indicator_id").get(indicator_id)
    if indicator is None:
        raise ContractError("indicator_not_found", "找不到课程指标。", 404)
    summary = next((row for row in reports[node_id]["indicators"] if row["indicator_id"] == indicator_id), None)
    if summary is None:
        raise ContractError("indicator_not_found", "该测验节点没有这个课程指标。", 404)
    return indicator, summary


def missed_points(batch, findings):
    """Missed rubric points cited by the findings, with criterion text and dimension."""
    items = index(batch["catalog"]["items"], "item_id")
    linked = {}
    for finding in findings:
        for evidence in finding["evidence"]:
            record = batch["records"].get(evidence["record_id"])
            if record is None or record["item_id"] not in items:
                continue
            points = rubric_points(items[record["item_id"]])
            for point_id in evidence["rubric_point_ids"]:
                if point_id in points and point_id not in linked:
                    criterion = points[point_id]["criterion"]
                    linked[point_id] = {"rubric_point_id": point_id, "item_id": record["item_id"],
                                        "criterion": criterion, "dimension": criterion_dimension(criterion)}
    return list(linked.values())


def _clean(text):
    text = unicodedata.normalize("NFKC", text or "").replace("−", "-")
    text = re.sub(r"^\s*\d+[.．、]\s*", "", text)
    return re.sub(r"\s+", "", text).removeprefix("=").strip("。.")


def consistency_question(batch, findings):
    """A question built from the student's own localized step, when the diagnosis found one."""
    items = index(batch["catalog"]["items"], "item_id")
    for finding in findings:
        for evidence in finding["evidence"]:
            record = batch["records"].get(evidence["record_id"])
            steps = evidence.get("step_numbers") or []
            if record is None or not steps or not 1 <= steps[0] <= len(record.get("steps") or []):
                continue
            item = items.get(record["item_id"], {})
            line, final = _clean(record["steps"][steps[0] - 1]), _clean(record.get("final_answer"))
            reference = _clean(item.get("reference_answer"))
            if not line or not final or line == final or reference not in (line, final):
                continue
            texts = sorted((line, final))
            options = [*texts, "两者都不对"]
            return {
                "question_id": f"consistency-{record['record_id']}",
                "dimension": "consistency",
                "dimension_label": LABELS["consistency"],
                "prompt": (f"回看 {record['item_id']}：你的解题过程第 {steps[0]} 步写的是「{line}」，"
                           f"最终填写的是「{final}」。哪一个是这道题正确的最终结果？"),
                "options": [{"option_id": str(i), "text": text} for i, text in enumerate(options)],
                "answer_id": str(options.index(reference)),
                "explanation": "最终填写应与过程末行一致。誊写答案时逐项核对符号，尤其是去括号后的各项。",
                "focus": True,
                "rubric_point_ids": list(evidence["rubric_point_ids"]),
            }
    return None


def question_set(batch, indicator, findings):
    """Fixed screening questions ordered by the missed rubric points, plus an evidence-built check."""
    linked = missed_points(batch, findings)
    by_dimension = {}
    for point in linked:
        if point["dimension"]:
            by_dimension.setdefault(point["dimension"], []).append(point["rubric_point_id"])
    questions = [
        {**q, "dimension_label": LABELS[q["dimension"]], "focus": q["dimension"] in by_dimension,
         "rubric_point_ids": by_dimension.get(q["dimension"], [])}
        for q in questions_for(indicator["description"])
    ]
    if not questions:
        return [], linked
    focus_order = list(by_dimension)
    questions.sort(key=lambda q: focus_order.index(q["dimension"]) if q["focus"] else len(focus_order))
    targeted = consistency_question(batch, findings)
    return ([targeted] if targeted else []) + questions, linked


def followup_view(batch, student_id, node_id, indicator_id, saved=None):
    indicator, summary = indicator_context(batch, student_id, node_id, indicator_id)
    findings = [f for f in summary["findings"] if f["kind"] == "practice_needed"]
    questions, linked = question_set(batch, indicator, findings)
    reason = None
    if not findings or summary["evidence_status"] != "supported":
        reason = "当前没有有效失分证据，暂不进行错因辨析。"
    elif not questions:
        reason = "该指标尚无经过编写的追问题组，请由教师补充观察。"
    return {
        "student_id": student_id, "node_id": node_id, "indicator_id": indicator_id,
        "probe_version": PROBE_VERSION, "version": saved["version"] if saved else 0,
        "finding_ids": [f["finding_id"] for f in findings],
        "evidence": [e for f in findings for e in f["evidence"]],
        "linked_rubric_points": linked if reason is None else [],
        "questions": [{key: q[key] for key in PUBLIC_FIELDS} for q in questions] if reason is None else [],
        "unavailable_reason": reason,
        "result": saved["result"] if saved else None,
    }


def evaluate_followup(batch, student_id, node_id, indicator_id, probe_version, answers):
    view = followup_view(batch, student_id, node_id, indicator_id)
    if probe_version != PROBE_VERSION:
        raise ContractError("probe_version_conflict", "追问题组已更新，请重新打开后作答。", 409)
    if view["unavailable_reason"]:
        raise ContractError("followup_unavailable", view["unavailable_reason"])
    indicator, summary = indicator_context(batch, student_id, node_id, indicator_id)
    findings = [f for f in summary["findings"] if f["kind"] == "practice_needed"]
    questions, linked = question_set(batch, indicator, findings)
    if set(answers) != {q["question_id"] for q in questions}:
        raise ContractError("invalid_answers", "请提交每道追问题各一次的作答。")
    checks = []
    for q in questions:
        selected = answers[q["question_id"]]
        if selected not in {o["option_id"] for o in q["options"]} | {"unsure"}:
            raise ContractError("invalid_answers", "作答选项不存在。")
        checks.append({
            **q, "selected_option_id": selected,
            "outcome": "uncertain" if selected == "unsure" else "pass" if selected == q["answer_id"] else "gap",
        })
    gaps = list(dict.fromkeys(q["dimension"] for q in checks if q["outcome"] == "gap"))
    uncertain = list(dict.fromkeys(q["dimension"] for q in checks if q["outcome"] == "uncertain"))
    focus = list(dict.fromkeys(q["dimension"] for q in checks if q["focus"] and q["outcome"] == "gap"))
    if gaps:
        conclusion = "需优先核查：" + "、".join(LABELS[d] for d in gaps) + "。"
        if focus:
            points = "、".join(f"{p['criterion']}（{p['rubric_point_id']}）" for p in linked
                              if p["dimension"] in focus or "consistency" in focus)
            if points:
                conclusion += f"其中与本次失分评分点{points}直接相关的小题未通过。"
        if uncertain:
            conclusion += "另有未确定作答，需继续观察。"
    elif uncertain:
        conclusion = "存在未确定作答，证据不足以区分错因。"
    else:
        conclusion = "本次小题均通过，尚未复现原题错误；请回看原题过程与最终填写。"
    return {
        "probe_version": PROBE_VERSION, "submitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "finding_ids": view["finding_ids"], "evidence": view["evidence"],
        "linked_rubric_points": linked,
        "checks": checks, "suspected_causes": gaps, "uncertain_dimensions": uncertain,
        "conclusion": conclusion,
        "limitation": "每个维度仅一道小题，结果是核查线索，不是原题错因定论；重复作答不用于证明学习提升。",
    }
