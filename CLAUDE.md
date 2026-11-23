# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Jupyter notebook demo (`demo.ipynb`) that measures how well a detector catches AI agents chatting with a Netomi virtual agent (VA) for "Summit Home Services", a fictional company. A local model plays the customer and is delivered through a "ladder" of six levels, each harder to detect than the last. Recorded human sessions go through the same detector as a false-alarm baseline. The notebook joins each session's true label with the detector's verdict and prints a pass/fail grid.

**`assets/plan.md` is the design spec**: goals, levels, data model, MCP tool contracts, notebook outline with per-cell narratives, Netomi setup steps, and open items. Read it before building any component. This file holds the rules and architecture summary; the plan holds the detail.

## Current state

Everything in the plan's Repository list is built, and the demo has run end to end (2026-11-22): the human baseline (10 scripted sessions by one tester) is recorded and its thresholds frozen, all six levels ran at 10 sessions each, and Section 10 reports 58 of 60 agent sessions caught, 0 of 10 humans flagged, with Level 6 the only level below the 90% line (8 of 10).

Write-up status: the LinkedIn article (`assets/article.md`) is drafted and reviewed, with its numbers from this run. The slide deck is built: `index.html` at the repo root, 12 slides (cover, why it matters, architecture, human baseline, one slide per level, results, takeaway), all on the charcoal background, built with the netomi-shared generate-presentation skill from the brief in `assets/prompts/prompt_preso.txt`. It shows one slide at a time with Prev/Next and a counter in a bar below the slide (arrow keys, Page Up/Down, Space, Home, End; `#N` in the URL), prints as one slide per page, loads fonts from Google Fonts and images from `assets/images/` (so it needs the repo layout), and the README links to it on GitHub Pages (`joeywhelan.github.io/agent-ladder/`). To check it, render a copy with the local fonts through the skill's `html_to_pdf.py --check` and look at every page; never ship absolute `file:///` paths in `index.html`. The images are done: `cover.png`, `arch.png` (1600 × 1000 for the README) and the seven section images (1800 × 600), each generated from a prompt in `assets/prompts/` and sized with `assets/images/resize.sh`. Section 11 then ran as planned, so `assets/data/` (this run's records) is gone; the numbers live on in the article, the deck and the README, and the human baseline in `assets/humans/` is kept for the next demo.

All modules go in `src/agent_ladder/`.

## Folder layout

Every project folder other than `src/` is a subfolder of `assets/` (`assets/data/`, `assets/page/`, `assets/levels/` and so on). Put any new folder there too, never at the repo root.

## Commands

The project uses `uv` and Python 3.14 (`.python-version`).

```bash
uv sync                               # install deps, including the dev group (ipykernel)
uv run agent-ladder                   # run the package entry point (agent_ladder:main)
uv add <pkg>                          # add a dependency (keep the dependency list short, see below)
uv run playwright install chromium    # browser for Levels 3-6
ollama pull qwen3.5:4b                # the customer model, run locally with thinking off
```

The notebook uses the `agent-ladder` venv kernel. No test runner is configured. pylint isn't a project dependency; run it with `uvx` and point it at `src/` and the venv:

```bash
uvx pylint --init-hook "import sys; sys.path.insert(0, 'src'); sys.path.insert(0, '.venv/lib/python3.14/site-packages')" src/agent_ladder/*.py
```

To lint the notebook the way the editor does, join its code cells into one `.py` file (in a scratch folder) and lint that.

## Architecture

Four moving parts, all started from notebook Section 1:

