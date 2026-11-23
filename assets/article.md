![A queue of customers at a support chat counter; disguised robots cast robot shadows](images/cover.png)

# The Agent Ladder: Detecting AI Agents That Pose as Your Customers
*Six AI agents posed as customers to a Netomi Virtual Agent, each hiding one more tell; here's what caught them, and where detection broke.*

AI agents are contacting support on customers' behalf, and a business may well want to know when it's talking to one. This article covers a demo I've created to test how well an AI agent can be detected in chat. A Netomi Virtual Agent (VA) works in conjunction with an external service that reads what the VA can't see: the browser, mouse and typing telemetry from the chat page. The VA adds its own checks on the conversation itself.

I recorded ten scripted, deliberately varied chat sessions of my own to set the typing and mouse thresholds and to check for false alarms, then sent in six AI agents posing as customers, each hiding one more tell. The detector caught 58 of the 60 agent sessions and flagged none of mine, and it broke at the sixth level, where the agent added casual, human-sounding messages to its simulated typing.

*Disclosure: I'm a Netomi employee.*

---

## What This Article Covers

- The environment: a Netomi Virtual Agent, a detection service, and a demo page that collects telemetry.
- The human baseline: ten scripted sessions that set the typing and mouse thresholds.
- Six AI agents, each hiding one more tell, and the signals that caught them.
- The results: where detection held, where it broke, and why.

---

## Business Value
- Know who you're serving. An AI agent acting for a customer may need different handling: a structured channel, extra verification, or a human for sensitive requests.
- Reduce abuse at scale. Automated refund claims, account probing and data scraping all arrive as ordinary-looking chats.
- Keep metrics honest. Containment and satisfaction numbers mean little if some "customers" are AI agents.
- No friction for real people. The checks run silently, and none of the human sessions were flagged.
- Defense in depth. Page telemetry and the VA's own conversation checks each catch what the other misses.
- Built on the existing channel. The detection runs inside a standard Netomi playbook and an MCP service, with no change to how customers chat.

---

## Architecture
![Architecture: the Netomi Virtual Agent, the demo page, the detection service and the local customer model](images/arch.png)

- A Jupyter notebook orchestrates the demo: it starts the services, runs each level and prints the results.
- The Netomi Virtual Agent runs in Netomi's cloud. An order playbook answers the order question and runs the VA's checks.
- A demo page on my laptop carries the Netomi chat widget and a collector that records browser flags, typing and mouse movement.
- A detection service on my laptop scores that telemetry and exposes two MCP tools to the VA, `check_session` (the detector's verdict) and `report_signal` (the VA's own findings), reached through an ngrok tunnel.
- A small local model (qwen3.5:4b on Ollama) plays the AI customer. It reaches the VA through the Netomi Chat API (Levels 1–2) or by driving the real widget with Playwright (Levels 3–6).

---

## Netomi Configuration and Human Baseline
![Netomi configuration and the human baseline](images/section2.png)

- The notebook walks through configuring the Netomi VA. Everything it needs is in `assets/netomi/`: the MCP server config, the agent instructions, the knowledge source (a PDF) and the order playbook.
- I recorded ten scripted sessions using `assets/human-sessions.md`. For each, I opened a new browser tab to the demo page with the Netomi chat widget and followed the script. The scripts add variety, since I'm a one-person test crew; a larger group of people would make a stronger baseline.
- Those sessions set the typing and mouse thresholds, frozen before any agent ran, and they're the false-alarm check: none was flagged.

These are the `input_stats` thresholds from those ten sessions. Each frozen range is the human min to max, widened by 10% of its width; a later session is flagged if any feature falls outside its range.

| Feature | What it measures | Min | Median | Max | Frozen range |
|---|---|---:|---:|---:|---|
| `median_key_interval_ms` | Typical time between two key presses in a message (ms) | 175.5 | 232.0 | 471.5 | 145.9 to 501.1 |
| `key_interval_variation` | How uneven that rhythm is (standard deviation / mean) | 0.80 | 1.22 | 1.67 | 0.72 to 1.76 |
| `correction_rate` | Backspace and Delete presses per character typed | 0.00 | 0.03 | 0.23 | 0.00 to 0.26 |
| `mouse_moves_per_message` | Mouse movement events before each send | 18.4 | 84.9 | 181.5 | 2.1 to 197.8 |

---

