"""Metric + benchmark registry and the single source of truth for formatting.

Everything here is plain Python data (no runtime dependency on any fixture).
Field names come from AA's published API vocabulary (its ``/api-reference``
schema), the benchmarks reference in the skill metrics.md, and the keys actually
present in the captured RSC payloads under ``tests/fixtures/``
(``leaderboard.rsc``, ``model_page_chart.rsc``, ``home.rsc``,
``capability_legal.rsc``, ``eval_index_openness.rsc``, ``eval_index_decision.rsc``).

``format_value`` is the only place user-visible numbers are rendered.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

__all__ = [
    "BENCHMARKS",
    "DOMAINS",
    "ENTERPRISE_OPS_DOMAINS",
    "FIELD_ALIASES",
    "METRICS",
    "MOBILE_EVALS",
    "MULTILINGUAL_LANGS",
    "OMNISCIENCE_DOMAINS",
    "OMNISCIENCE_LANGS",
    "OPENNESS_COMPONENTS",
    "RANKABLES",
    "TASK_DOMAINS",
    "TBSCIENCE_DOMAINS",
    "UNTRACKED_BENCHMARKS",
    "VALUE_SOURCE",
    "Benchmark",
    "Metric",
    "Rankable",
    "benchmark",
    "field_names",
    "format_value",
    "metric",
    "rankable",
    "rankables",
    "task_domain",
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
    #: best free surface for a cross-model value:
    #: "leaderboard" (700-row array) | "rich" (~700-model model-page dataset) |
    #: "chart" (eval-page chart set / homepage panel) | "board" (arena board) |
    #: "none" (AA publishes it only through its paid data API — no public page).
    source_hint: str = "leaderboard"


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
    ("decisionIndex", "AA Decision Index", None, "index",
     "AA Decision Index: weighted average of AA-Omniscience-Decision, "
     "HLE-MultiChoice, When2Call and WildGuardTest across decision models.",
     ("index", "decision"), False),
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
     ("GPQA Diamond: hardest 198 graduate-level physics/chem/biology questions "
      "(PhD experts ~65%, non-experts ~34%)."), ("science", "reasoning"), False),
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
     "Global-MMLU-Lite multilingual knowledge benchmark; charted on both "
     "/evaluations/global-mmlu-lite and /models/multilingual, which overlap "
     "(gemini-3-pro is on both) for a 17-model union.",
     ("knowledge", "multilingual"), False),
    ("when2call", "When2Call", "when2call", "%",
     "When2Call tool-calling decision benchmark (28-row decision-model table).",
     ("tool-use", "decision"), False),
    ("wildguardtest", "WildGuardTest", "wildguardtest", "%",
     "WildGuardTest safety/guardrail evaluation (28-row decision-model table).",
     ("safety", "decision"), False),
    ("cyberIndex", "AA Cyber Index", "artificial-analysis-cyber-index", "index",
     "AA Cyber Index capability composite (homepage panel).", ("cyber", "index"), False),
    ("cweBench", "CWE-Bench-AA", "cwe-bench-aa", "%",
     "CWE-Bench-AA cyber vulnerability benchmark (homepage panel).", ("cyber",), False),
    ("cybergymE2e", "CyberGym-E2E-AA", "cybergym-e2e-aa", "%",
     "CyberGym end-to-end cyber-range benchmark (homepage panel).", ("cyber",), False),
    ("deepsecBench", "DeepSecBench-AA", "deepsecbench-aa", "%",
     "DeepSecBench-AA deep security benchmark (homepage panel).", ("cyber",), False),
    # Companion metrics AA publishes beside the Cyber Index on the same panel /
    # eval chart set (wave F): the refusal rate and the mitigation status.
    ("cyberRefusalRate", "Cyber Refusal", "artificial-analysis-cyber-index", "%",
     "AA Cyber Index refusal rate; lower is better.", ("cyber", "safety"), False),
    ("cyberMitigationStatus", "Cyber Mitigation", "artificial-analysis-cyber-index", "text",
     "AA Cyber Index mitigation status (standard/unmitigated), published on the "
     "homepage panel and eval chart set.", ("cyber", "safety"), False),
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
    # The Decision-Models family: four ``/evaluations/<slug>`` pages that ship one
    # shared 28-row table (``indexScore`` + a ``scores`` map).  AA-Omniscience-
    # Decision and HLE-MultiChoice had no entry at all; When2Call and WildGuardTest
    # existed but carried no slug, so no surface could be found for them.
    ("hleMultichoice", "HLE-MultiChoice", "hle-multichoice", "%",
     "Humanity's Last Exam text multiple-choice subset, scored across AA's "
     "decision-model cohort (28 contestants).", ("reasoning", "decision"), False),
    ("omniscienceDecision", "AA-Omniscience-Decision", "aa-omniscience-decision", "%",
     "AA-Omniscience accuracy on the decision-model cohort (factual recall on "
     "decision tasks).", ("knowledge", "hallucination", "decision"), False),
    ("omniscienceDecisionNonHallucination", "Omniscience-Decision Non-Halluc",
     "aa-omniscience-decision", "%",
     "AA-Omniscience non-hallucination rate on the decision-model cohort.",
     ("knowledge", "hallucination", "decision"), False),
    # The Multilingual Index lives on ``/models/multilingual`` (AA's OpenAPI calls
    # it ``artificial_analysis_multilingual_index``); the same page also carries the
    # per-language split and a 13-row ``globalMmluLite`` that is wider than the
    # 5-row ``/evaluations/global-mmlu-lite`` chart set.
    ("multilingual", "Multilingual Index", "multilingual", "%",
     "AA Multilingual Index: mean accuracy across 16 languages (Global-MMLU-Lite).",
     ("multilingual", "knowledge"), False),
]

#: Multilingual Index languages: payload key -> display name.  The per-language
#: scores are registered as rankables (``multilingual.<code>``) and flattened by
#: :mod:`aa_mcp.normalize`, so both sides read the same table.
MULTILINGUAL_LANGS: dict[str, str] = {
    "ar": "Arabic", "bn": "Bengali", "de": "German", "en": "English",
    "es": "Spanish", "fr": "French", "hi": "Hindi", "id": "Indonesian",
    "it": "Italian", "ja": "Japanese", "ko": "Korean", "pt": "Portuguese",
    "sw": "Swahili", "yo": "Yoruba", "zh": "Chinese", "my": "Burmese",
}

#: AA-Omniscience per-domain slices (``omniscienceBreakdown.byDomain``):
#: payload key -> (key slug, display name).
OMNISCIENCE_DOMAINS: dict[str, tuple[str, str]] = {
    "Business": ("business", "Business"),
    "Health": ("health", "Health"),
    "Humanities & Social Sciences": ("humanitiesAndSocialSciences",
                                     "Humanities & Social Sciences"),
    "Law": ("law", "Law"),
    "Science, Engineering & Mathematics": ("scienceAndEngineering",
                                           "Science, Engineering & Mathematics"),
    "Software Engineering (SWE)": ("softwareEngineering", "Software Engineering (SWE)"),
}

#: AA-Omniscience per-SWE-language slices (``omniscienceBreakdown.bySweLanguage``):
#: payload key -> display name (the eval key is the lowercased key).
OMNISCIENCE_LANGS: dict[str, str] = {
    "C": "C", "R": "R", "Go": "Go", "PHP": "PHP", "Dart": "Dart", "HTML": "HTML",
    "Java": "Java", "Rust": "Rust", "Julia": "Julia", "Swift": "Swift",
    "Kotlin": "Kotlin", "Python": "Python", "JavaScript": "JavaScript",
    "TypeScript": "TypeScript",
}

#: AA Openness Index components (``opennessBreakdown``): payload key -> display
#: name (the eval key is ``openness.<payload key>``).
OPENNESS_COMPONENTS: dict[str, str] = {
    "modelAvailability": "Model availability",
    "modelTransparency": "Model transparency",
    "transparencyPreTrainingData": "Pre-training data transparency",
    "transparencyPostTrainingData": "Post-training data transparency",
    "transparencyMethodology": "Methodology transparency",
    "dataPretrainAccess": "Pre-training data access",
    "dataPretrainLicense": "Pre-training data license",
    "dataPosttrainAccess": "Post-training data access",
    "dataPosttrainLicense": "Post-training data license",
}

#: Terminal-Bench-Science domains (``terminalBenchSciencePassRateByDomain``):
#: payload key -> display name (the eval key keeps the payload's kebab slug).
TBSCIENCE_DOMAINS: dict[str, str] = {
    "life-sciences": "Life sciences",
    "physical-sciences": "Physical sciences",
    "mathematical-sciences": "Mathematical sciences",
    "engineering-sciences": "Engineering sciences",
    "earth-sciences": "Earth sciences",
}

#: EnterpriseOps-Gym domains (``enterpriseOpsGymSuccessRateByDomain``).
ENTERPRISE_OPS_DOMAINS: dict[str, str] = {
    "csm": "CSM", "hr": "HR", "itsm": "ITSM", "email": "Email",
    "calendar": "Calendar", "teams": "Teams", "drive": "Drive", "hybrid": "Hybrid",
}

#: The on-device benchmark set (``/hardware-inference-stack/mobile-phones``):
#: ``evalScores`` key -> display name.  The eval keys are namespaced
#: (``mobile.<key>``) so an on-device quantised run never mixes into the
#: first-party leaderboard column of the same evaluation.
MOBILE_EVALS: dict[str, str] = {
    "gpqa": "GPQA Diamond",
    "ifbench": "IFBench",
    "ifstruct": "IFStruct",
    "math_500": "MATH-500",
    "omniscience": "AA-Omniscience",
    "bfcl_500": "BFCL-500",
    "bfcl_small": "BFCL-Small",
}


#: Benchmark rows for AA's per-model breakdown sub-scores.  AA publishes several
#: benchmarks as a per-model *map* of sub-scores rather than a flat column; each
#: scalar in those maps is registered as its own rankable so the breakdown is not
#: merely readable on one model page but rankable across models — the treatment
#: the refusal rates, pass@k siblings and capability sub-scores already get.
#: Every row is a chart-set value (``slug`` names the page that carries it), so
#: ``source_hint`` is filled in below.
_SUBSCORES: list[tuple] = []
# Multilingual Index per language (``multilingual.<code>``).
for _code, _name in MULTILINGUAL_LANGS.items():
    _SUBSCORES.append((
        f"multilingual.{_code}", f"Multilingual {_name}", "multilingual", "%",
        f"Multilingual Index accuracy in {_name} (Global-MMLU-Lite).",
        ("multilingual", "language"), False,
    ))
# Openness Index components (``openness.<component>``).
for _comp, _name in OPENNESS_COMPONENTS.items():
    _SUBSCORES.append((
        f"openness.{_comp}", f"Openness · {_name}",
        "artificial-analysis-openness-index", "index",
        f"AA Openness Index component: {_name} (0-100).",
        ("openness", "index", "openness-component"), False,
    ))
# AA-Omniscience per-domain and per-SWE-language slices.
for _raw, (_slug, _name) in OMNISCIENCE_DOMAINS.items():
    _SUBSCORES.append((
        f"omniscience.domain.{_slug}", f"Omniscience · {_name}", "omniscience", "index",
        f"AA-Omniscience Index on the {_name} domain (same scale as the headline index).",
        ("knowledge", "hallucination", "domain"), False,
    ))
for _raw, _name in OMNISCIENCE_LANGS.items():
    _SUBSCORES.append((
        f"omniscience.language.{_raw.lower()}", f"Omniscience · {_name}",
        "omniscience", "index",
        f"AA-Omniscience Index on {_name} software-engineering questions.",
        ("knowledge", "coding", "language"), False,
    ))
# Terminal-Bench-Science and EnterpriseOps-Gym domain splits.
for _dom, _name in TBSCIENCE_DOMAINS.items():
    _SUBSCORES.append((
        f"terminalBenchScience.domain.{_dom}", f"TB-Science · {_name}",
        "terminal-bench-science", "%",
        f"Terminal-Bench-Science 0.1 pass rate on {_name} tasks.",
        ("agentic", "science", "domain"), False,
    ))
for _dom, _name in ENTERPRISE_OPS_DOMAINS.items():
    _SUBSCORES.append((
        f"enterpriseOpsGym.domain.{_dom}", f"EnterpriseOps · {_name}",
        "enterprise-ops-gym-aa", "%",
        f"EnterpriseOps-Gym-AA success rate on the {_name} domain.",
        ("agentic", "ops", "domain"), False,
    ))
# The on-device benchmark set (namespaced so it never mixes into the leaderboard
# column of the same evaluation).
for _name, _label in MOBILE_EVALS.items():
    _SUBSCORES.append((
        f"mobile.{_name}", f"On-device {_label}", "mobile", "%",
        f"{_label} run on-device by AA's mobile benchmark set (quantised weights, "
        "bounded context).",
        ("mobile", "on-device", "local"), False,
    ))
# Headline scalars inside the breakdown maps.
_SUBSCORES.extend([
    ("briefcaseAnalyticalQualityElo", "Briefcase Analytical Elo", "aa-briefcase", "Elo",
     "AA-Briefcase analytical-quality Elo (sub-score of the AA-Briefcase Elo).",
     ("agentic", "knowledge-work", "elo"), False),
    ("briefcasePresentationElo", "Briefcase Presentation Elo", "aa-briefcase", "Elo",
     "AA-Briefcase presentation-quality Elo (sub-score of the AA-Briefcase Elo).",
     ("agentic", "knowledge-work", "elo"), False),
    ("briefcaseRubricPassRate", "Briefcase Rubric Pass", "aa-briefcase", "%",
     "AA-Briefcase rubric pass rate (share of rubric criteria met).",
     ("agentic", "knowledge-work"), False),
    ("harveyCriteriaPass", "Harvey Criteria Pass", "harvey-lab-aa", "%",
     "Harvey LAB-AA share of rubric criteria passed.",
     ("legal", "agentic"), False),
    ("harveyGatedAllPass", "Harvey Gated All-Pass", "harvey-lab-aa", "%",
     "Harvey LAB-AA share of tasks passing every gated criterion.",
     ("legal", "agentic"), False),
    ("gdpPdfMacroPassRate", "GDP.pdf Macro Pass", "gdp-pdf", "%",
     "GDP.pdf macro-criterion pass rate (fraction of document-level criteria met).",
     ("agentic", "knowledge-work"), False),
    ("automationBenchStrictScore", "AutomationBench Strict", "automationbench-aa", "%",
     "AutomationBench-AA strict score (full task completion without violations).",
     ("agentic", "tool-use"), False),
    ("automationBenchCompletion", "AutomationBench Completion", "automationbench-aa", "%",
     "AutomationBench-AA task completion rate (guardrail violations ignored).",
     ("agentic", "tool-use"), False),
    ("gdpvalAvgTurns", "GDPval Avg Turns", "gdpval-aa", "index",
     "Mean agent turns per GDPval-AA task.",
     ("agentic", "knowledge-work"), False),
    ("itbenchAvgTurnsPerTask", "ITBench Avg Turns", "itbench-aa", "index",
     "Mean agent turns per ITBench-AA (SRE) task.",
     ("agentic", "ops"), False),
    ("enterpriseOpsGymAvgTurns", "EnterpriseOps Avg Turns", "enterprise-ops-gym-aa", "index",
     "Mean conversation turns per EnterpriseOps-Gym-AA task.",
     ("agentic", "ops"), False),
    ("aa3dTurnsP50", "AA-3D Median Turns", "aa-3d", "index",
     "Median agent turns to build one AA-3D experience.",
     ("media", "agentic"), False),
    ("medianCanonicalAnswerOutputSpeed", "Answer Output Speed",
     "artificial-analysis-intelligence-index", "tok/s",
     "Median output speed (tokens/s) on the Intelligence Index answer phase.",
     ("speed",), False),
])
_B.extend(_SUBSCORES)

#: Per-model metric columns of the speech / TTS / search boards.  Each board page
#: publishes a table rather than an eval chart set, so ``loaders.parse_chart``
#: adapts its rows (``_CHART_ADAPTERS``) and these keys are ranked through the same
#: chart-set path as every other published column.
_BOARD_METRICS: list[tuple] = [
    # /speech-to-text/non-streaming (36 rows)
    ("sttWerIndex", "STT WER Index", "stt", "%",
     "AA-WER Index for speech-to-text: aggregate word error rate across AA's "
     "transcription datasets; lower is better.", ("speech", "wer", "stt"), False),
    ("sttWordErrorRate", "STT Word Error Rate", "stt", "%",
     "Word error rate on the model's own transcription dataset, as published on "
     "AA's speech-to-text board; lower is better.", ("speech", "wer", "stt"), False),
    ("sttEarnings22Wer", "STT Earnings22 WER", "stt", "%",
     "Word error rate on Earnings22-Cleaned-AA (earnings-call audio); lower is better.",
     ("speech", "wer", "stt"), False),
    ("sttVoxpopuliWer", "STT VoxPopuli WER", "stt", "%",
     "Word error rate on VoxPopuli-Cleaned-AA (parliamentary speech); lower is better.",
     ("speech", "wer", "stt"), False),
    ("sttAgenttalkWer", "STT AgentTalk WER", "stt", "%",
     "Word error rate on AA-AgentTalk (agentic voice transcripts); lower is better.",
     ("speech", "wer", "stt"), False),
    # /speech-to-text/streaming (45 rows)
    ("sttStreamingWerIndex", "STT Stream WER Idx", "stt_streaming", "%",
     "AA-WER streaming index: word error rate of the streaming transcript; "
     "lower is better.", ("speech", "wer", "stt", "streaming"), False),
    ("sttStreamingEarnings22Wer", "Stream Earnings22", "stt_streaming", "%",
     "Streaming word error rate on Earnings22-Cleaned-AA; lower is better.",
     ("speech", "wer", "stt", "streaming"), False),
    ("sttStreamingAgenttalkWer", "Stream AgentTalk", "stt_streaming", "%",
     "Streaming word error rate on AA-AgentTalk; lower is better.",
     ("speech", "wer", "stt", "streaming"), False),
    ("sttStreamingTimeToFinal", "Stream Final Time", "stt_streaming", "s",
     "Seconds from end of speech to the final transcript; lower is better.",
     ("speech", "latency", "stt", "streaming"), False),
    ("sttStreamingTimeToFirstPartial", "Stream 1st Partial", "stt_streaming", "s",
     "Seconds from end of speech to the first partial transcript; lower is better.",
     ("speech", "latency", "stt", "streaming"), False),
    # /speech-to-speech/arena (80 rows across three slices)
    ("sts", "STS Index", "sts", "index",
     "Artificial Analysis Speech to Speech Index (0-100) over the arena's "
     "overall slice.", ("speech", "index", "sts", "realtime-voice"), False),
    ("stsOverallElo", "STS Overall Elo", "sts", "Elo",
     "Arena Elo on the STS overall slice (human pairwise preference).",
     ("speech", "elo", "sts"), False),
    ("stsAgenticElo", "STS Agentic Elo", "sts", "Elo",
     "Arena Elo on the STS agentic slice (agentic voice tasks).",
     ("speech", "elo", "sts", "agentic"), False),
    ("stsNonAgenticElo", "STS Non-Agentic Elo", "sts", "Elo",
     "Arena Elo on the STS non-agentic slice (plain conversation).",
     ("speech", "elo", "sts"), False),
    ("stsTaskCompletionRate", "STS Task %", "sts", "%",
     "Share of STS arena tasks the model completed successfully.",
     ("speech", "sts", "agentic"), False),
    ("stsBigBenchAudio", "STS BigBenchAudio", "sts", "index",
     "Big Bench Audio component of the STS Index (0-100).",
     ("speech", "sts", "index"), False),
    ("stsTauVoice", "STS tau3-Voice", "sts", "index",
     "tau3-Voice component of the STS Index (0-100).",
     ("speech", "sts", "index"), False),
    ("stsArenaScore", "STS Arena Score", "sts", "index",
     "Arena-preference component of the STS Index (0-100).",
     ("speech", "sts", "index"), False),
    ("stsTaskSuccess", "STS Succ Idx", "sts", "index",
     "Task-success component of the STS Index (0-100).",
     ("speech", "sts", "index"), False),
    # /text-to-speech/models (107 rows, 30 with pronunciation results)
    ("ttsQualityElo", "TTS Quality Elo", "tts", "Elo",
     "Text-to-speech arena-preference Elo for the model (AA TTS quality).",
     ("speech", "tts", "elo"), False),
    ("ttsPronunciationPassRate", "TTS Pronunciation", "tts", "%",
     "Pronunciation robustness: share of highlighted spans human reviewers judged "
     "as pronounced correctly (English).", ("speech", "tts"), False),
    ("ttsTermPronunciation", "TTS Term Pron.", "tts", "%",
     "Pronunciation robustness on standalone terms.", ("speech", "tts"), False),
    ("ttsTextNormalization", "TTS Text Norm.", "tts", "%",
     "Pronunciation robustness on expanded shorthand (text normalisation).",
     ("speech", "tts"), False),
    ("ttsSequenceFidelity", "TTS Sequence Fid.", "tts", "%",
     "Pronunciation robustness on preserving exact sequences.", ("speech", "tts"), False),
    ("ttsContextualDisambiguation", "TTS Context", "tts", "%",
     "Pronunciation robustness on contextually appropriate readings.",
     ("speech", "tts"), False),
    ("ttsCharactersPerSecond", "TTS chars/s", "tts", "chars/s",
     "Median generation throughput in characters per second.",
     ("speech", "tts", "speed"), False),
    ("ttsGenerationTime", "TTS Gen Time", "tts", "s",
     "Median generation time in seconds (lower is better).",
     ("speech", "tts", "latency"), False),
    # /agents/search-api (26 provider rows)
    ("searchQualityIndex", "Search Index", "search-api", "%",
     "AA Search API Index: composite search quality across AA's search benchmarks.",
     ("agents", "search", "tool-use"), False),
    ("searchBrowsecompAccuracy", "Search BrowseComp", "search-api", "%",
     "BrowseComp accuracy for the search provider.",
     ("agents", "search", "knowledge"), False),
    ("searchDeepsearchqaF1", "Search DSQA F1", "search-api", "%",
     "DeepSearchQA average F1 for the search provider.",
     ("agents", "search", "tool-use"), False),
    ("searchOmniscienceAccuracy", "Search Omni Acc", "search-api", "%",
     "AA-Omniscience accuracy of the provider's answer model.",
     ("agents", "search", "knowledge"), False),
    ("searchAvgLatency", "Search Latency", "search-api", "s",
     "Average end-to-end latency per task in seconds; lower is better.",
     ("agents", "search", "latency"), False),
    ("searchCostPerQuery", "Search $/query", "search-api", "USD/query",
     "Search-API cost per search query in USD; lower is better.",
     ("agents", "search", "cost"), False),
    ("searchCostPerTask", "Search $/task", "search-api", "USD/task",
     "Search-API cost per task in USD; lower is better.",
     ("agents", "search", "cost"), False),
    ("searchQueriesPerTask", "Search Q/task", "search-api", "index",
     "Mean search queries issued per task.", ("agents", "search"), False),
    ("searchQualityLift", "Search Lift", "search-api", "%",
     "Search quality lift over the same model answering without search.",
     ("agents", "search"), False),
]
_B.extend(_BOARD_METRICS)

#: benchmark key -> best surface that yields a *cross-model* value.
#: Everything not listed defaults to "leaderboard" (the 700-row array).
_SOURCE_HINTS: dict[str, str] = {
    # AA publishes these two composites only through its paid data API: no public
    # page carries a per-model value, so there is no free surface to hint at
    # (see catalog.API_ONLY_INDEXES for the free constituents that ARE rankable).
    "coding": "none",
    "agentic": "none",
    # AA's own eval page for the index carries its full per-model array
    "decisionIndex": "chart",
    # present in the ~700 x 94 rich dataset (model pages), incl. derived fields
    "aime25": "rich",
    "automationBenchPartialScore": "rich",
    "briefcaseBreakdown": "rich",
    "briefcaseElo": "rich",
    "cweBench": "rich",
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
    "cyberIndex": "chart",
    "cyberRefusalRate": "chart",
    "cyberMitigationStatus": "chart",
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
    "hleMultichoice": "chart",
    "omniscienceDecision": "chart",
    "omniscienceDecisionNonHallucination": "chart",
    "multilingual": "chart",
}
#: every breakdown sub-score and board metric is a per-model chart-set value
for _row in _SUBSCORES + _BOARD_METRICS:
    _SOURCE_HINTS.setdefault(_row[0], "chart")

BENCHMARKS: dict[str, Benchmark] = {
    key: Benchmark(key, label, slug, unit, desc, tuple(tags), member,
                   _SOURCE_HINTS.get(key, "leaderboard"))
    for key, label, slug, unit, desc, tags, member in _B
}

#: Composites AA publishes **only through its paid data API**: no public page
#: carries a per-model value (verified against `sitemap.xml` and every scraped RSC
#: payload — no `codingIndex`/`agenticIndex` key exists on any free page, and no
#: `/…/coding-index` route is published).  Each maps to the free constituents that
#: ARE rankable, best first, so a caller always gets a call that works.
API_ONLY_INDEXES: dict[str, tuple[str, ...]] = {
    "coding": ("scicode", "livecodebench", "frontierCode", "terminalBench40"),
    "agentic": ("terminalBench40", "tau2", "tauBanking",
                "automationBenchPartialScore"),
}

#: Lowercased benchmark names AA does not track, with the closest thing AA measures.
#: Factual only — "AA does not track X" plus the nearest AA surface, no equivalence claim.
UNTRACKED_BENCHMARKS: dict[str, str] = {
    "mathvista": "AA does not track MathVista; visual reasoning is covered by MMMU-Pro "
                 "plus the per-model image/video input modality flags.",
    "docvqa": "AA does not track DocVQA; the closest document-style evaluation is "
              "GDP.pdf (with MMLU-Pro for broad knowledge).",
    "bfcl": "AA tracks BFCL only on its on-device benchmark set "
            "(/hardware-inference-stack/mobile-phones, fields bfcl_500 / bfcl_small) — "
            "there is no first-party BFCL column. For server-side tool use see "
            "\u03c4\u00b2-Bench / \u03c4\u00b3-Banking and the per-endpoint "
            "functionCalling/jsonMode flags.",
    "berkeley function calling": "AA tracks BFCL only on its on-device benchmark set "
            "(/hardware-inference-stack/mobile-phones, fields bfcl_500 / bfcl_small) — "
            "there is no first-party BFCL column. For server-side tool use see "
            "\u03c4\u00b2-Bench / \u03c4\u00b3-Banking and the per-endpoint "
            "functionCalling/jsonMode flags.",
    "ifstruct": "AA tracks IFStruct only on its on-device benchmark set "
                "(/hardware-inference-stack/mobile-phones); the closest first-party "
                "instruction-following evaluation is IFBench.",
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


#: Task words AA publishes no benchmark for, with the closest measures it *does*
#: publish. A task word is not a benchmark name: the wording stays factual
#: ("AA does not measure X; closest AA measures are …") and never implies that the
#: named AA evaluation is equivalent to the task. Keys are every accepted spelling;
#: :func:`task_domain` matches them against a free-text query.
TASK_DOMAINS: dict[str, str] = {
    "classification": (
        "AA does not measure classification; closest AA measures are IFBench "
        "(instruction following on 58 verifiable constraints) and the "
        "MMLU-Pro / Global-MMLU-Lite knowledge suites."
    ),
    "classify": (
        "AA does not measure classification; closest AA measures are IFBench "
        "(instruction following on 58 verifiable constraints) and the "
        "MMLU-Pro / Global-MMLU-Lite knowledge suites."
    ),
    "text classification": (
        "AA does not measure text classification; closest AA measures are IFBench "
        "(instruction following on 58 verifiable constraints) and the "
        "MMLU-Pro / Global-MMLU-Lite knowledge suites."
    ),
    "sentiment analysis": (
        "AA does not measure sentiment analysis; closest AA measures are IFBench "
        "(instruction following on 58 verifiable constraints) and the "
        "MMLU-Pro / Global-MMLU-Lite knowledge suites."
    ),
    "summarization": (
        "AA does not measure summarization; closest AA measures are GDP.pdf "
        "(all-pass rate on PDF document tasks) and AA-LCR (long-context reasoning "
        "over 10k-100k-token documents)."
    ),
    "summarisation": (
        "AA does not measure summarization; closest AA measures are GDP.pdf "
        "(all-pass rate on PDF document tasks) and AA-LCR (long-context reasoning "
        "over 10k-100k-token documents)."
    ),
    "summarize": (
        "AA does not measure summarization; closest AA measures are GDP.pdf "
        "(all-pass rate on PDF document tasks) and AA-LCR (long-context reasoning "
        "over 10k-100k-token documents)."
    ),
    "translation": (
        "AA does not measure translation; the closest AA measure is "
        "Global-MMLU-Lite (multilingual knowledge) — AA publishes no machine-"
        "translation quality score."
    ),
    "translate": (
        "AA does not measure translation; the closest AA measure is "
        "Global-MMLU-Lite (multilingual knowledge) — AA publishes no machine-"
        "translation quality score."
    ),
    "retrieval": (
        "AA does not measure retrieval; closest AA measures are AA-LCR "
        "(long-context reasoning over 10k-100k-token documents) and GDP.pdf "
        "(PDF document tasks)."
    ),
    "rag": (
        "AA does not measure RAG / retrieval-augmented generation; closest AA "
        "measures are AA-LCR (long-context reasoning over 10k-100k-token documents) "
        "and GDP.pdf (PDF document tasks)."
    ),
    "retrieval augmented generation": (
        "AA does not measure RAG / retrieval-augmented generation; closest AA "
        "measures are AA-LCR (long-context reasoning over 10k-100k-token documents) "
        "and GDP.pdf (PDF document tasks)."
    ),
    "sql": (
        "AA does not measure SQL generation; the closest AA measure is "
        "AA-AnalystAgent (spreadsheet/document analysis tasks)."
    ),
    "data analysis": (
        "AA does not measure data analysis; the closest AA measure is "
        "AA-AnalystAgent (spreadsheet/document analysis tasks)."
    ),
    "data analytics": (
        "AA does not measure data analytics; the closest AA measure is "
        "AA-AnalystAgent (spreadsheet/document analysis tasks)."
    ),
    "tool calling": (
        "AA does not measure tool calling directly; closest AA measures are "
        "\u03c4\u00b2-Bench (telecom/retail tool use) and \u03c4\u00b3-Banking "
        "(fintech multi-step tool calls), plus the per-endpoint functionCalling / "
        "jsonMode flags in aa_providers."
    ),
    "function calling": (
        "AA does not measure function calling directly; closest AA measures are "
        "\u03c4\u00b2-Bench (telecom/retail tool use) and \u03c4\u00b3-Banking "
        "(fintech multi-step tool calls), plus the per-endpoint functionCalling / "
        "jsonMode flags in aa_providers."
    ),
    "tool use": (
        "AA does not measure tool use directly; closest AA measures are "
        "\u03c4\u00b2-Bench (telecom/retail tool use) and \u03c4\u00b3-Banking "
        "(fintech multi-step tool calls), plus the per-endpoint functionCalling / "
        "jsonMode flags in aa_providers."
    ),
    "moderation": (
        "AA does not measure moderation; the closest AA measure is WildGuardTest "
        "(safety suite, chart-set coverage)."
    ),
    "ocr": (
        "AA does not measure OCR; closest AA measures are GDP.pdf (all-pass rate on "
        "PDF document tasks) and MMMU-Pro (multimodal academic reasoning)."
    ),
}


def task_domain(text: str) -> tuple[str, str] | None:
    """Match a task word/phrase against :data:`TASK_DOMAINS` (AA has no benchmark).

    Normalized-substring matching, so a whole question ("best model for
    classification") finds ``classification``. Returns ``(task, note)`` naming the
    closest AA measures, or ``None`` when the text names no known task word.
    """
    q = _norm(text)
    if not q:
        return None
    for task, note in TASK_DOMAINS.items():
        n = _norm(task)
        if not n:
            continue
        if q == n or n in q or (len(q) >= 4 and q in n):
            return task, note
    return None


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
    ("weights_url", "Weights", "str", "identity",
     "Where the model weights are published (open-weights models).", None),
    ("modalities_in", "Mod In", "str", "identity",
     "Input modalities (text/image/speech/video).", None),
    ("modalities_out", "Mod Out", "str", "identity",
     "Output modalities (text/image/speech/video).", None),
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
    ("decisionIndex", "Decision", "index", "index",
     "AA Decision Index: composite across decision models (0-100).", "high"),
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
              "tok/s": "tps", "USD/task": "usd", "mixed": "str", "text": "str",
              # the TTS/search boards publish throughput and per-query prices
              "chars/s": "tps", "USD/query": "usd"}
#: Benchmark metrics where a *lower* value is the better result. Audited against
#: `BENCHMARKS` (2026-10-14): the only benchmark descriptions that say "lower is
#: better" are these four, plus the `METRICS` cost/TTFT/verbosity family above.
#: test_catalog.py::test_lower_is_better_marks_match_descriptions enforces it.
_LOWER_IS_BETTER = {
    "omniscienceHallucinationRate",
    "cweBenchRefusalRate",
    "cyberRefusalRate",
    "cybergymE2eRefusalRate",
    "deepsecBenchRefusalRate",
    # every word-error-rate / latency / cost column says "lower is better"
    "sttWerIndex", "sttWordErrorRate", "sttEarnings22Wer", "sttVoxpopuliWer",
    "sttAgenttalkWer", "sttStreamingWerIndex", "sttStreamingEarnings22Wer",
    "sttStreamingAgenttalkWer", "sttStreamingTimeToFinal",
    "sttStreamingTimeToFirstPartial", "ttsGenerationTime", "searchAvgLatency",
    "searchCostPerQuery", "searchCostPerTask",
}
#: Benchmark key -> the short label a table head shows.  A benchmark's own label
#: is truncated to 12 characters for column headers, which mangles the longer ones
#: ("On-device BFCL-500" and "-Small" both become "On-device BF"; every
#: "Openness · …" component becomes "Openness · M").  These give each one a label
#: that fits and stays distinguishable; the canonical key never changes.
_SHORT_LABELS: dict[str, str] = {
    "globalMmluLiteScore": "Global-MMLU",
    # these four/six all collapsed to one header ("Terminal-Ben", "Analyst Pass")
    # under plain truncation, so a reader could not tell the columns apart
    "terminalBench21": "TB 2.1",
    "terminalbenchHard": "TB Hard",
    "terminalBench40": "TB 4.0",
    "terminalBenchScience": "TB Science",
    "analystAgentPassAt1": "Analyst P@1",
    "analystAgentPassAtK": "Analyst P@k",
    "wildguardtest": "WildGuard",
    "hleMultichoice": "HLE-MCQ",
    "omniscienceDecision": "OmniDecision",
    "omniscienceDecisionNonHallucination": "Omni-Dec NH",
    "multilingual": "Multilingual",
    "briefcaseAnalyticalQualityElo": "BC Analytic",
    "briefcasePresentationElo": "BC Present.",
    "briefcaseRubricPassRate": "BC Rubric",
    "harveyCriteriaPass": "Harvey Crit.",
    "harveyGatedAllPass": "Harvey Gated",
    "gdpPdfMacroPassRate": "GDP.pdf Mac",
    "automationBenchStrictScore": "AutoBench St",
    "automationBenchCompletion": "AutoBench Cp",
    "gdpvalAvgTurns": "GDPval Turns",
    "itbenchAvgTurnsPerTask": "ITBench Trn",
    "enterpriseOpsGymAvgTurns": "EntOps Turns",
    "aa3dTurnsP50": "AA-3D Turns",
    "medianCanonicalAnswerOutputSpeed": "Answer tok/s",
    "mobile.gpqa": "Dev GPQA",
    "mobile.ifbench": "Dev IFBench",
    "mobile.ifstruct": "Dev IFStruct",
    "mobile.math_500": "Dev MATH-500",
    "mobile.omniscience": "Dev Omni",
    "mobile.bfcl_500": "Dev BFCL-500",
    "mobile.bfcl_small": "Dev BFCL-Sm",
}
#: the per-language / per-domain families, generated from the same tables that
#: define their keys so a new entry can never be left without a short label
_SHORT_LABELS.update({
    f"multilingual.{_code}": _name for _code, _name in MULTILINGUAL_LANGS.items()
})
_SHORT_LABELS.update({
    f"openness.{_comp}": _short for _comp, _short in (
        ("modelAvailability", "Open Avail"),
        ("modelTransparency", "Open Model"),
        ("transparencyPreTrainingData", "Open PreData"),
        ("transparencyPostTrainingData", "Open PostDat"),
        ("transparencyMethodology", "Open Method"),
        ("dataPretrainAccess", "Open PreAcc"),
        ("dataPretrainLicense", "Open PreLic"),
        ("dataPosttrainAccess", "Open PstAcc"),
        ("dataPosttrainLicense", "Open PstLic"),
    )
})
_SHORT_LABELS.update({
    f"omniscience.domain.{_slug}": _short for _slug, _short in (
        ("business", "Omni Bus."),
        ("health", "Omni Health"),
        ("humanitiesAndSocialSciences", "Omni Hum&Soc"),
        ("law", "Omni Law"),
        ("scienceAndEngineering", "Omni Sci&Eng"),
        ("softwareEngineering", "Omni SWE"),
    )
})
_SHORT_LABELS.update({
    f"omniscience.language.{_code.lower()}": _short for _code, _short in (
        ("JavaScript", "Omni JS"), ("TypeScript", "Omni TS"),
    )
})
for _code, _name in OMNISCIENCE_LANGS.items():
    _SHORT_LABELS.setdefault(f"omniscience.language.{_code.lower()}", f"Omni {_name}")
_SHORT_LABELS.update({
    f"terminalBenchScience.domain.{_dom}": _short for _dom, _short in (
        ("life-sciences", "TB-Sci Life"), ("physical-sciences", "TB-Sci Phys"),
        ("mathematical-sciences", "TB-Sci Math"),
        ("engineering-sciences", "TB-Sci Eng"),
        ("earth-sciences", "TB-Sci Earth"),
    )
})
_SHORT_LABELS.update({
    f"enterpriseOpsGym.domain.{_dom}": _short for _dom, _short in (
        ("csm", "EntOps CSM"), ("hr", "EntOps HR"), ("itsm", "EntOps ITSM"),
        ("email", "EntOps Email"), ("calendar", "EntOps Cal"),
        ("teams", "EntOps Teams"), ("drive", "EntOps Drive"),
        ("hybrid", "EntOps Hyb"),
    )
})


def _short_label(key: str, label: str) -> str:
    """The column label for benchmark ``key`` (AA's own label, shortened)."""
    return _SHORT_LABELS.get(key, label)[:12]


for _b in BENCHMARKS.values():
    if _b.unit == "mixed":
        continue
    if _b.key in METRICS:
        continue
    _kind = _UNIT_KIND.get(_b.unit, "str")
    _group = "index" if _b.unit == "index" else "eval"
    _better = "low" if _b.key in _LOWER_IS_BETTER else "high"
    METRICS[_b.key] = Metric(_b.key, _short_label(_b.key, _b.label),
                             _kind, _group, _b.desc, _better)


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
    "reasoning_time": "reasoning_s",
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

# Field names as they appear in AA's published API vocabulary (the schema its
# /api-reference page documents); every one also has a live-payload spelling.
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
    "artificial_analysis_multilingual_index": "multilingual",
    "price_1m_input_tokens": "price_in",
    "price_1m_output_tokens": "price_out",
}
for _alias, _key in _OPENAPI_ALIASES.items():
    if _key in METRICS or _key in BENCHMARKS:
        FIELD_ALIASES[_alias] = _key

# Short spellings for the six Capability Indexes: the payload's own field name
# (``capabilities.legal``), that name without the prefix (``legal``), AA's human
# label ("Legal Index") and the label without the trailing "Index".
_CAPABILITY_ALIASES = {
    "capabilities.financeAndAccounting": ("financeAndAccounting", "Finance & Accounting",
                                          "Finance and Accounting",
                                          "Finance & Accounting Index"),
    "capabilities.strategyAndOps": ("strategyAndOps", "Strategy & Ops",
                                    "Strategy and Ops", "Strategy & Ops Index"),
    "capabilities.legal": ("legal", "Legal", "Legal Index"),
    "capabilities.healthcareAndMedical": ("healthcareAndMedical", "Healthcare & Medical",
                                          "Healthcare and Medical",
                                          "Healthcare & Medical Index"),
    "capabilities.engineering": ("engineering", "Engineering", "Engineering Index"),
    "capabilities.economics": ("economics", "Economics", "Economics Index"),
    "decisionIndex": ("decisionIndex", "Decision Index", "AA Decision Index"),
}
for _key, _aliases in _CAPABILITY_ALIASES.items():
    if _key in BENCHMARKS:
        for _alias in _aliases:
            _add_alias(_alias, _key)

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


def _elo_text(value: float) -> str:
    """An Elo cell as AA's own table renders it: ``.5`` rounds away from zero.

    Python's ``:.0f`` rounds half-to-even, so it prints ``1146.5`` as ``"1146"``
    where the site shows ``"1147"`` (and ``1092.5`` as ``"1092"`` vs ``"1093"``).
    AA's payload carries the rendered string in ``formatted.elo``, so the site's
    convention is observable rather than assumed.  Display only — the stored Elo
    stays the exact float.
    """
    if not math.isfinite(value):
        return str(value)
    return str(math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5))


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
    if isinstance(value, (tuple, list, set, frozenset)):
        # identity fields hold tuples (modalities, tags): "text+image", not a repr
        return "+".join(str(item) for item in value) or "-"
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
            return _elo_text(float(value))
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
            return f"{round(float(value)):,}"
        if kind == "bool":
            return "yes" if value else "no"
    except (TypeError, ValueError):
        return str(value)
    return str(value)


