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
import json
import logging
import os
import sys
import time
from typing import Any, Iterable, Sequence

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import catalog, fetch, flight, loaders, normalize, reference, render, select, source
from . import __version__
from .fetch import AAFetchError
from .normalize import Model

log = logging.getLogger("aa_mcp.server")

_OFFLINE_ON = ("1", "true", "yes", "on")

# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #


def _split(csv: str) -> list[str]:
    return [part.strip() for part in (csv or "").split(",") if part.strip()]


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
    except OSError:  # pragma: no cover - defensive
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
    total: int | None,
    shown: int,
    note: str = "",
    *,
    name: str = "",
    api: bool = False,
    source_label: str | None = None,
) -> str:
    as_of: float | None = None
    if name:
        as_of, stale = _fresh(name, api=api)
        if stale and as_of is not None:
            note = (f"{note} · stale: {render.ago(as_of)}").strip(" ·")
            as_of = None
    return render.header(total, shown, note=note,
                         source=source_label or _source_key(), as_of=as_of)


def _close(query: str, pool: Iterable[str], n: int = 5) -> list[str]:
    pool = list(dict.fromkeys(pool))
    hits = difflib.get_close_matches(query, pool, n=n, cutoff=0.35)
    if not hits:
        ql = query.lower()
        hits = [p for p in pool if ql in p.lower()][:n]
    return hits


def _metric_key(name: str, what: str = "metric") -> str:
    m = catalog.metric(name)
    if m is not None:
        return m.key
    b = catalog.benchmark(name)
    if b is not None:
        return b.key
    pool = list(catalog.METRICS) + list(catalog.FIELD_ALIASES)
    near = ", ".join(_close(name, pool))
    raise ValueError(
        f"unknown {what} {name!r} — closest: {near}\n"
        "— aa_reference topic=fields lists every accepted name"
    )


def _ambiguous_text(exc: select.AmbiguousError) -> str:
    rows = [[m.name, _txt(m.creator), m.slug] for m in exc.candidates[:8]]
    table = render.table(["Model", "Creator", "Slug"], rows)
    return (
        f"{exc}\n{table}\n"
        "— re-run with the exact slug from the Slug column (aa_search resolves names)"
    )


def _fetch_text(exc: AAFetchError) -> str:
    hint = getattr(exc, "hint", "")
    return f"{exc}\n— {hint}" if hint else str(exc)


