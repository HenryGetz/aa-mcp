"""MCP server for artificialanalysis.ai — tools, resources, prompts, ``main()``.

This is the integration point: it wires the frozen modules (:mod:`fetch`,
:mod:`loaders`, :mod:`catalog`, :mod:`normalize`, :mod:`select`, :mod:`render`,
:mod:`source`) into the eleven agent-facing tools and renders every answer as
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
    source,
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


def _cache_aware(message: str, name: str, refresh: bool = False) -> str:
    """Append cache-file guidance to a parse/load failure (A22/A25/A26).

    A data-layer error that already names the cache file and ``refresh=true``
    (wave A) is passed through unchanged.
    """
    if "refresh=true" in message:
        return message
    path = _cache_file(name)
    if path is not None:
        return (
            f"{message}\n"
            f"— cached payload {path} looks wrong or truncated: retry with "
            "refresh=true to re-download it, or delete the file and retry; if you "
            "have a good copy saved there, AA_OFFLINE=1 uses it without a network call"
        )
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
        raise ValueError(_cache_aware(str(exc), name, refresh)) from None
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
        name, _api = _lb_cache()
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


#: metrics AA publishes on **two** surfaces: the 700-row leaderboard snapshot
#: (``medianOutputTokensPerSecond`` / ``medianTimeToFirstTokenSeconds`` / …) and the
#: first-party model page (``timescaleData.medianOutputSpeed`` /
#: ``medianTimeToFirstChunk`` / ``timeToFirstAnswerToken`` / ``endToEndResponseTime``).
#: The model-page value wins deterministically so one metric never renders two
#: numbers for the same call (wave G, G1).
_DUAL_SOURCE_KEYS = ("tps", "ttft", "ttfa", "e2e")
#: display precision of a ``usd`` cell: catalog.format_value uses 2 decimals above
#: $0.01, so a cost shown as ``$0.00`` is below this bound (G9).
_ZERO_USD = 0.005


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


def _discount(value: Any) -> str:
    """Cache-read discount as a percentage; AA reports it either as 0-1 or 0-100."""
    if value is None:
        return "-"
    v = float(value)
    return f"{v:.0f}%" if v > 1 else f"{v * 100:.0f}%"


def _api_available() -> bool:
    try:
        return source.api_key() is not None
    except Exception:  # pragma: no cover - defensive
        return False


def _source_key() -> str:
    try:
        return loaders.data_source().split(":", 1)[-1]
    except Exception:  # pragma: no cover - defensive
        return "rsc"


def _cache_ttl(api: bool) -> int:
    raw = os.environ.get("AA_API_TTL" if api else "AA_CACHE_TTL")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return 21600 if api else 3600


def _fresh(name: str, *, api: bool = False) -> tuple[float | None, bool]:
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
    return time.time() - age, offline or age > _cache_ttl(api)


def _lb_cache() -> tuple[str, bool]:
    if _source_key() == "api":
        return "api_models_free", True
    return "leaderboard", False


def _header(
    total: int | None = None,
    shown: int = 0,
    note: str = "",
    *,
    count: str | None = None,
    name: str = "",
    api: bool = False,
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
        as_of, stale = _fresh(name, api=api)
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


#: server-side aliases that catalog.py does not carry (capability + speech forms)
_EXTRA_ALIASES: dict[str, str] = {
    "caplegal": "capabilities.legal",
    "legalindex": "capabilities.legal",
    "legalcapability": "capabilities.legal",
    "capmedical": "capabilities.healthcareAndMedical",
    "medicalindex": "capabilities.healthcareAndMedical",
    "healthcareindex": "capabilities.healthcareAndMedical",
    "healthcaremedicalindex": "capabilities.healthcareAndMedical",
    "capfinance": "capabilities.financeAndAccounting",
    "financeindex": "capabilities.financeAndAccounting",
    "financeaccountingindex": "capabilities.financeAndAccounting",
    "capstrategy": "capabilities.strategyAndOps",
    "strategyindex": "capabilities.strategyAndOps",
    "strategyopsindex": "capabilities.strategyAndOps",
    "capengineer": "capabilities.engineering",
    "capengineering": "capabilities.engineering",
    "engineeringindex": "capabilities.engineering",
    "capeconomic": "capabilities.economics",
    "capeconomics": "capabilities.economics",
    "economicsindex": "capabilities.economics",
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
    near = ", ".join(_close(name, pool))
    raise ValueError(
        f"unknown {what} {_q(name)} — closest: {near}\n"
        "— aa_reference topic=fields lists every accepted name"
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
    rows = [[m.name, _txt(m.creator), m.slug] for m in exc.candidates[:8]]
    table = render.table(["Model", "Creator", "Slug"], rows)
    return (
        f"{exc}\n{table}\n"
        "— re-run with the exact slug from the Slug column (aa_search resolves names)"
    )


def _fetch_text(exc: AAFetchError) -> str:
    """Fetch failure plus the loader's hint and the cache/refresh recovery path."""
    hint = getattr(exc, "hint", "")
    text = f"{exc}\n— {hint}" if hint else str(exc)
    if "refresh=true" not in text:
        text += ("\n— retry with refresh=true to re-download it, or serve it from a "
                 "warm cache (AA_OFFLINE=1 uses an existing file without a network call)")
    return text


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
    return _lb_cache()[0]



#: tokens that ask a ``fields=``/``metrics=`` list for *every* column the surface has
_ALL_FIELD_TOKENS = {"all", "*", "everything", "every", "allfields"}


def _is_wildcard_field(name: str) -> bool:
    text = str(name).strip()
    return text in ("*", "**") or _norm_alias(text) in _ALL_FIELD_TOKENS


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
    for name in names:
        key = _identity_key(name, surface, identity_map)
        label = None
        if key is not None:
            label = next((lbl for k, lbl in surface if k == key), None)
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
            cells.append(render.num(select.lookup(model, key), 1))
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
                 identity: Sequence[str] = ()) -> str:
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
    if min_speed is not None:
        parts.append(f"tok/s>={min_speed:g}")
    if max_ttft is not None:
        parts.append(f"TTFT<={max_ttft:g}s")
    if min_context is not None:
        parts.append(f"ctx>={min_context:g}")
    if released_after:
        parts.append(f"released>={render.clean(released_after, None)}")
    return ", ".join(parts)


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

    lb_name, _api = _lb_cache()
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
    """The leaderboard rows for slug resolution (no rich overlay — see B6)."""
    return _models_state(refresh, rich=False)[0]


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


def _no_rank_text(key: str, label: str) -> str:
    if _is_index_key(key):
        return (
            f"{label!r}: AA exposes this index per model only on the scrape source "
            "(model pages) and through the JSON API (AA_API_KEY) — there is no "
            "cross-model ranking to sort by.\n"
            "— read one model with aa_model <slug>, or set AA_API_KEY; "
            "aa_benchmark_leaderboard has no slug for these."
        )
    if catalog.benchmark(key) is None:
        return (
            f"{label!r} has no values in the 700-row leaderboard — it lives on the "
            "model page only.\n"
            "— read it with aa_model <slug>."
        )
    bench = catalog.BENCHMARKS.get(key)
    if bench is not None and bench.source_hint == "chart" and not bench.slug:
        return (
            f"{label!r} is published only on individual model pages — AA exposes no "
            "cross-model column for it in the current source.\n"
            "— read it with aa_model <slug>."
        )
    return (
        f"{label!r} has no per-model values in the current source — it is not in the "
        "700-row leaderboard, and AA's eval chart set / homepage panel carry none "
        "either.\n"
        "— try refresh=true to re-fetch, or read one model with aa_model <slug>."
    )


