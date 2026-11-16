"""Optional local model chooses among already validated resources."""

import json
import logging
import os
from functools import lru_cache
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

logger = logging.getLogger(__name__)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def local_selector():
    model = os.environ.get("STUDY_MODEL")
    if not model:
        return None
    port = int(os.environ.get("STUDY_MODEL_PORT", "11434"))
    if not 1 <= port <= 65535:
        raise ValueError("STUDY_MODEL_PORT 必须在 1–65535 之间。")
    endpoint = f"http://127.0.0.1:{port}/v1/chat/completions"
    opener = build_opener(ProxyHandler({}), NoRedirect())
    headers = {"Content-Type": "application/json"}
    if key := os.environ.get("STUDY_MODEL_KEY"):
        headers["Authorization"] = f"Bearer {key}"
    available = True

    @lru_cache(maxsize=512)
    def select(kind, indicator_id, ids):
        nonlocal available
        if len(ids) < 2 or not available:
            return None
        payload = {
            "model": model, "temperature": 0, "max_tokens": 120,
            "messages": [
                {"role": "system", "content": (
                    "从已排序的合规候选中为学习活动挑一个材料。优先第一项。"
                    '只返回 JSON 对象 {"resource_id":"候选号"}。'
                )},
                {"role": "user", "content": json.dumps({
                    "activity_kind": kind, "indicator_id": indicator_id, "ranked_candidates": ids,
                }, ensure_ascii=False)},
            ],
        }
        request = Request(endpoint, data=json.dumps(payload).encode(), headers=headers)
        try:
            with opener.open(request, timeout=3) as response:
                reply = json.load(response)["choices"][0]["message"]["content"]
            rid = json.loads(reply)["resource_id"]
            return rid if isinstance(rid, str) and rid in ids else None
        except OSError:
            available = False
            logger.warning("本地模型不可用，本批次使用规则模板。")
        except (ValueError, KeyError, IndexError, TypeError):
            pass
        return None

    return select