def _tool(fn):
    """Deliver actionable error text to the client as an MCP ``ToolError``.

    ``mcp`` 2.x hides the message of an uncaught exception behind a generic
    "Error executing tool ..." wrapper, so every expected failure is re-raised
    as :class:`ToolError` with its own text preserved.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise
        except AAFetchError as exc:
            raise ToolError(_fetch_text(exc)) from exc
        except select.AmbiguousError as exc:
            raise ToolError(_ambiguous_text(exc)) from exc
        except LookupError as exc:
            raise ToolError(str(exc)) from exc
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    return wrapper


def _cols(default: Sequence[tuple[str, str]], fields: str,
          extra: Iterable[str] = ()) -> list[tuple[str, str]]:
    """Column list from ``fields`` (metric aliases, plus any non-metric ``extra``)."""
    if not fields:
        return list(default)
    extra = set(extra)
    out: list[tuple[str, str]] = []
    for name in _split(fields):
        try:
            key = _metric_key(name, "field")
        except ValueError:
            if name not in extra:
                raise
            key = name
        metric = catalog.metric(key)
        out.append((key, metric.label if metric else name.replace("_", " ").title()))
    return out


def _model_cells(model: Model, cols: Sequence[tuple[str, str]]) -> list[str]:
    cells: list[str] = []
    for key, _label in cols:
        value = select.lookup(model, key)
        if key == "value":
            cells.append(render.num(value, 1) if value is not None else "-")
        else:
            cells.append(_fmt(key, value))
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
                 empty: str = "no values to show for the selected columns") -> str:
    """Header + a markdown table with all-null columns removed."""
    headers, rows = _trim(headers, rows)
    if not headers:
        return f"{head}\n— {empty}"
    return f"{head}\n{render.table(headers, rows)}"


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
        parts.append(f"creator~{creator}")
    if name:
        parts.append(f"name~{name}")
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
        parts.append(f"released>={released_after}")
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


def _resolve_slug(query: str, models: Sequence[Model]) -> Model:
    try:
        return select.resolve(models, query)
    except select.AmbiguousError:
        raise
    except LookupError:
        near = select.search(models, query, limit=5)
        slugs = ", ".join(m.slug for m in near) or "none"
        raise ValueError(
            f"no model matches {query!r} — closest slugs: {slugs}\n"
            "— use aa_search to resolve names to slugs"
        ) from None


# --------------------------------------------------------------------------- #
# aa_leaderboard
# --------------------------------------------------------------------------- #

_LB_COLS = [
    ("name", "Model"), ("slug", "Slug"), ("creator", "Creator"),
    ("intelligence", "Intel"), ("cost_per_task", "$/Task"),
    ("tps", "tok/s"), ("ttft", "TTFT"), ("context_tokens", "Ctx"),
]


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
            f"unknown mode {mode!r} — expected rank, value or frontier"
        )
    n = top if isinstance(top, int) and top > 0 else 10
    sort_key = _metric_key(sort, "sort")

    all_models = loaders.leaderboard(refresh=refresh)
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
    label = catalog.metric(sort_key).label
    note = f"models · {label}, {where}"
    cache_name, api = _lb_cache()

    if not models:
        return f"# no models match {where} — drop one filter"

    footnotes: list[str] = _missing_notes(all_models, [
        ("intelligence", "intelligence", min_intelligence is not None),
        ("cost_per_task", "cost per task", max_cost_per_task is not None),
        ("tps", "output speed", min_speed is not None),
        ("ttft", "TTFT", max_ttft is not None),
        ("context_tokens", "context window", min_context is not None),
    ])
    if mode == "value":
        ranked = select.value_rank(models, score_key=sort_key)
        ranked.sort(key=lambda m: m.value if m.value is not None else float("-inf"),
                    reverse=True)
        models = ranked
        cols = _cols(_LB_COLS + [("value", "Intel/$")], fields)
        note = f"models · value = {label} per $/task, {where}"
    elif mode == "frontier":
        frontier = select.pareto(models, score_key=sort_key)
        if not frontier:
            return (f"# frontier needs both {label} and $/task — "
                    f"no model has both · {where}")
        knee = max(frontier, key=lambda m: (m.value if m.value is not None
                                            else (m.intelligence or 0) / (m.cost_per_task or 1)))
        select.value_rank(frontier, score_key=sort_key)
        models = frontier
        cols = _cols(_LB_COLS, fields)
        note = f"models · Pareto {label} vs $/task (cost ascending), {where}"
        footnotes.append(
            f"knee ≈ {knee.name}: {_fmt('cost_per_task', knee.cost_per_task)}/task, "
            f"intel {_fmt('intelligence', knee.intelligence)}"
        )
    else:
        models = select.sort_models(models, sort_key)
        cols = _cols(_LB_COLS, fields)

    if not fields and n > 15:
        cols = [c for c in cols if c[0] != "creator"]

    shown = models[:n]
    if mode == "frontier":
        footnotes.insert(0, f"{len(models)} points on the frontier; showing {len(shown)}")
    if sort_key in ("ttft", "ttfa", "e2e"):
        footnotes.append(
            f"{label} is AA's long-prompt median; use aa_model for the "
            "per-prompt-type breakdown (short/medium/long/100k)"
        )

    head = _header(len(all_models), len(shown), note, name=cache_name, api=api)
    out = [_table_block(head, [label for _, label in cols],
                        [_model_cells(m, cols) for m in shown])]
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
    parts = [_txt(m.creator)]
    if m.release_date:
        parts.append(f"released {m.release_date}")
    if m.params_b:
        parts.append(f"{render.num(m.params_b, 0)}B params")
    if m.active_params_b:
        parts.append(f"{render.num(m.active_params_b, 0)}B active")
    if m.context_tokens:
        parts.append(f"{render.ctx(m.context_tokens)} ctx")
    if m.modalities_in or m.modalities_out:
        mods = "+".join(m.modalities_in) or "?"
        mods += "→" + ("+".join(m.modalities_out) or "?")
        parts.append(mods)
    if m.is_reasoning:
        parts.append("reasoning" + (f" ({m.effort})" if m.effort else ""))
    parts.append(
        "open-weights" + (f" · {m.license}" if m.license else "")
        if m.is_open_weights else "closed"
    )
    if m.deprecated:
        parts.append("deprecated" + (f" → {m.deprecated_to}" if m.deprecated_to else ""))
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
        body += ("\n— capability indexes need AA_API_KEY (JSON API); scores shown "
                 "come from the model page")
    return body


def _model_benchmarks(m: Model) -> str | None:
    rows: list[list[str]] = []
    seen: set[str] = set()
    for key, value in m.evals.items():
        if value is None:
            continue
        bench = catalog.benchmark(key)
        canonical = bench.key if bench is not None else key
        if canonical in seen:
            continue  # alias keys (e.g. itbenchSre / itBenchSre) collapse to one row
        seen.add(canonical)
        label = bench.label if bench else key
        if bench is not None and bench.unit == "Elo":
            label += " (Elo)"
        rows.append([label, _fmt(canonical, value)])
    if not rows:
        return None
    return render.table(["Eval", "Score"], rows)


_PROMPT_TYPES = (("short", "short"), ("medium", "medium"), ("long", "long"),
                 ("hundredK", "100k"))


def _prompt_speed(slug: str) -> str | None:
    """TTFT (median time-to-first-chunk) per prompt type, from the model page.

    The headline TTFT is the long-prompt median; the chart record breaks it out
    by ``performanceByPromptType`` (short/medium/long/hundredK).
    """
    try:
        path = loaders.SOURCE_URLS["model"].format(slug=slug)
        text = fetch.get(loaders.url(path), f"model_{slug}").text
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
    return render.table(["Pricing", "Value"], rows)


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
    models = loaders.leaderboard(refresh=refresh)
    base = _resolve_slug(query, models)
    slug = base.slug
    record = loaders.model(slug, refresh=refresh).get(slug)
    model = normalize.merge(base, record) if record is not None else base

    chosen = _split(sections)
    if not chosen:
        chosen = ["identity", "indexes", "benchmarks", "pricing", "speed"]
    if "all" in chosen:
        chosen = list(_SECTIONS)
    bad = [s for s in chosen if s not in _SECTIONS]
    if bad:
        raise ValueError(
            f"unknown section(s) {', '.join(bad)} — valid: {', '.join(_SECTIONS)}, all"
        )

    as_of, stale = _fresh(f"model_{slug}")
    head = f"# {model.name} · {_txt(model.creator)} · aa.{slug}"
    if as_of is not None:
        head += f" · {'stale: ' + render.ago(as_of) if stale else render.ago(as_of)}"
    head += f" · aa:{_source_key()}"

    blocks = [head, _model_facts(model)]
    if "indexes" in chosen:
        blocks.append("## Indices\n" + _model_indices(model))
        caps = _model_capabilities(model)
        if caps:
            blocks.append("## Capability indexes\n" + caps)
    if "benchmarks" in chosen:
        table = _model_benchmarks(model)
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
    ("intelligence", "Intelligence"), ("cost_per_task", "$/task"),
    ("price_in", "In $/1M"), ("price_out", "Out $/1M"),
    ("tps", "tok/s"), ("ttft", "TTFT"),
]
_COMPARE_FULL = [
    ("intelligence", "Intelligence"), ("cost_per_task", "$/task"),
    ("price_in", "In $/1M"), ("price_out", "Out $/1M"),
    ("tps", "tok/s"), ("ttft", "TTFT"), ("context_tokens", "Context"),
    ("release_date", "Released"), ("params_b", "Params (B)"),
    ("is_open_weights", "Open weights"), ("effort", "Effort"),
]


def _compare(queries: list[str], metrics: str = "", compact: bool = True,
             refresh: bool = False) -> str:
    if not isinstance(queries, list) or not (2 <= len(queries) <= 6):
        raise ValueError(
            f"aa_compare takes 2-6 models; got {len(queries) if isinstance(queries, list) else 0}"
        )
    models = loaders.leaderboard(refresh=refresh)
    picked = [_resolve_slug(q, models) for q in queries]

    if metrics:
        rows = []
        for name in _split(metrics):
            key = _metric_key(name, "metric")
            metric = catalog.metric(key)
            rows.append((key, metric.label if metric else name))
    else:
        rows = list(_COMPARE_ROWS if compact else _COMPARE_FULL)

    short = [m.short_name or m.name for m in picked]
    duplicate = len(set(short)) != len(short)
    slug_row = duplicate

    table_rows: list[list[str]] = []
    if slug_row:
        table_rows.append(["Slug", *[m.slug for m in picked]])
    for key, label in rows:
        table_rows.append([label, *[_fmt(key, select.lookup(m, key))
                                   for m in picked]])
    labels = ["Metric", *short]
    body = render.table(labels, table_rows)

    cache_name, api = _lb_cache()
    head = _header(None, len(picked), "models compared", name=cache_name, api=api)
    return f"{head}\n{body}"


# --------------------------------------------------------------------------- #
# aa_benchmarks
# --------------------------------------------------------------------------- #

def _coverage(bench: catalog.Benchmark, models: Sequence[Model]) -> str:
    if bench.key in ("coding", "agentic") or bench.key.startswith("capabilities."):
        return "api only"
    count = sum(1 for m in models if select.lookup(m, bench.key) is not None)
    if count:
        return f"{count}/{len(models)}"
    if bench.unit == "mixed":
        return "model page only"
    if bench.slug:
        return "chart set only"
    return "model page only"


def _benchmarks(query: str = "", verbose: bool = False) -> str:
    models = loaders.leaderboard()
    q = (query or "").strip().lower()
    entries = []
    for bench in catalog.BENCHMARKS.values():
        if q and not (q in bench.key.lower() or q in bench.label.lower()
                      or any(q in tag for tag in bench.tags)):
            continue
        entries.append(bench)
    if not entries:
        near = ", ".join(_close(query, [b.key for b in catalog.BENCHMARKS.values()]
                                + [b.label for b in catalog.BENCHMARKS.values()]))
        raise ValueError(
            f"no benchmark matches {query!r} — closest: {near}"
        )

    show_measures = verbose or len(entries) <= 10
    if verbose:
        headers = ["Benchmark", "Slug", "Unit", "Coverage", "Index", "Tags", "Measures"]
    elif show_measures:
        headers = ["Benchmark", "Slug", "Unit", "Coverage", "Measures"]
    else:
        headers = ["Benchmark", "Slug", "Unit", "Coverage"]
    rows = []
    for bench in entries:
        base = [bench.label, bench.slug or "-", bench.unit, _coverage(bench, models)]
        if verbose:
            base += ["yes" if bench.index_member else "-",
                     ", ".join(bench.tags) or "-", bench.desc]
        elif show_measures:
            base.append(bench.desc)
        rows.append(base)

    cache_name, api = _lb_cache()
    note = (f"benchmarks · query={query}" if query else "benchmarks · all")
    head = _header(len(catalog.BENCHMARKS), len(rows), note,
                   name=cache_name, api=api)
    body = _table_block(head, headers, rows)
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
    bench = catalog.benchmark(benchmark)
    if bench is None:
        near = ", ".join(_close(benchmark, [b.key for b in catalog.BENCHMARKS.values()]
                                + [b.label for b in catalog.BENCHMARKS.values()]))
        raise ValueError(
            f"unknown benchmark {benchmark!r} — closest: {near}\n"
            "— aa_benchmarks lists every benchmark with its slug and coverage"
        )
    n = top if isinstance(top, int) and top > 0 else 15
    key = bench.key

    def keep(m: Model) -> bool:
        if creator and not (m.creator and creator.lower() in m.creator.lower()):
            return False
        if open_weights is not None and m.is_open_weights != open_weights:
            return False
        if min_intelligence is not None and (m.intelligence is None
                                             or m.intelligence < min_intelligence):
            return False
        if not include_estimates and m.estimated:
            return False
        return True

    def scored(models: Sequence[Model]) -> list[tuple[Model, float]]:
        out = []
        for m in models:
            value = select.lookup(m, key)
            if value is not None and keep(m):
                out.append((m, float(value)))
        return out

    # 1) full cross-model ranking from the 700-row leaderboard
    lb = loaders.leaderboard(refresh=refresh)
    pairs = scored(lb)
    source_note: str
    cache_name, api = _lb_cache()
    include_extra = True
    if pairs:
        present = sum(1 for m in lb if select.lookup(m, key) is not None)
        source_note = f"{bench.label} · {present}/{len(lb)} models scored (leaderboard)"
    else:
        # 2) AA's own chart set for the eval page
        pairs = []
        if bench.slug:
            try:
                chart = loaders.eval_models(bench.slug, refresh=refresh)
            except (AAFetchError, ValueError):
                chart = []
            pairs = scored(chart)
            if not pairs and chart:
                pairs = _raw_chart_pairs(bench.slug, key, chart, keep, refresh=refresh)
            if pairs:
                source_note = (f"{bench.label} · AA chart set ({len(pairs)} models) — "
                               "not a full leaderboard")
                cache_name, api = f"eval_{bench.slug}", False
        # 3) homepage panel (top 20) for the security boards
        if not pairs and bench.slug:
            try:
                panel = loaders.home_boards(refresh=refresh).get(f"eval:{bench.slug}") or []
            except AAFetchError:
                panel = []
            raw = []
            for item in panel:
                value = item.get("score")
                if value is None or not keep(_panel_model(item, key)):
                    continue
                raw.append((_panel_model(item, key), float(value)))
            pairs = raw
            if pairs:
                source_note = (f"{bench.label} · homepage panel (top {len(pairs)}) — "
                               "not a full leaderboard")
                cache_name, api = "home", False
                include_extra = False

    if not pairs:
        raise ValueError(
            f"no data for benchmark {bench.label!r}: not in the 700-row leaderboard, "
            "the eval chart set or the homepage panels — try aa_benchmarks for coverage"
        )

    pairs.sort(key=lambda t: t[1], reverse=True)
    shown = pairs[:n]

    score_label = bench.label
    if bench.unit not in ("%", "index"):
        score_label += f" ({bench.unit})"
    default_cols = [("name", "Model"), ("slug", "Slug"), ("creator", "Creator"),
                    ("score", score_label)]
    cols: list[tuple[str, str]]
    if fields:
        cols = _cols([], fields, ("score",))
    else:
        cols = list(default_cols)
        if include_extra:
            cols += [("intelligence", "Intel"), ("cost_per_task", "$/Task")]
    if not fields and n > 15:
        cols = [c for c in cols if c[0] != "creator"]

    table_rows = []
    for m, value in shown:
        cells = []
        for col, _label in cols:
            if col == "score":
                cells.append(_fmt(key, value))
            else:
                cells.append(_fmt(col, select.lookup(m, col)))
        table_rows.append(cells)

    head = _header(len(lb), len(shown), source_note, name=cache_name, api=api)
    body = _table_block(head, [label for _, label in cols], table_rows)
    notes = _missing_notes(lb, [("intelligence", "intelligence",
                                 min_intelligence is not None)])
    if notes:
        body += "\n" + render.note(notes)
    return body


def _raw_chart_pairs(slug: str, key: str, models: Sequence[Model], keep,
                     refresh: bool = False) -> list[tuple[Model, float]]:
    """Fallback for chart-set benchmarks the normalizer does not surface.

    Some eval-page chart fields (e.g. ``briefcaseElo``) live on the raw record
    but not on ``Model.evals``, so read the page's ``initialModels`` array and
    pair the value with the normalized model by slug.
    """
    try:
        path = loaders.SOURCE_URLS["eval"].format(slug=slug)
        text = fetch.get(loaders.url(path), f"eval_{slug}", refresh=refresh).text
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
        indices={}, evals={key: item.get("score")}, pricing={}, speed={},
        cost_per_task=None, cost_breakdown=None, per_eval_cost=None, source="panel",
    )


# --------------------------------------------------------------------------- #
# aa_providers
# --------------------------------------------------------------------------- #

_PROV_SORT = ("cost_per_task", "price_in", "price_out", "tps", "ttft",
              "intelligence", "context_tokens")
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


def _endpoint_cell(e, key: str) -> str:
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


def _providers(model: str = "", host: str = "", top: int = 15,
               sort: str = "cost_per_task", fields: str = "",
               open_weights: bool | None = None, min_context: int | None = None,
               refresh: bool = False) -> str:
    n = top if isinstance(top, int) and top > 0 else 15

    if model:
        base = _resolve_slug(model, loaders.leaderboard(refresh=refresh))
        endpoints = loaders.provider_endpoints(base.slug, refresh=refresh)
        if min_context is not None:
            endpoints = [e for e in endpoints
                         if e.context_tokens is not None and e.context_tokens >= min_context]
        endpoints = _endpoint_sort(endpoints, sort if sort in _PROV_SORT else "cost_per_task")
        if not endpoints:
            return (f"# no provider endpoints recorded for {base.name} (aa.{base.slug}) "
                    "— the model-page providers array was empty")
        cols = _cols(_PROV_COLS_MODEL, fields, _PROV_EXTRA)
        rows = [[_endpoint_cell(e, k) for k, _ in cols] for e in endpoints[:n]]
        head = _header(None, len(rows),
                       f"endpoints · {base.name} (aa.{base.slug})",
                       name=f"providers_{base.slug}")
        return _table_block(head, [l for _, l in cols], rows)

    if sort not in _PROV_SORT:
        raise ValueError(
            f"unknown sort {sort!r} — expected one of {', '.join(_PROV_SORT)}"
        )

    endpoints = loaders.provider_board(refresh=refresh)
    if host:
        hl = host.lower()
        endpoints = [e for e in endpoints if hl in (e.host or "").lower()]
    if min_context is not None:
        endpoints = [e for e in endpoints
                     if e.context_tokens is not None and e.context_tokens >= min_context]
    if open_weights is not None:
        ow = {m.slug: m.is_open_weights for m in loaders.leaderboard(refresh=refresh)}
        endpoints = [e for e in endpoints
                     if ow.get(e.model_slug) == open_weights]
    endpoints = _endpoint_sort(endpoints, sort)

    if not endpoints:
        sel = []
        if host:
            sel.append(f"host~{host}")
        if open_weights is not None:
            sel.append("open-weights" if open_weights else "closed-weights")
        if min_context is not None:
            sel.append(f"ctx>={min_context:g}")
        return f"# no provider endpoints match {', '.join(sel) or 'filters'} — drop one filter"

    cols = _cols(_PROV_COLS, fields, _PROV_EXTRA)
    rows = [[_endpoint_cell(e, k) for k, _ in cols] for e in endpoints[:n]]
    if host:
        note = f"endpoints · host~{host}, by {sort}"
    else:
        note = f"endpoints · cheapest {len(rows)} across all hosts, by {sort}"
    head = _header(len(endpoints), len(rows), note, name="providers_board", api=False)
    return _table_block(head, [l for _, l in cols], rows)


# --------------------------------------------------------------------------- #
# aa_media
# --------------------------------------------------------------------------- #

_SPEECH_BOARDS = {
    "speech_to_text": "stt",
    "speech_to_text_streaming": "stt_streaming",
    "speech_to_speech": "sts",
}
_MEDIA_COLS = [("rank", "Rank"), ("name", "Model"), ("creator", "Creator"),
               ("elo", "Elo"), ("appearances", "Appearances"),
               ("price", "Price"), ("release_date", "Release")]
_MEDIA_EXTRA = ("ci_lower", "ci_upper", "open_weights", "url", "price_unit", "price")


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
    if key == "release_date":
        return _txt(row.get("release_date"))
    return _txt(row.get(key))


def _media(board: str, top: int = 15, fields: str = "", open_weights: bool | None = None,
           refresh: bool = False) -> str:
    n = top if isinstance(top, int) and top > 0 else 15

    if board in _SPEECH_BOARDS:
        key = _SPEECH_BOARDS[board]
        rows = loaders.home_boards(refresh=refresh).get(key) or []
        if open_weights is not None:
            rows = [r for r in rows if r.get("openWeights") == open_weights]
        if not rows:
            return f"# no rows for speech board {board!r} in the homepage payload"
        if key == "sts":
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
        head = _header(len(rows), len(table_rows),
                       f"{board} · speech (WER lower is better)" if key != "sts"
                       else f"{board} · speech, STS index",
                       name="home", api=False)
        return _table_block(head, [l for _, l in cols], table_rows)

    if board not in loaders.MEDIA_BOARDS:
        valid = sorted(loaders.MEDIA_BOARDS) + sorted(_SPEECH_BOARDS)
        raise ValueError(
            f"unknown media board {board!r} — valid: {', '.join(valid)}"
        )
    rows = loaders.media(board, refresh=refresh)
    if open_weights is not None:
        rows = [r for r in rows if r.get("open_weights") == open_weights]
    if not rows:
        return f"# no rows on media board {board!r} (open_weights={open_weights})"

    if fields:
        cols = _cols(_MEDIA_COLS, fields, _MEDIA_EXTRA)
    else:
        cols = list(_MEDIA_COLS)
    table_rows = [[_media_cell(r, k) for k, _ in cols] for r in rows[:n]]
    head = _header(len(rows), len(table_rows), f"{board} · human-preference Elo",
                   name=f"media_{board}", api=False)
    return _table_block(head, [l for _, l in cols], table_rows)


# --------------------------------------------------------------------------- #
# aa_agents
# --------------------------------------------------------------------------- #

_AGENT_COLS = [("rank", "Rank"), ("agent", "Agent"), ("model", "Model"),
               ("creator", "Creator"), ("score", "Score"), ("cost_per_task", "$/Task")]


def _agents(board: str = "coding_agents", top: int = 15, refresh: bool = False) -> str:
    n = top if isinstance(top, int) and top > 0 else 15
    rows = loaders.agents(board, refresh=refresh)
    shown = rows[:n]
    table_rows = []
    for row in shown:
        table_rows.append([
            _txt(row.get("rank")),
            _txt(row.get("agent") or row.get("name")),
            _txt(row.get("model")),
            _txt(row.get("creator")),
            render.pct(row.get("score")),
            _fmt("cost_per_task", row.get("cost_per_task")),
        ])
    head = _header(len(rows), len(shown), f"agent rows · {board}",
                   name=f"agents_{board}", api=False)
    return _table_block(head, [l for _, l in _AGENT_COLS], table_rows)


# --------------------------------------------------------------------------- #
# aa_search
# --------------------------------------------------------------------------- #

_SEARCH_COLS = [("name", "Model"), ("creator", "Creator"), ("intelligence", "Intel"),
                ("cost_per_task", "$/Task"), ("slug", "Slug")]


def _search(query: str = "", creator: str = "", open_weights: bool | None = None,
            top: int = 15, refresh: bool = False) -> str:
    n = top if isinstance(top, int) and top > 0 else 15
    models = loaders.leaderboard(refresh=refresh)
    if query:
        found = select.search(models, query, limit=max(n, 20))
    else:
        found = select.sort_models(models, "intelligence")
    found = select.filter_models(
        found, creator=creator or None, open_weights=open_weights,
        exclude_deprecated=False,
    )
    shown = found[:n]
    if not shown:
        return (f"# no models match {query!r}"
                + (f" (creator~{creator})" if creator else "")
                + " — try a shorter substring or aa_reference topic=fields")
    cols = _cols(_SEARCH_COLS, "")
    rows = [[_fmt(k, select.lookup(m, k)) for k, _ in cols] for m in shown]
    cache_name, api = _lb_cache()
    note = f"models · name match {query!r}" if query else "models · most intelligent"
    head = _header(len(models), len(rows), note, name=cache_name, api=api)
    return _table_block(head, [l for _, l in cols], rows)


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
            f"unknown topic {topic!r} — topics: {', '.join(reference.TOPICS)}, all"
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
    return value


def _project(obj: Any, keys: Sequence[str]) -> Any:
    if not keys or not isinstance(obj, dict):
        return obj
    return {k: v for k, v in obj.items() if k in keys}


def _raw(kind: str, query: str = "", fields: str = "", top: int = 1,
         refresh: bool = False) -> str:
    if kind not in _RAW_KINDS:
        raise ValueError(f"unknown kind {kind!r} — valid: {', '.join(_RAW_KINDS)}")
    n = min(max(top if isinstance(top, int) else 1, 1), 5)
    keys = _split(fields)
    cache_name = ""
    api = False
    payload: Any

    if kind == "model":
        base = _resolve_slug(query, loaders.leaderboard(refresh=refresh))
        record = loaders.model(base.slug, refresh=refresh).get(base.slug)
        payload = _to_plain(record if record is not None else base)
        cache_name = f"model_{base.slug}"
    elif kind == "leaderboard":
        cache_name, api = _lb_cache()
        payload = [_project(_to_plain(m), keys) for m in loaders.leaderboard(refresh=refresh)[:n]]
    elif kind == "providers":
        base = _resolve_slug(query, loaders.leaderboard(refresh=refresh))
        cache_name = f"providers_{base.slug}"
        payload = [_project(_to_plain(e), keys)
                   for e in loaders.provider_endpoints(base.slug, refresh=refresh)[:n]]
    elif kind == "providers_board":
        cache_name = "providers_board"
        payload = [_project(_to_plain(e), keys)
                   for e in loaders.provider_board(refresh=refresh)[:n]]
    elif kind == "media":
        board = query or "text_to_image"
        if board not in loaders.MEDIA_BOARDS:
            raise ValueError(f"unknown media board {board!r} — "
                             f"valid: {', '.join(sorted(loaders.MEDIA_BOARDS))}")
        cache_name = f"media_{board}"
        payload = [_project(r, keys) for r in loaders.media(board, refresh=refresh)[:n]]
    elif kind == "agents":
        board = query or "coding_agents"
        cache_name = f"agents_{board}"
        payload = [_project(r, keys) for r in loaders.agents(board, refresh=refresh)[:n]]
    elif kind == "home":
        cache_name = "home"
        home = loaders.home_boards(refresh=refresh)
        payload = {k: [_project(r, keys) for r in v[:n]] for k, v in home.items()}
    elif kind == "eval":
        slug = query or "gpqa-diamond"
        cache_name = f"eval_{slug}"
        payload = [_project(_to_plain(m), keys)
                   for m in loaders.eval_models(slug, refresh=refresh)[:n]]
    else:  # catalog
        cache_name = "eval_catalog"
        payload = [_project(c, keys) for c in loaders.eval_catalog(refresh=refresh)]

    head = _header(None, n, f"raw {kind} · top {n} · JSON, token-expensive — prefer "
                            "the table tools", name=cache_name, api=api)
    body = json.dumps(payload, indent=1, default=str)
    return f"{head}\n{body}"


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
    """Rank and filter the ~700 tracked model variants — the default starting point.

    Answers "which model is smartest / cheapest / fastest / best value right now".
    Returns a compact markdown table sorted by ``sort`` (default: intelligence).

    Args:
        mode: "rank" (default), "value" (intelligence per $/task), or "frontier"
            (Pareto intelligence-vs-cost; the footnote gives the knee).
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
def aa_model(query: str, sections: str = "", refresh: bool = False) -> str:
    """One model's full digest: specs, indices, benchmark scores, pricing and speed.

    Use after aa_leaderboard/aa_search when you need everything about a single
    model. The header and footnote always carry the round-trippable slug.

    Args:
        query: model name or slug (fuzzy). Ambiguous names return a candidate table.
        sections: comma subset of identity, indexes, benchmarks, pricing, speed,
            cost, openness, modalities, all. Default identity, indexes,
            benchmarks, pricing, speed.
        refresh: bypass the cache and re-fetch.
    """
    return _model(query, sections=sections, refresh=refresh)