def _breakdown_text(key: str, label: str) -> str:
    """Honest one-liner for a ``unit == "mixed"`` container benchmark.

    Breakdown benchmarks (``aa3dBreakdown``, ``harveyLabBreakdown``, …) carry a
    per-model *map* of sub-scores, not a scalar column, so there is no ranking to
    give (round-5 audit: this used to raise ``TypeError: float() argument … not
    'dict'``). Names the closest scalar sibling so the caller can re-aim.
    """
    bench = catalog.BENCHMARKS.get(key)
    siblings: list[str] = []
    if bench is not None and bench.slug:
        siblings = [b.key for b in catalog.BENCHMARKS.values()
                    if b.key != key and b.unit != "mixed" and b.slug == bench.slug]
    hint = ""
    if siblings:
        extra = f" (or {', '.join(siblings[1:3])})" if len(siblings) > 1 else ""
        hint = (f"— rank the scalar sibling instead: "
                f"aa_benchmark_leaderboard benchmark={siblings[0]}{extra}; ")
    return (
        f"{label!r} is a container benchmark: AA publishes its values as "
        "per-model sub-score maps, not a cross-model ranking column.\n"
        f"{hint}read one model's breakdown with aa_model <slug> sections=benchmarks"
    )


def _resolve_slug(query: str, models: Sequence[Model]) -> Model:
    try:
        return select.resolve(models, query)
    except select.AmbiguousError:
        raise
    except LookupError:
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
        if bench.unit == "mixed":
            how = f"aa_model <model-slug> sections=benchmarks ({bench.label} breakdown)"
        elif (bench.source_hint != "api"
              and (bench.source_hint != "chart" or bench.slug)):
            # mirrors catalog's rule: the leaderboard path reaches leaderboard /
            # rich / chart-set / panel keys (the join is by eval-page slug)
            how = f"aa_leaderboard sort={key}"
        else:
            how = f"aa_benchmark_leaderboard benchmark={key}"
            if bench.source_hint == "api":
                how += " (needs AA_API_KEY)"
        aliases = tuple(dict.fromkeys((bench.label, *_BENCH_ALIASES.get(key, ()))))
        out[key] = _Rankable(key, bench.label, kind, bench.unit, tuple(bench.tags),
                             how, str(bench.source_hint or "leaderboard"), bench.desc,
                             aliases)
    for key, label, unit, tags, how in _DERIVED_RANKABLES:
        if key in out:
            continue
        out[key] = _Rankable(key, label, "derived", unit, tags, how, "rich", label, ())
    for board, (label, unit, tags, aliases) in _ARENAS.items():
        out.setdefault(board, _Rankable(board, label, "arena", unit, tags,
                                        f"aa_media board={board}", "board", label,
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
            "page with aa_model <slug> sections=cost, set AA_API_KEY, or retry with "
            "refresh=true"
        )
    return (f"{label!r} has no values in the current source — "
            "see aa_reference topic=sources")


def _score_surface(key: str, refresh: bool = False) -> tuple[list[Model], str]:
    """Models carrying ``key`` from AA's eval chart set and homepage panel(s).

    Returns ``(models, source)`` where ``source`` names the surfaces that
    contributed (``"chart set"``, ``"homepage panel"``, or both joined with
    ``" + "``), or ``""`` when AA publishes no per-model values for ``key``.
    Every surface is unioned in one pass — the eval page's chart set and the
    homepage panel(s) (which AA publishes per eval slug, sometimes twice) — so a
    companion scalar carried by only one of them is still reachable. The chart
    record wins where both carry a value (it is the richer record); panel-only
    models are appended rather than dropped.
    """
    bench = catalog.BENCHMARKS.get(key)
    if bench is None or not bench.slug:
        return [], ""
    try:
        chart = _load(f"eval_{bench.slug}", loaders.eval_models, bench.slug,
                      refresh=refresh)
    except (AAFetchError, ValueError):
        chart = []
    scored = [m for m in chart if select.lookup(m, key) is not None]
    sources = ["chart set"] if scored else []
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
    frontier works for a benchmark the 700-row leaderboard does not carry
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
    """Join AA's eval chart-set / homepage-panel values for ``key`` onto ``models``.

    Returns ``(models, source)``; ``source`` is ``""`` when AA publishes no
    per-model surface for ``key`` (so the caller keeps its honest no-rank error).
    The 700-row leaderboard record is the base and the chart/panel record is
    merged under it (same slug), so leaderboard-only columns (cost, speed) survive
    while the chart/panel score is added. Models AA publishes only on a panel /
    chart set are appended, so a ranking is never silently truncated to the rows
    the leaderboard happens to carry.
    """
    extra = _extra_score_models(key, refresh)
    if not extra:
        return list(models), ""
    base = {m.slug: m for m in models}
    joined: dict[str, Model] = {}
    for m in extra:
        if not m.slug:
            continue
        joined[m.slug] = normalize.merge(m, base[m.slug]) if m.slug in base else m
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
        min_speed=min_speed,
        max_ttft=max_ttft,
        min_context=min_context,
        released_after=released_after or None,
        exclude_deprecated=not include_deprecated,
    )
    where = _filter_desc(
        creator=creator, name=name, open_weights=open_weights, reasoning=reasoning,
        min_intelligence=min_intelligence, max_cost_per_task=max_cost_per_task,
        min_speed=min_speed, max_ttft=max_ttft, min_context=min_context,
        released_after=released_after, include_deprecated=include_deprecated,
    )
    if not models:
        return f"# no models match {where} — drop one filter"

    score_of: Callable[[Model], float | None] = functools.partial(
        _metric_value, key=score_key)
    x_of: Callable[[Model], float | None] = functools.partial(_axis_value, key=x_key)

    if not any(score_of(m) is not None for m in models):
        raise ValueError(_no_rank_text(score_key, score_label))
    if not any(x_of(m) is not None for m in models):
        raise ValueError(_axis_missing_text(x_key, x_label))

    if x_key == "cost_per_task" and score_key not in _DERIVED_AXES:
        front = [(m, _metric_value(m, x_key), score_of(m))
                 for m in select.pareto(models, score_key=score_key, cost_key=x_key)]
    else:
        front = _pareto_frontier(models, score_of, x_of)
    if not front:
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

    cache_name, api = _lb_cache()
    note = (f"{score_label} vs {x_label} (Pareto frontier, {x_order} ascending)")
    count = (f"{len(shown)} of {len(front)} frontier points"
             if len(shown) != len(front) else f"{len(front)} frontier points")
    source_label = " + ".join(part for part in (
        _source_key(), "rich dataset" if rich_used else "",
        "eval chart/panel" if panel_used else "") if part)
    head = _header(count=count, note=note, name=cache_name, api=api,
                   source_label=source_label)
    frontier_note = (f"frontier: {len(front)} non-dominated of {scored} models scored "
                     f"on both axes ({len(all_models)} tracked")
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
            "TTFT is the 700-row leaderboard snapshot median here (aa_compare "
            "reports the model page's long-prompt median); aa_model has the "
            "per-prompt-type breakdown (short/medium/long/100k)")
    if unknown:
        footnotes.append(_unknown_field_note(unknown))
    footnotes = list(dict.fromkeys(footnotes))
    body = _table_block(head, [label for _, label in cols], rows, trim=not fields,
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
_LB_EXTRA = ("precision",)
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
            min_speed=min_speed, max_ttft=max_ttft, min_context=min_context,
            released_after=released_after, include_deprecated=include_deprecated,
            refresh=refresh, fields=fields,
        )
    label = _metric_label(sort_key)

    all_models, rich_used = _models_state(
        refresh, rich=_rich_needed(refresh=refresh, sort_key=sort_key, fields=fields))
    tracked = len(_lb_rows(refresh))
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
        if any(select.lookup(m, key) is not None for m in all_models):
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
        min_speed=min_speed,
        max_ttft=max_ttft,
        min_context=min_context,
        released_after=released_after or None,
        exclude_deprecated=not include_deprecated,
    )
    where = _filter_desc(
        creator=creator, name=name, open_weights=open_weights, reasoning=reasoning,
        min_intelligence=min_intelligence, max_cost_per_task=max_cost_per_task,
        min_speed=min_speed, max_ttft=max_ttft, min_context=min_context,
        released_after=released_after, include_deprecated=include_deprecated,
    )
    cache_name, api = _lb_cache()
    explicit = any((creator, name, open_weights is not None, reasoning is not None,
                    min_intelligence is not None, max_cost_per_task is not None,
                    min_speed is not None, max_ttft is not None,
                    min_context is not None, released_after))

    if not models:
        return f"# no models match {where} — drop one filter"

    # A sort key the merged source cannot supply must explain itself, never
    # silently reorder (the rich overlay already covers capability/Elo fields).
    if not any(select.lookup(m, sort_key) is not None for m in models):
        if (not include_deprecated
                and any(select.lookup(m, sort_key) is not None for m in all_models)):
            raise ValueError(
                f"{label!r} is only published for deprecated models in the current "
                "source.\n— re-run with include_deprecated=true to rank them."
            )
        raise ValueError(_no_rank_text(sort_key, label))

    footnotes: list[str] = _missing_notes(all_models, [
        ("intelligence", "intelligence", min_intelligence is not None),
        ("cost_per_task", "cost per task", max_cost_per_task is not None),
        ("tps", "output speed", min_speed is not None),
        ("ttft", "TTFT", max_ttft is not None),
        ("context_tokens", "context window", min_context is not None),
    ])
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

    shown = models[:n]
    if sort_key in ("ttft", "ttfa", "e2e"):
        footnotes.append(
            f"{label} is the 700-row leaderboard snapshot median (aa_compare "
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
        footnotes.append(
            f"{label} comes from AA's eval chart set / homepage panel "
            f"({sort_scored} scored), joined onto the leaderboard rows — not a "
            "full leaderboard"
        )
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
    head = _header(count=count, note=note, name=cache_name, api=api,
                   source_label=source_label)
    out = [_table_block(head, [label for _, label in cols],
                        [_model_cells(m, cols, value_of) for m in shown],
                        trim=not fields, identity=_identity_labels(cols))]
    footnotes = list(dict.fromkeys(footnotes))
    if footnotes:
        out.append(render.note(footnotes))
    return "\n".join(part for part in out if part)


# --------------------------------------------------------------------------- #
# aa_model
# --------------------------------------------------------------------------- #

_INDEX_ORDER = ("intelligence", "coding", "agentic", "openness", "omniscience")
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
    if not _api_available():
        missing = [label for key, label in (("coding", "Coding Index"),
                                            ("agentic", "Agentic Index"))
                   if select.lookup(m, key) is None]
        if missing:
            body += ("\n— " + ", ".join(missing)
                     + " need AA_API_KEY (JSON API); unavailable on the scrape source")
    return body


_CAP_LABELS = {
    "financeAndAccounting": "Finance & Accounting",
    "strategyAndOps": "Strategy & Ops",
    "legal": "Legal",
    "healthcareAndMedical": "Healthcare & Medical",
    "engineering": "Engineering",
    "economics": "Economics",
}


def _model_capabilities(m: Model) -> str | None:
    """The AA capability indexes (aa:api, plus whatever a model page carries)."""
    rows: list[list[str]] = []
    for key in sorted(k for k in m.indices if k.startswith("capabilities.")):
        value = m.indices.get(key)
        if value is None:
            continue
        name = _CAP_LABELS.get(key.split(".", 1)[1], key.split(".", 1)[1])
        rows.append([f"{name} (capability)", _fmt(key, value)])
    if not rows:
        return None
    body = render.table(["Capability index", "Score"], rows)
    if not _api_available():
        body += ("\n— capability scores from the model page (rich dataset); "
                 "AA_API_KEY adds the Coding/Agentic indexes and cross-model ranking")
    return body


def _model_chart_evals(slug: str, have: set[str],
                       refresh: bool = False) -> dict[str, float]:
    """Chart-set / panel benchmark scores AA publishes for ``slug`` but that are
    absent from its rich record (the cyber boards, AA-3D, …).

    The same source chain ``aa_compare`` / ``aa_pareto`` join; only benchmarks AA
    serves from an eval chart set or homepage panel are probed, so a model page
    never fans out over the 700-row leaderboard.
    """
    try:
        panel_slugs = {key.split(":", 1)[1] for key in _home_rows(refresh)
                       if key.startswith("eval:")}
    except (AAFetchError, ValueError):
        panel_slugs = set()
    out: dict[str, float] = {}
    for key, bench in catalog.BENCHMARKS.items():
        if key in have or not bench.slug or bench.source_hint == "api":
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


def _model(query: str, sections: str = "", refresh: bool = False) -> str:
    models = _models(refresh)
    base = _resolve_slug(query, models)
    slug = base.slug
    record = _load(f"model_{slug}", loaders.model, slug, refresh=refresh).get(slug)
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
    if name_notes:
        blocks.append(render.note(name_notes))
    if "indexes" in chosen:
        blocks.append("## Indices\n" + _model_indices(model))
        caps = _model_capabilities(model)
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
        if record is not None and any(
            v is not None for v in (record.speed or {}).values()
        ):
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
    if kind in ("elo", "int") or abs(delta) >= 1000:
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
    """True when AA may publish ``key`` on an eval chart set / homepage panel."""
    bench = catalog.BENCHMARKS.get(key)
    if bench is None or not bench.slug or bench.source_hint == "api":
        return False
    rank = _rankable(key)
    return rank is not None and str(getattr(rank, "unit", "")) != "text"


def _compare_extra_values(key: str, models: Sequence[Model],
                          refresh: bool = False) -> tuple[dict[str, float], str, int]:
    """``({slug: value}, source, scored)`` for ``key`` from AA's chart set/panel.

    Fills a comparison row whose values live outside the 700-row leaderboard and
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
    means the cost is under $0.005 — a bare zero otherwise reads as a measured
    price, and it silently wins every "cheapest" ranking.
    """
    zeros = [(name, value, ow) for name, value, ow in cells
             if value is not None and _axis_text(key, value) == "$0.00"]
    if not zeros:
        return ""
    names = ", ".join(name for name, _, _ in zeros[:3])
    if len(zeros) > 3:
        names += f" +{len(zeros) - 3} more"
    note = f"$0.00 = measured under ${_ZERO_USD:g}{_zero_unit(key)} ({names}"
    if all(ow for _, _, ow in zeros):
        note += ("; AA publishes 0 for open-weights models — self-hosting cost is "
                 "not included")
    return note + ")"


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
    ("wer", "WER"),
    ("time_to_final", "Time to final"),
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
    "wer": "wer", "werindex": "wer", "worderrorrate": "wer",
    "timetofinal": "time_to_final", "time_to_final": "time_to_final",
    "ttf": "time_to_final", "finaltranscript": "time_to_final",
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
        return f"{render.num(entry.ci_lower, 0)}–{render.num(entry.ci_upper, 0)}", None
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
    if key in ("elo", "appearances", "rank"):
        return f"{delta:+,.0f}"
    if key == "wer":
        return f"{delta * 100:+.1f}pp"
    return f"{delta:+.2f}"


def _arena_row_specs(entries: Sequence[_ArenaEntry],
                     metrics_arg: str) -> list[tuple[str, str]]:
    """Rows to render for an arena comparison, honouring ``metrics=``."""
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
    order = [k for k, _ in _ARENA_ROWS]
    lower = metrics_arg.strip().lower()
    if not metrics_arg or lower in ("all", "benchmarks"):
        keys = [k for k in order if k in present]
        if lower != "all":
            keys = [k for k in keys if k != "ci"]  # CI only when asked
        return [(k, _ARENA_ROW_LABEL[k]) for k in keys]
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name in _split(metrics_arg):
        key = _ARENA_FIELD_ALIASES.get(_norm_alias(name))
        if key is None:
            valid = ", ".join(k for k, _ in _ARENA_ROWS)
            raise ValueError(
                f"unknown arena metric {_q(name)} — valid: {valid}\n"
                "— these select rows for an arena/media comparison"
            )
        if key in seen:
            continue
        seen.add(key)
        out.append((key, _ARENA_ROW_LABEL[key]))
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

    board_label = ", ".join(f"{b} ({_arena_board_label(b)})" for b in boards)
    if len(boards) == 1 and boards[0] in loaders.MEDIA_BOARDS:
        cache_name = f"media_{boards[0]}"
    elif len(boards) == 1:
        cache_name = "home"
    else:
        cache_name = ""
    count = f"{len(entries)} models · {len(specs)} metrics · arena"
    note = f"arena board{'s' if len(boards) > 1 else ''}: {board_label}"
    head = _header(count=count, note=note, name=cache_name, api=False)
    footnotes = [
        "arena entries are media/speech models — human-preference scores are "
        "per-board: a value from one board is not comparable with another board's",
        f"source: aa_media board={boards[0]}"
        + (" (and others)" if len(boards) > 1 else ""),
    ]
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
            "arena match was partial — not every query token appears in the name; "
            f"verify the entry on aa_media board={chosen}"
        )
    if fell_back:
        native = ", ".join(native_labels) or "its own metrics"
        footnotes.append(
            f"{board_label} publishes {native}, not "
            f"{', '.join(requested_labels)}; showing the board's own metrics — see "
            f"aa_media board={boards[0]}"
        )
    elif empty_keys:
        gone = ", ".join(label for key, label in specs if key in empty_keys)
        footnotes.append(
            f"{gone} not published on {board_label} (shown as -) — see "
            f"aa_media board={boards[0]}"
        )
    foot = render.note(footnotes)
    return _fit_compare(head, labels, rows, foot)


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
    for raw in names:
        name_board, name = _arena_split_board(raw)
        board = name_board or board_hint or None
        try:
            resolved = _resolve_slug(name, pool)
            picked.append(resolved)
            resolved_pairs.append((raw, resolved))
            continue
        except ValueError as exc:
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
            raise lm_error
        # an exact name is never dropped because a filter excluded it
        resolved = _resolve_slug(name, all_models)
        picked.append(resolved)
        resolved_pairs.append((raw, resolved))

    if arena_groups:
        if picked:
            lm = picked[0].short_name or picked[0].name
            a = arena_groups[0][0]
            raise ValueError(
                "aa_compare compares either language models or arena-board models, "
                "not both.\n"
                f"— arena entry: {_safe_text(a.name, 60)} on {a.board} (compare two "
                f"arena models, or list the board with aa_media board={a.board}); "
                f"language model: {_safe_text(lm, 60)} (aa_leaderboard / aa_search)"
            )
        arena_picked, chosen, other_boards = _arena_pick_board(arena_groups)
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
    if metrics_arg and compact:
        shown_specs = [(k, lbl) for k, lbl in row_specs
                       if any(cell(m, k) != "-" for m in models)]
        dropped_rows = len(row_specs) - len(shown_specs)
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

    cache_name, api = _lb_cache()
    metric_count = (f"{len(shown_specs)} of {len(row_specs)} metrics"
                    if dropped_rows else f"{len(shown_specs)} metrics")
    count = f"{len(models)} models · {metric_count}"
    note = view_note
    head = _header(count=count, note=note, name=cache_name, api=api,
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
            f"{names_} from the 700-row leaderboard snapshot (the model page is not "
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

    Computed from the same source chain the ranking tools use (the 700-row
    leaderboard, the rich overlay, then AA's eval chart set / homepage panel), so
    a benchmark AA now fetches live is never labelled "not fetched".
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
    extra = _extra_score_models(key)
    if extra:
        source = _extra_score_meta(key)[0] or "chart set"
        return f"{source} ({len(extra)} scored)"
    surface = str(getattr(r, "surface", "") or "")
    if surface == "api":
        return "api only (AA_API_KEY)"
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

    lb = _lb_rows()
    merged = _models_state(rich=True)[0]
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

    cache_name, api = _lb_cache()
    qdomain = _query_domain(query) if query else None
    note = " · ".join(part for part in (
        (f"query={render.clean(query, None)}"
         + (" (domain match)" if qdomain else "")) if query else "",
        f"domain={render.clean(domain, None)}" if domain else "",
        f"tag={render.clean(tag, None)}" if tag else "") if part)
    count = f"{len(table_rows)} of {len(rows_all)} rankables"
    head = _header(count=count, note=note, name=cache_name, api=api)
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
    if needs_rich:
        lb, rich_used = _models_state(refresh, rich=True)
    else:
        lb, rich_used = list(lb_plain), False
    cache_name, api = _lb_cache()
    include_extra = True
    source_note: str
    lower_better = _lower_is_better(key)

    if _is_index_key(key):
        # Capability / Coding / Agentic indexes have no leaderboard column; they
        # come from the rich overlay, or there is no ranking to give.
        pairs = scored(lb)
        if not pairs:
            raise ValueError(_no_rank_text(key, bench.label))
        source_note = f"{bench.label} · rich dataset — not a full leaderboard"
    else:
        pairs = scored(lb)
        if pairs:
            native = scored(lb_plain)
            if rich_used and len(pairs) > len(native):
                source_note = f"{bench.label} · rich dataset — not a full leaderboard"
            else:
                source_note = f"{bench.label} · leaderboard"
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
                    cache_name, api = f"eval_{bench.slug}", False
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
                    cache_name, api = "home", False
                    include_extra = False

    if not pairs:
        raise ValueError(
            f"no data for benchmark {bench.label!r}: not in the 700-row leaderboard, "
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

    table_rows = []
    estimated = 0
    for m, value in shown:
        lo, hi = ci_map.get(m.slug, (None, None))
        if m.estimated:
            estimated += 1
        cells = []
        for col, _label in cols:
            if col == "score":
                cells.append(_fmt(key, value) + ("*" if m.estimated else ""))
            elif col == "benchmark":
                cells.append(bench.label)
            elif col in ("ci_lower", "ci_upper", "ci"):
                if col == "ci":
                    cells.append("-" if lo is None and hi is None
                                 else f"{render.num(lo, 0)}–{render.num(hi, 0)}")
                else:
                    cells.append(render.num(lo if col == "ci_lower" else hi, 0))
            else:
                cells.append(_fmt(col, select.lookup(m, col)))
        table_rows.append(cells)

    count = f"{len(shown)} of {len(pairs)} scored ({len(lb)} tracked)"
    head = _header(count=count, note=source_note, name=cache_name, api=api,
                   source_label=_prov_label(rich_used))
    body = _table_block(head, [label for _, label in cols], table_rows, trim=not fields,
                        identity=_identity_labels(cols))
    notes = []
    if tie_note:
        notes.append(tie_note)
    if unknown:
        notes.append(_unknown_field_note(unknown))
    notes += _missing_notes(lb, [("intelligence", "intelligence",
                                  min_intelligence is not None)])
    if estimated:
        body += ("\n— * = AA-estimated score (fitted across variants of the same "
                 "model family); include_estimates=false drops them")
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
        if value is None:
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


def _endpoint_cell(e, key: str, creators: dict[str, str] | None = None) -> str:
    """One provider cell. Identity keys resolve from the endpoint record (G2).

    ``fields=model`` (or ``name``/``slug``) resolves to the surface's own identity
    column, so the Model column can never blank while the payload carries the
    model slug on every endpoint; ``creator`` comes from the model's record.
    """
    if key in ("model_name", "name"):
        return _txt(e.model_name or e.model_slug)
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


def _providers(model: str = "", host: str = "", top: int = 15,
               sort: str = "cost_per_task", fields: str = "",
               open_weights: bool | None = None, min_context: int | None = None,
               refresh: bool = False) -> str:
    n = top if isinstance(top, int) and top > 0 else 15
    sort_key = _prov_sort_key(sort)

    if model:
        base = _resolve_slug(model, _models(refresh))
        try:
            endpoints = _load(f"providers_{base.slug}",
                              loaders.provider_endpoints, base.slug, refresh=refresh)
        except (ValueError, AAFetchError):
            if _publishes_no_endpoints(base.slug):
                return _no_endpoints_text(base)
            raise
        # Endpoint payloads often omit the context window; fall back to the
        # model-level value rather than rendering a misleading "-".
        ctx_filled = False
        if base.context_tokens:
            for e in endpoints:
                if e.context_tokens is None:
                    e.context_tokens = base.context_tokens
                    ctx_filled = True
        if min_context is not None:
            endpoints = [e for e in endpoints
                         if e.context_tokens is not None and e.context_tokens >= min_context]
        endpoints = _endpoint_sort(endpoints, sort_key)
        if not endpoints:
            return (f"# no provider endpoints recorded for {base.name} (aa.{base.slug}) "
                    "— the model-page providers array was empty or all filtered out")
        creators = _creator_map(refresh)
        unknown: list[str] = []
        cols = _cols(_PROV_COLS_MODEL, fields, _PROV_EXTRA, _PROV_IDENTITY, unknown,
                     _PROV_IDENTITY_MAP)
        if not fields:
            cols = _with_sort_col(cols, sort_key)
        rows = [[_endpoint_cell(e, k, creators) for k, _ in cols]
                for e in endpoints[:n]]
        count = f"{len(rows)} of {len(endpoints)} endpoints"
        head = _header(count=count,
                       note=f"{base.name} (aa.{base.slug}), by {sort_key}",
                       name=f"providers_{base.slug}")
        body = _table_block(head, [lbl for _, lbl in cols], rows, trim=not fields,
                            identity=_identity_labels(cols))
        notes = []
        if ctx_filled:
            notes.append("context is model-level, not per-endpoint")
        if unknown:
            notes.append(_unknown_field_note(unknown))
        note = _zero_cost_note("cost_per_task", [
            (base.name, min((e.cost_per_task for e in endpoints
                             if e.cost_per_task is not None), default=None),
             bool(base.is_open_weights))])
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
    head = _header(count=count, note=note, name="providers_board", api=False)
    body = _table_block(head, [lbl for _, lbl in cols], rows, trim=not fields,
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
_MEDIA_COLS = [("rank", "Rank"), ("name", "Model"), ("creator", "Creator"),
               ("elo", "Elo"), ("appearances", "Appearances"),
               ("price", "Price"), ("release_date", "Release")]
_MEDIA_FIELDS = {
    "rank": "Rank", "name": "Model", "model": "Model", "creator": "Creator",
    "elo": "Elo", "ci": "95% CI", "ci_lower": "CI low", "ci_upper": "CI high",
    "appearances": "Appearances", "price": "Price", "price_unit": "Price unit",
    "release": "Release", "release_date": "Release", "open_weights": "Open",
    "url": "URL",
}
_MEDIA_CANON = {"model": "name", "release": "release_date"}


def _media_cols(fields: Any, unknown: list[str] | None = None) -> list[tuple[str, str]]:
    """Media fields are row keys (``elo``/``ci``/``name``), not model metrics.

    The ``Model`` identity column is always rendered first so a requested table
    is never an anonymous list of numbers. A field the board does not have is
    appended to ``unknown`` (when given) and ignored, so a long ``fields=`` list
    renders what resolves instead of aborting the call (G6).
    """
    out: list[tuple[str, str]] = []
    keys: set[str] = set()
    for raw in _split(fields):
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
        out.append((key, _MEDIA_FIELDS[name]))
    if "name" not in keys:
        out.insert(0, ("name", "Model"))
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
        return f"${row['price']:,.2f}{row.get('price_unit') or ''}"
    if key == "rank":
        return _txt(row.get("rank"))
    if key == "appearances":
        value = row.get("appearances")
        return f"{int(value):,}" if value is not None else "-"
    if key == "elo":
        return _fmt("briefcaseElo", row.get("elo"))
    if key == "ci_lower":
        return render.num(row.get("ci_lower"), 0)
    if key == "ci_upper":
        return render.num(row.get("ci_upper"), 0)
    if key == "ci":
        low, high = row.get("ci_lower"), row.get("ci_upper")
        if low is None and high is None:
            return "-"
        return f"{render.num(low, 0)}–{render.num(high, 0)}"
    if key == "release_date":
        return _txt(row.get("release_date"))
    return _txt(row.get(key))


def _media(board: str, top: int = 15, fields: str = "", open_weights: bool | None = None,
           refresh: bool = False) -> str:
    n = top if isinstance(top, int) and top > 0 else 15
    key_name = _norm_board(board)
    key_name = _SPEECH_ALIASES.get(key_name, key_name)

    if key_name in _SPEECH_BOARDS:
        speech = _SPEECH_BOARDS[key_name]
        canonical = key_name
        rows = _home_rows(refresh).get(speech) or []
        if open_weights is not None:
            flagged = [r for r in rows if _row_open_weights(r) is not None]
            if not flagged:
                return (f"# the {canonical} homepage panel carries no open-weights flag "
                        f"({len(rows)} rows) — drop open_weights, or use a model board "
                        "where the flag exists")
            rows = [r for r in flagged if _row_open_weights(r) == open_weights]
        if not rows:
            return f"# no rows for speech board {canonical} in the homepage payload"
        if speech == "sts":
            cols = [("rank", "Rank"), ("name", "Model"), ("hostName", "Host"),
                    ("stsIndex", "STS")]
            table_rows = [[str(i), _txt(r.get("name")), _txt(r.get("hostName")),
                           render.num(r.get("stsIndex"), 1)]
                          for i, r in enumerate(rows[:n], 1)]
        else:
            cols = [("rank", "Rank"), ("name", "Model"), ("creatorName", "Creator"),
                    ("werIndex", "WER%")]
            table_rows = [[str(i), _txt(r.get("name")), _txt(r.get("creatorName")),
                           render.pct(r.get("werIndex"))]
                          for i, r in enumerate(rows[:n], 1)]
        note = (f"{canonical} · speech, WER lower is better" if speech != "sts"
                else f"{canonical} · speech, STS index")
        head = _header(count=f"{len(table_rows)} of {len(rows)} rows", note=note,
                       name="home", api=False)
        return _table_block(head, [lbl for _, lbl in cols], table_rows)

    if key_name not in loaders.MEDIA_BOARDS:
        valid = sorted(loaders.MEDIA_BOARDS) + sorted(_SPEECH_BOARDS)
        raise ValueError(
            f"unknown media board {_q(board)} — valid: {', '.join(valid)} "
            "(hyphens/spaces/case are ignored, e.g. text-to-image == text_to_image; "
            "realtime-voice == speech_to_speech)"
        )
    rows = _load(f"media_{key_name}", loaders.media, key_name, refresh=refresh)
    if open_weights is not None:
        rows = [r for r in rows if r.get("open_weights") == open_weights]
    if not rows:
        return (f"# no rows on media board {_q(board)} "
                f"(open_weights={open_weights}) — drop one filter")

    unknown: list[str] = []
    cols = _media_cols(fields, unknown) if fields else list(_MEDIA_COLS)
    table_rows = [[_media_cell(r, k) for k, _ in cols] for r in rows[:n]]
    explicit = bool(fields or open_weights is not None)
    count = (f"{len(table_rows)} shown of {len(rows)} matching" if explicit
             else f"{len(table_rows)} of {len(rows)} {key_name}")
    head = _header(count=count,
                   note="human-preference Elo (ask fields=ci_lower,ci_upper,ci for the 95% CI)",
                   name=f"media_{key_name}", api=False)
    body = _table_block(head, [lbl for _, lbl in cols], table_rows, trim=not fields,
                        identity=_identity_labels(cols))
    if unknown:
        body += "\n" + render.note([_unknown_field_note(unknown)])
    return body


# --------------------------------------------------------------------------- #
# aa_agents
# --------------------------------------------------------------------------- #

_AGENT_COLS = [("rank", "Rank"), ("agent", "Agent"), ("model", "Model"),
               ("creator", "Creator"), ("score", "Score"), ("cost_per_task", "$/Task")]


def _no_ref(value: Any) -> str:
    """Render a flight ``$…:props:…`` reference as ``-`` instead of leaking it."""
    text = _txt(value)
    return "-" if text.startswith("$") and ":props:" in text else text


def _agents(board: str = "coding_agents", top: int = 15, refresh: bool = False) -> str:
    n = top if isinstance(top, int) and top > 0 else 15
    board_key = _norm_board(board)
    rows = _load(f"agents_{board_key}", loaders.agents,
                 board_key, refresh=refresh)
    shown = rows[:n]
    table_rows = []
    for row in shown:
        table_rows.append([
            _no_ref(row.get("rank")),
            _no_ref(row.get("agent") or row.get("name")),
            _no_ref(row.get("model")),
            _no_ref(row.get("creator")),
            render.pct(row.get("score")),
            _fmt("cost_per_task", row.get("cost_per_task")),
        ])
    head = _header(count=f"{len(shown)} of {len(rows)} rows", note=board_key,
                   name=f"agents_{board_key}", api=False)
    return _table_block(head, [lbl for _, lbl in _AGENT_COLS], table_rows)


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
    board: str                 # board key, e.g. "text_to_speech"
    kind: str                  # "media" | "speech"
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


def _speech_entry(board: str, panel: str, row: dict) -> _ArenaEntry:
    if panel == "sts":
        metrics = (("sts", "STS Index", row.get("stsIndex"), "index"),)
        creator = row.get("hostName")
    else:
        metrics = (("wer", "WER", row.get("werIndex"), "%"),)
        if panel == "stt_streaming":
            metrics += (("time_to_final", "Time to final",
                         row.get("timeToFinalTranscriptSeconds"), "s"),)
        creator = row.get("hostName") or row.get("creatorName")
    return _ArenaEntry(
        name=str(row.get("name") or ""), board=board, kind="speech",
        creator=(str(creator) if creator else None),
        metrics=metrics, rank=None, appearances=None, price=None, price_unit=None,
        release_date=None, open_weights=_row_open_weights(row),
        ci_lower=None, ci_upper=None,
    )


def _arena_entries(refresh: bool = False) -> list[_ArenaEntry]:
    """Every media/speech arena entry, memoised (one board fetch per board)."""
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
    for board, panel in _SPEECH_BOARDS.items():
        try:
            rows = _home_rows(refresh).get(panel) or []
        except (ValueError, AAFetchError) as exc:
            log.debug("arena index: speech panel %s unavailable (%s)", panel, exc)
            continue
        entries += [_speech_entry(board, panel, row) for row in rows]
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
        return render.num(value, 0)
    if unit == "index":
        return render.num(value, 1)
    if unit == "s":
        return render.num(value, 2) + "s"
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


def _arena_pick_board(groups: Sequence[Sequence[_ArenaEntry]]) -> tuple[
        list[_ArenaEntry], str, list[str]]:
    """Pick the board every compared name shares; ``(picks, board, other_boards)``.

    ``groups`` holds each name's candidate entries. The chosen board is the
    alphabetically first board common to all names, so a comparison is never
    silently spread across two boards (which would make the Elo meaningless);
    when a name exists on more boards the extra ones are returned so the reply
    can say a board was chosen.
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
    chosen = sorted(common)[0]
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
    rows = [[e.name, f"{e.board} (arena)", e.metrics[0][1],
             _arena_value_text(e.metrics[0]), e.creator or "-"] for e in entries]
    return render.table(headers, rows)


def _arena_board_key(name: str) -> str | None:
    """The media/speech board key a bare ``name`` names (``text-to-speech`` → …).

    Used so an ambiguous arena name can be pinned to one board, either as a
    standalone ``queries`` entry (``["text_to_speech", "Eleven v4 Turbo", …]``)
    or as a ``board: name`` prefix.
    """
    key = _norm_board(name)
    key = _SPEECH_ALIASES.get(key, key)
    if key in loaders.MEDIA_BOARDS or key in _SPEECH_BOARDS:
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
            "api": "API-only (AA_API_KEY)"}.get(surface, "")


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
        exclude_deprecated=False,
    )
    shown = found[:n]
    arena, arena_partial, arena_hits = (
        _arena_search_rows(query, n, creator, open_weights, refresh)
        if query else ([], False, 0))
    parts: list[str] = []
    if shown:
        cols = _cols(_SEARCH_COLS, "")
        rows = [[_fmt(k, select.lookup(m, k)) for k, _ in cols] for m in shown]
        cache_name, api = _lb_cache()
        matched = len(found)
        explicit = bool(query or creator or open_weights is not None)
        if explicit:
            count = (f"{len(rows)} shown of {matched} matching "
                     f"({len(models)} tracked)")
        else:
            count = f"{len(rows)} of {matched} models"
        note = (f"name match {render.clean(query, None)}" if query
                else "most intelligent")
        head = _header(count=count, note=note, name=cache_name, api=api,
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
            "media/speech models live on arena boards (aa_media)")


def _arena_section(query: str, arena: Sequence[_ArenaEntry], partial: bool,
                   hits: int) -> str:
    """The arena table block (heading + rows + notes) for ``aa_search``."""
    plural = "" if len(arena) == 1 else "es"
    if partial:
        label = f"partial arena-board match{plural} ({hits}/{len(_arena_tokens(query))} tokens)"
    else:
        label = f"arena-board match{plural}"
    head = (f"# {len(arena)} {label} · "
            f"name match {render.clean(query, None)} · aa:arena")
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
    if name in ("indexes", "all") and not _api_available():
        text += ("\n\n— note: coding/agentic/capability indexes need AA_API_KEY "
                 "(JSON API); unavailable on the scrape source (a model page may "
                 "still carry some capability scores).")
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


def _raw(kind: str, query: str = "", fields: str = "", top: int = 1,
         refresh: bool = False) -> str:
    if kind not in _RAW_KINDS:
        raise ValueError(f"unknown kind {_q(kind)} — valid: {', '.join(_RAW_KINDS)}")
    n = min(max(top if isinstance(top, int) else 1, 1), 5)
    keys = _split(fields)
    cache_name = ""
    api = False
    payload: Any

    if kind == "model":
        base = _resolve_slug(query, _models(refresh))
        record = _load(f"model_{base.slug}",
                       loaders.model, base.slug, refresh=refresh).get(base.slug)
        payload = _to_plain(record if record is not None else base)
        cache_name = f"model_{base.slug}"
    elif kind == "leaderboard":
        cache_name, api = _lb_cache()
        payload = [_project(_to_plain(m), keys) for m in _lb_rows(refresh)[:n]]
    elif kind == "providers":
        base = _resolve_slug(query, _models(refresh))
        cache_name = f"providers_{base.slug}"
        payload = [_project(_to_plain(e), keys)
                   for e in _load(f"providers_{base.slug}",
                                  loaders.provider_endpoints, base.slug,
                                  refresh=refresh)[:n]]
    elif kind == "providers_board":
        cache_name = "providers_board"
        payload = [_project(_to_plain(e), keys)
                   for e in _load("providers_board", loaders.provider_board,
                                  refresh=refresh)[:n]]
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

    head = _header(count=f"raw {kind} · top {n}",
                   note="JSON, token-expensive — prefer the table tools",
                   name=cache_name, api=api)
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
    min_speed: float | None = None,
    max_ttft: float | None = None,
    min_context: int | None = None,
    released_after: str = "",
    include_deprecated: bool = False,
    refresh: bool = False,
) -> str:
    """Rank and filter the ~700 tracked model variants — the default starting point.

    Answers "which model is smartest / cheapest / fastest / best value right now".
    Returns a compact markdown table sorted by ``sort`` (default: intelligence).
    Rows that *display* the same value are ordered by a named secondary key
    (intelligence, then slug) and one footnote says so, so a tie at the published
    precision is visible and reproducible.

    Args:
        mode: "rank" (default), "value" (intelligence per $/task), or "frontier"
            (the Pareto intelligence-vs-$/task frontier — the same code path as
            ``aa_pareto``, which also plots other x axes; the footnote gives the
            knee).
        sort: metric/alias to sort by — e.g. intelligence, cost_per_task, tps,
            ttft, context_tokens, price_in, price_out, params_b, release_date, or
            any benchmark key. Use aa_reference topic=fields for all names.
        fields: comma list of columns to show instead of the default set.
        top: rows to return (default 10; >15 drops the Creator column for brevity).
        creator: substring match on the creator/lab (e.g. "anthropic").
        name: substring match on the model name/slug.
        open_weights: True/False to keep only open- or closed-weights models.
        reasoning: True/False to keep only reasoning or non-reasoning models.
        min_intelligence: drop models below this Intelligence Index value.
        max_cost_per_task: drop models above this $/task (cache-aware).
        min_speed: drop models below this median output tok/s.
        max_ttft: drop models above this median time-to-first-token (seconds).
        min_context: drop models with a smaller context window (tokens).
        released_after: ISO date (YYYY-MM-DD); keep models released on/after it.
        include_deprecated: include deprecated rows (default False).
        refresh: bypass the cache and re-fetch (use for "released today").
    """
    return _leaderboard(
        mode=mode, sort=sort, fields=fields, top=top, creator=creator, name=name,
        open_weights=open_weights, reasoning=reasoning,
        min_intelligence=min_intelligence, max_cost_per_task=max_cost_per_task,
        min_speed=min_speed, max_ttft=max_ttft, min_context=min_context,
        released_after=released_after, include_deprecated=include_deprecated,
        refresh=refresh,
    )


@srv.tool(name="aa_model", title="Model digest", structured_output=False)
@_tool
def aa_model(query: str, sections: str | list[str] = "", refresh: bool = False) -> str:
    """One model's full digest: specs, indices, benchmark scores, pricing and speed.

    Use after aa_leaderboard/aa_search when you need everything about a single
    model. The header and footnote always carry the round-trippable slug.

    Args:
        query: model name or slug (fuzzy). Ambiguous names return a candidate table.
        sections: comma string (or list) of identity/indexes/benchmarks/pricing/
            speed/cost/openness/modalities, or all. Default: identity, indexes,
            benchmarks, pricing, speed. Alias: specs = identity. Unknown names
            error with the valid list.
        refresh: bypass the cache and re-fetch.
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
    """The Pareto frontier: any score vs any cost/size/speed axis, with the knee.

    Always available — no per-benchmark tool needed. Returns the models where no
    other model has both a lower-or-equal ``x`` and a higher-or-equal ``score``,
    ordered by ``x`` ascending, plus a knee line and coverage.

    The three site views this covers:
      * ``aa_pareto`` (default)            = "Intelligence Index vs. Cost per Index Task"
      * ``aa_pareto x=out_tokens_per_task`` = "Intelligence Index vs. Output Tokens per Task"
      * ``aa_pareto x=index_total_cost``   = "Intelligence Index vs. Cost to Run the
                                              AA Intelligence Index" (whole suite)

    Args:
        score: any rankable with per-model numbers (default intelligence); e.g.
            cyberIndex, terminalBench40, gpqa, capabilities.legal, openness.
        x: the trade-off axis — cost_per_task (default), index_total_cost,
            out_tokens_per_task, time_per_task, context_tokens, params_b, ttft,
            price_in, price_out.
        top: frontier points to return (default 15; cheapest first).
        creator: substring match on the creator/lab.
        open_weights: True/False to keep only open- or closed-weights models.
        min_intelligence: drop models below this Intelligence Index value.
        min_context: drop models with a smaller context window (tokens).
        include_deprecated: include deprecated rows (default False).
        include_all: return every frontier point instead of the ``top`` cheapest.
        refresh: bypass the cache and re-fetch.
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

    Mirrors artificialanalysis.ai's comparison pages: models as columns (or a
    per-metric delta view), every rankable metric, and a reproducible YAML spec.
    Rows AA publishes only on an eval chart set / homepage panel (the cyber
    boards, AA-3D, …) are joined in and the source is footnoted; any cell that
    stays ``-`` is footnoted (a per-model ``missing on requested metrics: …``
    count, the per-metric detail while the gap is small, or a whole-model
    "no published pricing or speed" line) so no gap is silent.

    One metric never means two numbers: ``tps``/``ttft``/``ttfa``/``e2e`` always
    come from the first-party model page (the same value whichever alias you
    type), and when the 700-row leaderboard snapshot differs by more than 2% one
    footnote names both numbers. ``metrics=all`` carries every published row
    including the derived ``Intel/$`` ratio; a ``score/$`` name asks for that
    ratio on any other score axis. A name that resolves to nothing is ignored
    with one footnote (``unknown, ignored: …``) instead of aborting the call, and
    a fuzzy name / bare family slug is announced (which slug, which
    reasoning-effort variant, its siblings).

    Media/speech arena models (e.g. "Grok Voice 3.0") also resolve: comparing
    only arena entries renders their board metrics (Elo / STS / WER, appearances,
    price, release, open weights) with a footer warning that per-board scores are
    not cross-comparable; mixing a language model with an arena entry is refused
    with an explanation.

    Args:
        queries: 2-12 model names or slugs (language models, or arena entries on
            one board).
        metrics: "all" (every rankable key any selected model has, plus the
            derived score/$ ratios), "benchmarks" (benchmark/index kinds only),
            or a comma list of keys/labels/aliases; empty uses the default rows
            (Intelligence, Intel/$, $/task, in/out $/1M, tok/s, TTFT, Context).
            For an arena comparison the names are arena fields (elo, sts, wer,
            ci, appearances, price, release, open_weights, rank, board, creator).
        view: "table" (models as columns) or "diff" (one row per metric, value
            plus the delta vs the first model, e.g. 57.6 (+4.9)).
        compact: default metric set only — keep the core rows instead of the full
            set; ignored (and stated in the footer) whenever metrics= is given.
        spec: a YAML or JSON document with models/metrics/view/compact/filters,
            merged with the explicit arguments; every reply ends with a
            copy-pasteable ``spec:`` block that reproduces the call (view and
            compact included, so the round-trip is lossless).
        refresh: bypass the cache and re-fetch.
    """
    return _compare(queries, metrics=metrics, view=view, compact=compact,
                    spec=spec, refresh=refresh)


@srv.tool(name="aa_benchmarks", title="Benchmark & metric search index",
          structured_output=False)
@_tool
def aa_benchmarks(query: str = "", domain: str = "", tag: str = "",
                  verbose: bool = False) -> str:
    """Search everything rankable: benchmarks, indexes, derived metrics, arenas.

    Each hit carries its ``How to query`` hint (the exact tool call), so finding
    "Artificial Analysis Speech to Speech Index" immediately gives you
    ``aa_media board=speech_to_speech``. A task word AA publishes no benchmark for
    (classification, summarization, translation, retrieval/RAG, SQL/data analysis,
    tool calling, …) answers with the closest AA measures instead of dead-ending.

    Args:
        query: tokenised AND-match over key/label/aliases/description/tags
            (e.g. "speech", "cyber", "long context").
        domain: one domain name (coding, math, science, security, agentic,
            tool-use, long-context, instruction-following, knowledge, reasoning,
            safety, multimodal, speech, media, music, video, business, finance,
            legal, medical, engineering, economics, cost, speed, openness, ...).
        tag: one raw tag (a narrower filter than domain=).
        verbose: also show what each thing measures.
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
    refresh: bool = False,
) -> str:
    """Rank models on one benchmark, stating the source and coverage honestly.

    Auto-selects the richest source: the full 700-row leaderboard when the field
    exists there, else AA's curated eval chart set, else the homepage panel; the
    header says which and warns when it is not a full leaderboard.

    Args:
        benchmark: benchmark key, label or eval slug (e.g. gpqa, gpqa-diamond,
            "GPQA Diamond", briefcaseElo).
        top: rows to return (default 15).
        fields: comma list of columns to show instead of the default set.
        creator: substring match on the creator/lab.
        open_weights: True/False to keep only open- or closed-weights models.
        min_intelligence: drop models below this Intelligence Index value.
        include_estimates: include AA-estimated scores (default True); estimates
            are marked with * and footnoted.
        refresh: bypass the cache and re-fetch.
    """
    return _benchmark_leaderboard(
        benchmark, top=top, fields=fields, creator=creator,
        open_weights=open_weights, min_intelligence=min_intelligence,
        include_estimates=include_estimates, refresh=refresh,
    )


@srv.tool(name="aa_providers", title="Provider endpoints", structured_output=False)
@_tool
def aa_providers(model: str = "", host: str = "", top: int = 15,
                 sort: str = "cost_per_task", fields: str | list[str] = "",
                 open_weights: bool | None = None, min_context: int | None = None,
                 refresh: bool = False) -> str:
    """Provider endpoints: per-host pricing, precision, speed and feature flags.

    Pass ``model`` for one model's serving endpoints (with per-endpoint $/task and
    precision), or ``host``/filters for the 1,200-row provider board. With neither,
    returns the cheapest endpoints globally. A model AA lists no API endpoints for
    is explained rather than errored, and ``fields=model``/``slug``/``host``/
    ``creator`` always resolve from the endpoint's own record.

    Args:
        model: model name or slug — switches to per-model endpoint detail.
        host: substring match on the serving host (e.g. "groq").
        top: rows to return (default 15).
        sort: cost_per_task (default), price_in, price_out, tps, ttft,
            intelligence or context_tokens. Lower-is-better keys sort ascending.
        fields: comma list of columns; supports model/name, slug, host, creator,
            precision, cache_read, discount, e2e, function_calling, json_mode,
            context_tokens. A name that resolves to nothing is ignored with one
            footnote.
        open_weights: keep only endpoints for open- or closed-weights models.
        min_context: drop endpoints with a smaller context window (tokens).
        refresh: bypass the cache and re-fetch.
    """
    return _providers(model=model, host=host, top=top, sort=sort, fields=fields,
                      open_weights=open_weights, min_context=min_context,
                      refresh=refresh)


@srv.tool(name="aa_media", title="Media leaderboards", structured_output=False)
@_tool
def aa_media(board: str, top: int = 15, fields: str | list[str] = "",
             open_weights: bool | None = None, refresh: bool = False) -> str:
    """Human-preference arenas: image, video, speech, music (Elo + 95% CI).

    Args:
        board: any image/video/TTS/music board key (text_to_image, image_editing,
            text_to_video, image_to_video, video_editing, text_to_speech,
            text_to_speech_controlled, music_instrumental, music_with_vocals) or a
            speech board (speech_to_text, speech_to_text_streaming,
            speech_to_speech — also accepted as realtime_voice / "realtime voice").
            Hyphens/spaces/case are ignored (text-to-image == text_to_image).
        top: rows to return (default 15).
        fields: comma string (or list) of columns; supports ci_lower, ci_upper, ci
            (95% CI), open_weights, url. Elo CI is not shown by default.
        open_weights: keep only open- or closed-weights entries.
        refresh: bypass the cache and re-fetch.
    """
    return _media(board, top=top, fields=fields, open_weights=open_weights,
                  refresh=refresh)


@srv.tool(name="aa_agents", title="Agent leaderboards", structured_output=False)
@_tool
def aa_agents(board: str = "coding_agents", top: int = 15, refresh: bool = False) -> str:
    """AA agent leaderboards: coding agents, chatbots and search APIs.

    Args:
        board: coding_agents (default), chatbots or search_api.
        top: rows to return (default 15).
        refresh: bypass the cache and re-fetch.
    """
    return _agents(board=board, top=top, refresh=refresh)


@srv.tool(name="aa_search", title="Find a model slug", structured_output=False)
@_tool
def aa_search(query: str = "", creator: str = "", open_weights: bool | None = None,
              top: int = 15, refresh: bool = False) -> str:
    """Cheap name -> slug resolver; call this first whenever a name is uncertain.

    Always returns the slug so the next tool call can be exact. Media/speech
    arena models (image/video/speech/music boards) are searched too and returned
    with their board, so a name like "Grok Voice 3.0" resolves instead of coming
    back empty. A query that was resolved for you says so — the fuzzy match
    (``matched 'opus max' → claude-opus-5-5``) and the reasoning-effort variant
    when a bare family slug matched one. A query that names a task AA publishes
    no benchmark for ("best model for classification") answers with the closest
    AA measures instead of dead-ending.

    Args:
        query: fuzzy model name or partial slug (e.g. "claude opus").
        creator: optional creator/lab substring filter.
        open_weights: True/False to keep only open- or closed-weights models.
        top: rows to return (default 15).
        refresh: bypass the cache and re-fetch.
    """
    return _search(query=query, creator=creator, open_weights=open_weights,
                   top=top, refresh=refresh)


@srv.tool(name="aa_reference", title="Reference & provenance", structured_output=False)
@_tool
def aa_reference(topic: str = "overview") -> str:
    """Static reference text: tool routing, metric/eval definitions, provenance.

    No network. Use to learn what the fields mean and which tool answers what.

    Args:
        topic: overview (default), indexes, benchmarks, pricing, speed, providers,
            media, fields (alias list), sources, or all.
    """
    return _reference(topic=topic)


@srv.tool(name="aa_raw", title="Raw JSON escape hatch", structured_output=False)
@_tool
def aa_raw(kind: str, query: str = "", fields: str | list[str] = "", top: int = 1,
           refresh: bool = False) -> str:
    """Raw JSON escape hatch (token-expensive — prefer the table tools).

    Args:
        kind: model, leaderboard, providers, providers_board, media, agents, home,
            eval or catalog.
        query: slug/board/slug argument for the chosen kind (e.g. a model slug for
            "model", a board key for "media"/"agents", an eval slug for "eval").
        fields: comma list of top-level keys to keep per record.
        top: records to return, capped at 5 (default 1).
        refresh: bypass the cache and re-fetch.
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
    level = (os.environ.get("AA_LOG_LEVEL") or "WARNING").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.WARNING),
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    srv.run("stdio")


if __name__ == "__main__":
    main()
