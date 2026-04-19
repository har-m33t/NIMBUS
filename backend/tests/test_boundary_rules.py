"""Phase 7.1 boundary detector: test all PROTOCOLS.md §2.2 rules (a-d)."""
from __future__ import annotations

import time

import pytest


def test_should_flush_rule_a_20_tokens():
    """Rule (a): len(glossBuffer) >= 20 triggers flush (20 unique letters = ~4-5 words)."""
    from handlers.process_frame import _should_flush

    buf_attrs = {
        "glossBuffer": list("ABCDEFGHIJKLMNOPQRST"),  # 20 single-char tokens
        "firstTokenAt": int(time.time() * 1000) - 100,
    }
    assert _should_flush(buf_attrs, []) is True


def test_should_flush_rule_b_10s_elapsed():
    """Rule (b): now() - firstTokenAt >= 10000ms triggers flush."""
    from handlers.process_frame import _should_flush

    buf_attrs = {
        "glossBuffer": ["A", "B", "C"],  # only 3 tokens
        "firstTokenAt": int(time.time() * 1000) - 10100,  # 10.1 seconds ago
    }
    assert _should_flush(buf_attrs, []) is True


def test_should_flush_rule_b_below_threshold():
    """Rule (b) does not trigger before 10s."""
    from handlers.process_frame import _should_flush

    buf_attrs = {
        "glossBuffer": ["A"],
        "firstTokenAt": int(time.time() * 1000) - 5000,  # only 5s ago
    }
    assert _should_flush(buf_attrs, []) is False


def test_should_flush_rule_d_eos_token():
    """Rule (d): [EOS] token in new_tokens triggers flush."""
    from handlers.process_frame import _should_flush

    buf_attrs = {"glossBuffer": ["A"], "firstTokenAt": int(time.time() * 1000) - 100}
    # EOS in the new tokens being appended
    assert _should_flush(buf_attrs, ["HELLO", "[EOS]"]) is True


def test_should_flush_no_eos():
    """No flush if no EOS and below limits."""
    from handlers.process_frame import _should_flush

    buf_attrs = {
        "glossBuffer": ["A", "B", "C"],
        "firstTokenAt": int(time.time() * 1000) - 100,  # very recent
    }
    assert _should_flush(buf_attrs, ["D", "E"]) is False


def test_boundary_detector_all_four_rules():
    """Comprehensive: test rule (a), (b), (d) in _should_flush; (c) in sweep."""
    from handlers.process_frame import _should_flush

    now_ms = int(time.time() * 1000)

    # Rule (a): 20+ tokens
    assert _should_flush({"glossBuffer": ["X"] * 20, "firstTokenAt": now_ms}, [])

    # Rule (b): 10s+ elapsed
    assert _should_flush({"glossBuffer": ["X"], "firstTokenAt": now_ms - 10100}, [])

    # Rule (d): [EOS] token
    assert _should_flush({"glossBuffer": ["X"], "firstTokenAt": now_ms}, ["Y", "[EOS]"])

    # No flush: none triggered
    assert not _should_flush({"glossBuffer": ["X"], "firstTokenAt": now_ms}, ["Y"])
