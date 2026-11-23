"""Talk to the Netomi VA through the Netomi Chat API, with no page and no widget.

Levels 1 and 2 deliver their messages this way. One token covers a whole run
(tokens last 24 hours). Each message is one POST, and reusing the same
conversationId keeps the VA's context across a session. Because the page
never loads, the collector never runs and the VA has no session ID to pass.
"""

import html
import json
import re
import time
import uuid

import httpx

AUTH_TIMEOUT_SECONDS = 60
# The VA calls the detection tools and searches the knowledge source before it
# answers, so one reply can take a while.
MESSAGE_TIMEOUT_SECONDS = 300


def chat_headers(settings: dict) -> dict:
    """The headers every Chat API call needs."""
    headers = {
        "Content-Type": "application/json",
        "x-channel": "CHAT",
        "x-channel-ref-id": settings["channel_ref_id"],
        "x-virtual-agent-id": settings["virtual_agent_id"],
    }
    return headers


def check_response(response: httpx.Response) -> None:
    """Raise an error with Netomi's own message if a call failed.

    Any 2xx is success: the token call returns 200 and a message returns 201.
    The error never includes the request headers, so the token isn't shown.
    """
    if 200 <= response.status_code < 300:
        return
    try:
        message = response.json().get("message", response.text)
    except ValueError:
        message = response.text
    raise RuntimeError(f"Netomi returned HTTP {response.status_code}: {message}")


def get_token(settings: dict) -> str:
    """Get a Chat API token, valid for 24 hours."""
    response = httpx.post(
        settings["auth_url"],
        headers=chat_headers(settings),
        timeout=AUTH_TIMEOUT_SECONDS,
    )
    check_response(response)
    return response.json()["payload"]["token"]


def decode_objects(stream: str) -> list[dict]:
    """Decode the JSON objects in a streamed reply, one after another.

    Netomi streams a reply as JSON objects that may be on separate lines or
    back to back, so json.loads on the whole text would fail.
    """
    decoder = json.JSONDecoder()
    objects = []
    position = 0
    while position < len(stream):
        if stream[position].isspace():
            position = position + 1
            continue
        decoded, position = decoder.raw_decode(stream, position)
        objects.append(decoded)
    return objects


def chunk_index(reply_object: dict) -> int:
    """The position of one streamed object in the reply. Netomi sends it as a string."""
    custom_payload = reply_object.get("customPayload") or {}
    return int(custom_payload.get("CHUNK_INDEX", 0))


def plain_text(value: str) -> str:
    """Strip the HTML from the VA's answer, keeping its line breaks."""
    # Line-break tags and the ends of blocks become line breaks; other tags go.
    with_breaks = re.sub(r"(?i)<br\s*/?>|</(p|div|li)>", "\n", value)
    without_tags = re.sub(r"<[^>]+>", "", with_breaks)
    unescaped = html.unescape(without_tags)

    lines = []
    for line in unescaped.splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def attachment_texts(reply_object: dict) -> list[str]:
    """The text a person would see from one streamed object's attachments.

    Text is the answer, with any quick-reply buttons added as Options.
    FillerText ("just a moment") is skipped. Anything else is shown as its
    type in brackets, so nothing the VA sent is silently lost.
    """
    texts = []
    for attachment in reply_object.get("attachments") or []:
        kind = attachment.get("type", "").rsplit(".", 1)[-1]
        inner = attachment.get("attachment") or {}
        if kind == "FillerText":
            continue
        if kind != "Text":
            texts.append(f"[{kind}]")
            continue

        texts.append(plain_text(inner.get("text", "")))
        quick_reply = inner.get("quickReply") or {}
        labels = []
        for option in quick_reply.get("options") or []:
            labels.append(option.get("label") or option.get("text") or str(option))
        if labels:
            texts.append("Options: " + " | ".join(labels))
    return texts


def parse_reply(stream: str) -> dict:
    """Turn one streamed reply into {"text": ...}, the VA's whole answer for the turn."""
    reply_objects = decode_objects(stream)
    reply_objects.sort(key=chunk_index)

    texts = []
    for reply_object in reply_objects:
        for text in attachment_texts(reply_object):
            if text:
                texts.append(text)
    return {"text": "\n".join(texts)}


def new_conversation_id() -> str:
    """A fresh conversationId for one session; it is also the run's session ID."""
    return str(uuid.uuid4())


def send_message(settings: dict, token: str, conversation_id: str, text: str) -> dict:
    """Send one customer message and return the VA's reply as {"text": ...}."""
    body = {
        "conversationId": conversation_id,
        "ownerType": "BOT",
        "messagePayload": {
            "text": text,
            "label": ".",
            "messageId": str(uuid.uuid4()),
            "timestamp": int(time.time() * 1000),
        },
    }
    headers = chat_headers(settings)
    headers["x-integration"] = settings["integration"]
    headers["x-auth-token"] = token

    response = httpx.post(
        settings["chat_url"],
        headers=headers,
        json=body,
        timeout=MESSAGE_TIMEOUT_SECONDS,
    )
    check_response(response)
    return parse_reply(response.text)
