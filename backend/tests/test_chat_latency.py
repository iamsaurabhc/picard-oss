"""Tests for chat latency diagnostics."""

from app.services.chat_latency import ChatLatencyTracker


def test_latency_tracker_phases():
    tracker = ChatLatencyTracker()
    with tracker.phase("understanding"):
        pass
    with tracker.phase("retrieval"):
        pass
    d = tracker.to_dict()
    assert "understanding" in d
    assert "retrieval" in d
    assert "total_pre_synthesis" in d


def test_latency_tracker_synthesis_ttft():
    tracker = ChatLatencyTracker()
    tracker.mark_synthesis_start()
    tracker.mark_first_content_token()
    d = tracker.to_dict()
    assert "synthesis_ttft" in d
    assert d["synthesis_ttft"] >= 0
