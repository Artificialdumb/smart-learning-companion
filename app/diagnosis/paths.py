"""Prerequisite paths using only evidence available at the selected node."""

from graphlib import CycleError, TopologicalSorter

from app._analysis import index


def prerequisite_graph(catalog):
    graph = {iid: set() for iid in index(catalog["indicators"], "indicator_id")}
    for relation in catalog.get("learning_relations", []):
        if relation["relation_type"] != "prerequisite":
            continue
        start, end = relation["from_indicator_id"], relation["to_indicator_id"]
        if start not in graph or end not in graph:
            raise ValueError("前置知识关系引用了未知指标。")
        graph[end].add(start)
    try:
        order = list(TopologicalSorter({k: sorted(v) for k, v in sorted(graph.items())}).static_order())
    except CycleError as error:
        raise ValueError("前置知识关系存在环，请先核对课程目录。") from error
    return graph, order


def learning_paths(catalog, reports, node_id):
    graph, order = prerequisite_graph(catalog)
    nodes = index(catalog["nodes"], "node_id")
    items = index(catalog["items"], "item_id")
    current = index(reports[node_id]["indicators"], "indicator_id")
    date = nodes[node_id].get("assessment_date")
    previous = sorted((
        (node["assessment_date"], nid) for nid, node in nodes.items()
        if date and node.get("assessment_date") and node["assessment_date"] < date and nid in reports
    ), reverse=True)
    historical = [(nid, index(reports[nid]["indicators"], "indicator_id")) for _, nid in previous]

    def step(iid):
        summary, evidence_node = current[iid], node_id
        if summary["evidence_status"] == "not_assessed":
            for nid, summaries in historical:
                if summaries[iid]["evidence_status"] != "not_assessed":
                    summary, evidence_node = summaries[iid], nid
                    break
        weak = [f for f in summary["findings"] if f["kind"] == "practice_needed"]
        findings = weak or summary["findings"]
        action = "practice" if weak else "continue" if summary["evidence_status"] == "supported" else "check"
        materials = [r["resource_id"] for r in catalog.get("resources", [])
                     if iid in r["indicator_ids"] and r["resource_type"] in {"learning_card", "textbook"}]
        item_ids = [item_id for item_id, item in items.items()
                    if iid in item["indicator_ids"] and item_id in nodes[node_id]["item_ids"]]
        return {
            "indicator_id": iid, "action": action, "evidence_status": summary["evidence_status"],
            "evidence_node_id": evidence_node, "historical": evidence_node != node_id,
            "finding_ids": [f["finding_id"] for f in findings],
            "evidence": [e for f in findings for e in f["evidence"]],
            "resource_ids": materials, "practice_item_ids": item_ids[:2],
        }

    paths = []
    for target, summary in current.items():
        if not any(f["kind"] == "practice_needed" for f in summary["findings"]):
            continue
        ancestors, pending = set(), list(graph[target])
        while pending:
            iid = pending.pop()
            if iid not in ancestors:
                ancestors.add(iid)
                pending.extend(graph[iid])
        steps = [step(iid) for iid in order if iid in ancestors | {target}]
        relations = [rel for rel in catalog.get("learning_relations", [])
                     if rel["relation_type"] == "prerequisite"
                     and rel["from_indicator_id"] in ancestors
                     and rel["to_indicator_id"] in ancestors | {target}]
        paths.append({
            "target_indicator_id": target, "steps": steps, "relations": relations,
            "priority_check_ids": [s["indicator_id"] for s in steps
                                   if s["indicator_id"] != target and s["action"] in {"practice", "check"}],
            "note": ("按前置顺序核查与补学；关系不能单独证明本次失分原因。" if ancestors else
                     "目录未提供该指标的前置关系，先复习当前指标。"),
        })
    return {"student_id": reports[node_id]["student_id"], "node_id": node_id, "paths": paths,
            "empty_reason": None if paths else "当前节点没有有效失分证据，暂不生成补学路径。"}
