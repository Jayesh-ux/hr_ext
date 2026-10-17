"""Optional LLM intent override (plain urllib — no SDK dependency).

When a model endpoint is configured in HR Ext Settings, the chat API calls
``classify(text, endpoint, api_key, model)`` before falling back to the
rule-based parser. The endpoint is called with a tiny prompt and must return
JSON. Any failure (network, bad JSON, missing config) returns ``None`` so the
conversational layer degrades gracefully to the deterministic parser.

The default response format expected:
    {"action": "<leave_apply|leave_balance|attendance_status|expense_claim|salary_information|help>"}
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Optional

# The ONLY actions a configured LLM may ever select. The model performs intent
# *classification*, never tool-calling: it returns a label, and the deterministic
# dispatcher (which separately re-derives parameters) runs the action. Any label
# outside this allowlist -- including prompt-injection attempts such as
# "delete_user" or "raw_sql" -- is rejected and the rule-based parser is used.
VALID_ACTIONS = {"leave_apply", "leave_balance", "attendance_status", "expense_claim", "salary_information", "help"}

_SYSTEM_PROMPT = (
    "You classify employee HR chat messages into one action: "
    "leave_apply, leave_balance, attendance_status, expense_claim, "
    "salary_information, or help. Reply with one JSON object only: "
    '{"action": "..."}'
)


def validate_action(action) -> Optional[str]:
    """Return ``action`` only if it is exactly one of :data:`VALID_ACTIONS`.

    Guards against a model returning an unknown/extra label (typos, prompt
    injection, free text). Anything else returns ``None`` so callers fall back
    to the rule-based parser.
    """
    if isinstance(action, str) and action in VALID_ACTIONS:
        return action
    return None


def classify(
    text: str,
    endpoint: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    timeout: float = 10.0,
) -> Optional[str]:
    """Ask a configured LLM endpoint to classify intent. Returns an action or None."""
    if not endpoint:
        return None
    api_key = api_key or os.environ.get("HR_EXT_LLM_API_KEY")
    model = model or os.environ.get("HR_EXT_LLM_MODEL")
    payload = {
        "model": model,
        "temperature": 0.0,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
    }
    headers = {"Content-Type": "application/json", "User-Agent": "hr_ext/0.1"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (intended network call)
            raw = resp.read().decode("utf-8", "replace")
        data = json.loads(raw)
        content = data.get("choices", [{}])[0].get("message", {}).get("content") or data.get("action") or ""
        match = json.loads(content) if content.strip().startswith("{") else None
        if match:
            validated = validate_action(match.get("action"))
            if validated:
                return validated
        return validate_action(data.get("action"))
    except (ValueError, KeyError, TypeError, OSError, urllib.error.URLError, urllib.error.HTTPError):
        return None