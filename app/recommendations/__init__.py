"""Build evidence-linked activities and validate teacher adjustments."""

import re
import unicodedata
from collections import defaultdict

from app._analysis import index, rubric_points
from app.contracts import ContractError
from app.rules import load_rules

KIND_ORDER = {"practice_needed": 0, "strength": 1, "observe_more": 2}
RESOURCE_TYPES = {"item", "learning_card", "textbook"}


def _rules():
    return load_rules()["recommendations"]


def normalize(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text).lower()).replace("−", "-")


def resource_index(catalog):
    resources = index(catalog.get("resources", []), "resource_id")
    for item_id, item in index(catalog["items"], "item_id").items():
        resources.setdefault(item_id, {
            "resource_id": item_id,
            "title": item.get("prompt", item_id),
            "resource_type": "item",
            "indicator_ids": item["indicator_ids"],
        })
    return resources


def eligible_resource(resource, indicator_id, node, items):
    resource_id = resource["resource_id"]
    kind = resource["resource_type"]
    if kind not in RESOURCE_TYPES or indicator_id not in resource["indicator_ids"]:
        return False
    return kind != "item" or (
        resource_id in node["item_ids"] and indicator_id in items[resource_id]["indicator_ids"]
    )


def checked_text(resource_id, hints, condition, items):
    hints = [hint.strip() for hint in hints]
    condition = condition.strip()
    if not 1 <= len(hints) <= 6 or any(not 1 <= len(t) <= 200 for t in hints) or not 1 <= len(condition) <= 300:
        raise ContractError("invalid_text", "填写 1–6 条提示和一条复查条件。每条提示最多 200 字，复查条件最多 300 字。")
    item = items.get(resource_id, {})
    answer = normalize(item.get("reference_answer") or "").strip("。.!！")
    for text in (*hints, condition):
        value = normalize(text)
        direct = re.search(
            r"(?:正确|参考|标准|最终)?答案(?:是|为|[:=])|(?:结果|解集|最终作答)(?:应为|就是|为|是|[:=])"
            r"|直接(?:填|选|写)|(?:应|应该|请选择|故|所以)选?[a-d](?:项|[。.!！]|$)",
            value,
        )
        # Short answers also occur in ordinary prose. Check stand-alone values and
        # explicit fill/select/equality contexts for those answers.
        literal = answer and (
            value.strip("。.!！?？") == answer
            or (
                len(answer) > 1
                and re.search(rf"(?<![a-z0-9]){re.escape(answer)}(?![a-z0-9])", value)
            )
            or re.search(
                rf"(?:填(?:写|入)?|选(?:择)?|得到|等于|=|为|是)[「“'\"]?{re.escape(answer)}"
                r"(?![a-z0-9])(?:[」”'\"])?(?:项|[，。.!！?？,;；)]|$)",
                value,
            )
        )
        if direct or literal:
            raise ContractError("answer_in_hint", "提示或复查条件含有直接给出答案的表述。请改为检查步骤或判断依据。")
    return hints, condition


def evidence_for(finding, records, items, report, indicator_id):
    ids = []
    for evidence in finding["evidence"]:
        record_id = evidence["record_id"]
        row = records.get(record_id)
        if (
            row is None
            or row["scoring_status"] != "graded"
            or row["validation_status"] != "valid"
            or (row["student_id"], row["node_id"]) != (report["student_id"], report["node_id"])
            or indicator_id not in items[row["item_id"]]["indicator_ids"]
            or not set(evidence["rubric_point_ids"]) <= rubric_points(items[row["item_id"]]).keys()
            or any(not 1 <= step <= len(row["steps"]) for step in evidence.get("step_numbers", []))
        ):
            raise ValueError(f"诊断证据引用不匹配: {record_id}")
        ids.append(record_id)
    if not ids and finding["kind"] != "observe_more":
        raise ValueError(f"缺少诊断证据: {finding['finding_id']}")
    return list(dict.fromkeys(ids))


