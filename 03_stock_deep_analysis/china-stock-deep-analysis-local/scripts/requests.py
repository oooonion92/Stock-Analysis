"""Tiny subset of `requests` used by this skill, built on stdlib urllib.

This avoids external dependency installation in restricted environments.
"""

from __future__ import annotations

import json as _json
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class HTTPError(RuntimeError):
    pass


@dataclass
class Response:
    _raw: bytes
    status_code: int
    encoding: Optional[str] = None

    @property
    def text(self) -> str:
        enc = self.encoding or "utf-8"
        return self._raw.decode(enc, errors="replace")

    def json(self) -> Any:
        return _json.loads(self.text)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise HTTPError(f"HTTP {self.status_code}")


def get(url: str, *, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None, timeout: int = 12) -> Response:
    if params:
        query = urlencode(params)
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{query}"
    req = Request(url, headers=headers or {}, method="GET")
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        status = getattr(resp, "status", 200) or 200
        return Response(_raw=raw, status_code=int(status))
