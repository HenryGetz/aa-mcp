"""MCP server for artificialanalysis.ai — tools, resources, prompts, ``main()``.

This is the integration point: it wires the frozen modules (:mod:`fetch`,
:mod:`loaders`, :mod:`catalog`, :mod:`normalize`, :mod:`select`, :mod:`render`)
into the twelve agent-facing tools and renders every answer as
compact markdown. Nothing here talks to the network at import time; data is
only loaded inside tool calls, and stdout carries nothing but the MCP protocol.
"""

from __future__ import annotations

import dataclasses
import difflib
import functools
import inspect
import json
import logging
import math
import os
import re
import sys
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import (
    __version__,
    catalog,
    fetch,
    flight,
    loaders,
    normalize,
    reference,
    render,
    select,
)
from .fetch import AAFetchError
from .normalize import Model

log = logging.getLogger("aa_mcp.server")

_OFFLINE_ON = ("1", "true", "yes", "on")

# --------------------------------------------------------------------------- #
# response / input bounds (adversarial A14/A36/A37)
# --------------------------------------------------------------------------- #

#: hard ceiling for one tool reply; tables truncate row-wise, other payloads
#: shrink their records (the backstop below cuts as a last resort).
MAX_RESPONSE = 200_000
#: characters of caller-supplied text echoed back inside an error message
MAX_ECHO = 60
#: default cap for a string argument (names, queries); `fields`-like lists get more
MAX_STR_ARG = 256
MAX_LIST_ARG = 2000
#: characters a raw JSON string value may contribute to `aa_raw`
MAX_RAW_STR = 400

_STR_ARG_LIMITS = {
    "fields": MAX_LIST_ARG,
    "sections": MAX_LIST_ARG,
    "metrics": MAX_LIST_ARG,
}

#: output sanitiser: NUL and lone surrogates never reach the MCP transport
_UNSAFE_OUT = {c: "\ufffd" for c in range(0xD800, 0xE000)}
_UNSAFE_OUT[0] = ""


def _q(value: Any, limit: int = MAX_ECHO) -> str:
    """A bounded, quoted echo of caller input for an error message.

    Error replies must never scale with an unvalidated argument (A36) and must
    never re-emit the exact string that was rejected.
    """
    text = str(value)
    if len(text) <= limit:
        return repr(text)
    return f"{text[:limit]!r}… (+{len(text) - limit} more chars)"


def _unsafe_char(text: str) -> str | None:
    """Describe the first control char / lone surrogate in ``text``."""
    for ch in text:
        code = ord(ch)
        if 0xD800 <= code <= 0xDFFF:
            return f"lone surrogate U+{code:04X}"
        if code == 0x7F or (code < 0x20 and ch not in "\t\n\r"):
            return f"control character U+{code:04X}"
    return None


def _check_arg(name: str, value: Any) -> None:
    """Reject hostile/degenerate values for one tool argument (A14/A2)."""
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(
                f"{name}={value!r} is not a finite number — NaN/Infinity are not "
                "valid filters or counts"
            )
        return
    limit = _STR_ARG_LIMITS.get(name, MAX_STR_ARG)
    if isinstance(value, str):
        texts: list[str] = [value]
    elif isinstance(value, (list, tuple, set)):
        texts = [str(item) for item in value]
    else:
        return
    for text in texts:
        bad = _unsafe_char(text)
        if bad is not None:
            raise ValueError(
                f"{name} contains a {bad}, which cannot be passed to this tool — "
                "strip control characters / lone surrogates and retry"
            )
        if len(text) > limit:
            raise ValueError(
                f"{name} is {len(text)} characters (limit {limit}) — pass a shorter "
                "value (aa_reference topic=fields lists the accepted names)"
            )


def _validate_args(fn: Callable, args: tuple, kwargs: dict) -> None:
    """Validate every bound argument of a tool call at the client boundary."""
    try:
        bound = inspect.signature(fn).bind(*args, **kwargs)
    except TypeError:  # pragma: no cover - the MCP layer validates the schema
        return
    bound.apply_defaults()
    for name, value in bound.arguments.items():
        _check_arg(name, value)


def _bounded(text: str) -> str:
    """Final reply sanitiser: strip un-serialisable code points, cap the size."""
    if any(ch in text for ch in ("\ud800", "\x00")):
        text = text.translate(_UNSAFE_OUT)
    if len(text) > MAX_RESPONSE:
        text = (text[:MAX_RESPONSE]
                + f"\n— response truncated at {MAX_RESPONSE // 1000} kB "
                  f"(original {len(text)} chars); narrow the request (`top`, `fields`, "
                  "`query`) to see the rest")
    return text


# --------------------------------------------------------------------------- #
# per-call caches (refresh only what a call needs — audit M)
# --------------------------------------------------------------------------- #

_CALL = threading.local()


def _call_cache() -> dict:
    """A per-thread, per-tool-call cache (the MCP server runs sync tools on a pool)."""
    cache = getattr(_CALL, "cache", None)
    if cache is None:
        cache = {}
        _CALL.cache = cache
    return cache


def _get(url: str, name: str, refresh: bool = False, **kwargs) -> fetch.Fetched:
    """``fetch.get`` deduplicated per tool call (same name -> one download)."""
    cache = _call_cache()
    key = ("get", name, bool(refresh))
    if key not in cache:
        cache[key] = fetch.get(url, name, refresh=refresh, **kwargs)
    _fetched(name)
    return cache[key]


def _cache_file(name: str):
    """The cache file backing ``name`` (first existing extension), if any."""
    for ext in (".rsc", ".html", ".json"):
        path = fetch.cache_dir() / f"{name}{ext}"
        try:
            if path.exists():
                return path
        except OSError:  # pragma: no cover - defensive
            continue
    return None


_SHAPE_MARKERS = ("no JSON array of dicts containing keys",
                  "no leaderboard row array in payload",
                  "was missing from the embedded",
                  "unexpected payload",
                  "payload format changed",
                  "no model records")


def _shape_changed(message: str) -> bool:
    """Whether a parse failure means the payload's shape changed (not a bad cache)."""
    return any(marker in message for marker in _SHAPE_MARKERS)


def _cache_aware(message: str, name: str) -> str:
    """Append cache-file guidance to a parse/load failure (A22/A25/A26).

    Distinguishes a missing/unreadable cache (refresh helps) from a payload whose
    shape changed (refresh refetches the same page and fails the same way — the
    parser must be updated). ``AA_OFFLINE=1`` never suggests refresh.
    """
    head = message.split("\n", 1)[0]
    path = _cache_file(name)
    offline = fetch._offline()
    exists = path is not None and path.exists() and path.stat().st_size > 0
    if _shape_changed(message):
        if offline:
            return (
                f"{head}\n— AA_OFFLINE=1: the saved payload at {path} has a shape this "
                "parser does not understand; refresh is unavailable offline — the "
                "parser in loaders/normalize must be updated"
            )
        if exists:
            return (
                f"{head}\n— the cached payload at {path} exists but its shape changed "
                "(this is not a missing or truncated download); refresh=true refetches "
                "the same page and fails the same way — the parser in "
                "loaders/normalize must be updated for the new shape"
            )
        return (
            f"{head}\n— the live payload's shape changed; refresh=true fetches the "
            "same page and fails the same way — the parser in loaders/normalize must "
            "be updated for the new shape"
        )
    if "refresh=true" in message:
        if not offline:
            return message
        kept = [line for line in message.splitlines()
                if "refresh" not in line.lower()]
        return "\n".join(kept) + (
            "\n— AA_OFFLINE=1: refresh is unavailable; fix the cached payload at "
            f"{path} by hand (or unset AA_OFFLINE for a live fetch)")
    if path is not None:
        if offline:
            return (
                f"{message}\n"
                f"— AA_OFFLINE=1: the cached payload {path} is missing or unreadable "
                "and no network fetch is allowed; save a browser-rendered copy there "
                "or unset AA_OFFLINE to download it"
            )
        return (
            f"{message}\n"
            f"— cached payload {path} is missing or unreadable: retry with "
            "refresh=true to re-download it, or delete the file and retry; if you "
            "have a good copy saved there, AA_OFFLINE=1 uses it without a network call"
        )
    if offline:
        return (f"{message}\n— AA_OFFLINE=1: no cached payload for {name!r} under "
                f"{fetch.cache_dir()} and no network fetch is allowed; save a "
                "browser-rendered copy there or unset AA_OFFLINE")
    return (
        f"{message}\n"
        f"— no cached payload for {name!r} under {fetch.cache_dir()}: retry with "
        "refresh=true to download it, or save a browser-rendered copy there and set "
        "AA_OFFLINE=1"
    )


def _load(name: str, fn: Callable, *args, refresh: bool = False, **kwargs):
    """Run a loader call, converting a payload failure into cache-aware text.

    The ``name`` is recorded for this call so a second consumer of the same page
    reads the copy the first one just downloaded (audit M).
    """
    try:
        result = fn(*args, refresh=refresh, **kwargs)
    except (LookupError, ValueError) as exc:
        raise ValueError(_cache_aware(str(exc), name)) from None
    _fetched(name)
    return result


def _fetched(name: str) -> None:
    """Record that ``name`` has been fetched during this tool call."""
    _call_cache().setdefault("fetched", set()).add(name)


def _already_fetched(name: str) -> bool:
    return name in _call_cache().get("fetched", ())


def _lb_rows(refresh: bool = False) -> list[Model]:
    """The leaderboard rows for this call — fetched at most once (audit M)."""
    cache = _call_cache()
    key = ("lb", bool(refresh))
    if key not in cache:
        name = _lb_cache()
        cache[key] = _load(name, loaders.leaderboard, refresh=refresh)
    return cache[key]


def _home_rows(refresh: bool = False) -> dict[str, list[dict]]:
    """The homepage panels for this call — fetched at most once (audit M)."""
    cache = _call_cache()
    key = ("home", bool(refresh))
    if key not in cache:
        cache[key] = _load("home", loaders.home_boards, refresh=refresh)
    return cache[key]


def _metric_value(model: Model, key: str) -> float | None:
    """The numeric value of ``key`` for ``model`` (``None`` when absent)."""
    value = select.lookup(model, key)
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


#: metrics AA publishes on **two** surfaces: the leaderboard snapshot
#: (``medianOutputTokensPerSecond`` / ``medianTimeToFirstTokenSeconds`` / …) and the
#: first-party model page (``timescaleData.medianOutputSpeed`` /
#: ``medianTimeToFirstChunk`` / ``timeToFirstAnswerToken`` / ``endToEndResponseTime``).
#: The model-page value wins deterministically so one metric never renders two
#: numbers for the same call (wave G, G1).
_DUAL_SOURCE_KEYS = ("tps", "ttft", "ttfa", "e2e")


def _value_of(model: Model, score_key: str) -> float | None:
    """``score / $/task`` for ``model``, computed locally (never memo-mutating)."""
    score = _metric_value(model, score_key)
    cost = model.cost_per_task
    if score is None or cost is None or cost <= 0:
        return None
    return score / cost


def _value_pairs(models: Sequence[Model],
                 score_key: str) -> list[tuple[Model, float | None]]:
    """``[(model, score/cost)]``, using ``select.value_pairs`` when available.

    ``select`` (another agent's module) is free to expose the functional API or
    not; the local computation below is authoritative either way and never
    writes derived values onto shared models (audit H3 / wave A A7).
    """
    fn = getattr(select, "value_pairs", None)
    if callable(fn):
        try:
            raw = list(fn(list(models), score_key=score_key))
        except Exception:
            raw = []
        pairs: list[tuple[Model, float | None]] = []
        for item in raw:
            if (isinstance(item, (tuple, list)) and len(item) == 2
                    and isinstance(item[0], Model)):
                pairs.append((item[0], item[1]))
            else:
                pairs = []
                break
        if pairs:
            return pairs
    return [(m, _value_of(m, score_key)) for m in models]


def _rich_needed(*, refresh: bool = False, sort_key: str | None = None,
                 fields: Any = (), benchmark_key: str | None = None) -> bool:
    """True when the rich overlay is the only source for a requested metric.

    The plain leaderboard already carries the leaderboard metrics (intelligence,
    cost, speed, omniscience…); the 699-model rich dataset only matters for
    chart-set/capability/Elo fields. Loading it otherwise costs 6 model-page
    probes per call (audit M/B6).

    A name resolves through the rankable index first (G1): an alias that only
    exists as a *rankable* spelling (``time_to_first_token``) is the same key as
    the canonical one, so it must not be mistaken for "absent from the
    leaderboard" and silently re-source the whole reply.
    """
    lb = _lb_rows(refresh)
    keys = [k for k in (sort_key, benchmark_key) if k]
    for name in _split(fields):
        if name.strip().lower() in ("all", "*", "everything", "benchmarks"):
            return True
        rank = _rankable(name)
        if rank is not None and str(getattr(rank, "key", "")):
            keys.append(str(rank.key))
            continue
        try:
            keys.append(_metric_key(name, "field"))
        except ValueError:
            # a name that resolves to nothing carries no data, so it must not
            # pull the rich overlay in and re-source the whole reply (G1/G6)
            continue
    for key in keys:
        if any(select.lookup(m, key) is not None for m in lb):
            continue
        return True
    return False


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #


def _split(csv: Any) -> list[str]:
    """Split a comma string, a JSON-ish array string, or an actual list.

    ``fields``/``sections``/``metrics`` accept ``"a,b"``, ``'["a","b"]'`` and
    ``["a", "b"]`` so a caller never has to guess the parameter type.
    """
    if csv is None:
        return []
    if isinstance(csv, (list, tuple, set)):
        return [str(part).strip() for part in csv if str(part).strip()]
    text = str(csv).strip()
    if not text:
        return []
    if text[0] in "[(":
        try:
            seq = json.loads(text.replace("'", '"'))
        except ValueError:
            seq = None
        if isinstance(seq, (list, tuple)):
            return [str(part).strip() for part in seq if str(part).strip()]
    return [part.strip() for part in text.split(",") if part.strip()]


def _txt(value: Any) -> str:
    return "-" if value in (None, "") else str(value)


def _fmt(key: str, value: Any) -> str:
    return catalog.format_value(key, value)


#: ``"elo"`` is a field alias for an Elo-kind metric, so ``catalog.format_value``
#: applies catalog's single half-away-from-zero Elo rule to any number handed to it.
_ELO_KEY = "elo"


def _elo_int(value: Any) -> str:
    """An Elo value or confidence-interval bound, rendered like catalog Elo.

    ``catalog.format_value`` rounds Elo half-away-from-zero to match AA's own
    rendered strings; a bare ``:.0f`` rounds half-to-even, so the same value could
    render one lower in these keyless cells than in a metric column.  Confidence-
    interval bounds have no published ground truth — they follow the Elo convention
    so one value never differs by one between tools (round-2 follow-up).
    """
    return catalog.format_value(_ELO_KEY, value)


def _elo_delta(delta: float) -> str:
    """A signed Elo delta, rounded like an Elo value (half away from zero).

    ``format_value`` carries no sign, so the sign is re-applied around the same
    rule: a diff cell must not disagree with a value cell by one (round-2 follow-up).
    """
    if not math.isfinite(delta):
        return f"{delta:+,.0f}"
    magnitude = int(_elo_int(abs(delta)))
    return f"{magnitude if delta >= 0 else -magnitude:+,}"


def _discount(value: Any) -> str:
    """Cache-read discount as a percentage; AA reports it either as 0-1 or 0-100."""
    if value is None:
        return "-"
    v = float(value)
    return f"{v:.0f}%" if v > 1 else f"{v * 100:.0f}%"


_keyed_env_warned = False


def _warn_keyed_env_once() -> None:
    """One-time notice that ``AA_API_KEY``/``AA_SOURCE`` are no longer read."""
    global _keyed_env_warned
    if _keyed_env_warned:
        return
    _keyed_env_warned = True
    stale = [name for name in ("AA_API_KEY", "AA_SOURCE") if os.environ.get(name)]
    if stale:
        log.warning(
            "%s set, but the keyed JSON-API backend has been removed; ignoring "
            "it and using the keyless RSC source",
            ", ".join(stale),
        )


def _source_key() -> str:
    """Provenance key for tool headers — always ``"rsc"`` (keyless source)."""
    _warn_keyed_env_once()
    return "rsc"


def _cache_ttl() -> int:
    """Cache TTL in seconds (``AA_CACHE_TTL``, default 3600)."""
    raw = os.environ.get("AA_CACHE_TTL")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return 3600


def _fresh(name: str) -> tuple[float | None, bool]:
    """``(as_of, stale)`` for a cache entry.

    A successful download resets the file mtime, so an entry whose age exceeds
    the TTL was served from cache after the network failed — i.e. stale.
    """
    try:
        age = fetch.cache_age(name)
    except (OSError, ValueError):  # pragma: no cover - defensive (unsafe name)
        return None, False
    if age is None:
        return None, False
    offline = (os.environ.get("AA_OFFLINE") or "").strip().lower() in _OFFLINE_ON
    return time.time() - age, offline or age > _cache_ttl()


def _lb_cache() -> str:
    """Cache name for the leaderboard — always the RSC payload."""
    return "leaderboard"


def _header(
    total: int | None = None,
    shown: int = 0,
    note: str = "",
    *,
    count: str | None = None,
    name: str = "",
    source_label: str | None = None,
) -> str:
    """One-line header; delegates the format to :func:`render.header`.

    Adds the cache state on top: ``count`` overrides the ``shown/total``
    left-hand text, and a cache entry older than its TTL (or ``AA_OFFLINE=1``)
    is labelled ``stale:`` rather than dated. ``render.header`` is the single
    renderer for this shape (B9).
    """
    as_of: float | None = None
    if name:
        as_of, stale = _fresh(name)
        if stale and as_of is not None:
            note = (f"{note} · stale: {render.ago(as_of)}").strip(" ·")
            as_of = None
    body = count if count is not None else (
        str(shown) if total is None else f"{shown}/{total}")
    left = f"{body} · {note}" if note else body
    return render.header(None, 0, count=left.strip(" ·"),
                         source=source_label or _source_key(), as_of=as_of)


def _close(query: str, pool: Iterable[str], n: int = 5) -> list[str]:
    pool = list(dict.fromkeys(pool))
    hits = difflib.get_close_matches(query, pool, n=n, cutoff=0.35)
    if not hits:
        ql = query.lower()
        hits = [p for p in pool if ql in p.lower()][:n]
    return hits


def _close_names(name: str, pool: Iterable[str], n: int = 3) -> list[str]:
    """Tight "did you mean" list for an invalid field/sort name (no reference dump).

    A loose cutoff turns ``nonsense`` into five unrelated column names; the error
    must instead name a handful of plausible keys inline and stop.
    """
    pool = list(dict.fromkeys(pool))
    hits = difflib.get_close_matches(name, pool, n=n, cutoff=0.55)
    if not hits:
        low = str(name).lower()
        hits = [p for p in pool if low and low in p.lower()][:n]
    return hits


#: normalized spellings that catalog.py does not carry (the capability-index
#: vocabulary lives in ``catalog._CAPABILITY_ALIASES``; these are the remaining
#: loose phrasings, kept so an agent's own wording resolves)
_EXTRA_ALIASES: dict[str, str] = {
    "legalcapability": "capabilities.legal",
    "medicalindex": "capabilities.healthcareAndMedical",
    "healthcareindex": "capabilities.healthcareAndMedical",
    "financeindex": "capabilities.financeAndAccounting",
    "strategyindex": "capabilities.strategyAndOps",
    "capengineer": "capabilities.engineering",
    "capeconomic": "capabilities.economics",
}