def choose_finding(summary, evidence, records):
    findings = summary["findings"]
    if summary["evidence_status"] == "insufficient":
        return next((f for f in findings if f["kind"] == "observe_more"), None)
    if summary["evidence_status"] != "supported":
        return None
    practice = [f for f in findings if f["kind"] == "practice_needed"]
    if practice:
        # A localized step supports a more specific follow-up than a total score.
        return max(practice, key=lambda f: any(e.get("step_numbers") for e in f["evidence"]))
    for finding in findings:
        if finding["kind"] == "strength" and len({
            records[rid]["event_id"] for rid in evidence[finding["finding_id"]]
            if records[rid]["score"] == records[rid]["max_score"]
        }) >= 2:
            return finding
    return None


def choose_resource(candidates, kind, items, source, attempted, description, used):
    source_prompt = normalize(source.get("prompt", ""))
    rules = _rules()
    form, transfer_rule = rules["matched_form_keyword"], rules["transfer"]

    def rank(resource):
        rid = resource["resource_id"]
        item = items.get(rid, {})
        prompt = normalize(item.get("prompt", ""))
        matched_form = (
            form in source_prompt and form in prompt
            and bool(re.search(r"-\d*\(", prompt))
            and prompt.count("(") == source_prompt.count("(")
        )
        transfer = (kind == "strength" and transfer_rule["indicator_keyword"] in description
                    and transfer_rule["item_keyword"] in prompt)
        return (
            rid in used, rid == source.get("item_id"),
            resource["resource_type"] != "item", rid in attempted,
            not transfer, not matched_form,
            item.get("max_score", 0) if kind == "practice_needed" else -item.get("max_score", 0),
            rid,
        )

    return sorted(candidates, key=rank)


def activity_text(kind, resource, description, finding, item):
    rid = resource["resource_id"]
    rules = _rules()
    default = rules["default_cue"]
    cue = next(((row["hint"], row["condition"]) for row in rules["skill_cues"]
                if any(word in description for word in row["keywords"])),
               (default["hint"], default["condition"]))
    transfer = rules["transfer"]
    if resource["resource_type"] != "item":
        return (
            f"复习与该指标对应的材料 {rid}，再用自己的例子检查理解。",
            ["读完后用自己的话说明方法。", "另写一个同类例子，解释每一步。"],
            "能独立解释方法，并用例子说明什么时候使用。",
        )
    if kind == "practice_needed":
        localized = any(e.get("step_numbers") for e in finding["evidence"])
        reason = (
            f"用 {rid} 练习核对过程末行与最终填写，巩固本次作答出现的薄弱步骤。" if localized
            else f"用同一指标下的 {rid} 巩固本次作答中定位到的问题。"
        )
        followup = (
            "逐项核对过程最后一行与最终填写是否一致。" if localized
            else "完成后回看每一步，标记需要重做的位置。"
        )
    elif kind == "strength":
        reason = f"已有多道满分作答支持当前表现，用 {rid} 检查能否迁移到新题。"
        if transfer["item_keyword"] in item.get("prompt", "") and transfer["indicator_keyword"] in description:
            reason = transfer["reason"].format(resource_id=rid)
            followup = transfer["followup"]
        else:
            followup = "写出与之前题目不同的条件，再解释所用方法。"
    else:
        reason = f"该指标已测且有效证据不足，用 {rid} 获取一次独立作答。"
        followup = "保留解题过程，标出犹豫或需要帮助的环节。"
    return reason, [cue[0], followup], cue[1]


def plan_id(student_id, node_id):
    return f"PLAN-{student_id}-{node_id}"


