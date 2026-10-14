"""Tests for RSC flight payload parsing."""

from __future__ import annotations

import json
import pathlib
import threading
import time

import pytest

from aa_mcp import flight

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------- #
# payload()
# --------------------------------------------------------------------------- #

def test_payload_raw_rsc_passthrough():
    raw = _read("leaderboard.rsc")
    assert flight.payload(raw) is raw


def test_payload_joins_html_chunks():
    chunk = '1:"$Sreact.fragment"\n32:[{"a":1,"b":2}]\n'
    html = (
        "<html><body><script>self.__next_f.push("
        + json.dumps([1, chunk])
        + ")</script><script>self.__next_f.push("
        + json.dumps([1, "35:tail"])
        + ")</script></body></html>"
    )
    joined = flight.payload(html)
    assert joined == chunk + "35:tail"
    assert flight.find_array(joined, ["a", "b"]) == [{"a": 1, "b": 2}]


# --------------------------------------------------------------------------- #
# find_array()
# --------------------------------------------------------------------------- #

def test_leaderboard_array_by_required_keys():
    p = flight.payload(_read("leaderboard.rsc"))
    arr = flight.find_array(p, ["intelligenceIndex"])
    assert len(arr) == 700
    assert all(isinstance(r, dict) for r in arr)
    # the nav array (name/releaseSlug/slug) is NOT matched
    assert "intelligenceIndex" in arr[0]


def test_find_array_min_len_and_lookup_error():
    p = flight.payload(_read("model_page_legacy.rsc"))
    # the legacy page's ref arrays lead with a club of "…:models:<N>" strings;
    # the first *dict* element is what the scan probes (audit H4).
    chart = flight.find_array(p, ["chartDefaultSelected", "releaseDate", "suffix"])
    assert len(chart) == 700
    assert isinstance(chart[0], str) and chart[1]["slug"]
    assert len(flight.find_array(p, ["intelligenceIndex"])) == 700
    with pytest.raises(LookupError):
        flight.find_array(p, ["intelligenceIndex"], min_len=5000)
    with pytest.raises(LookupError):
        flight.find_array(p, ["definitelyNotAKey"])


def test_find_array_last():
    text = '0:[{"k":1,"v":"a"}]\n1:[{"k":2,"v":"b"}]'
    assert flight.find_array(text, ["k", "v"], last=False)[0]["k"] == 1
    assert flight.find_array(text, ["k", "v"], last=True)[0]["k"] == 2


def test_find_array_nested_in_flight_row():
    text = '32:[[null,[{"values":{"name":"X"},"formatted":{"elo":1}}]]]'
    arr = flight.find_array(text, ["values", "formatted"])
    assert arr == [{"values": {"name": "X"}, "formatted": {"elo": 1}}]


def test_find_arrays_returns_all():
    text = '0:[{"k":1}]\n1:[{"k":2}]\n2:[{"other":3}]'
    arrays = flight.find_arrays(text, ["k"])
    assert [a[0]["k"] for a in arrays] == [1, 2]


def test_find_array_skips_non_dict_arrays():
    text = '0:[1,2,3]\n1:["a","b"]\n2:[{"k":9}]'
    assert flight.find_array(text, ["k"]) == [{"k": 9}]


@pytest.mark.parametrize("name", ["providers_board.rsc", "model_page_legacy.rsc"])
def test_find_array_performance(name):
    p = flight.payload(_read(name))
    start = time.perf_counter()
    with pytest.raises(LookupError):
        flight.find_array(p, ["__absent_key_for_full_scan__"])
    elapsed = time.perf_counter() - start
    assert elapsed < 1.5, f"{name} full scan took {elapsed:.3f}s"


def test_find_array_chart_and_providers():
    chart = flight.payload(_read("model_page_chart.rsc"))
    assert len(flight.find_array(chart, ["intelligenceIndexCostPerTask"])) == 27
    board = flight.payload(_read("providers_board.rsc"))
    assert len(flight.find_array(board, ["host", "model"])) == 1201


# --------------------------------------------------------------------------- #
# keyed_object()
# --------------------------------------------------------------------------- #

def test_keyed_object_legacy_current_model():
    p = flight.payload(_read("model_page_legacy.rsc"))
    cur = flight.keyed_object(p, "currentModel")
    assert isinstance(cur, dict)
    assert cur["slug"] == "glm-4-5v"


def test_keyed_object_ignores_string_occurrences():
    text = (
        '"note":"currentModel is a field name",'
        '"other":{"currentModel":"just a string"},'
        '"currentModel":{"slug":"real-model","n":1}'
    )
    obj = flight.keyed_object(text, "currentModel")
    assert obj == {"slug": "real-model", "n": 1}


def test_keyed_object_missing():
    assert flight.keyed_object("a:[1,2]", "currentModel") is None


def test_find_objects_nested_object_in_flight_row():
    text = (
        '68:[["$","$L5b",null,{"param":"cyber-index","tabs":[{"value":"cyber-index",'
        '"panel":["$","$L7b",null,{"evalSlug":"artificial-analysis-cyber-index",'
        '"models":[{"slug":"step-5"}]}]}]}]]'
    )
    objs = flight.find_objects(text, ["evalSlug", "models"])
    assert len(objs) == 1
    assert objs[0]["evalSlug"] == "artificial-analysis-cyber-index"
    assert objs[0]["models"] == [{"slug": "step-5"}]


