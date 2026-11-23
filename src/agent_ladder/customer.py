"""The simulated customer: a local model on Ollama plays the persona.

The harness sends each level's fixed opening line itself; from then on,
next_customer_message writes every customer turn from the level's persona and
the conversation so far.
"""

import ollama

CUSTOMER_MODEL = "qwen3.5:4b"
# The persona puts this at the end of its goodbye message.
END_MARKER = "[END]"
# Labels a small model sometimes puts in front of its message.
SPEAKER_LABELS = ("Customer:", "customer:", "Me:")


def check_ollama() -> None:
    """Confirm Ollama is running, the model is pulled, and it answers with thinking off."""
    try:
        listing = ollama.list()
    except ConnectionError as error:
        # Ollama runs as a system service here; a plain `ollama serve` would run as
        # this user and look for models in ~/.ollama, where the model isn't pulled.
        message = "Ollama isn't running. Start the service with `sudo systemctl start ollama`."
        raise RuntimeError(message) from error

    pulled_models = []
    for model in listing.models:
        pulled_models.append(model.model)
    if CUSTOMER_MODEL not in pulled_models:
        raise RuntimeError(f"{CUSTOMER_MODEL} isn't pulled. Run `ollama pull {CUSTOMER_MODEL}`.")

    # One short exchange proves the model loads and answers with thinking off,
    # which is how every customer turn will call it.
    reply = ollama.chat(
        model=CUSTOMER_MODEL,
        messages=[{"role": "user", "content": "Reply with the single word: ready"}],
        think=False,
    )
    answer = reply.message.content.strip()
    print(f"Customer model check passed: {CUSTOMER_MODEL} is pulled in Ollama")
    print(f"and, with thinking off, answered a test prompt with {answer!r}.")
    print("This model will play the customer in every agent session.")


def build_customer_prompt(persona: str, transcript: list[dict]) -> list[dict]:
    """Turn the conversation into Ollama chat messages, with the model as the customer.

    The model writes the assistant role, so the customer's past messages are
    "assistant" and the VA's are "user". The persona is the system message.
    Each transcript entry is {"speaker": "customer" | "va", "text": ...}.
    """
    messages = [{"role": "system", "content": persona}]
    for entry in transcript:
        if entry["speaker"] == "customer":
            role = "assistant"
        else:
            role = "user"
        messages.append({"role": role, "content": entry["text"]})
    return messages


def clean_customer_message(text: str) -> str:
    """Strip a speaker label and wrapping quotes, which a person wouldn't type."""
    text = text.strip()
    for label in SPEAKER_LABELS:
        if text.startswith(label):
            text = text[len(label):].strip()
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        text = text[1:-1].strip()
    return text


def next_customer_message(persona: str, transcript: list[dict]) -> str:
    """Write the customer's next message, replying to the VA's latest one.

    Thinking is off: the customer should answer like a person typing, and a
    small model's reasoning adds time on every turn without making it more
    convincing. The message may end with END_MARKER; split_end_marker removes it.
    """
    messages = build_customer_prompt(persona, transcript)
    reply = ollama.chat(model=CUSTOMER_MODEL, messages=messages, think=False)
    return clean_customer_message(reply.message.content)


def split_end_marker(message: str) -> tuple[str, bool]:
    """Return the message without END_MARKER, and whether the customer is done.

    The marker is for the harness only, so it is removed before the message
    is sent to the VA.
    """
    if END_MARKER not in message:
        return message, False
    text = message.replace(END_MARKER, "").strip()
    return text, True