# --------------------------------------------------------------------------- #
# the searchable rankable index (Wave C)
# --------------------------------------------------------------------------- #
#
# One flat index over *everything an agent can rank models on* — every benchmark,
# composite index, derived metric and arena board — so a task-domain search finds
# the right surface without one tool per benchmark. ``how`` is the actionable hint
# (which tool + argument); ``DOMAINS`` expands a task domain into the tags/tokens
# that select the relevant entries.

@dataclass(frozen=True, slots=True)
class Rankable:
    key: str
    label: str
    kind: str                  # "benchmark" | "index" | "derived" | "arena" | "view"
    unit: str
    tags: tuple[str, ...]
    how: str
    #: "leaderboard" | "rich" | "chart" | "board" | "none" (paid API only)
    surface: str
    desc: str
    aliases: tuple[str, ...] = ()


#: benchmark unit -> Rankable unit
_BENCH_UNIT = {"%": "%", "Elo": "Elo", "index": "index", "mixed": "text",
               "text": "text", "s": "s", "tok/s": "tok/s", "USD/task": "USD/task",
               "chars/s": "chars/s", "USD/query": "USD/query"}

#: canonical full names for the composites whose short label is ambiguous in search
_LABEL_OVERRIDES = {
    "intelligence": "Artificial Analysis Intelligence Index",
    "coding": "Artificial Analysis Coding Index",
    "agentic": "Artificial Analysis Agentic Index",
    "openness": "Artificial Analysis Openness Index",
    "omniscience": "AA-Omniscience Index",
    "cyberIndex": "Artificial Analysis Cyber Index",
    "decisionIndex": "Artificial Analysis Decision Index",
    "multilingual": "Artificial Analysis Multilingual Index",
    "capabilities.financeAndAccounting": "Finance & Accounting Index",
    "capabilities.strategyAndOps": "Strategy & Ops Index",
    "capabilities.legal": "Legal Index",
    "capabilities.healthcareAndMedical": "Healthcare & Medical Index",
    "capabilities.engineering": "Engineering Index",
    "capabilities.economics": "Economics Index",
}

