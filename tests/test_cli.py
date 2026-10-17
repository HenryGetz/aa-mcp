"""Tests for the CLI shim: the same functions, the same bytes, clean errors.

The CLI is a dispatch table over the tool/resource/prompt functions the MCP
server already registers, so the strongest offline assertion is an identity one:
the CLI's stdout must equal what the *MCP layer itself* returns for the same
call (``srv.call_tool`` / ``srv.read_resource`` / ``srv.get_prompt``, called
in-process — no client, no subprocess). The data layer is replaced by hand-built
``Model`` objects (the pattern ``tests/test_server.py`` uses), so nothing here
touches the network.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import subprocess
import sys

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from aa_mcp import cli, reference, server
from aa_mcp.normalize import Model

REPO = pathlib.Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #

def _model(slug: str, name: str | None = None, **overrides) -> Model:
    """A minimal ``Model`` (the shape ``_panel_model`` builds), overridable."""
    values: dict = {
        "slug": slug, "name": name or slug.title(), "short_name": name or slug.title(),
        "creator": "Lab", "creator_slug": "lab", "release_date": "2026-01-01",
        "deprecated": False, "deprecated_to": None, "is_reasoning": False,
        "is_open_weights": False, "effort": None, "params_b": None,
        "active_params_b": None, "context_tokens": 128_000, "license": None,
        "license_url": None, "weights_url": None, "knowledge_cutoff": None,
        "size_class": None, "modalities_in": (), "modalities_out": (),
        "intelligence": None, "estimated": False, "indices": {}, "evals": {},
        "pricing": {}, "speed": {}, "cost_per_task": None, "cost_breakdown": None,
        "per_eval_cost": None, "per_eval": None, "source": "leaderboard",
    }
    values.update(overrides)
    return Model(**values)


@pytest.fixture
def fake(monkeypatch):
    """Two models + a patched data layer, so a real tool renders real markdown."""
    alpha = _model("alpha", "Alpha One", creator="LabA", intelligence=60.0,
                   cost_per_task=1.0, pricing={"in": 1.0, "out": 2.0},
                   speed={"tps": 100.0, "ttft": 1.0, "out_tokens_per_task": 2_000.0})
    beta = _model("beta", "Beta Two", creator="LabB", intelligence=50.0,
                  cost_per_task=0.5)
    models = [alpha, beta]
    monkeypatch.setattr(server, "_models_state",
                        lambda refresh=False, rich=True: (models, rich))
    monkeypatch.setattr(server, "_lb_rows", lambda refresh=False: models)
    monkeypatch.setattr(server, "_rich_models", lambda refresh=False: models)
    monkeypatch.setattr(server, "_lb_cache", lambda: "leaderboard")
    monkeypatch.setattr(server, "_source_key", lambda: "rsc")
    monkeypatch.setattr(server, "_fresh", lambda name: (None, False))
    monkeypatch.setattr(server, "_extra_score_models", lambda key, refresh=False: [])
    monkeypatch.setattr(server, "_arena_entries", lambda refresh=False: [])
    return {m.slug: m for m in models}


def _mcp_text(tool: str, args: dict) -> str:
    """The text an MCP client receives for this call, without a client."""
    result = asyncio.run(server.srv.call_tool(tool, args))
    return "\n".join(block.text for block in result.content
                     if getattr(block, "text", None) is not None)


# --------------------------------------------------------------------------- #
# list
# --------------------------------------------------------------------------- #

def test_list_names_every_tool_with_a_summary_and_its_params(capsys):
    assert cli.main(["list"]) == 0
    lines = capsys.readouterr().out.splitlines()

    tools = cli._tools()
    assert len(lines) == 2 * len(tools)
    for tool, summary, params in zip(tools.values(), lines[::2], lines[1::2],
                                     strict=True):
        assert summary == f"{tool.name}: {(tool.description or '').strip().splitlines()[0]}"
        assert params == "    params: " + ", ".join(
            sorted(tool.parameters["properties"]))


def test_list_is_compact_and_mentions_every_name(capsys):
    cli.main(["list"])
    out = capsys.readouterr().out
    assert out.count("\n") == 2 * len(cli._tools())
    for name in ("aa_leaderboard", "aa_pareto", "aa_compare", "aa_raw"):
        assert f"\n{name}: " in "\n" + out


# --------------------------------------------------------------------------- #
# call
# --------------------------------------------------------------------------- #

def test_call_stdout_equals_the_mcp_layers_own_reply(fake, capsys):
    args = {"top": 2}
    assert cli.main(["call", "aa_leaderboard", json.dumps(args)]) == 0
    out = capsys.readouterr().out
    assert out == _mcp_text("aa_leaderboard", args) + "\n"
    # ...which is the tool function's own return value, byte for byte.
    assert out == server.aa_leaderboard(top=2) + "\n"


def test_call_without_args_uses_the_tool_defaults(capsys):
    assert cli.main(["call", "aa_reference"]) == 0
    assert capsys.readouterr().out == server.aa_reference() + "\n"


def test_call_stdout_is_only_the_payload(capsys, monkeypatch):
    """Agents parse stdout, so nothing but the reply may land there."""
    monkeypatch.setenv("AA_LOG_LEVEL", "DEBUG")
    assert cli.main(["call", "aa_reference", '{"topic":"sources"}']) == 0
    captured = capsys.readouterr()
    assert captured.out == server.aa_reference(topic="sources") + "\n"
    assert captured.out.count("\n") == captured.out.rstrip("\n").count("\n") + 1


def test_call_does_not_leak_a_traceback_on_a_tool_error(fake, capsys):
    with pytest.raises(ToolError) as excinfo:
        server.aa_model(query="no-such-model-anywhere")
    message = str(excinfo.value)

    assert cli.main(["call", "aa_model", '{"query":"no-such-model-anywhere"}']) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == message
    assert "Traceback" not in captured.err


def test_call_unknown_tool_lists_the_valid_ones(capsys):
    assert cli.main(["call", "aa_nope", "{}"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unknown tool: aa_nope" in captured.err
    for name in cli._tools():
        assert name in captured.err


@pytest.mark.parametrize("raw", ["{top:3}", "", "not json", "[1, 2]", '"aa_pareto"'])
def test_call_malformed_json_arguments(raw, capsys):
    assert cli.main(["call", "aa_pareto", raw]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "invalid JSON arguments" in captured.err
    assert "Traceback" not in captured.err


# --------------------------------------------------------------------------- #
# schema
# --------------------------------------------------------------------------- #

def test_schema_emits_one_tool_as_json(capsys):
    assert cli.main(["schema", "aa_pareto"]) == 0
    payload = json.loads(capsys.readouterr().out)
    tool = cli._tools()["aa_pareto"]
    assert payload == {"name": "aa_pareto", "description": tool.description,
                       "input_schema": tool.parameters}


def test_schema_without_names_emits_every_tool(capsys):
    assert cli.main(["schema"]) == 0
    out = capsys.readouterr().out
    decoder = json.JSONDecoder()
    names: list[str] = []
    idx = 0
    while idx < len(out):  # one JSON object per tool, newline-joined
        while idx < len(out) and out[idx].isspace():
            idx += 1
        if idx == len(out):
            break
        payload, idx = decoder.raw_decode(out, idx)
        names.append(payload["name"])
    assert names == list(cli._tools())


def test_schema_unknown_tool_lists_the_valid_ones(capsys):
    assert cli.main(["schema", "aa_pareto", "aa_nope"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unknown tool: aa_nope" in captured.err
    assert "aa_leaderboard" in captured.err


# --------------------------------------------------------------------------- #
# read
# --------------------------------------------------------------------------- #

def test_read_prints_the_resource_text(capsys):
    assert cli.main(["read", "aa://sources"]) == 0
    out = capsys.readouterr().out
    assert out == reference.TOPICS["sources"] + "\n"
    contents = asyncio.run(server.srv.read_resource("aa://sources"))
    assert out == "".join(part.content for part in contents) + "\n"


def test_read_unknown_uri_lists_the_valid_ones(capsys):
    assert cli.main(["read", "aa://nope"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unknown resource: aa://nope" in captured.err
    assert "aa://rankables" in captured.err


# --------------------------------------------------------------------------- #
# prompts
# --------------------------------------------------------------------------- #

def test_prompts_lists_every_prompt(capsys):
    assert cli.main(["prompts"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines == [f"{prompt.name}: {(prompt.description or '').strip()}"
                     for prompt in cli._prompts().values()]


def test_prompt_renders_like_the_mcp_layer(capsys):
    args = {"task": "coding", "budget": "$5/M tokens"}
    assert cli.main(["prompt", "best_model_for_task", json.dumps(args)]) == 0
    out = capsys.readouterr().out
    rendered = asyncio.run(server.srv.get_prompt("best_model_for_task", args))
    assert out == "\n".join(m.content.text for m in rendered.messages) + "\n"


def test_prompt_unknown_name_lists_the_valid_ones(capsys):
    assert cli.main(["prompt", "nope", "{}"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unknown prompt: nope" in captured.err
    assert "compare_models" in captured.err


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #

def test_python_dash_m_runs_the_same_dispatch():
    proc = subprocess.run([sys.executable, "-m", "aa_mcp.cli", "list"],
                          cwd=REPO, capture_output=True, text=True, check=False)
    assert proc.returncode == 0
    assert proc.stdout.startswith("aa_leaderboard: ")
    assert proc.stderr == ""


def test_python_dash_m_reports_errors_on_stderr_only():
    proc = subprocess.run([sys.executable, "-m", "aa_mcp.cli", "call", "aa_nope", "{}"],
                          cwd=REPO, capture_output=True, text=True, check=False)
    assert proc.returncode == 2
    assert proc.stdout == ""
    assert "unknown tool: aa_nope" in proc.stderr
