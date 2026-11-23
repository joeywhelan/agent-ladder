"""The results: each session's true label next to what the detector concluded.

Agent sessions come from runs.jsonl, where the level is the true label.
Human sessions are the recorded baseline in assets/humans/, with the verdicts
and signals Section 3 saved for them in assets/humans/detections/. For each session,
the detector's conclusion is every signal recorded for it, by the service's
external checks or by the VA. Any signal means the verdict is ai_agent, the same
rule check_session uses, so this is the verdict the session ended with. Signals
are taken from signals.jsonl as well as from the verdicts, because the VA can
report one (style_ai, say) after its last check_session call.

input_stats is the exception: it is judged here, once, on each session's
whole telemetry against the frozen thresholds, for agents and humans alike,
and the live signal is ignored. Live, check_session runs it after every
message once 30 key presses exist, so one short message's timing is compared
with ranges built from whole sessions; replayed that way it flagged 5 of the
10 human sessions on their first message. The humans were recorded before the
thresholds existed, so the live check never ran on them, and trusting the
live signal would judge agents by a rule the humans never faced.

Sessions with a session ID are matched by ID. Sessions without one pass the
word "none" (Levels 1 and 2, which never load the page), so their records are
matched by time instead: a "none" record belongs to the run whose started_at to
ended_at window contains its time. Only Chat API runs (NONE_MATCHED_LEVELS)
are matched this way: a widget session has a real session ID, so a "none" call
during it came from the agent calling the tool outside the playbook, and
crediting it as no_telemetry would give the session a catch it didn't earn.
Runs are sequential, so windows never overlap. A "none" record outside every
Chat API run's window is counted and reported.
"""

from agent_ladder.baseline import load_human_sessions
from agent_ladder.checks import MISSING_SESSION_ID, input_stats
from agent_ladder.service import VA_SIGNAL_NAMES
from agent_ladder.store import HUMANS_DIR, load_human_detections, read_records

# The pass rule, fixed before any agent run. The human limit is 10% for a
# ten-session baseline: one false alarm in ten is allowed, two are not.
LEVEL_PASS_RATE = 0.90
HUMAN_MAX_FLAG_RATE = 0.10
LEVELS = (1, 2, 3, 4, 5, 6)
# Judged on the whole session here, not taken from the live verdicts.
WHOLE_SESSION_SIGNAL = "input_stats"
# The levels that talk through the Chat API, with no page and so no session ID.
NONE_MATCHED_LEVELS = (1, 2)
LEVEL_NAMES = {
    0: "Humans",
    1: "1 Declared",
    2: "2 Direct API",
    3: "3 Naive browser",
    4: "4 Masked",
    5: "5 Human-like input",
    6: "6 Human-like language",
}


def human_session_ids() -> list[str]:
    """The recorded human sessions saved in assets/humans/, one file each."""
    session_ids = []
    if not HUMANS_DIR.exists():
        return session_ids
    for path in sorted(HUMANS_DIR.glob("*.jsonl")):
        session_ids.append(path.stem)
    return session_ids


def records_in_window(records: list[dict], run: dict) -> list[dict]:
    """The "none" records whose time falls inside one run's window."""
    matched = []
    for record in records:
        time = record.get("time")
        if time is None:
            continue
        if run["started_at"] <= time <= run["ended_at"]:
            matched.append(record)
    return matched


def signal_names(verdicts: list[dict], signals: list[dict], events: list[dict]) -> list[str]:
    """Every signal for a session, each once, with input_stats judged on the whole session.

    The live input_stats signal is skipped, and input_stats is run once on the
    session's full telemetry instead (see the module docstring).
    """
    names = []
    for verdict in verdicts:
        for name in verdict["signals"]:
            if name == WHOLE_SESSION_SIGNAL:
                continue
            if name not in names:
                names.append(name)
    for signal in signals:
        if signal["name"] == WHOLE_SESSION_SIGNAL:
            continue
        if signal["name"] not in names:
            names.append(signal["name"])
    if input_stats(events):
        names.append(WHOLE_SESSION_SIGNAL)
    return names