- **Collector** (`assets/page/collector.js`, loaded on `assets/page/index.html` before the Netomi widget): creates `window.detectSessionId` and posts environment flags on load, then one batch per send (keystrokes, paste, mouse summary, send) to the detection service's `/telemetry`. The widget's chat window is a same-origin iframe (`#netomiChatWindow`), so listeners go on the iframe's document; elements there fail `instanceof Element` from the parent page, so check `nodeType` instead. The page holds no `botRefId`: the page server (`tunnel.py`) answers `/config.js` with `NETOMI_CHANNEL_REF_ID` from `.env` (the channel reference ID is the widget's `botRefId`), and `index.html` reads it from there. The page passes the session ID to the widget with `Netomi.chat.publish('VISITOR_INFO', { detect_session_id })` inside the `Netomi.chat.init` callback, so the VA can read it as the `DETECT_SESSION_ID` variable.
- **Detection service** (`service.py`, FastAPI + MCP SDK, exposed through an ngrok tunnel): appends telemetry to JSONL files in `assets/data/` (`store.py`), runs the external checks (`checks.py`: `no_telemetry`, `automation_flags`, `injected_text`, `input_stats`), and exposes MCP tools to the VA: `check_session(session_id)` and `report_signal(session_id, name)`, which accepts `declared_ai`, `style_ai` and `probe_invented_detail`. In Netomi's @ picker they appear as `DETECT_SERVICES/CHECK_SESSION` and `DETECT_SERVICES/REPORT_SIGNAL`. A third tool, `ping` (returns `pong`), is kept on purpose as a connection test: a playbook that only invokes it shows whether Netomi can call the server's tools at all. Logs every call to `assets/data/service.log`.
- **VA** (configured by hand in Netomi from `assets/netomi/`): one Text playbook, `order-playbook.md`, answers the order question from the knowledge source and does the detection. Netomi accepts only the PDF, `knowledge.pdf`, which is committed as is; `knowledge.md` is its source, rendered to PDF with Chromium. Keeping order records in a knowledge source is a deliberate demo shortcut; a real deployment would look them up in a database through a tool. The guide gives each order its own page and repeats the order number on every line, because lookups of an order from a table were unreliable. `agent-instructions.md` includes a "Knowledge tool: Order Guide" section telling the VA how to search it and read the results. Transfers to a human are simulated: there is no live-agent queue. Never write how Netomi implements knowledge sources into any repo file; describe only observed behavior. It calls `check_session` at the start of the playbook's steps (it skips some turns, which doesn't change any verdict) and reports its own findings (`declared_ai`, `style_ai`, `probe_invented_detail`) via `report_signal`. Nothing the VA says may look odd to a real customer: a probe must be an ordinary customer-service question. Detection is not a separate playbook, because a playbook triggering on every message would compete with the order playbook. The VA never changes behavior for the customer; the demo measures detection only.
- **Netomi files** follow Netomi's playbook rules (PDFs in `~/Downloads/define_playbooks.pdf` and `write_playbooks.pdf`): `Step N - Name`, `Step N.M` branches, `Invoke @tool`, an exit condition per step, `→END PROCESS HERE` on every path, an Enforcement Summary, and no curly brackets or em dashes. Tools and variables are inserted with the @ picker. Netomi gotchas: the playbook and the knowledge source only take effect once moved to Staging; and after the ngrok tunnel restarts, refresh the MCP server's tool list in Netomi and allow a minute before the agent calls the tools again. Netomi's validator is an LLM and never reaches zero findings; two are expected and deliberate (Step 5.3 asking the delivery-day question even after a goodbye, and the simulated transfer in Step 9), as the plan records. Before handing over playbook changes, trace every kind of customer reply through every step, and redesign a section rather than patching one branch. MCP tools return `dict[str, Any]` (a bare type gives Netomi no structured content), and their docstrings are guidance the VA reads; after changing one, restart the service and refresh the tool list in Netomi.
- **Harness** (`runs.py`, `browser.py`, `chat_api.py`, `customer.py`): loads a level YAML from `assets/levels/` (fields include `opening`, sent by the harness, and `persona`, the customer model's system prompt), has `qwen3.5:4b` (via Ollama) generate customer messages, delivers them either through the Netomi Chat API (Levels 1–2) or by driving the real widget with Playwright (Levels 3–6, stealth from Level 4), and writes the true label, timing and transcript to `assets/data/runs.jsonl`. The persona ends with `[END]` only after the VA's goodbye or transfer; the harness strips it. `browser.py` uses Playwright's async API because the notebook already runs an event loop; `runs.run_level` is the blocking entry point (it runs `run_level_async` on one worker thread), so notebook cells need no top-level `await`. `run_level` stops if the public `/mcp` URL doesn't answer 401: interrupting a notebook cell can kill the ngrok child process, and the playbook then carries on without detection. It also records a session only if a `check_session` verdict reached the service for it; an unseen session is replaced (the count is printed and belongs in the write-up as a measure of the VA's tool reliability), and 2 in a row or 5 in a level stop the run: after an outage Netomi can reconnect without reloading the tools until they're refreshed in Netomi. The Chat API allows one live token per channel, so never run two Chat API clients at once: the newer token invalidates the older.
- **Results** (`results.py`): matches `runs.jsonl` and the human sessions in `assets/humans/` with the verdicts and signals, prints each level's result for its notebook section, and for Section 10 the grid as a Markdown table (pasted into the article) and a summary. The summary names the first level below the pass line and the signals that caught fewer sessions there than on the level below; there is deliberately no overall verdict, because the demo shows techniques and where each stops working. A session counts as flagged if any signal was recorded for it, including a VA report made after its last `check_session` call. `none` records are matched by time only to Level 1–2 runs: outside the playbook the agent may call `check_session` on its own with `none`, and that must not credit a widget session with `no_telemetry`. Both MCP tool descriptions say to call them only when a playbook says to.

Key behaviors that span components:

- A missing session ID (the VA passes `none`) is `no_telemetry` from the first turn: Netomi has a real session ID from turn 1, so no grace turn is needed. That is how Level 2 (no page, no collector) is caught. All Level 1 and 2 sessions share `none`, so `results.py` matches their verdicts to runs by time window (`time` on verdicts and signals, `started_at`/`ended_at` on runs).
- `check_session` waits up to 2 s for the latest `send` event so a slow collector doesn't read as missing telemetry.
- `input_stats` thresholds are set from the human sessions in notebook Section 3 and frozen before any agent run. Never tune them after agent results exist. `baseline.freeze_thresholds` refuses once an agent run exists, and `run_level` refuses to start until the thresholds exist, so an agent run can't come first. `input_stats` never fires without thresholds (the service runs while humans are recorded) or before a session has 30 key presses. The results ignore the live `input_stats` signal and judge it on each session's whole telemetry, for agents and humans alike: live, it judges single messages, which flagged 5 of 10 human sessions in a replay.
- Any test that calls `run_level` or writes records must point `store.DATA_DIR` at a temporary folder: one agent run in the real `runs.jsonl` freezes the baseline.
- Pass rule is fixed in advance: a level passes if ≥90% of its sessions end with verdict `ai_agent`; the human row passes if ≤10% are flagged (at most 1 of the 10 human sessions). The human limit was set at 10% for the ten-session baseline before any agent run; never change either threshold after agent results exist.

## Code style (from the plan; applies to the notebook, `src/` and `collector.js`)

Understandability comes before efficiency.

- Plain functions with descriptive names. Each check in `checks.py` is its own function returning true/false, with a docstring saying what it looks for and why it points to an agent.
- One step per line: no nested comprehensions, chained one-liners or clever shortcuts; name intermediate values.
- Comments explain why, not what.
- Sequential, not concurrent: no `asyncio`, threading or batching unless a library requires it. Playwright's async API (in the notebook) and the MCP SDK's async tools are the exceptions; calls are still awaited one at a time.
- Few dependencies: Ollama client, Playwright, FastAPI, MCP SDK, and the standard library. No database (records are JSONL files, see the plan's Data section), no ORM, no agent framework.
- Thresholds, timeouts, the pass rule and run counts are named constants at the top of the module.
- Short modules, one job each, readable top to bottom.
- Notebook sections are a heading cell, a markdown cell with the plan's bullets, and the one code cell they describe.
- The editor's pylint reads the whole notebook as one module. So the Section 1 cell holds the only docstring and every import the notebook needs; later code cells open with a `# Section N: ...` comment and import nothing. Section 2 (Netomi setup and human recording) is markdown only.
- Every notebook output explains itself: each printed value, table, transcript or block comes with text saying what it is and what to look for. This includes output printed from `src/` functions the notebook calls.

## Local-only outputs

Recorded human sessions (`assets/humans/*.jsonl`, with their verdicts and signals in `assets/humans/detections/`), the `assets/data/` folder (record files and `service.log`) and `.env` are gitignored and stay local. The human baseline is recorded once and reused by every demo; `assets/data/` holds one demo's records and Section 11 deletes it, because records are append-only and the results count every run in the folder. Netomi credentials (channel reference ID, VA ID) go in `.env`, with `.env.sample` as the template.
