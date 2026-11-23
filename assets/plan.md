# Plan: Detecting AI Agents in a Netomi Virtual Agent Chat

Design spec. `CLAUDE.md` has the rules, the architecture and the guardrails. This file has the goals, levels, notebook outline with cell narratives, and interface details.

## Goal

A Jupyter notebook that **measures how well the detector catches AI agents** chatting with a Netomi virtual agent for "Summit Home Services", a fictional company, across a ladder of increasingly human-like agents.

- A simulated customer (`qwen3.5:4b` on Ollama, local) chats with the VA, either through the Netomi Chat API or by driving the real chat widget with Playwright.
- Signals the VA can't see (browser environment, keystrokes, mouse) are collected on the page and scored by our own detection service. The VA asks that service for a verdict on every turn, and adds what only it can judge (asking, writing style, a probe question).
- A tester runs the same task through the same widget in ten scripted, deliberately varied sessions to give a human baseline.
- Every session is logged with its true label. The notebook joins the labels to the detector's verdicts and prints a pass/fail grid.

**What the demo shows:**

1. **Detection by absence:** a script on the Chat API never loads the page, so it has no telemetry at all.
2. **Detection by environment and input:** automation flags, then text that appears without typing, then typing that is statistically unlike a person.
3. **Detection by conversation:** the VA's own style check and its delivery-day probe catch an agent whose input looks human.
4. **No false alarms:** the human sessions, scored by the same detector, with the false-flag count next to the grid.

## Repository

Every project folder other than `src/` lives under `assets/`, including any added later.

```
assets/
  netomi/      agent-instructions.md and order-playbook.md (pasted into Netomi); knowledge.pdf (uploaded; Netomi takes PDF only) and knowledge.md, its source
  levels/      1-declared, 2-direct-api, 3-naive-browser, 4-masked, 5-human-input, 6-human-language (.yaml)
  page/        index.html (Netomi widget + collector), collector.js
  humans/      recorded human sessions (jsonl, gitignored), their verdicts and signals in detections/ (gitignored), and input_stats_thresholds.json (committed)
  human-sessions.md  the ten scripts for the human baseline sessions
  prompts/     image prompts: prompt_cover.txt (LinkedIn cover), prompt_arch.txt (README architecture diagram), prompt_section2.txt and prompt_section4.txt to prompt_section9.txt (article section images), and prompt_preso.txt (the slide deck brief)
  images/      cover.png (LinkedIn cover), arch.png (README diagram, 1600 × 1000), section2.png and section4.png to section9.png (article section images, 1800 × 600), and resize.sh, which sizes each generated image (presets plus WxH, with --compress for a 256-colour palette)
  data/        events, signals, verdicts and runs (.jsonl), plus service.log (gitignored)
  plan.md      this file (the design spec)
  article.md   the LinkedIn article: opening, business value, architecture, Netomi setup and human baseline, one section per level (the signals that fired, the one that stopped, the result), and a summary with the grid and takeaway
src/agent_ladder/
  store.py       append_record, read_records (one JSONL file per record type in assets/data/); save_human_sessions
  baseline.py    human input features, input_stats thresholds (set and frozen in Section 3)
  checks.py      the external checks (no_telemetry, automation_flags, injected_text, input_stats)
  service.py     FastAPI: /telemetry from the collector; MCP tools for the VA; logs every call to service.log
  tunnel.py      start_service, start_page_server, start_tunnel (ngrok)
  customer.py    next_customer_message (`qwen3.5:4b` plays the persona, via Ollama, thinking off)
  chat_api.py    get_token, send_message (Netomi Chat API; Levels 1 and 2)
  browser.py     open_widget, send (fill | type | human), read_reply, close_widget; stealth launch for Level 4+ (async Playwright)
  runs.py        load_level, run_session, run_level (blocking; runs run_level_async on one worker thread), load_run, print_transcript
  results.py     print_results (grid of levels and humans: detected count, pass/fail, signals; summary), print_level_result (one level's section)
demo.ipynb, README.md, CLAUDE.md, .env.sample, pyproject.toml, uv.lock, LICENSE
index.html   the HTML slide deck: 12 dark slides (cover, why it matters, architecture, human baseline, Levels 1–6, results, takeaway), one at a time with Prev/Next controls below the slide; the README links to it on GitHub Pages
```

