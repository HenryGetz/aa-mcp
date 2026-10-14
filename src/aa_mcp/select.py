"""Filter / sort / rank / resolve operations over :class:`normalize.Model`."""

from __future__ import annotations

from . import catalog
from .catalog import VALUE_SOURCE
from .normalize import Model

__all__ = [
    "filter_models",
    "sort_models",
    "value_rank",
    "pareto",
    "search",
    "resolve",
    "AmbiguousError",
]


class AmbiguousError(LookupError):
    """Raised when a query matches more than one model."""

    def __init__(self, message: str, candidates: list[Model] | None = None):
        super().__init__(message)
        self.candidates = candidates or []


def _norm(text: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]", "", text.lower())


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
    cn = _norm(creator) if creator else None
    nn = _norm(name) if name else None
    out: list[Model] = []
    for m in models:
        if exclude_deprecated and m.deprecated:
            continue
        if cn and not (
            (m.creator and cn in _norm(m.creator))
            or (m.creator_slug and cn in _norm(m.creator_slug))
        ):
            continue
        if nn and not (
            nn in _norm(m.slug) or nn in _norm(m.name) or nn in _norm(m.short_name)
        ):
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
    low -> ascending).
    """
    if desc is None:
        m = catalog.metric(key)
        desc = not (m is not None and m.better == "low")

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

def value_rank(models, *, score_key: str = "intelligence") -> list[Model]:
    """Populate ``model.value`` with ``score / cost_per_task`` where meaningful."""
    out = []
    for m in models:
        score = lookup(m, score_key)
        cost = m.cost_per_task
        if score is not None and cost is not None and cost > 0:
            m.value = score / cost
        else:
            m.value = None
        out.append(m)
    return out


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
    """Fuzzy name/slug search, ranked by match quality then intelligence."""
    nq = _norm(query)
    if not nq:
        return []
    scored = []
    for m in models:
        f = _fields(m)
        if nq == f[0]:
            score = 100
        elif nq in (f[1], f[2]):
            score = 90
        elif any(x.startswith(nq) for x in f if x):
            score = 70
        elif any(nq in x for x in f if x):
            score = 50
        else:
            continue
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
