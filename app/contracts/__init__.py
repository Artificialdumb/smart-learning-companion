"""Shared JSON contract helpers used by batch builds and HTTP responses."""

import json

from app._analysis import index


class ContractError(ValueError):
    def __init__(self, code, message, status=422, details=None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.details = details


def encode_json(value, *, indent=None):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=indent)


def with_run(run_id, payload):
    return {**payload, "run_id": run_id}


def usable_rows(latest, content=None):
    """Validate the optional A usable file against the canonical latest rows."""
    usable = [row for row in latest
              if row["scoring_status"] == "graded" and row["validation_status"] == "valid"]
    if content is not None:
        supplied = [json.loads(line) for line in content.splitlines() if line.strip()]
        if index(supplied, "record_id") != index(usable, "record_id"):
            raise ValueError("usable_responses.jsonl 与 responses.jsonl 中的有效作答不一致。")
    return usable
