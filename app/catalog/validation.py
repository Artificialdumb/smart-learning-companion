"""Catalog checks shared by the raw CSV route and the normalized-input route.

Both routes end in ``validate_catalog`` so a batch cannot be published from a
catalog that one route would have refused. Every message names the offending id.
"""

from datetime import date

from app._analysis import index, rubric_limits
from app.diagnosis.paths import prerequisite_graph
from app.recommendations import resource_index


def _id_list(value, owner, field):
    if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value):
        raise ValueError(f"{owner}: {field} 须为非空字符串列表")
    if len(value) != len(set(value)):
        raise ValueError(f"{owner}: {field} 有重复编号")
    return value


def validate_catalog(catalog):
    """Return the catalog with a complete resource list, or raise ValueError naming the bad id."""
    topics = index(catalog["topics"], "topic_id")
    indicators = index(catalog["indicators"], "indicator_id")
    items = index(catalog["items"], "item_id")
    nodes = index(catalog["nodes"], "node_id")
    if not topics or not indicators or not items or not nodes:
        raise ValueError("目录须包含主题、指标、题目和测验节点。")

    for indicator_id, indicator in indicators.items():
        if indicator["topic_id"] not in topics:
            raise ValueError(f"{indicator_id}: 指标引用了未知主题 {indicator['topic_id']}")

    for item_id, item in items.items():
        ids = _id_list(item.get("indicator_ids"), item_id, "indicator_ids")
        if not ids:
            raise ValueError(f"{item_id}: 题目缺少观察指标，作答将无法进入任何指标分析")
        unknown = set(ids) - indicators.keys()
        if unknown:
            raise ValueError(f"{item_id}: 题目引用了未知指标 {sorted(unknown)}")
        topic = item.get("topic_id")
        if topic is not None and any(indicators[i]["topic_id"] != topic for i in ids):
            raise ValueError(f"{item_id}: 题目主题 {topic} 与所映射指标的主题不一致")
        rubric_limits(item)

    resources = resource_index(catalog)
    for resource_id, resource in resources.items():
        ids = resource.get("indicator_ids")
        if resource_id not in items and isinstance(ids, list):
            # Textbooks gather indicators from several CSV rows; repeats carry no extra meaning.
            ids = resource["indicator_ids"] = list(dict.fromkeys(ids))
        ids = _id_list(ids, resource_id, "indicator_ids")
        if not set(ids) <= indicators.keys():
            raise ValueError(f"{resource_id}: 材料引用了未知指标 {sorted(set(ids) - indicators.keys())}")
        if (resource["resource_type"] == "item") != (resource_id in items):
            raise ValueError(f"{resource_id}: 题目与材料索引不一致")
    for indicator_id, indicator in indicators.items():
        missing = [ref["resource_id"] for ref in indicator.get("references", []) if ref["resource_id"] not in resources]
        if missing:
            raise ValueError(f"{indicator_id}: 指标出处无法定位 {missing}")

    for node_id, node in nodes.items():
        item_ids = _id_list(node.get("item_ids"), node_id, "item_ids")
        if not item_ids:
            raise ValueError(f"{node_id}: 测验节点没有可用题目")
        unknown = [i for i in item_ids if i not in items]
        if unknown:
            raise ValueError(f"{node_id}: 测验节点引用了不存在的题目 {unknown}")
        if node.get("assessment_date") is not None:
            try:
                date.fromisoformat(node["assessment_date"])
            except (TypeError, ValueError) as error:
                raise ValueError(f"{node_id}: 测验日期须为 YYYY-MM-DD") from error

    for relation in catalog.get("learning_relations", []):
        ends = {relation["from_indicator_id"], relation["to_indicator_id"]}
        if not ends <= indicators.keys():
            raise ValueError(f"学习关系引用了未知指标 {sorted(ends - indicators.keys())}")
    prerequisite_graph(catalog)
    return {**catalog, "resources": list(resources.values())}
