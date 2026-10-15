#!/usr/bin/env python3
"""Stdio MCP client harness for aa-mcp — used by the orchestrator and by
agent-in-the-loop evaluations.

Usage (from the repo root):
    .venv/bin/python eval/client.py tools                 # tool inventory (compact)
    .venv/bin/python eval/client.py schema                # full input schemas (JSON)
    .venv/bin/python eval/client.py call aa_leaderboard '{"top":5}'
    .venv/bin/python eval/client.py resources
    .venv/bin/python eval/client.py read aa://reference/metrics
    .venv/bin/python eval/client.py prompts
    .venv/bin/python eval/client.py prompt best_model_for_task '{"task":"coding"}'
    .venv/bin/python eval/client.py bench                 # panel: size/token report
    .venv/bin/python eval/client.py raw aa_model '{"query":"claude opus 5.5"}'

Every `call` appends one NDJSON record to $AA_EVAL_LOG
(default eval/runs/live.ndjson) with tool name, args, wall ms, result chars and
an estimated token count (chars/4). That log is the evidence used for iteration.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import pathlib
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_LOG = REPO / "eval" / "runs" / "live.ndjson"
BENCH_PANEL: list[tuple[str, dict]] = [
    ("aa_leaderboard", {"top": 5}),
    ("aa_leaderboard", {"mode": "frontier", "top": 12}),
    ("aa_leaderboard", {"sort": "tps", "top": 5}),
    ("aa_search", {"query": "claude"}),
    ("aa_model", {"query": "claude opus 5.5"}),
    ("aa_compare", {"queries": ["gpt-6-astra", "claude-opus-5-5"]}),
    ("aa_benchmarks", {}),
    ("aa_benchmark_leaderboard", {"benchmark": "gpqa"}),
    ("aa_providers", {"model": "claude-opus-5-5"}),
    ("aa_providers", {"host": "groq", "top": 5}),
    ("aa_media", {"board": "text_to_image", "top": 5}),
    ("aa_agents", {"board": "coding_agents", "top": 5}),
    ("aa_reference", {"topic": "overview"}),
]


def _server_params(argv_env: list[str]) -> object:
    from mcp import StdioServerParameters

    env = dict(os.environ)
    for item in argv_env:
        key, _, val = item.partition("=")
        env[key] = val
    override = os.environ.get("AA_MCP_CMD")
    if override:
        return StdioServerParameters(command=override, args=[], env=env)
    exe = REPO / ".venv" / "bin" / "aa-mcp"
    if exe.exists():
        return StdioServerParameters(command=str(exe), args=[], env=env)
    return StdioServerParameters(
        command=str(REPO / ".venv" / "bin" / "python"),
        args=["-m", "aa_mcp.server"],
        env=env,
    )


def _log(record: dict, path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")


def _tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


async def _with_session(env: list[str], fn):
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    params = _server_params(env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await fn(session)


def _result_text(result) -> str:
    parts = []
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
    return "\n".join(parts)


def cmd_tools(session) -> str:
    listing = asyncio.run(session)
    return listing


def _clean(obj):
    """Drop lone surrogates so a hostile argument cannot break the JSON wire."""
    if isinstance(obj, str):
        return obj.encode("utf-8", "replace").decode("utf-8")
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj


def main() -> int:
    ap = argparse.ArgumentParser(description="aa-mcp stdio client harness")
    ap.add_argument("--log", default=os.environ.get("AA_EVAL_LOG", str(DEFAULT_LOG)))
    ap.add_argument("--env", action="append", default=[], metavar="K=V")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("tools")
    s = sub.add_parser("schema")
    s.add_argument("tool", nargs="*", default=[],
                   help="one or more tool names; omit for every schema")
    sub.add_parser("resources")
    sub.add_parser("prompts")
    sub.add_parser("bench")

    c = sub.add_parser("call")
    c.add_argument("tool")
    c.add_argument("args", nargs="?", default="{}")
    r = sub.add_parser("read")
    r.add_argument("uri")

    p = sub.add_parser("prompt")
    p.add_argument("name")
    p.add_argument("args", nargs="?", default="{}")

    a = ap.parse_args()
    log_path = pathlib.Path(a.log)

    if a.cmd in ("tools", "schema"):
        wanted = {t.lower() for t in getattr(a, "tool", []) or []}

        async def go(session):
            res = await session.list_tools()
            out = []
            for t in res.tools:
                if wanted and t.name.lower() not in wanted:
                    continue
                desc = (t.description or "").strip().splitlines()
                summary = desc[0] if desc else ""
                params = sorted((t.input_schema or {}).get("properties", {}))
                if a.cmd == "tools":
                    out.append(f"{t.name}: {summary}\n    params: {', '.join(params)}")
                else:
                    out.append(json.dumps(
                        {"name": t.name, "description": t.description,
                         "input_schema": t.input_schema}, indent=1))
            if not out and wanted:
                known = ", ".join(sorted(x.name for x in res.tools))
                return f"no tool matched {sorted(wanted)} — available: {known}"
            return "\n".join(out)
        print(asyncio.run(_with_session(a.env, go)))
        return 0

    if a.cmd == "resources":
        async def go(session):
            res = await session.list_resources()
            return "\n".join(f"{x.uri}  {x.name or ''}  {x.mime_type or ''}"
                             for x in res.resources)
        print(asyncio.run(_with_session(a.env, go)))
        return 0

    if a.cmd == "prompts":
        async def go(session):
            res = await session.list_prompts()
            return "\n".join(f"{x.name}: {(x.description or '').strip()}"
                             for x in res.prompts)
        print(asyncio.run(_with_session(a.env, go)))
        return 0

    if a.cmd == "read":
        async def go(session):
            res = await session.read_resource(a.uri)
            parts = [c.text for c in res.contents if getattr(c, "text", None)]
            return "\n".join(parts)
        text = asyncio.run(_with_session(a.env, go))
        print(text)
        _log({"kind": "read", "uri": a.uri, "chars": len(text),
              "tokens_est": _tokens(text)}, log_path)
        return 0

    if a.cmd == "prompt":
        args = _clean(json.loads(a.args))

        async def go(session):
            res = await session.get_prompt(a.name, args)
            return "\n".join(getattr(m.content, "text", "") for m in res.messages)
        text = asyncio.run(_with_session(a.env, go))
        print(text)
        return 0

    if a.cmd == "call":
        args = _clean(json.loads(a.args))

        async def go(session):
            t0 = time.time()
            result = await session.call_tool(a.tool, args)
            return result, (time.time() - t0) * 1000
        result, ms = asyncio.run(_with_session(a.env, go))
        text = _result_text(result)
        print(text)
        rec = {"kind": "call", "tool": a.tool, "args": args, "ms": round(ms),
               "chars": len(text), "tokens_est": _tokens(text),
               "is_error": bool(result.is_error)}
        _log(rec, log_path)
        print(f"\n[harness] {rec['chars']} chars ≈ {rec['tokens_est']} tok · "
              f"{rec['ms']}ms · error={rec['is_error']}", file=sys.stderr)
        return 0 if not result.is_error else 1

    if a.cmd == "bench":
        rows = []

        async def one(session, tool, args):
            t0 = time.time()
            try:
                result = await session.call_tool(tool, args)
                text = _result_text(result)
                err = bool(result.is_error)
            except Exception as exc:
                text, err, result = f"EXC {type(exc).__name__}: {exc}", True, None
            ms = round((time.time() - t0) * 1000)
            rec = {"kind": "bench", "tool": tool, "args": args, "ms": ms,
                   "chars": len(text), "tokens_est": _tokens(text), "is_error": err}
            _log(rec, log_path)
            return rec, text

        async def go(session):
            out = []
            for tool, args in BENCH_PANEL:
                rec, text = await one(session, tool, args)
                out.append((rec, text))
            return out
        results = asyncio.run(_with_session(a.env, go))
        total = 0
        for rec, text in results:
            total += rec["tokens_est"]
            first = text.splitlines()[0][:80] if text else ""
            rows.append(f"{rec['tool']:26} {rec['tokens_est']:>6} tok {rec['ms']:>6}ms "
                        f"{'ERR' if rec['is_error'] else '   '} | {first}")
            if rec["is_error"]:
                rows.append("      " + text.strip().replace("\n", " ")[:300])
        print("\n".join(rows))
        print(f"\nTOTAL ≈ {total} tokens for {len(results)} calls "
              f"(avg {total // max(1, len(results))})")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