def generate_plans(catalog, diagnosis_results, evidence_by_record_id, *, select_resource=None):
    """Return original plans indexed by student_id and node_id."""
    items = index(catalog["items"], "item_id")
    nodes = index(catalog["nodes"], "node_id")
    indicators = index(catalog["indicators"], "indicator_id")
    resources = resource_index(catalog)
    records = index(evidence_by_record_id, "record_id")
    attempts = defaultdict(set)
    for row in records.values():
        if row["scoring_status"] != "unanswered":
            attempts[row["student_id"], row["node_id"]].add(row["item_id"])
    result = {}
    for student, reports in diagnosis_results.items():
        result[student] = {}
        for node_id, report in reports.items():
            pending, activities = [], []
            for summary in report["indicators"]:
                iid = summary["indicator_id"]
                evidence = {
                    f["finding_id"]: evidence_for(f, records, items, report, iid)
                    for f in summary["findings"]
                }
                finding = choose_finding(summary, evidence, records)
                if finding:
                    localized = any(e.get("step_numbers") for e in finding["evidence"])
                    pending.append((
                        KIND_ORDER[finding["kind"]], not localized, iid, finding,
                        evidence[finding["finding_id"]],
                    ))
            used = set()
            for _, _, iid, finding, ids in sorted(pending):
                kind = finding["kind"]
                description = indicators[iid]["description"]
                source = items[records[ids[0]]["item_id"]] if ids else {}
                candidates = choose_resource(
                    [r for r in resources.values() if eligible_resource(r, iid, nodes[node_id], items)],
                    kind, items, source, attempts[student, node_id], description, used,
                )
                ranked = []
                for resource in candidates:
                    rid = resource["resource_id"]
                    reason, hints, condition = activity_text(kind, resource, description, finding, items.get(rid, {}))
                    try:
                        hints, condition = checked_text(rid, hints, condition, items)
                    except ContractError:
                        continue
                    ranked.append((rid, reason, hints, condition))
                if not ranked:
                    continue
                by_id = {row[0]: row for row in ranked}
                preferred = select_resource(kind, iid, tuple(by_id)) if select_resource else None
                rid, reason, hints, condition = by_id.get(preferred, ranked[0])
                used.add(rid)
                sequence = len(activities) + 1
                activities.append({
                    "recommendation_id": f"REC-{student}-{node_id}-{sequence:02d}",
                    "indicator_id": iid, "finding_ids": [finding["finding_id"]],
                    "evidence_record_ids": ids, "kind": kind, "resource_id": rid,
                    "sequence": sequence, "reason": reason, "hints": hints,
                    "recheck_condition": condition,
                })
            result[student][node_id] = {
                "plan_id": plan_id(student, node_id),
                "student_id": student, "node_id": node_id, "activities": activities,
                "empty_reason": None if activities else "当前节点没有满足证据和材料条件的活动。",
            }
    return result


def validate_adjustment(plan, edits, catalog):
    original = index(plan["activities"], "recommendation_id")
    edit_ids = [edit["recommendation_id"] for edit in edits]
    if not original or len(edit_ids) != len(original) or set(edit_ids) != original.keys():
        raise ContractError("invalid_activities", "调整须包含计划中的每个活动各一次。")
    if sorted(edit["sequence"] for edit in edits) != list(range(1, len(edits) + 1)):
        raise ContractError("invalid_sequence", "活动顺序须从 1 开始连续排列。")
    resources = resource_index(catalog)
    items = index(catalog["items"], "item_id")
    node = index(catalog["nodes"], "node_id")[plan["node_id"]]
    effective = []
    for edit in sorted(edits, key=lambda row: row["sequence"]):
        prior = original[edit["recommendation_id"]]
        rid = edit["resource_id"]
        if rid not in resources:
            raise ContractError("resource_not_found", f"找不到材料 {rid}。", 404)
        if not eligible_resource(resources[rid], prior["indicator_id"], node, items):
            raise ContractError("invalid_resource", f"材料 {rid} 与活动指标或测验范围不匹配。")
        hints, condition = checked_text(rid, edit["hints"], edit["recheck_condition"], items)
        effective.append({
            **prior, "resource_id": rid, "sequence": edit["sequence"],
            "hints": hints, "recheck_condition": condition,
            "reason": (
                prior["reason"] if rid == prior["resource_id"] else
                f"教师更换为 {rid}，继续练习活动关联的同一指标。"
            ),
        })
    return effective
