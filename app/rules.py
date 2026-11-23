"""Rule settings: defaults in app/rules.json, optional $STUDY_RULES override, per-batch freezing.

A build resolves the rules once and stores the full resolved set in the batch, so
diagnosis, plans, follow-ups and teacher-edit checks of that batch keep using it
even after the defaults or the override file change. Exported packages carry the
same set as ``rules.json``; a rebuild from a package uses it instead of the
environment.
"""

import hashlib
import json
import math
import os
from functools import lru_cache
from pathlib import Path

DEFAULT_RULES = Path(__file__).with_name("rules.json")
CURRICULUM = Path(__file__).parent / "catalog" / "curriculum.json"


def _strip_comments(value):
    if isinstance(value, dict):
        return {k: _strip_comments(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, list):
        return [_strip_comments(v) for v in value]
    return value


def validate_rules(rules):
    """Reject invalid thresholds and matching cues before a batch can be published."""
    if not isinstance(rules, dict) or any(not isinstance(rules.get(k), dict) for k in
            ("mastery", "diagnosis", "followup", "recommendations", "export")):
        raise ValueError("规则须包含完整的五个配置分区。")
    mastery = rules["mastery"]
    def number(value):
        return type(value) in (int, float) and math.isfinite(value)
    prior = mastery.get("prior")
    if not isinstance(prior, list) or len(prior) != 2 or any(not number(v) or v <= 0 for v in prior):
        raise ValueError("mastery.prior 须为两个有限正数。")
    for key in ("interval_level", "mastered_lower", "developing_mean"):
        value = mastery.get(key)
        if not number(value) or not 0 < value < 1:
            raise ValueError(f"mastery.{key} 须在 0 与 1 之间。")
    if type(mastery.get("min_evidence")) is not int or mastery["min_evidence"] < 1:
        raise ValueError("mastery.min_evidence 须为正整数。")
    for key in ("criterion_cues", "profile_cues"):
        cues = rules["followup"].get(key)
        if not isinstance(cues, list) or not cues:
            raise ValueError(f"followup.{key} 须为非空匹配列表。")
        for row in cues:
            if (not isinstance(row, list) or len(row) != 2 or not isinstance(row[0], str)
                    or not row[0].strip() or not isinstance(row[1], list) or not row[1]
                    or any(not isinstance(v, str) or not v.strip() for v in row[1])):
                raise ValueError(f"followup.{key} 的匹配条目格式无效。")
        if key == "criterion_cues" and any(row[0] not in {"concept", "calculation", "reading"} for row in cues):
            raise ValueError("追问维度须为 concept、calculation 或 reading。")
    return rules


def digest(rules):
    """Stable SHA-256 of a resolved rule set (comments already removed)."""
    return hashlib.sha256(json.dumps(rules, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _load(override):
    rules = json.loads(DEFAULT_RULES.read_text(encoding="utf-8"))
    if override:
        custom = json.loads(Path(override).read_text(encoding="utf-8"))
        if not isinstance(custom, dict):
            raise ValueError("规则覆盖文件须为 JSON 对象。")
        for section, value in custom.items():
            base = rules.get(section)
            rules[section] = {**base, **value} if isinstance(base, dict) and isinstance(value, dict) else value
    rules = validate_rules(_strip_comments(rules))
    return json.dumps(rules, ensure_ascii=False)


def override_path():
    return os.environ.get("STUDY_RULES") or None


def load_rules():
    """Rules for a new build: defaults plus the optional $STUDY_RULES override (a fresh copy)."""
    return json.loads(_load(override_path()))


def rules_digest():
    return digest(load_rules())


def read_packaged(path, expected_digest=None):
    """Rules stored in an exported package; refuse files that no longer match the manifest."""
    rules = _strip_comments(json.loads(Path(path).read_text(encoding="utf-8")))
    if not isinstance(rules, dict):
        raise ValueError("成果包中的 rules.json 须为 JSON 对象。")
    if expected_digest is not None and digest(rules) != expected_digest:
        raise ValueError("成果包中的 rules.json 与 manifest.json 记录的 rules_sha256 不一致。")
    return validate_rules(rules)


def batch_rules(batch):
    """Rules a stored batch was built with; batches from before freezing fall back to the defaults."""
    return batch.get("rules") or load_rules()


@lru_cache(maxsize=1)
def curriculum():
    return _strip_comments(json.loads(CURRICULUM.read_text(encoding="utf-8")))