#: extra spellings a user is likely to type (incl. version-suffixed names)
_EXTRA_ALIASES = {
    "intelligence": ("Artificial Analysis Intelligence Index", "AA Intelligence Index",
                     "Intelligence Index"),
    "coding": ("Artificial Analysis Coding Index", "Coding Index"),
    "agentic": ("Artificial Analysis Agentic Index", "Agentic Index"),
    "openness": ("Artificial Analysis Openness Index", "Openness Index"),
    "omniscience": ("AA-Omniscience Index", "Omniscience Index"),
    "cyberIndex": ("Artificial Analysis Cyber Index", "Cyber Index"),
    "cyberRefusalRate": ("Cyber Index Refusal Rate", "Cyber Refusal Rate",
                         "AA Cyber Index Refusal Rate"),
    "cyberMitigationStatus": ("Cyber Index Mitigation Status", "Mitigation Status",
                              "AA Cyber Index Mitigation Status"),
    "itbenchSre": ("ITBench-AA", "ITBench AA", "ITBench"),
    "terminalBench40": ("Terminal-Bench 4.0", "TerminalBench 4.0"),
    "terminalBenchScience": ("Terminal-Bench-Science 0.1", "Terminal-Bench Science 0.1"),
    "frontierCode": ("FrontierCode 1.1", "FrontierCode v1.1"),
    "aa3dElo": ("AA-3D", "AA 3D", "AA-3D Elo"),
    "decisionIndex": ("Decision Index", "AA Decision Index"),
    "multilingual": ("Multilingual Index", "AA Multilingual Index",
                     "Multilingual", "Languages Index", "Languages"),
    "hleMultichoice": ("HLE-MultiChoice", "HLE MultiChoice", "HLE-MCQ",
                       "Humanity's Last Exam MultiChoice"),
    "omniscienceDecision": ("AA-Omniscience-Decision", "Omniscience Decision",
                            "Omniscience-Decision", "Omniscience Decision Accuracy"),
    "omniscienceDecisionNonHallucination": (
        "Omniscience-Decision Non-Hallucination", "Omniscience Decision Non-Halluc",
        "AA-Omniscience-Decision Non-Hallucination"),
    "when2call": ("When 2 Call", "When2Call Accuracy"),
    "wildguardtest": ("WildGuard Test", "WildGuard", "WildGuardTest Average F1"),
    "mobile.bfcl_500": ("BFCL-500", "BFCL 500", "Berkeley Function Calling 500",
                        "BFCL"),
    "mobile.bfcl_small": ("BFCL-Small", "BFCL Small", "BFCL-S"),
    "mobile.ifstruct": ("IFStruct", "IF-Struct"),
    "mobile.gpqa": ("On-device GPQA", "Mobile GPQA"),
    "mobile.ifbench": ("On-device IFBench", "Mobile IFBench"),
    "mobile.math_500": ("On-device MATH-500", "Mobile MATH-500"),
    "mobile.omniscience": ("On-device Omniscience", "Mobile Omniscience"),
    # speech / search board columns
    "sttWerIndex": ("AA-WER", "AA WER", "Speech Recognition WER", "STT WER",
                    "Word Error Rate"),
    "sttEarnings22Wer": ("Earnings22", "Earnings22-Cleaned-AA", "Earnings22 WER"),
    "sttVoxpopuliWer": ("VoxPopuli", "VoxPopuli-Cleaned-AA", "VoxPopuli WER"),
    "sttAgenttalkWer": ("AgentTalk", "AA-AgentTalk", "AgentTalk WER"),
    "sts": ("Speech to Speech Index", "Realtime Voice Index", "STS Index"),
    "stsTaskCompletionRate": ("STS Task Completion", "Task Completion Rate"),
    "stsBigBenchAudio": ("Big Bench Audio", "BBA"),
    "stsTauVoice": ("tau3-Voice", "Tau Voice", "tau-Voice"),
    "stsArenaScore": ("STS Arena Preference", "Arena Score"),
    "ttsPronunciationPassRate": ("Pronunciation Robustness", "Pronunciation"),
    "ttsTermPronunciation": ("Standalone Terms", "Term Pronunciation"),
    "ttsTextNormalization": ("Expanding Shorthand", "Text Normalization"),
    "ttsSequenceFidelity": ("Preserving Exact Sequences", "Sequence Fidelity"),
    "ttsContextualDisambiguation": ("Contextually Appropriate",
                                    "Contextual Disambiguation"),
    "ttsCharactersPerSecond": ("Characters Per Second", "TTS Throughput"),
    "ttsGenerationTime": ("TTS Latency", "Generation Time"),
    "ttsQualityElo": ("TTS Arena Preference", "TTS Elo"),
    "searchQualityIndex": ("Search API Index", "AA Search Index"),
    "searchBrowsecompAccuracy": ("BrowseComp", "BrowseComp Accuracy"),
    "searchDeepsearchqaF1": ("DeepSearchQA", "DeepSearchQA F1"),
    "searchAvgLatency": ("Search Latency", "Avg Latency"),
    "searchCostPerQuery": ("Cost per Search Query", "Search Query Cost"),
    "searchCostPerTask": ("Search API Cost", "Search Task Cost"),
    "capabilities.financeAndAccounting": ("Finance & Accounting", "Finance and Accounting",
                                          "Finance & Accounting Index"),
    "capabilities.strategyAndOps": ("Strategy & Ops", "Strategy and Ops",
                                    "Strategy & Ops Index"),
    "capabilities.legal": ("Legal", "Legal Index"),
    "capabilities.healthcareAndMedical": ("Healthcare & Medical", "Healthcare and Medical",
                                          "Healthcare & Medical Index"),
    "capabilities.engineering": ("Engineering", "Engineering Index"),
    "capabilities.economics": ("Economics", "Economics Index"),
}


