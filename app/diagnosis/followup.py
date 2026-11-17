"""Evidence-linked screening, kept separate from assessment scores."""

from datetime import datetime, timezone

from app._analysis import index
from app.contracts import ContractError
from app.diagnosis.probes import DIMENSIONS, PROBE_VERSION, questions_for


def indicator_context(batch, student_id, node_id, indicator_id):
    reports = batch["diagnoses"].get(student_id)
    if reports is None:
        raise ContractError("student_not_found", "找不到学生。", 404)
    if node_id not in reports:
        raise ContractError("node_not_found", "找不到测验节点。", 404)
    indicator = index(batch["catalog"]["indicators"], "indicator_id").get(indicator_id)
    if indicator is None:
        raise ContractError("indicator_not_found", "找不到课程指标。", 404)
    summary = next(row for row in reports[node_id]["indicators"] if row["indicator_id"] == indicator_id)
    return indicator, summary


def followup_view(batch, student_id, node_id, indicator_id, saved=None):
    indicator, summary = indicator_context(batch, student_id, node_id, indicator_id)
    findings = [f for f in summary["findings"] if f["kind"] == "practice_needed"]
    questions = questions_for(indicator["description"])
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
        "questions": [
            {key: q[key] for key in ("question_id", "dimension", "prompt", "options")}
            for q in questions
        ] if reason is None else [],
        "unavailable_reason": reason,
        "result": saved["result"] if saved else None,
    }


def evaluate_followup(batch, student_id, node_id, indicator_id, probe_version, answers):
    view = followup_view(batch, student_id, node_id, indicator_id)
    if probe_version != PROBE_VERSION:
        raise ContractError("probe_version_conflict", "追问题组已更新，请重新打开后作答。", 409)
    if view["unavailable_reason"]:
        raise ContractError("followup_unavailable", view["unavailable_reason"])
    indicator, _ = indicator_context(batch, student_id, node_id, indicator_id)
    questions = questions_for(indicator["description"])
    if set(answers) != {q["question_id"] for q in questions}:
        raise ContractError("invalid_answers", "请提交这三道追问题各一次的作答。")
    checks = []
    for q in questions:
        selected = answers[q["question_id"]]
        if selected not in {o["option_id"] for o in q["options"]} | {"unsure"}:
            raise ContractError("invalid_answers", "作答选项不存在。")
        checks.append({
            **q, "selected_option_id": selected,
            "outcome": "uncertain" if selected == "unsure" else "pass" if selected == q["answer_id"] else "gap",
        })
    gaps = [q["dimension"] for q in checks if q["outcome"] == "gap"]
    uncertain = [q["dimension"] for q in checks if q["outcome"] == "uncertain"]
    if gaps:
        conclusion = "需优先核查：" + "、".join(DIMENSIONS[d] for d in gaps) + "。"
        if uncertain:
            conclusion += "另有未确定作答，需继续观察。"
    elif uncertain:
        conclusion = "存在未确定作答，证据不足以区分错因。"
    else:
        conclusion = "本次小题均通过，尚未复现原题错误；请回看原题过程与最终填写。"
    return {
        "probe_version": PROBE_VERSION, "submitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "finding_ids": view["finding_ids"], "evidence": view["evidence"],
        "checks": checks, "suspected_causes": gaps, "uncertain_dimensions": uncertain,
        "conclusion": conclusion,
        "limitation": "每个维度仅一道小题，结果是核查线索，不是原题错因定论；重复作答不用于证明学习提升。",
    }
