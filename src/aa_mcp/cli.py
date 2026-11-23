"""``aa-mcp`` from a plain shell — the same tools, no MCP client.

A skill-only or shell-only agent cannot speak MCP, so it cannot reach the tools.
This module is a dispatch shim over the *same* functions those tools call: the
functions registered with :mod:`aa_mcp.server`'s decorators are ordinary
callables (``_tool`` only wraps them with ``functools.wraps`` to convert failures
into ``ToolError`` text and to bound the reply), and every resource/prompt
function is an ordinary zero-or-n-arg callable too. So there is no second parser,
cache, formatter or dependency here — one data layer, two front doors. The MCP
SDK is imported only for ``schema``, which needs the SDK's own JSON-schema
derivation; every other subcommand runs without it (a ~3.6 s saving per call).

Usage (``python -m aa_mcp.cli`` is identical to the ``aa-mcp-cli`` script)::

    aa-mcp-cli list
    aa-mcp-cli schema aa_pareto
    aa-mcp-cli call aa_leaderboard '{"top":3}'
    aa-mcp-cli call aa_compare '{"queries":["claude-opus-5-5","gpt-6-luna"],"view":"diff"}'
    aa-mcp-cli read aa://sources
    aa-mcp-cli prompts
    aa-mcp-cli prompt best_model_for_task '{"task":"coding","budget":"$5/M tokens"}'

``call`` prints exactly the text the MCP tool returns (byte-identical), so a
skill can hand an agent these commands and the agent parses the same markdown it
would have got over MCP. stdout carries only that payload; every diagnostic goes
to stderr. Exit status: 0 ok — a complete answer, including informational replies
like "AA publishes this composite only through its paid API" (there is nothing to
retry); 1 the tool reported an input error or unavailable data the caller must act
on (its message is on stderr, no traceback); 2 bad usage (unknown
tool/resource, malformed JSON).

Arguments are the tool's own JSON object, exactly as an MCP client would send it;
validation is the tool's (``_tool``), not a second JSON-schema pass, so an
unexpected key comes back as the tool's ``ToolError`` text rather than a wire
error. The documented environment knobs are honoured unchanged because the same
code reads them: ``AA_CACHE_DIR`` (default ``~/.cache/aa-mcp``), ``AA_CACHE_TTL``
seconds, ``AA_OFFLINE=1`` (cache only, never touch the network), ``AA_RICH_TTL``,
``AA_MAX_BYTES``, ``AA_BASE_URL``, ``AA_LOG_LEVEL``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any

from aa_mcp import server

_ENV_HELP = (
    "Environment is read by the same data layer the MCP server uses: AA_CACHE_DIR "
    "(default ~/.cache/aa-mcp), AA_CACHE_TTL seconds, AA_OFFLINE=1 (cache only, no "
    "network), AA_RICH_TTL, AA_MAX_BYTES, AA_BASE_URL, AA_LOG_LEVEL. stdout carries "
    "only the reply; diagnostics go to stderr.\n"
    "Exit status: 0 = a complete answer, including informational replies such as "
    "'AA publishes this only through its paid API' or 'AA no longer publishes this "
    "metric'; 1 = a genuine input error or unavailable data the caller must act on; "
    "2 = bad usage (unknown tool, malformed JSON)."
)


# --------------------------------------------------------------------------- #
# the registries (the same records ``tools/list``, ``resources/list`` and
# ``prompts/list`` serve). ``call``/``list``/``read``/``prompts``/``prompt`` read
# the plain records the module keeps for its decorators, so they never import the
# MCP SDK; only ``schema`` needs the SDK's own JSON-schema derivation, and it
# says so by building the server.
# --------------------------------------------------------------------------- #

def _tools() -> dict[str, Any]:
    """The registered tools keyed by name; ``Tool.fn`` is the callable itself.

    This is the SDK's view — the wire ``inputSchema`` lives here — so it builds
    the ``MCPServer``. Use :func:`_tool_fns` for anything that only needs to call
    a tool.
    """
    return {tool.name: tool for tool in server.srv._tool_manager.list_tools()}


def _tool_fns() -> dict[str, server.Registration]:
    """The tool functions keyed by name, in registration order (no SDK import)."""
    return server.tool_functions()


def _resources() -> dict[str, server.Registration]:
    """The registered resources keyed by URI (no SDK import)."""
    return server.resource_functions()


def _prompts() -> dict[str, server.Registration]:
    """The registered prompts keyed by name (no SDK import)."""
    return server.prompt_functions()


def _names(registry: dict[str, Any]) -> str:
    return ", ".join(sorted(registry))


def _fail(message: str, code: int) -> int:
    """One-line diagnostic on stderr (stdout stays payload-only), then ``code``."""
    print(message, file=sys.stderr)
    return code


def _parse_args(raw: str) -> dict[str, Any] | None:
    """Parse a JSON object argument, or ``None`` after reporting why it failed."""
    try:
        args = json.loads(raw)
    except ValueError as exc:
        _fail(f"invalid JSON arguments: {exc}\n— pass one JSON object, e.g. "
              "'{\"top\":3}'", 2)
        return None
    if not isinstance(args, dict):
        _fail(f"invalid JSON arguments: expected an object, got "
              f"{type(args).__name__}\n— pass one JSON object, e.g. '{{\"top\":3}}'", 2)
        return None
    return args


# --------------------------------------------------------------------------- #
# subcommands
# --------------------------------------------------------------------------- #

def cmd_list() -> int:
    """Name + one-line description + parameter names for every tool, compact."""
    for name, spec in _tool_fns().items():
        lines = (spec.description or "").strip().splitlines()
        summary = lines[0] if lines else ""
        params = sorted(spec.param_names())
        print(f"{name}: {summary}")
        print(f"    params: {', '.join(params)}")
    return 0


def cmd_schema(names: list[str]) -> int:
    """The input schemas for one or every tool, as JSON (the harness's own shape)."""
    tools = _tools()
    unknown = [name for name in names if name not in tools]
    if unknown:
        return _fail(f"unknown tool{'s' if len(unknown) > 1 else ''}: "
                     f"{', '.join(unknown)}\n— available: {_names(tools)}", 2)
    chosen = [tools[name] for name in names] if names else list(tools.values())
    print("\n".join(json.dumps({"name": tool.name, "description": tool.description,
                                "input_schema": tool.parameters}, indent=1)
                    for tool in chosen))
    return 0


def cmd_call(name: str, raw: str) -> int:
    """Call one tool with a JSON object and print its reply verbatim."""
    tools = _tool_fns()
    tool = tools.get(name)
    if tool is None:
        return _fail(f"unknown tool: {name}\n— available: {_names(tools)}", 2)
    args = _parse_args(raw)
    if args is None:
        return 2
    try:
        text = tool.fn(**args)
    except server.ToolError as exc:
        return _fail(str(exc), 1)
    print(text)
    return 0


def cmd_read(uri: str) -> int:
    """Print one resource's text (the same bytes ``resources/read`` returns)."""
    resources = _resources()
    resource = resources.get(uri)
    if resource is None:
        return _fail(f"unknown resource: {uri}\n— available: {_names(resources)}", 2)
    print(resource.fn())
    return 0


def cmd_prompts() -> int:
    """Name + description for every prompt."""
    for prompt in _prompts().values():
        print(f"{prompt.name}: {(prompt.description or '').strip()}")
    return 0


def cmd_prompt(name: str, raw: str) -> int:
    """Render one prompt with a JSON object of arguments."""
    prompts = _prompts()
    prompt = prompts.get(name)
    if prompt is None:
        return _fail(f"unknown prompt: {name}\n— available: {_names(prompts)}", 2)
    args = _parse_args(raw)
    if args is None:
        return 2
    try:
        text = prompt.fn(**args)
    except Exception as exc:  # pydantic validation of the prompt's arguments
        return _fail(f"{type(exc).__name__}: {exc}", 2)
    print(text)
    return 0


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #

def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="aa-mcp-cli",
        description="Call the aa-mcp tools from a shell — the same functions and "
                    "the same data layer the MCP server uses, so output is identical.",
        epilog=_ENV_HELP,
    )
    sub = ap.add_subparsers(dest="command", required=True)

    c = sub.add_parser("call", help="call one tool and print its reply verbatim")
    c.add_argument("tool", help="tool name (see `list`)")
    c.add_argument("args", nargs="?", default="{}", metavar="JSON",
                   help="one JSON object of arguments, e.g. '{\"top\":3}'")

    sub.add_parser("list", help="tool inventory: names, one-line description, params")

    s = sub.add_parser("schema", help="input schemas as JSON")
    s.add_argument("tool", nargs="*", default=[], help="tool names; omit for all")

    r = sub.add_parser("read", help="print a resource's text")
    r.add_argument("uri", help="resource URI, e.g. aa://sources")

    sub.add_parser("prompts", help="prompt inventory")

    p = sub.add_parser("prompt", help="render one prompt")
    p.add_argument("name", help="prompt name (see `prompts`)")
    p.add_argument("args", nargs="?", default="{}", metavar="JSON",
                   help="one JSON object of arguments, e.g. '{\"task\":\"coding\"}'")
    return ap


def main(argv: list[str] | None = None) -> int:
    """Dispatch one subcommand. Never logs to stdout — agents parse the payload."""
    level = (os.environ.get("AA_LOG_LEVEL") or "WARNING").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.WARNING),
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = _parser().parse_args(argv)
    if args.command == "call":
        return cmd_call(args.tool, args.args)
    if args.command == "list":
        return cmd_list()
    if args.command == "schema":
        return cmd_schema(args.tool)
    if args.command == "read":
        return cmd_read(args.uri)
    if args.command == "prompts":
        return cmd_prompts()
    return cmd_prompt(args.name, args.args)


if __name__ == "__main__":
    raise SystemExit(main())
