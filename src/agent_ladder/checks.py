"""The external checks: signals the VA can't see, read from the page's telemetry.

Each check takes one session's events (from events.jsonl, in the order they
arrived) and returns True when it finds a sign of an AI agent.

no_telemetry is the exception: it looks at the session ID, because a session
without one has no events to read.
"""

from agent_ladder.baseline import input_features, load_thresholds, split_into_messages

# What the playbook passes when the DETECT_SESSION_ID variable is empty.
MISSING_SESSION_ID = "none"
# Playwright's default headless Chromium names itself this in the user agent.
HEADLESS_USER_AGENT_MARKER = "HeadlessChrome"
# input_stats judges a session only once it has this many key presses. The
# human ranges come from whole sessions, and a few keys of one short message
# give rhythm and correction numbers too noisy to compare with them.
MIN_KEY_PRESSES_FOR_INPUT_STATS = 30


def no_telemetry(session_id: str) -> bool:
    """True if the VA had no session ID to pass, so the demo page never ran.

    The page's collector creates the session ID and publishes it to the widget
    before the customer's first message, and Netomi has it from turn 1. A
    client that skips the page, such as one posting straight to the Chat API,
    never gets an ID, so the VA passes the word none. That alone is enough:
    no turn of grace is needed, because a real page session never sends none.
    """
    return session_id == MISSING_SESSION_ID


def find_load_event(events: list[dict]) -> dict | None:
    """Return the session's page-load event, or None if it never arrived."""
    for event in events:
        if event["kind"] == "load":
            return event
    return None


def automation_flags(events: list[dict]) -> bool:
    """Look for a browser that says it is automated.

    Browsers driven by automation tools set navigator.webdriver to true, and
    Playwright's default headless Chromium puts HeadlessChrome in its user
    agent. A person's everyday browser does neither. Stealth launches hide
    both, which is why this check stops working at Level 4.
    """
    load_event = find_load_event(events)
    if load_event is None:
        return False

    environment = load_event["detail"]
    if environment.get("webdriver") is True:
        return True

    user_agent = environment.get("user_agent") or ""
    if HEADLESS_USER_AGENT_MARKER in user_agent:
        return True
    return False


def message_was_injected(message_events: list[dict]) -> bool:
    """True if one message was sent with fewer key presses than characters, and no paste."""
    send_event = message_events[-1]
    message_length = send_event["detail"].get("length", 0)

    key_presses = 0
    pasted = False
    for event in message_events:
        if event["kind"] == "key" and event["detail"].get("type") == "down":
            key_presses = key_presses + 1
        if event["kind"] == "paste":
            pasted = True

    if pasted:
        return False
    return key_presses < message_length


def injected_text(events: list[dict]) -> bool:
    """Look for a message that appeared in the box without being typed or pasted.

    A person types each character (one key press each, more with corrections)
    or pastes the text. Tools like Playwright's fill() set the box's value
    directly, so the message arrives with almost no key presses. Every key
    press counts, Shift and arrows included, so a person is never short of
    presses for what they typed.
    """
    messages = split_into_messages(events)
    for message_events in messages:
        if message_was_injected(message_events):
            return True
    return False


def count_key_presses(events: list[dict]) -> int:
    """Key presses (key down events) across a whole session."""
    presses = 0
    for event in events:
        if event["kind"] == "key" and event["detail"].get("type") == "down":
            presses = presses + 1
    return presses


def features_outside_ranges(features: dict[str, float], thresholds: dict) -> list[str]:
    """The names of the features that fall outside their human range."""
    outside = []
    for name, allowed in thresholds.items():
        value = features[name]
        if value < allowed["low"] or value > allowed["high"]:
            outside.append(name)
    return outside


def input_stats(events: list[dict]) -> bool:
    """Look for typing that doesn't match how the recorded people typed.

    Each session is reduced to four numbers: the typical gap between key
    presses, how uneven that rhythm is, corrections per character, and mouse
    movement before each send. A script that types key by key still tends to
    give itself away in one of them: a rhythm too even or too fast, no
    corrections, or almost no mouse movement. The allowed ranges are the human
    sessions' min to max, widened a little, and were frozen before any agent
    ran. Until they exist (while the humans are still being recorded), and
    until the session has enough typing to measure, this never fires.
    """
    thresholds = load_thresholds()
    if thresholds is None:
        return False
    if count_key_presses(events) < MIN_KEY_PRESSES_FOR_INPUT_STATS:
        return False
    features = input_features(events)
    if features is None:
        return False
    return len(features_outside_ranges(features, thresholds)) > 0


# The checks check_session runs, by the signal name each one reports.
EXTERNAL_CHECKS = {
    "automation_flags": automation_flags,
    "injected_text": injected_text,
    "input_stats": input_stats,
}


def run_external_checks(events: list[dict]) -> list[str]:
    """Run every external check on one session's events; return the names that fired."""
    fired = []
    for name, check in EXTERNAL_CHECKS.items():
        if check(events):
            fired.append(name)
    return fired
