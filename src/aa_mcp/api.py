"""Artificial Analysis JSON API (``/api/v2``) — the structured, keyed source.

Only the **free tier** language-model endpoint is implemented:
``GET /api/v2/language/models/free``.  It returns headline indices, the six
Capability Indexes, the Coding/Agentic indexes, median performance and
input/output/cache pricing — data the scraped RSC payload does not carry.

The endpoint needs an ``x-api-key`` header and is rate-limited (100 requests per
24 h on the free tier), so responses are cached with a longer TTL
(``AA_API_TTL``, default 6 h).  Without a key the whole module is inert: the
scraper remains the default source.  No network happens at import time.
"""

from __future__ import annotations

import json
import os
import re

from . import fetch
from .fetch import AAFetchError
from .normalize import Model

API_BASE = os.environ.get("AA_BASE_URL", "https://artificialanalysis.ai").rstrip("/") + "/api/v2"
MODELS_FREE_URL = f"{API_BASE}/language/models/free"
DEFAULT_API_TTL = 21600  # 6 hours

_MAX_PAGES = 20

__all__ = [
    "API_BASE",
    "MODELS_FREE_URL",
    "ApiAuthError",
    "fetch_models_free",
    "parse_model_item",
    "parse_models_free",
]


class ApiAuthError(AAFetchError):
    """The API rejected the key (401/403); callers downgrade to the scraper."""

    def __init__(self, message: str, *, status: int = 401, **kwargs) -> None:
        super().__init__(message, **kwargs)
        self.status = status


# --------------------------------------------------------------------------- #
# transport
# --------------------------------------------------------------------------- #


def _ttl() -> int:
    try:
        return int(os.environ.get("AA_API_TTL", DEFAULT_API_TTL))
    except (TypeError, ValueError):
        return DEFAULT_API_TTL


def _status_from(exc: BaseException) -> int | None:
    match = re.search(r"HTTP(?:\s+Error)?\s+(401|403)\b", str(exc))
    return int(match.group(1)) if match else None


def _auth_error(status: int, *, url: str, path=None) -> ApiAuthError:
    return ApiAuthError(
        f"artificialanalysis.ai API rejected the key (HTTP {status})",
        status=status,
        url=url,
        path=path,
        hint="set a valid AA_API_KEY or use AA_SOURCE=rsc",
    )


def _fetch_json_text(url: str, name: str, refresh: bool, key: str) -> str:
    """Fetch via ``fetch.get`` (which merges ``headers=`` over its defaults)."""
    try:
        got = fetch.get(
            url,
            name,
            refresh=refresh,
            rsc=False,
            ttl=_ttl(),
            headers={"x-api-key": key},
        )
    except ApiAuthError:
        raise
    except AAFetchError as exc:
        status = _status_from(exc)
        if status is not None:
            raise _auth_error(status, url=url, path=getattr(exc, "path", None)) from exc
        raise
    return got.text


def _key() -> str | None:
    return (os.environ.get("AA_API_KEY") or "").strip() or None


# --------------------------------------------------------------------------- #
# parsing (pure)
# --------------------------------------------------------------------------- #

_EVAL_INDEX_MAP = (
    ("artificial_analysis_intelligence_index", "intelligence"),
    ("artificial_analysis_coding_index", "coding"),
    ("artificial_analysis_agentic_index", "agentic"),
    ("artificial_analysis_finance_and_accounting_index", "capabilities.financeAndAccounting"),
    ("artificial_analysis_strategy_and_ops_index", "capabilities.strategyAndOps"),
    ("artificial_analysis_legal_index", "capabilities.legal"),
    ("artificial_analysis_healthcare_and_medical_index", "capabilities.healthcareAndMedical"),
    ("artificial_analysis_engineering_index", "capabilities.engineering"),
    ("artificial_analysis_economics_index", "capabilities.economics"),
)


