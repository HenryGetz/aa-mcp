"""Tests for markdown rendering helpers."""

from __future__ import annotations

import time

from aa_mcp import render


def test_table_basic():
    out = render.table(["Model", "Intel"], [["Alpha", "60.0"], ["Beta", "40.0"]])
    assert out == "| Model | Intel |\n|---|---|\n| Alpha | 60.0 |\n| Beta | 40.0 |"


def test_table_empty_returns_empty_string():
    assert render.table(["A"], []) == ""
    assert render.table([], [["x"]]) == ""


def test_header_exact_shape():
    as_of = time.time() - 180
    line = render.header(700, 42, note="models · sorted by intelligence", source="rsc", as_of=as_of)
    assert line == "# 42/700 models · sorted by intelligence · 3m ago · aa:rsc"


def test_header_without_total_or_time():
    assert render.header(None, 10, note="models", source="rsc") == "# 10 models · aa:rsc"
    assert render.header(None, 10, note="models") == "# 10 models · aa:rsc"


def test_note():
    assert render.note(["stale cache", "estimates marked *"]) == "— stale cache\n— estimates marked *"
    assert render.note([]) == ""


def test_num_usd_pct():
    assert render.num(None) == "-"
    assert render.num(53.349, 1) == "53.3"
    assert render.usd(None) == "-"
    assert render.usd(7.6297) == "$7.63"
    assert render.usd(0.00512) == "$0.0051"
    assert render.pct(0.5727) == "57.3%"
    assert render.pct(None) == "-"


def test_ctx():
    assert render.ctx(None) == "-"
    assert render.ctx(128000) == "128k"
    assert render.ctx(1000000) == "1.0M"
    assert render.ctx(2000000) == "2.0M"
    assert render.ctx(512) == "512"


def test_ago():
    now = time.time()
    assert render.ago(now - 5) == "5s ago"
    assert render.ago(now - 180) == "3m ago"
    assert render.ago(now - 7200) == "2h ago"
    assert render.ago(now - 3 * 86400) == "3d ago"
    assert render.ago(None) == ""
