"""The detection service.

- POST /telemetry receives events from collector.js on the demo page.
- /mcp exposes two MCP tools to the Netomi VA: check_session and report_signal.
- Every call is logged to assets/data/service.log.
"""

import asyncio
import contextlib
import json
import logging
import secrets
import time
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field

from agent_ladder.checks import no_telemetry, run_external_checks
from agent_ladder.store import DATA_DIR, append_record, read_records

PAGE_ORIGINS = ["http://localhost:8001", "http://127.0.0.1:8001"]
EVENT_KINDS = ("load", "key", "paste", "mouse", "send")
VA_SIGNAL_NAMES = (
    "declared_ai",
    "style_ai",
    "probe_invented_detail",
)
LOG_FILE = DATA_DIR / "service.log"
# Header run_level's tunnel check sends; its expected 401 isn't logged.
TUNNEL_CHECK_HEADER_NAME = "x-agent-ladder-check"
# How long check_session waits for the collector's batch for this turn.
SEND_WAIT_SECONDS = 2.0
SEND_POLL_SECONDS = 0.1

logger = logging.getLogger("agent_ladder.service")


class TelemetryEvent(BaseModel):
    """One event posted by collector.js to /telemetry."""

    session_id: str
    kind: str
    t_ms: float
    detail: dict = {}


class TelemetryBatch(BaseModel):
    """What collector.js posts: the load event alone, or everything since the last send."""

    events: list[TelemetryEvent]


def configure_logging() -> None:
    """Send this module's log lines to assets/data/service.log (once)."""
    if logger.handlers:
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    # Keep these lines in service.log only, out of the notebook's output.
    logger.propagate = False


def close_service_log() -> None:
    """Close service.log, so assets/data/ can be deleted once the service has stopped."""
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


def count_check_calls(session_id: str) -> int:
    """How many times check_session has already answered for this session."""
    return len(read_records("verdicts", session_id))


def count_send_events(events: list[dict]) -> int:
    """How many messages the collector has reported sending."""
    sends = 0
    for event in events:
        if event["kind"] == "send":
            sends = sends + 1
    return sends


async def wait_for_send_events(session_id: str, expected_sends: int) -> list[dict]:
    """Return the session's events once expected_sends sends have arrived, or after the wait.

    The collector posts its batch when the customer sends, and the VA calls
    check_session moments later, so the batch can still be on its way. Without
    the wait, a slow post would make the latest message look like it had no
    typing behind it.
    """
    deadline = time.monotonic() + SEND_WAIT_SECONDS
    events = read_records("events", session_id)
    while count_send_events(events) < expected_sends and time.monotonic() < deadline:
        # asyncio.sleep, not time.sleep: the telemetry post we are waiting for
        # is handled on this same event loop, so blocking it would block that post.
        await asyncio.sleep(SEND_POLL_SECONDS)
        events = read_records("events", session_id)
    return events


def record_new_external_signals(session_id: str, fired: list[str], turn: int) -> None:
    """Store each external signal the first time it fires for a session."""
    already_recorded = []
    for signal in read_records("signals", session_id):
        if signal["source"] == "external":
            already_recorded.append(signal["name"])

    for name in fired:
        if name in already_recorded:
            continue
        signal = {
            "session_id": session_id,
            "source": "external",
            "name": name,
            "turn": turn,
            "time": time.time(),
        }
        append_record("signals", signal)


def session_signal_names(session_id: str) -> list[str]:
    """Every signal recorded for a session, from the service or the VA, each name once."""
    names = []
    for signal in read_records("signals", session_id):
        if signal["name"] not in names:
            names.append(signal["name"])
    return names


