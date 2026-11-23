"""Run a level's agent sessions against the VA and record each one's true label.

A session is one conversation: the harness sends the level's opening line,
then the customer model and the VA take turns until the customer ends with
[END] or the level's max_turns is reached. Levels 1 and 2 talk through the
Netomi Chat API; Levels 3-6 drive the real widget on the demo page.

Each finished session gets one record in runs.jsonl. Its level is the true
label that results.py compares with the detector's verdicts. started_at and
ended_at let results.py match verdicts that carry session ID "none" (Levels 1
and 2, which never load the page) to the session that was running at the time.

The session functions are async only because browser.py is; sessions run one
at a time. run_level is the blocking entry point the notebook calls.
"""

import asyncio
import concurrent.futures
import time

import httpx
import yaml

from agent_ladder import browser, chat_api
from agent_ladder.baseline import THRESHOLDS_FILE
from agent_ladder.checks import MISSING_SESSION_ID
from agent_ladder.customer import next_customer_message, split_end_marker
from agent_ladder.settings import load_chat_api_settings, load_settings
from agent_ladder.store import REPO_ROOT, append_record, read_records

LEVELS_DIR = REPO_ROOT / "assets" / "levels"
LEVEL_KEYS = (
    "level",
    "name",
    "delivery",
    "input",
    "stealth",
    "runs",
    "max_turns",
    "opening",
    "persona",
)
TUNNEL_CHECK_TIMEOUT_SECONDS = 15
# Sent with the tunnel check so the service doesn't log it as a rejected call.
TUNNEL_CHECK_HEADER = {"X-Agent-Ladder-Check": "tunnel"}
# What the detection service answers at /mcp to a request without the bearer
# token. Anything else means the request never reached the service.
TUNNEL_UP_STATUS = 401
# A session the detector never saw is replaced by a new one. Two in a row
# means something is down (the tools, or Netomi's MCP connection), not a
# one-off glitch, so the level stops; so does a run with too many replacements.
MAX_UNSEEN_IN_A_ROW = 2
MAX_REPLACED_PER_LEVEL = 5
# Width of the progress bar run_level draws, in characters.
PROGRESS_BAR_WIDTH = 30
ENDED_BY_DESCRIPTIONS = {
    "end_marker": "the customer said goodbye",
    "max_turns": "cut off at the turn limit",
    "no_reply": "the VA stopped replying",
}
# After the last reply, the VA may still be finishing a report_signal call.
# Waiting before ended_at keeps that record inside this session's time window,
# and the gap keeps the next session's window from touching this one.
SESSION_SETTLE_SECONDS = 5


def load_level(level_name: str) -> dict:
    """Read a level file from assets/levels/, such as "2-direct-api", and check its keys."""
    path = LEVELS_DIR / f"{level_name}.yaml"
    with path.open(encoding="utf-8") as file:
        level = yaml.safe_load(file)

    missing = []
    for key in LEVEL_KEYS:
        if key not in level:
            missing.append(key)
    if missing:
        raise ValueError(f"{path} is missing {', '.join(missing)}")
    if level["delivery"] not in ("api", "browser"):
        raise ValueError(f"{path}: delivery must be api or browser, not {level['delivery']!r}")
    return level


def check_thresholds_frozen() -> None:
    """Refuse to run agents before the human baseline is frozen.

    baseline.py locks the input_stats thresholds once any agent run exists, so
    an agent run first would leave the baseline impossible to set.
    """
    if not THRESHOLDS_FILE.exists():
        raise RuntimeError(
            f"No input_stats thresholds at {THRESHOLDS_FILE}. Record the human sessions "
            "and run Section 3 first: the first agent run freezes the thresholds."
        )


def check_tunnel() -> None:
    """Stop if Netomi can't reach the detection service through the ngrok tunnel.

    If the tunnel is down, the VA's tool calls fail, the playbook carries on
    silently, and every session ends with no verdict: the level would look
    undetected when the detector never saw it. The service rejects a request
    without the bearer token with 401, so a 401 at the public /mcp URL proves
    the tunnel reaches it. Interrupting a notebook cell can kill ngrok, which
    is how this happened once.
    """
    url = f"https://{load_settings()['ngrok_domain']}/mcp"
    try:
        response = httpx.post(
            url, headers=TUNNEL_CHECK_HEADER, timeout=TUNNEL_CHECK_TIMEOUT_SECONDS
        )
        status = response.status_code
    except httpx.HTTPError as error:
        status = f"no response ({error})"
    if status != TUNNEL_UP_STATUS:
        raise RuntimeError(
            f"The detection service isn't reachable through the tunnel: {url} answered "
            f"{status}, not {TUNNEL_UP_STATUS}. The VA's tool calls would fail silently. "
            "Restart the kernel and run Section 1 (and Section 3), then run this level again."
        )


