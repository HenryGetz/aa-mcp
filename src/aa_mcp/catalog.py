"""Metric + benchmark registry and the single source of truth for formatting.

Everything here is plain Python data (no runtime dependency on the OpenAPI
fixture). Field names come from AA's public API vocabulary (``openapi.yaml``,
Pro ``Evaluations`` schema), the benchmarks reference in the skill metrics.md,
and the keys actually present in the captured RSC payloads.

``format_value`` is the only place user-visible numbers are rendered.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "Metric",
    "Benchmark",
    "METRICS",
    "BENCHMARKS",
    "UNTRACKED_BENCHMARKS",
    "FIELD_ALIASES",
    "VALUE_SOURCE",
    "metric",
    "benchmark",
    "format_value",
    "field_names",
]


@dataclass(frozen=True, slots=True)
class Metric:
    key: str
    label: str
    kind: str
    group: str
    desc: str
    better: str | None


@dataclass(frozen=True, slots=True)
class Benchmark:
    key: str
    label: str
    slug: str | None
    unit: str
    desc: str
    tags: tuple[str, ...]
    index_member: bool
    source_hint: str = "leaderboard"  # "leaderboard" | "rich" | "api" | "chart"


# --------------------------------------------------------------------------- #
# benchmarks
# --------------------------------------------------------------------------- #

# key, label, slug, unit, desc, tags, index_member
_B = [
    ("intelligence", "Intelligence", "artificial-analysis-intelligence-index", "index",
     "AA Intelligence Index v4.3.2 composite score.", ("index", "composite"), False),
    ("openness", "Openness", "artificial-analysis-openness-index", "index",
     "AA Openness Index: availability, transparency and licensing (0-100).", ("index", "openness"), False),
    ("coding", "Coding", None, "index",
     "AA Coding Index: composite weighted toward coding evaluations.", ("index", "coding"), False),
    ("agentic", "Agentic", None, "index",
     "AA Agentic Index: composite weighted toward agentic evaluations.", ("index", "agentic"), False),
    ("omniscience", "AA-Omniscience", "omniscience", "index",
     "AA-Omniscience Index: factual recall minus hallucination (roughly -70..+70).",
     ("knowledge", "hallucination", "intelligence-index"), True),
    ("omniscienceAccuracy", "Omni Accuracy", "omniscience", "%",
     "AA-Omniscience aggregate accuracy (fraction).", ("knowledge", "hallucination"), False),
    ("omniscienceNonHallucination", "Omni Non-Halluc", "omniscience", "%",
     "AA-Omniscience non-hallucination rate, 1 - hallucination (leaderboard field).",
     ("knowledge", "hallucination"), False),
    ("omniscienceHallucinationRate", "Omni Halluc", "omniscience", "%",
     "AA-Omniscience hallucination rate (chart/model-page field); lower is better.",
     ("knowledge", "hallucination"), False),
    ("gpqa", "GPQA Diamond", "gpqa-diamond", "%",
     "GPQA Diamond: hardest 198 graduate-level physics/chem/biology questions "
     "(PhD experts ~65%, non-experts ~34%).", ("science", "reasoning"), False),
    ("hle", "HLE", "humanitys-last-exam", "%",
     "Humanity's Last Exam: 2,500 expert-vetted frontier questions.",
     ("reasoning", "intelligence-index"), True),
    ("hleDiamond", "HLE Diamond", None, "%",
     "Diamond subset of Humanity's Last Exam (model pages only).", ("reasoning",), False),
    ("scicode", "SciCode", "scicode", "%",
     "SciCode: 288 scientist-curated coding subproblems from 80 lab problems.",
     ("coding", "science", "intelligence-index"), True),
    ("terminalBench21", "Terminal-Bench 2.1", "terminalbench-2-1", "%",
     "Terminal-Bench v2.1: 89 curated agentic terminal tasks.", ("agentic", "coding"), False),
    ("terminalbenchHard", "Terminal-Bench Hard", "terminalbench-hard", "%",
     "Harder agentic terminal subset.", ("agentic", "coding"), False),
    ("terminalBench40", "Terminal-Bench 4.0", "terminalbench-4-0", "%",
     "Terminal-Bench 4.0 agentic terminal tasks.", ("agentic", "coding", "intelligence-index"), True),
    ("terminalBenchScience", "Terminal-Bench Science", "terminal-bench-science", "%",
     "Terminal-Bench-Science 0.1 agentic science tasks.", ("agentic", "science"), False),
    ("tau2", "\u03c4\u00b2-Bench", "tau2-bench", "%",
     "\u03c4\u00b2-Bench telecom/retail tool-use agent benchmark.", ("agentic", "tool-use"), False),
    ("tauBanking", "\u03c4\u00b3-Banking", "tau3-banking", "%",
     "\u03c4\u00b3-Banking: fintech support with unstructured KB + tool calls.",
     ("agentic", "tool-use"), False),
    ("lcr", "AA-LCR", "artificial-analysis-long-context-reasoning", "%",
     "AA-LCR: long-context reasoning over 10k-100k-token documents.",
     ("reasoning", "long-context", "intelligence-index"), True),
    ("ifbench", "IFBench", "ifbench", "%",
     "IFBench: instruction-following on 58 verifiable out-of-domain constraints.",
     ("instruction-following",), False),
    ("critpt", "CritPt", "critpt", "%",
     "CritPt: 71 composite research-level physics reasoning challenges.",
     ("science", "reasoning", "intelligence-index"), True),
    ("mmmuPro", "MMMU-Pro", "mmmu-pro", "%",
     "MMMU-Pro: multimodal academic reasoning across 30 disciplines.",
     ("vision", "reasoning"), False),
    ("gdpval", "GDPval-AA Elo", "gdpval-aa", "Elo",
     "GDPval-AA v2.1 raw Elo (44 occupations, 9 industries, agentic).",
     ("agentic", "knowledge-work", "elo"), False),
    ("gdpvalNormalized", "GDPval-AA", "gdpval-aa", "%",
     "GDPval-AA v2.1 normalized 0-1 score used in the Intelligence Index.",
     ("agentic", "knowledge-work", "intelligence-index"), True),
    ("gdpPdfAllPass", "GDP.pdf", "gdp-pdf", "%",
     "GDP.pdf all-pass score.", ("agentic", "knowledge-work", "intelligence-index"), True),
    ("analystAgent", "AA-AnalystAgent", "aa-analyst-agent", "%",
     "AA-AnalystAgent: spreadsheet/document data-analysis tasks.", ("agentic", "knowledge-work"), False),
    ("apexAgents", "APEX-Agents-AA", "apex-agents-aa", "%",
     "APEX-Agents-AA: long-horizon cross-application professional-services tasks.",
     ("agentic",), False),
    ("itbenchSre", "ITBench-AA SRE", "itbench-aa", "%",
     "ITBench-AA (SRE): Kubernetes incident root-cause analysis.", ("agentic", "ops"), False),
    ("automationBenchPartialScore", "AutomationBench", "automationbench-aa", "%",
     "AutomationBench-AA partial score: agentic SaaS workflows without guardrail violations.",
     ("agentic", "tool-use", "intelligence-index"), True),
    ("briefcaseElo", "AA-Briefcase Elo", "aa-briefcase", "Elo",
     "AA-Briefcase v1.1: agentic knowledge-work benchmark, reported as Elo.",
     ("agentic", "knowledge-work", "elo", "intelligence-index"), True),
    ("aime25", "AIME 2025", "aime-2025", "%",
     "AIME 2025: 30 olympiad math problems (int answers 000-999).", ("math",), False),
    ("livecodebench", "LiveCodeBench", "livecodebench", "%",
     "LiveCodeBench: contamination-free competitive programming.", ("coding",), False),
    ("frontierCode", "FrontierCode", "frontiercode", "%",
     "FrontierCode 1.1 coding benchmark.", ("coding",), False),
    ("mlcrOverall", "MLCR-AA", "mlcr-aa", "%",
     "Medical Long Context Reasoning overall pass rate.", ("medical", "long-context"), False),
    ("harveyLab", "Harvey LAB-AA", "harvey-lab-aa", "%",
     "Harvey LAB-AA: 120 real legal-work tasks across 24 practice areas.",
     ("legal", "agentic"), False),
    ("enterpriseOpsGym", "EnterpriseOps-Gym", "enterprise-ops-gym-aa", "%",
     "EnterpriseOps-Gym-AA: ServiceNow enterprise multi-step stateful workflows.",
     ("agentic", "ops"), False),
    ("mmluPro", "MMLU-Pro", "mmlu-pro", "%",
     "MMLU-Pro knowledge and reasoning benchmark.", ("knowledge",), False),
    ("math500", "MATH-500", "math-500", "%",
     "MATH-500 competition mathematics problems.", ("math",), False),
    ("globalMmluLiteScore", "Global-MMLU-Lite", "global-mmlu-lite", "%",
     "Global-MMLU-Lite multilingual knowledge benchmark.", ("knowledge", "multilingual"), False),
    ("when2call", "When2Call", None, "%",
     "When2Call tool-calling decision benchmark (model pages only).", ("tool-use",), False),
    ("wildguardtest", "WildGuardTest", None, "%",
     "WildGuardTest safety/guardrail evaluation (model pages only).", ("safety",), False),
    ("cyberIndex", "AA Cyber Index", "artificial-analysis-cyber-index", "index",
     "AA Cyber Index capability composite (homepage panel).", ("cyber", "index"), False),
    ("cweBench", "CWE-Bench-AA", "cwe-bench-aa", "%",
     "CWE-Bench-AA cyber vulnerability benchmark (homepage panel).", ("cyber",), False),
    ("cybergymE2e", "CyberGym-E2E-AA", "cybergym-e2e-aa", "%",
     "CyberGym end-to-end cyber-range benchmark (homepage panel).", ("cyber",), False),
    ("deepsecBench", "DeepSecBench-AA", "deepsecbench-aa", "%",
     "DeepSecBench-AA deep security benchmark (homepage panel).", ("cyber",), False),
    ("aa3dElo", "AA-3D Elo", "aa-3d", "Elo",
     "AA-3D interactive 3D experience benchmark, reported as Elo.", ("media", "elo"), False),
    # Sub-scores / safety rates carried on eval-page records (audit 2026-10-14).
    ("mlcrAccuracy", "MLCR Accuracy", "mlcr-aa", "%",
     "MLCR-AA medical long-context reasoning: accuracy component.", ("medical", "long-context"), False),
    ("mlcrCompleteness", "MLCR Complete", "mlcr-aa", "%",
     "MLCR-AA medical long-context reasoning: completeness component.", ("medical", "long-context"), False),
    ("mlcrConciseness", "MLCR Concise", "mlcr-aa", "%",
     "MLCR-AA medical long-context reasoning: conciseness component.", ("medical", "long-context"), False),
    ("analystAgentPassAt1", "Analyst Pass@1", "aa-analyst-agent", "%",
     "AA-AnalystAgent pass@1 (single-attempt task success).", ("agentic", "knowledge-work"), False),
    ("analystAgentPassAtK", "Analyst Pass@k", "aa-analyst-agent", "%",
     "AA-AnalystAgent pass@k over repeated attempts.", ("agentic", "knowledge-work"), False),
    ("cweBenchRefusalRate", "CWE Refusal", "cwe-bench-aa", "%",
     "CWE-Bench-AA refusal rate; lower is better.", ("cyber", "safety"), False),
    ("cybergymE2eRefusalRate", "CyberGym Refusal", "cybergym-e2e-aa", "%",
     "CyberGym-E2E-AA refusal rate; lower is better.", ("cyber", "safety"), False),
    ("deepsecBenchRefusalRate", "DeepSec Refusal", "deepsecbench-aa", "%",
     "DeepSecBench-AA refusal rate; lower is better.", ("cyber", "safety"), False),
    ("capabilities.financeAndAccounting", "Cap Finance", None, "index",
     "AA capability index: finance and accounting (0-100).", ("capability",), False),
    ("capabilities.strategyAndOps", "Cap Strategy", None, "index",
     "AA capability index: strategy and operations (0-100).", ("capability",), False),
    ("capabilities.legal", "Cap Legal", None, "index",
     "AA capability index: legal (0-100).", ("capability",), False),
    ("capabilities.healthcareAndMedical", "Cap Medical", None, "index",
     "AA capability index: healthcare and medical (0-100).", ("capability",), False),
    ("capabilities.engineering", "Cap Engineering", None, "index",
     "AA capability index: engineering (0-100).", ("capability",), False),
    ("capabilities.economics", "Cap Economics", None, "index",
     "AA capability index: economics (0-100).", ("capability",), False),
    # Breakdown containers: present on model pages, no scalar data field of their own.
    ("briefcaseBreakdown", "Briefcase Breakdown", "aa-briefcase", "mixed",
     "AA-Briefcase sub-scores (rubric pass rate, analytical quality, presentation).",
     ("agentic", "breakdown"), False),
    ("automationBenchBreakdown", "AutomationBench Breakdown", "automationbench-aa", "mixed",
     "AutomationBench-AA sub-scores by domain.", ("agentic", "breakdown"), False),
    ("gdpvalBreakdown", "GDPval Breakdown", "gdpval-aa", "mixed",
     "GDPval-AA sub-scores across occupations/industries.", ("agentic", "breakdown"), False),
    ("harveyLabBreakdown", "Harvey Breakdown", "harvey-lab-aa", "mixed",
     "Harvey LAB-AA sub-scores by practice area.", ("legal", "breakdown"), False),
    ("gdpPdfBreakdown", "GDP.pdf Breakdown", "gdp-pdf", "mixed",
     "GDP.pdf sub-scores.", ("agentic", "breakdown"), False),
    ("aa3dBreakdown", "AA-3D Breakdown", "aa-3d", "mixed",
     "AA-3D sub-scores.", ("media", "breakdown"), False),
    ("enterpriseOpsGymSuccessRateByDomain", "EnterpriseOps By Domain",
     "enterprise-ops-gym-aa", "mixed",
     "EnterpriseOps-Gym-AA success rate by domain.", ("agentic", "breakdown"), False),
]

#: benchmark key -> best surface that yields a *cross-model* value.
#: Everything not listed defaults to "leaderboard" (the 700-row array).
_SOURCE_HINTS: dict[str, str] = {
    # only the keyed JSON API carries these composites
    "coding": "api",
    "agentic": "api",
    # present in the ~700 x 94 rich dataset (model pages), incl. derived fields
    "aime25": "rich",
    "automationBenchPartialScore": "rich",
    "briefcaseBreakdown": "rich",
    "briefcaseElo": "rich",
    "cweBench": "rich",
    "cyberIndex": "rich",
    "cybergymE2e": "rich",
    "deepsecBench": "rich",
    "enterpriseOpsGym": "rich",
    "frontierCode": "rich",
    "gdpPdfAllPass": "rich",
    "gdpval": "rich",
    "harveyLab": "rich",
    "hleDiamond": "rich",
    "livecodebench": "rich",
    "mlcrOverall": "rich",
    "omniscienceHallucinationRate": "rich",
    "openness": "rich",
    "terminalBenchScience": "rich",
    "capabilities.financeAndAccounting": "rich",
    "capabilities.strategyAndOps": "rich",
    "capabilities.legal": "rich",
    "capabilities.healthcareAndMedical": "rich",
    "capabilities.engineering": "rich",
    "capabilities.economics": "rich",
    # only the curated chart/eval-page sets carry these
    "aa3dBreakdown": "chart",
    "aa3dElo": "chart",
    "analystAgentPassAt1": "chart",
    "analystAgentPassAtK": "chart",
    "automationBenchBreakdown": "chart",
    "cweBenchRefusalRate": "chart",
    "cybergymE2eRefusalRate": "chart",
    "deepsecBenchRefusalRate": "chart",
    "enterpriseOpsGymSuccessRateByDomain": "chart",
    "gdpPdfBreakdown": "chart",
    "gdpvalBreakdown": "chart",
    "globalMmluLiteScore": "chart",
    "harveyLabBreakdown": "chart",
    "math500": "chart",
    "mlcrAccuracy": "chart",
    "mlcrCompleteness": "chart",
    "mlcrConciseness": "chart",
    "mmluPro": "chart",
    "when2call": "chart",
    "wildguardtest": "chart",
}

BENCHMARKS: dict[str, Benchmark] = {
    key: Benchmark(key, label, slug, unit, desc, tuple(tags), member,
                   _SOURCE_HINTS.get(key, "leaderboard"))
    for key, label, slug, unit, desc, tags, member in _B
}

#: Lowercased benchmark names AA does not track, with the closest thing AA measures.
#: Factual only — "AA does not track X" plus the nearest AA surface, no equivalence claim.
UNTRACKED_BENCHMARKS: dict[str, str] = {
    "mathvista": "AA does not track MathVista; visual reasoning is covered by MMMU-Pro "
                 "plus the per-model image/video input modality flags.",
    "docvqa": "AA does not track DocVQA; the closest document-style evaluation is "
              "GDP.pdf (with MMLU-Pro for broad knowledge).",
    "bfcl": "AA does not track BFCL (Berkeley Function Calling); tool use is covered by "
            "the per-endpoint functionCalling/jsonMode flags and by "
            "\u03c4\u00b2-Bench / \u03c4\u00b3-Banking.",
    "berkeley function calling": "AA does not track BFCL (Berkeley Function Calling); "
            "tool use is covered by the per-endpoint functionCalling/jsonMode flags and "
            "by \u03c4\u00b2-Bench / \u03c4\u00b3-Banking.",
    "human eval": "AA does not track HumanEval; the closest coding evaluation is "
                  "LiveCodeBench (also SciCode / FrontierCode).",
    "humaneval": "AA does not track HumanEval; the closest coding evaluation is "
                 "LiveCodeBench (also SciCode / FrontierCode).",
    "mbpp": "AA does not track MBPP; the closest coding evaluation is LiveCodeBench.",
    "chatbot arena": "AA does not track Chatbot Arena; human preference is measured in "
                     "AA's own media/agent arenas and via the AA-Briefcase Elo.",
    "lmsys arena": "AA does not track the LMArena/LMSYS arena; human preference is "
                   "measured in AA's own media/agent arenas and via the AA-Briefcase Elo.",
    "mt-bench": "AA does not track MT-Bench; the closest instruction-following "
                "evaluation is IFBench.",
    "alpaca eval": "AA does not track AlpacaEval; the closest agentic knowledge-work "
                   "evaluation is the AA-Briefcase Elo.",
}


# --------------------------------------------------------------------------- #
# metrics
# --------------------------------------------------------------------------- #

# key, label, kind, group, desc, better
_M = [
    ("name", "Model", "str", "identity", "Model display name.", None),
    ("creator", "Creator", "str", "identity", "Model creator / lab.", None),
    ("slug", "Slug", "str", "identity", "AA model slug (round-trippable identifier).", None),
    ("release_date", "Released", "date", "identity", "Release date (YYYY-MM-DD).", None),
    ("knowledge_cutoff", "Cutoff", "date", "identity", "Training knowledge cutoff date.", None),
    ("context_tokens", "Ctx", "tokens", "identity", "Context window in tokens.", "high"),
    ("params_b", "Params", "int", "identity", "Total parameters (billions).", None),
    ("active_params_b", "Active", "int", "identity", "Active parameters for MoE models (billions).", None),
    ("size_class", "Size", "str", "identity", "AA parameter/size class.", None),
    ("license", "License", "str", "identity", "License name (open-weights models).", None),
    ("is_open_weights", "Open", "bool", "identity", "Whether weights are openly available.", None),
    ("is_reasoning", "Reasoning", "bool", "identity", "Whether the model is a reasoning model.", None),
    ("effort", "Effort", "str", "identity", "Reasoning effort label (low..max).", None),
    ("deprecated", "Depr.", "bool", "identity", "Whether the model is deprecated.", None),
    ("deprecated_to", "Depr. to", "str", "identity", "Slug the model is deprecated to.", None),
    ("estimated", "Est.", "bool", "index", "Intelligence score is an AA estimate (marked *).", None),
    ("intelligence", "Intel", "index", "index", "AA Intelligence Index v4.3.2 (0-100).", "high"),
    ("coding", "Coding", "index", "index", "AA Coding Index (0-100).", "high"),
    ("agentic", "Agentic", "index", "index", "AA Agentic Index (0-100).", "high"),
    ("openness", "Openness", "index", "index", "AA Openness Index (0-100).", "high"),
    ("omniscience", "Omniscience", "index", "index",
     "AA-Omniscience Index (roughly -70..+70).", "high"),
    ("cost_per_task", "Cost", "usd", "pricing",
     "AA measured cost of one Intelligence Index task (cache-aware).", "low"),
    ("price_in", "In $/M", "usd", "pricing", "Input price, USD per 1M tokens.", "low"),
    ("price_out", "Out $/M", "usd", "pricing", "Output price, USD per 1M tokens.", "low"),
    ("cache_read", "CacheRd $/M", "usd", "pricing", "Cached-input read price, USD per 1M tokens.", "low"),
    ("cache_write", "CacheWr $/M", "usd", "pricing", "Cache write price, USD per 1M tokens.", "low"),
    ("cache_hit_discount", "Cache disc.", "pct", "pricing",
     "Cache-read discount versus input price (fraction).", "high"),
    ("blended_0_3_1", "Blend 0:3:1", "usd", "pricing", "Blended price at 0:3:1 input:output ratio.", "low"),
    ("blended_7_2_1", "Blend 7:2:1", "usd", "pricing", "Blended price at 7:2:1 input:output ratio.", "low"),
    ("blended_0_1_1", "Blend 0:1:1", "usd", "pricing", "Blended price at 0:1:1 input:output ratio.", "low"),
    ("blended_100_1_1", "Blend 100:1:1", "usd", "pricing", "Blended price at 100:1:1 input:output ratio.", "low"),
    ("blended_0_100_1", "Blend 0:100:1", "usd", "pricing", "Blended price at 0:100:1 input:output ratio.", "low"),
    ("tps", "tok/s", "tps", "speed", "Median output speed in tokens/second.", "high"),
    ("ttft", "TTFT", "sec", "speed", "Median time to first token (seconds).", "low"),
    ("ttfa", "TTFA", "sec", "speed", "Median time to first answer token (seconds).", "low"),
    ("e2e", "E2E", "sec", "speed", "Median end-to-end response time (seconds).", "low"),
    ("reasoning_s", "Reason s", "sec", "speed", "Median reasoning phase duration (seconds).", "low"),
    ("out_tokens_per_task", "Tok/task", "tokens", "speed",
     "Output tokens per Intelligence Index task (verbosity); lower is leaner.", "low"),
    ("tps_p05", "tok/s p05", "tps", "speed",
     "5th-percentile output speed (tokens/second).", "high"),
    ("tps_q25", "tok/s q25", "tps", "speed",
     "25th-percentile output speed (tokens/second).", "high"),
    ("tps_q75", "tok/s q75", "tps", "speed",
     "75th-percentile output speed (tokens/second).", "high"),
    ("tps_p95", "tok/s p95", "tps", "speed",
     "95th-percentile output speed (tokens/second).", "high"),
    ("ttft_p05", "TTFT p05", "sec", "speed",
     "5th-percentile time to first token (seconds).", "low"),
    ("ttft_q25", "TTFT q25", "sec", "speed",
     "25th-percentile time to first token (seconds).", "low"),
    ("ttft_q75", "TTFT q75", "sec", "speed",
     "75th-percentile time to first token (seconds).", "low"),
    ("ttft_p95", "TTFT p95", "sec", "speed",
     "95th-percentile time to first token (seconds).", "low"),
]

METRICS: dict[str, Metric] = {}
for _key, _label, _kind, _group, _desc, _better in _M:
    METRICS[_key] = Metric(_key, _label, _kind, _group, _desc, _better)

# Benchmark metrics (scalar data fields living in Model.evals / .indices).
_UNIT_KIND = {"%": "pct", "Elo": "elo", "index": "index", "s": "sec",
              "tok/s": "tps", "USD/task": "usd", "mixed": "str"}
_LOWER_IS_BETTER = {
    "omniscienceHallucinationRate",
    "cweBenchRefusalRate",
    "cybergymE2eRefusalRate",
    "deepsecBenchRefusalRate",
}
for _b in BENCHMARKS.values():
    if _b.unit == "mixed":
        continue
    if _b.key in METRICS:
        continue
    _kind = _UNIT_KIND.get(_b.unit, "str")
    _group = "index" if _b.unit == "index" else "eval"
    _better = "low" if _b.key in _LOWER_IS_BETTER else "high"
    METRICS[_b.key] = Metric(_b.key, _b.label[:12], _kind, _group, _b.desc, _better)


# --------------------------------------------------------------------------- #
# value lookup sources (used by select.py)
# --------------------------------------------------------------------------- #

# metric key -> (Model attribute holding a dict, dict key)
VALUE_SOURCE: dict[str, tuple[str, str]] = {
    "price_in": ("pricing", "in"),
    "price_out": ("pricing", "out"),
    "cache_read": ("pricing", "cache_read"),
    "cache_write": ("pricing", "cache_write"),
    "cache_hit_discount": ("pricing", "cache_hit_discount"),
    "blended_0_3_1": ("pricing", "blended_0_3_1"),
    "blended_7_2_1": ("pricing", "blended_7_2_1"),
    "blended_0_1_1": ("pricing", "blended_0_1_1"),
    "blended_100_1_1": ("pricing", "blended_100_1_1"),
    "blended_0_100_1": ("pricing", "blended_0_100_1"),
    "tps": ("speed", "tps"),
    "ttft": ("speed", "ttft"),
    "ttfa": ("speed", "ttfa"),
    "e2e": ("speed", "e2e"),
    "reasoning_s": ("speed", "reasoning_s"),
    "out_tokens_per_task": ("speed", "out_tokens_per_task"),
    "tps_p05": ("speed", "tps_p05"),
    "tps_q25": ("speed", "tps_q25"),
    "tps_q75": ("speed", "tps_q75"),
    "tps_p95": ("speed", "tps_p95"),
    "ttft_p05": ("speed", "ttft_p05"),
    "ttft_q25": ("speed", "ttft_q25"),
    "ttft_q75": ("speed", "ttft_q75"),
    "ttft_p95": ("speed", "ttft_p95"),
}


# --------------------------------------------------------------------------- #
# aliases
# --------------------------------------------------------------------------- #

_SHORTHANDS = {
    "intel": "intelligence",
    "int": "intelligence",
    "iq": "intelligence",
    "cost": "cost_per_task",
    "cpt": "cost_per_task",
    "price": "price_in",
    "in": "price_in",
    "out": "price_out",
    "input": "price_in",
    "output": "price_out",
    "cacheread": "cache_read",
    "cachewrite": "cache_write",
    "ttft": "ttft",
    "tps": "tps",
    "speed": "tps",
    "latency": "ttft",
    "ctx": "context_tokens",
    "context": "context_tokens",
    "params": "params_b",
    "param": "params_b",
    "open": "is_open_weights",
    "openweights": "is_open_weights",
    "reasoning": "is_reasoning",
    "n": "name",
    "model": "name",
    "released": "release_date",
    "date": "release_date",
    "elo": "briefcaseElo",
}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


FIELD_ALIASES: dict[str, str] = {}


def _add_alias(alias: str, key: str) -> None:
    alias = alias.strip()
    if alias and alias not in FIELD_ALIASES:
        FIELD_ALIASES[alias] = key


for _b in BENCHMARKS.values():
    for _a in (_b.key, _b.label, _b.slug, _b.label.replace(" ", "-"),
               _b.label.replace(" ", "_"), _b.key.replace("_", "-")):
        if _a:
            _add_alias(_a, _b.key)

for _m in METRICS.values():
    for _a in (_m.key, _m.label, _m.key.replace("_", "-"), _m.key.replace("_", "")):
        _add_alias(_a, _m.key)

for _alias, _key in _SHORTHANDS.items():
    FIELD_ALIASES[_alias] = _key

# Field names as they appear in AA's public OpenAPI vocabulary (openapi.yaml).
_OPENAPI_ALIASES = {
    "artificial_analysis_intelligence_index": "intelligence",
    "artificial_analysis_intelligence_index_cost": "cost_per_task",
    "artificial_analysis_coding_index": "coding",
    "artificial_analysis_agentic_index": "agentic",
    "artificial_analysis_openness_index": "openness",
    "artificial_analysis_finance_and_accounting_index": "capabilities.financeAndAccounting",
    "artificial_analysis_strategy_and_ops_index": "capabilities.strategyAndOps",
    "artificial_analysis_legal_index": "capabilities.legal",
    "artificial_analysis_healthcare_and_medical_index": "capabilities.healthcareAndMedical",
    "artificial_analysis_engineering_index": "capabilities.engineering",
    "artificial_analysis_economics_index": "capabilities.economics",
    "tau2_telecom": "tau2",
    "tau_banking": "tauBanking",
    "terminalbench_hard": "terminalbenchHard",
    "terminalbench_v2_1": "terminalBench21",
    "terminalbench_v4_0": "terminalBench40",
    "terminalbench_science": "terminalBenchScience",
    "aa_briefcase_elo": "briefcaseElo",
    "automationbench_aa": "automationBenchPartialScore",
    "gdp_pdf": "gdpPdfAllPass",
    "aa_lcr": "lcr",
    "aa_omniscience_index": "omniscience",
    "aa_omniscience_accuracy": "omniscienceAccuracy",
    "aa_omniscience_non_hallucination_rate": "omniscienceNonHallucination",
    "gpqa_diamond": "gpqa",
    "gdpval_aa_elo": "gdpval",
    "gdpval_aa_normalized": "gdpvalNormalized",
    "mmmu_pro": "mmmuPro",
    "mlcr_overall": "mlcrOverall",
    "price_1m_input_tokens": "price_in",
    "price_1m_output_tokens": "price_out",
}
for _alias, _key in _OPENAPI_ALIASES.items():
    if _key in METRICS or _key in BENCHMARKS:
        FIELD_ALIASES[_alias] = _key

_ALIAS_NORM: dict[str, str] = {}
for _alias, _key in FIELD_ALIASES.items():
    _ALIAS_NORM.setdefault(_norm(_alias), _key)
for _key in METRICS:
    _ALIAS_NORM.setdefault(_norm(_key), _key)
for _key in BENCHMARKS:
    _ALIAS_NORM.setdefault(_norm(_key), _key)
for _alias, _key in _SHORTHANDS.items():
    _ALIAS_NORM[_norm(_alias)] = _key


def _resolve_key(key_or_alias: str) -> str | None:
    if not key_or_alias:
        return None
    k = key_or_alias.strip()
    if k in METRICS or k in BENCHMARKS:
        return k
    return _ALIAS_NORM.get(_norm(k))


def metric(key_or_alias: str) -> Metric | None:
    """Look up a metric by canonical key, alias, label or shorthand."""
    k = _resolve_key(key_or_alias)
    return METRICS.get(k) if k else None


def benchmark(key_or_alias: str) -> Benchmark | None:
    """Look up a benchmark by key, alias, label or eval-page slug."""
    k = _resolve_key(key_or_alias)
    return BENCHMARKS.get(k) if k else None


def field_names() -> list[str]:
    """All accepted field aliases (for ``--fields`` help)."""
    return sorted(FIELD_ALIASES.keys())


# --------------------------------------------------------------------------- #
# formatting
# --------------------------------------------------------------------------- #

def _infer_kind(value) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "int"
    return "str"


def _compact_tokens(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.0f}k"
    return str(int(value))


def format_value(key: str, value) -> str:
    """Format ``value`` for display according to the metric ``key``'s kind."""
    if value is None:
        return "-"
    m = metric(key)
    kind = m.kind if m else None
    if kind is None:
        b = benchmark(key)
        if b:
            kind = _UNIT_KIND.get(b.unit)
    if kind is None:
        kind = _infer_kind(value)

    try:
        if kind == "pct":
            return f"{float(value) * 100:.1f}%"
        if kind == "elo":
            return f"{float(value):.0f}"
        if kind == "index":
            return f"{float(value):.1f}"
        if kind == "usd":
            v = float(value)
            if 0 < abs(v) < 0.01:
                return f"${v:.4f}"
            return f"${v:.2f}"
        if kind == "tps":
            return f"{float(value):.1f}"
        if kind == "sec":
            return f"{float(value):.1f}s"
        if kind == "tokens":
            return _compact_tokens(float(value))
        if kind == "int":
            return f"{int(round(float(value))):,}"
        if kind == "bool":
            return "yes" if value else "no"
    except (TypeError, ValueError):
        return str(value)
    return str(value)