@srv.tool(name="aa_compare", title="Compare models", structured_output=False)
@_tool
def aa_compare(queries: list[str], metrics: str = "", compact: bool = True,
               refresh: bool = False) -> str:
    """Side-by-side comparison of 2-6 models as metric rows x model columns.

    Args:
        queries: 2-6 model names or slugs.
        metrics: comma list of metric rows to show; empty uses the default set
            (intelligence, $/task, in/out $/1M, tok/s, TTFT, context, ...).
        compact: when true (and no metrics given) keep only the 6 rows that matter.
        refresh: bypass the cache and re-fetch.
    """
    return _compare(queries, metrics=metrics, compact=compact, refresh=refresh)


@srv.tool(name="aa_benchmarks", title="Benchmark catalog", structured_output=False)
@_tool
def aa_benchmarks(query: str = "", verbose: bool = False) -> str:
    """Catalog of AA benchmarks: slug, unit, live coverage and what each measures.

    Use to discover what exists and how many of the tracked models have a score.

    Args:
        query: optional substring filter over benchmark key/label/tags.
        verbose: also show index membership, tags and the full description.
    """
    return _benchmarks(query=query, verbose=verbose)


@srv.tool(name="aa_benchmark_leaderboard", title="Benchmark leaderboard",
          structured_output=False)
