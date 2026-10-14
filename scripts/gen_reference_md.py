#!/usr/bin/env python3
"""Regenerate ``docs/REFERENCE.md`` from :mod:`aa_mcp.reference`.

``src/aa_mcp/reference.py`` is the single source of truth for the reference
text served by the ``aa_reference`` tool and the ``aa://reference/*``
resources; this script renders it back to markdown so the two files cannot
drift. Run from the repo root::

    .venv/bin/python scripts/gen_reference_md.py [--check]

``--check`` exits non-zero when ``docs/REFERENCE.md`` differs from the
rendered text instead of rewriting it.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from aa_mcp import reference  # noqa: E402

TARGET = REPO / "docs" / "REFERENCE.md"


def render() -> str:
    """Render the reference markdown from :mod:`aa_mcp.reference`."""
    body = "\n\n".join(f"## {topic}\n\n{text}" for topic, text in reference.TOPICS.items())
    return reference.PREAMBLE + "\n\n" + body + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="verify docs/REFERENCE.md is up to date without writing")
    args = ap.parse_args()

    text = render()
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != text:
            print(f"{TARGET} is out of date; re-run scripts/gen_reference_md.py",
                  file=sys.stderr)
            return 1
        print(f"{TARGET} is up to date ({len(text)} chars)", file=sys.stderr)
        return 0

    TARGET.write_text(text, encoding="utf-8")
    print(f"wrote {TARGET} ({len(text)} chars)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