def score_session(
    session_id: str, level: int, verdicts: list[dict], signals: list[dict], events: list[dict]
) -> dict:
    """One session's result: how many verdicts it got, its signals, and whether it was flagged."""
    names = signal_names(verdicts, signals, events)
    result = {
        "session_id": session_id,
        "level": level,
        "verdicts": len(verdicts),
        "signals": names,
        "flagged": len(names) > 0,
    }
    return result


def score_all_sessions() -> tuple[list[dict], int]:
    """Score every agent run and human session; also count unmatched "none" records."""
    none_verdicts = read_records("verdicts", MISSING_SESSION_ID)
    none_signals = read_records("signals", MISSING_SESSION_ID)
    matched_none_records = 0

    results = []
    for run in read_records("runs"):
        if run["level"] == 0:
            continue
        verdicts = read_records("verdicts", run["session_id"])
        signals = read_records("signals", run["session_id"])
        window_verdicts = []
        window_signals = []
        if run["level"] in NONE_MATCHED_LEVELS:
            window_verdicts = records_in_window(none_verdicts, run)
            window_signals = records_in_window(none_signals, run)
        matched_none_records = matched_none_records + len(window_verdicts) + len(window_signals)
        result = score_session(
            run["session_id"],
            run["level"],
            verdicts + window_verdicts,
            signals + window_signals,
            read_records("events", run["session_id"]),
        )
        results.append(result)

    # Saved by Section 3, so the human row doesn't depend on assets/data/.
    human_events = load_human_sessions()
    for session_id in human_session_ids():
        verdicts, signals = load_human_detections(session_id)
        events = human_events.get(session_id, [])
        results.append(score_session(session_id, 0, verdicts, signals, events))

    unmatched_none_records = len(none_verdicts) + len(none_signals) - matched_none_records
    return results, unmatched_none_records


def sessions_at_level(level: int, results: list[dict]) -> list[dict]:
    """The scored sessions for one row of the grid."""
    sessions = []
    for result in results:
        if result["level"] == level:
            sessions.append(result)
    return sessions


def caught_by(session: dict) -> tuple[bool, bool]:
    """Whether the external service and the VA each caught a session: (external, va)."""
    by_external = False
    by_va = False
    for name in session["signals"]:
        if name in VA_SIGNAL_NAMES:
            by_va = True
        else:
            by_external = True
    return by_external, by_va


def passes_rule(level: int, flagged: int, total: int) -> bool | None:
    """Apply the fixed pass rule; None when the row has no sessions yet.

    Agents pass by being caught; humans pass by not being flagged.
    """
    if total == 0:
        return None
    rate = flagged / total
    if level == 0:
        return rate <= HUMAN_MAX_FLAG_RATE
    return rate >= LEVEL_PASS_RATE


def summarize_row(level: int, results: list[dict]) -> dict:
    """Totals for one row of the grid: a level, or the humans (level 0)."""
    row = {
        "level": level,
        "sessions": 0,
        "flagged": 0,
        "without_verdict": 0,
        "by_external": 0,
        "by_va": 0,
        "signal_counts": {},
    }
    for session in sessions_at_level(level, results):
        row["sessions"] = row["sessions"] + 1
        if session["verdicts"] == 0:
            row["without_verdict"] = row["without_verdict"] + 1
        if not session["flagged"]:
            continue
        row["flagged"] = row["flagged"] + 1
        for name in session["signals"]:
            row["signal_counts"][name] = row["signal_counts"].get(name, 0) + 1
        by_external, by_va = caught_by(session)
        if by_external:
            row["by_external"] = row["by_external"] + 1
        if by_va:
            row["by_va"] = row["by_va"] + 1

    if row["sessions"] == 0:
        row["rate"] = 0.0
    else:
        row["rate"] = row["flagged"] / row["sessions"]
    row["passed"] = passes_rule(level, row["flagged"], row["sessions"])
    return row


def describe_signals(signal_counts: dict) -> str:
    """Signal names with how many sessions each caught, most first."""
    if not signal_counts:
        return "-"
    names = sorted(signal_counts, key=signal_counts.get, reverse=True)
    parts = []
    for name in names:
        parts.append(f"{name} ({signal_counts[name]})")
    return ", ".join(parts)


