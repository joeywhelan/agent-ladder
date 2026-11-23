"""The human baseline: input features from recorded human sessions, and the
frozen input_stats thresholds derived from them (notebook Section 3).

Each human session is reduced to four numbers that describe how the person
typed and moved the mouse. The allowed range for each number runs from the
lowest to the highest human value, widened by a margin. Later, input_stats
flags a session whose numbers fall outside those ranges.

Taking the full human range means none of these sessions can be flagged by
input_stats, so the false-alarm count in the results says little about
input_stats itself; it mostly measures the other checks and the VA.
"""

import json
import statistics

from agent_ladder.store import HUMANS_DIR, read_records

THRESHOLDS_FILE = HUMANS_DIR / "input_stats_thresholds.json"
HUMAN_SESSIONS_EXPECTED = 10
# Widen each human range by this fraction of its width on both sides, so a
# person typing slightly faster or slower than the slowest or fastest tester
# isn't flagged.
RANGE_MARGIN = 0.10
FEATURE_NAMES = (
    "median_key_interval_ms",
    "key_interval_variation",
    "correction_rate",
    "mouse_moves_per_message",
)
FEATURE_DESCRIPTIONS = {
    "median_key_interval_ms": "typical time between two key presses in a message",
    "key_interval_variation": "how uneven that rhythm is (standard deviation / mean)",
    "correction_rate": "Backspace and Delete presses per character typed",
    "mouse_moves_per_message": "mouse movement events before each send",
}


def load_human_sessions() -> dict[str, list[dict]]:
    """Read every recorded human session from assets/humans/, keyed by session ID."""
    sessions = {}
    if not HUMANS_DIR.exists():
        return sessions
    for path in sorted(HUMANS_DIR.glob("*.jsonl")):
        events = []
        with path.open(encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        sessions[path.stem] = events
    return sessions


def split_into_messages(events: list[dict]) -> list[list[dict]]:
    """Group a session's key, paste and mouse events by the message they led up to.

    Each group ends with that message's send event. Events after the last send
    belong to no message and are dropped.
    """
    messages = []
    current = []
    for event in events:
        if event["kind"] == "load":
            continue
        current.append(event)
        if event["kind"] == "send":
            messages.append(current)
            current = []
    return messages


def key_intervals_ms(message_events: list[dict]) -> list[float]:
    """Gaps between consecutive key presses within one message."""
    press_times = []
    for event in message_events:
        if event["kind"] == "key" and event["detail"].get("type") == "down":
            press_times.append(event["t_ms"])

    intervals = []
    for index in range(1, len(press_times)):
        gap = press_times[index] - press_times[index - 1]
        intervals.append(gap)
    return intervals


def input_features(events: list[dict]) -> dict[str, float] | None:
    """Reduce one session to the four input features, or None if it has no typing."""
    messages = split_into_messages(events)

    all_intervals = []
    characters = 0
    corrections = 0
    mouse_moves = []
    for message in messages:
        all_intervals.extend(key_intervals_ms(message))
        for event in message:
            if event["kind"] == "key" and event["detail"].get("type") == "down":
                key = event["detail"].get("key")
                if key == "char":
                    characters = characters + 1
                if key in ("Backspace", "Delete"):
                    corrections = corrections + 1
            if event["kind"] == "mouse":
                mouse_moves.append(event["detail"].get("moves", 0))

    # Two gaps are the least that gives a spread; fewer means nothing was typed.
    if len(all_intervals) < 2 or characters == 0:
        return None

    mean_interval = statistics.mean(all_intervals)
    features = {
        "median_key_interval_ms": statistics.median(all_intervals),
        "key_interval_variation": statistics.stdev(all_intervals) / mean_interval,
        "correction_rate": corrections / characters,
        "mouse_moves_per_message": statistics.mean(mouse_moves) if mouse_moves else 0.0,
    }
    return features


def print_baseline_table(features_by_session: dict[str, dict[str, float]],
                         thresholds: dict[str, dict]) -> None:
    """Print each feature's spread across the human sessions next to its frozen range."""
    print(f"Input features across {len(features_by_session)} human sessions, and the frozen")
    print("input_stats range for each (a later session is flagged if any feature falls outside):")
    print(f"  {'feature':<26}{'min':>9}{'median':>9}{'max':>9}   frozen range")
    for name in FEATURE_NAMES:
        values = []
        for features in features_by_session.values():
            values.append(features[name])
        allowed = thresholds[name]
        print(f"  {name:<26}{min(values):>9.2f}{statistics.median(values):>9.2f}"
              f"{max(values):>9.2f}   {allowed['low']:.2f} to {allowed['high']:.2f}")
    print("Where:")
    for name in FEATURE_NAMES:
        print(f"  {name}: {FEATURE_DESCRIPTIONS[name]}")


def compute_thresholds(features_by_session: dict[str, dict[str, float]]) -> dict[str, dict]:
    """The allowed range per feature: the human min to max, widened by RANGE_MARGIN."""
    thresholds = {}
    for name in FEATURE_NAMES:
        values = []
        for features in features_by_session.values():
            values.append(features[name])
        low = min(values)
        high = max(values)
        margin = (high - low) * RANGE_MARGIN
        # None of these features can be negative, so the floor stops at zero.
        thresholds[name] = {"low": max(0.0, low - margin), "high": high + margin}
    return thresholds


def agent_runs_exist() -> bool:
    """True once any agent session (level 1 or above) has been recorded."""
    for run in read_records("runs"):
        if run.get("level", 0) > 0:
            return True
    return False


def freeze_thresholds(thresholds: dict[str, dict], session_count: int) -> None:
    """Write the thresholds to assets/humans/, refusing once agent runs exist.

    Changing the thresholds after seeing agent results would tune the detector
    to the test, so the file is locked as soon as the first agent run exists.
    """
    if agent_runs_exist():
        raise RuntimeError(
            "Agent runs already exist in runs.jsonl, so the input_stats thresholds are frozen. "
            f"Delete {THRESHOLDS_FILE} and the agent runs only if you mean to start over."
        )
    record = {
        "human_sessions": session_count,
        "range_margin": RANGE_MARGIN,
        "thresholds": thresholds,
    }
    with THRESHOLDS_FILE.open("w", encoding="utf-8") as file:
        json.dump(record, file, indent=2)
        file.write("\n")


def load_thresholds() -> dict[str, dict] | None:
    """The frozen input_stats ranges, or None if Section 3 hasn't frozen them yet."""
    if not THRESHOLDS_FILE.exists():
        return None
    with THRESHOLDS_FILE.open(encoding="utf-8") as file:
        record = json.load(file)
    return record["thresholds"]