@_tool
def aa_benchmark_leaderboard(
    benchmark: str,
    top: int = 15,
    fields: str = "",
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
        include_estimates: include AA-estimated scores (default True; estimates are
            marked with *).
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
                 sort: str = "cost_per_task", fields: str = "",
                 open_weights: bool | None = None, min_context: int | None = None,
                 refresh: bool = False) -> str:
    """Provider endpoints: per-host pricing, precision, speed and feature flags.

    Pass ``model`` for one model's serving endpoints (with per-endpoint $/task and
    precision), or ``host``/filters for the 1,200-row provider board. With neither,
    returns the cheapest endpoints globally.

    Args:
        model: model name or slug — switches to per-model endpoint detail.
        host: substring match on the serving host (e.g. "groq").
        top: rows to return (default 15).
        sort: cost_per_task (default), price_in, price_out, tps, ttft,
            intelligence or context_tokens. Lower-is-better keys sort ascending.
        fields: comma list of columns; supports precision, cache_read, discount,
            e2e, function_calling, json_mode, context_tokens.
        open_weights: keep only endpoints for open- or closed-weights models.
        min_context: drop endpoints with a smaller context window (tokens).
        refresh: bypass the cache and re-fetch.
    """
    return _providers(model=model, host=host, top=top, sort=sort, fields=fields,
                      open_weights=open_weights, min_context=min_context,
                      refresh=refresh)