def markdown_signals(signal_counts: dict) -> str:
    """Signal names in code format with their counts, most first, for the Markdown table."""
    if not signal_counts:
        return "none"
    names = sorted(signal_counts, key=signal_counts.get, reverse=True)
    parts = []
    for name in names:
        parts.append(f"`{name}` ({signal_counts[name]})")
    return ", ".join(parts)


def pass_label(passed: bool | None) -> str:
    """PASS, FAIL, or a dash for a row with no sessions yet."""
    if passed is None:
        return "-"
    if passed:
        return "PASS"
    return "FAIL"


def print_grid(rows: list[dict]) -> None:
    """Print the grid as a Markdown table, ready to paste into the article.

    One row per level plus the human row, with an explanation above it.
    """
    print("Results grid, as a Markdown table. For agent levels, 'Caught' means the")
    print(f"detector flagged the session; a level passes if at least {LEVEL_PASS_RATE:.0%} "
          "are caught.")
    print("For humans it counts false alarms; the row passes if no more than "
          f"{HUMAN_MAX_FLAG_RATE:.0%} are flagged.")
    print("'External' and 'VA' count caught sessions by the external service and by the")
    print("VA (a session can count for both). 'Signals' lists what fired, with how many")
    print("sessions each one caught.")
    print()
    print("| Level | Caught | Result | External | VA | Signals |")
    print("|---|---|---|---|---|---|")
    for row in rows:
        name = LEVEL_NAMES[row["level"]]
        caught = f"{row['flagged']}/{row['sessions']}"
        signals = markdown_signals(row["signal_counts"])
        print(f"| {name} | {caught} | {pass_label(row['passed'])} | "
              f"{row['by_external']} | {row['by_va']} | {signals} |")
    print()


def first_failing_level(rows: list[dict]) -> dict | None:
    """The lowest agent level that ran and failed, or None."""
    for row in rows:
        if row["level"] == 0:
            continue
        if row["passed"] is False:
            return row
    return None


def signals_that_weakened(rows: list[dict], failing_row: dict) -> list[str]:
    """Signals that caught fewer sessions on the failing level than on the level below.

    Each is described with both counts, such as "input_stats: 10 at Level 5,
    5 here", including signals that stopped completely ("0 here").
    """
    previous_row = None
    for row in rows:
        if row["level"] == failing_row["level"] - 1:
            previous_row = row
    if previous_row is None:
        return []
    drops = []
    for name, previous_count in previous_row["signal_counts"].items():
        count_here = failing_row["signal_counts"].get(name, 0)
        if count_here < previous_count:
            drops.append((previous_count - count_here, name, previous_count, count_here))
    # The biggest drop first: it's the signal the detector was relying on.
    drops.sort(reverse=True)
    weakened = []
    for _drop, name, previous_count, count_here in drops:
        weakened.append(
            f"{name}: {previous_count} at Level {previous_row['level']}, {count_here} here"
        )
    return weakened


def carried_by(row: dict) -> str:
    """Which detector caught most of a level's flagged sessions."""
    if row["flagged"] == 0:
        return "neither"
    if row["by_external"] > 0 and row["by_va"] > 0:
        return f"both (external {row['by_external']}, VA {row['by_va']})"
    if row["by_external"] > 0:
        return "the external service"
    return "the VA"


def print_totals(agent_rows: list[dict], human_row: dict) -> None:
    """Print the caught and wrongly flagged counts, and which levels passed."""
    agent_flagged = 0
    agent_total = 0
    passed_levels = []
    failed_levels = []
    not_run_levels = []
    for row in agent_rows:
        agent_flagged = agent_flagged + row["flagged"]
        agent_total = agent_total + row["sessions"]
        if row["passed"] is None:
            not_run_levels.append(str(row["level"]))
        elif row["passed"]:
            passed_levels.append(str(row["level"]))
        else:
            failed_levels.append(str(row["level"]))

    print(f"- Agent sessions caught: {agent_flagged} of {agent_total}.")
    print(f"- Human sessions wrongly flagged: {human_row['flagged']} of {human_row['sessions']}.")
    print(f"- Levels passed: {', '.join(passed_levels) or 'none'}. "
          f"Levels failed: {', '.join(failed_levels) or 'none'}.")
    if not_run_levels:
        print(f"- Levels with no sessions yet: {', '.join(not_run_levels)}.")


