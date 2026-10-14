"""Source selection between the keyed JSON API and the RSC scraper.

Environment switches:

* ``AA_API_KEY``   — free-tier API key (absent by default → scraper only).
* ``AA_SOURCE``    — ``auto`` (default) | ``api`` | ``rsc``.
* ``AA_API_TTL``   — API cache TTL in seconds (default 6 h, see :mod:`aa_mcp.api`).

Selection is deliberately fail-open: if the API is selected but the key is
missing (``AA_SOURCE=api``), or the last probe returned 401/403, we downgrade to
RSC and log exactly once — never spam, never hard-fail a tool.  The probe result
is cached for the life of the process.
"""

from __future__ import annotations

import logging
import os
import threading

from .fetch import AAFetchError

log = logging.getLogger("aa_mcp.source")

_MODES = ("auto", "api", "rsc")

_lock = threading.Lock()
_probe_cache: tuple[bool, str] | None = None
_downgrade_logged = False

__all__ = ["api_key", "active_source", "probe_api", "source_label"]


def api_key() -> str | None:
    """Return ``AA_API_KEY`` (empty/whitespace → ``None``)."""
    value = (os.environ.get("AA_API_KEY") or "").strip()
    return value or None


def _mode() -> str:
    mode = (os.environ.get("AA_SOURCE") or "auto").strip().lower()
    return mode if mode in _MODES else "auto"


def probe_api(refresh: bool = False) -> tuple[bool, str]:
    """Return ``(usable, reason)`` for the API key, cached per process."""
    global _probe_cache
    if _probe_cache is not None:
        return _probe_cache
    with _lock:
        if _probe_cache is not None:
            return _probe_cache
        from . import api

        if api_key() is None:
            _probe_cache = (False, "no-key")
            return _probe_cache
        try:
            api.fetch_models_free(refresh=refresh)
            _probe_cache = (True, "ok")
        except api.ApiAuthError as exc:
            _probe_cache = (False, f"auth:{getattr(exc, 'status', 401)}")
        except AAFetchError as exc:
            _probe_cache = (False, f"error:{exc}")
        except Exception as exc:  # noqa: BLE001 - probe must never escape
            _probe_cache = (False, f"error:{exc}")
        return _probe_cache


def _note_downgrade(reason: str) -> None:
    global _downgrade_logged
    if _downgrade_logged:
        return
    _downgrade_logged = True
    if reason.startswith("auth"):
        log.warning(
            "AA API key rejected (%s); falling back to RSC scraping "
            "(use AA_SOURCE=rsc to silence)",
            reason,
        )
    else:
        log.warning("AA API unavailable (%s); falling back to RSC scraping", reason)


def active_source(refresh: bool = False) -> str:
    """Return the source to use: ``"api"`` or ``"rsc"``."""
    mode = _mode()
    if mode == "rsc":
        return "rsc"
    if api_key() is None:
        if mode == "api":
            raise AAFetchError(
                "AA_SOURCE=api requires an AA_API_KEY",
                hint="set AA_API_KEY or use AA_SOURCE=rsc",
            )
        return "rsc"
    usable, reason = probe_api(refresh=refresh)
    if usable:
        return "api"
    _note_downgrade(reason)
    return "rsc"


def source_label() -> str:
    """Provenance label for tool headers: ``"aa:api"`` or ``"aa:rsc"``."""
    try:
        return "aa:api" if active_source() == "api" else "aa:rsc"
    except AAFetchError:
        return "aa:rsc"