def _dedupe(items) -> tuple[str, ...]:
    out: list[str] = []
    for it in items:
        it = (it or "").strip()
        if it and it not in out:
            out.append(it)
    return tuple(out)


RANKABLES: dict[str, Rankable] = {}

#: Breakdown container -> the scalar sub-scores registered for it (best first).
#: A container's own value is a per-model map, so its ``how`` hint must name a
#: *rankable* sub-score rather than the container itself (a hint may never point
#: at an empty output).
_BREAKDOWN_SUBSCORES: dict[str, tuple[str, ...]] = {
    "briefcaseBreakdown": ("briefcaseRubricPassRate", "briefcaseAnalyticalQualityElo",
                           "briefcasePresentationElo"),
    "automationBenchBreakdown": ("automationBenchStrictScore", "automationBenchCompletion"),
    "gdpvalBreakdown": ("gdpvalAvgTurns",),
    "harveyLabBreakdown": ("harveyCriteriaPass", "harveyGatedAllPass"),
    "gdpPdfBreakdown": ("gdpPdfMacroPassRate",),
    "aa3dBreakdown": ("aa3dTurnsP50",),
    "enterpriseOpsGymSuccessRateByDomain": tuple(
        f"enterpriseOpsGym.domain.{_dom}" for _dom in ENTERPRISE_OPS_DOMAINS
    ),
}

