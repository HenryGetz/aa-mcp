"""Per-source page loaders for artificialanalysis.ai.

Every public loader fetches a page through :mod:`aa_mcp.fetch` (disk cache,
``AA_OFFLINE`` aware), parses the Next.js RSC flight payload with
:mod:`aa_mcp.flight`, normalizes with :mod:`aa_mcp.normalize` and returns
canonical objects.  The parsing half of each loader is exposed as a pure
``parse_*`` function so tests and offline callers can work on fixture text
without touching the network.

The loaders hold no request state: they are safe to call concurrently from the
MCP server's thread pool.  The only module-level mutable state is a tiny memo of
the 700-row leaderboard keyed by the cache file's fetch time, which trades one
payload parse for lock-free reads on the hottest path.

URL convention: :data:`SOURCE_URLS`, :data:`MEDIA_BOARDS` and
:data:`AGENT_BOARDS` hold human-readable **site-relative paths** (``/leaderboards/models``);
call sites run them through :func:`url` to build the absolute URL that
``fetch.get`` requires.  :data:`BASE_URL` defaults to ``https://artificialanalysis.ai``
and can be overridden with ``AA_BASE_URL`` (used by the local transport test).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import catalog, fetch, flight, normalize, source
from .fetch import AAFetchError
from .normalize import Model

log = logging.getLogger("aa_mcp.loaders")

__all__ = [
    "Endpoint",
    "MEDIA_BOARDS",
    "AGENT_BOARDS",
    "SOURCE_URLS",
    "BASE_URL",
    "url",
    "leaderboard",
    "model",
    "data_source",
    "provider_endpoints",
    "provider_board",
    "home_boards",
    "media",
    "agents",
    "eval_models",
    "eval_catalog",
    "sitemap_paths",
    "parse_leaderboard",
    "parse_chart",
    "parse_legacy_model",
    "parse_rich_dataset",
    "rich_dataset",
    "rich_seed",
    "rich_models",
    "parse_media",
    "parse_home_boards",
    "parse_agents",
    "parse_eval_catalog",
    "parse_sitemap",
    "parse_provider_endpoints",
    "parse_provider_board",
]

_DEFAULT_BASE_URL = "https://artificialanalysis.ai"
BASE_URL = os.environ.get("AA_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")


def url(path: str) -> str:
    """Absolute URL for a site-relative ``path`` (``"/models/x"`` → base + path).

    ``AA_BASE_URL`` is read on every call so it can be overridden at runtime
    (the local transport test points it at a loopback server).
    """
    base = (os.environ.get("AA_BASE_URL") or BASE_URL).rstrip("/")
    return f"{base}{path}"


# --------------------------------------------------------------------------- #
# Registries
# --------------------------------------------------------------------------- #

SOURCE_URLS: dict[str, str] = {
    "leaderboard": "/leaderboards/models",
    "model": "/models/{slug}",
    "model_providers": "/models/{slug}/providers",
    "providers_board": "/leaderboards/providers",
    "home": "/",
    "media": "/{arena}/leaderboard/{board}",
    "agents": "/agents/{board}",
    "eval": "/evaluations/{slug}",
    "eval_catalog": "/evaluations",
    "sitemap": "/sitemap.xml",
}

#: media board key -> absolute path on artificialanalysis.ai
MEDIA_BOARDS: dict[str, str] = {
    "text_to_image": "/image/leaderboard/text-to-image",
    "image_editing": "/image/leaderboard/editing",
    "text_to_video": "/video/leaderboard/text-to-video",
    "image_to_video": "/video/leaderboard/image-to-video",
    "video_editing": "/video/leaderboard/video-editing",
    "text_to_speech": "/text-to-speech/leaderboard/provider-voice",
    "text_to_speech_controlled": "/text-to-speech/leaderboard/controlled-voice",
    "music_instrumental": "/music/leaderboard/instrumental",
    "music_with_vocals": "/music/leaderboard/vocals",
}

#: agents board key -> absolute path on artificialanalysis.ai
AGENT_BOARDS: dict[str, str] = {
    "coding_agents": "/agents/coding-agents",
    "chatbots": "/agents/chatbots",
    "search_api": "/agents/search-api",
}

_PRECISIONS = ("fp4", "fp8", "fp16", "bf16", "int4", "int8", "awq", "gptq")

_PRICE_UNITS: dict[str, str] = {
    "pricePer1kImages": "/1k imgs",
    "pricePerMillionImages": "/1M imgs",
    "pricePerImage": "/img",
    "pricePerMinute": "/min",
    "pricePerSecond": "/s",
    "pricePer1mCharacters": "/1M chars",
    "pricePerMillionCharacters": "/1M chars",
    "pricePer1kCharacters": "/1k chars",
    "pricePerGeneration": "/gen",
    "pricePerSong": "/song",
    "pricePerTrack": "/track",
    "pricePerSecondOfAudio": "/s audio",
}

_EXTRA_KEYS = (
    "voiceCount",
    "openWeightsCommercial",
    "baseModel",
    "isDerived",
)

# --------------------------------------------------------------------------- #
# Endpoint
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class Endpoint:
    """A single (host, model, precision) serving endpoint."""

    model_slug: str
    model_name: str
    host: str
    host_slug: str | None
    precision: str | None
    price_in: float | None
    price_out: float | None
    cache_read: float | None
    cache_write: float | None
    cache_hit_discount: float | None
    cost_per_task: float | None
    tps: float | None
    ttft: float | None
    e2e: float | None
    function_calling: bool
    json_mode: bool
    openai_compatible: bool | None
    context_tokens: int | None
    intelligence: float | None
    source: str


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v: Any) -> int | None:
    n = _num(v)
    return None if n is None else int(n)


def _dig(obj: Any, *path: str) -> Any:
    cur = obj
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _opt_bool(v: Any) -> bool | None:
    return None if v is None else bool(v)


_PRECISION_RE = re.compile(
    r"(?<![A-Za-z])(?:NV|MX)?(FP4|FP8|FP16|BF16)"
    r"|(?<![A-Za-z])(INT4|INT8)|(?<![A-Za-z])(AWQ|GPTQ)",
    re.IGNORECASE,
)


def _precision(endpoint_slug: str | None, *labels: str | None) -> str | None:
    """Quantization tag, lowercased (matching AA's vocabulary).

    AA now encodes it in a human label — the host label (``Supernova (FP4)``) or
    the endpoint/model label (``DeepSeek V3.2 (FP8)``) — so scan those first and
    keep the endpoint-slug suffix rule as a fallback.
    """
    for text in labels:
        if isinstance(text, str):
            match = _PRECISION_RE.search(text)
            if match:
                return (match.group(1) or match.group(2) or match.group(3)).lower()
    if not endpoint_slug:
        return None
    tail = re.split(r"[_\-/]", endpoint_slug.strip())
    for token in reversed(tail):
        if token.lower() in _PRECISIONS:
            return token.lower()
    return None


def _cost_per_task(perf: dict | None) -> float | None:
    """Read ``performance.intelligenceIndexCostPerTask`` in any of its shapes.

    Live payloads use three forms: a plain float, a flat ``{"total": …}`` (the
    ``/models/<slug>/providers`` endpoint shape) and the nested
    ``{"cost": {"total": …}}`` (chart/model-page shape).
    """
    if not isinstance(perf, dict):
        return None
    value = perf.get("intelligenceIndexCostPerTask")
    if isinstance(value, dict):
        total = _dig(value, "cost", "total")
        if total is None:
            total = _dig(value, "cost", "totalCost")
        if total is None:
            total = value.get("total")
        if total is None:
            total = value.get("totalCost")
        return _num(total)
    return _num(value)


# --------------------------------------------------------------------------- #
# leaderboard / model pages
# --------------------------------------------------------------------------- #

_LEADERBOARD_REQUIRED = ("slug", "intelligenceIndex")
_CHART_REQUIRED = ("chartDefaultSelected", "releaseDate", "suffix")

# cache key -> (fetch time, parsed list); guarded only by atomic rebinding
_LEADERBOARD_MEMO: tuple[tuple[str, float], list[Model]] | None = None


def _release_index(payload: str) -> dict[str, dict]:
    """The payload's sibling ``{slug, releaseDate, deprecated, creator}`` array.

    Keyed by *release* slug (e.g. ``claude-opus-5-5``) — leaderboard rows are
    *variant* slugs (e.g. ``claude-opus-5-5-high``).
    """
    try:
        records = flight.find_array(payload, ("releaseDate", "deprecated", "creator"))
    except LookupError:
        return {}
    index: dict[str, dict] = {}
    for record in records:
        slug = record.get("slug")
        if slug:
            index[slug] = record
    return index


def _join_release(model: Model, index: dict[str, dict], by_length: list[str]) -> None:
    """Fill ``release_date``/``creator_slug`` on a leaderboard row from siblings."""
    entry = index.get(model.slug)
    if entry is None:
        for slug in by_length:  # longest release slug that prefixes the variant
            if model.slug.startswith(slug + "-"):
                entry = index[slug]
                break
    if entry is None:
        return
    if model.release_date is None:
        model.release_date = entry.get("releaseDate")
    if model.creator_slug is None:
        creator = entry.get("creator")
        if isinstance(creator, dict):
            model.creator_slug = creator.get("slug")


def parse_leaderboard(text: str) -> list[Model]:
    """Parse the metrics array (the 700-row one) from ``/leaderboards/models``.

    Rows are joined to the payload's sibling release array so ``release_date``
    and ``creator_slug`` are populated (the metrics array carries neither).
    """
    payload = flight.payload(text)
    records = flight.find_array(payload, _LEADERBOARD_REQUIRED)
    index = _release_index(payload)
    by_length = sorted(index, key=len, reverse=True)
    models = [normalize.from_leaderboard(rec) for rec in records if isinstance(rec, dict)]
    if index:
        for model in models:
            _join_release(model, index, by_length)
    return models


_MODELS_REF_RE = re.compile(r":models:(\d+)$")
_RICH_MIN = 100  # chart arrays are 27-32 entries; the rich dataset is ~700


def _initial_models_items(payload: str) -> list | None:
    """The raw ``"initialModels"`` array (dicts and/or flight-reference strings)."""
    match = re.search(r'"initialModels"\s*:\s*\[', payload)
    if not match:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(payload, payload.index("[", match.start()))
    except ValueError:
        return None
    return value if isinstance(value, list) else None


def _rich_records(payload: str) -> list[dict] | None:
    """The >100-entry chart-shaped array (the rich ~700-model dataset), if present."""
    try:
        arrays = flight.find_arrays(payload, _CHART_REQUIRED)
    except LookupError:  # pragma: no cover - defensive
        return None
    candidates = [a for a in arrays if len(a) > _RICH_MIN]
    if not candidates:
        return None
    return max(candidates, key=len)


def _resolve_refs(items: list, payload: str, pool: list | None) -> list[dict]:
    """Resolve flight-reference strings against the same payload.

    ``$e:…:props:models:<N>`` indexes into the sibling chart-shaped array;
    ``$e:…:props:currentModel`` resolves the page's ``currentModel`` object.
    Non-dicts that cannot be resolved are skipped.
    """
    out: list[dict] = []
    for item in items:
        if isinstance(item, dict):
            out.append(item)
            continue
        if not isinstance(item, str):
            continue
        match = _MODELS_REF_RE.search(item)
        if match and pool is not None:
            index = int(match.group(1))
            if 0 <= index < len(pool) and isinstance(pool[index], dict):
                out.append(pool[index])
                continue
        if item.endswith(":currentModel"):
            current = flight.keyed_object(payload, "currentModel")
            if isinstance(current, dict):
                out.append(current)
    return out


def parse_chart(text: str) -> list[Model]:
    """Parse the ``initialModels`` chart set from a model or evaluation page.

    On "rich" pages the array holds flight-reference strings into the sibling
    ~700-entry dataset; those are resolved.  Non-dict entries are always skipped,
    so a single odd entry can never crash a tool.
    """
    payload = flight.payload(text)
    items = _initial_models_items(payload)
    if items is None:
        try:
            found = flight.find_array(payload, _CHART_REQUIRED)
        except LookupError:
            found = []
        records = [rec for rec in found if isinstance(rec, dict)]
    else:
        pool = _rich_records(payload) if any(isinstance(i, str) for i in items) else None
        records = _resolve_refs(items, payload, pool)
    return [normalize.from_chart(rec) for rec in records]



def parse_legacy_model(text: str) -> Model | None:
    """Parse the ``currentModel`` object from a legacy/deprecated model page."""
    record = flight.keyed_object(flight.payload(text), "currentModel")
    if not isinstance(record, dict):
        return None
    return normalize.from_legacy(record)


# --------------------------------------------------------------------------- #
# rich dataset (some model pages embed ~700 x 94-key chart records)
# --------------------------------------------------------------------------- #

#: slugs verified (2026-10-14) to carry the rich dataset; probed in this order.
_KNOWN_RICH = (
    "step-5",
    "minimax-m3",
    "gemini-4-argon",
    "muse-wonder-full",
    "qwen3-8-max",
    "qwen3-8-2-4t-a95b",
)
_RICH_PROBES = 6
_RICH_TTL_DEFAULT = 21600

_RICH_MEMO: tuple[str, list[Model]] | None = None  # (cache key, models)


def _rich_ttl() -> int:
    try:
        return int(os.environ.get("AA_RICH_TTL", _RICH_TTL_DEFAULT))
    except (TypeError, ValueError):
        return _RICH_TTL_DEFAULT


def _rich_cache_path() -> Path:
    return fetch.cache_dir() / "rich_dataset.json"


def _rich_seed_path() -> Path:
    return fetch.cache_dir() / "rich_seed.json"


def _write_json_atomic(path: Path, obj) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def parse_rich_dataset(text: str) -> list[Model]:
    """Parse the ~700-entry chart dataset some model pages embed.

    Pure and offline-friendly: resolves the few flight-reference strings against
    the same payload, dedupes by slug, and skips anything non-dict.
    """
    payload = flight.payload(text)
    rich = _rich_records(payload)
    if not rich:
        return []
    records = _resolve_refs(rich, payload, rich)
    seen: set[str] = set()
    models: list[Model] = []
    for record in records:
        slug = record.get("slug")
        if not slug or slug in seen:
            continue
        seen.add(slug)
        try:
            models.append(normalize.from_chart(record))
        except ValueError:
            continue
    return models


def rich_seed() -> str | None:
    """The slug currently remembered as carrying the rich dataset (no network)."""
    data = _read_json(_rich_seed_path())
    if isinstance(data, dict):
        slug = data.get("slug")
        if isinstance(slug, str) and slug:
            return slug
    return None


def _discover_rich_seed() -> list[str]:
    """Candidate slugs to probe: remembered, then known-rich, then newest releases."""
    candidates: list[str] = []
    remembered = rich_seed()
    if remembered:
        candidates.append(remembered)
    for slug in _KNOWN_RICH:
        if slug not in candidates:
            candidates.append(slug)
    if len(candidates) < _RICH_PROBES:
        try:
            releases = sorted(
                (m for m in leaderboard() if m.release_date),
                key=lambda m: m.release_date,
                reverse=True,
            )
        except Exception as exc:  # noqa: BLE001 - discovery must not raise
            log.warning("rich seed discovery: leaderboard unavailable (%s)", exc)
            releases = []
        for model in releases:
            if model.slug not in candidates:
                candidates.append(model.slug)
            if len(candidates) >= _RICH_PROBES:
                break
    return candidates[:_RICH_PROBES]


def _offline() -> bool:
    return os.environ.get("AA_OFFLINE", "").strip().lower() in ("1", "true", "yes", "on")


def rich_dataset(refresh: bool = False) -> list[Model]:
    """The cross-model rich dataset, disk-cached and memoized (``AA_RICH_TTL``).

    Offline returns whatever is cached (or ``[]``) without touching the network.
    Never raises.
    """
    global _RICH_MEMO
    path = _rich_cache_path()
    if _RICH_MEMO is not None and _RICH_MEMO[0] == str(path) and not refresh:
        return _RICH_MEMO[1]

    records = _read_json(path) if path.exists() else None
    models: list[Model] = (
        [normalize.from_chart(r) for r in records if isinstance(r, dict)]
        if isinstance(records, list)
        else []
    )
    if models and not refresh:
        try:
            age = max(0.0, time.time() - path.stat().st_mtime)
        except OSError:  # pragma: no cover - race
            age = 0.0
        if _offline() or age <= _rich_ttl():
            _RICH_MEMO = (str(path), models)
            return models
    if _offline():
        _RICH_MEMO = (str(path), models)
        return models

    for slug in _discover_rich_seed():
        try:
            got = fetch.get(
                url(SOURCE_URLS["model"].format(slug=slug)), f"model_{slug}", refresh=refresh
            )
        except AAFetchError as exc:
            log.warning("rich seed probe %s failed (%s)", slug, exc)
            continue
        payload = flight.payload(got.text)
        raw = _rich_records(payload)
        if not raw:
            continue
        seen: set[str] = set()
        extracted: list[dict] = []
        for record in _resolve_refs(raw, payload, raw):
            slug_key = record.get("slug")
            if slug_key and slug_key not in seen:
                seen.add(slug_key)
                extracted.append(record)
        if not extracted:
            continue
        try:
            _write_json_atomic(path, extracted)
            _write_json_atomic(_rich_seed_path(), {"slug": slug, "ts": time.time()})
        except OSError as exc:  # pragma: no cover - cache write failure must not break
            log.warning("could not persist rich dataset: %s", exc)
        log.warning("rich dataset discovered via slug %s (%d models)", slug, len(extracted))
        models = [normalize.from_chart(r) for r in extracted]
        _RICH_MEMO = (str(path), models)
        return models

    log.warning("rich dataset not found in %d probe(s)", _RICH_PROBES)
    _RICH_MEMO = (str(path), [])
    return []


def rich_models(slug: str, refresh: bool = False) -> dict[str, Model]:
    """The rich record for ``slug`` from its own page's dataset (empty if absent)."""
    got = fetch.get(
        url(SOURCE_URLS["model"].format(slug=slug)), f"model_{slug}", refresh=refresh
    )
    for model in parse_rich_dataset(got.text):
        if model.slug == slug:
            return {slug: model}
    return {}



def data_source() -> str:
    """Provenance label (``"aa:api"`` / ``"aa:rsc"``) for tool headers."""
    return source.source_label()


def _leaderboard_rsc(refresh: bool = False) -> list[Model]:
    """The 700-row RSC leaderboard (memoized on the cache file's fetch time)."""
    global _LEADERBOARD_MEMO
    got = fetch.get(
        url(SOURCE_URLS["leaderboard"]), "leaderboard", refresh=refresh, min_bytes=200_000
    )
    key = (str(got.path), got.fetched_at)
    memo = _LEADERBOARD_MEMO
    if memo is not None and memo[0] == key:
        return memo[1]
    models = parse_leaderboard(got.text)
    _LEADERBOARD_MEMO = (key, models)
    return models


def _enrich_licensing(api_model: Model, rsc_model: Model) -> Model:
    """Merge RSC identity/licensing/estimated fields onto an API record.

    The RSC contribution is stripped of its dict/cost fields first, so it can
    only supply identity/licensing/estimated scalars; the API's indices,
    pricing and speed are preserved (``source`` stays ``"api"``).
    """
    patch = replace(
        rsc_model,
        slug=api_model.slug,
        name=api_model.name,
        short_name=api_model.short_name,
        source="api",
        indices={},
        evals={},
        pricing={},
        speed={},
        cost_per_task=None,
        cost_breakdown=None,
        per_eval_cost=None,
        per_eval=None,
    )
    return normalize.merge(api_model, patch)


def leaderboard(refresh: bool = False, *, with_licensing: bool = False) -> list[Model]:
    """All model variants — from the JSON API when keyed, else the RSC scrape.

    On the API source the free shape carries no licensing data, so
    ``with_licensing=True`` lazily enriches each record from the RSC leaderboard
    (identity/licensing/estimated only).  If that fetch fails the API records are
    returned unchanged (``is_open_weights`` stays ``None`` → "unknown").
    """
    if source.active_source(refresh=refresh) == "api":
        from . import api

        models = api.fetch_models_free(refresh=refresh)
        if not with_licensing:
            return models
        try:
            rsc = _leaderboard_rsc(refresh=refresh)
        except (AAFetchError, LookupError) as exc:
            log.warning(
                "RSC licensing enrichment unavailable (%s); returning API records "
                "with unknown licensing",
                exc,
            )
            return models
        by_slug = {model.slug: model for model in rsc}
        return [
            _enrich_licensing(model, by_slug[model.slug])
            if model.slug in by_slug
            else model
            for model in models
        ]
    return _leaderboard_rsc(refresh=refresh)


def model(slug: str, refresh: bool = False) -> dict[str, Model]:
    """Chart set embedded in ``/models/<slug>`` as ``{slug: Model}``.

    On the API source the target record comes from the JSON API and is merged
    with the RSC chart set (which adds per-eval fields); if that RSC fetch or
    merge path fails we return the API record alone.  Otherwise the page's
    ``initialModels`` chart set is used, falling back to the legacy
    ``currentModel`` object, and the requested slug is always a key.
    """
    path = SOURCE_URLS["model"].format(slug=slug)
    name = f"model_{slug}"

    if source.active_source(refresh=refresh) == "api":
        from . import api

        api_model: Model | None = None
        try:
            api_model = next(
                (m for m in api.fetch_models_free(refresh=refresh) if m.slug == slug),
                None,
            )
        except AAFetchError:
            api_model = None
        if api_model is not None:
            chart: list[Model] = []
            try:
                chart = parse_chart(fetch.get(url(path), name, refresh=refresh).text)
            except (AAFetchError, LookupError):
                chart = []
            out = {record.slug: record for record in chart}
            if slug in out:
                out[slug] = normalize.merge(api_model, out[slug])
            else:
                out[slug] = api_model
            return out

    got = fetch.get(url(path), name, refresh=refresh)
    out = {}
    legacy: Model | None = None
    try:
        chart = parse_chart(got.text)
    except LookupError:
        chart = []
    for record in chart:
        out.setdefault(record.slug, record)
    if slug not in out:
        legacy = parse_legacy_model(got.text)
        if legacy is not None:
            out.setdefault(legacy.slug, legacy)
    if slug not in out:
        raise ValueError(
            f"{url(path)}: model {slug!r} was missing from the embedded chart set "
            f"({len(out)} records) and the page carried no matching 'currentModel' "
            "object (legacy/deprecated page)."
        )
    return out


# --------------------------------------------------------------------------- #
# providers
# --------------------------------------------------------------------------- #


def _as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _pick_name(*candidates) -> str | None:
    """First non-empty, non-flight-reference string among ``candidates``."""
    for cand in candidates:
        if isinstance(cand, str):
            cand = cand.strip()
            if cand and not cand.startswith("$"):
                return cand
    return None


def _endpoint(rec: dict, source: str) -> Endpoint:
    host = _as_dict(rec.get("host"))
    model = _as_dict(rec.get("model"))
    pricing = _as_dict(rec.get("pricing"))
    perf = _as_dict(rec.get("performance"))
    features = _as_dict(rec.get("features"))
    model_slug = _clean(model.get("slug")) or ""
    model_name = (
        _pick_name(
            rec.get("label"),
            model.get("name"),
            model.get("label"),
            rec.get("modelName"),
            rec.get("name"),
        )
        or model_slug
    )
    host_name = _pick_name(host.get("name"), host.get("label")) or ""
    return Endpoint(
        model_slug=model_slug,
        model_name=model_name,
        host=host_name,
        host_slug=_clean(host.get("slug")),
        precision=_precision(
            rec.get("endpointSlug") or rec.get("slug"),
            host.get("label"),
            host.get("name"),
            rec.get("label"),
            model.get("name"),
            model.get("label"),
        ),
        price_in=_num(pricing.get("price1mInputTokens")),
        price_out=_num(pricing.get("price1mOutputTokens")),
        cache_read=_num(pricing.get("cacheHitPrice")),
        cache_write=_num(pricing.get("cacheWritePrice")),
        cache_hit_discount=_num(pricing.get("cacheHitDiscountPercent")),
        cost_per_task=_cost_per_task(perf),
        tps=_num(
            perf.get("medianOutputTokensPerSecond")
            if perf.get("medianOutputTokensPerSecond") is not None
            else _dig(perf, "outputSpeed", "median")
        ),
        ttft=_num(
            perf.get("medianTimeToFirstTokenSeconds")
            if perf.get("medianTimeToFirstTokenSeconds") is not None
            else _dig(perf, "timeToFirstToken", "median")
        ),
        e2e=_num(
            perf.get("medianEndToEndResponseTimeSeconds")
            if perf.get("medianEndToEndResponseTimeSeconds") is not None
            else _dig(perf, "endToEndResponseTime", "totalTime")
        ),
        function_calling=bool(
            rec.get("functionCalling", features.get("functionCalling"))
        ),
        json_mode=bool(rec.get("jsonMode", features.get("jsonMode"))),
        openai_compatible=_opt_bool(features.get("openaiCompatible")),
        context_tokens=_int(
            features.get("contextWindowTokens")
            if features.get("contextWindowTokens") is not None
            else model.get("contextWindowTokens")
        ),
        intelligence=_num(model.get("intelligenceIndex")),
        source=source,
    )


def parse_provider_endpoints(text: str) -> list[Endpoint]:
    """Parse the ``hostModels`` array of ``/models/<slug>/providers``."""
    records = flight.find_array(
        flight.payload(text), ("host", "model", "pricing", "jsonMode")
    )
    endpoints = [_endpoint(rec, "providers_model") for rec in records if isinstance(rec, dict)]
    # Cheapest cost_per_task first (None last); all rows are always returned —
    # the tiebreakers only make the order fully deterministic.
    endpoints.sort(
        key=lambda e: (
            e.cost_per_task is None,
            e.cost_per_task or 0.0,
            e.price_in or 0.0,
            e.host_slug or "",
            e.model_slug or "",
        )
    )
    return endpoints


def parse_provider_board(text: str) -> list[Endpoint]:
    """Parse the 1201-row ``rows`` array of ``/leaderboards/providers``."""
    records = flight.find_array(
        flight.payload(text), ("host", "model", "features", "pricing")
    )
    return [_endpoint(rec, "providers_board") for rec in records if isinstance(rec, dict)]


def provider_endpoints(slug: str, refresh: bool = False) -> list[Endpoint]:
    """All serving endpoints for one model, cheapest ``cost_per_task`` first."""
    path = SOURCE_URLS["model_providers"].format(slug=slug)
    got = fetch.get(url(path), f"providers_{slug}", refresh=refresh)
    return parse_provider_endpoints(got.text)


def provider_board(refresh: bool = False) -> list[Endpoint]:
    """The 1201-row provider leaderboard."""
    got = fetch.get(
        url(SOURCE_URLS["providers_board"]),
        "providers_board",
        refresh=refresh,
        min_bytes=200_000,
    )
    return parse_provider_board(got.text)


# --------------------------------------------------------------------------- #
# homepage boards
# --------------------------------------------------------------------------- #


def _sort_asc(rows: list[dict], key: str) -> list[dict]:
    return sorted(rows, key=lambda r: (_num(r.get(key)) is None, _num(r.get(key)) or 0.0))


def _sort_desc(rows: list[dict], key: str) -> list[dict]:
    return sorted(
        rows,
        key=lambda r: (_num(r.get(key)) is None, -(_num(r.get(key)) or 0.0)),
    )


_EVAL_PANEL_RE = re.compile(r'\{"evalSlug"\s*:')


def _eval_panels(payload: str) -> list[dict]:
    """All ``{"evalSlug":..,"models":[..]}`` panel objects in document order.

    ``flight`` has no generic "every nested object with key" helper, so we anchor
    on the literal object opening and decode it directly.
    """
    decoder = json.JSONDecoder()
    panels: list[dict] = []
    for match in _EVAL_PANEL_RE.finditer(payload):
        try:
            value, _ = decoder.raw_decode(payload, match.start())
        except ValueError:
            continue
        if isinstance(value, dict) and value.get("evalSlug") and value.get("models"):
            panels.append(value)
    return panels


def parse_home_boards(text: str) -> dict[str, list[dict]]:
    """speech + eval-panel boards embedded in the homepage payload."""
    payload = flight.payload(text)
    out: dict[str, list[dict]] = {}
    for key, name, metric, desc in (
        ("sttNonStreaming", "stt", "werIndex", False),
        ("sttStreaming", "stt_streaming", "werIndex", False),
        ("sts", "sts", "stsIndex", True),
    ):
        obj = flight.keyed_object(payload, key)
        rows = list(obj.get("models") or []) if isinstance(obj, dict) else []
        out[name] = _sort_desc(rows, metric) if desc else _sort_asc(rows, metric)
    for panel in _eval_panels(payload):
        out[f"eval:{panel['evalSlug']}"] = list(panel["models"])
    return out


def home_boards(refresh: bool = False) -> dict[str, list[dict]]:
    """Homepage speech boards and per-eval top panels."""
    got = fetch.get(url(SOURCE_URLS["home"]), "home", refresh=refresh, min_bytes=100_000)
    return parse_home_boards(got.text)


# --------------------------------------------------------------------------- #
# media arenas
# --------------------------------------------------------------------------- #


def _media_price(values: dict) -> tuple[float | None, str | None]:
    for key, unit in _PRICE_UNITS.items():
        if values.get(key) is not None:
            return _num(values.get(key)), unit
    for key, value in values.items():
        if key.startswith("pricePer") and value is not None:
            return _num(value), "/" + key[len("pricePer"):].replace("1m", "1M ").strip()
    return None, None


def _media_open_weights(values: dict) -> bool | None:
    if "openWeights" in values:
        return _opt_bool(values.get("openWeights"))
    if "openWeightsUrl" in values:
        return bool(values.get("openWeightsUrl"))
    return None


def _media_row(item: dict) -> dict:
    values = item.get("values") or {}
    formatted = item.get("formatted") or {}
    creator = values.get("creator")
    if isinstance(creator, dict):
        creator = creator.get("name")
    rank = formatted.get("rank")
    if rank is None:
        rank = values.get("storedRank")
    if rank is None:
        rank = values.get("rank")
    price, price_unit = _media_price(values)
    extra = {
        key: values[key]
        for key in _EXTRA_KEYS
        if values.get(key) is not None
    }
    return {
        "name": values.get("name") or formatted.get("name"),
        "creator": creator,
        "elo": _num(values.get("elo")),
        "ci_lower": _num(values.get("ciLower")),
        "ci_upper": _num(values.get("ciUpper")),
        "appearances": _int(values.get("appearances")),
        "rank": _int(rank),
        "release_date": values.get("releaseDate") or formatted.get("released"),
        "price": price,
        "price_unit": price_unit,
        "open_weights": _media_open_weights(values),
        "url": values.get("url"),
        "extra": extra,
    }


def parse_media(text: str, board: str = "") -> list[dict]:
    """Parse one media arena page into flat rows sorted by Elo (best first)."""
    payload = flight.payload(text)
    arrays = flight.find_arrays(payload, ("values", "formatted"))
    if not arrays:
        raise ValueError(
            f"{board or 'media page'}: no arena array carrying 'values' + 'formatted' "
            "keys was found in the payload"
        )
    arena = max(arrays, key=len)
    rows = [_media_row(item) for item in arena if isinstance(item, dict)]
    rows.sort(key=lambda r: (r["elo"] is None, -(r["elo"] or 0.0)))
    return rows


def media(board: str, refresh: bool = False) -> list[dict]:
    """Leaderboard rows for one of :data:`MEDIA_BOARDS`."""
    try:
        path = MEDIA_BOARDS[board]
    except KeyError:
        raise ValueError(
            f"unknown media board {board!r}; expected one of "
            f"{', '.join(sorted(MEDIA_BOARDS))}"
        ) from None
    got = fetch.get(url(path), f"media_{board}", refresh=refresh)
    return parse_media(got.text, board)


# --------------------------------------------------------------------------- #
# agents
# --------------------------------------------------------------------------- #


def _unwrap_row(rec: dict) -> dict:
    """Flatten a ``{"values": {...}, "formatted": {...}}`` wrapper when present."""
    values = rec.get("values")
    if isinstance(values, dict):
        merged = {k: v for k, v in rec.items() if k != "values"}
        merged.update(values)
        return merged
    return rec


_AGENT_REF_RE = re.compile(r"\$[^:]*:.*?:([A-Za-z][A-Za-z0-9]*):(\d+)(?::([A-Za-z0-9_]+))?$")


def _is_ref(value) -> bool:
    return isinstance(value, str) and value.startswith("$")


def _clean(value):
    """Drop unresolved flight references so they never render as literal ``$…``."""
    return None if _is_ref(value) else value


def _named_array(payload: str, name: str) -> list | None:
    """The array decoded from the first ``"<name>":[...]`` in the payload."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r'"%s"\s*:\s*\[' % re.escape(name), payload):
        try:
            value, _ = decoder.raw_decode(payload, payload.index("[", match.start()))
        except ValueError:
            continue
        if isinstance(value, list):
            return value
    return None


def _agent_resolver(payload: str):
    """Resolve ``$id:…:<array>:<index>[:<field>]`` references inside a payload.

    The referenced array is looked up by name in the same payload (``rows``,
    ``benchmarkRows``, …), matching how the flight serializer dedupes objects.
    """
    cache: dict[str, list] = {}

    def resolve(value, depth: int = 0):
        if depth > 5:
            return None
        if isinstance(value, dict):
            return value
        if isinstance(value, list):
            for item in value:
                found = resolve(item, depth + 1)
                if found:
                    return found
            return None
        if not _is_ref(value):
            return None
        match = _AGENT_REF_RE.search(value)
        if not match:
            return None
        name, index, field = match.group(1), int(match.group(2)), match.group(3)
        if name not in cache:
            cache[name] = _named_array(payload, name) or []
        array = cache[name]
        if index >= len(array):
            return None
        obj = array[index]
        if field and isinstance(obj, dict):
            obj = obj.get(field)
        if isinstance(obj, dict):
            return obj
        return resolve(obj, depth + 1)

    return resolve


def _creator_name(rec: dict, resolve=None):
    """Creator name from a dict, a plain string, a list, or creator-like fields."""
    for key in ("agentCreator", "creator", "modelCreators", "creatorName",
                "providerFamily", "providerName"):
        value = rec.get(key)
        if _is_ref(value) and resolve is not None:
            value = resolve(value)
        if isinstance(value, dict):
            name = _clean(value.get("name")) or _clean(value.get("slug"))
            if name:
                return name
        elif isinstance(value, str):
            if value and not _is_ref(value):
                return value
        elif isinstance(value, list) and value:
            first = value[0]
            if _is_ref(first) and resolve is not None:
                first = resolve(first)
            if isinstance(first, dict):
                name = _clean(first.get("name")) or _clean(first.get("slug"))
                if name:
                    return name
            elif isinstance(first, str) and first and not _is_ref(first):
                return first
    return None


def _first_num(rec: dict, *keys: str):
    for key in keys:
        value = _num(rec.get(key))
        if value is not None:
            return value
    return None


_AGENT_EXTRA_KEYS = (
    "agentName", "displayLabel", "provider", "hostModelSlug", "evalCount",
    "tier", "priceMonthly", "priceMonthlyNotes", "externalUrl",
    "intelligenceIndex", "modelSlug", "modelName", "modelNotes", "featuresScore",
    "providerKey", "providerName", "providerFamily", "providerVariant",
    "isNativeSearch", "isBaseline", "aaSearchQualityIndex", "browsecompAccuracy",
    "deepsearchqaAvgF1", "omniscienceAccuracy", "avgLatencyS",
    "searchApiCostPerTaskUsd", "candidateModelCostPerTaskUsd", "benchmarkCount",
    "isDefault", "isHighlighted", "isUnavailable",
)


def _resolve_scalar(value, resolve=None):
    """Resolve a scalar that might be a flight reference; never returns ``$…``."""
    if _is_ref(value) and resolve is not None:
        value = resolve(value)
    if isinstance(value, dict):
        return _clean(value.get("name")) or _clean(value.get("slug"))
    return value if isinstance(value, str) and not _is_ref(value) else None


def _agent_row(rec: dict, resolve=None) -> dict:
    """Flatten one agents-board record, tolerant of every observed shape."""
    rec = _unwrap_row(rec)
    display = rec.get("display")
    if _is_ref(display) and resolve is not None:
        display = resolve(display)
    if not isinstance(display, dict):
        display = {}
    mean = rec.get("mean") if isinstance(rec.get("mean"), dict) else {}
    creator = rec.get("agentCreator")
    if _is_ref(creator) and resolve is not None:
        creator = resolve(creator)
    if not isinstance(creator, dict):
        creator = rec.get("creator")
        if _is_ref(creator) and resolve is not None:
            creator = resolve(creator)
    if not isinstance(creator, dict):
        creator = {}
    row = {
        "name": _resolve_scalar(rec.get("displayLabel"), resolve)
        or _resolve_scalar(rec.get("agentName"), resolve)
        or _resolve_scalar(rec.get("name"), resolve)
        or _resolve_scalar(rec.get("providerName"), resolve),
        "agent": _resolve_scalar(rec.get("agentName"), resolve)
        or _resolve_scalar(rec.get("name"), resolve)
        or _resolve_scalar(rec.get("providerName"), resolve),
        "model": _resolve_scalar(display.get("model"), resolve)
        or _resolve_scalar(rec.get("modelName"), resolve)
        or _resolve_scalar(rec.get("modelSlug"), resolve)
        or _resolve_scalar(rec.get("answerModelSlug"), resolve),
        "creator": _creator_name(rec, resolve),
        "creator_slug": _clean(creator.get("slug")),
        "provider": _resolve_scalar(rec.get("provider"), resolve)
        or _resolve_scalar(rec.get("providerName"), resolve)
        or _resolve_scalar(rec.get("providerFamily"), resolve),
        "host_model_slug": _clean(rec.get("hostModelSlug")),
        "rank": None,
        "score": _first_num(rec, "indexScore", "aaSearchQualityIndex", "featuresScore",
                            "qualityIndex"),
        "eval_count": rec.get("evalCount"),
        "cost_per_task": _first_num(mean, "costUsd") if mean else None,
        "wall_time_sec": _num(mean.get("agentWallTimeSec")) if mean else None,
        "steps": _num(mean.get("steps")) if mean else None,
        "input_tokens": _num(mean.get("inputTokens")) if mean else None,
        "output_tokens": _num(mean.get("outputTokens")) if mean else None,
        "total_cost": _num(_dig(rec, "sums", "costUsd")),
        "is_default": rec.get("isDefault"),
        "is_highlighted": rec.get("isHighlighted"),
        "unavailable": rec.get("isUnavailable"),
    }
    if row["cost_per_task"] is None:
        row["cost_per_task"] = _first_num(rec, "searchApiCostPerTaskUsd")
    for key in _AGENT_EXTRA_KEYS:
        if key in rec and key not in row:
            row[key] = rec[key]
    # never expose a residual flight reference as a literal "$…" string
    for key, value in list(row.items()):
        if _is_ref(value):
            row[key] = None
    return row


_ROW_REF_RE = re.compile(r":rows:(\d+)$")

#: first-item keys identifying each board's leaderboard array
_AGENT_BOARD_KEYS: dict[str, tuple[str, ...]] = {
    "coding_agents": ("agentName", "indexScore"),
    "chatbots": ("featuresScore", "tier"),
    "search_api": ("providerKey", "aaSearchQualityIndex"),
}
_AGENT_GENERIC_KEYS = (
    ("agentName", "indexScore"),
    ("providerKey", "aaSearchQualityIndex"),
    ("featuresScore", "tier"),
)


def _agent_arrays(payload: str, board: str) -> list[list[dict]]:
    order: list[tuple[str, ...]] = []
    if board in _AGENT_BOARD_KEYS:
        order.append(_AGENT_BOARD_KEYS[board])
    order.extend(keys for keys in _AGENT_GENERIC_KEYS if keys not in order)
    for keys in order:
        try:
            arrays = [a for a in flight.find_arrays(payload, keys) if a and isinstance(a[0], dict)]
        except LookupError:  # pragma: no cover - defensive
            arrays = []
        if arrays:
            return arrays
    return []


def parse_agents(text: str, board: str = "") -> list[dict]:
    """Normalize the table an agents board embeds into flat dicts.

    Handles all three boards (coding agents, chatbots, search APIs); rows may
    hold flight-reference strings (``$29:…:props:rows:3``), which are resolved
    against the sibling all-dict row array.  Creator may be a dict or a string.
    Non-dict entries are skipped.
    """
    payload = flight.payload(text)
    arrays = _agent_arrays(payload, board)
    if not arrays:
        return []
    main = max(arrays, key=len)
    indices: list[int | None] = []
    for item in main:
        if isinstance(item, dict):
            indices.append(None)
        elif isinstance(item, str):
            match = _ROW_REF_RE.search(item)
            indices.append(int(match.group(1)) if match else None)
        else:
            indices.append(None)
    pool: list[dict] | None = None
    wanted = [i for i in indices if i is not None]
    if wanted:
        largest = max(wanted)
        pools = [
            a
            for a in arrays
            if a is not main and len(a) > largest and all(isinstance(x, dict) for x in a)
        ]
        if pools:
            pool = max(pools, key=len)
    records: list[dict] = []
    for item, index in zip(main, indices):
        if isinstance(item, dict):
            records.append(item)
        elif index is not None and pool is not None and index < len(pool):
            records.append(pool[index])
    resolve = _agent_resolver(payload)
    rows = [_agent_row(rec, resolve) for rec in records]
    rows.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0.0)))
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    return rows


def agents(board: str, refresh: bool = False) -> list[dict]:
    """Leaderboard rows for one of :data:`AGENT_BOARDS`."""
    try:
        path = AGENT_BOARDS[board]
    except KeyError:
        raise ValueError(
            f"unknown agents board {board!r}; expected one of "
            f"{', '.join(sorted(AGENT_BOARDS))}"
        ) from None
    got = fetch.get(url(path), f"agents_{board}", refresh=refresh)
    rows = parse_agents(got.text, board)
    if not rows:
        raise ValueError(
            f"{url(path)}: no structured leaderboard data found in the "
            "payload (the surface may be client-rendered)"
        )
    return rows


# --------------------------------------------------------------------------- #
# evaluations
# --------------------------------------------------------------------------- #


def eval_models(slug: str, refresh: bool = False) -> list[Model]:
    """Top-N chart set for one ``/evaluations/<slug>`` page, best first."""
    path = SOURCE_URLS["eval"].format(slug=slug)
    got = fetch.get(url(path), f"eval_{slug}", refresh=refresh)
    try:
        models = parse_chart(got.text)
    except LookupError:
        models = []
    if not models:
        raise ValueError(
            f"{url(path)}: no 'initialModels' chart set found "
            "in the payload"
        )
    bench = catalog.benchmark(slug)
    if bench is not None:
        key = bench.key
        models.sort(
            key=lambda m: (
                m.evals.get(key) is None,
                -(m.evals.get(key) or 0.0),
            )
        )
    return models


class _CatalogParser(HTMLParser):
    """Collect the server-rendered ``/evaluations/<slug>`` cards."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[dict] = []
        self._card: dict | None = None
        self._depth = 0
        self._capture: str | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        href = a.get("href") or ""
        if tag == "a" and href.startswith("/evaluations/"):
            self._card = {
                "slug": href[len("/evaluations/"):].strip("/"),
                "title": "",
                "description": "",
                "tags": [],
            }
            self._depth = 1
            return
        if self._card is None:
            return
        if tag == "a":
            self._depth += 1
            return
        if self._depth != 1:
            return
        if tag in ("h2", "h3"):
            self._capture, self._buf = "title", []
        elif tag == "p" and not self._card["description"]:
            self._capture, self._buf = "description", []
        elif tag == "span":
            self._capture, self._buf = "tag", []

    def handle_endtag(self, tag: str) -> None:
        if self._card is None:
            return
        if tag == "a":
            self._depth -= 1
            if self._depth == 0:
                self.cards.append(self._card)
                self._card = None
            return
        if self._capture and tag in ("h2", "h3", "p", "span"):
            text = " ".join("".join(self._buf).split())
            capture = self._capture
            self._capture, self._buf = None, []
            if capture == "title" and not self._card["title"]:
                self._card["title"] = text
            elif capture == "description":
                self._card["description"] = text
            elif capture == "tag":
                self._card["tags"].append(text)

    def handle_data(self, data: str) -> None:
        if self._card is not None and self._capture:
            self._buf.append(data)


def parse_eval_catalog(html_text: str) -> list[dict]:
    """Parse the server-rendered ``/evaluations`` card grid."""
    parser = _CatalogParser()
    parser.feed(html_text)
    parser.close()
    cards: list[dict] = []
    seen: set[str] = set()
    for card in parser.cards:
        if not card["title"] or card["slug"] in seen:
            continue
        seen.add(card["slug"])
        cards.append(card)
    return cards


def eval_catalog(refresh: bool = False) -> list[dict]:
    """Every evaluation card from the plain-HTML ``/evaluations`` index."""
    got = fetch.get(url(SOURCE_URLS["eval_catalog"]), "eval_catalog", refresh=refresh, rsc=False)
    return parse_eval_catalog(got.text)


# --------------------------------------------------------------------------- #
# sitemap
# --------------------------------------------------------------------------- #

_LOC_RE = re.compile(r"<loc>\s*([^<\s][^<]*?)\s*</loc>", re.IGNORECASE)


def parse_sitemap(text: str) -> list[str]:
    """Return the path of every ``<loc>`` entry in a sitemap, in order."""
    paths: list[str] = []
    seen: set[str] = set()
    for raw in _LOC_RE.findall(text):
        path = urlsplit(raw.strip()).path or "/"
        if path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


def sitemap_paths(refresh: bool = False) -> list[str]:
    """Model/evaluation surface paths from ``/sitemap.xml`` (diagnostics only)."""
    try:
        got = fetch.get(url(SOURCE_URLS["sitemap"]), "sitemap", refresh=refresh, rsc=False)
    except AAFetchError as exc:  # pragma: no cover - network error path
        log.warning("sitemap fetch failed: %s", exc)
        raise
    return parse_sitemap(got.text)
