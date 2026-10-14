# Wave C — new capabilities requested by the user

The user's asks (verbatim intent):

1. "some sort of easy way to search through all the tools to find specifically ones
   that are relevant to whatever task domain" — i.e. one searchable index over
   *everything rankable* (benchmarks, composite indexes, derived metrics, arena
   boards), searchable by name **and domain tag**. Not one tool per benchmark:
   benchmarks churn, so the index must be data-driven.
2. "this one should ALWAYS have a tool for it: Intelligence Index vs. Cost to Run
   Artificial Analysis Intelligence Index — i also specifically want to be able to see
   models on the Pareto line of this graph easily."
3. "ideally, the MCP allows for comparing all models directly on any benchmark" —
   parity with
   `https://artificialanalysis.ai/models/comparisons/<a>-vs-<b>` and
   `.../comparisons?compare=a,b,c,d`, plus a YAML spec for reproducible comparisons.
4. "so high-quality that there is no question that is impossible for an AI agent to
   answer when comparing models" — the acceptance bar.

## Frozen interface (Wave C-catalog provides; Wave C-server consumes)

Add to `catalog.py` (this exact shape — the server is being written against it in
parallel; code against these names with defensive `getattr` until they exist):

```python
@dataclass(frozen=True, slots=True)
class Rankable:
    key: str                  # canonical metric key (unique across the index)
    label: str                # human label, e.g. "Artificial Analysis Cyber Index"
    kind: str                 # "benchmark" | "index" | "derived" | "arena"
    unit: str                 # "%" | "Elo" | "index" | "USD/task" | "USD" | "USD/1M" | "s" | "tok/s" | "tokens" | "params" | "date" | "text"
    tags: tuple[str, ...]     # domain tags (see DOMAINS)
    how: str                  # exact actionable hint, e.g.
                              #   "aa_benchmark_leaderboard benchmark=gpqa"
                              #   "aa_leaderboard sort=tps"
                              #   "aa_pareto x=cost_per_task"
                              #   "aa_media board=text_to_speech"
    surface: str              # "leaderboard" | "rich" | "chart" | "api" | "board"
    desc: str
    aliases: tuple[str, ...] = ()

RANKABLES: dict[str, Rankable]
DOMAINS: dict[str, tuple[str, ...]]      # canonical domain -> tags/tokens it covers
def rankable(key_or_alias: str) -> Rankable | None
def rankables(*, domain: str = "", tag: str = "", query: str = "") -> list[Rankable]
```

## Required coverage (all of these must be findable and, where applicable, rankable)

- Every entry of `BENCHMARKS` (67) as `kind="benchmark"`/`"index"`.
- Composite/derived indexes: `intelligence`, `coding`, `agentic`, `omniscience`,
  `openness`, `capabilities.*` (6) — `kind="index"`, tag `index` + domain tags.
- Derived metrics as `kind="derived"`: `tps` (label "Speed (output tokens/s)"),
  `ttft`, `ttfa`, `e2e`, `cost_per_task` ("Cost per Task"), `price_in`, `price_out`,
  `cache_read`, `cache_write`, `out_tokens_per_task` ("Output Tokens per Intelligence
  Index Task"), `index_total_cost` ("Cost to Run the Intelligence Index (whole suite)"),
  `time_per_task`, `context_tokens`, `params_b`, `active_params_b`, `release_date`.
- Arena boards as `kind="arena"` (12): `text_to_image` (label "Text-to-Image Arena
  Elo"), `image_editing`, `text_to_video`, `image_to_video`, `video_editing`,
  `text_to_speech`, `text_to_speech_controlled`, `music_instrumental`,
  `music_with_vocals`, `speech_to_text`, `speech_to_text_streaming`,
  `speech_to_speech` — with the user's phrasing as aliases where it differs, e.g.
  `text_to_speech` must answer to **"Provider Voice Arena Preference Elo"**, and
  `speech_to_speech` to **"Artificial Analysis Speech to Speech Index"**.
- The user's exact strings must resolve through `rankable()` **and** surface in
  `rankables(query=…)`:
  `"Artificial Analysis Intelligence Index"`, `"Speed"`, `"Cost per Task"`,
  `"Artificial Analysis Cyber Index"`, `"AA-3D"`, `"Provider Voice Arena Preference
  Elo"`, `"Artificial Analysis Speech to Speech Index"`, `"Terminal-Bench 4.0"`,
  `"Terminal-Bench-Science 0.1"`, `"FrontierCode 1.1"`, `"ITBench-AA"`,
  `"AA-Omniscience Index"`, `"Openness Index"`, `"Output Tokens per Intelligence
  Index Task"`.
- Version-suffix tolerance: `"Terminal-Bench 4.0"`, `"FrontierCode 1.1"`,
  `"Terminal-Bench-Science 0.1"`, `"AA-3D"` must match even though the keys have no
  version; implement by stripping a trailing `v?\d+(\.\d+)*` and normalising
  hyphens/spaces before matching (keep the exact strings as explicit aliases too, so a
  match never depends on the heuristic alone).
- `DOMAINS` must make domain search work for at least: `coding`, `math`, `science`,
  `security`, `agentic`, `tool-use`, `long-context`, `instruction-following`,
  `knowledge`, `reasoning`, `safety`, `multimodal`/`vision`, `speech`, `media`,
  `music`, `video`, `business`/`finance`, `legal`, `medical`, `engineering`,
  `economics`, `cost`, `speed`, `openness`. Each domain maps to the tags/tokens that
  expand it (e.g. `security` → `cyber`, `cweBench*`, `deepsec*`, `cybergym*`,
  `wildguard*`).
- `rankables()` filtering semantics: `query` = tokenised AND-match over
  key/label/aliases/desc/tags (reuse the tokenisation approach from
  `select.search`); `domain`/`tag` filter by expansion; all three combine.

Keep `BENCHMARKS`, `METRICS`, `metric()`, `format_value()`, `UNTRACKED_BENCHMARKS`
working exactly as today (additive only) and make sure `rankable()` falls back to
`metric()`/`BENCHMARKS` so a key that exists in either is always resolvable.

## Interaction with the sibling wave

Nothing here may change `Model`/`Endpoint`. The server wave adds `aa_pareto`, upgrades
`aa_compare` (up to 12 models, `metrics=all`, diff view, YAML `spec`) and rewrites
`aa_benchmarks` to search `RANKABLES`.

## Acceptance (paste evidence)

- `pytest -q` green; new tests for: every user string resolving via `rankable()`,
  version-suffix matching, domain expansion, `rankables(query="speech")` /
  `(domain="security")` results.
- A table in the report: `user string -> rankable key -> kind -> how`.
- `uvx ruff check src/aa_mcp/catalog.py` clean (or the remaining findings listed).
