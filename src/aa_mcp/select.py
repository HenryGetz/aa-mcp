"""Filter / sort / rank / resolve operations over :class:`normalize.Model`."""

from __future__ import annotations

import math
from dataclasses import replace

from . import catalog
from .catalog import VALUE_SOURCE
from .normalize import Model

__all__ = [
    "AmbiguousError",
    "better_desc",
    "filter_models",
    "pareto",
    "resolve",
    "search",
    "sort_models",
    "value_pairs",
    "value_rank",
]


class AmbiguousError(LookupError):
    """Raised when a query matches more than one model."""

    def __init__(self, message: str, candidates: list[Model] | None = None):
        super().__init__(message)
        self.candidates = candidates or []


def _norm(text: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]", "", text.lower())


def _tokens(text: str) -> list[str]:
    """Whitespace/punctuation-separated, lowercased alphanumeric tokens."""
    import re

    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if t]


def _token_score(token: str, fields: list[str]) -> int:
    if any(f == token for f in fields):
        return 90
    if any(f.startswith(token) for f in fields):
        return 70
    if any(token in f for f in fields):
        return 50
    return 0


def lookup(model: Model, key: str):
    """Return the value of metric ``key`` for ``model`` (``None`` if absent)."""
    src = VALUE_SOURCE.get(key)
    if src:
        container, sub = src
        d = getattr(model, container, None)
        return d.get(sub) if isinstance(d, dict) else None
    if hasattr(model, key):
        return getattr(model, key)
    for name in ("evals", "indices", "pricing", "speed"):
        d = getattr(model, name)
        if key in d:
            return d[key]
    return None


def better_desc(key: str) -> bool:
    """Whether higher is better for ``key`` (unknown metrics: higher).

    Rank lower-is-better evaluations (hallucination/refusal rates, cost, TTFT)
    the right way round: ``pairs.sort(key=…, reverse=better_desc(key))``.
    """
    m = catalog.metric(key)
    return not (m is not None and m.better == "low")