def _num(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _nested(rec: dict, *path: str):
    cur = rec
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def parse_model_item(item: dict) -> Model:
    """Map one ``FreeModelData`` object onto the canonical :class:`Model`.

    The free shape carries no licensing block, so ``is_open_weights`` is ``None``
    ("unknown") rather than a false "proprietary" claim.  A Pro/Commercial
    payload that includes ``is_open_weights`` / ``open_weights`` /
    ``licensing.is_open_weights`` is read if present.
    """
    slug = item.get("slug") or ""
    name = item.get("name") or slug
    creator = item.get("model_creator") or {}

    evaluations = item.get("evaluations") or {}
    indices: dict[str, float | None] = {}
    for api_key, model_key in _EVAL_INDEX_MAP:
        indices[model_key] = _num(evaluations.get(api_key))

    pricing = item.get("pricing") or {}
    speed = item.get("performance") or {}
    cost = item.get("artificial_analysis_intelligence_index_cost") or {}

    is_open_weights = None
    for candidate in (
        item.get("is_open_weights"),
        item.get("open_weights"),
        _nested(item, "licensing", "is_open_weights"),
    ):
        if candidate is not None:
            is_open_weights = bool(candidate)
            break

    return Model(
        slug=slug,
        name=name,
        short_name=name,
        creator=creator.get("name") if isinstance(creator, dict) else None,
        creator_slug=creator.get("slug") if isinstance(creator, dict) else None,
        release_date=item.get("release_date"),
        deprecated=False,
        deprecated_to=None,
        is_reasoning=False,
        is_open_weights=is_open_weights,
        effort=None,
        params_b=None,
        active_params_b=None,
        context_tokens=None,
        license=None,
        license_url=None,
        weights_url=None,
        knowledge_cutoff=None,
        size_class=None,
        modalities_in=(),
        modalities_out=(),
        intelligence=indices.get("intelligence"),
        estimated=False,
        indices=indices,
        evals={},
        pricing={
            "in": _num(pricing.get("price_1m_input_tokens")),
            "out": _num(pricing.get("price_1m_output_tokens")),
            "cache_read": _num(pricing.get("price_1m_cache_hit_tokens")),
            "cache_write": _num(pricing.get("price_1m_cache_write_tokens")),
        },
        speed={
            "tps": _num(speed.get("median_output_tokens_per_second")),
            "ttft": _num(speed.get("median_time_to_first_token_seconds")),
            "ttfa": _num(speed.get("median_time_to_first_answer_token_seconds")),
            "e2e": _num(speed.get("median_end_to_end_response_time_seconds")),
        },
        cost_per_task=_num(_nested(cost, "cost_per_task", "total_cost")),
        cost_breakdown=None,
        per_eval_cost=None,
        per_eval=None,
        source="api",
    )


def parse_models_free(payload: dict) -> list[Model]:
    """Unwrap a ``LLMModelsFreeResponse`` envelope into canonical models."""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    return [parse_model_item(item) for item in data if isinstance(item, dict)]


# --------------------------------------------------------------------------- #
# fetch
# --------------------------------------------------------------------------- #


def fetch_models_free(refresh: bool = False) -> list[Model]:
    """All free-tier language models, following pagination."""
    key = _key()
    if key is None:
        raise AAFetchError(
            "AA_API_KEY is not set",
            url=MODELS_FREE_URL,
            hint="set AA_API_KEY or use AA_SOURCE=rsc",
        )
    models: list[Model] = []
    page = 1
    while True:
        name = "api_models_free" if page == 1 else f"api_models_free_p{page}"
        url = MODELS_FREE_URL if page == 1 else f"{MODELS_FREE_URL}?page={page}"
        text = _fetch_json_text(url, name, refresh, key)
        try:
            payload = json.loads(text)
        except ValueError as exc:
            raise AAFetchError(
                f"AA API returned non-JSON for {url}: {exc}", url=url
            ) from exc
        models.extend(parse_models_free(payload))
        pagination = payload.get("pagination") or {}
        if not pagination.get("has_more") or page >= _MAX_PAGES:
            break
        page += 1
    return models
