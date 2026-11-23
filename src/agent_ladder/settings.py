"""Settings read from .env at the repo root."""

import os
import secrets

from dotenv import load_dotenv

from agent_ladder.store import REPO_ROOT

ENV_FILE = REPO_ROOT / ".env"
REQUIRED_KEYS = ("NGROK_DOMAIN", "NETOMI_CHANNEL_REF_ID")


def load_settings() -> dict:
    """Load the ngrok domain, the MCP bearer token and the VA's channel reference ID from .env.

    The ngrok domain and the bearer token are fixed in .env so the MCP config
    pasted into Netomi stays the same from one run to the next.
    """
    load_dotenv(ENV_FILE)

    missing = []
    for key in REQUIRED_KEYS:
        if not os.environ.get(key):
            missing.append(key)
    if missing:
        raise RuntimeError(f"Missing {', '.join(missing)} in {ENV_FILE} (see .env.sample)")

    bearer_token = os.environ.get("MCP_BEARER_TOKEN")
    if not bearer_token:
        # Without a fixed token, Netomi's MCP config would break on every run.
        bearer_token = secrets.token_urlsafe(32)
        print("No MCP_BEARER_TOKEN was found in .env, so a token was generated for this run only.")
        print("Add this line to .env so the MCP config you paste into Netomi")
        print("keeps working on later runs:")
        print(f"MCP_BEARER_TOKEN={bearer_token}")
        print()

    settings = {
        "ngrok_domain": os.environ["NGROK_DOMAIN"],
        "bearer_token": bearer_token,
        # The channel reference ID is also the widget's botRefId.
        "netomi_channel_ref_id": os.environ["NETOMI_CHANNEL_REF_ID"],
    }
    return settings


CHAT_API_KEYS = (
    "NETOMI_AUTH_URL",
    "NETOMI_CHAT_URL",
    "NETOMI_CHANNEL_REF_ID",
    "NETOMI_VIRTUAL_AGENT_ID",
)
DEFAULT_INTEGRATION = "NETOMI_WEB_WIDGET"


def load_chat_api_settings() -> dict:
    """Load what the Netomi Chat API needs from .env (used by Levels 1 and 2 only).

    Kept apart from load_settings so the service and page can start without
    the Chat API keys.
    """
    load_dotenv(ENV_FILE)

    missing = []
    for key in CHAT_API_KEYS:
        if not os.environ.get(key):
            missing.append(key)
    if missing:
        raise RuntimeError(f"Missing {', '.join(missing)} in {ENV_FILE} (see .env.sample)")

    integration = os.environ.get("NETOMI_INTEGRATION", "").strip()
    if not integration:
        integration = DEFAULT_INTEGRATION

    settings = {
        "auth_url": os.environ["NETOMI_AUTH_URL"],
        "chat_url": os.environ["NETOMI_CHAT_URL"],
        "integration": integration,
        "channel_ref_id": os.environ["NETOMI_CHANNEL_REF_ID"],
        "virtual_agent_id": os.environ["NETOMI_VIRTUAL_AGENT_ID"],
    }
    return settings