async def open_conversation(level: dict, api_access: dict | None) -> dict:
    """Start a session the way the level delivers its messages.

    Returns a dict with the session ID: for the Chat API, the conversationId
    plus the settings and token; for the widget, browser.py's session.
    """
    if level["delivery"] == "api":
        conversation = {
            "session_id": chat_api.new_conversation_id(),
            "settings": api_access["settings"],
            "token": api_access["token"],
        }
        return conversation
    return await browser.open_widget(level["stealth"])


async def send_and_read(level: dict, conversation: dict, text: str) -> str:
    """Send one customer message and return the VA's reply text."""
    if level["delivery"] == "api":
        # The Chat API returns the VA's reply as the response to the send.
        reply = chat_api.send_message(
            conversation["settings"], conversation["token"], conversation["session_id"], text
        )
        return reply["text"]
    await browser.send(conversation, text, level["input"])
    reply = await browser.read_reply(conversation)
    return reply["text"]


async def close_conversation(level: dict, conversation: dict) -> None:
    """Close the browser for a widget session; a Chat API conversation needs nothing."""
    if level["delivery"] == "browser":
        await browser.close_widget(conversation)


def count_customer_turns(transcript: list[dict]) -> int:
    """How many messages the customer sent in a transcript."""
    customer_turns = 0
    for entry in transcript:
        if entry["speaker"] == "customer":
            customer_turns = customer_turns + 1
    return customer_turns


async def run_session(level: dict, run_index: int, api_access: dict | None = None) -> dict:
    """Run one conversation and return its record (run_level decides whether to keep it).

    The record's transcript lists each message as {"speaker", "text"}. ended_by
    says why the session stopped: the customer's [END], max_turns, or a VA
    reply that never came.
    """
    started_at = time.time()
    conversation = await open_conversation(level, api_access)
    transcript = []
    ended_by = "max_turns"
    message = level["opening"]
    customer_done = False
    try:
        for _turn in range(level["max_turns"]):
            reply = await send_and_read(level, conversation, message)
            transcript.append({"speaker": "customer", "text": message})
            transcript.append({"speaker": "va", "text": reply})
            if customer_done:
                ended_by = "end_marker"
                break
            if not reply:
                ended_by = "no_reply"
                break
            raw_message = next_customer_message(level["persona"], transcript)
            message, customer_done = split_end_marker(raw_message)
    finally:
        await close_conversation(level, conversation)

    await asyncio.sleep(SESSION_SETTLE_SECONDS)
    record = {
        "session_id": conversation["session_id"],
        "level": level["level"],
        "run_index": run_index,
        "turns": count_customer_turns(transcript),
        "ended_by": ended_by,
        "started_at": started_at,
        "ended_at": time.time(),
        "transcript": transcript,
    }
    return record


def detector_saw_session(level: dict, record: dict) -> bool:
    """True if at least one check_session verdict was recorded for this session.

    A widget session's verdicts carry its session ID. A Chat API session has
    none, so its verdicts are the "none" ones inside its time window.
    """
    if level["delivery"] == "browser":
        return len(read_records("verdicts", record["session_id"])) > 0
    for verdict in read_records("verdicts", MISSING_SESSION_ID):
        time_of_verdict = verdict.get("time")
        if time_of_verdict is None:
            continue
        if record["started_at"] <= time_of_verdict <= record["ended_at"]:
            return True
    return False


def progress_line(level: dict, done: int, total: int) -> str:
    """One line with a text progress bar for a level's sessions."""
    filled = round(PROGRESS_BAR_WIDTH * done / total)
    progress = "#" * filled + "-" * (PROGRESS_BAR_WIDTH - filled)
    return f"Level {level['level']} ({level['name']}): [{progress}] {done}/{total} sessions"


def describe_endings(ended_by_counts: dict, replaced: int) -> str:
    """How the recorded sessions ended, and how many were replaced, as readable lines."""
    parts = []
    for ended_by, count in ended_by_counts.items():
        parts.append(f"{count} {ENDED_BY_DESCRIPTIONS.get(ended_by, ended_by)}")
    text = "Sessions ended: " + ", ".join(parts) + "."
    if replaced:
        text = text + (
            f"\nReplaced: {replaced} session(s) in which the VA made no check_session call, so "
            "the detector never saw them. They aren't counted; they show how reliably the VA "
            "calls its tools."
        )
    return text