@srv.tool(name="aa_media", title="Media leaderboards", structured_output=False)
@_tool
def aa_media(board: str, top: int = 15, fields: str = "",
             open_weights: bool | None = None, refresh: bool = False) -> str:
    """Human-preference arenas: image, video, speech, music (Elo + 95% CI).

    Args:
        board: any image/video/TTS/music board key (text_to_image, image_editing,
            text_to_video, image_to_video, video_editing, text_to_speech,
            text_to_speech_controlled, music_instrumental, music_with_vocals) or a
            speech board (speech_to_text, speech_to_text_streaming,
            speech_to_speech).
        top: rows to return (default 15).
        fields: comma list of columns; supports ci_lower, ci_upper, open_weights.
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

    Always returns the slug so the next tool call can be exact.

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
def aa_raw(kind: str, query: str = "", fields: str = "", top: int = 1,
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


@srv.resource("aa://reference/fields", name="Field aliases",
              mime_type="text/plain",
              description="Every field alias accepted by fields=/metrics=/sort=.")
def _r_fields() -> str:
    return "\n".join(catalog.field_names())


@srv.resource("aa://benchmarks", name="Benchmark catalog", mime_type="application/json",
              description="The full benchmark registry as JSON.")
def _r_benchmarks() -> str:
    data = [_to_plain(b) for b in catalog.BENCHMARKS.values()]
    return json.dumps(data, indent=1, default=str)


@srv.resource("aa://sources", name="Data sources & cache", mime_type="text/markdown",
              description="URLs, cache paths, TTLs, offline mode and recovery.")
def _r_sources() -> str:
    return reference.TOPICS["sources"]


# --------------------------------------------------------------------------- #
# prompts
# --------------------------------------------------------------------------- #


@srv.prompt(name="best_model_for_task",
            description="Pick the best model for a task and budget.")
def best_model_for_task(task: str, budget: str = "", open_weights: str = "") -> str:
    """Recommend the best model for a task, with alternates and the cost knee."""
    lines = [
        "Pick the best model for the task below using the aa-mcp tools, then answer "
        "with a recommendation, 2 alternates and the knee of the intelligence-vs-cost "
        "curve. Never recompute cost_per_task — it is already cache-aware.",
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
        "2. Call aa_leaderboard with filters that encode the task (e.g. "
        "max_cost_per_task for a budget, sort=intelligence; use mode=value for best "
        "value or mode=frontier for the cost/intelligence frontier).",
        "3. Optionally aa_model on the top pick for specs (context, license, "
        "modalities, knowledge cutoff).",
        "4. Answer with: one recommendation and why, two alternates, and the knee "
        "point (name, $/task, intelligence) plus the trade-off.",
    ]
    return "\n".join(lines)


@srv.prompt(name="compare_models", description="Compare specific models side by side.")
def compare_models(models: str) -> str:
    """Compare the named models, adding provider detail when price matters."""
    return "\n".join([
        f"Compare these models: {models}",
        "",
        "Steps:",
        f"1. Call aa_compare with the models ({models}) — resolve names via aa_search "
        "if unsure.",
        "2. If price or provider choice matters, call aa_providers for the winner "
        "(per-endpoint $/1M, precision, TTFT).",
        "3. Report a compact comparison table plus a one-line verdict and the key "
        "trade-off. Do not recompute cost_per_task.",
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