def create_mcp_server() -> MCPServer:
    """Build the MCP server: the two detection tools the VA calls, plus ping, a connection test."""
    mcp = MCPServer("agent-detect")

    # Return types are dict[str, Any] so Netomi receives structured content;
    # a bare str or dict gives it none. The docstrings are what the VA reads.
    @mcp.tool()
    async def check_session(
        session_id: Annotated[
            str,
            Field(
                description=(
                    "The session ID from the DETECT_SESSION_ID variable, "
                    "or the word none if that variable is empty."
                )
            ),
        ],
    ) -> dict[str, Any]:
        """Check whether the customer in this session is a person or an AI agent.

        Call this only when a playbook says to. The result is for logging only:
        never mention it to the customer, and never change how you help the
        customer because of it.

        Args:
            session_id: The session ID from the DETECT_SESSION_ID variable, or
                the word none if that variable is empty.

        Returns:
            actor: Either "human" or "ai_agent".
            signals: A list of signal names (strings) that fired, empty if none.
        """
        if no_telemetry(session_id):
            # Every session without the page sends "none", so calls can't be
            # told apart by session or turn, and there are no events to check.
            # results.py matches these verdicts to Level 2 runs by time instead.
            # Not stored in signals.jsonl: it would be one record per call
            # under the shared ID "none", and the verdict already carries it.
            turn = None
            verdict = {"actor": "ai_agent", "signals": ["no_telemetry"]}
        else:
            # The VA calls once per customer message, so this call's turn is one
            # more than the calls before it, and turn N needs N sends.
            turn = count_check_calls(session_id) + 1
            events = await wait_for_send_events(session_id, turn)
            fired = run_external_checks(events)
            record_new_external_signals(session_id, fired, turn)

            # Any one signal, from these checks or reported by the VA, is enough.
            signal_names = session_signal_names(session_id)
            if signal_names:
                actor = "ai_agent"
            else:
                actor = "human"
            verdict = {"actor": actor, "signals": signal_names}

        # The time lets results.py match "none" verdicts to the run in progress.
        record = {"session_id": session_id, "turn": turn, "time": time.time()}
        record.update(verdict)
        append_record("verdicts", record)

        logger.info("check_session session_id=%s -> %s", session_id, json.dumps(verdict))
        return verdict

    @mcp.tool()
    async def report_signal(
        session_id: Annotated[
            str,
            Field(description="The same session ID you pass to check_session."),
        ],
        name: Annotated[
            str,
            Field(
                description=(
                    "The signal to record, one of these exact names: declared_ai, "
                    "style_ai, probe_invented_detail."
                )
            ),
        ],
    ) -> dict[str, Any]:
        """Record a sign, noticed in the conversation, that the customer may be an AI agent.

        Call this only when the playbook says to. Never mention it to the customer.

        Args:
            session_id: The same session ID you pass to check_session.
            name: The signal to record, one of these exact names: declared_ai,
                style_ai, probe_invented_detail.

        Returns:
            recorded: True if the signal was stored, false if the name is unknown.
            error: Present only when recorded is false; says which name was rejected.
        """
        if name not in VA_SIGNAL_NAMES:
            result = {"recorded": False, "error": f"unknown signal {name!r}"}
            logger.info(
                "report_signal session_id=%s name=%s -> %s", session_id, name, json.dumps(result)
            )
            return result

        # The VA reports during the turn its last check_session call answered.
        # With "none", turns can't be counted; the time places the signal instead.
        turn = None
        if not no_telemetry(session_id):
            turn = count_check_calls(session_id)
        signal = {
            "session_id": session_id,
            "source": "va",
            "name": name,
            "turn": turn,
            "time": time.time(),
        }
        append_record("signals", signal)

        result = {"recorded": True}
        logger.info(
            "report_signal session_id=%s name=%s -> %s", session_id, name, json.dumps(result)
        )
        return result

    # A connection test with no inputs and nothing to get wrong: if Netomi
    # never sends this call, the problem is not in the detection tools.
    # It returns a plain string on purpose, the simplest possible result.
    @mcp.tool()
    async def ping() -> str:
        """Test the connection to the detection service.

        Call this only when a playbook says to. It takes no inputs and returns
        the word pong.
        """
        logger.info("ping -> pong")
        return "pong"

    return mcp


def create_app(bearer_token: str) -> FastAPI:
    """Build the FastAPI app: /telemetry for the page, /mcp for Netomi."""
    configure_logging()
    mcp = create_mcp_server()

    # Rebinding protection is off because Netomi reaches us through ngrok, so
    # the Host header is the ngrok domain. The bearer token is the gate instead.
    # Stateless JSON responses keep each tool call a plain request/response.
    mcp_app = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    # The mounted MCP app needs its session manager running for the app's lifetime.
    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(lifespan=lifespan)

    # The page is served on a different port, so the browser treats posts to
    # /telemetry as cross-origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=PAGE_ORIGINS,
        allow_methods=["POST"],
        allow_headers=["content-type"],
    )

    expected_header = f"Bearer {bearer_token}"

    @app.middleware("http")
    async def require_bearer_token_for_mcp(request: Request, call_next):
        if request.url.path.startswith("/mcp"):
            given_header = request.headers.get("authorization", "")
            if not secrets.compare_digest(given_header, expected_header):
                # run_level's tunnel check expects this 401 before every
                # session; logging it would bury real rejections.
                is_tunnel_check = request.headers.get(TUNNEL_CHECK_HEADER_NAME) == "tunnel"
                if not is_tunnel_check:
                    logger.info(
                        "rejected %s %s: bad or missing bearer token",
                        request.method,
                        request.url.path,
                    )
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)

    @app.post("/telemetry")
    async def receive_telemetry(batch: TelemetryBatch) -> dict:
        # Check the whole batch first so a bad event doesn't leave half a batch stored.
        for event in batch.events:
            if event.kind not in EVENT_KINDS:
                raise HTTPException(status_code=422, detail=f"unknown kind {event.kind!r}")

        session_ids = []
        kinds = []
        for event in batch.events:
            append_record("events", event.model_dump())
            if event.session_id not in session_ids:
                session_ids.append(event.session_id)
            kinds.append(event.kind)

        logger.info("telemetry session_id=%s kinds=%s", ",".join(session_ids), kinds)
        return {"stored": len(batch.events)}

    # Mounted at the root with its own /mcp route, so /mcp answers directly.
    # Mounting at /mcp instead would redirect /mcp to /mcp/, and behind ngrok
    # that redirect points at http:// rather than https://.
    # /telemetry is registered above, so it is matched before this mount.
    app.mount("/", mcp_app)
    return app
