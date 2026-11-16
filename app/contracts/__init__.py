"""Shared JSON contract helpers used by batch builds and HTTP responses."""

import json


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