def _norm_alias(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def _metric_key(name: str, what: str = "metric") -> str:
    m = catalog.metric(name)
    if m is not None:
        return m.key
    b = catalog.benchmark(name)
    if b is not None:
        return b.key
    extra = _EXTRA_ALIASES.get(_norm_alias(name))
    if extra is not None:
        return extra
    pool = list(catalog.METRICS) + list(catalog.FIELD_ALIASES) + list(_EXTRA_ALIASES)
    near = ", ".join(_close_names(name, pool)) or "none"
    examples = "intelligence, cost_per_task, price_out, tps, ttft, context_tokens"
    raise ValueError(
        f"unknown {what} {_q(name)} — closest: {near}\n"
        f"— {what}s accept metric/benchmark keys (e.g. {examples})"
    )


def _metric_label(key: str) -> str:
    """Display label for a resolvable key (metric, benchmark or raw field).

    ``unit == "mixed"`` breakdown keys (e.g. ``briefcaseBreakdown``) live in
    ``catalog.BENCHMARKS`` but deliberately not in ``METRICS``; label them from
    there instead of raising ``AttributeError`` (audit M/B4).
    """
    metric = catalog.metric(key)
    if metric is not None:
        return metric.label
    bench = catalog.BENCHMARKS.get(key)
    if bench is not None:
        return bench.label
    return key.replace("_", " ").title()


def _lower_is_better(key: str) -> bool:
    """True when ``catalog`` models ``key`` as lower-is-better (audit H2/B2)."""
    fn = getattr(select, "better_desc", None)
    if callable(fn):
        try:
            return not bool(fn(key))
        except Exception as exc:
            log.debug("select.better_desc(%r) failed (%s); using catalog", key, exc)
    metric = catalog.metric(key)
    return bool(metric is not None and metric.better == "low")


def _ambiguous_text(exc: select.AmbiguousError) -> str:
    """Candidate table for an ambiguous query, with a variant discriminator.

    Several variants of one release can share a slug (or a bare slug can select
    one of them while its *name* is unique), so "re-run with the slug" is a loop:
    the table prints the variant beside the slug and the hint names the Model
    value that actually resolves.
    """
    candidates = list(exc.candidates[:8])
    slugs = [m.slug for m in candidates]
    duplicates = len(set(slugs)) != len(slugs)
    example = candidates[0].name if candidates else "GPT-6.2 Astra (Max)"
    if duplicates:
        rows = [[m.name, _txt(m.creator), _variant_label(m) or "-", m.slug]
                for m in candidates]
        table = render.table(["Model", "Creator", "Variant", "Slug"], rows)
    else:
        rows = [[m.name, _txt(m.creator), m.slug] for m in candidates]
        table = render.table(["Model", "Creator", "Slug"], rows)
    return (
        f"{exc}\n{table}\n"
        f"— re-run with the full Model value, e.g. `{_safe_text(example, 60)}` "
        "— a bare slug can name several variants"
    )


def _fetch_text(exc: AAFetchError) -> str:
    """Fetch failure plus the loader's hint and the cache/refresh recovery path."""
    hint = getattr(exc, "hint", "")
    text = f"{exc}\n— {hint}" if hint else str(exc)
    if _shape_changed(text):
        head = text.split("\n", 1)[0]
        if fetch._offline():
            return (f"{head}\n— AA_OFFLINE=1: the saved payload has a shape this "
                    "parser does not understand; refresh is unavailable offline — "
                    "the parser in loaders/normalize must be updated")
        return (f"{head}\n— the payload's shape changed; refresh=true fetches the "
                "same page and fails the same way — the parser in loaders/normalize "
                "must be updated for the new shape")
    if fetch._offline():
        kept = [line for line in text.splitlines() if "refresh" not in line.lower()]
        return "\n".join(kept) + (
            "\n— AA_OFFLINE=1: refresh is unavailable; check the cached file under "
            f"{fetch.cache_dir()} or unset AA_OFFLINE for a live fetch")
    if "refresh=true" not in text:
        text += ("\n— retry with refresh=true to re-download it, or serve it from a "
                 "warm cache (AA_OFFLINE=1 uses an existing file without a network call)")
    return text


class _InfoAnswer(ValueError):
    """A complete informational answer — delivered as the reply, not an error.

    Exit-code rule (also documented in the CLI help): a call that *answers* the
    question with "AA publishes this only through its paid API" / "AA no longer
    publishes this" is a success (exit 0); only a genuine input error or data the
    caller must act on is non-zero.
    """


def _tool(fn):
    """Deliver actionable error text to the client as an MCP ``ToolError``.

    ``mcp`` 2.x hides the message of an uncaught exception behind a generic
    "Error executing tool ..." wrapper, so every expected failure is re-raised
    as :class:`ToolError` with its own text preserved. Arguments are validated
    and replies are bounded/neutralized here, at the single client boundary.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        _call_cache().clear()
        try:
            _validate_args(fn, args, kwargs)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        try:
            return _bounded(fn(*args, **kwargs))
        except _InfoAnswer as exc:
            return _bounded(str(exc))
        except ToolError:
            raise
        except AAFetchError as exc:
            raise ToolError(_fetch_text(exc)) from exc
        except select.AmbiguousError as exc:
            raise ToolError(_ambiguous_text(exc)) from exc
        except LookupError as exc:
            raise ToolError(_cache_aware(str(exc), _primary_cache(fn.__name__))) from exc
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        except Exception as exc:
            raise ToolError(
                f"{fn.__name__} failed: {type(exc).__name__}: {exc}\n"
                "— retry once; if it persists, report the tool name and arguments"
            ) from exc

    return wrapper


def _primary_cache(tool: str) -> str:
    """The cache entry a tool reads first, for cache-aware error text."""
    if tool in ("aa_media",):
        return "home"
    if tool in ("aa_providers",):
        return "providers_board"
    if tool in ("aa_benchmarks", "aa_benchmark_leaderboard"):
        return "leaderboard"
    return _lb_cache()



#: tokens that ask a ``fields=``/``metrics=`` list for *every* column the surface has
_ALL_FIELD_TOKENS = {"all", "*", "everything", "every", "allfields"}


def _is_wildcard_field(name: str) -> bool:
    text = str(name).strip()
    return text in ("*", "**") or _norm_alias(text) in _ALL_FIELD_TOKENS


def _ratio_key_for(name: str) -> str | None:
    """The column key for a ``score/$`` alias (``intel/$``), else ``None``."""
    try:
        ratio = _ratio_metric(name)
    except Exception:  # a malformed alias must never break column selection
        return None
    return ratio[0] if ratio else None


def _ratio_columns(names: Sequence[str]) -> list[tuple[str, str]]:
    """``[(key, label)]`` for every ratio alias in a ``fields=`` list."""
    out: list[tuple[str, str]] = []
    for name in names:
        try:
            ratio = _ratio_metric(name)
        except Exception:
            continue
        if ratio:
            out.append(ratio)
    return out


def _fields_trim(fields: Any) -> bool:
    """Whether an explicit ``fields`` argument should still drop all-null columns.

    A named list is rendered in full — with ``-`` for nulls — so a caller can tell
    "no data" from "wrong field name". A wildcard (``all``/``*``) instead asks for
    everything the surface *can* render, so a column that is empty for every shown
    row is dropped exactly as it is for the default set (audit round 2, L5).
    """
    names = _split(fields)
    return not names or all(_is_wildcard_field(n) for n in names)


def _col_label(key: str) -> str:
    metric = catalog.metric(key)
    return metric.label if metric else key.replace("_", " ").title()


#: identity field names a ``fields=`` list may use, mapped to the column label the
#: surface renders them under. Identity is always resolvable from the record, so a
#: requested identity field must never blank a column or be reported as "no data"
#: (G2). A name whose label the surface does not carry stays an unknown field.
_IDENTITY_FIELD_LABELS = {
    "model": "Model", "name": "Model", "modelname": "Model",
    "slug": "Slug", "modelslug": "Slug",
    "host": "Host", "creator": "Creator", "benchmark": "Benchmark",
}


def _identity_key(name: str, surface: Sequence[tuple[str, str]],
                  identity_map: Mapping[str, str] | None = None) -> str | None:
    """The surface's own column key for an identity field name (``None`` if absent).

    ``identity_map`` is the surface's explicit name → column-key map (used where a
    name has no matching column label, e.g. ``slug`` on a providers table whose
    identity column is ``model_slug``); otherwise the label is matched.
    """
    norm = _norm_alias(name)
    if identity_map and norm in identity_map:
        return identity_map[norm]
    label = _IDENTITY_FIELD_LABELS.get(norm)
    if label is None:
        return None
    for key, col_label in surface:
        if str(col_label).lower() == label.lower():
            return str(key)
    return None


def _cols(default: Sequence[tuple[str, str]], fields: Any,
          extra: Iterable[str] = (),
          identity: Sequence[tuple[str, str]] = (),
          unknown: list[str] | None = None,
          identity_map: Mapping[str, str] | None = None) -> list[tuple[str, str]]:
    """Column list from ``fields`` (metric aliases, plus any non-metric ``extra``).

    ``identity`` columns (Model/Slug/Host/...) are always rendered first, even
    when ``fields`` names only metrics, so a requested table is never anonymous —
    and an identity name (``model``/``name``/``slug``/``host``/``creator``/
    ``benchmark``) resolves to the surface's own identity column rather than to a
    metric key the rows cannot fill (G2).

    A wildcard token (``all``/``*``/``everything``) selects the whole surface:
    its default columns plus every ``extra`` column it can render.

    A name that resolves to nothing is appended to ``unknown`` (when given) and
    ignored, so a long ``fields=`` list renders what resolves instead of aborting
    the whole call (G6); with no ``unknown`` sink the name raises, as before.
    """
    if not fields:
        return list(default)
    extra = set(extra)
    names = _split(fields)
    if any(_is_wildcard_field(n) for n in names):
        out = list(default)
        keys = {k for k, _ in out}
        for e in extra:
            if e in keys:
                continue
            keys.add(e)
            out.append((e, _col_label(e)))
        prefix = [(k, label) for k, label in identity if k not in keys]
        return prefix + out
    surface = list(default) + list(identity)
    surface += [(e, _col_label(e)) for e in extra]
    out: list[tuple[str, str]] = []
    keys: set[str] = set()
    ratio_labels = {key: label for key, label in _ratio_columns(names)}
    for name in names:
        key = _identity_key(name, surface, identity_map)
        label = None
        if key is not None:
            label = next((lbl for k, lbl in surface if k == key), None)
        elif _ratio_key_for(name):
            key = _ratio_key_for(name)
            label = ratio_labels.get(key)
        else:
            try:
                key = _metric_key(name, "field")
            except ValueError:
                if name in extra:
                    key = name
                elif unknown is not None:
                    unknown.append(name)
                    continue
                else:
                    raise
        if key in keys:
            continue
        keys.add(key)
        out.append((key, label or _col_label(key)))
    prefix = [(k, label) for k, label in identity if k not in keys]
    return prefix + out


def _model_cells(model: Model, cols: Sequence[tuple[str, str]],
                 value_of: Callable[[Model], float | None] | None = None) -> list[str]:
    """Render one model's cells.

    ``value_of`` supplies the ``value`` column from a value computed for *this
    call* (never a stale, memo-mutated ``Model.value`` — audit H3).
    """
    cells: list[str] = []
    for key, _label in cols:
        if key == "value" and value_of is not None:
            cells.append(render.num(value_of(model), 1))
        elif key == "value":
            cells.append(render.num(_value_of(model, "intelligence"), 1))
        elif key.startswith("value:"):
            cells.append(render.num(_value_of(model, key.split(":", 1)[1]), 1))
        else:
            cells.append(_fmt(key, select.lookup(model, key)))
    return cells


def _trim(headers: Sequence[str], rows: Sequence[Sequence[str]]
          ) -> tuple[list[str], list[list[str]]]:
    """Drop columns whose visible cells are all blank/``-`` (empty → ``([], [])``)."""
    if not rows:
        return [], []
    keep = [i for i in range(len(headers))
            if any(str(row[i]).strip() not in ("", "-") for row in rows)]
    if not keep:
        return [], []
    return ([headers[i] for i in keep],
            [[row[i] for i in keep] for row in rows])


def _table_block(head: str, headers: Sequence[str], rows: Sequence[Sequence[str]],
                 *, trim: bool = True, empty: str = "no values to show",
                 identity: Sequence[str] = (),
                 page_only: Mapping[str, str] | None = None) -> str:
    """Header + a markdown table, bounded to :data:`MAX_RESPONSE`.

    ``trim`` drops all-null columns — but only for *default* column sets; an
    explicit ``fields=`` list is always rendered (with ``-`` for nulls) so a
    caller can tell "no data" from "wrong field name". When the table would
    exceed the response cap the rows are dropped (never mid-row) and one note
    says how many were kept.

    ``identity`` names the header labels that identify the row (Model/Slug/Host/…):
    they are never reported as "no data" (G2) — an identity column that cannot be
    filled is a record gap, not a wrong field name.
    """
    headers = list(headers)
    rows = [list(row) for row in rows]
    if not rows:
        return f"{head}\n— {empty}"
    if trim:
        headers, rows = _trim(headers, rows)
        if not headers:
            return f"{head}\n— {empty}"
    else:
        exempt = {str(label).lower() for label in identity}
        all_null = [headers[i] for i in range(len(headers))
                    if str(headers[i]).lower() not in exempt
                    and all(str(row[i]).strip() in ("", "-") for row in rows)]
        if all_null:
            head += f"\n— no data for: {', '.join(all_null)} (shown as -)"
            if page_only:
                on_page = [label for label in all_null if label in page_only]
                if on_page:
                    sections = ", ".join(dict.fromkeys(
                        page_only[label] for label in on_page))
                    head += (f"\n— {', '.join(on_page)} live on the model page, "
                             f"not the leaderboard — read aa_model query=<slug> "
                             f"sections={sections}")
    body = render.table(headers, rows)
    text = f"{head}\n{body}"
    if len(text) <= MAX_RESPONSE:
        return text
    return _fit_rows(head, headers, rows)


def _fit_rows(head: str, headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """Binary-search the largest row prefix whose table fits :data:`MAX_RESPONSE`."""
    lo, hi = 0, len(rows)
    best: str | None = None
    while lo <= hi:
        mid = (lo + hi) // 2
        note = (f"— response capped at {MAX_RESPONSE // 1000} kB: showing {mid} of "
                f"{len(rows)} rows; narrow the request (`top`, `fields`) to see the rest")
        table = render.table(headers, rows[:mid])
        text = f"{head}\n{table}\n{note}" if table else f"{head}\n{note}"
        if len(text) <= MAX_RESPONSE:
            best = text
            lo = mid + 1
        else:
            hi = mid - 1
    if best is not None:
        return best
    return (f"{head}\n— response capped at {MAX_RESPONSE // 1000} kB: none of the "
            f"{len(rows)} rows fit; narrow the request (`top`, `fields`)")


def _filter_desc(
    *,
    creator: str,
    name: str,
    open_weights: bool | None,
    reasoning: bool | None,
    min_intelligence: float | None,
    max_cost_per_task: float | None,
    min_speed: float | None,
    max_ttft: float | None,
    min_context: int | None,
    released_after: str,
    include_deprecated: bool,
    max_price_in: float | None = None,
    max_price_out: float | None = None,
    vision: bool | None = None,
) -> str:
    parts = ["incl. deprecated" if include_deprecated else "active only"]
    if creator:
        parts.append(f"creator~{render.clean(creator, None)}")
    if name:
        parts.append(f"name~{render.clean(name, None)}")
    if open_weights is not None:
        parts.append("open-weights" if open_weights else "closed-weights")
    if reasoning is not None:
        parts.append("reasoning" if reasoning else "non-reasoning")
    if min_intelligence is not None:
        parts.append(f"intel>={min_intelligence:g}")
    if max_cost_per_task is not None:
        parts.append(f"$/task<={max_cost_per_task:g}")
    if max_price_in is not None:
        parts.append(f"in $/M<={max_price_in:g}")
    if max_price_out is not None:
        parts.append(f"out $/M<={max_price_out:g}")
    if vision is not None:
        parts.append("vision" if vision else "no vision")
    if min_speed is not None:
        parts.append(f"tok/s>={min_speed:g}")
    if max_ttft is not None:
        parts.append(f"TTFT<={max_ttft:g}s")
    if min_context is not None:
        parts.append(f"ctx>={min_context:g}")
    if released_after:
        parts.append(f"released>={render.clean(released_after, None)}")
    return ", ".join(parts)


#: How many per-model pages a modality join may read. AA publishes modality only
#: per model page (the leaderboard row and provider-board `features` carry none),
#: so a bounded fan-out is the cheapest honest source; one page's chart set already
#: documents ~28 models (~20 leaderboard variants).
_MODALITY_FANOUT = 6


def _modality_map(models: Sequence[Model], refresh: bool = False) -> dict[
        str, tuple[tuple[str, ...], tuple[str, ...]]]:
    """``slug -> (input, output) modalities`` from up to N model pages.

    No bulk payload carries modality: the leaderboard row has no modality keys,
    the provider board's ``features`` has none, and the eval chart pages carry
    none. Each ``/models/<slug>`` chart set does carry ``inputModality*`` /
    ``outputModality*`` for ~28 models, so the join reads a bounded number of
    pages of the highest-value models (best Intelligence Index first) and reports
    how many rows it covered.
    """
    known: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
    ordered = sorted(models, key=lambda m: (
        -(m.intelligence if m.intelligence is not None else -1.0), m.slug))
    tried = 0
    for m in ordered:
        if tried >= _MODALITY_FANOUT:
            break
        if m.slug in known:
            continue
        try:
            pages = _load(f"model_{m.slug}", loaders.model, m.slug, refresh=refresh)
        except (AAFetchError, ValueError, LookupError):
            continue
        tried += 1
        for page_model in pages.values():
            if page_model.modalities_in or page_model.modalities_out:
                known.setdefault(page_model.slug, (
                    tuple(page_model.modalities_in),
                    tuple(page_model.modalities_out)))
    return known


def _apply_modality(scope: Sequence[Model], known: Mapping[
        str, tuple[tuple[str, ...], tuple[str, ...]]]) -> None:
    """Attach known modalities to the models in ``scope`` (no-op when unknown)."""
    for model in scope:
        modalities = known.get(model.slug)
        if modalities:
            ins, outs = modalities
            model.modalities_in = tuple(ins)
            model.modalities_out = tuple(outs)


def _modality_in(
    known: Mapping[str, tuple[tuple[str, ...], tuple[str, ...]]], slug: str
) -> tuple[str, ...]:
    """Input modalities for ``slug`` (empty when unknown)."""
    pair = known.get(slug)
    return pair[0] if pair else ()


def _modality_note(known: Mapping[str, tuple[tuple[str, ...], tuple[str, ...]]],
                   total: int, vision: bool | None = None) -> str:
    """One honest coverage line for a modality join (`-` is unknown, not "no")."""
    covered = sum(1 for m in known)
    text = (f"modality known for {min(covered, total)} of {total} tracked rows "
            f"(per-model pages; unknown rows are excluded from a modality filter)")
    if vision is None:
        text += " — '-' means unknown, not \"no vision\""
    return text


def _missing_notes(
    scope: Sequence[Model], specs: Sequence[tuple[str, str, bool]]
) -> list[str]:
    """Footnote lines for rows dropped because a filtered field was never measured."""
    total = len(scope)
    lines: list[str] = []
    for key, label, active in specs:
        if not active:
            continue
        missing = sum(1 for m in scope if select.lookup(m, key) is None)
        if missing:
            lines.append(
                f"{missing} rows skipped: no measured {label} "
                f"(AA has {label} for {total - missing}/{total} variants)"
            )
    return lines


def _rich_models(refresh: bool = False) -> list[Model]:
    """The optional 699-model rich dataset (loaders.rich_dataset), or ``[]``.

    Defensive: the loader may not exist yet (another agent's slice) or may fail
    (a poisoned ``rich_dataset.json`` now raises); callers fall back to the
    leaderboard/chart sources, and the reason is logged so the degradation is
    visible in the server log rather than silent.
    """
    fn = getattr(loaders, "rich_dataset", None)
    if not callable(fn):
        return []
    try:
        return list(fn(refresh=refresh) or [])
    except Exception as exc:
        log.warning("rich dataset unavailable (%s); continuing without the overlay", exc)
        return []


def _mtime(*names: str) -> tuple:
    """Cache-file mtimes for the given cache names (``None`` when absent)."""
    out = []
    for name in names:
        stamp = None
        for ext in (".rsc", ".html", ".json"):
            path = fetch.cache_dir() / f"{name}{ext}"
            try:
                if path.exists():
                    stamp = path.stat().st_mtime
                    break
            except OSError:
                continue
        out.append(stamp)
    return tuple(out)


#: memo: (key, merged models, rich overlay contributed?)
_MODELS_MEMO: tuple[tuple, list[Model], bool] | None = None


def _models_state(refresh: bool = False, *,
                  rich: bool = True) -> tuple[list[Model], bool]:
    """``(models, rich_used)`` — the 700 leaderboard rows with the rich overlay merged.

    The leaderboard row is the base and the rich record (same slug) is merged over
    it, so rich-only fields (license, effort, params, capabilities.*, aime25,
    livecodebench, per-eval cost) become available while leaderboard-only fields
    (isOpenWeights, omniscience*, itbenchSre, the speed snapshot) are kept.
    Memoised on the cache mtimes so a tool call does not re-merge 700 records.

    ``rich=False`` skips the overlay entirely (no discovery, no 6 model-page
    probes) for calls whose metrics the leaderboard already carries — see
    :func:`_rich_needed`.
    """
    global _MODELS_MEMO
    lb = _lb_rows(refresh)
    if not rich:
        return list(lb), False

    lb_name = _lb_cache()
    key = (len(lb), _mtime(lb_name, "rich_dataset"))
    memo = _MODELS_MEMO
    if memo is not None and not refresh and memo[0] == key:
        return memo[1], memo[2]

    rich_rows = _rich_models(refresh)
    if rich_rows:
        overlay = {m.slug: m for m in rich_rows}
        merged = [normalize.merge(m, overlay[m.slug]) if m.slug in overlay else m
                  for m in lb]
        used = True
    else:
        merged = list(lb)
        used = False
    _MODELS_MEMO = (key, merged, used)
    return merged, used


def _models(refresh: bool = False) -> list[Model]:
    """Every model AA publishes, for name/slug resolution (audit D3).

    The leaderboard snapshot tracks the **active** variants only (275 rows, none
    deprecated), so resolving against it made a deprecated slug unreachable even
    though its page still renders.  ``loaders.model_pool`` is the union of the
    active rows and the rich dataset (lead order preserved, rich-only rows
    appended); ``include_deprecated=false`` is a presentation choice each tool
    applies *after* resolution.
    """
    fn = getattr(loaders, "model_pool", None)
    if callable(fn):
        try:
            rows = list(fn(refresh=refresh) or [])
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("model pool unavailable (%s); resolving against the "
                        "leaderboard", exc)
        else:
            if rows:
                return rows
    return _models_state(refresh, rich=False)[0]


def _include_deprecated_rows(models: Sequence[Model],
                             refresh: bool = False) -> list[Model]:
    """``models`` plus the deprecated rows resolution can see (audit D3).

    The merged ranking dataset only carries slugs the active leaderboard also
    carries, so ``include_deprecated=true`` had nothing to add.  The pool holds the
    444 rich-only deprecated records; append the ones missing from the dataset
    (same-slug rows keep the leaderboard/merged value, which wins on ordering).
    """
    have = {m.slug for m in models}
    extra = [m for m in _models(refresh) if m.deprecated and m.slug not in have]
    return list(models) + extra


def _prov_label(rich_used: bool, source_key: str | None = None) -> str:
    """The header's source label, naming the rich overlay's own age when used.

    The header's date/``stale`` flag describe the *leaderboard* payload
    (``AA_CACHE_TTL``); the rich overlay is a separate, longer-lived cache
    (``AA_RICH_TTL``), so it is labelled separately instead of silently inheriting
    the leaderboard's age (round-7 §4.5).
    """
    base = source_key or _source_key()
    if not rich_used:
        return base
    age = getattr(loaders, "rich_age", None)
    seconds = age() if callable(age) else None
    if not isinstance(seconds, (int, float)):
        return f"{base} + rich dataset"
    seed = getattr(loaders, "rich_seed", None)
    slug = seed() if callable(seed) else None
    where = f", seed {render.clean(slug, 40)}" if slug else ""
    return f"{base} + rich dataset (overlay {render.ago(time.time() - seconds)}{where})"



def _is_index_key(key: str) -> bool:
    return key.startswith("capabilities.") or key in ("coding", "agentic")


def _deprecated_only_text(key: str, label: str) -> str:
    """Explain a metric AA publishes only on deprecated models — and name a live one."""
    live = {
        "math500": ("AIME 2025", "aime25"),
        "mmluPro": ("GPQA Diamond", "gpqa"),
    }.get(key)
    text = (f"{label!r} is only published for deprecated models in the current "
            "source — no active model carries it.")
    if live:
        text += (f"\n— use a live alternative instead: {live[0]} "
                 f"(aa_leaderboard sort={live[1]})")
    text += ("\n— include_deprecated=true ranks the deprecated rows (they are "
             "clearly marked Depr in the reply)")
    return text


def _no_rank_text(key: str, label: str) -> str:
    if key == "math500":
        return (
            "'Math-500' is deprecated-only in the current source: no active model "
            "carries it, and the deprecated values the rich overlay used to hold "
            "are no longer served on any free page.\n"
            "— use the live math ranking instead: AIME 2025 "
            "(aa_leaderboard sort=aime25; aa_benchmark_leaderboard benchmark=aime25)"
        )
    if key == "mmluPro":
        return _deprecated_only_text(key, label)
    constituents = catalog.API_ONLY_INDEXES.get(key)
    if constituents:
        return (
            f"{label!r}: AA publishes this composite only through its paid data API, "
            "and no public page carries a per-model value — there is no cross-model "
            "ranking to sort by.\n"
            f"— rank the free constituents instead: {', '.join(constituents)} "
            "(aa_benchmark_leaderboard benchmark=<one of those>)"
        )
    if key in _OWN_PAGE_KEYS:
        return (
            f"{label!r}: AA publishes this index on a page of its own, which could not "
            "be read just now — no per-model values are available, so there is no "
            "cross-model ranking to sort by.\n"
            "— retry with refresh=true, or read one model with aa_model <slug>."
        )
    if catalog.benchmark(key) is None:
        return (
            f"{label!r} has no values in the leaderboard — it lives on the "
            "model page only, so it cannot be ranked across models.\n"
            f"— read one model with aa_model query=<slug> sections=specs,benchmarks "
            f"(e.g. aa_leaderboard name=<model> to find the slug)"
        )
    bench = catalog.BENCHMARKS.get(key)
    if bench is not None and bench.source_hint == "none":
        rank = getattr(catalog, "RANKABLES", {}).get(key)
        how = str(getattr(rank, "how", "") or "")
        return (
            f"{label!r}: AA no longer publishes this metric on any free surface, so "
            "there are no per-model values to rank — the value is never substituted "
            "from a different metric.\n"
            + (f"— {how}" if how else "— aa_benchmarks lists the metrics AA does publish")
        )
    if bench is not None and bench.source_hint == "chart" and not bench.slug:
        return (
            f"{label!r} is published only on individual model pages — AA exposes no "
            "cross-model column for it in the current source.\n"
            "— read one model with aa_model query=<slug> sections=benchmarks."
        )
    return (
        f"{label!r} has no per-model values in the current source — it is not in the "
        "leaderboard, and AA's eval chart set / homepage panel carry none "
        "either.\n"
        "— try refresh=true to re-fetch, or read one model with aa_model <slug>."
    )


def _informational_no_rank(key: str) -> bool:
    """Whether "no ranking exists" is a complete answer (exit 0) for ``key``.

    A composite AA sells only through its paid API, or a metric AA stopped
    publishing, is answered in full — there is nothing the caller can re-run.
    A deprecated-only metric with a free live alternative is actionable, so it
    stays an error (non-zero).
    """
    if key in getattr(catalog, "API_ONLY_INDEXES", {}):
        return True
    bench = catalog.BENCHMARKS.get(key)
    return bench is not None and getattr(bench, "source_hint", "") == "none"


def _no_rank_error(key: str, label: str) -> Exception:
    """The right exception for a metric with no ranking: info reply or error."""
    text = _no_rank_text(key, label)
    return _InfoAnswer(text) if _informational_no_rank(key) else ValueError(text)


def _breakdown_text(key: str, label: str) -> str:
    """Honest one-liner for a ``unit == "mixed"`` container benchmark.

    Breakdown benchmarks (``aa3dBreakdown``, ``harveyLabBreakdown``, …) carry a
    per-model *map* of sub-scores, not a scalar column, so there is no ranking to
    give (round-5 audit: this used to raise ``TypeError: float() argument … not
    'dict'``). Names the scalar sub-score the catalog's own hint points at (a call
    that ranks something) plus the other scalar columns on the same page, and the
    model-page breakdown that renders the maps.
    """
    bench = catalog.BENCHMARKS.get(key)
    rank = catalog.RANKABLES.get(key)
    how = str(getattr(rank, "how", "") or "")
    sub = (how.partition("=")[2].strip()
           if how.startswith("aa_benchmark_leaderboard benchmark=") else "")
    siblings: list[str] = []
    if bench is not None and bench.slug:
        siblings = [b.key for b in catalog.BENCHMARKS.values()
                    if b.key != key and b.unit != "mixed" and b.slug == bench.slug]
    # lead with the sub-score the catalog hint names, then the other scalar columns
    targets = list(dict.fromkeys(([sub] if sub else []) + siblings))
    hint = ""
    if targets:
        extra = f" (or {', '.join(targets[1:3])})" if len(targets) > 1 else ""
        hint = (f"— rank a published sub-score instead: "
                f"aa_benchmark_leaderboard benchmark={targets[0]}{extra}; ")
    return (
        f"{label!r} is a container benchmark: AA publishes its values as "
        "per-model sub-score maps, not a cross-model ranking column.\n"
        f"{hint}read one model's breakdown with aa_model <slug> sections=benchmarks"
    )


def _deprecated_match(query: str) -> Model | None:
    """A deprecated release whose slug/name exactly matches ``query``, if any.

    Resolution normally sees the full pool (which includes deprecated releases),
    so this fires when a caller restricted the pool — ``aa_compare`` resolves
    against the *active* rows — and the name is a real release rather than a typo.
    """
    q = _norm_alias(query)
    if not q:
        return None
    fn = getattr(loaders, "deprecated_releases", None)
    if not callable(fn):
        return None
    try:
        releases = list(fn() or [])
    except Exception:  # pragma: no cover - resolution must never fail on the hint
        return None
    for m in releases:
        if q in {_norm_alias(m.slug), _norm_alias(m.name),
                 _norm_alias(m.short_name)}:
            return m
    return None


def _resolve_slug(query: str, models: Sequence[Model]) -> Model:
    try:
        return select.resolve(models, query)
    except select.AmbiguousError:
        raise
    except LookupError:
        deprecated = _deprecated_match(query)
        if deprecated is not None:
            target = (f" → superseded by {deprecated.deprecated_to}"
                      if deprecated.deprecated_to else "")
            raise ValueError(
                f"known model, deprecated — {deprecated.name} is not in the "
                f"active pool; page /models/{deprecated.slug}{target}\n"
                "— aa_model <slug> still reads its page; ranked surfaces hide it "
                "unless include_deprecated=true"
            ) from None
        near = select.search(models, query, limit=5)
        slugs = ", ".join(m.slug for m in near) or "none"
        raise ValueError(
            f"no model matches {_q(query)} — closest slugs: {slugs}\n"
            "— use aa_search to resolve names to slugs"
        ) from None


# --------------------------------------------------------------------------- #
# rankable index (the Wave-C catalog interface, consumed defensively)
# --------------------------------------------------------------------------- #
#
# ``catalog`` may or may not expose the ``Rankable``/``RANKABLES``/``DOMAINS``
# interface yet; every helper below prefers it and falls back to an index built
# from ``catalog.BENCHMARKS`` + the metric registry + the loader board keys, so
# ``aa_benchmarks`` and the ``aa://rankables*`` resources work either way.

@dataclasses.dataclass(frozen=True, slots=True)
class _Rankable:
    """Local stand-in for ``catalog.Rankable`` (same field shape)."""
    key: str
    label: str
    kind: str
    unit: str
    tags: tuple[str, ...]
    how: str
    surface: str
    desc: str
    aliases: tuple[str, ...] = ()


#: ``aa_pareto`` x axes: key -> (short label incl. unit, unit text, ordering word).
#: The header states all three so a plot's axes are never ambiguous.
_PARETO_AXES: dict[str, tuple[str, str, str]] = {
    "cost_per_task": ("$/task", "USD per Intelligence Index task", "cost"),
    "index_total_cost": ("$/index", "USD for the whole Intelligence Index run", "cost"),
    "out_tokens_per_task": ("tok/task", "output tokens per index task", "tokens"),
    "time_per_task": ("s/task", "seconds per index task", "time"),
    "tps": ("tok/s", "output tokens per second", "speed"),
    "context_tokens": ("ctx (tokens)", "context window in tokens", "context"),
    "params_b": ("params (B)", "parameters in billions", "size"),
    "ttft": ("TTFT (s)", "seconds to first token", "TTFT"),
    "price_in": ("in ($/1M)", "USD per 1M input tokens", "price"),
    "price_out": ("out ($/1M)", "USD per 1M output tokens", "price"),
}
#: axes the leaderboard cannot carry — derived on the model page (rich overlay)
_OVERLAY_AXES = ("index_total_cost", "time_per_task")
#: spellings ``catalog.metric`` does not know yet (the new derived axes)
_AXIS_ALIASES = {
    "indexcost": "index_total_cost",
    "indextotalcost": "index_total_cost",
    "totalcost": "index_total_cost",
    "costtorunindex": "index_total_cost",
    "costofindex": "index_total_cost",
    "costtoruntheintelligenceindex": "index_total_cost",
    "timepertask": "time_per_task",
    "indextimepertask": "time_per_task",
    "timetorunindex": "time_per_task",
    "timeperintelligenceindextask": "time_per_task",
    "tokenspertask": "out_tokens_per_task",
    "outputtokensperindextask": "out_tokens_per_task",
    "costperindextask": "cost_per_task",
    "task": "cost_per_task",
}
#: score keys the local frontier resolver must handle itself
_DERIVED_AXES = ("index_total_cost", "time_per_task")

#: derived (non-benchmark) rankables: key, label, unit, tags, how-to-query
_DERIVED_RANKABLES: tuple[tuple[str, str, str, tuple[str, ...], str], ...] = (
    ("tps", "Speed (output tokens/s)", "tok/s", ("speed", "performance"),
     "aa_leaderboard sort=tps"),
    ("ttft", "Time to First Token", "s", ("speed", "latency"),
     "aa_leaderboard sort=ttft"),
    ("ttfa", "Time to First Answer Token", "s", ("speed", "latency"),
     "aa_leaderboard sort=ttfa"),
    ("e2e", "End-to-End Response Time", "s", ("speed", "latency"),
     "aa_leaderboard sort=e2e"),
    ("reasoning_s", "Reasoning Time", "s", ("speed", "reasoning"),
     "aa_leaderboard sort=reasoning_s"),
    ("cost_per_task", "Cost per Task", "USD/task", ("cost", "pricing"),
     "aa_pareto x=cost_per_task"),
    ("index_total_cost", "Cost to Run the Intelligence Index (whole suite)", "USD",
     ("cost", "pricing", "index"), "aa_pareto x=index_total_cost"),
    ("out_tokens_per_task", "Output Tokens per Intelligence Index Task", "tokens",
     ("cost", "speed", "verbosity"), "aa_pareto x=out_tokens_per_task"),
    ("time_per_task", "Time per Intelligence Index Task", "s",
     ("speed", "latency", "cost"), "aa_pareto x=time_per_task"),
    ("price_in", "Input Price", "USD/1M", ("cost", "pricing"),
     "aa_leaderboard sort=price_in"),
    ("price_out", "Output Price", "USD/1M", ("cost", "pricing"),
     "aa_leaderboard sort=price_out"),
    ("cache_read", "Cache Read Price", "USD/1M", ("cost", "pricing", "caching"),
     "aa_providers fields=cache_read"),
    ("cache_write", "Cache Write Price", "USD/1M", ("cost", "pricing", "caching"),
     "aa_providers fields=cache_write"),
    ("context_tokens", "Context Window", "tokens", ("long-context", "context"),
     "aa_leaderboard sort=context_tokens"),
    ("params_b", "Parameters (total)", "params", ("openness", "size"),
     "aa_leaderboard sort=params_b"),
    ("active_params_b", "Parameters (active, MoE)", "params", ("openness", "size"),
     "aa_leaderboard sort=active_params_b"),
    ("release_date", "Release Date", "date", ("release", "freshness"),
     "aa_leaderboard sort=release_date"),
)

#: arena boards: key -> (label, unit, tags, aliases). Covers every ``aa_media``
#: board plus the speech panels and the ``aa_agents`` boards.
_ARENAS: dict[str, tuple[str, str, tuple[str, ...], tuple[str, ...]]] = {
    "text_to_image": ("Text-to-Image Arena Elo", "Elo",
                      ("media", "image", "vision", "arena"),
                      ("Text to Image Arena", "Image Arena Elo")),
    "image_editing": ("Image Editing Arena Elo", "Elo",
                      ("media", "image", "vision", "arena"), ("Image Edit Arena",)),
    "text_to_video": ("Text-to-Video Arena Elo", "Elo", ("media", "video", "arena"),
                      ("Text to Video Arena",)),
    "image_to_video": ("Image-to-Video Arena Elo", "Elo", ("media", "video", "arena"),
                       ("Image to Video Arena",)),
    "video_editing": ("Video Editing Arena Elo", "Elo", ("media", "video", "arena"), ()),
    "text_to_speech": ("Provider Voice Arena Preference Elo", "Elo",
                       ("media", "speech", "audio", "arena"),
                       ("Text to Speech Arena Elo", "TTS Arena Elo",
                        "Provider Voice Arena")),
    "text_to_speech_controlled": ("Controlled Voice Arena Preference Elo", "Elo",
                                  ("media", "speech", "audio", "arena"), ()),
    "music_instrumental": ("Music Arena Elo (instrumental)", "Elo",
                           ("media", "music", "audio", "arena"), ()),
    "music_with_vocals": ("Music Arena Elo (with vocals)", "Elo",
                          ("media", "music", "audio", "arena"), ()),
    "speech_to_text": ("Speech to Text (word error rate)", "%",
                       ("media", "speech", "audio", "arena", "safety"),
                       ("Speech Recognition", "STT")),
    "speech_to_text_streaming": ("Streaming Speech to Text", "%",
                                 ("media", "speech", "audio", "arena"), ()),
    "speech_to_speech": ("Artificial Analysis Speech to Speech Index", "index",
                         ("media", "speech", "audio", "arena"),
                         ("Realtime Voice", "STS Index", "Speech to Speech")),
    "coding_agents": ("AA Coding Agent Index", "index",
                      ("agentic", "coding", "agents", "arena"),
                      ("Coding Agents Board",)),
    "chatbots": ("Chatbot Arena Preference", "index", ("arena", "agents"),
                 ("Chatbot Board",)),
    "search_api": ("Search API Index", "index", ("agents", "tool-use", "arena"), ()),
}

#: extra aliases so the user's own phrasings resolve even without catalog support
_BENCH_ALIASES: dict[str, tuple[str, ...]] = {
    "intelligence": ("Artificial Analysis Intelligence Index", "Intelligence Index"),
    "cyberIndex": ("Artificial Analysis Cyber Index",),
    "openness": ("Openness Index",),
    "omniscience": ("AA-Omniscience Index",),
    "terminalBench40": ("Terminal-Bench 4.0", "TerminalBench 4.0"),
    "terminalBenchScience": ("Terminal-Bench-Science 0.1", "Terminal-Bench Science 0.1"),
    "frontierCode": ("FrontierCode 1.1",),
    "itbenchSre": ("ITBench-AA", "ITBench SRE"),
    "aa3dElo": ("AA-3D", "AA 3D"),
    "lcr": ("AA-LCR",),
    "hle": ("Humanity's Last Exam",),
    "gdpPdfAllPass": ("GDP.pdf",),
    "gdpval": ("GDPval-AA Elo",),
    "briefcaseElo": ("AA-Briefcase Elo",),
}

#: canonical domain -> the tags/tokens it expands to (fallback for ``catalog.DOMAINS``)
_FALLBACK_DOMAINS: dict[str, tuple[str, ...]] = {
    "coding": ("coding",),
    "math": ("math",),
    "science": ("science",),
    "security": ("cyber", "cweBench*", "deepsec*", "cybergym*", "wildguard*", "security"),
    "agentic": ("agentic",),
    "tool-use": ("tool-use", "function calling"),
    "long-context": ("long-context",),
    "instruction-following": ("instruction-following",),
    "knowledge": ("knowledge",),
    "reasoning": ("reasoning",),
    "safety": ("safety",),
    "multimodal": ("vision", "multimodal", "image"),
    "vision": ("vision", "image"),
    "speech": ("speech", "audio"),
    "media": ("media",),
    "music": ("music",),
    "video": ("video",),
    "business": ("knowledge-work", "business"),
    "finance": ("finance", "capability.finance"),
    "legal": ("legal", "capability.legal"),
    "medical": ("medical", "capability.healthcareAndMedical"),
    "engineering": ("engineering", "capability.engineering"),
    "economics": ("economics", "capability.economics"),
    "cost": ("cost", "pricing"),
    "speed": ("speed",),
    "latency": ("latency",),
    "openness": ("openness",),
    "index": ("index",),
    "arena": ("arena",),
    "agents": ("agents",),
}

_FALLBACK_MEMO: dict[str, _Rankable] | None = None


def _build_fallback_rankables() -> dict[str, _Rankable]:
    """Build the local index from ``catalog.BENCHMARKS`` + the board keys."""
    out: dict[str, _Rankable] = {}
    for key, bench in catalog.BENCHMARKS.items():
        kind = "index" if bench.unit == "index" else "benchmark"
        constituents = catalog.API_ONLY_INDEXES.get(key)
        if constituents:
            # no free per-model surface exists: point at a call that works
            how = f"aa_benchmark_leaderboard benchmark={constituents[0]}"
        elif bench.unit == "mixed":
            how = f"aa_model <model-slug> sections=benchmarks ({bench.label} breakdown)"
        elif (bench.source_hint != "none"
              and (bench.source_hint != "chart" or bench.slug)):
            # mirrors catalog's rule: the leaderboard path reaches leaderboard /
            # rich / chart-set / panel keys (the join is by eval-page slug)
            how = f"aa_leaderboard sort={key}"
        else:
            how = f"aa_benchmark_leaderboard benchmark={key}"
        aliases = tuple(dict.fromkeys((bench.label, *_BENCH_ALIASES.get(key, ()))))
        out[key] = _Rankable(key, bench.label, kind, bench.unit, tuple(bench.tags),
                             how, str(bench.source_hint or "leaderboard"), bench.desc,
                             aliases)
    for key, label, unit, tags, how in _DERIVED_RANKABLES:
        if key in out:
            continue
        out[key] = _Rankable(key, label, "derived", unit, tags, how, "rich", label, ())
    for board, (label, unit, tags, aliases) in _ARENAS.items():
        tool = "aa_agents" if board in loaders.AGENT_BOARDS else "aa_media"
        out.setdefault(board, _Rankable(board, label, "arena", unit, tags,
                                        f"{tool} board={board}", "board", label,
                                        aliases))
    return out


def _fallback_rankables() -> dict[str, _Rankable]:
    global _FALLBACK_MEMO
    if _FALLBACK_MEMO is None:
        _FALLBACK_MEMO = _build_fallback_rankables()
    return _FALLBACK_MEMO


def _strip_version(text: str) -> str:
    r"""Drop a trailing ``v?\d+(\.\d+)*`` from a normalized token (version tolerance)."""
    return re.sub(r"v?\d+(?:\.\d+)*$", "", text)


def _rankable_hay(r: Any) -> str:
    """Lowercased search haystack for one rankable (key/label/desc/tags/aliases)."""
    parts = [str(getattr(r, "key", "")), str(getattr(r, "label", "")),
             str(getattr(r, "desc", "")), *getattr(r, "tags", ())]
    parts += [str(a) for a in getattr(r, "aliases", ())]
    return " ".join(parts).lower()


def _fallback_rankable(key_or_alias: str) -> _Rankable | None:
    table = _fallback_rankables()
    raw = str(key_or_alias).strip()
    if raw in table:
        return table[raw]
    n = _norm_alias(raw)
    if not n:
        return None
    stripped = _strip_version(n)
    for r in table.values():
        names = [_norm_alias(r.key), _norm_alias(r.label)]
        names += [_norm_alias(a) for a in r.aliases]
        if n in names or (stripped != n and stripped in names):
            return r
    return None


def _domain_map() -> dict[str, tuple[str, ...]]:
    """Canonical domain -> tags/tokens it expands to (catalog's, else the fallback)."""
    domains = getattr(catalog, "DOMAINS", None)
    if isinstance(domains, dict) and domains:
        return {str(k): tuple(v) for k, v in domains.items()}
    return dict(_FALLBACK_DOMAINS)


def _domain_tokens(domain: str) -> tuple[str, ...] | None:
    """The expansion for ``domain`` (``None`` when unknown)."""
    n = _norm_alias(domain)
    for name, tokens in _domain_map().items():
        if _norm_alias(name) == n:
            return tuple(tokens)
    return None


def _query_domain(query: str) -> str | None:
    """The canonical domain a single-word ``query`` names (else ``None``).

    Mirrors :func:`catalog.query_domain` so the fallback index and the header
    note agree with the catalog's own expansion.
    """
    text = str(query).strip()
    if not text or any(ch.isspace() for ch in text):
        return None
    n = _norm_alias(text)
    for name in _domain_map():
        if _norm_alias(name) == n:
            return name
    return None


def _domain_match(r: Any, tokens: Sequence[str]) -> bool:
    """True when a rankable belongs to a domain (tag hit or key/label token hit)."""
    tags = {_norm_alias(t) for t in getattr(r, "tags", ())}
    hay = _norm_alias(_rankable_hay(r))
    for token in tokens:
        t = _norm_alias(token)
        if not t:
            continue
        if t in tags or t in hay:
            return True
        if token.endswith("*") and _norm_alias(token[:-1]) in hay:
            return True
    return False


def _fallback_list(*, domain: str = "", tag: str = "", query: str = "") -> list[_Rankable]:
    """Local ``rankables()``: domain/tag expansion + tokenised AND query."""
    rows = list(_fallback_rankables().values())
    if domain:
        tokens = _domain_tokens(domain)
        if tokens is None:
            raise ValueError(_unknown_domain(domain))
        rows = [r for r in rows if _domain_match(r, tokens)]
    if tag:
        nt = _norm_alias(tag)
        rows = [r for r in rows
                if any(nt == _norm_alias(t) or nt in _norm_alias(t) for t in r.tags)]
    if query:
        canon = _query_domain(query)
        if canon:
            rows = [r for r in rows if _domain_match(r, _domain_tokens(canon) or ())]
        else:
            tokens = [t for t in re.split(r"[^a-z0-9]+", query.lower()) if t]
            rows = [r for r in rows if all(t in _rankable_hay(r) for t in tokens)]
    return rows


def _unknown_domain(domain: str) -> str:
    return (f"unknown domain {_q(domain)} — valid domains: "
            f"{', '.join(sorted(_domain_map()))}")


def _rankable_list(*, domain: str = "", tag: str = "", query: str = "") -> list[Any]:
    """``catalog.rankables(...)`` when available, else the local fallback index."""
    fn = getattr(catalog, "rankables", None)
    if callable(fn):
        try:
            got = list(fn(domain=domain, tag=tag, query=query) or [])
        except Exception as exc:
            log.warning("catalog.rankables(%r, %r, %r) failed (%s); using the fallback",
                        domain, tag, query, exc)
        else:
            return got
    return _fallback_list(domain=domain, tag=tag, query=query)


def _rankable(key_or_alias: str) -> Any | None:
    """One rankable by key/label/alias (catalog's resolver, else the fallback)."""
    fn = getattr(catalog, "rankable", None)
    if callable(fn):
        try:
            got = fn(key_or_alias)
        except Exception as exc:
            log.debug("catalog.rankable(%r) failed: %s", key_or_alias, exc)
            got = None
        if got is not None:
            return got
    return _fallback_rankable(key_or_alias)


def _rankable_value(model: Model, key: str) -> float | None:
    """A rankable's numeric value for one model (derived axes included)."""
    return _axis_value(model, key)


# --------------------------------------------------------------------------- #
# aa_pareto (the Pareto frontier — also aa_leaderboard mode=frontier)
# --------------------------------------------------------------------------- #

def _pareto_axis(name: str) -> str:
    """Resolve an ``x=`` axis name/alias to one of :data:`_PARETO_AXES`."""
    n = _norm_alias(name)
    if n in _AXIS_ALIASES:
        return _AXIS_ALIASES[n]
    rank = _rankable(name)
    if rank is not None and str(getattr(rank, "key", "")) in _PARETO_AXES:
        return str(rank.key)
    try:
        key = _metric_key(name, "x axis")
    except ValueError:
        key = ""
    if key in _PARETO_AXES:
        return key
    raise ValueError(
        f"unknown x axis {_q(name)} — valid axes: {', '.join(_PARETO_AXES)}\n"
        "— x is the trade-off axis plotted against the score"
    )


def _axis_value(model: Model, key: str) -> float | None:
    """Value of a Pareto ``x`` axis for ``model`` (``None`` when absent).

    ``index_total_cost`` is AA's whole-suite index cost
    (``cost_breakdown['index_total']``) and ``time_per_task`` AA's published
    ``intelligenceIndexTimePerTask`` (``speed['time_per_task']``, model-page data).
    A record that predates that field (or a panel/arena row) falls back to the
    unweighted mean of the per-evaluation ``timePerTask`` values
    (``speed['time_per_task_derived']``, computed here when absent) — the caller
    labels which of the two it is, so a recomputation is never passed off as AA's
    field. Every other axis is the ordinary metric lookup.
    """
    if key == "index_total_cost":
        value = (model.cost_breakdown or {}).get("index_total")
        return float(value) if isinstance(value, (int, float)) else None
    if key == "time_per_task":
        published = model.speed.get("time_per_task")
        if isinstance(published, (int, float)):
            return float(published)
        derived = model.speed.get("time_per_task_derived")
        if isinstance(derived, (int, float)):
            return float(derived)
        rows = getattr(model, "per_eval", None) or model.per_eval_cost or []
        times = [float(r["timePerTask"]) for r in rows
                 if isinstance(r, dict)
                 and isinstance(r.get("timePerTask"), (int, float))]
        return math.fsum(times) / len(times) if times else None
    return _metric_value(model, key)


def _time_per_task_derived(model: Model) -> bool:
    """True when ``model``'s ``s/task`` is our recomputation, not AA's field."""
    published = model.speed.get("time_per_task")
    return not isinstance(published, (int, float))


def _axis_text(key: str, value: Any) -> str:
    """One ``x`` cell; the two derived axes carry their own units."""
    if value is None:
        return "-"
    if key == "index_total_cost":
        v = float(value)
        return f"${v:,.0f}" if abs(v) >= 100 else f"${v:,.2f}"
    if key == "time_per_task":
        return f"{float(value):,.1f}s"
    return _fmt(key, value)


def _ratio_text(value: float | None) -> str:
    """``score / x`` — adaptive precision (a tok/task ratio is far below 1)."""
    if value is None:
        return "-"
    v = float(value)
    if v >= 100:
        return f"{v:,.0f}"
    if v >= 1:
        return f"{v:,.1f}"
    return f"{v:.3f}"


def _pareto_frontier(
    models: Sequence[Model],
    score_of: Callable[[Model], float | None],
    x_of: Callable[[Model], float | None],
) -> list[tuple[Model, float, float]]:
    """x-ascending non-dominated frontier over ``(x, score)`` pairs.

    Generalises :func:`select.pareto` to the derived axes ``select`` cannot
    resolve: a model is on the frontier when no other model has ``x' <= x`` and
    ``score' >= score`` with at least one strict. Deterministic and
    order-independent (sorted by ``(x, -score)``, then a strict running max).
    """
    pairs: list[tuple[Model, float, float]] = []
    for m in models:
        x, s = x_of(m), score_of(m)
        if x is None or s is None:
            continue
        pairs.append((m, float(x), float(s)))
    pairs.sort(key=lambda t: (t[1], -t[2]))
    front: list[tuple[Model, float, float]] = []
    best: float | None = None
    for m, x, s in pairs:
        if best is None or s > best:
            front.append((m, x, s))
            best = s
    return front


def _pareto_knee(front: Sequence[tuple[Model, float, float]]) -> int:
    """Index of the last frontier point before the cost/score ratio jumps ≥5×.

    The cost/score ratio is measured against the cheapest frontier point with a
    usable ``x`` (a zero-cost point carries no ratio): the knee is the most
    expensive point still within 5× that baseline, i.e. the last model before
    the ratio collapses.
    """
    if not front:
        return -1
    base: float | None = None
    knee = 0
    for i, (_m, x, s) in enumerate(front):
        if x <= 0 or s <= 0:
            knee = i
            continue
        ratio = x / s
        if base is None:
            base = ratio
            knee = i
            continue
        if ratio >= 5 * base:
            return knee
        knee = i
    return knee


def _axis_missing_text(key: str, label: str) -> str:
    if key in _OVERLAY_AXES:
        return (
            f"{label!r} is model-page data, not a leaderboard column: AA reports it in "
            "the per-model cost/time breakdown (the rich dataset merged over the "
            "leaderboard).\n— nothing to plot in the current source: load the model "
            "page with aa_model <slug> sections=cost, or retry with refresh=true"
        )
    return (f"{label!r} has no values in the current source — "
            "see aa_reference topic=sources")


#: index keys AA publishes on a page of their own (see ``loaders.index_models``):
#: the six Capability Indexes plus the Openness and Decision indexes.  Their page
#: is authoritative for its own key and, for a capability index, is the only
#: source of that index's sub-scores.
_OWN_PAGE_KEYS = frozenset(loaders.CAPABILITY_INDEXES) | frozenset(loaders.INDEX_PAGES)
#: the six Capability Indexes (the ones with sub-scores)
_CAPABILITY_KEYS = frozenset(loaders.CAPABILITY_INDEXES)


def _index_page_surface(key: str, refresh: bool = False) -> tuple[list[Model], str]:
    """Models carrying ``key`` from AA's own page for that index, or ``([], "")``.

    AA gives each Capability Index a keyless page (``/models/capabilities/<slug>``,
    a curated ~26-model chart set that also carries the index's sub-scores) and the
    Openness / Decision indexes a full per-model array on their eval page.  A key
    with no such page returns ``([], "")``; an unreadable page is logged and
    treated as absent so a ranking degrades instead of failing.
    """
    fn = getattr(loaders, "index_models", None)
    if not callable(fn):
        return [], ""
    try:
        models, source, published = fn(key, refresh=refresh)
    except (AAFetchError, ValueError) as exc:
        log.warning("index page for %s unavailable (%s); continuing without it", key, exc)
        return [], ""
    models = [m for m in models or [] if m.slug]
    if not models:
        return [], ""
    _call_cache().setdefault("index_page", {})[key] = (source, len(models), published)
    return models, source


def _index_page_meta(key: str) -> tuple[str, int, int]:
    """``(source, joined, published)`` recorded for ``key`` by this call's join."""
    return _call_cache().get("index_page", {}).get(key, ("", 0, 0))


def _capability_subs(model: Model, key: str) -> list[tuple[str, float]]:
    """``[(sub_key, value)]`` for capability index ``key`` on ``model`` (may be empty).

    Only the index's own page publishes sub-scores, so a model outside that page's
    chart set has none — the caller says so instead of inventing them.
    """
    prefix = f"{key}."
    return [(k, v) for k, v in sorted(model.indices.items())
            if k.startswith(prefix) and isinstance(v, (int, float))
            and not isinstance(v, bool)]


def _score_surface(key: str, refresh: bool = False) -> tuple[list[Model], str]:
    """Models carrying ``key`` from AA's own index page, eval chart set and panel(s).

    Returns ``(models, source)`` where ``source`` names the surfaces that
    contributed (e.g. ``"/models/capabilities/legal"``, ``"chart set"``,
    ``"homepage panel"``, joined with ``" + "``), or ``""`` when AA publishes no
    per-model values for ``key``.  Every surface is unioned in one pass — the
    index's own page, the eval page's chart set and the homepage panel(s) — so a
    value carried by only one of them is still reachable.  The first surface that
    carries a model keeps it, so the wider / more authoritative record wins.
    """
    scored, source = _index_page_surface(key, refresh)
    sources = [source] if source else []
    bench = catalog.BENCHMARKS.get(key)
    if bench is None or not bench.slug:
        return scored, " + ".join(sources)
    try:
        chart = _load(f"eval_{bench.slug}", loaders.eval_models, bench.slug,
                      refresh=refresh)
    except (AAFetchError, ValueError):
        chart = []
    chart_scored = [m for m in chart if select.lookup(m, key) is not None]
    if chart_scored:
        sources.append("chart set")
        have = {m.slug for m in scored}
        scored = scored + [m for m in chart_scored if m.slug not in have]
    panel = _home_rows(refresh).get(f"eval:{bench.slug}") or []
    panel_models: list[Model] = []
    for item in panel:
        if not isinstance(item, dict) or _panel_value(item, key) is None:
            continue
        model = _panel_model(item, key)
        if model.slug:
            panel_models.append(model)
    if panel_models:
        sources.append("homepage panel")
        have = {m.slug for m in scored}
        scored = scored + [m for m in panel_models if m.slug not in have]
    return scored, " + ".join(sources)


def _extra_score_models(key: str, refresh: bool = False) -> list[Model]:
    """Models carrying ``key`` from AA's eval chart set or homepage panel.

    The same source chain ``aa_benchmark_leaderboard`` uses; needed so a
    frontier works for a benchmark the leaderboard does not carry
    (e.g. the cyber boards, which AA publishes only on an eval page / panel).
    """
    models, source = _score_surface(key, refresh)
    _call_cache().setdefault("extra_source", {})[key] = (source, len(models))
    return models


def _extra_score_meta(key: str) -> tuple[str, int]:
    """``(source, scored)`` recorded for ``key`` by this call's extra join."""
    return _call_cache().get("extra_source", {}).get(key, ("", 0))


def _join_extra_scores(
    models: Sequence[Model], key: str, refresh: bool = False
) -> tuple[list[Model], str]:
    """Join AA's index-page / eval chart-set / homepage-panel values for ``key``.

    Returns ``(models, source)``; ``source`` is ``""`` when AA publishes no
    per-model surface for ``key`` (so the caller keeps its honest no-rank error).
    The merged leaderboard record is the base and the extra record is merged under it
    (same slug), so leaderboard-only columns (cost, speed, identity) survive while
    the extra score is added.  For a key that has its **own page** (a capability
    index, or the Openness / Decision index) that page is authoritative for its own
    key — and for a capability index it also supplies the sub-scores, which no
    other surface publishes.  Models AA publishes only on the extra surface are
    appended, so a ranking is never silently truncated to the rows the leaderboard
    happens to carry.
    """
    extra = _extra_score_models(key, refresh)
    if not extra:
        return list(models), ""
    own_page = key in _OWN_PAGE_KEYS
    base = {m.slug: m for m in models}
    joined: dict[str, Model] = {}
    for m in extra:
        if not m.slug:
            continue
        if m.slug not in base:
            joined[m.slug] = m
            continue
        merged = normalize.merge(m, base[m.slug])
        if own_page:
            # AA's own page for this index wins its own key (and carries the
            # sub-scores); every other field keeps the merged record's value.
            for k, v in m.indices.items():
                if v is not None:
                    merged.indices[k] = v
        joined[m.slug] = merged
    out = [joined.get(m.slug, m) for m in models]
    out += [joined[slug] for slug in joined if slug not in base]
    return out, (_extra_score_meta(key)[0] or "chart set")


def _score_label(key: str) -> str:
    """Short score label for the frontier columns (the docstring names the full one)."""
    rank = _rankable(key)
    label = str(getattr(rank, "label", "") or "").removeprefix("Artificial Analysis ")
    if not label:
        label = _metric_label(key)
    if key == "intelligence":
        label = "Intel"
    return label[:24]


def _pareto(
    score: str = "intelligence",
    x: str = "cost_per_task",
    top: int = 15,
    creator: str = "",
    open_weights: bool | None = None,
    min_intelligence: float | None = None,
    min_context: int | None = None,
    include_deprecated: bool = False,
    include_all: bool = False,
    refresh: bool = False,
    *,
    name: str = "",
    reasoning: bool | None = None,
    max_cost_per_task: float | None = None,
    max_price_in: float | None = None,
    max_price_out: float | None = None,
    vision: bool | None = None,
    min_speed: float | None = None,
    max_ttft: float | None = None,
    released_after: str = "",
    fields: Any = (),
) -> str:
    """The single Pareto implementation behind ``aa_pareto`` and ``mode=frontier``."""
    n = top if isinstance(top, int) and top > 0 else 15
    score_key = _metric_key(score, "score")
    _mixed = catalog.BENCHMARKS.get(score_key)
    if _mixed is not None and _mixed.unit == "mixed":
        raise ValueError(_breakdown_text(score_key, _mixed.label))
    score_label = _score_label(score_key)
    x_key = _pareto_axis(x)
    x_label, x_unit, x_order = _PARETO_AXES[x_key]

    rich = x_key in _OVERLAY_AXES or _rich_needed(
        refresh=refresh, sort_key=score_key, fields=x_key)
    all_models, rich_used = _models_state(refresh, rich=rich)
    if include_deprecated:
        all_models = _include_deprecated_rows(all_models, refresh)
    panel_used = False
    if not any(_metric_value(m, score_key) is not None for m in all_models):
        # join the extra source's score onto the model with the same slug so the
        # x axis (cost/size/speed) comes from the merged dataset (one join path)
        all_models, extra_source = _join_extra_scores(all_models, score_key, refresh)
        panel_used = bool(extra_source)
    models = select.filter_models(
        all_models,
        creator=creator or None,
        name=name or None,
        open_weights=open_weights,
        reasoning=reasoning,
        min_intelligence=min_intelligence,
        max_cost_per_task=max_cost_per_task,
        max_price_in=max_price_in,
        max_price_out=max_price_out,
        min_speed=min_speed,
        max_ttft=max_ttft,
        min_context=min_context,
        released_after=released_after or None,
        exclude_deprecated=not include_deprecated,
    )
    modality_known: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
    if vision is not None:
        modality_known = _modality_map(models or all_models, refresh)
        _apply_modality(models, modality_known)
        if vision is True:
            models = [m for m in models
                      if "image" in _modality_in(modality_known, m.slug)]
        else:
            models = [m for m in models
                      if _modality_in(modality_known, m.slug)
                      and "image" not in _modality_in(modality_known, m.slug)]
    where = _filter_desc(
        creator=creator, name=name, open_weights=open_weights, reasoning=reasoning,
        min_intelligence=min_intelligence, max_cost_per_task=max_cost_per_task,
        min_speed=min_speed, max_ttft=max_ttft, min_context=min_context,
        released_after=released_after, include_deprecated=include_deprecated,
        max_price_in=max_price_in, max_price_out=max_price_out, vision=vision,
    )
    if not models:
        return f"# no models match {where} — drop one filter"

    score_of: Callable[[Model], float | None] = functools.partial(
        _metric_value, key=score_key)
    x_of: Callable[[Model], float | None] = functools.partial(_axis_value, key=x_key)

    if not any(score_of(m) is not None for m in models):
        raise _no_rank_error(score_key, score_label)
    if not any(x_of(m) is not None for m in models):
        raise ValueError(_axis_missing_text(x_key, x_label))

    if x_key == "cost_per_task" and score_key not in _DERIVED_AXES:
        front = [(m, _metric_value(m, x_key), score_of(m))
                 for m in select.pareto(models, score_key=score_key, cost_key=x_key)]
    else:
        front = _pareto_frontier(models, score_of, x_of)
    if not front:
        # A board-only column (ttsQualityElo, sttEarnings22Wer, …) has rows but no
        # Intelligence-Index cost: say why instead of a bare "no model has both",
        # and never invent a cost for them (round-2 follow-up).
        board_rows = [m for rows in _board_models(refresh).values() for m in rows
                      if select.lookup(m, score_key) is not None]
        if board_rows:
            return (
                f"# frontier needs both {score_label} and {x_label} — no model has "
                f"both · {where}\n"
                f"— {score_label} is published on AA's boards ({len(board_rows)} rows: "
                "TTS voices / STT hosts / search APIs) — they are not language models "
                "and publish no Intelligence-Index cost or speed, so no frontier can "
                "be drawn. Compare them with aa_compare (aa_benchmarks lists the "
                "board's own columns)"
            )
        return (f"# frontier needs both {score_label} and {x_label} — no model has "
                f"both · {where}")

    scored = sum(1 for m in models
                 if score_of(m) is not None and x_of(m) is not None)
    shown = list(front) if include_all else front[:n]
    knee = _pareto_knee(front)
    knee_model, knee_x, knee_score = front[knee]

    cols: list[tuple[str, str]] = [
        ("name", "Model"), ("slug", "Slug"), ("creator", "Creator"),
        (score_key, score_label), (x_key, x_label),
        ("ratio", f"{score_label}/{x_label}"),
    ]
    taken = {key for key, _ in cols}
    unknown: list[str] = []
    if fields:
        cols += [c for c in _cols((), fields, (), cols, unknown) if c[0] not in taken]
    rows: list[list[str]] = []
    for m, xv, sv in shown:
        row = [_txt(m.name), m.slug, _txt(m.creator),
               _fmt(score_key, sv), _axis_text(x_key, xv),
               _ratio_text(sv / xv if xv else None)]
        row += [_fmt(key, select.lookup(m, key)) for key, _ in cols[6:]]
        rows.append(row)

    cache_name = _lb_cache()
    note = (f"{score_label} vs {x_label} (Pareto frontier, {x_order} ascending)")
    count = (f"{len(shown)} of {len(front)} frontier points"
             if len(shown) != len(front) else f"{len(front)} frontier points")
    source_label = " + ".join(part for part in (
        _source_key(), "rich dataset" if rich_used else "",
        "eval chart/panel" if panel_used else "") if part)
    head = _header(count=count, note=note, name=cache_name,
                   source_label=source_label)
    # A filter narrows the pool the frontier is computed on; label that
    # denominator as matches, exactly as the ranking tools do — the dataset size
    # (``len(all_models)``) is a different number and must not be confused with it
    # (audit round 2, M3).
    filtered = any((creator, name, open_weights is not None, reasoning is not None,
                    min_intelligence is not None, max_cost_per_task is not None,
                    min_speed is not None, max_ttft is not None, min_context is not None,
                    released_after))
    frontier_note = (f"frontier: {len(front)} non-dominated of {scored} models scored "
                     f"on both axes{' matching your filters' if filtered else ''} "
                     f"({len(all_models)} tracked")
    if not include_deprecated:
        frontier_note += ", active only"
    if len(shown) != len(front):
        frontier_note += (f"; showing the {len(shown)} cheapest, include_all=true "
                          "for the rest")
    frontier_note += ")"
    footnotes = [
        f"axes: {score_label} vs {x_label}; x unit = {x_unit}",
        frontier_note,
        (f"knee ≈ {knee_model.name}: {x_label} {_axis_text(x_key, knee_x)}, "
         f"{score_label} {_fmt(score_key, knee_score)} (5× cost/score cliff)"),
    ]
    if rich_used and x_key in _OVERLAY_AXES:
        footnotes.append(f"{x_label} is model-page data (rich dataset), not a "
                         "leaderboard column")
    if x_key == "time_per_task":
        derived = [m.short_name or m.name for m, _x, _s in shown
                   if _time_per_task_derived(m)]
        if derived:
            footnotes.append(
                "s/task for " + ", ".join(derived[:3]) + " is a recomputed mean of "
                "the per-evaluation timePerTask values (AA publishes no "
                "intelligenceIndexTimePerTask for them)")
    if panel_used:
        footnotes.append(f"{score_label} comes from AA's eval chart set / homepage "
                         "panel (top ~20), joined onto the leaderboard rows — not a "
                         "full leaderboard")
    if score_key in ("ttft", "ttfa", "e2e") or x_key == "ttft":
        footnotes.append(
            "TTFT is the leaderboard snapshot median here (aa_compare "
            "reports the model page's long-prompt median); aa_model has the "
            "per-prompt-type breakdown (short/medium/long/100k)")
    if unknown:
        footnotes.append(_unknown_field_note(unknown))
    footnotes = list(dict.fromkeys(footnotes))
    body = _table_block(head, [label for _, label in cols], rows, trim=_fields_trim(fields),
                        identity=_identity_labels(cols))
    return body + "\n" + render.note(footnotes)


# --------------------------------------------------------------------------- #
# aa_leaderboard
# --------------------------------------------------------------------------- #

_LB_COLS = [
    ("name", "Model"), ("slug", "Slug"), ("creator", "Creator"),
    ("intelligence", "Intel"), ("cost_per_task", "$/Task"),
    ("tps", "tok/s"), ("ttft", "TTFT"), ("context_tokens", "Ctx"),
]
#: fields accepted in `fields=` that are not leaderboard metrics (shown as `-`)
_LB_EXTRA = ("precision", "modalities_in", "modalities_out")
#: leaderboard field -> the ``aa_model`` section that actually carries it. These
#: values are never in the leaderboard payload, so an all-``-`` column must say
#: where it lives instead of implying AA has no data (round-2 audit P2).
_PAGE_ONLY_FIELD_SECTIONS = {
    "params_b": "specs", "active_params_b": "specs", "license": "specs",
    "license_url": "specs", "weights_url": "specs", "knowledge_cutoff": "specs",
    "size_class": "specs", "modalities_in": "modalities",
    "modalities_out": "modalities",
}


def _page_only_sections(key: str) -> str:
    """The model-page section that carries ``key`` (``""`` when it is leaderboard-native)."""
    section = _PAGE_ONLY_FIELD_SECTIONS.get(key)
    if section:
        return section
    bench = catalog.BENCHMARKS.get(key)
    if bench is not None and getattr(bench, "source_hint", "") == "rich":
        return "benchmarks"
    return ""


def _page_only_map(cols: Sequence[tuple[str, str]]) -> dict[str, str]:
    """``{column label: aa_model section}`` for requested page-only columns."""
    out: dict[str, str] = {}
    for key, label in cols:
        section = _page_only_sections(key)
        if section:
            out[label] = section
    return out


#: identity columns always rendered, before any requested `fields=`
_LB_IDENTITY = [("name", "Model"), ("slug", "Slug")]
_BENCH_IDENTITY = [("name", "Model"), ("slug", "Slug")]
_PROV_IDENTITY = [("host", "Host"), ("model_name", "Model")]


#: ``aa_leaderboard sort=`` tokens that mean "rank by value" (score per $/task)
_VALUE_SORT_RAW = {"intel/$", "intel/1$", "$/intel", "intel per $", "intel per dollar",
                   "intelligence per dollar", "intelligence/$"}
_VALUE_SORT_NORM = {"value", "intelpercost", "intelperdollar", "intelligenceperdollar",
                    "intelperusd", "intelper1usd", "intelligencedollar", "bestvalue"}


def _leaderboard(
    mode: str = "rank",
    sort: str = "intelligence",
    fields: str = "",
    top: int = 10,
    creator: str = "",
    name: str = "",
    open_weights: bool | None = None,
    reasoning: bool | None = None,
    min_intelligence: float | None = None,
    max_cost_per_task: float | None = None,
    max_price_in: float | None = None,
    max_price_out: float | None = None,
    vision: bool | None = None,
    min_speed: float | None = None,
    max_ttft: float | None = None,
    min_context: int | None = None,
    released_after: str = "",
    include_deprecated: bool = False,
    refresh: bool = False,
) -> str:
    if mode not in ("rank", "value", "frontier"):
        raise ValueError(
            f"unknown mode {_q(mode)} — expected rank, value or frontier"
        )
    n = top if isinstance(top, int) and top > 0 else 10
    # an explicit "best value" sort token switches to the value ranking
    # (score per $/task) instead of erroring as an unknown sort key.
    sort_raw = str(sort).strip()
    value_sort = (sort_raw.lower() in _VALUE_SORT_RAW
                  or _norm_alias(sort_raw) in _VALUE_SORT_NORM)
    if value_sort:
        if mode == "rank":
            mode = "value"
        sort_key = _metric_key("intelligence", "sort")
    else:
        sort_key = _metric_key(sort, "sort")
    _mixed = catalog.BENCHMARKS.get(sort_key)
    if _mixed is not None and _mixed.unit == "mixed":
        raise ValueError(_breakdown_text(sort_key, _mixed.label))
    if mode == "frontier":
        # one implementation for both surfaces (aa_pareto and mode=frontier)
        return _pareto(
            score=sort_key, x="cost_per_task", top=n, creator=creator, name=name,
            open_weights=open_weights, reasoning=reasoning,
            min_intelligence=min_intelligence, max_cost_per_task=max_cost_per_task,
            max_price_in=max_price_in, max_price_out=max_price_out, vision=vision,
            min_speed=min_speed, max_ttft=max_ttft, min_context=min_context,
            released_after=released_after, include_deprecated=include_deprecated,
            refresh=refresh, fields=fields,
        )
    label = _metric_label(sort_key)

    all_models, rich_used = _models_state(
        refresh, rich=_rich_needed(refresh=refresh, sort_key=sort_key, fields=fields))
    if include_deprecated:
        all_models = _include_deprecated_rows(all_models, refresh)
    tracked = len(all_models) if include_deprecated else len(_lb_rows(refresh))
    # One uniform ranking path: a sort key (or a requested field) whose per-model
    # values live on AA's eval chart set / homepage panel is joined by slug before
    # filtering, exactly like a leaderboard-native column (wave F).
    extra_source = ""
    sort_source = ""
    wanted = [sort_key]
    for field in _split(fields):
        try:
            wanted.append(_metric_key(field, "field"))
        except ValueError:
            continue
    for key in dict.fromkeys(wanted):
        # A key AA publishes on its own index page is always joined: that page is
        # authoritative for its own key and carries the capability sub-scores,
        # which the leaderboard/rich rows never do.
        if key not in _OWN_PAGE_KEYS and any(
                select.lookup(m, key) is not None for m in all_models):
            continue
        joined, source = _join_extra_scores(all_models, key, refresh)
        if not source:
            continue
        all_models = joined
        extra_source = extra_source or source
        if key == sort_key:
            sort_source = source
    models = select.filter_models(
        all_models,
        creator=creator or None,
        name=name or None,
        open_weights=open_weights,
        reasoning=reasoning,
        min_intelligence=min_intelligence,
        max_cost_per_task=max_cost_per_task,
        max_price_in=max_price_in,
        max_price_out=max_price_out,
        min_speed=min_speed,
        max_ttft=max_ttft,
        min_context=min_context,
        released_after=released_after or None,
        exclude_deprecated=not include_deprecated,
    )
    modality_known: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
    wants_modality = any(
        _norm_alias(name) in ("modalities", "modality", "modalitiesin",
                              "modalitiesout", "modin", "modout", "inputmodalities",
                              "outputmodalities")
        or _is_wildcard_field(name)
        for name in _split(fields))
    if vision is not None or wants_modality:
        modality_known = _modality_map(models or all_models, refresh)
        _apply_modality(models, modality_known)
        if vision is True:
            models = [m for m in models
                      if "image" in _modality_in(modality_known, m.slug)]
        elif vision is False:
            models = [m for m in models
                      if _modality_in(modality_known, m.slug)
                      and "image" not in _modality_in(modality_known, m.slug)]
    where = _filter_desc(
        creator=creator, name=name, open_weights=open_weights, reasoning=reasoning,
        min_intelligence=min_intelligence, max_cost_per_task=max_cost_per_task,
        min_speed=min_speed, max_ttft=max_ttft, min_context=min_context,
        released_after=released_after, include_deprecated=include_deprecated,
        max_price_in=max_price_in, max_price_out=max_price_out, vision=vision,
    )
    cache_name = _lb_cache()
    explicit = any((creator, name, open_weights is not None, reasoning is not None,
                    min_intelligence is not None, max_cost_per_task is not None,
                    max_price_in is not None, max_price_out is not None,
                    vision is not None,
                    min_speed is not None, max_ttft is not None,
                    min_context is not None, released_after))

    if not models:
        out = f"# no models match {where} — drop one filter"
        if modality_known:
            out += "\n" + render.note([_modality_note(
                modality_known, len(all_models), vision)])
        if sort_key in _CAPABILITY_KEYS:
            # the coverage describes the dataset, so it survives a filter that
            # matches nothing (the empty-result note alone would hide it)
            out += "\n" + render.note([_capability_coverage_note(
                sort_key, label, all_models, include_deprecated=include_deprecated,
                rich_used=rich_used)])
        return out

    # A sort key the merged source cannot supply must explain itself, never
    # silently reorder (the rich overlay already covers capability/Elo fields).
    if not any(select.lookup(m, sort_key) is not None for m in models):
        if explicit:
            # A name/filter matched rows (e.g. a deprecated release that only the
            # release array names) but the sort key has no value for any of them:
            # list the matches honestly instead of claiming the whole metric is
            # absent.  Nothing is ranked, so the header says so.
            unknown_fields: list[str] = []
            cols = _cols(_LB_COLS, fields, _LB_EXTRA, _LB_IDENTITY, unknown_fields)
            shown = models[:n]
            head = _header(
                count=f"{len(shown)} shown of {len(models)} matching "
                      f"({tracked} tracked)",
                note=f"{label} has no ranked values for these rows; listing "
                     "identity only, " + where,
                name=cache_name, source_label=_prov_label(rich_used))
            body = _table_block(
                head, [label for _, label in cols],
                [_model_cells(m, cols, None) for m in shown],
                trim=_fields_trim(fields), identity=_identity_labels(cols),
                page_only=_page_only_map(cols))
            extra_notes = ([_unknown_field_note(unknown_fields)]
                           if unknown_fields else [])
            if modality_known:
                extra_notes.append(_modality_note(
                    modality_known, len(all_models), vision))
            return body + ("\n" + render.note(extra_notes) if extra_notes else "")
        if (not include_deprecated
                and any(select.lookup(m, sort_key) is not None for m in all_models)):
            raise ValueError(_deprecated_only_text(sort_key, label))
        raise _no_rank_error(sort_key, label)

    footnotes: list[str] = _missing_notes(all_models, [
        ("intelligence", "intelligence", min_intelligence is not None),
        ("cost_per_task", "cost per task", max_cost_per_task is not None),
        ("tps", "output speed", min_speed is not None),
        ("ttft", "TTFT", max_ttft is not None),
        ("context_tokens", "context window", min_context is not None),
    ])
    if modality_known:
        footnotes.append(_modality_note(modality_known, len(all_models), vision))
    value_of: Callable[[Model], float | None] | None = None
    unknown: list[str] = []
    if mode == "value":
        pairs = [(m, v) for m, v in _value_pairs(models, sort_key) if v is not None]
        pairs.sort(key=lambda t: t[1], reverse=True)
        models = _break_display_ties([m for m, _ in pairs],
                                     lambda m: render.num(_value_of(m, sort_key), 1))
        value_of = functools.partial(_value_of, score_key=sort_key)
        cols = _cols(_LB_COLS + [("value", f"{label}/$")], fields, _LB_EXTRA,
                     _LB_IDENTITY, unknown)
        note = f"value = {label} per $/task"
        if value_sort:
            note += f" (sort={sort_raw})"
        note += f", {where}"
        footnotes += _missing_notes(all_models, [("cost_per_task", "cost per task", True)])
    else:
        # a rank table lists only the models the key actually scored — an
        # unscored row would sort last with a "-" and inflate the coverage claim
        models = [m for m in select.sort_models(models, sort_key)
                  if select.lookup(m, sort_key) is not None]
        # rows that *display* the same value are ordered by a named secondary key
        # (G7), so a tie is reproducible instead of following AA's payload order
        models = _break_display_ties(
            models, lambda m: _fmt(sort_key, select.lookup(m, sort_key)))
        cols = _cols(_LB_COLS, fields, _LB_EXTRA, _LB_IDENTITY, unknown)
        note = f"{label}, {where}"
        tie_note = _tie_note(
            models[:n], lambda m: _fmt(sort_key, select.lookup(m, sort_key)),
            unit="/task" if sort_key == "cost_per_task" else "")
        if tie_note:
            footnotes.append(tie_note)

    if not fields:
        keys = {c[0] for c in cols}
        if sort_key not in keys:
            cols.append((sort_key, label))

    if not fields and n > 15:
        cols = [c for c in cols if c[0] != "creator"]

    # `cost` is $/task on this surface; keep the unit visible next to `out $/M`.
    cols = [(key, "$/Task" if key == "cost_per_task" and label == "Cost" else label)
            for key, label in cols]

    shown = models[:n]
    if sort_key in ("ttft", "ttfa", "e2e"):
        footnotes.append(
            f"{label} is the leaderboard snapshot median (aa_compare "
            "reports the model page's long-prompt median); use aa_model for the "
            "per-prompt-type breakdown (short/medium/long/100k)"
        )
    if unknown:
        footnotes.append(_unknown_field_note(unknown))
    for key, _lbl in cols:
        if key in _COMPARE_USD_KEYS:
            zero_note = _zero_cost_note(key, [
                (m.short_name or m.name, _compare_numeric(m, key),
                 bool(m.is_open_weights)) for m in shown])
            if zero_note:
                footnotes.append(zero_note)

    matching = len(models)
    sort_scored = sum(1 for m in models if select.lookup(m, sort_key) is not None)
    if sort_source:
        source, page_joined, page_published = _index_page_meta(sort_key)
        if page_joined:
            count = f"{page_joined} model" + ("" if page_joined == 1 else "s")
            if page_published > page_joined:
                count += f" of the {page_published} rows it publishes"
            # the capability note below states the coverage for its own key; for
            # every other surface the dataset count belongs here (never the
            # filtered view's)
            if sort_key not in _CAPABILITY_KEYS:
                count += f", {_dataset_scored(all_models, sort_key)} scored in the dataset"
            footnotes.append(
                f"{label} comes from {sort_source} ({count}), joined onto the "
                "leaderboard rows"
            )
        else:
            footnotes.append(
                f"{label} comes from {sort_source} "
                f"({_dataset_scored(all_models, sort_key)} scored in the dataset), "
                "joined onto the leaderboard rows"
            )
    if sort_key in _CAPABILITY_KEYS:
        footnotes.append(_capability_coverage_note(
            sort_key, label, all_models, include_deprecated=include_deprecated,
            shown=shown, rich_used=rich_used))
    if explicit:
        # the coverage above is the dataset's; the filter's effect is a separate,
        # clearly labelled count
        match_note = _filter_match_note(
            sort_scored,
            _dataset_scored(
                select.filter_models(all_models,
                                     exclude_deprecated=not include_deprecated),
                sort_key),
            explicit)
        if match_note:
            footnotes.append(match_note)
    if mode == "value":
        count = (f"{len(shown)} of {matching} scored by value "
                 f"({tracked} tracked)")
    elif explicit:
        count = (f"{len(shown)} shown of {matching} matching "
                 f"({tracked} tracked)")
    else:
        count = f"{len(shown)} of {sort_scored} scored ({tracked} tracked)"
    source_label = _prov_label(rich_used)
    if extra_source:
        source_label = f"{source_label} + {extra_source}"
    head = _header(count=count, note=note, name=cache_name,
                   source_label=source_label)
    out = [_table_block(head, [label for _, label in cols],
                        [_model_cells(m, cols, value_of) for m in shown],
                        trim=_fields_trim(fields), identity=_identity_labels(cols),
                        page_only=_page_only_map(cols))]
    footnotes = list(dict.fromkeys(footnotes))
    if footnotes:
        out.append(render.note(footnotes))
    return "\n".join(part for part in out if part)


# --------------------------------------------------------------------------- #
# aa_model
# --------------------------------------------------------------------------- #

_INDEX_ORDER = ("intelligence", "coding", "agentic", "openness", "omniscience",
                "decisionIndex")
_SECTIONS = ("identity", "indexes", "benchmarks", "pricing", "speed",
             "cost", "openness", "modalities")


def _model_facts(m: Model) -> str:
    """One-line fact strip; scraped text is sanitized to a single safe line."""
    parts = [render.clean(_txt(m.creator))]
    if m.release_date:
        parts.append(f"released {render.clean(m.release_date)}")
    if m.params_b:
        parts.append(f"{render.num(m.params_b, 0)}B params")
    if m.active_params_b:
        parts.append(f"{render.num(m.active_params_b, 0)}B active")
    if m.context_tokens:
        parts.append(f"{render.ctx(m.context_tokens)} ctx")
    if m.modalities_in or m.modalities_out:
        mods = "+".join(render.clean(x, 24) for x in m.modalities_in) or "?"
        mods += "→" + ("+".join(render.clean(x, 24) for x in m.modalities_out) or "?")
        parts.append(mods)
    if m.is_reasoning:
        parts.append("reasoning"
                     + (f" ({render.clean(m.effort)})" if m.effort else ""))
    parts.append(
        "open-weights" + (f" · {render.clean(m.license)}" if m.license else "")
        if m.is_open_weights else "closed"
    )
    if m.deprecated:
        parts.append("deprecated"
                     + (f" → {render.clean(m.deprecated_to)}" if m.deprecated_to else ""))
    return " · ".join(parts)


def _model_indices(m: Model) -> str:
    rows: list[list[str]] = []
    for key in _INDEX_ORDER:
        value = select.lookup(m, key)
        if value is None:
            continue
        metric = catalog.metric(key)
        label = metric.label if metric else key
        if key == "intelligence" and m.estimated:
            label += "*"
        rows.append([label, _fmt(key, value)])
    if not rows:
        return "no index scores for this model"
    body = render.table(["Index", "Score"], rows)
    missing = [label for key, label in (("coding", "Coding Index"),
                                        ("agentic", "Agentic Index"))
               if select.lookup(m, key) is None]
    if missing:
        body += (
            "\n— " + ", ".join(missing) + ": AA publishes these composites only "
            "through its paid data API, so no free page carries a per-model value. "
            "The free constituents are rankable — aa_benchmarks query=coding "
            "(SciCode, LiveCodeBench, FrontierCode, Terminal-Bench, τ²-Bench)"
        )
    return body


_CAP_LABELS = {
    "financeAndAccounting": "Finance & Accounting",
    "strategyAndOps": "Strategy & Ops",
    "legal": "Legal",
    "healthcareAndMedical": "Healthcare & Medical",
    "engineering": "Engineering",
    "economics": "Economics",
}


def _dataset_scored(models: Sequence[Model], key: str) -> int:
    """How many models in a dataset carry ``key``.

    Coverage is always measured over a whole dataset, never over a filtered view:
    a filter must not be able to shrink the published coverage claim (an empty or
    narrow filter would otherwise report "1 of 703 scored" as if that were the
    index's coverage).
    """
    return sum(1 for m in models if select.lookup(m, key) is not None)


def _capability_coverage_note(
    key: str, label: str, dataset: Sequence[Model], *,
    include_deprecated: bool, shown: Sequence[Model] | None = None,
    rich_used: bool = True,
) -> str:
    """The honest coverage line for one capability index.

    States how many variants in the **dataset** carry a value (plus the active
    count when deprecation filtering would hide some), then how many of the rows
    actually shown have sub-scores on the index's own page.  When the rich
    model-page overlay is not loaded the dataset only holds the index's own
    chart set, so the count is qualified as "in the data available" instead of
    reading as AA's full coverage (audit round 2).
    """
    page = loaders.CAPABILITY_INDEXES.get(key, "")
    scored = _dataset_scored(dataset, key)
    active = _dataset_scored(
        select.filter_models(dataset, exclude_deprecated=not include_deprecated), key)
    scope = "" if rich_used else (
        " in the data available (the rich model-page overlay is not loaded)")
    text = f"{label}: {scored} of {len(dataset)} tracked variants have a value{scope}"
    if active != scored:
        text += f" ({active} active)"
    text += (f"; the index's own page (/models/capabilities/{page}) publishes "
             "its sub-scores")
    if shown is None:
        return text
    subs = sum(1 for m in shown if _capability_subs(m, key))
    text += f" for {subs} of the {len(shown)} rows shown"
    if not subs:
        # Zero sub-scores means either "this model is not on the chart set" or
        # "the page could not be read this call" — say which, so an unreadable
        # page is never reported as an absent model (audit round 2, L1).
        if _index_page_meta(key)[0]:
            text += " (none of these is on that page's chart set)"
        else:
            text += (" (that page could not be read this call — sub-scores "
                     "unavailable)")
    return text


def _filter_match_note(scored: int, available: int, explicit: bool) -> str:
    """The post-filter count, labelled as matches — never as coverage."""
    if not explicit or scored >= available:
        return ""
    return f"{scored} of {available} scored models match your filters"


def _capability_page_subs(key: str, slug: str,
                          refresh: bool = False) -> tuple[list[tuple[str, float]], bool]:
    """``(sub-scores for slug, page_was_readable)`` from the index's own page.

    The sub-scores are published on that page alone, so this is the only way to
    read them.  ``page_was_readable`` is False when the page could not be fetched
    or parsed, so a caller can tell "this model is not on the chart set" from "the
    page is unavailable" instead of asserting the wrong one (audit round 2, L1).
    """
    if not slug:
        return [], True
    fn = getattr(loaders, "capability_models", None)
    if not callable(fn):
        return [], False
    try:
        rows = fn(key, refresh=refresh)
    except (AAFetchError, ValueError) as exc:
        log.warning("capability page for %s unavailable (%s)", key, exc)
        return [], False
    for row in rows:
        if row.slug == slug:
            return _capability_subs(row, key), True
    return [], True


def _model_capabilities(m: Model, refresh: bool = False) -> str | None:
    """The six AA Capability Indexes for one model, plus their sub-scores.

    Scores come from the merged record (the model page's chart set / the rich
    dataset); the sub-scores come from each index's own page
    (``/models/capabilities/<slug>``), which is the only surface that publishes
    them.  An index the model has a score for but whose page does not list it has
    no sub-scores, and the footer says so — distinguishing a model that is absent
    from the chart set from a page that could not be read.
    """
    rows: list[list[str]] = []
    sub_lines: list[str] = []
    without: list[str] = []
    unreadable: list[str] = []
    for key in sorted(_CAPABILITY_KEYS):
        value = m.indices.get(key)
        if value is None:
            continue
        name = _CAP_LABELS.get(key.split(".", 1)[1], key.split(".", 1)[1])
        rows.append([name, _fmt(key, value)])
        subs = _capability_subs(m, key)
        page_read = True
        if not subs:
            subs, page_read = _capability_page_subs(key, m.slug, refresh)
        if not subs:
            (without if page_read else unreadable).append(name)
            continue
        sub_lines.append(f"{name}: {_sub_scores_text(subs)}")
    if not rows:
        return None
    body = render.table(["Capability index", "Score"], rows)
    if sub_lines:
        # a table cell is capped at 120 chars, which would truncate the six
        # sub-scores of the widest index; one line per index keeps them complete
        body += ("\n— sub-scores, from each index's own page "
                 "(/models/capabilities/<slug>):\n  " + "\n  ".join(sub_lines))
    if without:
        body += ("\n— no sub-scores for " + ", ".join(without)
                 + ": AA publishes them only on that index's own page, which does "
                   "not list this model")
    if unreadable:
        body += ("\n— no sub-scores for " + ", ".join(unreadable)
                 + ": that index's own page could not be read this call — retry "
                   "with refresh=true, or read the index page directly")
    body += ("\n— the six capability indexes are rankable: "
             "aa_leaderboard sort=capabilities.legal (any of the six)")
    return body


def _sub_scores_text(subs: Sequence[tuple[str, float]]) -> str:
    """One compact cell for a capability index's sub-scores (empty when none)."""
    if not subs:
        return "-"
    return " · ".join(
        f"{loaders.CAPABILITY_SUBLABELS.get(key.rsplit('.', 1)[-1], key.rsplit('.', 1)[-1])} "
        f"{render.num(value, 1)}"
        for key, value in subs
    )


def _model_chart_evals(slug: str, have: set[str],
                       refresh: bool = False) -> dict[str, float]:
    """Chart-set / panel benchmark scores AA publishes for ``slug`` but that are
    absent from its rich record (the cyber boards, AA-3D, …).

    The same source chain ``aa_compare`` / ``aa_pareto`` join; only benchmarks AA
    serves from an eval chart set or homepage panel are probed, so a model page
    never fans out over the leaderboard.
    """
    try:
        panel_slugs = {key.split(":", 1)[1] for key in _home_rows(refresh)
                       if key.startswith("eval:")}
    except (AAFetchError, ValueError):
        panel_slugs = set()
    out: dict[str, float] = {}
    for key, bench in catalog.BENCHMARKS.items():
        if key in have or not bench.slug or bench.source_hint == "none":
            continue
        if bench.source_hint != "chart" and bench.slug not in panel_slugs:
            continue
        rank = _rankable(key)
        if rank is None or str(getattr(rank, "unit", "")) == "text":
            continue
        for m in _extra_score_models(key, refresh):
            if m.slug == slug:
                value = _rankable_value(m, key)
                if value is not None:
                    out[key] = value
                break
    return out


def _model_benchmarks(m: Model, refresh: bool = False) -> str | None:
    rows: list[list[str]] = []
    seen: set[str] = set()

    def add(key: str, value: Any) -> None:
        bench = catalog.benchmark(key)
        canonical = bench.key if bench is not None else key
        if canonical in seen:
            return  # alias keys (e.g. itbenchSre / itBenchSre) collapse to one row
        seen.add(canonical)
        label = bench.label if bench else key
        if bench is not None and bench.unit == "Elo":
            label += " (Elo)"
        rows.append([label, _fmt(canonical, value)])

    for key, value in m.evals.items():
        if value is not None:
            add(key, value)
    chart = _model_chart_evals(m.slug, set(m.evals), refresh)
    for key, value in chart.items():
        add(key, value)
    if not rows:
        return None
    table = render.table(["Eval", "Score"], rows)
    if chart:
        table += "\n" + render.note([
            f"{len(chart)} published score(s) joined from AA's eval chart set / "
            "homepage panel (not on the rich record)"])
    return table


_PROMPT_TYPES = (("short", "short"), ("medium", "medium"), ("long", "long"),
                 ("hundredK", "100k"))


def _prompt_speed(slug: str) -> str | None:
    """TTFT (median time-to-first-chunk) per prompt type, from the model page.

    The headline TTFT is the long-prompt median; the chart record breaks it out
    by ``performanceByPromptType`` (short/medium/long/hundredK).

    ``loaders.model`` has already fetched (and cached) this page in the same
    call, so read it back from disk rather than re-downloading it (audit M).
    """
    try:
        path = loaders.SOURCE_URLS["model"].format(slug=slug)
        name = f"model_{slug}"
        # `loaders.model` fetched this page earlier in the same call, so read the
        # freshly written file instead of downloading it again (audit M/B6).
        text = _get(loaders.url(path), name, refresh=not _already_fetched(name)).text
        records = flight.find_array(
            flight.payload(text), ("chartDefaultSelected", "releaseDate", "suffix")
        )
    except Exception:  # pragma: no cover - best-effort enrichment
        return None
    record = next((r for r in records
                   if isinstance(r, dict) and r.get("slug") == slug), None)
    if record is None:
        return None
    by_prompt = record.get("performanceByPromptType")
    if not isinstance(by_prompt, dict):
        return None
    parts = []
    for key, label in _PROMPT_TYPES:
        entry = by_prompt.get(key)
        if isinstance(entry, dict) and entry.get("medianTimeToFirstChunk") is not None:
            parts.append(f"{label} {render.num(entry['medianTimeToFirstChunk'], 1)}s")
    return "TTFT by prompt: " + " · ".join(parts) if parts else None


def _model_pricing(m: Model) -> str:
    p = m.pricing
    rows = [
        ["In $/1M", _fmt("price_in", p.get("in"))],
        ["Out $/1M", _fmt("price_out", p.get("out"))],
        ["Cache read $/1M", _fmt("cache_read", p.get("cache_read"))],
        ["Cache write $/1M", _fmt("cache_write", p.get("cache_write"))],
        ["Cache discount", _discount(p.get("cache_hit_discount"))],
        ["$/task", _fmt("cost_per_task", m.cost_per_task)],
    ]
    if all(row[1] == "-" for row in rows):
        return "no pricing recorded"
    body = render.table(["Pricing", "Value"], rows)
    zeros = [_zero_cost_note(key, [(str(m.name or m.slug), value,
                                    bool(m.is_open_weights))])
             for key, value in (("cost_per_task", m.cost_per_task),
                                ("price_in", p.get("in")),
                                ("price_out", p.get("out")))]
    zeros = [note for note in dict.fromkeys(zeros) if note]
    if zeros:
        body += "\n" + render.note(zeros)
    return body


def _model_speed(m: Model) -> str:
    s = m.speed
    rows = [
        ["tok/s", _fmt("tps", s.get("tps"))],
        ["TTFT", _fmt("ttft", s.get("ttft"))],
        ["TTFA", _fmt("ttfa", s.get("ttfa"))],
        ["E2E", _fmt("e2e", s.get("e2e"))],
        ["Reasoning", _fmt("reasoning_s", s.get("reasoning_s"))],
        ["Tokens/task", _fmt("out_tokens_per_task", s.get("out_tokens_per_task"))],
    ]
    if s.get("reasoning_tokens") is not None:
        rows.append(["Reasoning tokens", f"{s['reasoning_tokens']:,.0f}"])
    if all(row[1] == "-" for row in rows):
        return "no speed measurements recorded"
    return render.table(["Speed", "Value"], rows)


def _model_cost(m: Model) -> str | None:
    parts: list[str] = []
    if m.cost_breakdown:
        per_task = [[k, _fmt("cost_per_task", v)] for k, v in m.cost_breakdown.items()
                    if v is not None and not k.endswith("_total")]
        totals = [[k, _fmt("cost_per_task", v)] for k, v in m.cost_breakdown.items()
                  if v is not None and k.endswith("_total")]
        if per_task:
            parts.append(render.table(["Cost component", "$/task"], per_task))
        if totals:
            parts.append(render.table(["Whole-suite total", "USD"], totals))

    per_eval = getattr(m, "per_eval", None) or m.per_eval_cost
    if per_eval:
        norm = []
        for entry in per_eval:
            if not isinstance(entry, dict):
                continue
            score = entry.get("score", entry.get("weighted_cost_per_task"))
            cost = entry.get("costPerTask", entry.get("weighted_cost_per_task"))
            norm.append({
                "slug": entry.get("slug"),
                "score": score,
                "cost": cost,
                "time": entry.get("timePerTask"),
                "tokens": entry.get("outputTokensPerTask"),
            })
        norm = [e for e in norm if e["score"] is not None or e["cost"] is not None]
        norm.sort(key=lambda e: -(e["cost"] or 0.0))
        if norm:
            rows = []
            for e in norm[:8]:
                score = e["score"]
                if score is None:
                    score_txt = "-"
                elif abs(float(score)) <= 1:
                    score_txt = f"{float(score):.3f}"
                else:
                    score_txt = f"{float(score):.0f}"
                rows.append([
                    e["slug"] or "-", score_txt,
                    _fmt("cost_per_task", e["cost"]),
                    render.num(e["time"], 1) if e["time"] is not None else "-",
                    render.num(e["tokens"], 0) if e["tokens"] is not None else "-",
                ])
            parts.append(render.table(
                ["Eval", "Score", "$/task", "Time s", "Tokens"], rows))
    return "\n".join(parts) if parts else None


def _model_openness(m: Model) -> str:
    rows = [
        ["Open weights", _fmt("is_open_weights", m.is_open_weights)],
        ["License", _txt(m.license)],
        ["License URL", _txt(m.license_url)],
        ["Weights URL", _txt(m.weights_url)],
        ["Knowledge cutoff", _txt(m.knowledge_cutoff)],
        ["Size class", _txt(m.size_class)],
        ["Params (B)", _fmt("params_b", m.params_b)],
        ["Active params (B)", _fmt("active_params_b", m.active_params_b)],
    ]
    return render.table(["Openness", "Value"], rows)


def _model_modalities(m: Model) -> str:
    rows = [
        ["Input", ", ".join(m.modalities_in) or "-"],
        ["Output", ", ".join(m.modalities_out) or "-"],
        ["Reasoning", _fmt("is_reasoning", m.is_reasoning)],
        ["Effort", _txt(m.effort)],
    ]
    return render.table(["Modalities", "Value"], rows)


#: Numeric fields a leaderboard row owns. AA's derived variant slugs
#: (``gpt-6-luna-high``) are real records, but ``/models/<variant>`` 308s to the
#: base release page, whose record can be the *default* variant. The row is the
#: only source that is guaranteed to describe the requested variant, so it wins.
_LB_OWNED_FIELDS = ("intelligence", "cost_per_task", "context_tokens")
_LB_OWNED_PRICING = ("price_in", "price_out")
_LB_OWNED_SPEED = ("tps", "ttft")


def _page_is_other_variant(record: Model | None, base: Model) -> bool:
    """True when a loaded model page describes a different (the default) variant."""
    if record is None:
        return False
    return record.slug != base.slug or record.name != base.name


def _variant_model(base: Model, record: Model) -> tuple[Model, str]:
    """Page for identity/benchmarks, leaderboard row for the variant's numerics.

    A variant page that redirects to the release page may carry the default
    variant's measurements. Keep the page's richer identity/benchmark data, but
    never let it supply the numbers the requested variant's row owns — and say
    which remaining values are page-level/default-variant.
    """
    model = normalize.merge(base, record)
    if base.name:
        model.name = base.name
    if base.effort:
        model.effort = base.effort
    if base.release_date:
        model.release_date = base.release_date
    for name in _LB_OWNED_FIELDS:
        setattr(model, name, getattr(base, name))
    pricing = dict(model.pricing or {})
    for key in _LB_OWNED_PRICING:
        value = (base.pricing or {}).get(key)
        if value is None:
            pricing.pop(key, None)
        else:
            pricing[key] = value
    model.pricing = pricing
    speed = dict(model.speed or {})
    for key in _LB_OWNED_SPEED:
        value = (base.speed or {}).get(key)
        if value is None:
            speed.pop(key, None)
        else:
            speed[key] = value
    model.speed = speed
    note = (
        f"page-level, default variant ({render.clean(record.name)}) — benchmarks "
        "and cost breakdown come from the release page; intelligence, $/task, "
        "tok/s, TTFT, context and input/output price come from this variant's "
        f"leaderboard row (aa.{base.slug})")
    return model, note


def _model(query: str, sections: str = "", refresh: bool = False) -> str:
    models = _models(refresh)
    base = _resolve_slug(query, models)
    slug = base.slug
    record = _load(f"model_{slug}", loaders.model, slug, refresh=refresh).get(slug)
    page_other = _page_is_other_variant(record, base)
    variant_note = ""
    if page_other or (_EFFORT_SUFFIX_RE.search(slug) is not None
                      and record is not None):
        # a variant row's own numbers always win; only a page that describes a
        # *different* variant needs the provenance label
        model, variant_note = _variant_model(base, record)
        if not page_other:
            variant_note = ""
    else:
        model = normalize.merge(base, record) if record is not None else base

    chosen = _split(sections)
    if not chosen:
        chosen = ["identity", "indexes", "benchmarks", "pricing", "speed"]
    section_aliases = {"specs": "identity", "spec": "identity",
                       "specification": "identity", "specifications": "identity"}
    chosen = [section_aliases.get(s.strip().lower(), s.strip().lower()) for s in chosen]
    if "all" in chosen:
        chosen = list(_SECTIONS)
    bad = [s for s in chosen if s not in _SECTIONS]
    if bad:
        raise ValueError(
            f"unknown section(s) {', '.join(bad)} — valid: {', '.join(_SECTIONS)}, "
            "all (alias: specs = identity)"
        )

    as_of, stale = _fresh(f"model_{slug}")
    head = (f"# {render.clean(model.name)} · {render.clean(_txt(model.creator))} "
            f"· aa.{render.clean(slug, 80)}")
    if as_of is not None:
        head += f" · {'stale: ' + render.ago(as_of) if stale else render.ago(as_of)}"
    head += f" · aa:{_source_key()}"

    blocks = [head, _model_facts(model)]
    name_notes = _name_notes(query, base, models)
    if base.deprecated:
        target = f" → {base.deprecated_to}" if base.deprecated_to else ""
        name_notes.append(
            f"known deprecated release{target} — it is not in the active pool, so "
            f"ranked tools hide it (page /models/{base.slug})")
    if name_notes:
        blocks.append(render.note(name_notes))
    if variant_note:
        blocks.append(render.note([variant_note]))
    if "indexes" in chosen:
        blocks.append("## Indices\n" + _model_indices(model))
        caps = _model_capabilities(model, refresh)
        if caps:
            blocks.append("## Capability indexes\n" + caps)
    if "benchmarks" in chosen:
        table = _model_benchmarks(model, refresh)
        if table:
            blocks.append("## Benchmarks\n" + table)
    if "pricing" in chosen:
        blocks.append("## Pricing\n" + _model_pricing(model))
    if "speed" in chosen:
        speed_block = "## Speed\n" + _model_speed(model)
        if (record is not None and not page_other
                and any(v is not None for v in (record.speed or {}).values())):
            speed_block += (
                "\n— speed from the model page (first-party measurement); "
                "aa_leaderboard reports the leaderboard snapshot and may differ slightly"
            )
        by_prompt = _prompt_speed(slug)
        if by_prompt:
            speed_block += "\n— " + by_prompt
        blocks.append(speed_block)
    if "cost" in chosen:
        cost = _model_cost(model)
        if cost:
            blocks.append("## Cost per task\n" + cost)
    if "openness" in chosen:
        blocks.append("## Openness\n" + _model_openness(model))
    if "modalities" in chosen:
        blocks.append("## Modalities\n" + _model_modalities(model))
    return "\n\n".join(blocks)


# --------------------------------------------------------------------------- #
# aa_compare
# --------------------------------------------------------------------------- #

_COMPARE_ROWS = [
    ("intelligence", "Intelligence"), ("value", "Intel/$"),
    ("cost_per_task", "$/task"),
    ("price_in", "In $/1M"), ("price_out", "Out $/1M"),
    ("tps", "tok/s"), ("ttft", "TTFT"), ("context_tokens", "Context"),
]
_COMPARE_FULL = _COMPARE_ROWS + [
    ("cache_hit_discount", "Cache disc."),
    ("release_date", "Released"), ("params_b", "Params (B)"),
    ("is_open_weights", "Open weights"), ("effort", "Effort"),
]
_COMPARE_VALUE_NAMES = {"value", "intel/$", "$/intel", "intel/1$", "intelperdollar",
                        "intel per dollar", "intelligence per dollar"}
_COMPARE_MIN, _COMPARE_MAX = 2, 12
#: hard ceiling for one comparison reply (12 models x every metric is a wide table;
#: the row-wise fit below keeps one reply around 1.5k tokens and says what it dropped)
_COMPARE_MAX_CHARS = 6_000
_COMPARE_VIEWS = ("table", "diff")
#: ``spec=`` keys a comparison understands
_COMPARE_SPEC_KEYS = ("models", "queries", "metrics", "view", "compact", "filters")
_COMPARE_FILTER_KEYS = ("creator", "open_weights", "min_intelligence", "min_context",
                        "include_deprecated")

_COMPARE_SPEC_TEMPLATE = """\
# aa_compare spec — YAML (a JSON object works too). Paste into aa_compare spec=...
models:                       # 2-12 model names or slugs
  - claude-opus-5-5
  - gpt-6-luna
  - gemini-3-5-flash
metrics: all                  # all | benchmarks | a comma list of keys/labels/aliases
view: diff                    # table (models as columns) | diff (per-metric delta vs the first model)
compact: true                 # default metric set only: core rows instead of the full set;
                              # ignored (and stated in the footer) whenever metrics= is given
filters:                      # optional; gate fuzzy name matching
  open_weights: true
  min_intelligence: 30
"""


def _ratio_score(key: str) -> str:
    """The score axis of a derived ratio row (``value`` → ``intelligence``)."""
    return key.split(":", 1)[1] if ":" in key else "intelligence"


def _is_ratio_key(key: str) -> bool:
    """True for a derived ``score / $/task`` row (``value``, ``value:coding``)."""
    return key == "value" or key.startswith("value:")


def _compare_numeric(m: Model, key: str) -> float | None:
    """Numeric cell value for a comparison row (``value`` = score per $/task)."""
    if _is_ratio_key(key):
        return _value_of(m, _ratio_score(key))
    value = _axis_value(m, key)
    if value is None and key == "cache_hit_discount":
        cache_read = select.lookup(m, "cache_read")
        price_in = select.lookup(m, "price_in")
        if cache_read is not None and price_in:
            value = 1 - cache_read / price_in
    return value


def _compare_cell(m: Model, key: str) -> str:
    value = _compare_numeric(m, key)
    if key == "cache_hit_discount":
        return _discount(value)
    if _is_ratio_key(key):
        return render.num(value, 1)
    return _axis_text(key, value)


def _delta_text(key: str, delta: float) -> str:
    """A delta in the same display unit as the value cell (pp for percentages)."""
    metric = catalog.metric(key)
    kind = metric.kind if metric is not None else None
    if kind == "pct":
        return f"{delta * 100:+.1f}pp"
    if kind == "elo":
        # same half-away-from-zero rule as the Elo value/CI cells
        return _elo_delta(delta)
    if kind == "int" or abs(delta) >= 1000:
        return f"{delta:+,.0f}"
    return f"{delta:+.1f}"


def _close_text(name: str) -> str:
    """The closest accepted field names for ``name`` (shared error/footnote text)."""
    pool = list(catalog.METRICS) + list(catalog.FIELD_ALIASES) + list(_EXTRA_ALIASES)
    return ", ".join(_close(name, pool)) or "none"


#: score axes ``metrics=all`` also ratios against $/task: the default view's
#: ``Intel/$`` plus the same derived row for a non-default score axis (G4).
_COMPARE_RATIO_AXES = ("intelligence", "coding", "agentic")


def _ratio_metric(name: str) -> tuple[str, str] | None:
    """``score/$`` (or ``score per dollar``) → the derived ratio row for ``score``.

    ``Intel/$`` is the ratio the default comparison view uses; the same form works
    for any other score axis (``coding/$``, ``agentic/$``), so a ratio is never
    silently read as the plain score (G4).
    """
    text = str(name).strip()
    # a wildcard spelling (``intel/$*``) is the same ratio alias, not a miss
    if text.endswith("*"):
        text = text.rstrip("*").strip()
    low = text.lower()
    axis = ""
    if low.endswith("/$") or low.endswith("/usd"):
        axis = text[:text.rfind("/")]
    elif " per " in low:
        head, _, tail = text.rpartition(" per ")
        if tail.strip().lower() in ("dollar", "usd", "$", "1$"):
            axis = head
    if not axis.strip():
        return None
    if _norm_alias(axis) in ("intel", "intelligence", "intelligencedollar"):
        return ("value", "Intel/$")
    rank = _rankable(axis)
    key = str(getattr(rank, "key", "")) if rank is not None else ""
    if not key:
        try:
            key = _metric_key(axis, "score")
        except ValueError:
            return None
    if key in _COMPARE_PRICING_KEYS:
        return None
    return (f"value:{key}", f"{_col_label(key)}/$")


def _insert_ratio_rows(row_specs: Sequence[tuple[str, str]],
                       models: Sequence[Model]) -> list[tuple[str, str]]:
    """Add the ``score/$`` rows ``metrics=all`` must carry (G4).

    Each ratio row goes directly after the score axis it derives from, and only
    when at least one selected model has both the score and a $/task cost — the
    same rule the default view's ``Intel/$`` row follows.
    """
    out = list(row_specs)
    for axis in _COMPARE_RATIO_AXES:
        key = "value" if axis == "intelligence" else f"value:{axis}"
        if any(k == key for k, _ in out):
            continue
        if not any(_compare_numeric(m, key) is not None for m in models):
            continue
        label = "Intel/$" if axis == "intelligence" else f"{_col_label(axis)}/$"
        at = next((i for i, (k, _) in enumerate(out) if k == axis), None)
        out.insert(len(out) if at is None else at + 1, (key, label))
    return out


def _compare_metric_row(name: str) -> tuple[str, str]:
    """Resolve one requested comparison metric (ratio, rankable, then metric)."""
    ratio = _ratio_metric(name)
    if ratio is not None:
        return ratio
    r = _rankable(name)
    if r is not None:
        return str(r.key), str(r.label)
    key = _metric_key(name, "metric")
    return key, _metric_label(key)


#: metric keys whose absence means "no published pricing" / "no measured speed"
_COMPARE_PRICING_KEYS = {"cost_per_task", "index_total_cost", "price_in", "price_out",
                         "cache_read", "cache_write", "cache_hit_discount"}
#: ``usd``-kind comparison rows that can render as ``$0.00`` (G9)
_COMPARE_USD_KEYS = {"cost_per_task", "index_total_cost", "price_in", "price_out",
                     "cache_read", "cache_write"}
_COMPARE_SPEED_KEYS = {"tps", "ttft", "ttfa", "e2e", "time_per_task",
                       "out_tokens_per_task"}


def _compare_extra_candidate(key: str) -> bool:
    """True when AA may publish ``key`` on its own index page / chart set / panel."""
    bench = catalog.BENCHMARKS.get(key)
    if bench is None or bench.source_hint == "none":
        return False
    if not bench.slug and key not in _OWN_PAGE_KEYS:
        return False
    rank = _rankable(key)
    return rank is not None and str(getattr(rank, "unit", "")) != "text"


def _compare_extra_values(key: str, models: Sequence[Model],
                          refresh: bool = False) -> tuple[dict[str, float], str, int]:
    """``({slug: value}, source, scored)`` for ``key`` from AA's chart set/panel.

    Fills a comparison row whose values live outside the leaderboard and
    the rich overlay (the cyber boards, AA-3D, …) — the same source chain
    ``aa_pareto`` and ``aa_benchmark_leaderboard`` use.
    """
    extra = _extra_score_models(key, refresh)
    if not extra:
        return {}, "", 0
    source, _scored = _extra_score_meta(key)
    wanted = {m.slug for m in models}
    values: dict[str, float] = {}
    for m in extra:
        if m.slug not in wanted or m.slug in values:
            continue
        value = _rankable_value(m, key)
        if value is not None:
            values[m.slug] = value
    return values, (source or "chart set"), len(extra)


def _safe_text(value: Any, limit: int | None = None) -> str:
    """Scraped text made safe for a footnote.

    Lone surrogates are mapped to U+FFFD (the same replacement :func:`_bounded`
    applies), then the text is passed through :func:`render.clean` so a hostile
    scraped name cannot restructure the markdown or inflate the reply.
    """
    text = str(value)
    if any("\ud800" <= ch <= "\udfff" for ch in text):
        text = text.translate(_UNSAFE_OUT)
    return render.clean(text, limit)


# ---- shared trust footnotes (wave G) ----------------------------------------

#: reasoning-effort suffixes AA appends to a family slug (the bare slug is the
#: Max / default-fallback row). A slug that extends the base with anything else is
#: a *different* model, not a variant (``claude-opus-5-5`` is not ``claude-opus-5``).
_EFFORT_SUFFIXES = ("xhigh", "high", "medium", "low", "non-reasoning", "minimal",
                    "reasoning", "thinking", "adaptive", "default")


def _variant_label(m: Model) -> str:
    """The reasoning-effort variant a model row represents (``Max``, ``High``…)."""
    name = str(m.name or "")
    if "(" in name and ")" in name:
        inner = name[name.find("(") + 1:name.rfind(")")]
        label = inner.split(",")[0].strip()
        if label:
            return label
    return str(m.effort or "")


def _effort_siblings(m: Model, pool: Sequence[Model]) -> list[Model]:
    """Rows that add a reasoning-effort variant to ``m``'s own family slug."""
    siblings = [x for x in pool
                if x.slug.startswith(m.slug + "-")
                and x.slug[len(m.slug) + 1:] in _EFFORT_SUFFIXES]
    order = {s: i for i, s in enumerate(_EFFORT_SUFFIXES)}
    siblings.sort(key=lambda x: (order.get(x.slug[len(m.slug) + 1:], 99), x.slug))
    return siblings


def _effort_note(m: Model, pool: Sequence[Model], query: str = "") -> str:
    """Announce a bare-family name that resolved to one effort variant (G5).

    Empty when the row has no effort siblings, or when the query already names the
    variant (a caller who asked for ``…-high`` is not told about it).
    """
    siblings = _effort_siblings(m, pool)
    if not siblings:
        return ""
    variant = _variant_label(m)
    if variant and _norm_alias(variant) in _norm_alias(query):
        return ""
    names = [siblings[0].slug]
    names += [f"-{x.slug[len(m.slug) + 1:]}" for x in siblings[1:6]]
    extra = "" if len(siblings) <= 6 else f" (+{len(siblings) - 6} more)"
    what = f"the {variant} variant" if variant else "the base variant"
    return f"matched {what} of {m.slug}; siblings: {', '.join(names)}{extra}"


def _match_note(query: str, resolved: Model, pool: Sequence[Model]) -> str:
    """Announce a fuzzy name resolution — never silently correct a name (G5)."""
    q = str(query).strip()
    if not q:
        return ""
    exact = q.lower() in {resolved.slug.lower(), str(resolved.name or "").lower(),
                          str(resolved.short_name or "").lower()}
    if exact:
        return ""
    near = [m.slug for m in select.search(pool, q, limit=4)
            if m.slug != resolved.slug]
    text = f"matched {_q(q)} → {resolved.slug} (exact slug for that name)"
    if near:
        text += f"; closest alternatives: {', '.join(near[:2])}"
    return text


def _name_notes(query: str, resolved: Model, pool: Sequence[Model]) -> list[str]:
    """Both name-resolution announcements for one resolved query (G5).

    A query that is not the exact slug/name was resolved *for* the caller, so the
    correction is named. Either way, a row that is one of several reasoning-effort
    variants says which one it is and lists its siblings — the bare family slug
    (``gpt-6-luna``) is the Max/default row, and silently comparing that is the
    documented cold-start hazard. ``_effort_note`` stays quiet when the query
    already names the variant.
    """
    notes = [note for note in (_match_note(query, resolved, pool),
                               _effort_note(resolved, pool, query)) if note]
    return list(dict.fromkeys(notes))


def _unknown_field_note(unknown: Sequence[str]) -> str:
    """One footnote for ``fields=``/``metrics=`` names that resolved to nothing (G6).

    A list-valued request renders everything that resolves; the rest is named here
    with its closest accepted spellings instead of aborting the whole call.
    """
    parts = [f"{render.clean(name, 40)} (closest: {_close_text(name)})"
             for name in dict.fromkeys(str(n) for n in unknown)]
    return "unknown, ignored: " + "; ".join(parts)


def _zero_unit(key: str) -> str:
    """The unit a cost/price footnote names after ``$0.00`` (G9)."""
    if key == "cost_per_task":
        return "/task"
    if key.startswith("blended_") or key in ("price_in", "price_out", "cache_read",
                                             "cache_write"):
        return "/1M tokens"
    return ""


def _zero_cost_note(key: str, cells: Sequence[tuple[str, float | None, bool]]) -> str:
    """One footnote for cost/price cells that render ``$0.00`` (G9).

    ``cells`` is ``[(model name, value, is_open_weights)]``. A rendered ``$0.00``
    is AA's **published** zero (the raw value is exactly ``0``), not a
    below-threshold measurement — a bare zero otherwise reads as unknown and it
    silently wins every "cheapest" ranking. A null cell keeps rendering ``-``.
    """
    zeros = [(name, value, ow) for name, value, ow in cells
             if value is not None and _axis_text(key, value) == "$0.00"]
    if not zeros:
        return ""
    names = ", ".join(name for name, _, _ in zeros[:3])
    if len(zeros) > 3:
        names += f" +{len(zeros) - 3} more"
    note = (f"$0.00 = published $0.00{_zero_unit(key)} for {names} "
            "(raw value 0, not unknown)")
    if all(ow for _, _, ow in zeros):
        note += ("; AA publishes 0 for open-weights models — self-hosting cost is "
                 "not included")
    return note


def _secondary_order(models: Sequence[Model]) -> list[Model]:
    """Deterministic order *within* a displayed tie: intelligence, then slug (G7)."""
    return sorted(models, key=lambda m: (
        -(m.intelligence if m.intelligence is not None else -1.0), m.slug))


def _break_display_ties(models: Sequence[Model],
                        cell_of: Callable[[Model], str]) -> list[Model]:
    """Order each displayed-tie group by the secondary key (G7).

    ``sort_models`` orders by the raw value, so two rows that *display* the same
    number (``$0.13``) keep AA's payload order and the tie is invisible and
    unreproducible. Grouping by the rendered cell makes the order explainable.
    """
    groups: dict[str, list[Model]] = {}
    for m in models:
        groups.setdefault(cell_of(m), []).append(m)
    out: list[Model] = []
    for members in groups.values():
        out.extend(_secondary_order(members))
    return out


def _tie_note(shown: Sequence[Model], cell_of: Callable[[Model], str],
              unit: str = "") -> str:
    """One line naming the first displayed tie and the secondary ordering (G7)."""
    groups: dict[str, list[Model]] = {}
    for m in shown:
        groups.setdefault(cell_of(m), []).append(m)
    for value, members in groups.items():
        if len(members) < 2:
            continue
        scores = [m.intelligence for m in members]
        if all(v is not None for v in scores):
            pair = f"{scores[0]:.1f} vs {scores[1]:.1f}"
            return (f"{len(members)} models tie at {value}{unit}; ordered by "
                    f"intelligence ({pair})")
        return (f"{len(members)} models tie at {value}{unit}; ordered by slug "
                f"({members[0].slug} vs {members[1].slug})")
    return ""


def _compare_missing_notes(models: Sequence[Model], short: Sequence[str],
                           row_specs: Sequence[tuple[str, str]],
                           numeric: Callable[[Model, str], float | None]) -> list[str]:
    """Coverage footnotes for the comparison cells that could not be filled (D1).

    Two shapes, both bounded:

    * a whole-model line when a model has *no* value on any requested metric
      (``<model> has no published pricing or speed …``);
    * otherwise a **per-model count** (``missing on requested metrics: X 29, Y 31``)
      so a wide ``metrics=all`` diff never hides *which* model is missing what,
      plus the per-metric detail (``missing: <metric> (<model>)``) only while the
      gap is small enough to read (≤6 cells).
    """
    blank = {m.slug for m in models
             if all(numeric(m, key) is None for key, _ in row_specs)}
    counts: list[tuple[str, int]] = []
    total_missing = 0
    for i, m in enumerate(models):
        if m.slug in blank:
            continue
        n = sum(1 for key, _ in row_specs if numeric(m, key) is None)
        if n:
            counts.append((_safe_text(short[i], 60), n))
            total_missing += n
    notes: list[str] = []
    if counts:
        notes.append("missing on requested metrics: "
                     + ", ".join(f"{name} {n}" for name, n in counts))
    if 0 < total_missing <= 6:
        missing: list[str] = []
        for key, label in row_specs:
            gone = [_safe_text(short[i], 60) for i, m in enumerate(models)
                    if numeric(m, key) is None and m.slug not in blank]
            if gone:
                missing.append(f"{label} ({', '.join(gone)})")
        if missing:
            notes.append(f"missing: {', '.join(missing)}")
    keys = {key for key, _ in row_specs}
    for m in models:
        if m.slug not in blank:
            continue
        if keys <= _COMPARE_PRICING_KEYS:
            kind = "pricing"
        elif keys <= _COMPARE_SPEED_KEYS:
            kind = "speed"
        elif keys <= (_COMPARE_PRICING_KEYS | _COMPARE_SPEED_KEYS):
            kind = "pricing or speed"
        else:
            kind = "values for the requested metrics"
        notes.append(
            f"{_safe_text(m.name or m.short_name or m.slug, 80)} has no published "
            f"{kind} on AA; 0/{len(row_specs)} requested metrics available"
        )
    return notes


# ---- spec parsing (a small YAML subset; JSON is accepted as-is) --------------

#: characters that force quoting when this subset emits a scalar
_YAML_UNSAFE = ':#{}[],&*?|>\'"%@`\\'
#: words a bare scalar would come back as something other than a string
_YAML_RESERVED = ("true", "false", "yes", "no", "on", "off", "null", "~")


def _yaml_scalar(text: str) -> Any:
    """Parse one scalar from the YAML subset (bool/int/float/quoted/plain)."""
    t = text.strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        inner = t[1:-1]
        if t[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner
    low = t.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "~", ""):
        return None
    if t.startswith("[") and t.endswith("]"):
        inner = t[1:-1].strip()
        return [] if not inner else [_yaml_scalar(p) for p in inner.split(",")]
    if t.startswith("{") and t.endswith("}"):
        out: dict[str, Any] = {}
        inner = t[1:-1].strip()
        for part in (inner.split(",") if inner else []):
            k, _, v = part.partition(":")
            out[k.strip().strip("\"'")] = _yaml_scalar(v)
        return out
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        pass
    return t


def _yaml_text(value: Any) -> str:
    """Render one scalar for the emitted YAML (quoting what needs it)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    plain = (text == text.strip() and bool(text)
             and not any(ch in text for ch in _YAML_UNSAFE)
             and text.lower() not in _YAML_RESERVED)
    if plain:
        try:
            float(text)          # a bare number would come back as a number
        except ValueError:
            return text
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _spec_yaml(data: Any, indent: int = 0) -> str:
    """Emit a mapping/list/scalar tree as the same YAML subset."""
    pad = " " * indent
    if isinstance(data, dict):
        lines: list[str] = []
        for key, value in data.items():
            if isinstance(value, dict):
                lines.append(f"{pad}{key}:")
                lines.append(_spec_yaml(value, indent + 2))
            elif isinstance(value, (list, tuple)):
                lines.append(f"{pad}{key}:")
                lines += [f"{pad}  - {_yaml_text(item)}" for item in value]
            else:
                lines.append(f"{pad}{key}: {_yaml_text(value)}")
        return "\n".join(lines)
    if isinstance(data, (list, tuple)):
        return "\n".join(f"{pad}- {_yaml_text(item)}" for item in data)
    return f"{pad}{_yaml_text(data)}"


def _parse_spec(text: str) -> dict:
    """Parse a ``spec=`` document: JSON, or the small YAML mapping subset.

    Supported subset: nested mappings, ``- `` block lists, inline ``[a, b]``
    lists, plain/quoted scalars, ``#`` comments. Tabs, anchors, multi-line
    strings and flow mappings spanning lines are rejected with the line number.
    """
    raw = str(text)
    stripped = raw.strip()
    if not stripped:
        return {}
    if stripped[0] in "{[":
        try:
            data = json.loads(stripped)
        except ValueError as exc:
            raise ValueError(f"spec: not valid JSON ({exc}) — pass YAML or JSON") from None
        if not isinstance(data, dict):
            raise ValueError("spec: the JSON document must be an object")
        return data

    lines: list[tuple[int, str, int]] = []
    for num, line in enumerate(raw.splitlines(), 1):
        if "\t" in line:
            raise ValueError(f"spec line {num}: tabs are not supported — indent with "
                             "spaces")
        body = line.rstrip()
        if not body.strip() or body.lstrip().startswith("#"):
            continue
        hash_at = body.find(" #")
        if hash_at >= 0:
            body = body[:hash_at].rstrip()
        if not body.strip():
            continue
        lines.append((len(body) - len(body.lstrip(" ")), body.strip(), num))

    def block(pos: int, indent: int) -> tuple[Any, int]:
        if pos < len(lines) and lines[pos][1].startswith("- "):
            items: list[Any] = []
            while (pos < len(lines) and lines[pos][0] == indent
                   and lines[pos][1].startswith("- ")):
                items.append(_yaml_scalar(lines[pos][1][2:]))
                pos += 1
            return items, pos
        mapping: dict[str, Any] = {}
        while pos < len(lines) and lines[pos][0] == indent:
            content = lines[pos][1]
            if content.startswith("- "):
                break
            key, sep, rest = content.partition(":")
            if not sep or not key.strip():
                raise ValueError(f"spec line {lines[pos][2]}: expected 'key: value', "
                                 f"got {content[:40]!r}")
            pos += 1
            if rest.strip():
                mapping[key.strip()] = _yaml_scalar(rest)
            elif pos < len(lines) and lines[pos][0] > indent:
                value, pos = block(pos, lines[pos][0])
                mapping[key.strip()] = value
            else:
                mapping[key.strip()] = None
        return mapping, pos

    if not lines:
        return {}
    value, pos = block(0, lines[0][0])
    if pos != len(lines):
        raise ValueError(f"spec line {lines[pos][2]}: unexpected indentation")
    if not isinstance(value, dict):
        # the MCP boundary turns ValueError into the tool's error text
        raise ValueError("spec: the document must be a mapping "
                         "(models/metrics/view)")
    return value


def _metric_arg(value: Any) -> str:
    """Coerce a ``metrics`` argument (string or list) to the comma form."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ",".join(str(part).strip() for part in value if str(part).strip())
    return str(value).strip()


def _fit_compare(head: str, labels: Sequence[str], rows: Sequence[Sequence[str]],
                 foot: str, limit: int = _COMPARE_MAX_CHARS) -> str:
    """Header + the largest row prefix whose table fits ``limit`` characters."""
    total = len(rows)
    lo, hi, best = 0, total, None
    while lo <= hi:
        mid = (lo + hi) // 2
        table = render.table(labels, rows[:mid]) if mid else ""
        note = ("" if mid == total else
                f"— response capped at {limit // 1000} kB: showing {mid} of {total} "
                "table rows — narrow with metrics=<list> or compare fewer models")
        text = "\n".join(part for part in (head, table, note, foot) if part)
        if len(text) <= limit:
            best = text
            lo = mid + 1
        else:
            hi = mid - 1
    if best is not None:
        return best
    return "\n".join(part for part in (
        head,
        (f"— response capped at {limit // 1000} kB: none of the {total} metric rows "
         "fit — narrow with metrics=<list> or compare fewer models"),
        foot) if part)


def _compare_spec_block(names: Sequence[str], metrics_arg: str, view: str,
                        compact: bool, filters: dict) -> str:
    """The copy-pasteable YAML ``spec:`` reproducing this comparison.

    Every effective key is emitted (``view`` and ``compact`` included even at
    their defaults), so re-running the echoed spec reproduces the call exactly
    instead of silently falling back to a default.
    """
    doc: dict[str, Any] = {"models": list(names)}
    if metrics_arg:
        doc["metrics"] = metrics_arg
    doc["view"] = view
    doc["compact"] = compact
    if filters:
        doc["filters"] = filters
    return ("— reproducible spec (re-run with aa_compare spec=...):\n"
            "```yaml\n" + _spec_yaml(doc) + "\n```")


#: arena comparison rows, in display order (key -> label)
_ARENA_ROWS = [
    ("board", "Board"),
    ("creator", "Creator/Host"),
    ("elo", "Elo"),
    ("sts", "STS Index"),
    # the STT/STT-streaming boards' own columns (a legacy ``wer`` alias maps here)
    ("sttWerIndex", "WER"),
    ("sttStreamingWerIndex", "WER index"),
    ("sttStreamingTimeToFinal", "Time to final"),
    ("ci", "95% CI"),
    ("rank", "Rank"),
    ("appearances", "Appearances"),
    ("price", "Price"),
    ("release_date", "Release"),
    ("open_weights", "Open"),
]
_ARENA_ROW_LABEL = {k: lbl for k, lbl in _ARENA_ROWS}
#: accepted arena field spellings (``metrics=`` on an arena comparison)
_ARENA_FIELD_ALIASES = {
    "board": "board", "arena": "board",
    "creator": "creator", "host": "creator", "lab": "creator",
    "elo": "elo", "preference": "elo",
    "sts": "sts", "stsindex": "sts", "score": "sts", "stsindexscore": "sts",
    "wer": "sttWerIndex", "werindex": "sttWerIndex", "worderrorrate": "sttWerIndex",
    "timetofinal": "sttStreamingTimeToFinal",
    "time_to_final": "sttStreamingTimeToFinal",
    "ttf": "sttStreamingTimeToFinal",
    "finaltranscript": "sttStreamingTimeToFinal",
    "ci": "ci", "ci95": "ci", "ci_lower": "ci", "ci_upper": "ci",
    "rank": "rank",
    "appearances": "appearances", "appearancescount": "appearances",
    "price": "price", "priceunit": "price",
    "release": "release_date", "released": "release_date",
    "releasedate": "release_date",
    "open": "open_weights", "openweights": "open_weights",
}


def _arena_row_cell(entry: _ArenaEntry, key: str) -> tuple[str, float | None]:
    """``(display text, numeric value)`` for one arena comparison cell."""
    if key == "board":
        return entry.board, None
    if key == "creator":
        return (entry.creator or "-"), None
    for mkey, label, value, unit in entry.metrics:
        if mkey == key:
            numeric = float(value) if isinstance(value, (int, float)) else None
            return _arena_value_text((mkey, label, value, unit)), numeric
    if key == "ci":
        if entry.ci_lower is None and entry.ci_upper is None:
            return "-", None
        return f"{_elo_int(entry.ci_lower)}–{_elo_int(entry.ci_upper)}", None
    if key == "rank":
        return (str(entry.rank) if entry.rank is not None else "-"), None
    if key == "appearances":
        return (f"{entry.appearances:,}" if entry.appearances is not None else "-"), None
    if key == "price":
        if entry.price is None:
            return "-", None
        return f"${entry.price:,.2f}{entry.price_unit or ''}", entry.price
    if key == "release_date":
        return (entry.release_date or "-"), None
    if key == "open_weights":
        if entry.open_weights is None:
            return "-", None
        return ("yes" if entry.open_weights else "no"), None
    return "-", None


def _arena_delta_text(key: str, delta: float) -> str:
    if key == "elo":
        # same half-away-from-zero rule as the Elo value/CI cells
        return _elo_delta(delta)
    if key in ("appearances", "rank"):
        return f"{delta:+,.0f}"
    if key == "wer":
        return f"{delta * 100:+.1f}pp"
    return f"{delta:+.2f}"


def _arena_row_label(key: str) -> str:
    """The row label for an arena/board comparison key."""
    if key in _ARENA_ROW_LABEL:
        return _ARENA_ROW_LABEL[key]
    # a board column: prefer the benchmark's full label over the metric's
    # shortened one (the metric label is capped for narrow tables)
    bench = catalog.benchmark(key)
    if bench is not None:
        return bench.label
    return _col_label(key)


def _arena_row_specs(entries: Sequence[_ArenaEntry],
                     metrics_arg: str) -> list[tuple[str, str]]:
    """Rows to render for an arena/board comparison, honouring ``metrics=``."""
    present = {"board", "creator"}
    for e in entries:
        for k, _label, value, _unit in e.metrics:
            if value is not None:
                present.add(k)
        if e.ci_lower is not None or e.ci_upper is not None:
            present.add("ci")
        if e.rank is not None:
            present.add("rank")
        if e.appearances is not None:
            present.add("appearances")
        if e.price is not None:
            present.add("price")
        if e.release_date:
            present.add("release_date")
        if e.open_weights is not None:
            present.add("open_weights")

    def _resolve(name: str) -> str | None:
        key = _ARENA_FIELD_ALIASES.get(_norm_alias(name))
        if key is not None:
            return key
        # a board column (ttsQualityElo, sttEarnings22Wer, searchQualityIndex, …)
        try:
            return _metric_key(name, "field")
        except ValueError:
            return None

    lower = metrics_arg.strip().lower()
    if not metrics_arg or lower in ("all", "benchmarks"):
        keys = [k for k, _ in _ARENA_ROWS if k in present]
        # a board publishes its own metric columns; show the ones every compared
        # row shares, so a bare board comparison is not just board + creator
        if any(e.kind == "board" for e in entries):
            extra: list[str] = []
            for e in entries:
                for k, _label, value, _unit in e.metrics:
                    if value is not None and k not in keys and k not in extra:
                        extra.append(k)
            shared = [k for k in extra
                      if all(any(mk == k and mv is not None
                                 for mk, _l, mv, _u in e.metrics) for e in entries)]
            keys += shared[:8]
        if lower != "all":
            keys = [k for k in keys if k != "ci"]  # CI only when asked
        return [(k, _arena_row_label(k)) for k in keys]
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name in _split(metrics_arg):
        key = _resolve(name)
        if key is None:
            valid = ", ".join(k for k, _ in _ARENA_ROWS)
            raise ValueError(
                f"unknown arena metric {_q(name)} — valid: {valid}\n"
                "— these select rows for an arena/media comparison"
            )
        if key in seen:
            continue
        seen.add(key)
        out.append((key, _arena_row_label(key)))
    return out


def _arena_compare(entries: Sequence[_ArenaEntry], metrics_arg: str, view: str,
                   filters: dict, *, chosen: str = "", other_boards: Sequence[str] = (),
                   partial: bool = False) -> str:
    """Comparison table for arena/media entries (not language models)."""
    boards: list[str] = []
    for e in entries:
        if e.board not in boards:
            boards.append(e.board)
    specs = _arena_row_specs(entries, metrics_arg)
    requested_labels = [label for _, label in specs]
    # a requested metric the board does not publish must never yield an all-dash
    # table: fall back to the board's own metric(s) and say why (F1).
    empty_keys = [key for key, _ in specs
                  if all(_arena_row_cell(e, key)[0] == "-" for e in entries)]
    fell_back = bool(specs) and len(empty_keys) == len(specs)
    if fell_back:
        specs = _arena_row_specs(entries, "")
    native_labels: list[str] = []
    for e in entries:
        for _k, label, value, _u in e.metrics:
            if value is not None and label not in native_labels:
                native_labels.append(label)
    short = [e.name for e in entries]
    labels = ["Metric", *short]
    rows: list[list[str]] = []
    if len(set(short)) != len(short):
        rows.append(["Board", *[e.board for e in entries]])
    if view == "diff":
        ref = entries[0]
        for key, label in specs:
            cells: list[str] = []
            for i, e in enumerate(entries):
                text, num = _arena_row_cell(e, key)
                _rtext, ref_num = _arena_row_cell(ref, key)
                if i and num is not None and ref_num is not None:
                    cells.append(f"{text} ({_arena_delta_text(key, num - ref_num)})")
                else:
                    cells.append(text)
            rows.append([label, *cells])
    else:
        for key, label in specs:
            rows.append([label, *[_arena_row_cell(e, key)[0] for e in entries]])

    board_kind = all(e.kind == "board" for e in entries)
    board_label = ", ".join(f"{b} ({_arena_board_label(b)})" for b in boards)
    if len(boards) == 1 and boards[0] in loaders.MEDIA_BOARDS:
        cache_name = f"media_{boards[0]}"
    elif len(boards) == 1 and boards[0] in _BOARD_CHART_SLUGS:
        cache_name = f"eval_{_BOARD_CHART_SLUGS[boards[0]]}"
    elif len(boards) == 1:
        cache_name = "home"
    else:
        cache_name = ""
    count = (f"{len(entries)} models · {len(specs)} metrics · "
             + ("board" if board_kind else "arena"))
    kind_word = "board" if board_kind else "arena board"
    note = f"{kind_word}{'s' if len(boards) > 1 else ''}: {board_label}"
    head = _header(count=count, note=note, name=cache_name)
    if board_kind:
        footnotes = [
            "board rows are their own namespace (a TTS voice / STT host / search "
            "API is not a language model) — compare within one board; the values "
            "are AA's own board columns",
            f"source: {_board_source(boards[0])}"
            + (" (and others)" if len(boards) > 1 else ""),
        ]
    else:
        footnotes = [
            "arena entries are media/speech models — human-preference scores are "
            "per-board: a value from one board is not comparable with another board's",
            f"source: aa_media board={boards[0]}"
            + (" (and others)" if len(boards) > 1 else ""),
        ]
    if (any(_is_board_metric_key(key) for key, _label in specs)
            or any(_is_board_metric_key(key) for key in _split(metrics_arg))):
        footnotes.insert(
            0, "board rows are their own namespace (a TTS voice / STT host / search "
               "API is not a language model) — these are the board's own columns, "
               "not language-model scores")
    where_board = (_board_source(boards[0]) if board_kind
                   else f"aa_media board={boards[0]}")
    if filters:
        footnotes.append("filters apply to language models only — ignored for arenas")
    if other_boards:
        footnotes.append(
            f"board {chosen} chosen — this name also appears on "
            f"{', '.join(other_boards)}; pass a board key (e.g. {other_boards[0]}) "
            "as a queries entry to compare a different board"
        )
    if partial:
        footnotes.append(
            f"{'board' if board_kind else 'arena'} match was partial — not every "
            f"query token appears in the name; verify the entry on {where_board}"
        )
    if fell_back:
        native = ", ".join(native_labels) or "its own metrics"
        footnotes.append(
            f"{board_label} publishes {native}, not "
            f"{', '.join(requested_labels)}; showing the board's own metrics — see "
            f"{where_board}"
        )
    elif empty_keys:
        gone = ", ".join(label for key, label in specs if key in empty_keys)
        footnotes.append(
            f"{gone} not published on {board_label} (shown as -) — see {where_board}"
        )
    foot = render.note(footnotes)
    return _fit_compare(head, labels, rows, foot)


def _is_board_metric_key(key: str) -> bool:
    """Whether ``key`` is a speech/search board column (not a language-model score)."""
    return key.startswith(("tts", "stt", "search")) and catalog.metric(key) is not None


def _compare(queries: list[str] = (), metrics: str = "", view: str = "table",
             compact: bool = True, spec: str = "", refresh: bool = False) -> str:
    doc: dict[str, Any] = {}
    if spec is not None and str(spec).strip():
        doc = _parse_spec(str(spec))
        unknown = [k for k in doc if k not in _COMPARE_SPEC_KEYS]
        if unknown:
            raise ValueError(
                f"spec: unknown key(s) {', '.join(sorted(unknown))} — accepted: "
                f"{', '.join(_COMPARE_SPEC_KEYS)}"
            )

    names = [str(q).strip() for q in (queries or []) if str(q).strip()]
    if not names:
        spec_models = doc.get("models") if doc.get("models") is not None else doc.get("queries")
        if isinstance(spec_models, str):
            spec_models = _split(spec_models)
        names = [str(m).strip() for m in (spec_models or []) if str(m).strip()]
    # a bare arena board key in queries pins the board for an arena comparison
    board_hint = ""
    if len(names) > _COMPARE_MIN:
        stripped: list[str] = []
        for n in names:
            b = _arena_board_key(n)
            if b is not None and not board_hint:
                board_hint = b
                continue
            stripped.append(n)
        if board_hint and len(stripped) >= _COMPARE_MIN:
            names = stripped
    stray = next((n for n in names if _arena_board_key(n) is not None), None)
    if stray is not None:
        raise ValueError(
            f"{_q(stray)} is an arena board, not a model — pass it together with "
            f"2+ arena model names to compare that board, or list it with "
            f"aa_media board={_arena_board_key(stray)}"
        )
    if not (_COMPARE_MIN <= len(names) <= _COMPARE_MAX):
        raise ValueError(
            f"aa_compare takes {_COMPARE_MIN}-{_COMPARE_MAX} models; got {len(names)} "
            "— pass queries=[...] or a spec with a models: list"
        )

    metrics_arg = _metric_arg(metrics) or _metric_arg(doc.get("metrics"))
    view_arg = (str(view).strip().lower() or "table")
    if view_arg == "table" and doc.get("view") is not None:
        view_arg = str(doc["view"]).strip().lower()
    if view_arg not in _COMPARE_VIEWS:
        raise ValueError(
            f"unknown view {_q(view)} — expected {', '.join(_COMPARE_VIEWS)}"
        )
    if compact is True and doc.get("compact") is not None:
        compact = bool(doc["compact"])
    filters = doc.get("filters") or {}
    if not isinstance(filters, dict):
        raise ValueError(
            "spec: filters must be a mapping (e.g. open_weights: true)")
    bad = [k for k in filters if k not in _COMPARE_FILTER_KEYS]
    if bad:
        raise ValueError(
            f"spec: unknown filter(s) {', '.join(sorted(bad))} — accepted: "
            f"{', '.join(_COMPARE_FILTER_KEYS)}"
        )

    # Resolve the requested metric names *before* loading data: the deterministic
    # source choice (G1) and the unknown-name footnote (G6) both depend on which
    # keys were asked for, and a list-valued request must not abort the call.
    lower = metrics_arg.strip().lower()
    unknown_metrics: list[str] = []
    requested: list[tuple[str, str]] = []
    if metrics_arg and lower not in ("all", "benchmarks"):
        for name in _split(metrics_arg):
            if name.strip().lower() in _COMPARE_VALUE_NAMES:
                requested.append(("value", "Intel/$"))
                continue
            try:
                requested.append(_compare_metric_row(name))
            except ValueError:
                unknown_metrics.append(name)
    elif not metrics_arg:
        requested = list(_COMPARE_ROWS if compact else _COMPARE_FULL)
    board_keys = [key for key, _label in requested if _is_board_metric_key(key)]
    if board_keys:
        # Speech/TTS/search columns are board rows, never language-model metrics.
        # Route a board-metric comparison to the board's own table and refuse an
        # unresolvable mix explicitly (board rows are their own namespace).
        groups: list[list[_ArenaEntry]] = []
        missing: list[str] = []
        for raw in names:
            _name_board, name = _arena_split_board(raw)
            cands, _partial = _arena_candidates(name)
            if cands:
                groups.append(cands)
            else:
                missing.append(name)
        labels = ", ".join(label for key, label in requested if key in board_keys)
        if groups and not missing:
            try:
                picks, chosen, others = _arena_pick_board(groups, board_keys)
                return _arena_compare(picks, metrics_arg, view_arg, filters,
                                      chosen=chosen, other_boards=others)
            except ValueError as exc:
                route_note = str(exc)
        else:
            route_note = ("not every name is on a speech/search board: "
                          + ", ".join(missing))
        entry_boards = sorted({
            e.board for e in _arena_entries()
            for mk, _lbl, _mv, _u in e.metrics if mk in board_keys})
        head = _header(count=f"{len(names)} names · board metrics {labels}")
        return head + "\n" + render.note([
            "board rows are their own namespace (a TTS voice / STT host / search "
            "API is not a language model) — a board column is compared only with "
            "rows from the same board, never against language models",
            f"{labels} live on: {', '.join(entry_boards) or 'the speech/search boards'}"
            " — list a board with aa_media board=<key>, or compare two names that "
            "both appear on it",
            route_note,
        ])
    # The first-party model-page value wins for the dual-sourced speed metrics, so
    # `ttft` and `time_to_first_token` — and `all` — can never disagree (G1).
    rich = (lower in ("all", "benchmarks")
            or any(key in _DUAL_SOURCE_KEYS for key, _ in requested)
            or _rich_needed(refresh=refresh, fields=metrics_arg))
    all_models, rich_used = _models_state(refresh, rich=rich)
    pool = all_models
    if filters:
        pool = select.filter_models(
            all_models,
            creator=str(filters.get("creator") or "") or None,
            open_weights=filters.get("open_weights"),
            min_intelligence=filters.get("min_intelligence"),
            min_context=filters.get("min_context"),
            exclude_deprecated=not bool(filters.get("include_deprecated")),
        )

    picked: list[Model] = []
    resolved_pairs: list[tuple[str, Model]] = []
    arena_groups: list[list[_ArenaEntry]] = []
    arena_partial = False
    seen_inputs: dict[str, int] = {}
    for index, raw in enumerate(names):
        name_board, name = _arena_split_board(raw)
        board = name_board or board_hint or None
        try:
            resolved = _resolve_slug(name, pool)
            if resolved.slug in seen_inputs:
                first = seen_inputs[resolved.slug]
                raise ValueError(
                    f"queries[{index}] duplicates queries[{first}] — both "
                    f"resolve to {resolved.slug} ({resolved.name}); compare "
                    "distinct models\n"
                    "— use aa_search for the full variant name (e.g. "
                    "\"GPT-6 Luna (High)\"), or name distinct releases")
            seen_inputs[resolved.slug] = index
            picked.append(resolved)
            resolved_pairs.append((raw, resolved))
            continue
        except ValueError as exc:
            if "duplicates queries[" in str(exc):
                raise
            # an exact deprecated release is a real model, never a fuzzy arena hit
            if _deprecated_match(name) is not None:
                raise
            lm_error = exc
        cands, partial = _arena_candidates(name, board)
        if cands:
            arena_groups.append(cands)
            arena_partial = arena_partial or partial
            continue
        if board and _arena_candidates(name)[0]:
            raise ValueError(
                f"{_q(name)} is not on arena board {board} — drop the board, or "
                f"check the name on it with aa_media board={board}"
            )
        if pool is all_models:
            raise ValueError(f"queries[{index}] {_q(raw)}: {lm_error}") from None
        # an exact name is never dropped because a filter excluded it
        resolved = _resolve_slug(name, all_models)
        if resolved.slug in seen_inputs:
            first = seen_inputs[resolved.slug]
            raise ValueError(
                f"queries[{index}] duplicates queries[{first}] — both resolve to "
                f"{resolved.slug} ({resolved.name}); compare distinct models\n"
                "— use aa_search for the full variant name (e.g. "
                "\"GPT-6 Luna (High)\"), or name distinct releases")
        seen_inputs[resolved.slug] = index
        picked.append(resolved)
        resolved_pairs.append((raw, resolved))

    if arena_groups:
        if picked:
            lm = picked[0].short_name or picked[0].name
            a = arena_groups[0][0]
            kind = "board row" if a.kind == "board" else "arena entry"
            where = (_board_source(a.board) if a.kind == "board"
                     else f"aa_media board={a.board}")
            raise ValueError(
                "aa_compare compares either language models or arena-board models, "
                "not both.\n"
                f"— {kind}: {_safe_text(a.name, 60)} on {a.board} (compare two rows "
                f"from that board — see {where}); language model: "
                f"{_safe_text(lm, 60)} (aa_leaderboard / aa_search)"
            )
        prefer = [k for k, _ in requested
                  if k != "value" and not k.startswith("value:")]
        arena_picked, chosen, other_boards = _arena_pick_board(arena_groups, prefer)
        return _arena_compare(arena_picked, metrics_arg, view_arg, filters,
                              chosen=chosen, other_boards=other_boards,
                              partial=arena_partial)

    # mirror the site's comparison page: a model missing from the rich overlay
    # gets its own (cached) model page fetched and merged in.
    rich_slugs = {m.slug for m in _rich_models(refresh)} if rich_used else set()
    models: list[Model] = []
    page_fetched: list[str] = []
    for base in picked:
        record = None
        if rich_used and base.slug not in rich_slugs:
            try:
                record = _load(f"model_{base.slug}", loaders.model, base.slug,
                               refresh=refresh).get(base.slug)
                page_fetched.append(base.slug)
            except (ValueError, AAFetchError) as exc:  # best effort
                log.debug("compare: model page for %s unavailable (%s)", base.slug, exc)
        models.append(normalize.merge(base, record) if record is not None else base)

    overlay: dict[str, dict[str, float]] = {}
    extra_keys: list[str] = []

    def join_extra(key: str) -> bool:
        """Fill ``key`` for the selected models from AA's chart set / panel (D2)."""
        values = _compare_extra_values(key, models, refresh)[0]
        if not values:
            return False
        overlay[key] = values
        if key not in extra_keys:
            extra_keys.append(key)
        return True

    def numeric(m: Model, key: str) -> float | None:
        if key in overlay and overlay[key].get(m.slug) is not None:
            return overlay[key][m.slug]
        return _compare_numeric(m, key)

    def cell(m: Model, key: str) -> str:
        if key in overlay and overlay[key].get(m.slug) is not None:
            return _axis_text(key, overlay[key][m.slug])
        return _compare_cell(m, key)

    row_specs: list[tuple[str, str]] = []
    if lower in ("all", "benchmarks"):
        kinds = ("benchmark", "index") if lower == "benchmarks" else None
        for r in _rankable_list():
            kind = str(getattr(r, "kind", ""))
            if kinds is not None and kind not in kinds:
                continue
            key = str(getattr(r, "key", ""))
            if not key:
                continue
            label = str(getattr(r, "label", key))
            if any(_axis_value(m, key) is not None for m in models):
                row_specs.append((key, label))
                continue
            if (kind in ("benchmark", "index") and _compare_extra_candidate(key)
                    and join_extra(key)):
                row_specs.append((key, label))
        if lower == "all":
            row_specs = _insert_ratio_rows(row_specs, models)
    elif metrics_arg:
        row_specs = list(requested)
        # a named metric the selected models do not carry may still be published
        # on AA's chart set / homepage panel — join it before giving up (D2)
        for key, _label in list(row_specs):
            if key != "value" and not key.startswith("value:") \
                    and all(_axis_value(m, key) is None for m in models):
                join_extra(key)
    else:
        row_specs = list(requested)

    if not row_specs:
        if unknown_metrics:
            raise ValueError(
                f"unknown metric {_q(unknown_metrics[0])} — closest: "
                f"{_close_text(unknown_metrics[0])}\n"
                "— aa_reference topic=fields lists every accepted name"
            )
        raise ValueError(
            f"no metric rows: none of the requested metrics has a value for "
            f"{', '.join(m.slug for m in models)}\n"
            "— try metrics=all (every rankable any of them has) or name a metric "
            "directly (aa_benchmarks lists them)"
        )

    short = [m.short_name or m.name for m in models]
    labels = ["Metric", *short]
    # with an explicit metrics= list, compact controls the extras: true (default)
    # omits the Slug row and any all-null metric row, false includes them
    slug_row = (not compact if metrics_arg
                else len(set(short)) != len(short) or len(models) > 6)
    shown_specs = list(row_specs)
    dropped_rows = 0
    empty_all_rows = 0
    if metrics_arg and compact:
        shown_specs = [(k, lbl) for k, lbl in row_specs
                       if any(cell(m, k) != "-" for m in models)]
        dropped_rows = len(row_specs) - len(shown_specs)
    if lower == "all":
        # metrics=all sweeps every rankable key, so rows that resolve to "-" for
        # every compared model are noise; drop them and say how many. A metric
        # the caller named explicitly is always kept (even when empty).
        kept = [(k, lbl) for k, lbl in row_specs
                if any(cell(m, k) != "-" for m in models)]
        empty_all_rows = len(row_specs) - len(kept)
        shown_specs = kept
        dropped_rows = 0
    rows: list[list[str]] = []
    if slug_row:
        rows.append(["Slug", *[m.slug for m in models]])
    if view_arg == "diff":
        ref_name = short[0]
        for key, label in shown_specs:
            vals = [numeric(m, key) for m in models]
            cells: list[str] = []
            for i, m in enumerate(models):
                text = cell(m, key)
                if i == 0 or vals[i] is None or vals[0] is None:
                    cells.append(text)
                else:
                    cells.append(f"{text} ({_delta_text(key, vals[i] - vals[0])})")
            rows.append([label, *cells])
        view_note = (f"diff: each cell is value (Δ vs {render.clean(ref_name, None)}, "
                     "the first model); + means higher")
    else:
        for key, label in shown_specs:
            rows.append([label, *[cell(m, key) for m in models]])
        view_note = ""

    cache_name = _lb_cache()
    metric_count = (f"{len(shown_specs)} of {len(row_specs)} metrics"
                    if (dropped_rows or empty_all_rows)
                    else f"{len(shown_specs)} metrics")
    if empty_all_rows:
        plural = "metric" if empty_all_rows == 1 else "metrics"
        metric_count += f" · {empty_all_rows} {plural} with no data hidden"
    count = f"{len(models)} models · {metric_count}"
    note = view_note
    head = _header(count=count, note=note, name=cache_name,
                   source_label=_prov_label(rich_used))
    if metrics_arg:
        footnotes = [f"metrics: {metrics_arg}"]
    else:
        # the default set is a subset: say so (a first-try reader must not mistake
        # it for "every metric"). The exact metrics=all row count would require
        # loading the rich overlay + every eval chart set for a footer line, so
        # name the widening paths instead of paying that on the default path.
        footnotes = [
            f"showing the default {len(row_specs)}-row subset, not every metric: "
            "metrics=all selects every published row these models have (rich "
            "overlay + AA's eval chart set / homepage panels), metrics=benchmarks "
            "limits to benchmarks/indexes"]
    if unknown_metrics:
        footnotes.append(_unknown_field_note(unknown_metrics))
    if metrics_arg and compact:
        if slug_row is False:
            footnotes.append("compact=true: Slug row omitted (compact=false adds it)")
        if dropped_rows:
            footnotes.append(
                f"compact=true: {dropped_rows} all-null rows omitted "
                "(compact=false includes them)")
    if page_fetched:
        footnotes.append(
            "model page fetched + merged for "
            + ", ".join(page_fetched[:4])
            + ("…" if len(page_fetched) > 4 else "")
            + " (not in the rich overlay)"
        )
    if filters:
        footnotes.append("filters: " + ", ".join(f"{k}={v}" for k, v in filters.items()))
    # ---- G5: never correct a name silently (fuzzy match, effort variant) -------
    for raw, m in resolved_pairs:
        footnotes += _name_notes(raw, m, all_models)
    # ---- G1: deterministic sourcing of the dual-sourced speed metrics ----------
    page_rows: dict[str, Model] = {}
    if rich_used:
        for m in _rich_models(refresh):
            page_rows[m.slug] = m
        for m in models:
            if m.slug in page_fetched:
                page_rows.setdefault(m.slug, m)  # page-fetched: merged == page
    snapshot_rows = {m.slug: m for m in _lb_rows(refresh)}
    page_sourced: list[str] = []
    snapshot_sourced: list[str] = []
    seen_dual: set[str] = set()
    for key, label in row_specs:
        if key not in _DUAL_SOURCE_KEYS or key in seen_dual:
            continue
        seen_dual.add(key)
        differ: list[tuple[float, str, float, float]] = []
        fell_back: list[str] = []
        for i, m in enumerate(models):
            source = page_rows.get(m.slug)
            page_value = _metric_value(source, key) if source is not None else None
            base = snapshot_rows.get(m.slug)
            snap_value = _metric_value(base, key) if base is not None else None
            if page_value is None:
                if snap_value is not None:
                    fell_back.append(_safe_text(short[i], 40))
                continue
            page_sourced.append(key)
            if snap_value is None or snap_value == 0:
                continue
            rel = abs(page_value - snap_value) / abs(snap_value)
            if rel > 0.02:
                differ.append((rel, _safe_text(short[i], 40), page_value, snap_value))
        if differ:
            differ.sort(key=lambda t: (-t[0], t[1]))
            _rel, who, page_value, snap_value = differ[0]
            text = (f"{label}: model page {_axis_text(key, page_value)} vs leaderboard "
                    f"snapshot {_axis_text(key, snap_value)} for {who} (using the "
                    "model page)")
            if len(differ) > 1:
                text += f"; {len(differ) - 1} other model(s) differ"
            footnotes.append(text)
        if fell_back:
            footnotes.append(
                f"{label}: no first-party model-page value for "
                f"{', '.join(fell_back[:3])}; leaderboard snapshot shown")
    page_sourced = list(dict.fromkeys(page_sourced))
    for key, _label in row_specs:
        if key in _DUAL_SOURCE_KEYS and key not in page_sourced:
            snapshot_sourced.append(key)
    if page_sourced:
        text = "speed/latency from AA's first-party model page"
        if "ttft" in page_sourced:
            text += " (TTFT is the long-prompt median)"
        footnotes.append(text + "; aa_model has the per-prompt-type breakdown "
                                "(short/medium/long/100k)")
    if snapshot_sourced:
        names_ = ", ".join(_metric_label(k) for k in dict.fromkeys(snapshot_sourced))
        footnotes.append(
            f"{names_} from the leaderboard snapshot (the model page is not "
            "in this source); aa_model has the per-prompt-type breakdown")
    # ---- G9: a cost that displays as $0.00 is not a measured zero -------------
    for key, _label in row_specs:
        if key in _COMPARE_USD_KEYS:
            cells = [(short[i], _compare_numeric(m, key), bool(m.is_open_weights))
                     for i, m in enumerate(models)]
            zero_note = _zero_cost_note(key, cells)
            if zero_note:
                footnotes.append(zero_note)
    # ---- G4: a score/$ row is ours, not AA's ---------------------------------
    ratio_labels = [label for key, label in row_specs if _is_ratio_key(key)]
    if ratio_labels:
        footnotes.append(f"{', '.join(ratio_labels)}: derived here as score ÷ $/task "
                         "(AA publishes no such column)")
    if lower in ("all", "benchmarks"):
        footnotes.append(f"metrics={lower}: every {'benchmark/index' if lower == 'benchmarks' else 'rankable'} "
                         "key any of these models has (aa_benchmarks lists them all)")
    footnotes += _compare_missing_notes(models, short, row_specs, numeric)
    if extra_keys:
        groups: dict[str, list[str]] = {}
        counts: dict[str, int] = {}
        for key in extra_keys:
            source, scored = _extra_score_meta(key)
            where = {"chart set": "eval chart set",
                     "homepage panel": "homepage panel"}.get(
                         source, "eval chart set / homepage panel")
            groups.setdefault(where, []).append(_score_label(key))
            counts[where] = max(counts.get(where, 0), scored,
                                len(overlay[key]))
        for where, names in groups.items():
            shown = sorted(names)[:8]
            text = ", ".join(shown)
            if len(names) > len(shown):
                text += f" … (+{len(names) - len(shown)} more)"
            footnotes.append(f"{text} from AA's {where} "
                             f"(top ~{counts[where]} models)")
    if board_hint:
        footnotes.append(f"board {board_hint} ignored — every model resolved to a "
                         "language model, not an arena entry")
    foot = "\n".join([render.note(footnotes),
                      _compare_spec_block([m.slug for m in models], metrics_arg,
                                          view_arg, compact, filters)])
    return _fit_compare(head, labels, rows, foot)


# --------------------------------------------------------------------------- #
# aa_benchmarks
# --------------------------------------------------------------------------- #


def _untracked(query: str) -> tuple[str, str] | None:
    """Match a query against ``catalog.UNTRACKED_BENCHMARKS`` (the only source)."""
    table = getattr(catalog, "UNTRACKED_BENCHMARKS", None) or {}
    q = _norm_alias(query)
    if not q:
        return None
    for name, note in table.items():
        n = _norm_alias(name)
        if n and (q == n or n in q or q in n):
            return str(name), str(note)
    return None


def _known_tags() -> list[str]:
    """Every tag a rankable can carry (domain expansions + the index itself)."""
    tags: set[str] = set()
    for values in _domain_map().values():
        tags.update(str(t) for t in values)
    for r in _rankable_list():
        tags.update(str(t) for t in getattr(r, "tags", ()))
    return sorted(t for t in tags if "*" not in t)


def _rankable_coverage(r: Any, lb: Sequence[Model], merged: Sequence[Model]) -> str:
    """Live coverage of one rankable in the current source.

    Computed from the same source chain the ranking tools use (the leaderboard,
    the rich overlay, then AA's eval chart set / homepage panel), so a benchmark
    AA now fetches live is never labelled "not fetched".
    """
    if str(getattr(r, "kind", "")) == "arena":
        return "arena board"
    key = str(getattr(r, "key", ""))
    if str(getattr(r, "kind", "")) == "view":
        # a view is a plotting instruction over live data, not a data source:
        # report how many models the underlying score/x axes cover (F2).
        axis = str(getattr(r, "how", "")).removeprefix("aa_pareto x=").strip()
        axis_label = _PARETO_AXES.get(axis, (axis, axis, ""))[0]
        scored = sum(1 for m in merged
                     if not m.deprecated
                     and _metric_value(m, "intelligence") is not None
                     and _axis_value(m, axis) is not None)
        if scored:
            return f"view — Intel vs {axis_label}: {scored} models scored on both axes"
        return "view — run aa_pareto to see the frontier"
    native = sum(1 for m in lb if _rankable_value(m, key) is not None)
    if native:
        return f"leaderboard ({native}/{len(lb)})"
    rich = sum(1 for m in merged if _rankable_value(m, key) is not None)
    if rich:
        return f"rich dataset ({rich}/{len(merged)})"
    try:
        extra = _extra_score_models(key)
    except (AAFetchError, LookupError, ValueError):
        # a static catalog must still render when a live source is unreachable
        extra = []
    if extra:
        source, joined, published = _index_page_meta(key)
        if not source:
            source = _extra_score_meta(key)[0] or "chart set"
        if published and joined and published > joined:
            return f"{source} ({joined} of {published} rows are tracked models)"
        return f"{source} ({len(extra)} scored)"
    surface = str(getattr(r, "surface", "") or "")
    if surface == "none":
        return "not published free (AA's paid data API only)"
    if surface == "chart":
        return "chart set (no live values in current source)"
    if surface == "rich":
        return "model page only (not in the rich dataset)"
    return "no data in current source"


def _benchmarks(query: str = "", domain: str = "", tag: str = "",
                verbose: bool = False) -> str:
    """The searchable index over everything rankable (see ``catalog.rankables``)."""
    if domain and _domain_tokens(domain) is None:
        raise ValueError(_unknown_domain(domain))
    if tag:
        known = _known_tags()
        if not any(_norm_alias(t) == _norm_alias(tag) for t in known):
            raise ValueError(
                f"unknown tag {_q(tag)} — valid tags: {', '.join(known)}\n"
                "— or use domain= for a coarser search (aa_benchmarks with no "
                "arguments lists everything)"
            )
    rows_all = _rankable_list()
    entries = _rankable_list(domain=domain, tag=tag, query=query)
    if not entries:
        untracked = _untracked(query) if query else None
        if untracked is not None:
            name, note = untracked
            head = _header(count=f"AA does not track {name}",
                           note=f"query={render.clean(query, None)}")
            return f"{head}\n— {note}"
        task = getattr(catalog, "task_domain", None)
        hit = task(query) if query and callable(task) else None
        if hit is not None:
            name, note = hit
            head = _header(count=f"AA does not measure {name}",
                           note=f"query={render.clean(query, None)}")
            return (f"{head}\n— {note}\n"
                    "— aa_benchmarks lists every rankable AA does measure "
                    "(aa_benchmarks domain=<name> for a task area)")
        wanted = " · ".join(part for part in (
            f"query={render.clean(query, None)}" if query else "",
            f"domain={render.clean(domain, None)}" if domain else "",
            f"tag={render.clean(tag, None)}" if tag else "") if part)
        pool = [str(getattr(r, "label", "")) for r in rows_all]
        pool += [str(getattr(r, "key", "")) for r in rows_all]
        near = ", ".join(_close(query or domain or tag, pool, n=3)) or "none"
        raise ValueError(
            f"no rankable matches {wanted or '(no filter)'} — closest: {near}\n"
            "— aa_benchmarks with no arguments lists every rankable thing "
            f"({len(rows_all)}), or try domain=<name>"
        )

    static_note = ""
    try:
        lb = _lb_rows()
        merged = _models_state(rich=True)[0]
    except (AAFetchError, LookupError, ValueError) as exc:
        # This is a static catalog; an unparseable live pool must not hide it.
        lb, merged = [], []
        static_note = (f"live model pool unavailable ({str(exc).splitlines()[0]}) — "
                       "coverage below is the static catalog only")
    show_measures = verbose or len(entries) <= 10
    headers = ["Thing", "Kind", "Unit", "Coverage", "How to query"]
    if show_measures:
        headers.append("Measures")
    table_rows: list[list[str]] = []
    for r in entries:
        base = [str(getattr(r, "label", "")), str(getattr(r, "kind", "")),
                str(getattr(r, "unit", "")),
                _rankable_coverage(r, lb, merged), str(getattr(r, "how", ""))]
        if show_measures:
            base.append(str(getattr(r, "desc", "")))
        table_rows.append(base)

    cache_name = _lb_cache()
    qdomain = _query_domain(query) if query else None
    note = " · ".join(part for part in (
        (f"query={render.clean(query, None)}"
         + (" (domain match)" if qdomain else "")) if query else "",
        f"domain={render.clean(domain, None)}" if domain else "",
        f"tag={render.clean(tag, None)}" if tag else "") if part)
    count = f"{len(table_rows)} of {len(rows_all)} rankables"
    if static_note:
        note = " · ".join(part for part in (note, static_note) if part)
    head = _header(count=count, note=note, name=cache_name)
    body = _table_block(head, headers, table_rows)
    if not show_measures:
        body += ("\n— descriptions hidden at this size; add query=<term> or "
                 "verbose=true to show Measures")
    return body


# --------------------------------------------------------------------------- #
# aa_benchmark_leaderboard
# --------------------------------------------------------------------------- #


def _benchmark_leaderboard(
    benchmark: str,
    top: int = 15,
    fields: str = "",
    creator: str = "",
    open_weights: bool | None = None,
    min_intelligence: float | None = None,
    include_estimates: bool = True,
    include_deprecated: bool = True,
    refresh: bool = False,
) -> str:
    try:
        key = _metric_key(benchmark, "benchmark")
    except ValueError:
        untracked = _untracked(benchmark)
        if untracked is not None:
            name, note = untracked
            raise ValueError(f"AA does not track {name} — {note}") from None
        near = ", ".join(_close(benchmark, [b.key for b in catalog.BENCHMARKS.values()]
                                + [b.label for b in catalog.BENCHMARKS.values()]))
        raise ValueError(
            f"unknown benchmark {_q(benchmark)} — closest: {near}\n"
            "— aa_benchmarks lists every benchmark with its slug and coverage"
        ) from None
    bench = catalog.BENCHMARKS.get(key)
    if bench is None:
        raise ValueError(
            f"{_q(benchmark)} resolved to {key!r}, which is not a ranked benchmark "
            "— try aa_benchmarks for the catalog"
        )
    if bench.unit == "mixed":
        raise ValueError(_breakdown_text(key, bench.label))
    n = top if isinstance(top, int) and top > 0 else 15

    def keep(m: Model) -> bool:
        if creator and not (m.creator and creator.lower() in m.creator.lower()):
            return False
        if open_weights is not None and m.is_open_weights != open_weights:
            return False
        if min_intelligence is not None and (m.intelligence is None
                                             or m.intelligence < min_intelligence):
            return False
        if m.deprecated and not include_deprecated:
            return False
        return not (not include_estimates and m.estimated)

    def scored(models: Sequence[Model]) -> list[tuple[Model, float]]:
        out = []
        for m in models:
            value = select.lookup(m, key)
            if value is not None and keep(m):
                out.append((m, float(value)))
        return out

    lb_plain = _lb_rows(refresh)
    needs_rich = _rich_needed(refresh=refresh, benchmark_key=key)
    if needs_rich or key in _OWN_PAGE_KEYS:
        lb, rich_used = _models_state(refresh, rich=True)
    else:
        lb, rich_used = list(lb_plain), False
    cache_name = _lb_cache()
    include_extra = True
    source_note: str
    lower_better = _lower_is_better(key)

    # AA's own page for this index (a capability chart set, or the Openness /
    # Decision index array) is authoritative for its own key and is the only
    # source of a capability index's sub-scores; join it onto the merged rows.
    index_source = ""
    if key in _OWN_PAGE_KEYS:
        joined, index_source = _join_extra_scores(lb, key, refresh)
        if index_source:
            lb = joined

    if _is_index_key(key):
        # Capability / Coding / Agentic indexes have no leaderboard column: the
        # merged source covers the six capability indexes far more widely than
        # their own 26-row chart sets, and AA publishes Coding/Agentic nowhere free.
        pairs = scored(lb)
        if not pairs:
            raise _no_rank_error(key, bench.label)
        origin = " + ".join(part for part in (index_source, "rich dataset") if part)
        source_note = f"{bench.label} · {origin} — not a full leaderboard"
    else:
        pairs = scored(lb)
        if pairs:
            native = scored(lb_plain)
            if index_source and len(pairs) > len(native):
                origin = " + ".join(part for part in (
                    index_source, "rich dataset" if rich_used else "") if part)
            elif rich_used and len(pairs) > len(native):
                origin = "rich dataset"
            else:
                origin = "leaderboard"
            source_note = f"{bench.label} · {origin}"
            if origin != "leaderboard":
                source_note += " — not a full leaderboard"
        else:
            # AA's own chart set for the eval page
            pairs = []
            if bench.slug:
                try:
                    chart = _load(f"eval_{bench.slug}",
                                  loaders.eval_models, bench.slug, refresh=refresh)
                except (AAFetchError, ValueError):
                    chart = []
                pairs = scored(chart)
                if not pairs and chart:
                    pairs = _raw_chart_pairs(bench.slug, key, chart, keep, refresh=refresh)
                if pairs:
                    source_note = f"{bench.label} · AA chart set — not a full leaderboard"
                    cache_name = f"eval_{bench.slug}"
            # homepage panel (top 20) for the security boards
            if not pairs and bench.slug:
                try:
                    panel = _home_rows(refresh).get(f"eval:{bench.slug}") or []
                except AAFetchError:
                    panel = []
                raw = []
                for item in panel:
                    value = _panel_value(item, key)
                    if value is None or not keep(_panel_model(item, key)):
                        continue
                    try:
                        raw.append((_panel_model(item, key), float(value)))
                    except (TypeError, ValueError):
                        continue
                pairs = raw
                if pairs:
                    source_note = f"{bench.label} · homepage panel — not a full leaderboard"
                    cache_name = "home"
                    include_extra = False

    if not pairs:
        if getattr(bench, "source_hint", "") == "none":
            # AA removed the metric (GDPval's normalized fraction): say so instead
            # of substituting another metric's value or raising a parse error.
            return _no_rank_text(key, bench.label)
        raise ValueError(
            f"no data for benchmark {bench.label!r}: not in the leaderboard, "
            "the eval chart set or the homepage panels — try aa_benchmarks for coverage"
        )

    # Honour the metric direction: the four refusal/hallucination keys are
    # lower-is-better, and ranking them descending names the worst models as
    # "leaders" (audit H2/B2).
    pairs.sort(key=lambda t: t[1], reverse=not lower_better)
    if lower_better:
        source_note += " · lower is better"
    # rows that display the same score are ordered by a named secondary key (G7)
    order = {m.slug: i for i, m in enumerate(_break_display_ties(
        [m for m, _ in pairs], lambda m: _fmt(key, select.lookup(m, key))))}
    pairs.sort(key=lambda t: order[t[0].slug])
    shown = pairs[:n]
    tie_note = _tie_note([m for m, _ in shown],
                         lambda m: _fmt(key, select.lookup(m, key)))

    request_keys = _split(fields)
    wants_ci = any(k in ("ci_lower", "ci_upper", "ci") for k in request_keys)
    ci_map = _chart_ci(bench.slug, refresh) if wants_ci else {}

    score_label = bench.label
    if bench.unit not in ("%", "index"):
        score_label += f" ({bench.unit})"
    default_cols = [("name", "Model"), ("slug", "Slug"), ("creator", "Creator"),
                    ("score", score_label)]
    cols: list[tuple[str, str]]
    unknown: list[str] = []
    if fields:
        cols = _cols([], fields, ("score", "ci_lower", "ci_upper", "ci"),
                     _BENCH_IDENTITY + [("benchmark", "Benchmark")], unknown)
    else:
        cols = list(default_cols)
        if include_extra:
            cols += [("intelligence", "Intel"), ("cost_per_task", "$/Task")]
    if not fields and n > 15:
        cols = [c for c in cols if c[0] != "creator"]

    # A bool ``Model.deprecated`` cannot express "unknown": the leaderboard rows
    # always carry a status (release array), but chart-set / panel rows do not.
    # State the known count in the header and never print a column that is ``-``
    # for every row while claiming deprecated rows were included.
    depr_status = {m.slug: m.deprecated for m in lb_plain}
    depr_known = sum(1 for m, _ in pairs if m.slug in depr_status)
    deprecated_present = any(depr_status.get(m.slug) for m, _ in pairs)
    requested_depr = any(str(k).strip().lower() in ("deprecated", "depr")
                         for k in request_keys)
    if depr_known == 0 and requested_depr:
        cols = [c for c in cols if c[0] != "deprecated"]
    elif (deprecated_present or depr_known) and not any(
            c[0] == "deprecated" for c in cols):
        cols.append(("deprecated", "Depr"))
    if include_deprecated:
        source_note += (" · deprecated rows included (include_deprecated=true; "
                        "false hides them")
        source_note += (f"; deprecation status known for {depr_known} of "
                        f"{len(pairs)} rows)" if depr_known else
                        "; AA publishes no deprecation status for these rows — "
                        "not the same as none deprecated)")
    else:
        source_note += " · deprecated rows hidden (include_deprecated=false"
        source_note += (f"; deprecation status known for {depr_known} of "
                        f"{len(pairs)} rows)" if depr_known else ")")

    # The ``*`` marks an AA-estimated value. Only the Intelligence Index carries
    # that flag today (``intelligenceIndexIsEstimated``), so a published Openness /
    # capability / benchmark score must never inherit it from the model's
    # intelligence estimate (audit round 2, M2).
    starred = key == "intelligence"
    table_rows = []
    estimated = 0
    for m, value in shown:
        lo, hi = ci_map.get(m.slug, (None, None))
        if starred and m.estimated:
            estimated += 1
        cells = []
        for col, _label in cols:
            if col == "score":
                cells.append(_fmt(key, value)
                             + ("*" if starred and m.estimated else ""))
            elif col == "benchmark":
                cells.append(bench.label)
            elif col == "deprecated":
                cells.append("yes" if depr_status.get(m.slug)
                             else ("no" if m.slug in depr_status else ""))
            elif col in ("ci_lower", "ci_upper", "ci"):
                if col == "ci":
                    cells.append("-" if lo is None and hi is None
                                 else f"{_elo_int(lo)}–{_elo_int(hi)}")
                else:
                    cells.append(_elo_int(lo if col == "ci_lower" else hi))
            else:
                cells.append(_fmt(col, select.lookup(m, col)))
        table_rows.append(cells)

    # the coverage number describes the dataset; a filter only narrows the view
    dataset_scored = _dataset_scored(lb, key)
    filtered = bool(creator or open_weights is not None
                    or min_intelligence is not None or not include_estimates)
    if filtered:
        count = (f"{len(shown)} shown of {len(pairs)} matching "
                 f"({len(lb)} tracked)")
    else:
        count = f"{len(shown)} of {len(pairs)} scored ({len(lb)} tracked)"
    head = _header(count=count, note=source_note, name=cache_name,
                   source_label=_prov_label(rich_used))
    body = _table_block(head, [label for _, label in cols], table_rows, trim=_fields_trim(fields),
                        identity=_identity_labels(cols))
    notes = []
    if tie_note:
        notes.append(tie_note)
    if unknown:
        notes.append(_unknown_field_note(unknown))
    if requested_depr and depr_known == 0:
        notes.append(
            "deprecated: no row on this surface carries a deprecation status — "
            "the column is omitted rather than shown as '-' (aa_leaderboard's "
            "Depr column has the status where AA publishes it)")
    if key in _CAPABILITY_KEYS:
        notes.append(_capability_coverage_note(
            key, bench.label, lb, include_deprecated=True,
            shown=[m for m, _v in shown], rich_used=rich_used))
    match_note = _filter_match_note(len(pairs), dataset_scored, filtered)
    if match_note:
        notes.append(match_note)
    notes += _missing_notes(lb, [("intelligence", "intelligence",
                                  min_intelligence is not None)])
    if estimated:
        body += ("\n— * = the model's Intelligence Index is AA-estimated (fitted "
                 "across variants of the same model family); include_estimates=false "
                 "drops estimated models")
    if notes:
        body += "\n" + render.note(notes)
    return body


def _chart_ci(slug: str, refresh: bool = False) -> dict[str, tuple[float | None, float | None]]:
    """95% CI (lower, upper) per chart-set model, from the raw eval-page records."""
    if not slug:
        return {}
    try:
        path = loaders.SOURCE_URLS["eval"].format(slug=slug)
        name = f"eval_{slug}"
        text = _get(loaders.url(path), name,
                    refresh=refresh and not _already_fetched(name)).text
        records = flight.find_array(
            flight.payload(text), ("chartDefaultSelected", "releaseDate", "suffix")
        )
    except Exception:  # pragma: no cover - best-effort enrichment
        return {}
    out: dict[str, tuple[float | None, float | None]] = {}
    for rec in records:
        if not isinstance(rec, dict) or not rec.get("slug"):
            continue
        lower = rec.get("ciLower")
        upper = rec.get("ciUpper")
        breakdown = rec.get("briefcaseBreakdown")
        if isinstance(breakdown, dict):
            lower = lower if lower is not None else breakdown.get("lower95ci")
            upper = upper if upper is not None else breakdown.get("upper95ci")
        if lower is not None or upper is not None:
            out[rec["slug"]] = (lower, upper)
    return out


def _raw_chart_pairs(slug: str, key: str, models: Sequence[Model], keep,
                     refresh: bool = False) -> list[tuple[Model, float]]:
    """Fallback for chart-set benchmarks the normalizer does not surface.

    Some eval-page chart fields (e.g. ``briefcaseElo``) live on the raw record
    but not on ``Model.evals``, so read the page's ``initialModels`` array and
    pair the value with the normalized model by slug.
    """
    try:
        path = loaders.SOURCE_URLS["eval"].format(slug=slug)
        name = f"eval_{slug}"
        text = _get(loaders.url(path), name,
                    refresh=refresh and not _already_fetched(name)).text
        records = flight.find_array(
            flight.payload(text), ("chartDefaultSelected", "releaseDate", "suffix")
        )
    except Exception:  # pragma: no cover - best-effort fallback
        return []
    raw = {r.get("slug"): r for r in records if isinstance(r, dict)}
    out: list[tuple[Model, float]] = []
    for m in models:
        if not keep(m):
            continue
        rec = raw.get(m.slug) or {}
        value = rec.get(key)
        if value is None and key == "briefcaseElo":
            # Only the metric that owns this breakdown may read its Elo.  A
            # percentage/fraction metric must never be handed an Elo: the old
            # unconditional fallback rendered ``gdpvalNormalized`` as
            # 1610.19 × 100 = 161019.0% (audit D1).
            breakdown = rec.get("briefcaseBreakdown")
            if isinstance(breakdown, dict):
                value = breakdown.get("elo")
        if value is None:
            value = select.lookup(m, key)
        if value is not None:
            out.append((m, float(value)))
    return out


#: benchmark key -> the homepage eval-panel field carrying its value. AA names
#: the headline panel scalar ``score``; companion metrics keep their own name
#: (the Cyber Index panel ships ``refusalRate`` and ``mitigationStatus``).
_PANEL_FIELDS = {
    "cyberRefusalRate": "refusalRate",
    "cyberMitigationStatus": "mitigationStatus",
    "cweBenchRefusalRate": "refusalRate",
    "cybergymE2eRefusalRate": "refusalRate",
    "deepsecBenchRefusalRate": "refusalRate",
}


def _panel_value(item: dict, key: str) -> Any:
    """The homepage-panel value for ``key`` (``score`` unless the key is a companion)."""
    return item.get(_PANEL_FIELDS.get(key, "score"))


def _panel_model(item: dict, key: str) -> Model:
    """Wrap a homepage eval-panel row as a minimal :class:`Model` for filtering."""
    return Model(
        slug=item.get("slug") or "", name=item.get("name") or item.get("slug") or "",
        short_name=item.get("shortName") or item.get("name") or "",
        creator=None, creator_slug=None, release_date=None, deprecated=False,
        deprecated_to=None, is_reasoning=False, is_open_weights=False, effort=None,
        params_b=None, active_params_b=None, context_tokens=None, license=None,
        license_url=None, weights_url=None, knowledge_cutoff=None, size_class=None,
        modalities_in=(), modalities_out=(), intelligence=None, estimated=False,
        indices={}, evals={key: _panel_value(item, key)}, pricing={}, speed={},
        cost_per_task=None, cost_breakdown=None, per_eval_cost=None, source="panel",
    )


# --------------------------------------------------------------------------- #
# aa_providers
# --------------------------------------------------------------------------- #

_PROV_SORT = ("cost_per_task", "price_in", "price_out", "cache_read", "cache_write",
              "tps", "ttft", "intelligence", "context_tokens")
_PROV_COLS = [
    ("host", "Host"), ("model_name", "Model"),
    ("price_in", "In $/M"), ("price_out", "Out $/M"),
    ("cost_per_task", "$/Task"), ("tps", "tok/s"), ("ttft", "TTFT"),
]
_PROV_COLS_MODEL = [("host", "Host"), ("model_name", "Model"), ("precision", "Prec"),
                    ("price_in", "In $/M"), ("price_out", "Out $/M"),
                    ("cost_per_task", "$/Task"), ("tps", "tok/s")]
_PROV_EXTRA = ("host", "model_name", "model_slug", "precision", "cache_read",
               "discount", "e2e", "function_calling", "json_mode",
               "openai_compatible", "source")
#: identity names → the providers column each resolves to (G2): the endpoint record
#: carries the model slug/name and the host, and `creator` comes from the model row.
_PROV_IDENTITY_MAP = {
    "model": "model_name", "name": "model_name", "modelname": "model_name",
    "slug": "model_slug", "modelslug": "model_slug", "host": "host",
    "creator": "creator",
}


def _identity_labels(cols: Sequence[tuple[str, str]]) -> list[str]:
    """The header labels of the identity columns in ``cols`` (never "no data", G2)."""
    return [label for key, label in cols
            if key in ("name", "slug", "creator", "host", "model_name", "model_slug",
                       "benchmark")]


def _creator_map(refresh: bool = False) -> dict[str, str]:
    """``{model slug: creator}`` from the leaderboard rows (provider endpoints have
    no creator of their own, so an identity ``fields=creator`` resolves here)."""
    return {m.slug: str(m.creator) for m in _lb_rows(refresh) if m.creator}


def _endpoint_cell(e, key: str, creators: dict[str, str] | None = None,
                   variant: str | None = None) -> str:
    """One provider cell. Identity keys resolve from the endpoint record (G2).

    ``fields=model`` (or ``name``/``slug``) resolves to the surface's own identity
    column, so the Model column can never blank while the payload carries the
    model slug on every endpoint; ``creator`` comes from the model's record and
    ``variant`` from the release-family map.
    """
    if key in ("model_name", "name"):
        return _txt(e.model_name or e.model_slug)
    if key == "variant":
        return _txt(variant)
    if key in ("model_slug", "slug"):
        return _txt(e.model_slug)
    if key == "host":
        return _txt(e.host)
    if key == "creator":
        return _txt((creators or {}).get(e.model_slug))
    if key == "precision":
        return _txt(e.precision)
    if key == "cache_read":
        return _fmt("cache_read", e.cache_read)
    if key == "discount":
        return _discount(e.cache_hit_discount)
    if key in ("function_calling", "json_mode", "openai_compatible"):
        value = getattr(e, key)
        return "-" if value is None else ("yes" if value else "no")
    if key == "context_tokens":
        return render.ctx(e.context_tokens)
    return _fmt(key, getattr(e, key, None))


def _endpoint_sort(eps: Sequence[loaders.Endpoint], key: str) -> list[loaders.Endpoint]:
    metric = catalog.metric(key)
    desc = not (metric is not None and metric.better == "low")
    present = [e for e in eps if getattr(e, key, None) is not None]
    missing = [e for e in eps if getattr(e, key, None) is None]
    present.sort(key=lambda e: getattr(e, key), reverse=desc)
    return present + missing


_PROV_SORT_ALIASES = {
    "input": "price_in", "in": "price_in",
    "output": "price_out", "out": "price_out",
    "cacheread": "cache_read", "cachehit": "cache_read", "read": "cache_read",
    "cachewrite": "cache_write", "write": "cache_write",
    "speed": "tps", "latency": "ttft",
    "ctx": "context_tokens", "context": "context_tokens", "contextwindow": "context_tokens",
    "cost": "cost_per_task", "cpt": "cost_per_task", "costpertask": "cost_per_task",
    "intel": "intelligence", "iq": "intelligence",
}


def _prov_sort_key(sort: str) -> str:
    raw = str(sort).strip().lower()
    if raw in _PROV_SORT:
        return raw
    key = _PROV_SORT_ALIASES.get(_norm_alias(sort))
    if key is not None:
        return key
    norm = _norm_alias(sort)
    for candidate in _PROV_SORT:  # tolerate price-in / cache.read spellings
        if _norm_alias(candidate) == norm:
            return candidate
    near = ", ".join(_close(str(sort), list(_PROV_SORT) + list(_PROV_SORT_ALIASES)))
    raise ValueError(
        f"unknown sort {_q(sort)} — closest: {near or 'none'}\n"
        f"— accepted: {', '.join(_PROV_SORT)} "
        "(aliases: input, output, cache_read, cache_write, speed, latency, ctx, cost)"
    )


def _with_sort_col(cols: Sequence[tuple[str, str]],
                   sort_key: str) -> list[tuple[str, str]]:
    """Append the sort key as a visible column when the default set omits it.

    ``aa_providers sort=ttft`` reorders rows but the default columns hide TTFT,
    so the ranking is unreadable — show what the table is sorted by (the same
    rule ``aa_leaderboard`` already follows).
    """
    cols = list(cols)
    if any(k == sort_key for k, _ in cols):
        return cols
    return cols + [(sort_key, _col_label(sort_key))]


#: an AA providers page that publishes no endpoint list at all
_NO_ENDPOINT_RE = re.compile(r'"hostModels"\s*:\s*(?:\[\s*\]|null)')


def _publishes_no_endpoints(slug: str) -> bool:
    """True when AA's ``/models/<slug>/providers`` page lists no endpoints (G3).

    The page exists (the fetch succeeded) but AA publishes an empty ``hostModels``
    array — an absence, not a broken payload, so it must be explained rather than
    reported as an unusable cache file. The cached copy the failed parse just read
    is reused (no second network call).
    """
    try:
        path = loaders.SOURCE_URLS["model_providers"].format(slug=slug)
        text = _get(loaders.url(path), f"providers_{slug}").text
    except Exception as exc:  # pragma: no cover - offline / missing cache
        log.debug("providers: could not re-read %s (%s)", slug, exc)
        return False
    return bool(_NO_ENDPOINT_RE.search(text))


def _no_endpoints_text(base: Model) -> str:
    """The G3 explanation for a model AA lists no API providers for."""
    head = _header(count=f"AA lists no API providers for {base.slug}",
                   note="no published pricing or endpoint measurements",
                   name=f"providers_{base.slug}")
    return (f"{head}\n"
            f"— AA lists no API providers for {base.name} ({base.slug}); it has no "
            "published pricing or endpoint measurements (see aa_model for what AA "
            "does publish)")


_EFFORT_SUFFIX_RE = re.compile(
    r"-(" + "|".join(re.escape(x) for x in sorted(_EFFORT_SUFFIXES,
                                                  key=len, reverse=True)) + r")$")


def _release_family(base: Model, pool: Sequence[Model]) -> list[Model]:
    """The release and its effort siblings, whatever variant ``base`` resolved to.

    ``aa_providers model=gemini-4-carbon`` resolves to the release's *default*
    variant, but the provider board also carries its Medium/Low siblings — and a
    cheaper sibling must never be invisible ("1 of 1 endpoints" was false).
    """
    by_slug = {m.slug: m for m in pool}
    root = base
    slug = base.slug
    for _ in range(4):
        match = _EFFORT_SUFFIX_RE.search(slug)
        if not match or match.start() == 0:
            break
        slug = slug[: match.start()]
        if slug in by_slug:
            root = by_slug[slug]
            break
    family = [root] + [s for s in _effort_siblings(root, pool)
                       if s.slug != root.slug]
    if all(m.slug != base.slug for m in family):
        family.append(base)
    return family


def _variant_slug_for(label: str, family: Sequence[Model]) -> str:
    """The family slug whose variant label is ``label`` (falls back to the label)."""
    norm = _norm_alias(label)
    for m in family:
        if _norm_alias(_variant_label(m)) == norm:
            return m.slug
    return label


def _endpoint_variant(e, base: Model, family: Sequence[Model]) -> str:
    """The release variant an endpoint row serves.

    The provider board nests the *release* slug on every row and puts the variant
    in the model name (``Claude Sonnet 5.5 (medium)``); the per-model page's row
    is the release's default variant.
    """
    match = re.search(r"\(([^()]*)\)\s*$", str(e.model_name or ""))
    if match and match.group(1).strip():
        label = match.group(1).strip()
        return label[:1].upper() + label[1:]
    for m in family:
        if m.slug == e.model_slug:
            return _variant_label(m) or m.slug
    return _variant_label(base) or base.slug


def _providers(model: str = "", host: str = "", top: int = 15,
               sort: str = "cost_per_task", fields: str = "",
               open_weights: bool | None = None, min_context: int | None = None,
               refresh: bool = False) -> str:
    n = top if isinstance(top, int) and top > 0 else 15
    sort_key = _prov_sort_key(sort)

    if model:
        pool = _models(refresh)
        base = _resolve_slug(model, pool)
        try:
            endpoints = list(_load(f"providers_{base.slug}",
                                   loaders.provider_endpoints, base.slug,
                                   refresh=refresh))
        except (ValueError, AAFetchError):
            if _publishes_no_endpoints(base.slug):
                return _no_endpoints_text(base)
            raise
        for e in endpoints:
            if not e.model_slug:
                e.model_slug = base.slug
        # The model page describes one variant; the provider board also carries the
        # release's effort siblings, which can be cheaper. Aggregate them so
        # "cheapest provider" never misses an endpoint (round-2 audit P2).
        family = _release_family(base, pool)
        family_slugs = {m.slug for m in family}
        base_label = _variant_label(base) or base.slug
        family_used = False
        if len(family) > 1:
            try:
                board = list(_load("providers_board", loaders.provider_board,
                                   refresh=refresh))
            except (AAFetchError, ValueError):
                board = []
            page_hosts = {e.host for e in endpoints}
            seen = {(e.host, _norm_alias(base_label), e.precision)
                    for e in endpoints}
            for e in board:
                if e.model_slug not in family_slugs:
                    continue
                label = _endpoint_variant(e, base, family)
                norm = _norm_alias(label)
                if norm == _norm_alias(base_label) and e.host in page_hosts:
                    # the model page already carries this variant+host row
                    continue
                key = (e.host, norm, e.precision)
                if key in seen:
                    continue
                seen.add(key)
                endpoints.append(e)
                family_used = True
        if host:
            hl = host.lower()
            endpoints = [e for e in endpoints if hl in (e.host or "").lower()]
        # Endpoint payloads often omit the context window; fall back to the
        # model-level value rather than rendering a misleading "-".
        ctx_filled = False
        by_slug = {m.slug: m for m in family}
        for e in endpoints:
            if e.context_tokens is None:
                rec = by_slug.get(e.model_slug) or base
                if rec.context_tokens:
                    e.context_tokens = rec.context_tokens
                    ctx_filled = True
        if min_context is not None:
            endpoints = [e for e in endpoints
                         if e.context_tokens is not None and e.context_tokens >= min_context]
        endpoints = _endpoint_sort(endpoints, sort_key)
        if not endpoints:
            if host:
                return (f"# no provider endpoints for {base.name} "
                        f"(aa.{base.slug}) match host~{render.clean(host, None)} "
                        "— drop the host filter")
            return (f"# no provider endpoints recorded for {base.name} (aa.{base.slug}) "
                    "— the model-page providers array was empty or all filtered out")
        creators = _creator_map(refresh)
        unknown: list[str] = []
        cols = _cols(_PROV_COLS_MODEL, fields,
                     _PROV_EXTRA + (("variant",) if family_used else ()),
                     _PROV_IDENTITY, unknown, _PROV_IDENTITY_MAP)
        if not fields:
            cols = _with_sort_col(cols, sort_key)
            if family_used:
                at = next((i + 1 for i, (k, _l) in enumerate(cols)
                           if k == "model_name"), 1)
                cols.insert(at, ("variant", "Variant"))
        rows = []
        for e in endpoints[:n]:
            label = _endpoint_variant(e, base, family) if family_used else None
            rows.append([_endpoint_cell(e, k, creators, label) for k, _ in cols])
        count = f"{len(rows)} of {len(endpoints)} endpoints"
        note_text = f"{base.name} (aa.{base.slug}), by {sort_key}"
        if host:
            note_text = (f"{base.name} (aa.{base.slug}), "
                         f"host~{render.clean(host, None)}, by {sort_key}")
        if family_used:
            note_text = (f"{base.name} + release family (aa.{base.slug}), "
                         + (f"host~{render.clean(host, None)}, " if host else "")
                         + f"by {sort_key}")
        head = _header(count=count, note=note_text,
                       name=f"providers_{base.slug}")
        body = _table_block(head, [lbl for _, lbl in cols], rows, trim=_fields_trim(fields),
                            identity=_identity_labels(cols))
        notes = []
        if ctx_filled:
            notes.append("context is model-level, not per-endpoint")
        if family_used:
            shown_labels = list(dict.fromkeys(
                _endpoint_variant(e, base, family) for e in endpoints))
            labels = [lbl for lbl in shown_labels
                      if _norm_alias(lbl) != _norm_alias(base_label)]
            if labels:
                names = ", ".join(f"{lbl} aa.{_variant_slug_for(lbl, family)}"
                                  for lbl in labels)
                notes.append(f"release family included: {names} — the model "
                             "page describes the default variant only")
        if unknown:
            notes.append(_unknown_field_note(unknown))
        note = _zero_cost_note("cost_per_task", [
            (e.model_name or e.model_slug, e.cost_per_task,
             bool((by_slug.get(e.model_slug) or base).is_open_weights))
            for e in endpoints[:n]])
        if note:
            notes.append(note)
        if notes:
            body += "\n" + render.note(notes)
        return body

    endpoints = _load("providers_board", loaders.provider_board, refresh=refresh)
    if host:
        hl = host.lower()
        endpoints = [e for e in endpoints if hl in (e.host or "").lower()]
    if open_weights is not None:
        ow = {m.slug: m.is_open_weights for m in _lb_rows(refresh)}
        endpoints = [e for e in endpoints
                     if ow.get(e.model_slug) == open_weights]
    board_ctx = False
    if any(e.context_tokens is None for e in endpoints):
        by_slug = {m.slug: m for m in _models(refresh)}
        for e in endpoints:
            if e.context_tokens is None:
                rec = by_slug.get(e.model_slug)
                if rec is not None and rec.context_tokens:
                    e.context_tokens = rec.context_tokens
                    board_ctx = True
    if min_context is not None:
        endpoints = [e for e in endpoints
                     if e.context_tokens is not None and e.context_tokens >= min_context]
    endpoints = _endpoint_sort(endpoints, sort_key)

    if not endpoints:
        sel = []
        if host:
            sel.append(f"host~{render.clean(host, None)}")
        if open_weights is not None:
            sel.append("open-weights" if open_weights else "closed-weights")
        if min_context is not None:
            sel.append(f"ctx>={min_context:g}")
        return f"# no provider endpoints match {', '.join(sel) or 'filters'} — drop one filter"

    unknown: list[str] = []
    cols = _cols(_PROV_COLS, fields, _PROV_EXTRA, _PROV_IDENTITY, unknown,
                 _PROV_IDENTITY_MAP)
    if not fields:
        cols = _with_sort_col(cols, sort_key)
    creators = _creator_map(refresh)
    rows = [[_endpoint_cell(e, k, creators) for k, _ in cols]
            for e in endpoints[:n]]
    explicit = bool(host or open_weights is not None or min_context is not None)
    if explicit:
        count = f"{len(rows)} shown of {len(endpoints)} matching"
        note = (f"host~{render.clean(host, None)}, by {sort_key}" if host
                else f"by {sort_key}")
    else:
        count = f"{len(rows)} of {len(endpoints)} endpoints"
        note = f"cheapest across all hosts, by {sort_key}"
    head = _header(count=count, note=note, name="providers_board")
    body = _table_block(head, [lbl for _, lbl in cols], rows, trim=_fields_trim(fields),
                        identity=_identity_labels(cols))
    notes = []
    if board_ctx:
        notes.append("context is model-level, not per-endpoint")
    if unknown:
        notes.append(_unknown_field_note(unknown))
    zero = _zero_cost_note("cost_per_task", [
        (e.model_name or e.model_slug, e.cost_per_task, False)
        for e in endpoints[:n]])
    if zero:
        notes.append(zero)
    if notes:
        body += "\n" + render.note(notes)
    return body


# --------------------------------------------------------------------------- #
# aa_media
# --------------------------------------------------------------------------- #

_SPEECH_BOARDS = {
    "speech_to_text": "stt",
    "speech_to_text_streaming": "stt_streaming",
    "speech_to_speech": "sts",
}
#: extra accepted spellings for a speech board (README: "realtime voice")
_SPEECH_ALIASES = {
    "realtime_voice": "speech_to_speech",
    "realtime_sts": "speech_to_speech",
}
#: short board names an agent types first (the audit: `board=image` failed)
_MEDIA_BOARD_ALIASES = {
    "image": "text_to_image",
    "image_gen": "text_to_image",
    "image_generation": "text_to_image",
    "video": "text_to_video",
    "text2video": "text_to_video",
    "t2v": "text_to_video",
    "image2video": "image_to_video",
    "i2v": "image_to_video",
    "tts": "text_to_speech",
    "stt": "speech_to_text",
    "asr": "speech_to_text",
    "speech": "speech_to_text",
}
#: media row field -> column label
_MEDIA_FIELDS = {
    "rank": "Rank", "name": "Model", "model": "Model", "creator": "Creator",
    "elo": "Elo", "ci": "95% CI", "ci_lower": "CI low", "ci_upper": "CI high",
    "appearances": "Appearances", "price": "Price", "price_unit": "Price unit",
    "release": "Release", "release_date": "Release", "open_weights": "Open",
    "url": "URL", "wer": "WER%", "wer_index": "WER%", "host": "Host",
    "sts": "STS", "sts_index": "STS", "speed": "Speed",
}
_MEDIA_CANON = {"model": "name", "release": "release_date", "wer": "werIndex",
                "wer_index": "werIndex", "sts": "stsIndex",
                "sts_index": "stsIndex", "host": "hostName", "speed": "speed"}
#: the order `fields=all` renders (every column the surface can fill)
_MEDIA_FIELD_ORDER = [
    "rank", "name", "creator", "hostName", "elo", "ci", "ci_lower", "ci_upper",
    "stsIndex", "werIndex", "appearances", "speed", "price", "price_unit",
    "release_date", "open_weights", "url",
]



_MEDIA_LABELS = {
    "rank": "Rank", "name": "Model", "creator": "Creator", "elo": "Elo",
    "ci": "95% CI", "ci_lower": "CI low", "ci_upper": "CI high",
    "appearances": "Appearances", "price": "Price", "price_unit": "Price unit",
    "release_date": "Release", "open_weights": "Open", "url": "URL",
    "werIndex": "WER%", "hostName": "Host", "stsIndex": "STS", "speed": "Speed",
}


def _media_cols(fields: Any, unknown: list[str] | None = None) -> list[tuple[str, str]]:
    """Media fields are row keys (``elo``/``ci``/``name``), not model metrics.

    The identity column (``Model``) and ``Rank`` are always rendered, so a
    requested table is never anonymous and a ranking always keeps its rank
    (``fields=model,elo,price`` used to drop Rank silently). A wildcard
    (``all``/``*``) selects every catalogued column. A field the board does not
    have is appended to ``unknown`` (when given) and ignored, so a long
    ``fields=`` list renders what resolves instead of aborting the call (G6).
    """
    names = _split(fields)
    if any(_is_wildcard_field(n) for n in names):
        return [(key, _MEDIA_LABELS[key]) for key in _MEDIA_FIELD_ORDER]
    out: list[tuple[str, str]] = []
    keys: set[str] = set()
    for raw in names:
        name = re.sub(r"[\s-]+", "_", raw.strip().lower())
        if name not in _MEDIA_FIELDS:
            if unknown is not None:
                unknown.append(raw)
                continue
            raise ValueError(
                f"unknown field {_q(raw)} — valid: {', '.join(sorted(_MEDIA_FIELDS))}"
            )
        key = _MEDIA_CANON.get(name, name)
        if key in keys:
            continue
        keys.add(key)
        out.append((key, _MEDIA_LABELS.get(key, _MEDIA_FIELDS[name])))
    if "name" not in keys:
        out.insert(0, ("name", "Model"))
    if "rank" not in keys:
        out.insert(0, ("rank", "Rank"))
    return out


def _norm_board(name: str) -> str:
    """Board keys are accepted hyphen/space/case-insensitively (``text-to-image``)."""
    return re.sub(r"[\s-]+", "_", str(name).strip().lower())


def _row_open_weights(row: dict) -> bool | None:
    """Open-weights flag for an arena/homepage row (``None`` when unknown).

    Uses the data layer's public normalizer (it understands the several key
    spellings AA ships and never invents a flag); the local fallback keeps the
    tool working if that helper is absent.
    """
    fn = getattr(loaders, "open_weights_flag", None)
    if callable(fn):
        try:
            value = fn(row)
        except Exception:
            value = None
        if isinstance(value, bool):
            return value
    value = row.get("openWeights", row.get("isOpenWeights"))
    if isinstance(value, bool):
        return value
    if row.get("openWeightsUrl"):
        return True
    return None


def _media_cell(row: dict, key: str) -> str:
    if key == "price":
        if row.get("price") is None:
            return "-"
        value = f"${row['price']:,.2f}{row.get('price_unit') or ''}"
        return f"{value}*" if row["price"] == 0 else value
    if key == "rank":
        return _txt(row.get("rank"))
    if key == "appearances":
        value = row.get("appearances")
        return f"{int(value):,}" if value is not None else "-"
    if key == "elo":
        return _elo_int(row.get("elo"))
    if key == "ci_lower":
        return _elo_int(row.get("ci_lower"))
    if key == "ci_upper":
        return _elo_int(row.get("ci_upper"))
    if key == "ci":
        low, high = row.get("ci_lower"), row.get("ci_upper")
        if low is None and high is None:
            return "-"
        return f"{_elo_int(low)}–{_elo_int(high)}"
    if key == "werIndex":
        return render.pct(row.get("werIndex"))
    if key == "stsIndex":
        return render.num(row.get("stsIndex"), 1)
    if key == "speed":
        extra = row.get("extra") or {}
        return render.num(extra.get("medianSpeedFactor"), 1)
    if key == "release_date":
        return _txt(row.get("release_date"))
    return _txt(row.get(key))


_MEDIA_SORT_ALIASES = {
    "elo": "elo", "rank": "rank", "price": "price", "cost": "price",
    "cheapest": "price", "appearances": "appearances", "release": "release_date",
    "released": "release_date", "date": "release_date", "wer": "werIndex",
    "wer%": "werIndex", "sts": "stsIndex", "tps": "speed",
    "tokens_per_second": "speed", "tokenspersecond": "speed", "speed": "speed",
}
#: True = lowest first
_MEDIA_SORT_ASC = {"price": True, "rank": True, "werIndex": True}
_MEDIA_SORT_LABELS = {
    "elo": "Elo", "rank": "rank", "price": "price", "appearances": "appearances",
    "release_date": "release", "werIndex": "WER", "stsIndex": "STS index",
    "speed": "speed",
}


def _media_sort_token(text: Any) -> str:
    return re.sub(r"[\s-]+", "_", str(text).strip().lower())


def _media_sort_value(row: dict, key: str) -> float | str | None:
    value = ((row.get("extra") or {}).get("medianSpeedFactor")
             if key == "speed" else row.get(key))
    if isinstance(value, bool) or value is None:
        return None
    if key == "release_date":
        return str(value)
    return float(value) if isinstance(value, (int, float)) else None


def _media_sort_rows(rows: list[dict], sort: str, allowed: Sequence[str]
                     ) -> tuple[list[dict], str, bool]:
    """Apply ``sort=``; returns ``(rows, key, ascending)``.

    Unknown/absent fields raise with the board's own valid keys, so an agent gets
    a usable sort name inline instead of a reference lookup.
    """
    token = _media_sort_token(sort)
    if not token:
        return rows, "", False
    key = _MEDIA_SORT_ALIASES.get(token, token)
    if key not in allowed:
        nearest = ", ".join(_close(sort, list(allowed), n=3)) or "none"
        raise ValueError(
            f"unknown sort {_q(sort)} — valid: {', '.join(allowed)} "
            f"(closest: {nearest})")
    ascending = _MEDIA_SORT_ASC.get(key, False)
    present = [r for r in rows if _media_sort_value(r, key) is not None]
    absent = [r for r in rows if _media_sort_value(r, key) is None]
    present.sort(key=lambda r: _media_sort_value(r, key), reverse=not ascending)
    return present + absent, key, ascending


def _speech_panel_rows(speech: str, raw_rows: Sequence[dict]) -> list[dict]:
    """Normalize a homepage speech panel to the media row shape."""
    out: list[dict] = []
    for r in raw_rows:
        row = {
            "rank": None, "name": r.get("name"),
            "creator": r.get("creatorName"), "hostName": r.get("hostName"),
            "price": r.get("price"), "price_unit": r.get("price_unit"),
            "release_date": r.get("release_date"),
            "open_weights": _row_open_weights(r), "url": r.get("url"),
            "appearances": r.get("appearances"), "extra": r.get("extra") or {},
        }
        if speech == "sts":
            row.update(elo=r.get("elo"), ci_lower=r.get("ci_lower"),
                       ci_upper=r.get("ci_upper"), stsIndex=r.get("stsIndex"))
        else:
            row["werIndex"] = r.get("werIndex")
        out.append(row)
    return out


def _media(board: str, top: int = 15, fields: str = "", open_weights: bool | None = None,
           category: str = "", sort: str = "", max_price: float | None = None,
           refresh: bool = False) -> str:
    n = top if isinstance(top, int) and top > 0 else 15
    key_name = _norm_board(board)
    key_name = _SPEECH_ALIASES.get(key_name, key_name)
    key_name = _MEDIA_BOARD_ALIASES.get(key_name, key_name)
    category = str(category or "").strip()
    sort = str(sort or "").strip()

    speech = _SPEECH_BOARDS.get(key_name)
    if speech is not None:
        if category:
            raise ValueError(
                f"category= is not available for the {key_name} homepage panel — AA "
                "publishes no category split there; drop category=, or use a media "
                "board that has categories (e.g. text_to_image, "
                "text_to_speech_controlled)"
            )
        raw = _home_rows(refresh).get(speech) or []
        if open_weights is not None:
            flagged = [r for r in raw if _row_open_weights(r) is not None]
            if not flagged:
                return (f"# the {key_name} homepage panel carries no open-weights flag "
                        f"({len(raw)} rows) — drop open_weights, or use a model board "
                        "where the flag exists")
            raw = [r for r in flagged if _row_open_weights(r) == open_weights]
        if not raw:
            return f"# no rows for speech board {key_name} in the homepage payload"
        rows = _speech_panel_rows(speech, raw)
        elo_board = speech == "sts"
        allowed = (["werIndex", "price", "release_date", "speed"]
                   if not elo_board else
                   ["elo", "rank", "price", "appearances", "release_date",
                    "stsIndex"])
        board_note = ("speech, WER lower is better" if not elo_board
                      else "speech arena, STS index and Elo")
        native_default = "werIndex" if not elo_board else "elo"
        cache_name = "home"
    else:
        if key_name not in loaders.MEDIA_BOARDS:
            valid = sorted(loaders.MEDIA_BOARDS) + sorted(_SPEECH_BOARDS)
            nearest = ", ".join(_close(board, valid + list(_MEDIA_BOARD_ALIASES), n=3))
            raise ValueError(
                f"unknown media board {_q(board)} — closest: {nearest or 'none'}\n"
                f"— valid: {', '.join(valid)} (aliases: image, video, t2v, i2v, "
                "tts, stt, speech)"
            )
        try:
            rows = _load(f"media_{key_name}", loaders.media, key_name,
                         refresh=refresh, category=category)
        except ValueError as exc:
            # an unknown category is a bad argument, not a broken payload: drop
            # the loader's cache-file suffix so the error only names the slugs
            msg = str(exc)
            marker = " — the payload cached at "
            if "unknown category" in msg and marker in msg:
                raise ValueError(msg.split(marker, 1)[0]) from None
            raise
        if open_weights is not None:
            rows = [r for r in rows if r.get("open_weights") == open_weights]
        elo_board = True
        allowed = ["elo", "rank", "price", "appearances", "release_date"]
        if any(_media_sort_value(r, "speed") is not None for r in rows):
            allowed.append("speed")
        board_note = ("human-preference Elo · board-relative, not comparable "
                      "across boards")
        native_default = "elo"
        cache_name = f"media_{key_name}"

    if not rows:
        return (f"# no rows on media board {_q(board)}"
                + (f" category={category}" if category else "")
                + f" (open_weights={open_weights}) — drop one filter")

    notes: list[str] = []
    if max_price is not None:
        cap = float(max_price)
        excluded = sum(1 for r in rows
                       if not isinstance(r.get("price"), (int, float))
                       or isinstance(r.get("price"), bool))
        rows = [r for r in rows
                if isinstance(r.get("price"), (int, float))
                and not isinstance(r.get("price"), bool) and r["price"] <= cap]
        if not rows:
            return (f"# no rows on media board {_q(board)} with price <= "
                    f"${cap:,.2f}"
                    + (f" ({excluded} rows publish no price)" if excluded else "")
                    + " — raise max_price or drop it")
        notes.append(f"max_price=${cap:,.2f} (the board's own price unit)"
                     + (f"; {excluded} rows with no published price excluded"
                        if excluded else ""))

    rows, sort_key, ascending = _media_sort_rows(rows, sort, allowed)
    if not sort:
        if not elo_board:
            rows.sort(key=lambda r: (_media_sort_value(r, "werIndex") is None,
                                     _media_sort_value(r, "werIndex") or 0.0))
        elif speech == "sts":
            rows.sort(key=lambda r: (_media_sort_value(r, "elo") is None,
                                     _media_sort_value(r, "elo") or 0.0),
                      reverse=True)
    if not rows:
        return f"# no rows on media board {_q(board)} — drop one filter"

    explicit = bool(fields or open_weights is not None or max_price is not None
                    or (sort_key and sort_key != native_default))
    want_ci = elo_board and n <= 10
    unknown: list[str] = []
    price_view = sort_key == "price" and not fields
    if price_view:
        cols = [("name", "Model"), ("price", "Price")]
    elif fields:
        cols = _media_cols(fields, unknown)
    elif elo_board:
        if speech == "sts":
            cols = [("rank", "Rank"), ("name", "Model"), ("hostName", "Host"),
                    ("stsIndex", "STS"), ("elo", "Elo"), ("price", "Price"),
                    ("release_date", "Release")]
            if want_ci:
                cols.insert(5, ("ci", "95% CI"))
        else:
            cols = [("rank", "Rank"), ("name", "Model"), ("creator", "Creator"),
                    ("elo", "Elo"), ("price", "Price"), ("release_date", "Release")]
            if want_ci:
                cols.insert(4, ("ci", "95% CI"))
    else:
        cols = [("rank", "Rank"), ("name", "Model"), ("creator", "Creator"),
                ("werIndex", "WER%")]
        if sort_key == "price" or max_price is not None:
            cols.append(("price", "Price"))
    if (fields and sort_key == "price"
            and not any(k == "price" for k, _ in cols)):
        cols.append(("price", "Price"))

    shown = rows[:n]
    view_rows: list[dict] = []
    for i, row in enumerate(shown, 1):
        view = dict(row)
        if (sort_key and sort_key != native_default) or view.get("rank") is None:
            view["rank"] = i
        view_rows.append(view)
    table_rows = [[_media_cell(r, k) for k, _ in cols] for r in view_rows]

    price_shown = any(k == "price" for k, _ in cols)
    free = sum(1 for r in rows if r.get("price") == 0) if price_shown else 0
    priced_unknown = (sum(1 for r in rows if r.get("price") is None)
                      if price_shown else 0)
    count = (f"{len(shown)} shown of {len(rows)} matching" if explicit
             else f"{len(shown)} of {len(rows)} {key_name}")
    if price_view:
        count = f"{len(shown)} of {len(rows)} {key_name} · cheapest first"
    if price_shown:
        if free:
            count += f" · {free} at $0.00*"
        if priced_unknown:
            count += f" · {priced_unknown} price -"
    note = "" if price_view else board_note
    if sort_key and not price_view:
        note = (f"sorted by {_MEDIA_SORT_LABELS.get(sort_key, sort_key)} "
                f"({'lowest' if ascending else 'highest'} first) · {note}")
    elif not elo_board and not price_view:
        note = board_note
    if elo_board and not want_ci and not fields and not price_view:
        note += " · fields=ci for the 95% CI"
    if category:
        note = f"category={category} · {note}"
    head = _header(count=count, note=note, name=cache_name)
    body = _table_block(head, [lbl for _, lbl in cols], table_rows,
                        trim=_fields_trim(fields), identity=_identity_labels(cols))
    if free:
        notes.append("* published $0.00 (not unknown)")
    if category:
        notes.append(
            f"category={category}: AA's own per-category sub-board of {key_name} "
            "(not the overall board); omit category= for the primary ranking")
    if unknown:
        notes.append(_unknown_field_note(unknown))
    if notes:
        body += "\n" + render.note(notes)
    return body


# --------------------------------------------------------------------------- #
# aa_agents
# --------------------------------------------------------------------------- #

_AGENT_COLS = [("rank", "Rank"), ("agent", "Agent"), ("model", "Model"),
               ("creator", "Creator"), ("score", "Score"), ("cost_per_task", "$/Task")]
#: short board names an agent types first (the audit: `board=coding` failed)
_AGENT_BOARD_ALIASES = {
    "coding": "coding_agents", "codingagents": "coding_agents",
    "coding_agent": "coding_agents", "agents": "coding_agents",
    "chat": "chatbots", "chatbot": "chatbots", "chatbot_arena": "chatbots",
    "search": "search_api", "searchapi": "search_api", "search_apis": "search_api",
}


def _no_ref(value: Any) -> str:
    """Render a flight ``$…:props:…`` reference as ``-`` instead of leaking it."""
    text = _txt(value)
    return "-" if text.startswith("$") and ":props:" in text else text


def _agents(board: str = "coding_agents", top: int = 5, refresh: bool = False) -> str:
    n = top if isinstance(top, int) and top > 0 else 5
    board_key = _norm_board(board)
    board_key = _AGENT_BOARD_ALIASES.get(board_key, board_key)
    if board_key not in loaders.AGENT_BOARDS:
        nearest = ", ".join(_close(board, sorted(loaders.AGENT_BOARDS)
                                   + list(_AGENT_BOARD_ALIASES), n=3)) or "none"
        raise ValueError(
            f"unknown agents board {_q(board)} — closest: {nearest}\n"
            f"— valid: {', '.join(sorted(loaders.AGENT_BOARDS))} "
            "(aliases: coding, chat, search)"
        )
    rows = _load(f"agents_{board_key}", loaders.agents,
                 board_key, refresh=refresh)
    shown = rows[:n]
    # Each board's score column has its own scale and AA's own column name:
    #   coding_agents — ``indexScore`` 0-1: the AA Coding Agent Index on 0-100;
    #   search_api    — ``aaSearchQualityIndex`` 0-1: a percentage;
    #   chatbots      — ``featuresScore``: AA's absolute Feature Score OUT OF 6
    #                   (Inputs/Media Gen/Tools/Memory/MCP/Connectors, 1 point
    #                   each) — never a fraction (it used to print "580.0%").
    def _coding_score(value: Any) -> str:
        return render.num(value * 100, 1)

    def _feature_score(value: Any) -> str:
        return render.num(value, 2)

    if board_key == "coding_agents":
        score_label, score_text = "Coding Agent Index", _coding_score
    elif board_key == "chatbots":
        score_label, score_text = "Feature Score", _feature_score
    else:
        score_label, score_text = "Score", render.pct

    if board_key == "chatbots":
        # the board's own plan columns: monthly price and tier. Drop the filler
        # Model/Creator columns so the price answer fits one tight table.
        cols = [("rank", "Rank"), ("agent", "Agent"),
                ("score", score_label), ("price_monthly", "$/mo"),
                ("tier", "Tier")]
    else:
        cols = [(key, score_label if key == "score" else label)
                for key, label in _AGENT_COLS]

    def _monthly(row: dict) -> str:
        value = row.get("priceMonthly")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return "-"
        return f"${value:,.2f}/mo" if value else "$0.00/mo*"

    table_rows = []
    for row in shown:
        if board_key == "chatbots":
            table_rows.append([
                _no_ref(row.get("rank")),
                _no_ref(row.get("agent") or row.get("name")),
                score_text(row.get("score")),
                _monthly(row),
                _no_ref(row.get("tier")),
            ])
            continue
        table_rows.append([
            _no_ref(row.get("rank")),
            _no_ref(row.get("agent") or row.get("name")),
            _no_ref(row.get("model")),
            _no_ref(row.get("creator")),
            score_text(row.get("score")),
            _fmt("cost_per_task", row.get("cost_per_task")),
        ])
    if board_key == "coding_agents":
        note = ("Artificial Analysis Coding Agent Index (DeepSWE v1.1 + "
                "Terminal-Bench 4.0 + SWE-Atlas-QnA) · agents, not models")
    elif board_key == "chatbots":
        note = "chatbots · Feature Score out of 6 · agents, not models"
    else:
        note = board_key
    head = _header(count=f"{len(shown)} of {len(rows)} rows", note=note,
                   name=f"agents_{board_key}")
    body = _table_block(head, [lbl for _, lbl in cols], table_rows)
    if board_key == "coding_agents":
        body += ("\n— the Coding Agent Index ranks agent x model combinations (AA's "
                 "harness plus the model it drives); for the model-level coding "
                 "scores that ARE free, see aa_benchmarks query=coding")
    elif board_key == "chatbots":
        body += ("\n— Feature Score is AA's absolute score out of 6 (Inputs, Media "
                 "Gen, Tools, Memory, MCP, Connectors — 1 point each), not a "
                 "percentage; $/mo is the plan's published monthly price, tier is "
                 "AA's plan tier ('-' = not published)")
    return body


# --------------------------------------------------------------------------- #
# aa_search
# --------------------------------------------------------------------------- #

_SEARCH_COLS = [("name", "Model"), ("creator", "Creator"), ("intelligence", "Intel"),
                ("cost_per_task", "$/Task"), ("slug", "Slug")]


# --------------------------------------------------------------------------- #
# arena / media model resolution (Wave E E3)
# --------------------------------------------------------------------------- #
#
# ``aa_media`` lists arena boards, but their entries are not language models, so
# ``aa_search``/``aa_compare`` could not see them (round-5: "no model matches
# 'Grok Voice 3.0' — closest slugs: none"). This index flattens every media
# board plus the three speech panels into one searchable list so a media/speech
# model resolves and compares. Built once per process (one board fetch per
# board; the loader memoises the parsed rows).


@dataclasses.dataclass(frozen=True, slots=True)
class _ArenaEntry:
    name: str
    board: str                 # board key, e.g. "text_to_speech", "tts", "search_api"
    kind: str                  # "media" | "board"
    creator: str | None
    metrics: tuple[tuple[str, str, float | None, str], ...]  # (key, label, value, unit)
    rank: int | None
    appearances: int | None
    price: float | None
    price_unit: str | None
    release_date: str | None
    open_weights: bool | None
    ci_lower: float | None
    ci_upper: float | None


def _arena_board_label(board: str) -> str:
    """The rankable label of an arena board (e.g. ``Speech-to-Speech Arena Elo``)."""
    r = catalog.RANKABLES.get(board)
    return str(getattr(r, "label", board))


_ARENA_MEMO: list[_ArenaEntry] | None = None
_BOARD_MEMO: dict[str, list[Model]] | None = None


def _media_entry(board: str, row: dict) -> _ArenaEntry:
    return _ArenaEntry(
        name=str(row.get("name") or ""), board=board, kind="media",
        creator=(str(row["creator"]) if row.get("creator") else None),
        metrics=(("elo", "Elo", row.get("elo"), "Elo"),),
        rank=row.get("rank"), appearances=row.get("appearances"),
        price=row.get("price"), price_unit=row.get("price_unit"),
        release_date=(str(row["release_date"]) if row.get("release_date") else None),
        open_weights=row.get("open_weights"),
        ci_lower=row.get("ci_lower"), ci_upper=row.get("ci_upper"),
    )


#: board key -> the chart-set slug carrying that board's full row list.  These
#: boards are their own model namespace (a TTS voice / STT host / search API is
#: not a language model), so their rows resolve and compare through the same
#: board path as the media arenas — with every column the board publishes.
_BOARD_CHART_SLUGS: dict[str, str] = {
    "speech_to_text": "stt",
    "speech_to_text_streaming": "stt_streaming",
    "speech_to_speech": "sts",
    "tts": "tts",
    "search_api": "search-api",
}

#: board key -> the column its table leads with (``aa_search``'s row, and the
#: first row of a bare board comparison)
_BOARD_HEADLINE: dict[str, str] = {
    "speech_to_text": "sttWerIndex",
    "speech_to_text_streaming": "sttStreamingWerIndex",
    "speech_to_speech": "sts",
    "tts": "ttsQualityElo",
    "search_api": "searchQualityIndex",
}

#: catalog metric kind -> the unit ``_arena_value_text`` renders it with
_ARENA_UNIT_BY_KIND: dict[str, str] = {
    "pct": "%", "elo": "Elo", "index": "index", "sec": "s", "usd": "usd",
    "int": "int", "tps": "tps",
}


def _arena_unit_for(key: str) -> str:
    """The ``_arena_value_text`` unit for a catalog metric/benchmark key."""
    metric = catalog.metric(key)
    return _ARENA_UNIT_BY_KIND.get(metric.kind if metric is not None else "", "")


def _board_models(refresh: bool = False) -> dict[str, list[Model]]:
    """``{board key: rows}`` for every board we expose as its own namespace.

    Read from the board's chart-set page (``loaders.eval_models``), which carries
    the full row list and every published column — not the homepage's top-N panel.
    A page that cannot be read is skipped so the index keeps working on the rest.
    """
    global _BOARD_MEMO
    if _BOARD_MEMO is not None and not refresh:
        return _BOARD_MEMO
    out: dict[str, list[Model]] = {}
    for board, slug in _BOARD_CHART_SLUGS.items():
        try:
            models = _load(f"eval_{slug}", loaders.eval_models, slug, refresh=refresh)
        except (ValueError, AAFetchError) as exc:
            log.debug("arena index: board %s unavailable (%s)", board, exc)
            continue
        if models:
            out[board] = models
    _BOARD_MEMO = out
    return out


def _board_entry(board: str, model: Model) -> _ArenaEntry:
    """One board row (TTS voice, STT host, search API, …) as an arena-style entry."""
    headline = _BOARD_HEADLINE.get(board, "")
    keys = [k for k in model.evals
            if k != headline and model.evals.get(k) is not None]
    if model.evals.get(headline) is not None:
        keys.insert(0, headline)
    metrics: list[tuple[str, str, float | None, str]] = []
    for key in keys:
        bench = catalog.benchmark(key)
        metric = catalog.metric(key)
        label = (bench.label if bench is not None
                 else metric.label if metric is not None else key)
        metrics.append((key, label, float(model.evals[key]), _arena_unit_for(key)))
    return _ArenaEntry(
        name=str(model.name or model.slug or ""), board=board, kind="board",
        creator=(str(model.creator) if model.creator else None),
        metrics=tuple(metrics), rank=None, appearances=None, price=None,
        price_unit=None,
        release_date=(str(model.release_date) if model.release_date else None),
        open_weights=model.is_open_weights, ci_lower=None, ci_upper=None,
    )


def _board_source(board: str) -> str:
    """Where a board's rows come from, for a footnote (a page path, not ``aa_media``)."""
    slug = _BOARD_CHART_SLUGS.get(board, "")
    pages = loaders.EXTRA_EVAL_PAGES.get(slug, ())
    return pages[0] if pages else f"aa_media board={board}"


def _arena_entries(refresh: bool = False) -> list[_ArenaEntry]:
    """Every media/board entry, memoised (one page fetch per board)."""
    global _ARENA_MEMO
    if _ARENA_MEMO is not None and not refresh:
        return _ARENA_MEMO
    entries: list[_ArenaEntry] = []
    for board in sorted(loaders.MEDIA_BOARDS):
        try:
            rows = _load(f"media_{board}", loaders.media, board, refresh=refresh)
        except (ValueError, AAFetchError) as exc:
            log.debug("arena index: media board %s unavailable (%s)", board, exc)
            continue
        entries += [_media_entry(board, row) for row in rows]
    for board, models in _board_models(refresh).items():
        entries += [_board_entry(board, m) for m in models]
    _ARENA_MEMO = entries
    return entries


def _arena_norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def _arena_tokens(text: str) -> list[str]:
    """Lowercased alphanumeric tokens (same split as ``select._tokens``)."""
    return [t for t in re.split(r"[^a-z0-9]+", str(text).lower()) if t]


def _arena_fields(entry: _ArenaEntry) -> list[str]:
    """Normalized searchable fields — the arena analogue of ``select._fields``.

    Arena entries have no slug, so the name and the creator/host stand in for the
    language-model path's slug/name/short_name/creator.
    """
    return [_arena_norm(entry.name), _arena_norm(entry.creator or "")]


def _arena_token_hits(entry: _ArenaEntry, tokens: Sequence[str]) -> int:
    """How many query ``tokens`` appear (as substrings) in the entry's fields."""
    fields = _arena_fields(entry)
    return sum(1 for t in tokens
               if any(t == f or f.startswith(t) or t in f for f in fields if f))


def _arena_score(entry: _ArenaEntry, query: str, tokens: Sequence[str]) -> int:
    """Match score: ``>= _ARENA_FULL`` is an exact/AND match, ``1..`` a partial.

    Mirrors ``select.search``: the whole query as the name (100) or a substring
    of it (90), else **every** token must appear (70) — anything less is a partial
    match, scored by how many tokens hit.
    """
    qn = _arena_norm(query)
    name = _arena_norm(entry.name)
    if not qn or not name or not tokens:
        return 0
    if qn == name:
        return 100
    if qn in name:
        return 90
    hits = _arena_token_hits(entry, tokens)
    if hits == len(tokens):
        return _ARENA_FULL
    return hits


#: score at/above which a match used *every* query token (exact / AND match)
_ARENA_FULL = 70


def _arena_matches(query: str, entries: Sequence[_ArenaEntry], limit: int) -> tuple[
        list[_ArenaEntry], bool, int]:
    """``(matches, partial, best_token_hits)`` for a tokenised AND search.

    Full (all-token) matches win; partial matches are returned only when no entry
    matches every token, and only at the best token-hit tier (so the heading's
    ``n/m tokens`` is true of every row). ``partial`` says which it is — the caller
    labels them apart so exact and fuzzy results are never mixed under one heading.
    """
    tokens = _arena_tokens(query)
    if not tokens:
        return [], False, 0
    scored = [(s, e) for e in entries if (s := _arena_score(e, query, tokens))]
    if not scored:
        return [], False, 0
    full = [(s, e) for s, e in scored if s >= _ARENA_FULL]
    if full:
        pool, partial = full, False
    else:
        best_hits = max(_arena_token_hits(e, tokens) for _s, e in scored)
        if len(tokens) > 1 and best_hits < 2:
            return [], False, 0      # one stray token is not a useful match
        pool = [(s, e) for s, e in scored
                if _arena_token_hits(e, tokens) == best_hits]
        partial = True
    pool.sort(key=lambda t: (-t[0], t[1].board, t[1].name))
    best = max(_arena_token_hits(e, tokens) for _s, e in pool)
    return [e for _s, e in pool[:limit]], partial, best


def _arena_value_text(metric: tuple[str, str, float | None, str]) -> str:
    _key, _label, value, unit = metric
    if value is None:
        return "-"
    if unit == "%":
        return render.pct(value)
    if unit == "Elo":
        return _elo_int(value)
    if unit == "index":
        return render.num(value, 1)
    if unit == "s":
        return render.num(value, 2) + "s"
    if unit == "usd":
        return render.usd(value)
    if unit == "int":
        return f"{round(float(value)):,}"
    return render.num(value, 2)


def _arena_candidates(query: str, board: str | None = None) -> tuple[
        list[_ArenaEntry], bool]:
    """``(candidates, partial)`` for one name — the AND rule, partial as fallback.

    With ``board`` the search is pinned to that board. Without it, a name that
    exists on several boards (e.g. "Eleven v4 Turbo" is on both voice boards)
    returns one candidate per board, so the caller can pick a board shared with
    the other models being compared. ``partial`` is True only when no entry
    matched every query token.
    """
    entries = _arena_entries()
    pool = [e for e in entries if e.board == board] if board is not None else entries
    matches, partial, _hits = _arena_matches(query, pool, limit=len(pool) or 1)
    if not matches:
        return [], False
    return matches, partial


def _arena_pick_board(groups: Sequence[Sequence[_ArenaEntry]],
                      prefer_keys: Sequence[str] = ()) -> tuple[
        list[_ArenaEntry], str, list[str]]:
    """Pick the board every compared name shares; ``(picks, board, other_boards)``.

    ``groups`` holds each name's candidate entries. The chosen board is the one
    that publishes every ``prefer_keys`` column when a single board qualifies
    (a name can sit on several boards — a TTS voice is on the voice arenas *and*
    the TTS models board, and only the latter carries ``ttsQualityElo``); else it
    is the alphabetically first board common to all names, so a comparison is
    never silently spread across two boards. When a name exists on more boards the
    extra ones are returned so the reply can say a board was chosen.
    """
    sets = [{e.board for e in g} for g in groups]
    common = set.intersection(*sets) if sets else set()
    if not common:
        detail = " | ".join(
            ", ".join(sorted({e.board for e in g})) for g in groups)
        raise ValueError(
            "these arena names are not published on one board: "
            f"{detail}\n— pass a board key as a queries entry (or prefix a name "
            "with \"<board>: \") to compare entries from one board"
        )

    def _carries(board: str) -> bool:
        picks = [next(e for e in g if e.board == board) for g in groups]
        return all(any(mk == key and mv is not None
                       for mk, _l, mv, _u in e.metrics)
                   for e in picks for key in prefer_keys)

    ordered = sorted(common)
    if prefer_keys:
        scored = [b for b in ordered if _carries(b)]
        if scored:
            ordered = scored + [b for b in ordered if b not in scored]
    chosen = ordered[0]
    picks = [next(e for e in g if e.board == chosen) for g in groups]
    return picks, chosen, sorted(common - {chosen})


def _arena_search_rows(query: str, top: int, creator: str = "",
                       open_weights: bool | None = None,
                       refresh: bool = False) -> tuple[list[_ArenaEntry], bool, int]:
    """``(rows, partial, best_token_hits)`` for the arena part of ``aa_search``."""
    entries = _arena_entries(refresh)
    if open_weights is not None:
        entries = [e for e in entries if e.open_weights == open_weights]
    if creator:
        cn = _norm_alias(creator)
        entries = [e for e in entries if e.creator and cn in _norm_alias(e.creator)]
    return _arena_matches(query, entries, top)


def _arena_search_table(entries: Sequence[_ArenaEntry]) -> str:
    headers = ["Model", "Board", "Metric", "Value", "Creator"]
    rows = [[e.name, f"{e.board} ({'board' if e.kind == 'board' else 'arena'})",
             e.metrics[0][1], _arena_value_text(e.metrics[0]), e.creator or "-"]
            for e in entries]
    return render.table(headers, rows)


def _arena_board_key(name: str) -> str | None:
    """The media/speech board key a bare ``name`` names (``text-to-speech`` → …).

    Used so an ambiguous arena name can be pinned to one board, either as a
    standalone ``queries`` entry (``["text_to_speech", "Eleven v4 Turbo", …]``)
    or as a ``board: name`` prefix.
    """
    key = _norm_board(name)
    key = _SPEECH_ALIASES.get(key, key)
    if (key in loaders.MEDIA_BOARDS or key in _SPEECH_BOARDS
            or key in _BOARD_CHART_SLUGS):
        return key
    return None


def _arena_split_board(name: str) -> tuple[str | None, str]:
    """Split a ``"<board>: <model>"`` query into ``(board, model)``."""
    head, sep, tail = str(name).partition(":")
    if sep:
        board = _arena_board_key(head.strip())
        if board is not None and tail.strip():
            return board, tail.strip()
    return None, str(name).strip()


#: rankable kind -> the noun ``aa_search`` uses when the query names a thing
_RANKABLE_NOUN = {
    "benchmark": "benchmark", "index": "composite index", "derived": "metric",
    "arena": "arena board", "view": "comparison view",
}


def _rankable_hint_coverage(r: Any, models: Sequence[Model]) -> str:
    """A short, cheap coverage note for the rankable named by a search query."""
    kind = str(getattr(r, "kind", ""))
    if kind == "view":
        return ""
    if kind == "arena":
        return "arena board"
    key = str(getattr(r, "key", ""))
    native = sum(1 for m in models if _rankable_value(m, key) is not None)
    if native:
        return f"{native}/{len(models)} scored"
    surface = str(getattr(r, "surface", "") or "")
    return {"chart": "chart-set only", "rich": "rich/model-page data",
            "none": "not published free (paid data API only)"}.get(surface, "")


def _task_domain_hint(query: str) -> str:
    """A task word AA does not measure, answered with its closest measures (G8)."""
    fn = getattr(catalog, "task_domain", None)
    if not callable(fn):
        return ""
    hit = fn(query)
    if hit is None:
        return ""
    task, note = hit
    return (f"# no model matches {_q(query)} — {task} is a task, not an AA benchmark\n"
            f"— {note}\n"
            "— aa_benchmarks lists what AA does measure; aa_leaderboard "
            "sort=<key> ranks it")


def _rankable_search_hint(query: str, models: Sequence[Model]) -> str:
    """One/two-line answer when ``query`` names a rankable thing, not a model.

    ``aa_search`` is a name -> slug resolver, but a query like ``gpqa`` names a
    benchmark with no model slug; point at its ``How to query`` call instead of
    dead-ending on "no models match". A *task* word AA publishes no benchmark for
    ("best model for classification") is answered with its closest measures (G8).
    """
    if not query:
        return ""
    domain = _query_domain(query)
    if domain:
        rows = _rankable_list(domain=domain)
        if rows:
            return (f"# {_q(query)} is a task domain, not a model — {len(rows)} "
                    f"rankable things cover it\n— aa_benchmarks domain={domain} "
                    "lists them (benchmarks, indexes, metrics and arenas)")
    rows = _rankable_list(query=query)
    if not rows:
        return _task_domain_hint(query)
    r = rows[0]
    kind = _RANKABLE_NOUN.get(str(getattr(r, "kind", "")), "thing")
    label = str(getattr(r, "label", "") or getattr(r, "key", ""))
    coverage = _rankable_hint_coverage(r, models)
    detail = f"{label}, {coverage}" if coverage else label
    return (f"# {_q(query)} names a {kind}, not a model — there is no slug to "
            f"resolve\n— {getattr(r, 'how', '')!s} ({detail}); aa_benchmarks "
            f"query={_q(query)} lists related things")


def _search(query: str = "", creator: str = "", open_weights: bool | None = None,
            top: int = 15, refresh: bool = False) -> str:
    n = top if isinstance(top, int) and top > 0 else 15
    models = _models(refresh)
    if query:
        found = select.search(models, query, limit=max(n, 20))
    else:
        found = select.sort_models(models, "intelligence")
    found = select.filter_models(
        found, creator=creator or None, open_weights=open_weights,
        # The default listing is the active field; a *name* query may resolve a
        # deprecated model, which the Status column labels.  Resolution already
        # used the merged pool, so this filter is presentation only (audit D3).
        exclude_deprecated=not query,
    )
    shown = found[:n]
    arena, arena_partial, arena_hits = (
        _arena_search_rows(query, n, creator, open_weights, refresh)
        if query else ([], False, 0))
    parts: list[str] = []
    if shown:
        show_status = any(m.deprecated for m in shown)
        cols = _cols(_SEARCH_COLS, "")
        if show_status:
            cols += [("status", "Status")]
        rows = []
        for m in shown:
            row = [_fmt(k, select.lookup(m, k)) for k, _ in _SEARCH_COLS]
            if show_status:
                row.append("deprecated" if m.deprecated else "active")
            rows.append(row)
        cache_name = _lb_cache()
        matched = len(found)
        explicit = bool(query or creator or open_weights is not None)
        active = sum(1 for m in models if not m.deprecated)
        tracked = (f"{active} active of {len(models)} tracked"
                   if active < len(models) else f"{len(models)} tracked")
        if explicit:
            count = f"{len(rows)} shown of {matched} matching ({tracked})"
        else:
            count = f"{len(rows)} of {matched} models"
        note = (f"name match {render.clean(query, None)}" if query
                else "most intelligent")
        head = _header(count=count, note=note, name=cache_name,
                       source_label=_source_key())
        parts.append(_table_block(head, [lbl for _, lbl in cols], rows))
        if query:
            name_notes = _name_notes(query, shown[0], models)
            if name_notes:
                parts.append(render.note(name_notes))
        if arena and arena_partial:
            # the language-model answer is already an exact/AND match — hint at
            # the fuzzy arena rows in one line instead of a table of near-misses
            tokens = len(_arena_tokens(query))
            parts.append(render.note([
                f"{len(arena)} partial arena matches ({arena_hits}/{tokens} tokens) "
                f"for this query; aa_media board=<key> lists a board "
                f"(e.g. {arena[0].board})"]))
        elif arena:
            parts.append(_arena_section(query, arena, arena_partial, arena_hits))
        return "\n".join(parts)

    # no language-model match: a full arena match still answers the name …
    if arena and not arena_partial:
        return "\n".join(parts + [_arena_section(query, arena, False, arena_hits)])
    # … else a rankable name (gpqa, "terminal-bench 4.0") beats fuzzy arena rows
    hint = _rankable_search_hint(query, models)
    if hint:
        return hint
    if arena:
        return "\n".join(parts + [_arena_section(query, arena, arena_partial, arena_hits)])
    return (f"# no models match {_q(query)}"
            + (f" (creator~{render.clean(creator, None)})" if creator else "")
            + " — try a shorter substring or aa_reference topic=fields; "
            "media/speech models live on arena boards (aa_media), and TTS voices / "
            "STT hosts / search APIs on their own boards (aa_benchmarks)")


def _arena_section(query: str, arena: Sequence[_ArenaEntry], partial: bool,
                   hits: int) -> str:
    """The arena/board table block (heading + rows + notes) for ``aa_search``."""
    kinds = {e.kind for e in arena}
    only_board = kinds == {"board"}
    has_board = "board" in kinds
    plural = "" if len(arena) == 1 else "es"
    noun = ("board" if only_board
            else "board/arena" if has_board else "arena-board")
    if partial:
        label = (f"partial {noun} match{plural} "
                 f"({hits}/{len(_arena_tokens(query))} tokens)")
    else:
        label = f"{noun} match{plural}"
    head = (f"# {len(arena)} {label} · "
            f"name match {render.clean(query, None)} · "
            f"aa:{'board' if only_board else 'arena'}")
    if only_board:
        notes = [
            "board rows are their own namespace (a TTS voice / STT host / search "
            "API is not a language model) — aa_compare compares them on the board's "
            "own columns, aa_benchmark_leaderboard ranks a whole board"]
    elif has_board:
        notes = [
            "these rows are arena entries and board rows (TTS voices / STT hosts / "
            "search APIs), not language models — aa_compare compares rows from one "
            "board; aa_media board=<key> lists a whole arena"]
    else:
        notes = ["arena entries are media/speech models, not language models — "
                 "aa_media board=<key> lists a whole board; aa_compare can compare them"]
    if partial:
        notes.insert(0, "partial: not every query token appears in these names "
                        "— treat them as fuzzy suggestions, not an exact match")
    return head + "\n" + _arena_search_table(arena) + "\n" + render.note(notes)


# --------------------------------------------------------------------------- #
# aa_reference
# --------------------------------------------------------------------------- #


def _reference(topic: str = "overview") -> str:
    name = (topic or "overview").strip().lower()
    if name == "all":
        body = "\n\n".join(f"## {key}\n\n{text}"
                           for key, text in reference.TOPICS.items())
        text = reference.PREAMBLE + "\n\n" + body
    elif name in reference.TOPICS:
        text = reference.TOPICS[name]
    else:
        raise ValueError(
            f"unknown topic {_q(topic)} — topics: {', '.join(reference.TOPICS)}, all"
        )
    if name in ("indexes", "all"):
        text += ("\n\n— note: AA publishes its Coding and Agentic indexes only through "
                 "its paid data API, so no free page carries a per-model value for "
                 "them; the six Capability Indexes (aa_leaderboard "
                 "sort=capabilities.legal), the Openness Index and the Decision Index "
                 "are free, and the Coding *Agent* Index is on aa_agents "
                 "board=coding_agents.")
    return text


# --------------------------------------------------------------------------- #
# aa_raw
# --------------------------------------------------------------------------- #

_RAW_KINDS = ("model", "leaderboard", "providers", "providers_board", "media",
              "agents", "home", "eval", "catalog")


def _to_plain(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _to_plain(getattr(value, f.name))
                for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {k: _to_plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_plain(v) for v in value]
    if isinstance(value, str) and len(value) > MAX_RAW_STR:
        return f"{value[:MAX_RAW_STR]}… (truncated {len(value) - MAX_RAW_STR} chars)"
    return value


def _project(obj: Any, keys: Sequence[str]) -> Any:
    if not keys or not isinstance(obj, dict):
        return obj
    return {k: v for k, v in obj.items() if k in keys}


def _provider_board_matches(rows: Sequence[Any], query: str) -> list[Any]:
    """Rows of the provider board whose model name/slug matches every query token."""
    tokens = [t for t in re.split(r"[^a-z0-9]+", query.lower()) if t]
    if not tokens:
        return list(rows)
    out = []
    for row in rows:
        hay = _norm_alias(f"{getattr(row, 'model_slug', '')} "
                          f"{getattr(row, 'model_name', '')}")
        if all(t in hay for t in tokens):
            out.append(row)
    return out


_RAW_UNITS = {
    "model": "price_* = $/1M tokens · cost_per_task = $ · scores = fraction 0..1 "
             "or Elo · tps = tok/s · ttft = s",
    "leaderboard": "price_* = $/1M tokens · cost_per_task = $ · scores = fraction "
                   "0..1 or Elo · tps = tok/s · ttft = s",
    "providers": "price_* = $/1M tokens · cost_per_task = $ · tps = tok/s · "
                 "ttft = s",
    "providers_board": "price_* = $/1M tokens · cost_per_task = $ · tps = tok/s · "
                       "ttft = s",
    "media": "price = the row's own price_unit (per image/min/1M chars) · score "
             "= Elo or index as labeled",
    "agents": "score = the board's own scale · cost_per_task = $ · priceMonthly "
              "= the plan's $/month",
    "home": "price = the panel's own price_unit · score = percentage/index/Elo "
            "as labeled",
    "eval": "scores = fraction 0..1 or Elo as labeled",
    "catalog": "no numeric values — catalog metadata only",
}


def _raw(kind: str, query: str = "", fields: str = "", top: int = 1,
         refresh: bool = False) -> str:
    if kind not in _RAW_KINDS:
        raise ValueError(f"unknown kind {_q(kind)} — valid: {', '.join(_RAW_KINDS)}")
    if kind in ("model", "providers") and not str(query).strip():
        raise ValueError(
            f"kind={kind} needs a model — pass query=<name or slug> "
            "(aa_search resolves a name to a slug)"
        )
    requested = top if isinstance(top, int) else 1
    # The raw leaderboard is useful for scripted spot-checks, so it accepts a
    # wider slice than the other kinds; either way the header states the cap and
    # the requested count instead of silently returning fewer rows.
    cap = 25 if kind == "leaderboard" else 5
    n = min(max(requested, 1), cap)
    cap_note = f" (cap {cap}; {requested} requested)" if requested > cap else ""
    head = ""
    keys = _split(fields)
    cache_name = ""
    payload: Any

    if kind == "model":
        base = _resolve_slug(query, _models(refresh))
        record = _load(f"model_{base.slug}",
                       loaders.model, base.slug, refresh=refresh).get(base.slug)
        payload = _to_plain(record if record is not None else base)
        cache_name = f"model_{base.slug}"
    elif kind == "leaderboard":
        cache_name = _lb_cache()
        rows = _lb_rows(refresh)
        payload = [_project(_to_plain(m), keys) for m in rows[:n]]
        head = _header(
            count=f"raw leaderboard · top {len(payload)} of {len(rows)}{cap_note}",
            note="JSON, token-expensive — prefer the table tools", name=cache_name)
    elif kind == "providers":
        base = _resolve_slug(query, _models(refresh))
        cache_name = f"providers_{base.slug}"
        payload = [_project(_to_plain(e), keys)
                   for e in _load(f"providers_{base.slug}",
                                  loaders.provider_endpoints, base.slug,
                                  refresh=refresh)[:n]]
    elif kind == "providers_board":
        cache_name = "providers_board"
        rows = list(_load("providers_board", loaders.provider_board,
                          refresh=refresh))
        matched = rows
        label = ""
        if str(query).strip():
            matched = _provider_board_matches(rows, str(query))
            if not matched:
                known = sorted({e.model_slug for e in rows if e.model_slug})
                hint = ", ".join(known[:5]) or "none"
                raise ValueError(
                    f"no provider-board row matches {_q(query)} — the board nests "
                    "the variant slug under release; known examples: " + hint +
                    "\n— resolve the model name with aa_search first")
            label = f" · {render.clean(query, None)}"
        cap = 25
        n = min(max(top if isinstance(top, int) else 1, 1), cap)
        if top > cap:
            cap_note = f" (cap {cap}; {top} requested)"
        payload = [_project(_to_plain(e), keys) for e in matched[:n]]
        head = (f"# raw providers_board{label} · top {len(payload)} of "
                f"{len(matched)} matching{cap_note}")
    elif kind == "media":
        board = _norm_board(query or "text_to_image")
        if board not in loaders.MEDIA_BOARDS:
            raise ValueError(f"unknown media board {_q(query)} — "
                             f"valid: {', '.join(sorted(loaders.MEDIA_BOARDS))}")
        cache_name = f"media_{board}"
        payload = [_project(r, keys)
                   for r in _load(f"media_{board}", loaders.media,
                                  board, refresh=refresh)[:n]]
    elif kind == "agents":
        board = _norm_board(query or "coding_agents")
        cache_name = f"agents_{board}"
        payload = [_project(r, keys)
                   for r in _load(f"agents_{board}", loaders.agents,
                                  board, refresh=refresh)[:n]]
    elif kind == "home":
        cache_name = "home"
        home = _home_rows(refresh)
        payload = {k: [_project(r, keys) for r in v[:n]] for k, v in home.items()}
    elif kind == "eval":
        slug = _eval_slug(query)
        cache_name = f"eval_{slug}"
        payload = [_project(_to_plain(m), keys)
                   for m in _load(f"eval_{slug}", loaders.eval_models,
                                  slug, refresh=refresh)[:n]]
    else:  # catalog
        cache_name = "eval_catalog"
        payload = [_project(c, keys)
                   for c in _load("eval_catalog", loaders.eval_catalog,
                                  refresh=refresh)]

    if not head:
        head = _header(count=f"raw {kind} · top {n}{cap_note}",
                       note="JSON, token-expensive — prefer the table tools",
                       name=cache_name)
    elif cache_name:
        head += f"\n- cache: `{cache_name}`"
    head += f"\n- units: {_RAW_UNITS.get(kind, 'as labeled')}"
    return _fit_json(head, payload)


def _eval_slug(query: str) -> str:
    """Validate an evaluation slug (``aa_raw kind=eval``).

    A slug reaches ``/evaluations/<slug>`` and the cache file name, so it must
    be one safe path segment: letters/digits/``.``/``-``/``_``, no ``/``, no
    ``..`` (adversarial A42/A43; the cache name is re-validated by ``fetch``).
    When the eval catalog is available the slug must also be one of its entries,
    so a *model* slug (e.g. ``claude-opus-5-5``) is rejected with the expected
    shape instead of being fetched and 404ing (B9).
    """
    slug = (query or "gpqa-diamond").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}", slug) or ".." in slug:
        raise ValueError(
            f"kind=eval expects an evaluation slug (e.g. gpqa-diamond), got {_q(query)} "
            "— see aa_benchmarks for the eval slugs"
        )
    try:
        catalog_rows = loaders.eval_catalog()
        known = sorted({str(row["slug"]) for row in catalog_rows
                        if isinstance(row, dict) and row.get("slug")})
    except Exception:
        known = []
    if known and slug not in known:
        near = ", ".join(_close(slug, known)) or "none"
        raise ValueError(
            f"kind=eval expects an evaluation slug (e.g. gpqa-diamond), got "
            f"{_q(query)} — closest evaluations: {near}\n"
            "— aa_benchmarks lists every eval slug"
        )
    return slug


def _fit_json(head: str, payload: Any) -> str:
    """Serialize ``payload`` as pretty JSON, bounded to :data:`MAX_RESPONSE`."""
    body = json.dumps(payload, indent=1, default=str)
    text = f"{head}\n{body}"
    if len(text) <= MAX_RESPONSE:
        return text
    if isinstance(payload, list):
        records = list(payload)
        while records:
            records.pop()
            body = json.dumps(records, indent=1, default=str)
            text = (f"{head}\n{body}\n— response capped at {MAX_RESPONSE // 1000} kB: "
                    f"showing {len(records)} of {len(payload)} records "
                    "(narrow `fields`/`top`)")
            if len(text) <= MAX_RESPONSE:
                return text
    return (f"{head}\n— response capped at {MAX_RESPONSE // 1000} kB: this payload "
            "does not fit; narrow `fields`, `top` or the requested board")


# --------------------------------------------------------------------------- #
# app
# --------------------------------------------------------------------------- #

srv = MCPServer(
    name="aa-mcp",
    version=__version__,
    instructions=(
        "Live Artificial Analysis benchmark data (artificialanalysis.ai): model "
        "intelligence/price/speed/context leaderboards, per-model digests, "
        "benchmark rankings, provider endpoints, media and agent arenas. Resolve "
        "uncertain names with aa_search first, then use aa_leaderboard / aa_model / "
        "aa_compare. All output is token-efficient markdown; unknown names return "
        "actionable candidates."
    ),
)


@srv.tool(name="aa_leaderboard", title="Model leaderboard", structured_output=False)
@_tool
def aa_leaderboard(
    mode: str = "rank",
    sort: str = "intelligence",
    fields: str | list[str] = "",
    top: int = 10,
    creator: str = "",
    name: str = "",
    open_weights: bool | None = None,
    reasoning: bool | None = None,
    min_intelligence: float | None = None,
    max_cost_per_task: float | None = None,
    max_price_in: float | None = None,
    max_price_out: float | None = None,
    vision: bool | None = None,
    min_speed: float | None = None,
    max_ttft: float | None = None,
    min_context: int | None = None,
    released_after: str = "",
    include_deprecated: bool = False,
    refresh: bool = False,
) -> str:
    """Rank/filter the tracked model variants — the default starting point.

    The tool for "smartest / cheapest / fastest / best value right now".
    mode=rank | value (intelligence per $/task) | frontier (Pareto curve with its
    knee, same as aa_pareto). sort=<metric alias or benchmark key>; fields=<comma
    list> for exact columns; max_price_in/max_price_out cap $/1M input/output
    tokens. refresh=true bypasses the cache. Resolve uncertain names with
    aa_search first. The header labels coverage and ties.
    """
    return _leaderboard(
        mode=mode, sort=sort, fields=fields, top=top, creator=creator, name=name,
        open_weights=open_weights, reasoning=reasoning,
        min_intelligence=min_intelligence, max_cost_per_task=max_cost_per_task,
        max_price_in=max_price_in, max_price_out=max_price_out, vision=vision,
        min_speed=min_speed, max_ttft=max_ttft, min_context=min_context,
        released_after=released_after, include_deprecated=include_deprecated,
        refresh=refresh,
    )


@srv.tool(name="aa_model", title="Model digest", structured_output=False)
@_tool
def aa_model(query: str, sections: str | list[str] = "", refresh: bool = False) -> str:
    """One model's full digest: specs, indices, benchmarks, pricing and speed.

    Use after aa_leaderboard/aa_search for everything about one model. query= name
    or slug (fuzzy; ambiguous names return candidates). sections= comma list or
    all of identity | indexes | benchmarks | pricing | speed | cost | openness |
    modalities (alias specs=identity). refresh=true bypasses the cache.
    """
    return _model(query, sections=sections, refresh=refresh)


@srv.tool(name="aa_pareto", title="Pareto trade-off frontier",
          structured_output=False)
@_tool
def aa_pareto(score: str = "intelligence", x: str = "cost_per_task", top: int = 15,
              creator: str = "", open_weights: bool | None = None,
              min_intelligence: float | None = None, min_context: int | None = None,
              include_deprecated: bool = False, include_all: bool = False,
              refresh: bool = False) -> str:
    """Pareto frontier: any score vs any cost/size/speed axis, with the knee.

    Non-dominated models ordered by x ascending, plus the knee and coverage.
    score= any rankable with per-model numbers (default intelligence), e.g.
    cyberIndex, terminalBench40. x= cost_per_task (default) | index_total_cost |
    out_tokens_per_task | time_per_task | context_tokens | params_b | ttft |
    price_in | price_out. include_all=true returns every point. refresh=true
    bypasses the cache.
    """
    return _pareto(
        score=score, x=x, top=top, creator=creator, open_weights=open_weights,
        min_intelligence=min_intelligence, min_context=min_context,
        include_deprecated=include_deprecated, include_all=include_all,
        refresh=refresh,
    )


@srv.tool(name="aa_compare", title="Compare models", structured_output=False)
@_tool
def aa_compare(queries: list[str] = [],  # noqa: B006 - the MCP schema wants a list default
               metrics: str | list[str] = "",
               view: str = "table", compact: bool = True, spec: str = "",
               refresh: bool = False) -> str:
    """Side-by-side comparison of 2-12 models on any benchmark (site parity).

    queries= 2-12 model names or slugs (or arena entries on one board).
    metrics=all (every published row plus derived score/$ ratios) | benchmarks | a
    comma list of keys/aliases; empty uses the default rows. view=table (models as
    columns) or diff (per-metric delta vs the first model). Cells from a chart set /
    homepage panel are joined and footnoted, and any ``-`` cell is footnoted, so no
    gap is silent. refresh=true bypasses the cache.
    """
    return _compare(queries, metrics=metrics, view=view, compact=compact,
                    spec=spec, refresh=refresh)


@srv.tool(name="aa_benchmarks", title="Benchmark & metric search index",
          structured_output=False)
@_tool
def aa_benchmarks(query: str = "", domain: str = "", tag: str = "",
                  verbose: bool = False) -> str:
    """Search everything rankable: benchmarks, indexes, derived metrics, arenas.

    Each hit carries the exact tool call that ranks it. query= tokenised AND-match
    over key/label/aliases/description/tags; domain= one domain name (coding,
    security, agentic, legal, speech, media, finance, ...); tag= one raw tag
    (narrower); verbose=true also shows what each thing measures. A task AA
    publishes no benchmark for answers with the closest AA measures instead of
    dead-ending.
    """
    return _benchmarks(query=query, domain=domain, tag=tag, verbose=verbose)


@srv.tool(name="aa_benchmark_leaderboard", title="Benchmark leaderboard",
          structured_output=False)
@_tool
def aa_benchmark_leaderboard(
    benchmark: str,
    top: int = 15,
    fields: str | list[str] = "",
    creator: str = "",
    open_weights: bool | None = None,
    min_intelligence: float | None = None,
    include_estimates: bool = True,
    include_deprecated: bool = True,
    refresh: bool = False,
) -> str:
    """Rank models on one benchmark, stating the source and coverage honestly.

    benchmark= key, label or eval slug (e.g. gpqa, gpqa-diamond, briefcaseElo).
    Picks the richest source (full leaderboard → AA's curated eval chart set →
    homepage panel); the header says which and warns when it is not a full
    leaderboard (chart sets cover ~5-32 models). fields=<comma list> for exact
    columns; include_estimates=false drops AA-estimated (``*``) scores;
    include_deprecated=false hides deprecated rows (the default keeps them and
    adds a Depr column + header note); refresh=true bypasses the cache.
    """
    return _benchmark_leaderboard(
        benchmark, top=top, fields=fields, creator=creator,
        open_weights=open_weights, min_intelligence=min_intelligence,
        include_estimates=include_estimates,
        include_deprecated=include_deprecated, refresh=refresh,
    )


@srv.tool(name="aa_providers", title="Provider endpoints", structured_output=False)
@_tool
def aa_providers(model: str = "", host: str = "", top: int = 15,
                 sort: str = "cost_per_task", fields: str | list[str] = "",
                 open_weights: bool | None = None, min_context: int | None = None,
                 refresh: bool = False) -> str:
    """Provider endpoints: per-host pricing, precision, speed and feature flags.

    model= one model's serving endpoints (per-endpoint $/task and precision); host=
    substring on the serving host; neither returns the cheapest endpoints globally.
    sort= cost_per_task (default) | price_in | price_out | tps | ttft |
    intelligence | context_tokens; fields=<comma list> for exact columns
    (precision, cache_read, e2e, function_calling, ...); refresh=true bypasses the
    cache. A model AA lists no endpoints for is explained rather than errored.
    """
    return _providers(model=model, host=host, top=top, sort=sort, fields=fields,
                      open_weights=open_weights, min_context=min_context,
                      refresh=refresh)


@srv.tool(name="aa_media", title="Media leaderboards", structured_output=False)
@_tool
def aa_media(board: str, top: int = 15, fields: str | list[str] = "",
             open_weights: bool | None = None, category: str = "",
             sort: str = "", max_price: float | None = None,
             refresh: bool = False) -> str:
    """Human-preference arenas: image, video, speech, music (Elo + 95% CI).

    board= text_to_image | image_editing | text_to_video | image_to_video |
    video_editing | text_to_speech[_controlled] | music_instrumental |
    music_with_vocals | speech_to_text[_streaming] | speech_to_speech (aliases:
    image, video, t2v, i2v, tts, stt, speech, realtime_voice). category= ranks a
    sub-board. sort= elo | price | appearances | release | rank (+ wer/sts on
    speech). max_price= caps the board's price unit; `$0.00` is published zero,
    `-` unknown. Elo is board-relative. fields= selects columns; fields=all
    renders every catalogued column. A board entry is not a language model.
    """
    return _media(board, top=top, fields=fields, open_weights=open_weights,
                  category=category, sort=sort, max_price=max_price,
                  refresh=refresh)


@srv.tool(name="aa_agents", title="Agent leaderboards", structured_output=False)
@_tool
def aa_agents(board: str = "coding_agents", top: int = 5, refresh: bool = False) -> str:
    """AA agent leaderboards: coding agents, chatbots and search APIs.

    board= coding_agents (default) | chatbots | search_api (aliases: coding,
    chat, search); top= rows (default 5). Chatbot rows render the plan's monthly
    price and tier. An agent row is not a language model, so it carries no
    Intelligence cost or speed.
    """
    return _agents(board=board, top=top, refresh=refresh)


@srv.tool(name="aa_search", title="Find a model slug", structured_output=False)
@_tool
def aa_search(query: str = "", creator: str = "", open_weights: bool | None = None,
              top: int = 15, refresh: bool = False) -> str:
    """Cheap name -> slug resolver; call this first whenever a name is uncertain.

    Always returns the slug so the next tool call can be exact, and announces a
    fuzzy match and the reasoning-effort variant. query= fuzzy model name or
    partial slug; creator=, open_weights= filters; refresh=true bypasses the cache.
    Media/speech arena models are searched too, with their board.
    """
    return _search(query=query, creator=creator, open_weights=open_weights,
                   top=top, refresh=refresh)


@srv.tool(name="aa_reference", title="Reference & provenance", structured_output=False)
@_tool
def aa_reference(topic: str = "overview") -> str:
    """Static reference text: tool routing, metric/eval definitions, provenance.

    No network, keyless — there is no API-key path. topic= overview (default) |
    indexes | benchmarks | pricing | speed | providers | media | fields (alias
    list) | sources | all.
    """
    return _reference(topic=topic)


@srv.tool(name="aa_raw", title="Raw JSON escape hatch", structured_output=False)
@_tool
def aa_raw(kind: str, query: str = "", fields: str | list[str] = "", top: int = 1,
           refresh: bool = False) -> str:
    """Raw JSON escape hatch.

    kind= model | leaderboard | providers | providers_board | media | agents |
    home | eval | catalog. query= slug/board/eval for the kind. fields= top-level
    keys to keep (ignored for kind=model); top= records (default 1, capped at 5).
    """
    return _raw(kind, query=query, fields=fields, top=top, refresh=refresh)


# --------------------------------------------------------------------------- #
# resources (no network at import; text comes from reference.py / catalog)
# --------------------------------------------------------------------------- #


@srv.resource("aa://reference/metrics", name="Metric & benchmark definitions",
              mime_type="text/markdown",
              description="Metric/eval definitions and methodology notes.")
def _r_metrics() -> str:
    keys = ("indexes", "benchmarks", "pricing", "speed")
    return "\n\n".join(f"## {k}\n\n{reference.TOPICS[k]}" for k in keys)


@srv.resource("aa://benchmarks", name="Benchmark catalog", mime_type="application/json",
              description="The full benchmark registry as JSON.")
def _r_benchmarks() -> str:
    data = [_to_plain(b) for b in catalog.BENCHMARKS.values()]
    return json.dumps(data, indent=1, default=str)


def _rankables_yaml() -> str:
    """The rankable index as the same YAML subset ``aa_compare spec=`` accepts."""
    lines: list[str] = []
    for r in _rankable_list():
        lines.append(f"- key: {_yaml_text(str(getattr(r, 'key', '')))}")
        for field in ("label", "kind", "unit", "surface", "how", "desc"):
            lines.append(f"  {field}: {_yaml_text(str(getattr(r, field, '')))}")
        tags = ", ".join(_yaml_text(str(t)) for t in getattr(r, "tags", ()))
        lines.append(f"  tags: [{tags}]")
        aliases = ", ".join(_yaml_text(str(a)) for a in getattr(r, "aliases", ()))
        if aliases:
            lines.append(f"  aliases: [{aliases}]")
    return "\n".join(lines) + "\n"


@srv.resource("aa://rankables", name="Rankable index", mime_type="application/json",
              description="Every rankable thing (benchmarks, indexes, derived metrics, "
                          "arenas) with its how-to-query hint, as JSON.")
def _r_rankables() -> str:
    return json.dumps([_to_plain(r) for r in _rankable_list()], indent=1, default=str)


@srv.resource("aa://rankables.yaml", name="Rankable index (YAML)",
              mime_type="application/yaml",
              description="The same rankable index as YAML (aa_benchmarks domain/tag "
                          "search covers the same data).")
def _r_rankables_yaml() -> str:
    return _rankables_yaml()


@srv.resource("aa://comparisons/spec", name="Comparison spec template",
              mime_type="application/yaml",
              description="A YAML template for aa_compare's spec= argument "
                          "(models/metrics/view/compact/filters).")
def _r_compare_spec() -> str:
    return _COMPARE_SPEC_TEMPLATE


@srv.resource("aa://sources", name="Data sources & cache", mime_type="text/markdown",
              description="URLs, cache paths, TTLs, offline mode and recovery.")
def _r_sources() -> str:
    return reference.TOPICS["sources"]


def _register_topic_resource(topic: str) -> None:
    def _res() -> str:
        return reference.TOPICS[topic]

    _res.__name__ = f"_r_topic_{topic}"
    _res.__doc__ = f"aa_reference topic={topic}"
    srv.resource(f"aa://reference/{topic}", name=f"reference: {topic}",
                 mime_type="text/markdown",
                 description=f"Static reference text for the {topic} topic.")(_res)


# every ``reference.TOPICS`` entry gets one resource, from the same source as
# ``aa_reference`` (no special-cased topic).
for _topic in reference.TOPICS:
    _register_topic_resource(_topic)


# --------------------------------------------------------------------------- #
# prompts
# --------------------------------------------------------------------------- #


@srv.prompt(name="best_model_for_task",
            description="Pick the best model for a task and budget.")
def best_model_for_task(task: str, budget: str = "", open_weights: str = "") -> str:
    """Recommend the best model for a task, with alternates and the cost knee."""
    lines = [
        ("Pick the best model for the task below using the aa-mcp tools, then answer "
         "with a recommendation, 2 alternates and the knee of the intelligence-vs-cost "
         "curve. Never recompute cost_per_task — it is already cache-aware."),
        "",
        f"task: {task}",
    ]
    if budget:
        lines.append(f"budget: {budget}")
    if open_weights:
        lines.append(f"open_weights: {open_weights}")
    lines += [
        "",
        "Steps:",
        "1. If any model name is uncertain, call aa_search first to pin the slug.",
        ("2. Call aa_leaderboard with filters that encode the task (e.g. "
         "max_cost_per_task for a budget, sort=intelligence; use mode=value for best "
         "value)."),
        ("3. For any value/trade-off question call aa_pareto instead — it returns the "
         "Pareto frontier for the axis that matters (x=cost_per_task default, or "
         "out_tokens_per_task, index_total_cost, time_per_task, context_tokens, "
         "params_b, ttft, price_in, price_out) and names the knee."),
        ("4. Optionally aa_model on the top pick for specs (context, license, "
         "modalities, knowledge cutoff)."),
        ("5. Answer with: one recommendation and why, two alternates, and the knee "
         "point (name, x axis value, score) plus the trade-off."),
    ]
    return "\n".join(lines)


@srv.prompt(name="compare_models", description="Compare specific models side by side.")
def compare_models(models: str) -> str:
    """Compare the named models, adding provider detail when price matters."""
    return "\n".join([
        f"Compare these models: {models}",
        "",
        "Steps:",
        (f"1. Call aa_compare with the models ({models}) — resolve names via aa_search "
         "if unsure. Up to 12 models."),
        ("2. For the full comparison use metrics=\"all\" (every rankable key any of "
         "these models has) and view=\"diff\" (each metric's value plus its delta vs "
         "the first model)."),
        ("3. Keep the `spec:` block aa_compare prints at the end: re-running it with "
         "spec=<that YAML> reproduces the exact comparison later."),
        ("4. If price or provider choice matters, call aa_providers for the winner "
         "(per-endpoint $/1M, precision, TTFT)."),
        ("5. Report a compact comparison table plus a one-line verdict and the key "
         "trade-off. Do not recompute cost_per_task."),
    ])


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #


def main() -> None:
    """Console-script entry point: serve MCP over stdio (stdout = protocol only)."""
    if sys.argv[1:]:
        if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
            sys.stdout.write(
                "usage: aa-mcp [-h]\n\n"
                "Keyless MCP server for artificialanalysis.ai over stdio.\n\n"
                "Options:\n"
                "  -h, --help    Show this help message and exit.\n\n"
                "For ad-hoc CLI calls without an MCP client, use aa-mcp-cli:\n"
                "  aa-mcp-cli list\n"
                "  aa-mcp-cli call <tool> '<json>'\n"
            )
            sys.exit(0)
        sys.stderr.write(
            "aa-mcp is the stdio MCP server; for ad-hoc calls use "
            "aa-mcp-cli call <tool> '<json>' (aa-mcp-cli list for the tool list)\n"
        )
        sys.exit(2)

    level = (os.environ.get("AA_LOG_LEVEL") or "WARNING").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.WARNING),
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    srv.run("stdio")


if __name__ == "__main__":
    main()