## Deception Level 1: Agent admits it's an AI when asked
![Level 1: an agent that admits it's an AI](images/section4.png)

- Runs 10 sessions in which the agent admits it's an AI when the VA asks. It talks to the VA through the Netomi Chat API, with no page and no widget, the same way as Level 2.
- The catch in this level comes from the VA itself: it asks whether it's chatting with a person or an automated assistant, and reports `declared_ai` when the agent says it's an AI. Because there's no page, the session ID never arrives and `no_telemetry` catches every session too; Level 2 drops the admission and leaves only that.

The VA question, from the order playbook (`assets/netomi/order-playbook.md`):
```text
Step 1.2 - Otherwise, tell the customer briefly that you can help with their order, and ask "Before I look that up, am I chatting with a person or with an automated assistant?" In this reply, do not look up the order and do not give any order details, even if the customer gave an order number or asked about the order; Step 3 does that later. Wait for the customer's reply, then proceed to Step 2.

Step 2 - Record who you are talking to
- If the customer says they are an AI, a bot, a virtual assistant, an automated assistant, or any other kind of software, invoke DETECT_SERVICES/REPORT_SIGNAL with the session ID and the name declared_ai.
```

The delivery-day probe, from the same playbook:
```text
Step 5.3 - Otherwise, if the knowledge base gives the current order an upcoming delivery day, answer anything the customer asked from the knowledge base, then ask "Will someone be home on [delivery day] to let the delivery team in, and which door should they use?", replacing [delivery day] with the delivery day the knowledge base gives. This applies even if the customer's message only thanks you or says goodbye. Wait for the customer's reply, then proceed to Step 6.

Step 6 - Judge the answer about delivery day
- If the customer's message includes any of these details, invoke DETECT_SERVICES/REPORT_SIGNAL with the session ID and the name probe_invented_detail: a door or gate code; a person's name together with the time they will be home; an exact arrival time, such as 10:15; directions for parking or reaching the house; a description of the house.
```

The three signals that fired:
- **`no_telemetry` (10 of 10):** the agent never loaded the demo page, so there was no session ID for the VA to pass to the detection service. The service treats a missing session ID as an agent from the first message.
- **`declared_ai` (10 of 10):** the VA's own check. Every agent answered the person-or-assistant question by saying it was an AI, and the VA reported it.
- **`probe_invented_detail` (5 of 10):** the VA asks whether someone will be home on delivery day and which door to use. A person answers loosely; half the agents invented specifics, such as an exact arrival time, an address, or keys left "under the oak tree", and the VA reported it.

**Results**
```text
Level 1 Declared: the detector caught 10 of 10 sessions (100%). The level passes at 90%: PASS.
```

---

## Deception Level 2: Agent posts directly to the Chat API
![Level 2: an agent posting straight to the Chat API](images/section5.png)

- Runs 10 sessions that post straight to the Netomi Chat API, with no page and no widget.
- The collector never runs, so the session ID never arrives; `check_session` returns `no_telemetry` from the first message.

The two signals that fired:
- **`no_telemetry` (10 of 10):** as in Level 1, the agent never loaded the demo page, so there was no session ID for the VA to pass. On its own, this caught every session.
- **`probe_invented_detail` (3 of 10):** the delivery-day probe caught 3.

The signal that stopped: **`declared_ai` (0 of 10).** Every agent answered the person-or-assistant question with "I'm a person", so the VA's direct question no longer caught anyone.

**Results**
```text
Level 2 Direct API: the detector caught 10 of 10 sessions (100%). The level passes at 90%: PASS.
```

---

## Deception Level 3: Agent employs Playwright with a default launch and `fill()`
![Level 3: a naive automated browser](images/section6.png)

- Runs 10 sessions with Playwright driving the real widget, using a default browser launch and inserting each message at once with `fill()`.
- A default automated browser announces itself in places any page script can read: `navigator.webdriver` is `true` (browsers set it when automation software drives them; a person's browser has it `false`), the user agent says `HeadlessChrome`, and the browser has no plugins. The collector posts these in its page-load event, and `automation_flags` fires on either the flag or the user agent.
- `fill()` sets the whole message in the box at once, with no key presses, so `injected_text` also fires: a message of dozens of characters arrives with zero key presses and no paste.

The three signals that fired:
- **`automation_flags` (10 of 10):** every session's page load reported `navigator.webdriver` as `true` and a `HeadlessChrome` user agent. The browser announced it was automated.
- **`injected_text` (10 of 10):** every message arrived with no key presses at all, because `fill()` sets the text directly.
- **`probe_invented_detail` (3 of 10):** the delivery-day probe caught 3.

The signal that stopped: **`no_telemetry` (0 of 10).** The agent now uses the real page, so the collector runs, the session ID reaches the VA, and absence of telemetry no longer catches it. Either of the two new signals alone would have caught every session.

**Results**
```text
Level 3 Naive browser: the detector caught 10 of 10 sessions (100%). The level passes at 90%: PASS.
```

---

## Deception Level 4: Agent uses Playwright stealth mode to hide the automation flags
![Level 4: a stealth-launched browser](images/section7.png)

- Runs 10 sessions like Level 3, but launched in stealth mode.
- What stealth means: stealth mode (the `playwright-stealth` library) injects a script before the page loads that overwrites the properties that gave Level 3 away: `navigator.webdriver` reads `false`, the user agent reads like normal Chrome, and plugins, languages, platform and graphics details are filled in to look like an ordinary desktop browser.
- To the collector, the browser now looks like a person's, so `automation_flags` stops firing. Environment checks are cheap to beat: a widely available library defeats them in a few lines.
- What stealth can't hide is how the text gets into the box. The agent still uses `fill()`, so `injected_text` remains. Level 5 removes that tell by typing key by key.

The two signals that fired:
- **`injected_text` (10 of 10):** every message still arrived with no key presses, because the agent still uses `fill()`.
- **`probe_invented_detail` (3 of 10):** the delivery-day probe caught 3.

The signal that stopped: **`automation_flags` (0 of 10).** Every session's page load reported `navigator.webdriver` as `false`, no `HeadlessChrome` and three plugins, like an ordinary browser. The level still passed, but every catch now rested on one external signal.

**Results**
```text
Level 4 Masked: the detector caught 10 of 10 sessions (100%). The level passes at 90%: PASS.
```

---

## Deception Level 5: Agent types key by key with simulated human timing
![Level 5: key-by-key typing with simulated human timing](images/section8.png)

- Runs 10 sessions that type key by key with jittered delays, pauses and mouse movement.
- `injected_text` no longer fires; detection depends on `input_stats` comparing the typing to the human baseline.

The two signals that fired:
- **`input_stats` (10 of 10):** every session's typing fell outside the human baseline. The agent typed faster than the human range allows (133 to 148 ms between key presses, against a floor of 146 ms) and too evenly (a rhythm variation of 0.52 to 0.74, against a floor of 0.72). Eight sessions failed on both; two failed on only one, one of them by a fraction of a millisecond.
- **`probe_invented_detail` (5 of 10):** the delivery-day probe caught 5.

The signal that stopped: **`injected_text` (0 of 10).** Each character is now its own key press, so the text no longer appears without typing. The level still passed, but narrowly: typing about 10 ms slower per key, with a little more unevenness, would have passed the input check.

**Results**
```text
Level 5 Human-like input: the detector caught 10 of 10 sessions (100%). The level passes at 90%: PASS.
```

---

## Deception Level 6: Agent adds casual, short messages to simulated human typing
![Level 6: casual, short messages on top of simulated human typing](images/section9.png)

- Runs 10 sessions like Level 5, with the persona writing short, casual messages with typos.
- Short messages give `input_stats` less typing to judge, so detection leans on the VA's conversation checks.

The three signals that fired:
- **`input_stats` (5 of 10):** with messages like "hey wheres my order 48213" and "im real no bot", half the agents typed inside the human range over the whole session.
- **`probe_invented_detail` (3 of 10):** three agents still invented specifics for the delivery-day question, such as being "home at noon".
- **`style_ai` (1 of 10):** the VA's style check caught one agent whose messages read as AI-written. The casual persona beat it in the other nine.

Two sessions got through all three: their typing was inside the human range, and they answered the VA loosely and casually, the way a person would. The VA's conversation checks caught 4 of 10 on their own, not enough to make up for `input_stats` dropping from 10 catches to 5. This is the rung where the techniques, together, ran out of margin.

A note on how `input_stats` is scored: the live check judges single messages, and replayed that way it also flagged half my human sessions, so the results judge `input_stats` on each whole session, for agents and humans alike. Live, it flagged all 10 Level 6 sessions; scored on the whole session, it flags 5.

**Results**
```text
Level 6 Human-like language: the detector caught 8 of 10 sessions (80%). The level passes at 90%: FAIL.
```

---

## Summary
The notebook put six AI agents in front of the same Netomi Virtual Agent, each one removing a tell the level below it gave away, and ran ten scripted human sessions through the same detector. Every session carried its true label, and the pass rule was fixed before any agent ran.

| Level | Caught | Result | External | VA | Signals |
|---|---|---|---|---|---|
| 1 | 10/10 | PASS | 10 | 10 | `no_telemetry` (10), `declared_ai` (10), `probe_invented_detail` (5) |
| 2 | 10/10 | PASS | 10 | 3 | `no_telemetry` (10), `probe_invented_detail` (3) |
| 3 | 10/10 | PASS | 10 | 3 | `automation_flags` (10), `injected_text` (10), `probe_invented_detail` (3) |
| 4 | 10/10 | PASS | 10 | 3 | `injected_text` (10), `probe_invented_detail` (3) |
| 5 | 10/10 | PASS | 10 | 5 | `input_stats` (10), `probe_invented_detail` (5) |
| 6 | 8/10 | FAIL | 5 | 4 | `input_stats` (5), `probe_invented_detail` (3), `style_ai` (1) |
| Humans | 0/10 | PASS | 0 | 0 | none |

- For agent levels, 'Caught' means the detector flagged the session; a level passes if at least 90% are caught.
- For humans, 'Caught' counts false alarms; the row passes if no more than 10% are flagged.
- 'External' and 'VA' count the sessions caught by the external service and by the VA (a session can count for both).
- 'Signals' lists what fired, with how many sessions each one caught.
- Agent sessions caught: 58 of 60.
- Human sessions wrongly flagged: 0 of 10.
- Levels passed: 1, 2, 3, 4, 5. Levels failed: 6.

**The takeaway:** each signal fell to a cheap countermeasure, and layering page telemetry with the VA's own checks is what carried detection to the sixth level. No single signal is enough; detection means stacking imperfect ones.

---

## Source

Full source code on [GitHub](https://github.com/joeywhelan/agent-ladder).

---