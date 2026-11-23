"""Record storage: one JSONL file per record type in assets/data/.

Each record is one JSON object on its own line. Every write opens the file,
appends one line and closes it again, so nothing already written is lost if
the notebook kernel restarts partway through a run.

No lock is needed. The detection service's handlers are `async def`, so
uvicorn runs them one at a time on its event loop. The harness, running in the
notebook's main thread, only writes `runs.jsonl`, which the service never
touches.
"""

import json
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "assets" / "data"
HUMANS_DIR = REPO_ROOT / "assets" / "humans"
# What the detector concluded about each human session, kept with the baseline so
# the human row of the results survives assets/data/ being deleted after a demo.
HUMAN_DETECTIONS_DIR = HUMANS_DIR / "detections"
RECORD_TYPES = ("events", "signals", "verdicts", "runs")


def delete_data_folder() -> None:
    """Delete assets/data/ and everything in it, after a demo is over.

    The human baseline lives in assets/humans/, so it is not affected.
    """
    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)


def create_data_folder() -> Path:
    """Create assets/data/ if it doesn't exist yet, and return its path."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def record_file_path(record_type: str) -> Path:
    """Return the JSONL file for a record type, rejecting unknown types."""
    if record_type not in RECORD_TYPES:
        raise ValueError(f"Unknown record type {record_type!r}; expected one of {RECORD_TYPES}")
    return DATA_DIR / f"{record_type}.jsonl"


def append_record(record_type: str, record: dict) -> None:
    """Append one record as a single JSON line."""
    path = record_file_path(record_type)
    line = json.dumps(record)
    with path.open("a", encoding="utf-8") as file:
        file.write(line + "\n")


def read_records(record_type: str, session_id: str | None = None) -> list[dict]:
    """Read every record of a type, optionally only those for one session.

    The whole file is read each time. At a few thousand lines per file this is
    fast enough, and it keeps the code obvious.
    """
    path = record_file_path(record_type)
    if not path.exists():
        return []

    records = []
    with path.open(encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if session_id is not None and record.get("session_id") != session_id:
                continue
            records.append(record)
    return records


def find_human_session_ids() -> list[str]:
    """Return the sessions whose page was opened with ?label=human."""
    session_ids = []
    for event in read_records("events"):
        if event["kind"] != "load":
            continue
        if event["detail"].get("label") != "human":
            continue
        if event["session_id"] not in session_ids:
            session_ids.append(event["session_id"])
    return session_ids


def save_human_detections(session_id: str) -> None:
    """Copy one human session's verdicts and signals into assets/humans/detections/.

    Each line is the original record with a record_type of "verdicts" or "signals".
    """
    HUMAN_DETECTIONS_DIR.mkdir(parents=True, exist_ok=True)
    target = HUMAN_DETECTIONS_DIR / f"{session_id}.jsonl"
    with target.open("w", encoding="utf-8") as file:
        for record_type in ("verdicts", "signals"):
            for record in read_records(record_type, session_id):
                line = dict(record)
                line["record_type"] = record_type
                file.write(json.dumps(line) + "\n")


def load_human_detections(session_id: str) -> tuple[list[dict], list[dict]]:
    """One human session's saved verdicts and signals, as (verdicts, signals)."""
    verdicts = []
    signals = []
    path = HUMAN_DETECTIONS_DIR / f"{session_id}.jsonl"
    if not path.exists():
        return verdicts, signals
    with path.open(encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            record_type = record.pop("record_type")
            if record_type == "verdicts":
                verdicts.append(record)
            else:
                signals.append(record)
    return verdicts, signals


def save_human_sessions() -> list[str]:
    """Copy each new human session from assets/data/ into assets/humans/.

    For each session: its events (the input baseline) and what the detector
    concluded about it (the human row of the results). A session is copied
    only once, and only if the tester sent at least one message; a tester who
    opened the page and left gives nothing to measure. assets/humans/ keeps
    the baseline after assets/data/ is deleted at the end of a demo, so the
    humans are recorded once, not for every demo. Returns the IDs copied.
    """
    HUMANS_DIR.mkdir(parents=True, exist_ok=True)
    copied = []
    for session_id in find_human_session_ids():
        target = HUMANS_DIR / f"{session_id}.jsonl"
        if target.exists():
            continue

        events = read_records("events", session_id)
        sends = []
        for event in events:
            if event["kind"] == "send":
                sends.append(event)
        if not sends:
            continue

        with target.open("w", encoding="utf-8") as file:
            for event in events:
                file.write(json.dumps(event) + "\n")
        save_human_detections(session_id)
        copied.append(session_id)
    return copied
