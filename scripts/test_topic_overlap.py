#!/usr/bin/env python3
"""Assert near-duplicate psychology topics are blocked."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common import (  # noqa: E402
    filter_topics_against_history,
    load_topic_history,
    topic_overlaps_history,
    topic_similarity_ratio,
)


def main() -> None:
    history = load_topic_history()
    assert history, "topic_history.json must list published videos"

    # Exact channel failure mode that shipped Jul 13–17.
    never = "The Psychology of People Who Never Ask for Help"
    hate = "The Psychology of People Who Hate Asking for Help"
    reason = topic_overlaps_history(hate, [{"title": never, "topic": never}])
    assert reason, f"expected overlap for hate≈never, got {reason!r}"
    print("ok hate~never:", reason)

    ratio = topic_similarity_ratio(hate, never)
    assert ratio >= 0.72, ratio
    print(f"ok similarity={ratio:.2f}")

    # Distinct themes must still pass.
    fresh = "The Psychology of People Who Fear Success Explained"
    assert topic_overlaps_history(fresh, [{"title": never, "topic": never}]) is None
    print("ok distinct theme allowed")

    # History file should block both help angles against each other.
    kept, rejected = filter_topics_against_history(
        [hate, "The Psychology of Chronic Boredom Explained"],
        history,
    )
    assert any("Hate Asking" in t or "Asking for Help" in t for t, _ in rejected) or hate not in kept
    assert any("Boredom" in t for t in kept)
    print(f"ok filter kept={kept} rejected={len(rejected)}")
    print("ALL TOPIC OVERLAP CHECKS PASSED")


if __name__ == "__main__":
    main()
