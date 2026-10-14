"""Convert raw AA payload records into the canonical :class:`Model` record.

Three source shapes are supported:

* ``from_leaderboard`` — the 50-key rows in the ``/leaderboards/models`` array.
  Here ``intelligenceIndexCostPerTask`` is a **plain float**.
* ``from_chart`` — the 92-key model-page / eval-page chart records. Here
  ``intelligenceIndexCostPerTask`` is a **dict** ``{"cost": {...},
  "evaluations": [...]}`` and extra capability / briefcase fields exist.
* ``from_legacy`` — the ``currentModel`` object on legacy/deprecated model pages.

Eval values in :attr:`Model.evals` are stored **raw**: percentages stay as
fractions (0-1) and Elo values are **not** divided by 100. The formatting layer
(:func:`catalog.format_value`) scales fractions to ``%``. This is deliberate and
must not change.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

__all__ = ["Model", "from_chart", "from_leaderboard", "from_legacy", "merge"]


@dataclass(slots=True)
class Model:
    slug: str
    name: str
    short_name: str
    creator: str | None
    creator_slug: str | None
    release_date: str | None
    deprecated: bool
    deprecated_to: str | None
    is_reasoning: bool
    is_open_weights: bool
    effort: str | None
    params_b: float | None
    active_params_b: float | None
    context_tokens: int | None
    license: str | None
    license_url: str | None
    weights_url: str | None
    knowledge_cutoff: str | None
    size_class: str | None
    modalities_in: tuple[str, ...]
    modalities_out: tuple[str, ...]
    intelligence: float | None
    estimated: bool
    indices: dict[str, float | None]
    evals: dict[str, float | None]
    pricing: dict[str, float | None]
    speed: dict[str, float | None]
    cost_per_task: float | None
    cost_breakdown: dict[str, float] | None
    per_eval_cost: list[dict] | None
    source: str
    value: float | None = None
    per_eval: list[dict] | None = None


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _int(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    return None


def _get(rec, *keys):
    for k in keys:
        v = rec.get(k)
        if v is not None:
            return v
    return None


def _modalities(rec, kind: str) -> tuple[str, ...]:
    # payload keys are inputModalityText / outputModalityText (lowercase prefix)
    prefix = kind
    out = []
    for suffix, label in (("Text", "text"), ("Image", "image"),
                          ("Speech", "speech"), ("Video", "video")):
        if rec.get(f"{prefix}Modality{suffix}"):
            out.append(label)
    return tuple(out)


def _evals(rec, keys, aliases: dict[str, str] | None = None) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for k in keys:
        v = _num(rec.get(k))
        if v is not None:
            out[aliases.get(k, k) if aliases else k] = v
    return out


def _briefcase_elo(rec) -> float | None:
    """AA-Briefcase Elo in any of its three payload shapes.

    ``briefcaseElo`` (direct), ``briefcaseBreakdown.elo`` (flat) and
    ``briefcaseBreakdown.overall.elo`` (nested, model-page chart).
    """
    direct = _num(rec.get("briefcaseElo"))
    if direct is not None:
        return direct
    breakdown = rec.get("briefcaseBreakdown")
    if isinstance(breakdown, dict):
        flat = _num(breakdown.get("elo"))
        if flat is not None:
            return flat
        overall = breakdown.get("overall")
        if isinstance(overall, dict):
            return _num(overall.get("elo"))
    return None


def _creator(rec) -> tuple[str | None, str | None]:
    c = rec.get("creator")
    if isinstance(c, dict):
        return c.get("name"), c.get("slug")
    name = rec.get("modelCreatorName")
    return name, None


def _release(rec) -> tuple[str | None, str | None]:
    r = rec.get("release")
    if isinstance(r, dict):
        return r.get("name"), r.get("deprecatedTo")
    return None, None


_LEADER_EVAL_KEYS = (
    "omniscienceAccuracy", "omniscienceNonHallucination", "gdpvalNormalized",
    "analystAgent", "terminalbenchHard", "terminalBench21", "terminalBench40",
    "tau2", "tauBanking", "lcr", "hle", "gpqa", "scicode", "ifbench", "critpt",
    "apexAgents", "itbenchSre", "mmmuPro",
)

_CHART_EVAL_KEYS = (
    "omniscienceAccuracy", "omniscienceHallucinationRate", "mlcrOverall",
    "mlcrAccuracy", "mlcrCompleteness", "mlcrConciseness",
    "harveyLab", "gdpPdfAllPass", "gdpval", "gdpvalNormalized", "itBenchSre",
    "itbenchSre", "tau2", "tauBanking", "terminalbenchHard", "terminalBench21",
    "terminalBench40", "frontierCode", "terminalBenchScience", "hleDiamond",
    "scicode", "lcr", "ifbench", "hle", "gpqa", "critpt", "apexAgents",
    "mmmuPro", "livecodebench", "aime25", "analystAgent",
    "analystAgentPassAt1", "analystAgentPassAtK",
    "automationBenchPartialScore", "when2call", "wildguardtest",
    "briefcaseElo",
    # audit 2026-10-14: catalogued benchmarks that appear as flat scalars on
    # chart/eval records but were previously unreachable via Model.evals.
    "enterpriseOpsGym", "enterpriseOpsGymSuccessRateByDomain",
    "cweBench", "cybergymE2e", "deepsecBench", "cyberIndex",
    "cweBenchRefusalRate", "cybergymE2eRefusalRate", "deepsecBenchRefusalRate",
    "globalMmluLiteScore", "mmluPro", "math500", "aa3dElo",
)

# Payload key spellings that differ from the canonical catalog key.
_CHART_KEY_ALIASES = {"itBenchSre": "itbenchSre"}

_LEGACY_EVAL_KEYS = (
    "omniscienceAccuracy", "omniscienceHallucinationRate", "gdpval",
    "itBenchSre", "itbenchSre", "tau2", "tauBanking", "terminalbenchHard",
    "terminalBench21", "terminalBench40", "frontierCode",
    "terminalBenchScience", "hleDiamond", "scicode", "lcr", "ifbench", "hle",
    "gpqa", "critpt", "apexAgents", "mmmuPro", "livecodebench", "aime25",
    "analystAgent", "briefcaseElo",
)

_CAPABILITIES = (
    "financeAndAccounting", "strategyAndOps", "legal",
    "healthcareAndMedical", "engineering", "economics",
)


def _capability_indices(rec) -> dict[str, float | None]:
    caps = rec.get("capabilities")
    out: dict[str, float | None] = {}
    if isinstance(caps, dict):
        for k, v in caps.items():
            out[f"capabilities.{k}"] = _num(v)
    return out


def _pricing(rec) -> dict[str, float | None]:
    return {
        "in": _num(rec.get("price1mInputTokens")),
        "out": _num(rec.get("price1mOutputTokens")),
        "cache_read": _num(rec.get("cacheHitPrice")),
        "cache_write": _num(rec.get("cacheWritePrice")),
        "cache_hit_discount": _num(rec.get("cacheHitDiscountPercent")),
        "blended_0_3_1": _num(rec.get("price1mBlended0To3To1")),
        "blended_7_2_1": _num(rec.get("price1mBlended7To2To1")),
        "blended_0_1_1": _num(rec.get("price1mBlended0To1To1")),
        "blended_100_1_1": _num(rec.get("price1mBlended100To1To1")),
        "blended_0_100_1": _num(rec.get("price1mBlended0To100To1")),
    }


# --------------------------------------------------------------------------- #
# constructors
# --------------------------------------------------------------------------- #

def from_leaderboard(rec: dict) -> Model:
    """Build a :class:`Model` from a ``/leaderboards/models`` row."""
    if not isinstance(rec, dict):
        raise TypeError(f"from_leaderboard expects a mapping, got {type(rec).__name__}")
    slug = rec.get("slug") or ""
    name = rec.get("name") or slug
    creator, creator_slug = _creator(rec)
    return Model(
        slug=slug,
        name=name,
        short_name=rec.get("shortName") or name,
        creator=creator,
        creator_slug=creator_slug,
        release_date=rec.get("releaseDate"),
        deprecated=bool(rec.get("deprecated")),
        deprecated_to=None,
        is_reasoning=bool(rec.get("isReasoning")),
        is_open_weights=bool(rec.get("isOpenWeights")),
        effort=None,
        params_b=None,
        active_params_b=None,
        context_tokens=_int(rec.get("contextWindowTokens")),
        license=None,
        license_url=None,
        weights_url=None,
        knowledge_cutoff=None,
        size_class=rec.get("paramClass") or rec.get("sizeClass"),
        modalities_in=(),
        modalities_out=(),
        intelligence=_num(rec.get("intelligenceIndex")),
        estimated=bool(rec.get("intelligenceIndexIsEstimated")),
        indices={"omniscience": _num(rec.get("omniscience"))},
        evals=_evals(rec, _LEADER_EVAL_KEYS),
        pricing=_pricing(rec),
        speed={
            "tps": _num(rec.get("medianOutputTokensPerSecond")),
            "ttft": _num(rec.get("medianTimeToFirstTokenSeconds")),
            "ttfa": _num(rec.get("medianTimeToFirstAnswerTokenSeconds")),
            "e2e": _num(rec.get("medianEndToEndResponseTimeSeconds")),
            "reasoning_s": _num(rec.get("medianReasoningTimeSeconds")),
            "out_tokens_per_task": None,
            "tps_p05": _num(rec.get("percentile05OutputTokensPerSecond")),
            "tps_q25": _num(rec.get("quartile25OutputTokensPerSecond")),
            "tps_q75": _num(rec.get("quartile75OutputTokensPerSecond")),
            "tps_p95": _num(rec.get("percentile95OutputTokensPerSecond")),
            "ttft_p05": _num(rec.get("percentile05TimeToFirstTokenSeconds")),
            "ttft_q25": _num(rec.get("quartile25TimeToFirstTokenSeconds")),
            "ttft_q75": _num(rec.get("quartile75TimeToFirstTokenSeconds")),
            "ttft_p95": _num(rec.get("percentile95TimeToFirstTokenSeconds")),
        },
        cost_per_task=_num(rec.get("intelligenceIndexCostPerTask")),
        cost_breakdown=None,
        per_eval_cost=None,
        source="leaderboard",
    )


_PER_EVAL_FIELDS = ("score", "outputTokensPerTask", "costPerTask", "timePerTask")


def _per_eval(rec) -> list[dict] | None:
    """Per-evaluation Intelligence Index rows from ``intelligenceIndexEvaluations``."""
    rows = rec.get("intelligenceIndexEvaluations")
    if not isinstance(rows, list):
        return None
    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("slug"):
            continue
        entry = {"slug": row.get("slug")}
        for key in _PER_EVAL_FIELDS:
            entry[key] = _num(row.get(key))
        out.append(entry)
    return out or None


def _cost_fields(rec):
    """Return ``(cost_per_task, cost_breakdown, per_eval_cost)`` from a chart row."""
    cb = rec.get("intelligenceIndexCostPerTask")
    total = None
    breakdown = None
    per_eval = None
    if isinstance(cb, dict):
        cost = cb.get("cost")
        if isinstance(cost, dict):
            total = _num(cost.get("total"))
            breakdown = {k: _num(v) for k, v in cost.items() if _num(v) is not None}
            breakdown = breakdown or None
        evals = cb.get("evaluations")
        if isinstance(evals, list):
            per_eval = [
                {"slug": e.get("slug"), "weighted_cost_per_task": _num(e.get("weightedCostPerTask"))}
                for e in evals
                if isinstance(e, dict) and e.get("slug")
            ] or None
    index_cost = rec.get("intelligenceIndexCost")
    index_total = _num(index_cost.get("total")) if isinstance(index_cost, dict) else _num(index_cost)
    if index_total is not None:
        breakdown = breakdown or {}
        breakdown["index_total"] = index_total
    briefcase_total = _num(rec.get("briefcaseTotalCost"))
    if briefcase_total is not None:
        breakdown = breakdown or {}
        breakdown["briefcase_total"] = briefcase_total
    return total, breakdown, per_eval


def _speed_chart(rec) -> dict[str, float | None]:
    ts = rec.get("timescaleData") or {}
    e2e = rec.get("endToEndResponseTime") or {}
    ttfa = rec.get("timeToFirstAnswerToken") or {}
    out_tokens = rec.get("intelligenceIndexOutputTokensPerTask")
    out_val = _num(out_tokens.get("output")) if isinstance(out_tokens, dict) else None
    return {
        "tps": _num(ts.get("medianOutputSpeed")),
        "ttft": _num(ts.get("medianTimeToFirstChunk")),
        "ttfa": _num(ttfa.get("total")),
        "e2e": _num(e2e.get("total")),
        "reasoning_s": _num(e2e.get("reasoning")),
        "out_tokens_per_task": out_val,
        "reasoning_tokens": _num(rec.get("reasoningTokens")),
    }


def from_chart(rec: dict) -> Model:
    """Build a :class:`Model` from a model-page / eval-page chart record."""
    if not isinstance(rec, dict):
        raise TypeError(f"from_chart expects a mapping, got {type(rec).__name__}")
    slug = rec.get("slug") or ""
    name = rec.get("name") or slug
    creator, creator_slug = _creator(rec)
    _, deprecated_to = _release(rec)
    effort = rec.get("effort")
    effort_label = effort.get("label") if isinstance(effort, dict) else None

    evals = _evals(rec, _CHART_EVAL_KEYS, _CHART_KEY_ALIASES)
    briefcase_elo = _briefcase_elo(rec)
    if briefcase_elo is not None:
        evals["briefcaseElo"] = briefcase_elo

    indices = {"omniscience": _num(rec.get("omniscience"))}
    openness = rec.get("openness")
    if isinstance(openness, dict):
        indices["openness"] = _num(openness.get("opennessIndex"))
    indices.update(_capability_indices(rec))

    total, breakdown, per_eval = _cost_fields(rec)
    return Model(
        slug=slug,
        name=name,
        short_name=rec.get("shortName") or name,
        creator=creator,
        creator_slug=creator_slug,
        release_date=rec.get("releaseDate"),
        deprecated=bool(rec.get("deprecated")),
        deprecated_to=deprecated_to,
        is_reasoning=bool(rec.get("isReasoning")),
        is_open_weights=bool(rec.get("isOpenWeights")),
        effort=effort_label,
        params_b=_num(rec.get("parameters")),
        active_params_b=_num(rec.get("inferenceParametersActiveBillions")),
        context_tokens=_int(rec.get("contextWindowTokens")),
        license=rec.get("licenseName"),
        license_url=rec.get("licenseUrl"),
        weights_url=rec.get("modelWeightsSourceUrl"),
        knowledge_cutoff=rec.get("knowledgeCutoffDate"),
        size_class=rec.get("sizeClass") or rec.get("openSourceCategorization"),
        modalities_in=_modalities(rec, "input"),
        modalities_out=_modalities(rec, "output"),
        intelligence=_num(rec.get("intelligenceIndex")),
        estimated=bool(rec.get("intelligenceIndexIsEstimated")),
        indices=indices,
        evals=evals,
        pricing=_pricing(rec),
        speed=_speed_chart(rec),
        cost_per_task=total,
        cost_breakdown=breakdown,
        per_eval_cost=per_eval,
        per_eval=_per_eval(rec),
        source="chart",
    )


def from_legacy(rec: dict) -> Model:
    """Build a :class:`Model` from a legacy ``currentModel`` object."""
    if not isinstance(rec, dict):
        raise TypeError(f"from_legacy expects a mapping, got {type(rec).__name__}")
    slug = rec.get("slug") or ""
    name = rec.get("name") or slug
    creator, creator_slug = _creator(rec)
    _, deprecated_to = _release(rec)

    evals = _evals(rec, _LEGACY_EVAL_KEYS, _CHART_KEY_ALIASES)
    briefcase_elo = _briefcase_elo(rec)
    if briefcase_elo is not None:
        evals["briefcaseElo"] = briefcase_elo

    openness = rec.get("openness")
    indices = {"omniscience": _num(rec.get("omniscience"))}
    if isinstance(openness, dict):
        indices["openness"] = _num(openness.get("opennessIndex"))
    indices.update(_capability_indices(rec))

    return Model(
        slug=slug,
        name=name,
        short_name=rec.get("shortName") or name,
        creator=creator,
        creator_slug=creator_slug,
        release_date=rec.get("releaseDate"),
        deprecated=bool(rec.get("deprecated")),
        deprecated_to=deprecated_to,
        is_reasoning=bool(rec.get("isReasoning")),
        is_open_weights=bool(rec.get("isOpenWeights")),
        effort=None,
        params_b=_num(rec.get("parameters")),
        active_params_b=_num(rec.get("inferenceParametersActiveBillions")),
        context_tokens=_int(rec.get("contextWindowTokens")),
        license=rec.get("licenseName"),
        license_url=rec.get("licenseUrl"),
        weights_url=rec.get("modelWeightsSourceUrl"),
        knowledge_cutoff=rec.get("knowledgeCutoffDate"),
        size_class=rec.get("sizeClass") or rec.get("openSourceCategorization"),
        modalities_in=_modalities(rec, "input"),
        modalities_out=_modalities(rec, "output"),
        intelligence=_num(rec.get("intelligenceIndex")),
        estimated=bool(rec.get("intelligenceIndexIsEstimated")),
        indices=indices,
        evals=evals,
        pricing=_pricing(rec),
        speed=_speed_chart(rec),
        cost_per_task=None,
        cost_breakdown=None,
        per_eval_cost=None,
        source="legacy",
    )


# --------------------------------------------------------------------------- #
# merge
# --------------------------------------------------------------------------- #

_DICT_FIELDS = {"indices", "evals", "pricing", "speed"}


def merge(*models: Model) -> Model:
    """Merge models left-to-right; later non-None values win.

    Dict fields (evals/indices/pricing/speed) are unioned, with later non-None
    values overriding earlier ones. ``source`` is taken from the last model.
    """
    present = [m for m in models if m is not None]
    if not present:
        raise ValueError("merge() requires at least one Model")
    if len(present) == 1:
        return present[0]

    values: dict = {}
    for f in fields(Model):
        name = f.name
        if name in _DICT_FIELDS:
            merged: dict = {}
            for m in present:
                for k, v in getattr(m, name).items():
                    if v is not None:
                        merged[k] = v
            values[name] = merged
        elif name in ("cost_breakdown", "per_eval_cost"):
            chosen = None
            for m in present:
                if getattr(m, name):
                    chosen = getattr(m, name)
            values[name] = chosen
        elif name == "per_eval":
            chosen = None
            for m in present:
                value = getattr(m, name)
                if value:
                    chosen = value
                    break
            values[name] = chosen
        elif name in ("modalities_in", "modalities_out"):
            chosen = ()
            for m in present:
                if getattr(m, name):
                    chosen = getattr(m, name)
            values[name] = chosen
        elif name == "source":
            values[name] = present[-1].source
        else:
            chosen = None
            for m in present:
                v = getattr(m, name)
                if v is not None:
                    chosen = v
            values[name] = chosen
    return Model(**values)
