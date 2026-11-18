"""Load rule settings from app/rules.json, optionally overridden by $STUDY_RULES."""

import hashlib
import json
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


@lru_cache(maxsize=8)
def _load(override):
    rules = json.loads(DEFAULT_RULES.read_text(encoding="utf-8"))
    if override:
        custom = json.loads(Path(override).read_text(encoding="utf-8"))
        if not isinstance(custom, dict):
            raise ValueError("规则覆盖文件须为 JSON 对象。")
        for section, value in custom.items():
            base = rules.get(section)
            rules[section] = {**base, **value} if isinstance(base, dict) and isinstance(value, dict) else value
    rules = _strip_comments(rules)
    digest = hashlib.sha256(json.dumps(rules, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return rules, digest


def load_rules():
    return _load(os.environ.get("STUDY_RULES") or None)[0]


def rules_digest():
    return _load(os.environ.get("STUDY_RULES") or None)[1]


@lru_cache(maxsize=1)
def curriculum():
    return _strip_comments(json.loads(CURRICULUM.read_text(encoding="utf-8")))