def print_first_failure(rows: list[dict]) -> None:
    """Print the first level that failed and the signals that weakened there."""
    failing_row = first_failing_level(rows)
    if failing_row is None:
        print("- No level failed.")
        return
    weakened = signals_that_weakened(rows, failing_row)
    print(f"- First level to fail: {LEVEL_NAMES[failing_row['level']]}.")
    if weakened:
        print(f"  Signals that caught fewer sessions here than on Level "
              f"{failing_row['level'] - 1}: {'; '.join(weakened)}.")
    else:
        print(f"  No signal caught fewer sessions here than on Level "
              f"{failing_row['level'] - 1}.")


def print_carriers(agent_rows: list[dict]) -> None:
    """Print which detector caught each level's flagged sessions."""
    print("- Which detector caught each level's flagged sessions:")
    for row in agent_rows:
        if row["sessions"] == 0:
            continue
        print(f"    {LEVEL_NAMES[row['level']]}: {carried_by(row)}")


def print_warnings(rows: list[dict], unmatched_none_records: int) -> None:
    """Warn about sessions the detector never saw and "none" records no run claimed."""
    without_verdict = 0
    for row in rows:
        without_verdict = without_verdict + row["without_verdict"]
    if without_verdict:
        print(f"- Warning: sessions with no check_session verdict at all: {without_verdict}. "
              "The VA never reached the detection service for them, so they count as "
              "not flagged.")
    if unmatched_none_records:
        print(f"- Warning: records with session ID 'none' outside every Chat API run's "
              f"time window: {unmatched_none_records}. They were not counted for any session; "
              "during widget runs they come from the agent calling check_session outside "
              "the playbook.")


def print_summary(rows: list[dict], unmatched_none_records: int) -> None:
    """Print the overall summary below the grid, each line saying what it is."""
    agent_rows = []
    human_row = None
    for row in rows:
        if row["level"] == 0:
            human_row = row
        else:
            agent_rows.append(row)

    print("Summary")
    print_totals(agent_rows, human_row)
    print_first_failure(rows)
    print_carriers(agent_rows)
    print_warnings(rows, unmatched_none_records)


def print_results() -> None:
    """Score every session, then print the grid and the summary."""
    results, unmatched_none_records = score_all_sessions()
    rows = []
    for level in LEVELS:
        rows.append(summarize_row(level, results))
    rows.append(summarize_row(0, results))
    print_grid(rows)
    print_summary(rows, unmatched_none_records)


def print_level_result(level: int, show_va_catches: bool = False) -> None:
    """Print one level's detected count and signals, as its notebook section reports them.

    show_va_catches adds one line per session listing what the VA caught
    (its style check and probes), for Level 6, where the conversation is what
    gives the agent away.
    """
    results, _unmatched = score_all_sessions()
    row = summarize_row(level, results)
    print(f"Level {LEVEL_NAMES[level]}: the detector caught {row['flagged']} of {row['sessions']} "
          f"sessions ({row['rate']:.0%}). The level passes at {LEVEL_PASS_RATE:.0%}: "
          f"{pass_label(row['passed'])}.")
    print(f"Signals that fired, with how many sessions each caught: "
          f"{describe_signals(row['signal_counts'])}")
    if row["without_verdict"]:
        print(f"Sessions with no check_session verdict at all: {row['without_verdict']}. "
              "The VA never reached the detection service for them, so they count as not caught.")

    if not show_va_catches:
        return
    print()
    print("What the VA caught in each session (style check and probes); '-' means nothing:")
    run_number = 0
    for result in results:
        if result["level"] != level:
            continue
        run_number = run_number + 1
        va_names = []
        for name in result["signals"]:
            if name in VA_SIGNAL_NAMES:
                va_names.append(name)
        caught = ", ".join(va_names) or "-"
        print(f"  run {run_number}: {caught}")