def unseen_session_error(level: dict, recorded: int, unseen_in_a_row: int, replaced: int) -> str:
    """The message run_level stops with when sessions keep reaching it unseen."""
    if unseen_in_a_row >= MAX_UNSEEN_IN_A_ROW:
        reason = f"{unseen_in_a_row} sessions in a row ran with no check_session call"
    else:
        reason = f"{replaced} sessions in this run had no check_session call"
    return (
        f"Level {level['level']} stopped: {reason} reaching the detection service. The tunnel "
        "is up, so Netomi isn't calling the tools: refresh the MCP server's tool list in "
        "Netomi, check the tools are active in Staging, wait a minute, then run this level "
        f"again ({recorded} sessions of this run were recorded)."
    )


async def run_level_async(level_name: str, runs: int | None = None) -> list[str]:
    """Run a level's sessions one after another; return their session IDs.

    runs defaults to the level file's count. A session is recorded only if the
    detector saw it (at least one check_session verdict); one it didn't see is
    replaced by a new session, and the level stops after MAX_UNSEEN_IN_A_ROW
    such sessions in a row or MAX_REPLACED_PER_LEVEL in all. A progress bar is
    redrawn in place after each recorded session (the carriage return makes
    the notebook overwrite the line), then the endings and replacements print.
    """
    check_thresholds_frozen()
    check_tunnel()
    level = load_level(level_name)
    if runs is None:
        runs = level["runs"]

    # One Chat API token lasts 24 hours, so a whole level shares it.
    api_access = None
    if level["delivery"] == "api":
        settings = load_chat_api_settings()
        api_access = {"settings": settings, "token": chat_api.get_token(settings)}

    session_ids = []
    ended_by_counts = {}
    replaced = 0
    unseen_in_a_row = 0
    print(progress_line(level, 0, runs), end="", flush=True)
    while len(session_ids) < runs:
        # Checked before every session, so a tunnel that dies mid-level stops
        # the run instead of recording sessions the detector never saw.
        if session_ids or replaced:
            check_tunnel()
        record = await run_session(level, len(session_ids), api_access)

        # A session the detector never saw measures the VA's tool calls, not
        # the detector, so it isn't recorded; a new session takes its place.
        if not detector_saw_session(level, record):
            replaced = replaced + 1
            unseen_in_a_row = unseen_in_a_row + 1
            if unseen_in_a_row >= MAX_UNSEEN_IN_A_ROW or replaced > MAX_REPLACED_PER_LEVEL:
                print()
                raise RuntimeError(
                    unseen_session_error(level, len(session_ids), unseen_in_a_row, replaced)
                )
            continue

        unseen_in_a_row = 0
        append_record("runs", record)
        session_ids.append(record["session_id"])
        ended_by_counts[record["ended_by"]] = ended_by_counts.get(record["ended_by"], 0) + 1
        print("\r" + progress_line(level, len(session_ids), runs), end="", flush=True)
    print()
    print(describe_endings(ended_by_counts, replaced))
    return session_ids


def run_level(level_name: str, runs: int | None = None) -> list[str]:
    """Run a level and wait for it to finish; return the session IDs.

    The notebook already runs an event loop, so asyncio.run can't start
    another one in the notebook's thread, and a top-level await in a cell
    isn't valid Python for the linter. The level runs on one worker thread
    with its own loop, and this call blocks until it's done, so nothing runs
    alongside it. Errors from the run are raised here.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(asyncio.run, run_level_async(level_name, runs))
        return future.result()


def load_run(session_id: str) -> dict:
    """The runs.jsonl record for one session."""
    for record in read_records("runs"):
        if record["session_id"] == session_id:
            return record
    raise ValueError(f"No run recorded for session {session_id}")


def print_transcript(record: dict) -> None:
    """Print one session's conversation, labelled, so a reader can follow what was said."""
    print(f"Transcript of Level {record['level']} run {record['run_index'] + 1} "
          f"(session {record['session_id']}), {record['turns']} customer turns:")
    for entry in record["transcript"]:
        if entry["speaker"] == "customer":
            label = "Customer"
        else:
            label = "VA"
        print(f"{label}: {entry['text']}")