# benchmarks + composite indexes (kind follows the benchmark's unit)
for _key, _b in BENCHMARKS.items():
    _kind = "index" if _b.unit == "index" else "benchmark"
    _label = _LABEL_OVERRIDES.get(_key, _b.label)
    _aliases = _dedupe((_b.key, _b.label, _b.slug, *_EXTRA_ALIASES.get(_key, ())))
    # ``aa_leaderboard sort=`` is the default ranking path for every key that has
    # per-model values on some surface it can reach (the 700-row leaderboard, the
    # rich overlay, or an eval chart set / homepage panel — joined by slug). Keys
    # AA serves only through its paid data API, container/breakdown kinds, and the
    # few chart keys with no eval-page slug stay on ``aa_benchmark_leaderboard``.
    _lb_reachable = (
        _b.unit != "mixed"
        and _b.source_hint != "none"
        and (_b.source_hint != "chart" or bool(_b.slug))
    )
    # A hint must always name a call that works: for a composite with no public
    # values, point at the free constituents instead of an empty leaderboard.
    _constituents = API_ONLY_INDEXES.get(_key)
    if _constituents:
        _how = f"aa_benchmark_leaderboard benchmark={_constituents[0]}"
    elif _lb_reachable:
        _how = f"aa_leaderboard sort={_key}"
    elif _b.unit == "mixed":
        # a container's own value is a per-model map: name a rankable sub-score
        _subs = _BREAKDOWN_SUBSCORES.get(_key, ())
        _how = (f"aa_benchmark_leaderboard benchmark={_subs[0]}" if _subs
                else "aa_model <model-slug> sections=benchmarks")
    else:
        _how = f"aa_benchmark_leaderboard benchmark={_key}"
    RANKABLES[_key] = Rankable(
        key=_key, label=_label, kind=_kind,
        unit=_BENCH_UNIT.get(_b.unit, "text"),
        tags=_dedupe(_b.tags), how=_how, surface=_b.source_hint,
        desc=_b.desc,
        aliases=tuple(a for a in _aliases if a != _label),
    )