def test_find_objects_limit_and_absent_keys():
    text = '{"a":1,"b":2}{"a":3,"b":4}'
    assert len(flight.find_objects(text, ["a", "b"])) == 2
    assert len(flight.find_objects(text, ["a", "b"], limit=1)) == 1
    assert flight.find_objects(text, ["a", "zzz"]) == []


def test_find_objects_home_eval_panels():
    p = flight.payload(_read("home.rsc"))
    panels = flight.find_objects(p, ["evalSlug", "models"])
    slugs = {o["evalSlug"] for o in panels}
    assert slugs == {
        "artificial-analysis-cyber-index",
        "cwe-bench-aa",
        "deepsecbench-aa",
        "cybergym-e2e-aa",
    }
    assert all(isinstance(o["models"], list) and o["models"] for o in panels)


def test_find_objects_performance_legacy():
    p = flight.payload(_read("model_page_legacy.rsc"))
    start = time.perf_counter()
    objs = flight.find_objects(p, ["slug", "name"])
    elapsed = time.perf_counter() - start
    assert objs and all("slug" in o and "name" in o for o in objs)
    assert elapsed < 1.5, f"find_objects took {elapsed:.3f}s"


# --------------------------------------------------------------------------- #
# jsonld / text_strip_tags
# --------------------------------------------------------------------------- #

def test_jsonld_html():
    html = (
        '<script type="application/ld+json">{"@type":"FAQPage"}</script>'
        '<script type="application/ld+json">[{"a":1},{"b":2}]</script>'
        '<script type="application/ld+json">not json</script>'
    )
    blocks = flight.jsonld(html)
    assert {"@type": "FAQPage"} in blocks
    assert {"a": 1} in blocks and {"b": 2} in blocks
    assert len(blocks) == 3  # 1 dict + 2 items from the list block


def test_jsonld_raw_rsc_fallback():
    p = flight.payload(_read("media_t2i.rsc"))
    blocks = flight.jsonld(p)
    assert blocks
    texts = [
        b.get("acceptedAnswer", {}).get("text", "")
        for b in blocks
        if isinstance(b.get("acceptedAnswer"), dict)
    ]
    assert any("GPT Image 2.5 Sunburst (max)" in t and "1217" in t for t in texts)


def test_text_strip_tags():
    assert flight.text_strip_tags("<p>Hello&nbsp;  <b>world</b></p>") == "Hello world"
    assert flight.text_strip_tags("") == ""


# --------------------------------------------------------------------------- #
# content-addressed memos
# --------------------------------------------------------------------------- #

def test_payload_memo_only_wraps_the_html_join():
    flight._clear_memos()
    raw_a = _read("leaderboard.rsc")
    raw_b = _read("leaderboard.rsc")
    assert raw_a is not raw_b
    # raw RSC passes straight through, so each caller keeps its own object
    assert flight.payload(raw_a) is raw_a
    assert flight.payload(raw_b) is raw_b

    chunk = '0:[{"a":1}]'
    html = "<script>self.__next_f.push(" + json.dumps([1, chunk]) + ")</script>"
    joined = flight.payload(html)
    assert joined == chunk
    assert flight.payload(html) is joined   # the HTML join is memoised


def test_scan_memo_is_content_addressed():
    flight._clear_memos()
    # same length, same keys, different content: the entries must not be shared
    p1 = '0:[{"k":1,"v":"a"}]'
    p2 = '0:[{"k":2,"v":"a"}]'
    assert len(p1) == len(p2)
    assert flight.find_array(p1, ["k", "v"])[0]["k"] == 1
    assert flight.find_array(p2, ["k", "v"])[0]["k"] == 2


def test_scan_memo_reuses_the_decoded_array_and_rescans_on_change():
    flight._clear_memos()
    page = '0:[{"k":1,"v":"a"}]'
    first = flight.find_array(page, ["k", "v"])
    assert flight.find_array(page, ["k", "v"]) is first          # served from the memo
    # a payload whose content changed (refresh) must be re-scanned
    changed = '0:[{"k":9,"v":"a"}]'
    assert flight.find_array(changed, ["k", "v"])[0]["k"] == 9


def test_find_array_and_find_arrays_share_one_decoded_copy():
    flight._clear_memos()
    page = '0:[{"k":1,"v":"a"}]'
    arrays = flight.find_arrays(page, ["k", "v"])
    assert flight.find_array(page, ["k", "v"]) is arrays[0]
    assert len(flight._SCAN_MEMO._entries) == 1


def test_scan_memo_is_bounded():
    flight._clear_memos()
    for i in range(flight._MEMO_MAXSIZE * 3):
        flight.find_arrays(f'0:[{{"k":{i}}}]', ["k"])
    assert len(flight._SCAN_MEMO._entries) <= flight._MEMO_MAXSIZE


def test_memo_publication_is_thread_safe():
    memo = flight._Memo(8, 1024 * 1024)
    errors: list[BaseException] = []

    def worker(n: int) -> None:
        try:
            for i in range(500):
                memo.put((n % 16, i), [i], 16)
                memo.get((n % 16, i))
        except BaseException as exc:  # pragma: no cover - a race would surface here
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    assert len(memo._entries) <= 8
    assert memo._bytes <= 1024 * 1024
