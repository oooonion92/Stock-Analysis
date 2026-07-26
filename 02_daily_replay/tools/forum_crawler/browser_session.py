from __future__ import annotations

import atexit
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from playwright.sync_api import BrowserContext, Playwright, sync_playwright


_playwright: Playwright | None = None
_context: BrowserContext | None = None


class _ReusedChromium:
    def __init__(self, context: BrowserContext | None) -> None:
        self._context = context

    def launch_persistent_context(self, **kwargs) -> BrowserContext:
        if self._context is not None:
            return self._context
        return get_persistent_context(
            Path(str(kwargs["user_data_dir"])),
            str(kwargs["executable_path"]),
            bool(kwargs.get("headless", True)),
        )


class _ReusedPlaywright:
    def __init__(self, context: BrowserContext | None) -> None:
        self.chromium = _ReusedChromium(context)


@contextmanager
def playwright_for_context(context: BrowserContext | None) -> Iterator[tuple[object, bool]]:
    """Reuse one persistent browser, including when callers do not pass a context."""
    yield _ReusedPlaywright(context), False


def get_persistent_context(profile_dir: Path, executable_path: str, headless: bool) -> BrowserContext:
    global _playwright, _context
    if _context is not None:
        return _context

    _playwright = sync_playwright().start()
    _context = _playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        executable_path=executable_path,
        headless=headless,
        viewport={"width": 1400, "height": 950},
        locale="zh-CN",
    )
    return _context


def close_persistent_context() -> None:
    global _playwright, _context
    if _context is not None:
        _context.close()
        _context = None
    if _playwright is not None:
        _playwright.stop()
        _playwright = None


atexit.register(close_persistent_context)