# derived metrics (kind="derived"): label, unit, tags, how
_DERIVED = [
    ("tps", "Speed (output tokens/s)", "tok/s", ("speed",), "aa_leaderboard sort=tps"),
    ("ttft", "Time to First Token", "s", ("speed",), "aa_leaderboard sort=ttft"),
    ("ttfa", "Time to First Answer Token", "s", ("speed",), "aa_leaderboard sort=ttfa"),
    ("e2e", "End-to-End Response Time", "s", ("speed",), "aa_leaderboard sort=e2e"),
    ("cost_per_task", "Cost per Task", "USD/task", ("cost", "pricing"),
     "aa_pareto x=cost_per_task"),
    ("index_total_cost", "Cost to Run the Intelligence Index (whole suite)", "USD",
     ("cost", "pricing"), "aa_pareto x=index_total_cost"),
    ("time_per_task", "Time per Intelligence Index Task", "s", ("speed", "cost"),
     "aa_pareto x=time_per_task"),
    ("out_tokens_per_task", "Output Tokens per Intelligence Index Task", "tokens",
     ("speed", "cost"), "aa_pareto x=out_tokens_per_task"),
    ("price_in", "Input Price (USD per 1M tokens)", "USD/1M", ("cost", "pricing"),
     "aa_leaderboard sort=price_in"),
    ("price_out", "Output Price (USD per 1M tokens)", "USD/1M", ("cost", "pricing"),
     "aa_leaderboard sort=price_out"),
    ("cache_read", "Cache Read Price (USD per 1M tokens)", "USD/1M", ("cost", "pricing"),
     "aa_leaderboard sort=cache_read"),
    ("cache_write", "Cache Write Price (USD per 1M tokens)", "USD/1M", ("cost", "pricing"),
     "aa_leaderboard sort=cache_write"),
    ("context_tokens", "Context Window", "tokens", ("long-context",),
     "aa_leaderboard sort=context_tokens"),
    ("params_b", "Total Parameters (B)", "params", ("model-size",),
     "aa_leaderboard sort=params_b"),
    ("active_params_b", "Active Parameters (B)", "params", ("model-size",),
     "aa_leaderboard sort=active_params_b"),
    ("release_date", "Release Date", "date", ("date",),
     "aa_leaderboard sort=release_date"),
]