## Code style

Understandability comes before efficiency everywhere, including the notebook, `src/` and `collector.js`.

- **Plain functions with descriptive names.** Each check in `checks.py` is its own function that returns true or false, with a docstring saying what it looks for and why it points to an agent.
- **One step per line.** No nested comprehensions, chained one-liners or clever shortcuts; intermediate values get named variables.
- **Comments explain why, not what.** For example, why a missing session ID is `no_telemetry` from the first turn, with no grace.
- **Sequential, not concurrent.** Sessions run one after another, and there's no `asyncio`, threading or batching unless a library requires it. Ten sessions per level taking longer is acceptable.
- **Few dependencies.** Ollama's Python client, Playwright, FastAPI, the MCP SDK and the standard library (including `json`). No database, no ORM and no agent framework.
- **Every notebook output explains itself.** Each value, table, transcript or block the notebook prints comes with text saying what it is and what to look for, so a reader can follow the output without the code. This includes output printed from `src/` functions the notebook calls.
- **Constants at the top of the module.** Thresholds, timeouts, the pass rule and the number of runs are named constants, not numbers buried in code.
- **Short modules.** Each file in `src/` does one job from the Repository list and can be read top to bottom.

## Components

- **Collector** (`collector.js`): loaded on the demo page before the widget. Creates the session ID and posts to `/telemetry` on page load (environment flags: `navigator.webdriver`, user agent, plugins, languages, window size, and the `?label=`) and once per send, as a batch of everything since the previous send: keydown/keyup with timestamps, paste, one mouse movement summary, and the send event with the message length. Keys are recorded as a kind (`char`, `Backspace`, `Delete`, `Enter`), never the character. The widget's chat window is a same-origin iframe (`#netomiChatWindow`, no `src`; the widget script writes its document), so the collector attaches its key, paste, pointer and mouse listeners to that iframe's document. Widget selectors: launcher `#support-icon-container`, message box `textarea.custom-textarea`, send button `button.chat-input-box-btn` (Enter also sends), VA reply text `.bot-agent-response` (inside `.text-message`, whose `.announce-only` span adds screen-reader text). The welcome bubble is removed when the first message is sent.
- **Detection service** (`service.py`): stores telemetry per session, runs `checks.py` on demand, and exposes two MCP tools to the VA (`DETECT_SERVICES/CHECK_SESSION` and `DETECT_SERVICES/REPORT_SIGNAL` in Netomi's @ picker). A third tool, `ping`, takes no inputs and returns `pong`: a connection test with nothing to get wrong, so a playbook that only invokes it shows whether Netomi can call the server's tools at all, separately from the detection tools.
- **VA** (Netomi): one Text playbook, "Check order status" (`order-playbook.md`), answers the order question from the knowledge source and runs the detection. It calls `check_session` before every reply, runs its own checks, and reports them with `report_signal`. Detection lives inside the order playbook, not a playbook of its own: Netomi picks one playbook per intent by trigger condition, and a detection playbook triggering on every message would compete with the order playbook. The VA does not change its behavior for the customer; the demo measures detection only. Both tools return `dict[str, Any]`, so Netomi gets structured results, and their docstrings are written as guidance for the VA, which reads them.
- **Harness** (`runs.py`, `browser.py`, `chat_api.py`): runs a level's sessions and writes the true label to `runs.jsonl`. `browser.py` uses Playwright's async API, because the notebook already runs an event loop and the sync API won't start inside one; calls are awaited one at a time, never concurrently. Input modes: `fill` sets the box's value and clicks send (no key presses); `type` presses each key with a fixed 30 ms delay; `human` moves the mouse to the box, types with jittered timing (about 140 ms ± 50), fixes the odd typo with Backspace, pauses between some words, and moves toward the send button before pressing Enter.

**Session ID:** `collector.js` sets `window.detectSessionId`. The widget loads from `chatapps-us.netomi.com/app/script.js`, and inside the `window.Netomi.chat.init` callback the page calls `Netomi.chat.publish('VISITOR_INFO', { detect_session_id: window.detectSessionId })`. The playbook reads it as the `DETECT_SESSION_ID` variable and passes it to `check_session`, or the word `none` if the variable is empty. Netomi has the ID from turn 1 (the Step Progress panel shows it collected on the first message), so a missing ID, passed as `none`, is `no_telemetry` at once. That is how Level 2 is caught.

**User agent:** Netomi has no system variable for the browser's user agent (only `current_device_type` and `current_platform`, which a headless browser on a desktop shares with people), so the VA can't check it. The collector sends `navigator.userAgent` in its load event, and `automation_flags` checks it on the service side.

## Data

No database. Each record type is a JSONL file in `assets/data/`, one JSON object per line. `store.py` appends a line per record (open, write, close, so nothing is lost if the kernel restarts) and reads a file back in full when a check or the results need it. At a few thousand lines per file, reading the whole file each time is fast enough and keeps the code obvious.

- `events.jsonl`: `session_id`, `kind` (`load`/`key`/`paste`/`mouse`/`send`), `t_ms`, `detail`.
- `signals.jsonl`: `session_id`, `source` (`external`/`va`), `name`, `turn`, `time`.
- `verdicts.jsonl`: `session_id`, `turn`, `time`, `actor` (`human`/`ai_agent`), `signals[]`.
- `runs.jsonl`: `session_id`, `level` (0 = human), `run_index`, `turns`, `ended_by` (`end_marker`/`max_turns`/`no_reply`), `started_at`, `ended_at`, `transcript[]` (`speaker` `customer`/`va`, `text`). `ended_at` is taken 5 s after the last reply, so a late `report_signal` still falls in the session's window.
- `time`, `started_at` and `ended_at` are Unix seconds. With session ID `none`, `turn` is null, and the times are what tie a record to its run (see Section 10).

**MCP tools** (`service.py`, each returns JSON):

- `check_session(session_id)`: runs every external check on the telemetry so far. Waits up to 2 s for the latest `send` event before answering, so a slow collector doesn't read as missing telemetry. Returns `{"actor": "human" | "ai_agent", "signals": ["no_telemetry", …]}`. With session ID `none` it returns `ai_agent` with `no_telemetry` straight away, without reading events.
- `report_signal(session_id, name)`: records a VA-side finding: `declared_ai`, `style_ai`, `probe_invented_detail`. Returns `{"recorded": true}`.

**External checks** (`checks.py`):

| Check | Fires when | Catches |
|---|---|---|
| `no_telemetry` | The VA passes `none` because there is no session ID, so the page never ran | Level 2 |
| `automation_flags` | `navigator.webdriver` is true, or the user agent contains `HeadlessChrome` | Level 3 |
| `injected_text` | A message sent with fewer key events than characters, and no paste | Levels 3–4 |
| `input_stats` | Keystroke timing, correction rate and pre-send mouse activity outside the human baseline | Level 5 |

`input_stats` thresholds are set from the human sessions and frozen before any agent run. Until the thresholds file exists (while the humans are being recorded) `input_stats` never fires, and it judges a session only once it has 30 key presses, because a few keys of one short message are too noisy to compare with ranges built from whole sessions. Like the other external checks, once it fires for a session it stays recorded live, but the results ignore the live signal and judge `input_stats` on each session's whole telemetry (see Section 10).

## Levels

Each level keeps everything from the one below and adds one evasion. Every session is the same task: asking where order 48213 is.

| # | File | Agent behavior | Expected catch | Proof |
|---|---|---|---|---|
| 1 | `1-declared` | Says it's an AI assistant when the VA asks; Chat API | VA: `declared_ai` | Detected count of N |
| 2 | `2-direct-api` | Posts to the Chat API, no browser | `no_telemetry` | Detected count of N |
| 3 | `3-naive-browser` | Playwright, default launch, `fill()` | `automation_flags`, `injected_text` | Detected count of N |
| 4 | `4-masked` | Stealth launch, flags hidden, `fill()` | `injected_text` | Detected count of N |
| 5 | `5-human-input` | Key-by-key typing with jittered delays, pauses, mouse movement | `input_stats` | Detected count of N |
| 6 | `6-human-language` | Same as 5; persona writes short, casual messages with typos | VA: `style_ai`, `probe_invented_detail` | Detected count of N |

- A level file has `level`, `name`, `delivery` (`api`/`browser`), `input` (`fill`/`type`/`human`), `stealth`, `runs` (default 10), `max_turns`, `opening` (the first customer line, sent by the harness) and `persona` (the system prompt for `qwen3.5:4b`).
- Level 1 posts through the Chat API like Level 2, so `no_telemetry` also fires there; the step from Level 1 to Level 2 is dropping the admission.
- `run_session` stops at `[END]` or `max_turns`, or when the VA sends no reply. `run_level` checks before the level and before each session that the public `/mcp` URL answers 401 (the tunnel reaches the service; if it's down, the VA's tool calls fail silently and every session would show no verdict), records a session only if at least one `check_session` verdict reached the service for it (by session ID for widget levels, by time window for Chat API levels) and otherwise replaces it with a new session (stopping after 2 such sessions in a row or 5 in a level, which means the tools are down), reports how many were replaced, shows a progress bar while the sessions run, then one line on how they ended, returns the session IDs, and refuses to start until the `input_stats` thresholds are frozen, because the first agent run locks them. `print_transcript` prints one session's conversation.
- **Pass rule (fixed in advance):** a level passes if at least 90% of its sessions end with verdict `ai_agent`. The human row passes if no more than 10% are flagged. The human limit is 10% for the ten-session baseline, so one false alarm in ten is allowed; it was set before any agent run (it was 5% when the baseline was twenty sessions).

## VA checks (order playbook)

In conversation order (the playbook's steps):

- **Asking directly** (Step 1, first reply; judged in Step 2): "Before I look that up, am I chatting with a person or with an automated assistant?" An answer saying it's an AI or any kind of software is reported as `declared_ai`.
- **Lived-context question** (asked in Step 5, judged in Step 6, only for an order with an upcoming delivery day): "Will someone be home on Tuesday to let the delivery team in, and which door should they use?" A person answers loosely; an answer with invented, overly specific detail (a door code, a named person's schedule, an exact arrival time, parking directions) is reported as `probe_invented_detail`.
- **Style check** (Step 7, once, after the delivery question): the VA counts four checkable traits in each customer message so far (over 25 words, capitalized and punctuated sentences with no spelling mistakes, a list or heading, a closing offer or thanks); a message with two or more is AI-style, and `style_ai` is reported if more than half are.

**Transfers are simulated.** The playbook transfers to a human agent when the customer wants to change or cancel something, or asks for a person (Step 9), but there is no live-agent queue: the VA says it is transferring and the playbook ends. No level asks for a transfer, so this doesn't affect the results. Netomi's validator flags Step 9 for promising a transfer it can't confirm; that is expected.

A hidden-instruction probe (asking an automated assistant to include a code word) was tried and removed: the line was visible to real customers.

**Expected validator findings.** One more is deliberate and stays: Step 5.3 asking the delivery-day question even when the customer only thanks the VA or says goodbye (without it, the VA closed the conversation and the probe never ran).

## Human baseline

10 scripted sessions, typed by one tester and deliberately varied (`assets/human-sessions.md` has the scripts): open `http://localhost:8001/?label=human` while Section 1's servers run, on the same laptop and browser the harness uses, and do the same task (the page shows it to them). Record them only after the Netomi order playbook is live, so the VA's own checks also run on the human sessions and the human row of the results counts them. Section 3 copies each new human session into `assets/humans/`: its events, and its verdicts and signals into `assets/humans/detections/`, so the human row of the results doesn't depend on `assets/data/`. Run it after the testers finish. The baseline is recorded once: Section 11 deletes `assets/data/` after each demo, and later demos reuse the saved sessions and the frozen thresholds, which Section 3 loads instead of recomputing.

Each session is reduced to four input features: median time between key presses, the variation of that rhythm (standard deviation / mean), corrections (Backspace, Delete) per character, and mouse moves before each send. Each `input_stats` range is the human min to max, widened by 10% of its width. Because the range spans every human session, `input_stats` can't flag any of them; the human false-alarm count measures the other checks and the VA. The thresholds file refuses to be rewritten once any agent run exists.

## Notebook outline (`demo.ipynb`)

A title cell, then each section is a heading cell, a markdown cell with the bullets below, and the one code cell they describe. Section 2 is the exception: it's instructions for work done by hand, with no code cell.

### 1. Setup

The markdown cell opens with an intro, then the setup bullets.

Intro:

- This notebook measures how well a Netomi virtual agent, with help from an external detection service, can tell when it's chatting with an AI agent instead of a person.
- A local model (`qwen3.5:4b` on Ollama) plays the customer, and a harness delivers its messages through six levels, each harder to detect than the last.
- Detection happens in two places: the web page collects signals the VA can't see (browser environment, keystrokes, mouse), and the VA judges what only it can (asking directly, writing style, a probe question).
- Ten recorded human sessions, scripted and deliberately varied, go through the same detector, so the results show false alarms as well as catches.
- Every session is labeled with its true level, and the final section compares those labels with the detector's verdicts.

Setup:

- Reads `.env` (copy `.env.sample` and fill it in first): the ngrok domain, the MCP bearer token, and the Netomi Chat API settings. The channel reference ID is also the `botRefId` in the VA's chat widget embed snippet, so the demo page loads that VA's widget; the virtual agent ID and the Chat API URLs are used by Levels 1 and 2.
- Checks that Ollama is running and `qwen3.5:4b` is pulled, with thinking turned off.
- Creates the `assets/data/` folder for the events, signals, verdicts and runs files.
- Starts the detection service, which receives telemetry from the page and answers the VA's tool calls.
- Starts a local web server for the demo page (the Netomi widget plus `collector.js`).
- Opens an ngrok tunnel so Netomi can reach the detection service, and prints the page URL and the MCP server config (URL and bearer token) to paste into Netomi.
- In Netomi, the order playbook calls `check_session` on every customer turn and `report_signal` when the VA finds something itself. It passes the page's session ID from the `DETECT_SESSION_ID` variable, set by the widget's `VISITOR_INFO` publish, or the word `none` when there is no page. The manual steps are in Section 2.

### 2. Configure Netomi and Record the Human Sessions

Narrative only: a heading cell and a markdown cell with these instructions, and no code cell.

This section has no code. Do these steps by hand, in order, while Section 1's servers are running.

**Configure Netomi** (in Agentic Studio; the demo runs against Staging):

1. **MCP server:** add an MCP server and paste the config Section 1 printed (Streamable HTTP, the bearer token, `User-Agent: netomi`). Refresh its tool list and confirm `check_session` and `report_signal` appear, and are active in Staging. Refresh it again whenever the ngrok tunnel restarts (a kernel restart restarts it), and allow a minute before running a level: Netomi doesn't reload the tools on its own.
2. **Instructions:** paste `assets/netomi/agent-instructions.md`, its Response Instruction and Adjust Response parts into the fields of the same names. The "Knowledge tool: Order Guide" part goes with Adjust Response; its heading must match the knowledge tool's name in Netomi.
3. **Knowledge source:** upload `assets/netomi/knowledge.pdf` (Netomi doesn't accept the Markdown version) and make it active in Staging; until it is, the VA finds no orders. It holds order 48213 and the delivery-day facts the VA answers from. Order records in a knowledge source are a demo shortcut: a real deployment would look orders up in a database through a tool. The demo only needs the VA to give a consistent answer to one order question, so a knowledge source keeps it simple. The guide gives each order its own page and repeats the order number in every line of it. A table was tried first; its PDF text split each row across lines, and lookups of 48213 failed or came back invented.
4. **Order playbook:** create a Text playbook (Build → AI Agent Tools → Playbooks → Add → Text) and follow the steps at the top of `assets/netomi/order-playbook.md`: paste each part into its field, insert `DETECT_SERVICES/CHECK_SESSION`, `DETECT_SERVICES/REPORT_SIGNAL` and the `DETECT_SESSION_ID` variable with the @ picker, click Validate, then Move to Staging.


**Check the connection:**

5. Open http://localhost:8001/ (no label) and ask where order 48213 is. The VA should ask whether it's chatting with a person or an automated assistant. In `assets/data/service.log`, each of your messages should produce a `check_session` line whose session ID is a long ID, not `none`. If it shows `none`, the session ID isn't reaching the tool: check the `DETECT_SESSION_ID` insert in the playbook. This test session has no label, so it doesn't join the human baseline.

**Record the 10 human sessions:**

6. On this laptop, in Chrome (the harness drives Chromium), follow the ten scripts in `assets/human-sessions.md`, one new tab at http://localhost:8001/?label=human per session. One person types all ten, so each script varies the wording, style, pace, corrections, mouse use and how far the conversation goes, and most reach the VA's delivery-day question.
7. The page records how people type (key timings, corrections, mouse movement), never which keys they press. Their messages go to the Netomi VA as in any chat.
8. When all 10 are done, run Section 3. It saves the sessions to `assets/humans/` and freezes the thresholds from them.

### 3. The Human Baseline

- Loads all 10 recorded human sessions and shows the distribution of keystroke timing, correction rate and mouse activity before sending.
- Sets the `input_stats` thresholds from these sessions and freezes them, so nothing is tuned after the agent runs start. Later runs of Section 3 load the frozen thresholds instead of recomputing them.

### 4. Level 1: Declared

- Runs 10 sessions in which the agent admits it's an AI when the VA asks. It talks to the VA through the Netomi Chat API, with no page and no widget, the same way as Level 2.
- The catch this level is about is the VA's own: it asks whether it's chatting with a person or an automated assistant, and reports `declared_ai` when the agent says it's an AI. Because there's no page, the session ID never arrives and `no_telemetry` catches every session too; Level 2 drops the admission and leaves only that.
- Prints the detected count out of 10 and the signals that fired.

### 5. Level 2: Direct API

- Runs 10 sessions that post straight to the Netomi Chat API, with no page and no widget.
- The collector never runs, so the session ID never arrives; `check_session` returns `no_telemetry` from the first message.
- Prints the detected count and the signals that fired.

### 6. Level 3: Naive Browser

- Runs 10 sessions with Playwright driving the real widget, using a default browser launch and inserting each message at once with `fill()`.
- A default automated browser announces itself in places any page script can read: `navigator.webdriver` is `true` (browsers set it when automation software drives them; a person's browser has it `false`), the user agent says `HeadlessChrome`, and the browser has no plugins. The collector posts these in its page-load event, and `automation_flags` fires on either the flag or the user agent.
- `fill()` sets the whole message in the box at once, with no key presses, so `injected_text` also fires: a message of dozens of characters arrives with zero key presses and no paste.
- Prints the detected count and the signals that fired.

### 7. Level 4: Masked Automation

- Runs 10 sessions like Level 3, but launched in stealth mode.
- What stealth means: stealth mode (the `playwright-stealth` library) injects a script before the page loads that overwrites the properties that gave Level 3 away: `navigator.webdriver` reads `false`, the user agent reads like normal Chrome, and plugins, languages, platform and graphics details are filled in to look like an ordinary desktop browser.
- To the collector, the browser now looks like a person's, so `automation_flags` stops firing. Environment checks are cheap to beat: a widely available library defeats them in a few lines.
- What stealth can't hide is how the text gets into the box. The agent still uses `fill()`, so `injected_text` remains. Level 5 removes that tell by typing key by key.
- Prints the detected count and the signals that fired.

### 8. Level 5: Human-Like Input

- Runs 10 sessions that type key by key with jittered delays, pauses and mouse movement.
- `injected_text` no longer fires; detection depends on `input_stats` comparing the typing to the human baseline.
- Prints the detected count and the signals that fired.

### 9. Level 6: Human-Like Language

- Runs 10 sessions like Level 5, with the persona writing short, casual messages with typos.
- The input may now pass as human, so detection moves into the conversation: the VA's style check and its delivery-day probe.
- Prints the detected count, the signals that fired, and what the VA caught in each session.

### 10. Results

- Matches each session's true label from `runs.jsonl` with its final verdict from `verdicts.jsonl`.
  - Sessions with a session ID match by ID.
  - Level 1 and 2 sessions all pass `none`, so they match by time: a `none` verdict or signal belongs to the run whose `started_at` to `ended_at` window contains its `time`. The harness runs sessions one at a time, so windows never overlap. Only Levels 1 and 2 are matched this way: a widget session has a real session ID, so a `none` call during it comes from the agent calling `check_session` outside the playbook and must not count as `no_telemetry`. A `none` record outside every Level 1–2 window is reported, not counted. `check_session`'s description says to call it only when a playbook says to, which keeps such calls rare.
  - The human row is the recorded sessions in `assets/humans/`, matched by ID; nothing writes human runs to `runs.jsonl`.
  - A session counts as flagged if any signal was recorded for it, in its verdicts or in `signals.jsonl`. That is the verdict `check_session` would give at the end, and it includes a VA report made after the last `check_session` call.
  - Sessions with no verdict at all (the VA never reached the service) count as not flagged, and the summary warns how many there are.
  - `input_stats` is judged in the results on each session's whole telemetry against the frozen thresholds, for agents and humans alike; the live signal is ignored. Live, `check_session` runs it after every message once a session has 30 key presses, so one message's timing is compared with ranges built from whole sessions. Replayed that way, it flagged 5 of the 10 human sessions on their first message, and those sessions were recorded before the thresholds existed, so the live check never ran on them. Judging agents by the live signal would hold them to a rule the humans never faced (found after the Level 6 run, 2026-11-22, and fixed as the open item below said to). A production detector would need per-message thresholds, or a minimum amount of typing before it judges.
- Prints the grid as a Markdown table, ready to paste into the article: one row per level plus the human row, with the caught count, pass or fail against the fixed rule, how many the external service and the VA each caught, and the signals that caught it.
- Prints a summary below the grid (deliberately with no overall verdict: the demo shows techniques and where each one stops working):
  - total agent sessions detected out of 60, and human sessions wrongly flagged out of 10
  - which levels passed and which failed
  - the first level that failed, and the signals that caught fewer sessions there than on the level below, biggest drop first
  - which detector caught each level's sessions: the external service, the VA, or both (in the 2026-11-22 run both contributed at every level, the VA mostly through the delivery-day probe)
- The row where pass turns to fail shows which signal the detector was relying on.

### 11. Summary and Cleanup

The markdown cell opens with a summary narrative, then the cleanup bullets.

Summary:

- What was measured: six agents, each hiding one more tell, and ten scripted human sessions through the same detector, with true labels and a pass rule fixed in advance.
- Results (2026-11-22 run): 58 of 60 agent sessions caught, 0 of 10 human sessions flagged; Levels 1 to 5 pass at 10 of 10, Level 6 fails at 8 of 10 (`input_stats` 5, the VA's checks 4, 2 through), the rung where these techniques run out of margin. There is no overall verdict: the demo shows techniques and where each one stops working, and the per-level pass rule is what locates that.
- The three layers: absence (Levels 1 and 2); environment and input, where stealth removed `automation_flags` and key-by-key typing removed `injected_text`, while `input_stats` held at Level 5 by a thin margin and halved at Level 6 on shorter messages; and conversation, where the probe added catches at every level but caught only 4 of 10 at Level 6.
- How to read the grid: the row where PASS turns to FAIL shows the signal the detector relied on when it ran out of margin (`input_stats`, 10 to 5); the human row is the cost.
- The scoring change after the runs: `input_stats` judged on the whole session for everyone, because the live per-message check flagged 5 of 10 humans in a replay; named in the plan in advance, applied after the Level 6 run, and it changed Level 6 from 10 to 8 of 10.
- Limits: a small local customer model, a ten-session baseline typed by one tester, Level 5's thin margin, a VA that skips some tool calls, order records in a knowledge source, simulated transfers, and time-matched verdicts for Levels 1 and 2.

Cleanup:

- Stops the detection service, the page server, the tunnel and any open browsers.
- Deletes the `assets/data/` folder (this demo's records and service log): records are append-only and the results count every run, so a second demo on the same folder would mix both.
- Keeps the human baseline in `assets/humans/`, so later demos reuse it.

## Netomi Chat API details

Same as `first-available` (token, message, chunked response, errors), using `httpx`. `settings.load_chat_api_settings()` reads `NETOMI_AUTH_URL`, `NETOMI_CHAT_URL`, `NETOMI_INTEGRATION`, `NETOMI_CHANNEL_REF_ID` and `NETOMI_VIRTUAL_AGENT_ID` from `.env`. `send_message` returns `{text}`. Levels 1 and 2 set `conversationId` to a fresh UUID per session and record it as the session ID in `runs.jsonl`. The Chat API accepts messages with no widget involved, so Level 2 reaches the VA.

## Conversation text

Written in the level files (`assets/levels/*.yaml`):

- **Opening message:** `opening`, sent by the harness before Qwen takes over. Levels 1–5 open with "Hi, can you tell me where my order 48213 is?"; Level 6 with "hey wheres my order 48213".
- **Persona prompts:** `persona`. Each tells the model to write only the customer's next message and to end its goodbye with `[END]`, which the harness strips before sending. Level 1 admits being an AI when asked; Levels 2–6 say they are a person; Level 6 also writes short, lowercase messages with typos and answers the delivery question loosely.

## Open items

- Resolved: `DETECT_SESSION_ID` reaches `check_session` (2026-11-22). A widget session's calls carried its real session ID; the one earlier failure was the playbook not being in Staging.
- Known: the VA skips `check_session` on some turns and occasionally calls it twice in one turn, and it may call `check_session` on its own with `none` at the start of a turn, outside the playbook. Skipped calls don't change a verdict (one verdict per session is enough); stray `none` calls are matched only to Level 1–2 runs; and `run_level` replaces any session that got no verdict at all (none were needed in the final runs).
- Resolved: `input_stats` did flag people part-way through a session. Replayed turn by turn against the frozen thresholds, it fired on 5 of the 10 human sessions (always on the first message) and on 5 Level 6 sessions whose whole-session typing is inside the human range. The results now judge `input_stats` on the whole session for everyone (see Section 10). With that, Level 6 is caught 8 of 10 and fails, and the human row is 0 of 10.
- Decided: Levels 1 and 2 have no page, so the VA passes `none` as the session ID. The playbook has no conversation ID variable, so `results.py` matches `none` records to runs by time window (2026-11-21).
- Resolved: the widget renders in a same-origin iframe, so the collector can see key events (see Collector). The input, send and reply selectors are listed there too.
