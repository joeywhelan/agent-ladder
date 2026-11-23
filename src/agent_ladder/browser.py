"""Drive the real Netomi chat widget on the demo page with Playwright (Levels 3-6).

The page loads collector.js before the widget, so everything done here is seen
by the detection service exactly as a person's session would be. What changes
from level to level is how the browser is launched (default or stealth) and how
each message gets into the message box (fill, type or human).

Playwright's async API is used because the notebook already runs an event loop,
and the sync API refuses to start inside one. Every call is awaited in turn;
nothing runs concurrently.
"""

import random
import time

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

PAGE_URL = "http://localhost:8001/"
VIEWPORT = {"width": 1280, "height": 800}

# Widget elements, all inside the chat window's same-origin iframe.
WIDGET_IFRAME = "#netomiChatWindow"
LAUNCHER_BUTTON = "#support-icon-container"
MESSAGE_BOX = "textarea.custom-textarea"
SEND_BUTTON = "button.chat-input-box-btn"
VA_REPLY = ".bot-agent-response"
# Set on VA replies already read, so the next read only picks up new ones.
SEEN_ATTRIBUTE = "data-harness-seen"

WIDGET_OPEN_TIMEOUT_MS = 30_000
# The VA calls the detection tools and searches the knowledge source first.
REPLY_TIMEOUT_SECONDS = 120
# A reply can arrive as several bubbles; it is complete once none has
# appeared or changed for this long.
REPLY_SETTLE_SECONDS = 3.0
REPLY_POLL_SECONDS = 0.5

# input "type": the same short delay after every key, like Playwright's default typing.
TYPE_DELAY_MS = 30

# input "human": jittered key timing, the odd typo fixed with Backspace,
# pauses between words, and mouse movement before typing and before sending.
HUMAN_KEY_DELAY_MEAN_MS = 140
HUMAN_KEY_DELAY_SPREAD_MS = 50
HUMAN_KEY_DELAY_MIN_MS = 40
HUMAN_TYPO_RATE = 0.03
HUMAN_WORD_PAUSE_RATE = 0.10
HUMAN_WORD_PAUSE_MS = (300, 900)
HUMAN_THINK_PAUSE_MS = (800, 2500)
HUMAN_MOUSE_STEPS = (15, 40)
TYPO_LETTERS = "abcdefghijklmnopqrstuvwxyz"


async def open_widget(stealth: bool) -> dict:
    """Launch a browser, open the demo page and the chat window; return the session.

    A default headless launch gives itself away: navigator.webdriver is true
    and the user agent says HeadlessChrome. Stealth (Level 4 and up) patches
    both before any page script runs, so collector.js reports a normal browser.
    The returned dict holds what the other functions need, plus the session ID
    the collector created, which is the session's ID in runs.jsonl.
    """
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch()
    context = await browser.new_context(viewport=VIEWPORT)
    if stealth:
        await Stealth().apply_stealth_async(context)
    page = await context.new_page()
    await page.goto(PAGE_URL)

    widget = page.frame_locator(WIDGET_IFRAME)
    await widget.locator(LAUNCHER_BUTTON).click(timeout=WIDGET_OPEN_TIMEOUT_MS)
    await widget.locator(MESSAGE_BOX).wait_for(timeout=WIDGET_OPEN_TIMEOUT_MS)

    session_id = await page.evaluate("window.detectSessionId")
    session = {
        "playwright": playwright,
        "browser": browser,
        "page": page,
        "widget": widget,
        "session_id": session_id,
    }
    return session


async def close_widget(session: dict) -> None:
    """Close the browser and stop Playwright."""
    await session["browser"].close()
    await session["playwright"].stop()


async def mark_replies_seen(session: dict) -> None:
    """Mark every VA reply on screen as read, so read_reply waits for a new one."""
    replies = session["widget"].locator(VA_REPLY)
    await replies.evaluate_all(f"els => els.forEach(e => e.setAttribute('{SEEN_ATTRIBUTE}', '1'))")


async def send_by_fill(session: dict, text: str) -> None:
    """Put the whole message in the box at once and click send: no key presses at all."""
    widget = session["widget"]
    await widget.locator(MESSAGE_BOX).fill(text)
    await widget.locator(SEND_BUTTON).click()