#: derived key -> extra spellings
_DERIVED_ALIASES = {
    "tps": ("Speed", "Output Speed", "Tokens per Second"),
    "cost_per_task": ("Cost per Index Task",),
    "index_total_cost": ("Cost to Run the Intelligence Index", "Cost to Run",
                         "Index Total Cost"),
    "time_per_task": ("Time per Task", "Time per Intelligence Index Task"),
    "out_tokens_per_task": ("Output Tokens per Task", "Output Tokens per Index Task"),
    "ttft": ("Time to First Token",),
    "ttfa": ("Time to First Answer Token",),
    "e2e": ("End-to-End",),
    "price_in": ("Input Price", "Input $/M"),
    "price_out": ("Output Price", "Output $/M"),
    "cache_read": ("Cache Read Price", "Cache Read $/M"),
    "cache_write": ("Cache Write Price", "Cache Write $/M"),
    "context_tokens": ("Context", "Context Length"),
    "params_b": ("Parameters", "Total Parameters"),
    "active_params_b": ("Active Parameters",),
    "release_date": ("Released", "Release"),
}

_DERIVED_DESC = {
    "index_total_cost": ("Cost to run the whole AA Intelligence Index suite for the "
                         "model (sum of the per-evaluation task costs)."),
    "time_per_task": "Wall-clock time to complete one AA Intelligence Index task.",
}

for _key, _label, _unit, _tags, _how in _DERIVED:
    _m = METRICS.get(_key)
    _desc = _DERIVED_DESC.get(_key) or (_m.desc if _m else _label)
    _aliases = _dedupe((_key, _key.replace("_", "-"), _key.replace("_", " "), _label,
                        *_DERIVED_ALIASES.get(_key, ())))
    RANKABLES[_key] = Rankable(
        key=_key, label=_label, kind="derived", unit=_unit, tags=_dedupe(_tags),
        how=_how, surface="leaderboard", desc=_desc,
        aliases=tuple(a for a in _aliases if a != _label),
    )

# arena boards (kind="arena"): key, label, tags, extra aliases
_ARENA = [
    ("text_to_image", "Text-to-Image Arena Elo", ("media", "image", "vision"),
     ("Text-to-Image", "T2I", "Image Arena")),
    ("image_editing", "Image Editing Arena Elo", ("media", "image", "vision"),
     ("Image Editing", "Image Edit")),
    ("text_to_video", "Text-to-Video Arena Elo", ("media", "video"),
     ("Text-to-Video", "T2V")),
    ("image_to_video", "Image-to-Video Arena Elo", ("media", "video"),
     ("Image-to-Video", "I2V")),
    ("video_editing", "Video Editing Arena Elo", ("media", "video"), ("Video Editing",)),
    ("text_to_speech", "Text-to-Speech Arena Elo", ("media", "speech", "audio"),
     ("Provider Voice Arena Preference Elo", "Provider Voice", "Text-to-Speech", "TTS")),
    ("text_to_speech_controlled", "Controlled Voice Arena Elo",
     ("media", "speech", "audio"), ("Controlled Voice", "Text-to-Speech Controlled")),
    ("music_instrumental", "Instrumental Music Arena Elo", ("media", "music", "audio"),
     ("Instrumental Music", "Music Instrumental")),
    ("music_with_vocals", "Music with Vocals Arena Elo", ("media", "music", "audio"),
     ("Music with Vocals", "Vocal Music")),
    ("speech_to_text", "Speech-to-Text Arena Elo", ("media", "speech", "audio"),
     ("Speech-to-Text", "STT", "Transcription")),
    ("speech_to_text_streaming", "Streaming Speech-to-Text Arena Elo",
     ("media", "speech", "audio"), ("Streaming Speech-to-Text", "STT Streaming")),
    ("speech_to_speech", "Speech-to-Speech Arena Elo", ("media", "speech", "audio"),
     ("Artificial Analysis Speech to Speech Index", "Speech to Speech Index",
      "Speech-to-Speech", "Realtime Voice", "realtime_voice", "STS")),
]

for _key, _label, _tags, _aliases in _ARENA:
    RANKABLES[_key] = Rankable(
        key=_key, label=_label, kind="arena", unit="Elo", tags=_dedupe(_tags),
        how=f"aa_media board={_key}", surface="board",
        desc=f"Human-preference Elo for the {_label.replace(' Arena Elo', '')} arena board.",
        aliases=tuple(a for a in _dedupe((_key, *_aliases)) if a != _label),
    )

# agent boards (kind="arena"): ranked by ``aa_agents``, and their headline score is
# an index rather than an Elo. The coding board's ``indexScore`` *is* the Artificial
# Analysis Coding Agent Index — the one coding index AA publishes for free (it ranks
# agent x model combinations, not the model variants ``aa_leaderboard`` ranks).
# key, label, tags, extra aliases
_AGENT_BOARDS = [
    ("coding_agents", "Artificial Analysis Coding Agent Index",
     ("agentic", "coding", "agents", "arena"),
     ("Coding Agent Index", "Coding Agents Index", "AA Coding Agent Index",
      "Coding Agents Board")),
    ("chatbots", "Chatbot Arena Preference", ("arena", "agents"),
     ("Chatbot Board", "Chatbots")),
    ("search_api", "Search API Index", ("agents", "tool-use", "arena"),
     ("Search API Board", "Search Index")),
]

for _key, _label, _tags, _aliases in _AGENT_BOARDS:
    RANKABLES[_key] = Rankable(
        key=_key, label=_label, kind="arena", unit="index", tags=_dedupe(_tags),
        how=f"aa_agents board={_key}", surface="board",
        desc=(f"{_label}: AA's agent-board composite (it ranks agent x model "
              "combinations, not the model variants aa_leaderboard ranks)."),
        aliases=tuple(a for a in _dedupe((_key, *_aliases)) if a != _label),
    )

# site comparison views (kind="view"): the "Intelligence Index vs. X" plots the user
# asked to be able to reach *always*. Each points at the ``aa_pareto`` axis call.
# key, label, pareto x-axis, tags, extra aliases
_VIEWS = [
    ("intelligence_vs_cost_per_task",
     "Intelligence Index vs. Cost per Task", "cost_per_task", ("view", "cost"),
     ("Intelligence Index vs Cost per Task", "Intelligence Index versus Cost per Task",
      "Intelligence Index vs. Cost per Index Task", "Intelligence vs. Cost per Task",
      "Intelligence Index vs. Cost")),
    ("intelligence_vs_index_total_cost",
     "Intelligence Index vs. Cost to Run Artificial Analysis Intelligence Index",
     "index_total_cost", ("view", "cost"),
     ("Intelligence Index vs. Cost to Run AA Intelligence Index",
      "Intelligence Index vs Cost to Run Artificial Analysis Intelligence Index",
      "Intelligence Index vs. Cost to Run the AA Intelligence Index",
      "Intelligence Index versus Cost to Run Artificial Analysis Intelligence Index",
      "Cost to Run Artificial Analysis Intelligence Index",
      "Cost to Run AA Intelligence Index", "Intelligence Index vs. Cost to Run")),
    ("intelligence_vs_out_tokens_per_task",
     "Intelligence Index vs. Output Tokens per Intelligence Index Task",
     "out_tokens_per_task", ("view", "speed", "cost"),
     ("Intelligence Index vs. Output Tokens per Task",
      "Intelligence Index vs Output Tokens per Intelligence Index Task",
      "Intelligence Index versus Output Tokens per Intelligence Index Task",
      "Intelligence Index vs. Output Tokens")),
    ("intelligence_vs_speed",
     "Intelligence Index vs. Speed", "tps", ("view", "speed"),
     ("Intelligence Index vs Speed", "Intelligence Index versus Speed",
      "Speed vs. Intelligence Index", "Intelligence Index vs. Tokens per Second")),
]

