import base64
import json
from typing import Any
from typing import Dict
from typing import List
from typing import Optional


FLASH_COOKIE_NAME = "moyza_flash"


def _encode(messages: List[Dict[str, Any]]) -> str:
    raw = json.dumps(messages, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_flash(raw_value: Optional[str]) -> List[Dict[str, Any]]:
    if not raw_value:
        return []

    try:
        decoded = base64.urlsafe_b64decode(raw_value.encode("ascii")).decode("utf-8")
        data = json.loads(decoded)
        if isinstance(data, list):
            return [m for m in data if isinstance(m, dict)]
    except Exception:
        return []

    return []


def set_flash(response, category: str, message: str) -> None:
    """Store a one-time message in a cookie to be shown on the next page load.

    Categories: success | error | warning
    """

    payload = [{"category": category, "message": message}]
    response.set_cookie(
        key=FLASH_COOKIE_NAME,
        value=_encode(payload),
        max_age=60,
        httponly=True,
        samesite="lax",
        path="/",
    )