async def send_by_typing(session: dict, text: str) -> None:
    """Type the message key by key with a fixed delay, then press Enter."""
    box = session["widget"].locator(MESSAGE_BOX)
    await box.press_sequentially(text, delay=TYPE_DELAY_MS)
    await box.press("Enter")


def human_key_delay_ms() -> float:
    """One jittered gap between key presses."""
    delay = random.gauss(HUMAN_KEY_DELAY_MEAN_MS, HUMAN_KEY_DELAY_SPREAD_MS)
    return max(delay, HUMAN_KEY_DELAY_MIN_MS)


def wrong_letter(intended: str) -> str:
    """A letter other than the intended one, for a typo."""
    letter = random.choice(TYPO_LETTERS)
    while letter == intended.lower():
        letter = random.choice(TYPO_LETTERS)
    return letter


async def move_mouse_to(session: dict, locator) -> None:
    """Glide the mouse to a random point inside an element, in many small steps."""
    box = await locator.bounding_box()
    target_x = box["x"] + random.uniform(0.2, 0.8) * box["width"]
    target_y = box["y"] + random.uniform(0.3, 0.7) * box["height"]
    steps = random.randint(*HUMAN_MOUSE_STEPS)
    await session["page"].mouse.move(target_x, target_y, steps=steps)


async def send_like_a_human(session: dict, text: str) -> None:
    """Move to the box, click, type with human-like timing and typos, then press Enter.

    Each character is its own key press, so injected_text can't fire. The
    timing, corrections and mouse movement are what input_stats compares with
    the human baseline.
    """
    page = session["page"]
    box = session["widget"].locator(MESSAGE_BOX)

    await page.wait_for_timeout(random.uniform(*HUMAN_THINK_PAUSE_MS))
    await move_mouse_to(session, box)
    await box.click()

    for character in text:
        if character.isalpha() and random.random() < HUMAN_TYPO_RATE:
            await page.keyboard.type(wrong_letter(character))
            await page.wait_for_timeout(human_key_delay_ms())
            await page.keyboard.press("Backspace")
            await page.wait_for_timeout(human_key_delay_ms())

        await page.keyboard.type(character)
        await page.wait_for_timeout(human_key_delay_ms())

        if character == " " and random.random() < HUMAN_WORD_PAUSE_RATE:
            await page.wait_for_timeout(random.uniform(*HUMAN_WORD_PAUSE_MS))

    # A person often glances over the message, moving the mouse, before sending.
    await move_mouse_to(session, session["widget"].locator(SEND_BUTTON))
    await page.keyboard.press("Enter")


async def send(session: dict, text: str, input_mode: str) -> None:
    """Send one customer message the way the level's input mode says: fill, type or human."""
    await mark_replies_seen(session)
    if input_mode == "fill":
        await send_by_fill(session, text)
    elif input_mode == "type":
        await send_by_typing(session, text)
    elif input_mode == "human":
        await send_like_a_human(session, text)
    else:
        raise ValueError(f"Unknown input mode {input_mode!r}; expected fill, type or human")


async def new_reply_texts(session: dict) -> list[str]:
    """The text of each VA reply bubble that arrived since the last send."""
    new_replies = session["widget"].locator(f"{VA_REPLY}:not([{SEEN_ATTRIBUTE}])")
    return await new_replies.all_inner_texts()


async def read_reply(session: dict) -> dict:
    """Wait for the VA's reply to the last message and return it as {"text": ...}.

    Waits for at least one new reply bubble, then until nothing new has
    appeared or changed for REPLY_SETTLE_SECONDS, because a reply can arrive
    in more than one bubble. Returns an empty text if nothing came in time.
    """
    page = session["page"]
    deadline = time.monotonic() + REPLY_TIMEOUT_SECONDS
    texts = []
    last_change = time.monotonic()
    while time.monotonic() < deadline:
        await page.wait_for_timeout(REPLY_POLL_SECONDS * 1000)
        current = await new_reply_texts(session)
        if current != texts:
            texts = current
            last_change = time.monotonic()
            continue
        settled = time.monotonic() - last_change >= REPLY_SETTLE_SECONDS
        if texts and settled:
            break

    cleaned = []
    for text in texts:
        text = text.strip()
        if text:
            cleaned.append(text)
    return {"text": "\n".join(cleaned)}