def _finite(value, name: str):
    """Reject ``NaN``/``inf`` filters: they compare False and silently no-op."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return value


# --------------------------------------------------------------------------- #
# filter / sort
# --------------------------------------------------------------------------- #

def filter_models(
    models,
    *,
    creator=None,
    name=None,
    open_weights=None,
    reasoning=None,
    min_intelligence=None,
    max_cost_per_task=None,
    min_speed=None,
    max_ttft=None,
    min_context=None,
    released_after=None,
    exclude_deprecated=True,
    min_score=None,
    score_key=None,
) -> list[Model]:
    numeric = {
        key: _finite(value, key)
        for key, value in (
            ("min_intelligence", min_intelligence),
            ("max_cost_per_task", max_cost_per_task),
            ("min_speed", min_speed),
            ("max_ttft", max_ttft),
            ("min_context", min_context),
            ("min_score", min_score),
        )
    }
    min_intelligence = numeric["min_intelligence"]
    max_cost_per_task = numeric["max_cost_per_task"]
    min_speed = numeric["min_speed"]
    max_ttft = numeric["max_ttft"]
    min_context = numeric["min_context"]
    min_score = numeric["min_score"]
    cn = _norm(creator) if creator else None
    name_tokens = _tokens(name) if name else None
    # A ``name`` that carries no alphanumeric token (CJK, emoji, punctuation,
    # whitespace) can never match a model: treat it as "matches nothing" rather
    # than letting an empty token list silently disable the filter and return the
    # whole dataset while the header still claims ``name~…`` (audit round 2, M1).
    name_unmatchable = bool(name) and not name_tokens
    out: list[Model] = []
    for m in models:
        if exclude_deprecated and m.deprecated:
            continue
        if cn and not (
            (m.creator and cn in _norm(m.creator))
            or (m.creator_slug and cn in _norm(m.creator_slug))
        ):
            continue
        if name_unmatchable or (name_tokens and not all(
            any(t in f for f in (_norm(m.slug), _norm(m.name), _norm(m.short_name)))
            for t in name_tokens
        )):
            continue
        if open_weights is not None and m.is_open_weights != open_weights:
            continue
        if reasoning is not None and m.is_reasoning != reasoning:
            continue
        if min_intelligence is not None and (
            m.intelligence is None or m.intelligence < min_intelligence
        ):
            continue
        if max_cost_per_task is not None and (
            m.cost_per_task is None or m.cost_per_task > max_cost_per_task
        ):
            continue
        if min_speed is not None:
            v = m.speed.get("tps")
            if v is None or v < min_speed:
                continue
        if max_ttft is not None:
            v = m.speed.get("ttft")
            if v is None or v > max_ttft:
                continue
        if min_context is not None and (
            m.context_tokens is None or m.context_tokens < min_context
        ):
            continue
        if released_after and (not m.release_date or m.release_date < released_after):
            continue
        if min_score is not None:
            v = lookup(m, score_key or "intelligence")
            if v is None or v < min_score:
                continue
        out.append(m)
    return out


def sort_models(models, key: str, *, desc: bool | None = None) -> list[Model]:
    """Sort by a metric key/alias or any ``Model`` attribute name.

    ``None`` values always sort last, regardless of direction. When ``desc`` is
    omitted it follows the metric's ``better`` hint (high -> descending,
    low -> ascending, via :func:`better_desc`).
    """
    if desc is None:
        desc = better_desc(key)

    present: list[tuple] = []
    missing: list[Model] = []
    for m in models:
        v = lookup(m, key)
        if v is None:
            missing.append(m)
        else:
            present.append((v, m))
    present.sort(key=lambda t: t[0], reverse=desc)
    return [m for _, m in present] + missing


# --------------------------------------------------------------------------- #
# value / frontier
# --------------------------------------------------------------------------- #

def value_pairs(
    models,
    *,
    score_key: str = "intelligence",
    cost_key: str = "cost_per_task",
) -> list[tuple[Model, float]]:
    """``[(model, score / cost)]`` for every model where that ratio is meaningful.

    Functional and non-mutating: the models passed in are never touched, so two
    calls with the same arguments return the same pairs no matter what else ran
    in between (``Model`` objects are memoized and shared across tool calls).
    """
    pairs: list[tuple[Model, float]] = []
    for m in models:
        score = lookup(m, score_key)
        cost = lookup(m, cost_key)
        if score is None or cost is None or cost <= 0:
            continue
        pairs.append((m, score / cost))
    return pairs


def value_rank(
    models,
    *,
    score_key: str = "intelligence",
    cost_key: str = "cost_per_task",
) -> list[Model]:
    """Copies of ``models`` with ``.value`` set to ``score / cost_per_task``.

    Callers must not rely on mutation: the returned list holds *new* objects
    (:func:`dataclasses.replace`) and the inputs keep ``value`` untouched, so the
    frontier "knee" cannot be reordered by a previous call (audit H3).
    **Deprecated** in favour of :func:`value_pairs` for new code.
    """
    scores = {id(m): value for m, value in value_pairs(models, score_key=score_key, cost_key=cost_key)}
    return [replace(m, value=scores.get(id(m))) for m in models]


def pareto(
    models,
    *,
    score_key: str = "intelligence",
    cost_key: str = "cost_per_task",
) -> list[Model]:
    """Return the cost-ascending non-dominated ``(cost, score)`` frontier."""
    points = []
    for m in models:
        cost = lookup(m, cost_key)
        score = lookup(m, score_key)
        if cost is None or score is None:
            continue
        points.append((cost, score, m))
    points.sort(key=lambda t: (t[0], -t[1]))
    frontier: list[Model] = []
    best: float | None = None
    for _cost, score, m in points:
        if best is None or score > best:
            frontier.append(m)
            best = score
    return frontier


# --------------------------------------------------------------------------- #
# search / resolve
# --------------------------------------------------------------------------- #

def _fields(m: Model) -> list[str]:
    return [_norm(m.slug), _norm(m.name), _norm(m.short_name), _norm(m.creator or "")]


def search(models, query: str, limit: int = 20) -> list[Model]:
    """Fuzzy name/slug search, ranked by match quality then intelligence.

    The query is tokenised on whitespace/punctuation and **every** token must
    appear (as a substring) in the model's normalized slug/name/short_name/creator
    — in any order.  Single-token queries behave exactly as before.
    """
    tokens = _tokens(query)
    if not tokens:
        return []
    nq = _norm(query)
    scored = []
    for m in models:
        f = _fields(m)
        if nq == f[0]:
            score = 100
        elif nq in (f[1], f[2]):
            score = 90
        else:
            token_scores = [_token_score(t, f) for t in tokens]
            if not all(token_scores):
                continue
            score = min(token_scores)
        scored.append((score, m.intelligence if m.intelligence is not None else -1.0, m))
    scored.sort(key=lambda t: (-t[0], -t[1]))
    return [m for _, _, m in scored[:limit]]


def _by_intel(models) -> list[Model]:
    return sorted(
        models,
        key=lambda m: m.intelligence if m.intelligence is not None else -1.0,
        reverse=True,
    )


def resolve(models, query: str) -> Model:
    """Resolve a user query to exactly one model.

    Order: exact slug, exact normalized short name / name, unique substring
    match. More than one candidate at any stage raises :class:`AmbiguousError`
    with up to 8 intelligence-sorted candidates.
    """
    nq = _norm(query)
    if not nq:
        raise ValueError("empty model query")

    pool = list(models)

    exact_slug = [m for m in pool if _norm(m.slug) == nq]
    if exact_slug:
        if len(exact_slug) == 1:
            return exact_slug[0]
        raise AmbiguousError(
            f"multiple models match slug {query!r}", _by_intel(exact_slug)[:8]
        )

    exact_name = [m for m in pool if _norm(m.short_name) == nq or _norm(m.name) == nq]
    if exact_name:
        if len(exact_name) == 1:
            return exact_name[0]
        raise AmbiguousError(
            f"multiple models match name {query!r}", _by_intel(exact_name)[:8]
        )

    subs = [
        m
        for m in pool
        if nq in _norm(m.slug) or nq in _norm(m.short_name) or nq in _norm(m.name)
    ]
    if len(subs) == 1:
        return subs[0]
    if not subs:
        raise LookupError(f"no model matches {query!r}")
    raise AmbiguousError(
        f"{len(subs)} models match {query!r}", _by_intel(subs)[:8]
    )