for _key, _label, _axis, _tags, _aliases in _VIEWS:
    RANKABLES[_key] = Rankable(
        key=_key, label=_label, kind="view", unit="index", tags=_dedupe(_tags),
        how=f"aa_pareto x={_axis}", surface="chart",
        desc=(f"Site comparison view: plots the AA Intelligence Index against "
              f"{RANKABLES[_axis].label}."),
        aliases=tuple(a for a in _dedupe((_key, *_aliases)) if a != _label),
    )


# --------------------------------------------------------------------------- #
# domain expansion
# --------------------------------------------------------------------------- #

#: canonical task domain -> tags/tokens it covers. A token matches a rankable when
#: it equals one of its tags (or key), or, with a trailing ``*``, is a prefix of the
#: key. Aliased spellings (``vision``/``multimodal``, ``business``/``finance``, …)
#: are separate keys so an agent can ask either way.
DOMAINS: dict[str, tuple[str, ...]] = {
    "coding": ("coding",),
    "math": ("math",),
    "science": ("science",),
    "security": ("cyber", "security", "cweBench*", "deepsec*", "cybergym*", "wildguard*"),
    "agentic": ("agentic",),
    "tool-use": ("tool-use",),
    "long-context": ("long-context",),
    "instruction-following": ("instruction-following",),
    "knowledge": ("knowledge",),
    "reasoning": ("reasoning",),
    "safety": ("safety", "guardrail"),
    "multimodal": ("vision", "media", "image", "video", "audio", "speech", "music"),
    "vision": ("vision",),
    "speech": ("speech",),
    "media": ("media", "image", "video", "audio", "speech", "music"),
    "music": ("music",),
    "video": ("video",),
    "business": ("business", "finance", "capabilities.financeAndAccounting*",
                 "capabilities.strategyAndOps*"),
    "finance": ("finance", "capabilities.financeAndAccounting*"),
    "legal": ("legal", "capabilities.legal*"),
    "medical": ("medical", "healthcare", "capabilities.healthcareAndMedical*"),
    "engineering": ("engineering", "capabilities.engineering*"),
    "economics": ("economics", "capabilities.economics*"),
    "cost": ("cost", "pricing"),
    "speed": ("speed",),
    "openness": ("openness",),
    "multilingual": ("multilingual", "language"),
    "languages": ("multilingual", "language"),
    "search": ("search", "agents"),
    "agents": ("agents",),
    "tts": ("tts", "speech"),
    "mobile": ("mobile", "on-device", "local"),
    "on-device": ("mobile", "on-device", "local"),
}

_DOMAIN_KEYS = {_norm(_d): _d for _d in DOMAINS}


def _resolve_domain(domain: str) -> str | None:
    d = domain.strip()
    if d in DOMAINS:
        return d
    return _DOMAIN_KEYS.get(_norm(d))


def _domain_token_matches(token: str, r: Rankable) -> bool:
    t = token.lower()
    if t.endswith("*"):
        prefix = t[:-1]
        return (r.key.lower().startswith(prefix)
                or any(tag.lower().startswith(prefix) for tag in r.tags))
    return t == r.key.lower() or t in {tag.lower() for tag in r.tags}


def _tokens(text: str) -> list[str]:
    """Lowercased alphanumeric tokens (same split as ``select.search``)."""
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if t]


def _haystack(r: Rankable) -> set[str]:
    fields = [r.key, r.label, r.desc, *r.tags, *r.aliases]
    return set(_tokens(" ".join(fields)))


#: kind preference among otherwise-equal query matches (views/arenas first)
_KIND_ORDER = {"view": 0, "arena": 0, "index": 1, "benchmark": 1, "derived": 1}


def _query_sort_key(r: Rankable, query: str, qtokens: list[str]) -> tuple:
    """Deterministic rank for tokenised query results (see :func:`rankables`)."""
    names = {_norm(r.key), _norm(r.label), *(_norm(a) for a in r.aliases)}
    exact = 0 if _norm(query) in names else 1
    named = set(_tokens(" ".join((r.key, r.label, *r.aliases, *r.tags))))
    tier = 0 if all(t in named for t in qtokens) else 1
    numeric = 0 if r.unit not in ("text",) else 1
    return (exact, tier, numeric, _KIND_ORDER.get(r.kind, 9), r.label.lower(), r.key)


def query_domain(query: str) -> str | None:
    """The canonical task domain a single-word ``query`` names, else ``None``.

    ``query="security"`` is a domain name, so a bare word is not a useful
    AND-token (it only matches the one entry whose text spells it out); it is
    expanded through :data:`DOMAINS` exactly like ``domain="security"``. A
    multi-word query (``"cyber index"``) keeps the tokenised AND behaviour.
    """
    text = str(query).strip()
    if not text or any(ch.isspace() for ch in text):
        return None
    return _resolve_domain(text)


def rankables(*, domain: str = "", tag: str = "", query: str = "") -> list[Rankable]:
    """Search the rankable index by task ``domain``, ``tag`` and/or free ``query``.

    ``query`` is an AND-match over key/label/aliases/desc/tags, except that a
    single word naming a known domain expands to that whole domain (see
    :func:`query_domain`); ``domain`` expands through :data:`DOMAINS`; ``tag`` is
    an exact tag match. All three combine. An unknown ``domain``/``tag`` yields an
    empty list.

    Ordering is deterministic. Tokenised ``query`` results sort by, in order:

    1. exact label/alias/key match first;
    2. entries matched on their name/tags before those matched only via ``desc``;
    3. numeric units before ``text`` containers (so a breakdown row never
       outranks the value it breaks down);
    4. ``view``/``arena`` before ``benchmark``/``index``/``derived`` among
       otherwise-equal matches (an arena/view only appears when the query names
       it, so this never floats an unrelated one to the top);
    5. label, then key, for a total order.

    Domain/tag-only results sort by ``(kind, key)``.
    """
    out = list(RANKABLES.values())
    if domain:
        canon = _resolve_domain(domain)
        tokens = DOMAINS.get(canon) if canon else None
        if not tokens:
            return []
        out = [r for r in out if any(_domain_token_matches(t, r) for t in tokens)]
    if tag:
        want = tag.strip().lower()
        out = [r for r in out if want in {t.lower() for t in r.tags}]
    if query:
        canon = query_domain(query)
        if canon:
            tokens = DOMAINS[canon]
            out = [r for r in out if any(_domain_token_matches(t, r) for t in tokens)]
        else:
            qtokens = _tokens(query)
            if qtokens:
                out = [r for r in out if all(t in _haystack(r) for t in qtokens)]
                return sorted(out, key=lambda r: _query_sort_key(r, query, qtokens))
    return sorted(out, key=lambda r: (r.kind, r.key))


# --------------------------------------------------------------------------- #
# rankable lookup (canonical key, alias, version-tolerant, metric()/BENCHMARKS)
# --------------------------------------------------------------------------- #

_RANK_ALIAS: dict[str, str] = {}
for _k, _r in RANKABLES.items():
    for _a in (_k, _r.label, *_r.aliases):
        if _a:
            _RANK_ALIAS.setdefault(_norm(_a), _k)


def _strip_version(text: str) -> str:
    """Drop a trailing version suffix (``v4``, ``4.0``, ``2.1``, ``0.1``)."""
    return re.sub(r"[ _-]*v?\d+(?:\.\d+)*$", "", text.strip(), flags=re.IGNORECASE)


_RANK_ALIAS_STRIPPED: dict[str, str] = {}
for _k, _r in RANKABLES.items():
    for _a in (_k, _r.label, *_r.aliases):
        if _a:
            _s = _norm(_strip_version(_a))
            if _s:
                _RANK_ALIAS_STRIPPED.setdefault(_s, _k)


def rankable(key_or_alias: str) -> Rankable | None:
    """Resolve any key/label/alias (or metric/benchmark key) to a :class:`Rankable`."""
    if not key_or_alias:
        return None
    raw = key_or_alias.strip()
    if raw in RANKABLES:
        return RANKABLES[raw]
    k = _RANK_ALIAS.get(_norm(raw))
    if k:
        return RANKABLES[k]
    k = _RANK_ALIAS_STRIPPED.get(_norm(_strip_version(raw)))
    if k:
        return RANKABLES[k]
    k = _resolve_key(raw)          # fall back to metric() / BENCHMARKS vocabulary
    if k and k in RANKABLES:
        return RANKABLES[k]
    return None
