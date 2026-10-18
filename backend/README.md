# Aura AI backend

FastAPI + SQLite service that holds Aura Skincare's mock order records and makes every policy decision in plain Python. It also starts Aria's voice calls: it mints short-lived Gemini tokens, runs the tools Aria asks for, and builds the post-call summary. The language model never decides eligibility on its own.

> **Mock assessment system.** The three orders are the sample data from the DataStraw brief. Nothing here connects to a real order-management, carrier or payment system. "Cancelling" an order changes only the demo SQLite record.

## Requirements

- Python 3.11 or newer (developed and tested on 3.13)
- For voice calls only: a Gemini API key (see [Voice setup](#voice-setup)). Everything else runs without one.

## Install

From the `backend/` directory:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt   # runtime + test/lint tools
# or, runtime only:  pip install -r requirements.txt
```

## Configure

```bash
cp .env.example .env               # optional: the defaults work locally
```

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_PATH` | `data/aura.db` | SQLite file. Relative paths resolve from `backend/`. |
| `ALLOWED_ORIGINS` | `http://localhost:5173,http://localhost:4173` | Comma-separated browser origins allowed by CORS (the dev server and `npm run preview`). |
| `APP_TIMEZONE` | `Asia/Kolkata` | Time zone for "today", "6 PM" and day counts. |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR`. |
| `GEMINI_API_KEY` | *(empty)* | **Secret.** Enables voice calls. Without it, `POST /api/voice/sessions` returns `503 VOICE_NOT_CONFIGURED`. |
| `GEMINI_LIVE_MODEL` | `gemini-3.8-live` | Gemini Live model. |
| `GEMINI_API_VERSION` | `v1beta` | API version for ephemeral tokens (`v1beta` or `v1alpha`). |
| `GEMINI_VOICE` | `Sulafat` | One of Gemini's 30 prebuilt voices. |
| `VOICE_SESSION_MINUTES` | `15` | Token lifetime and maximum call length, 1–15. Google also closes a Live connection after about 10 minutes (see limitations). |
| `VOICE_SESSIONS_PER_IP_PER_HOUR` | `30` | New calls allowed per client IP per hour. |

Environment variables override `.env`. `GEMINI_API_KEY` is the only secret: it is read on the server, never returned by any endpoint, and never logged.

## Voice setup

1. Create a key at <https://aistudio.google.com/apikey>. Google's pricing page lists Live audio on the free tier; check your account's current limits and data terms in AI Studio.
2. Put it in `backend/.env` as `GEMINI_API_KEY=...` (or set the environment variable). Don't commit it.
3. Restart the server. `POST /api/voice/sessions` should now return `201`.

How it works:

- **Token, not key.** For each call the server mints a Gemini *ephemeral token* (`app/voice/tokens.py`). It can open one session, must be used within 1 minute, expires after `VOICE_SESSION_MINUTES`, and has the model, Aria's instructions, tools and voice **locked** into it, so the browser can't change them.
- **Aria's instructions and tools** are in `app/voice/prompt.py`. The brief's policies are included verbatim. All six tools are `BLOCKING`, because `gemini-3.8-live` otherwise answers before tool results arrive.
- **Tools run here** (`app/voice/tools.py`), using the same functions as the REST API. Every result goes back to the model as `{"ok": true|false, ...}`, so failures are reported instead of left for the model to guess at.
- **Cancellation** needs three things: `customer_confirmed: true` (a real JSON boolean), an `ELIGIBLE` eligibility check for that order earlier in the same call, and the Phase 3 database re-check.
- **Post-call summary** (`app/voice/summary.py`) is built by rules from the tools this server executed, plus the customer's own words quoted verbatim. No AI writes it.
- **Call records** are stored in SQLite: `voice_sessions`, `voice_tool_calls`, `voice_transcript_turns` and `voice_summaries`. `reset-db` resets orders only, not call records.
- Model, voice and Indian-English/Hinglish delivery are set by `GEMINI_LIVE_MODEL`, `GEMINI_VOICE` and Aria's instructions. Gemini has no dedicated Indian-English voice, so how Indian Aria sounds depends on the model following those instructions.

## Database

```bash
python -m app.cli init-db     # create and seed, only if the database has no orders yet
python -m app.cli reset-db    # wipe all orders and reseed the three sample orders
python -m app.cli show        # list orders and their status
```

- **Startup never overwrites data.** On start the server creates the schema and seeds the three orders *only if the database is empty*. A cancelled ORD-103 stays cancelled across restarts.
- **Resetting** is explicit: `reset-db` deletes every order and reseeds in one transaction. Run it before a demo, or whenever you want to test the ORD-103 cancellation again. It's safe to run while the server is up.
- **Relative timing.** The brief gives times relative to "now" ("delivered 14 days ago", "expected by 6 PM today", "ordered 3 hours ago"). Seeding turns these into real timestamps anchored to the moment of seeding, in `APP_TIMEZONE`. Responses phrase timing relative to the current time, so a day later ORD-102 reads "Delivered 15 days ago" and ORD-103 "Ordered 27 hours ago". `reset-db` re-anchors them to the brief's exact wording.
- **ORD-101's delivery estimate is a fixed snapshot.** It always reads "Expected by 6 PM today", matching the brief and the Test Orders card, whatever the time of day the app is opened. It is never compared with the clock, so it can't show as late after 6 PM. It is mock data, not a carrier update, and every lookup's `data_note` says so.
- Only facts the brief states are stored. It gives no order date for ORD-101 or ORD-102, so `ordered_at` is `null` for them. No extra orders or tracking events exist.

## Run

```bash
uvicorn app.main:app --reload --port 8000
```

- Health: <http://localhost:8000/health>
- Interactive API docs: <http://localhost:8000/docs>
- Endpoint contract for the frontend: [API_CONTRACT.md](API_CONTRACT.md)

## Test, lint, type-check

```bash
python -m pytest              # full test suite (no network or API key needed)
ruff check .                  # lint
ruff format --check .         # formatting
mypy                          # strict type check of app/
```

Every test uses its own temporary SQLite file and a frozen clock. An autouse fixture fails the run if any test touches `data/aura.db`. Voice tests replace Google's token service with a fake minter (`tests/conftest.py`), so they never contact Google.

## How it's organised

| File | Role |
|---|---|
| `app/main.py` | FastAPI app factory, routes, CORS, error handlers, request logging |
| `app/db.py` | Schema, seed data, `seed_if_empty`, `reset_demo_data` |
| `app/order_ids.py` | Normalises `ord 101`, `Order 101`, `#101`… to `ORD-101` |
| `app/orders.py` | `get_order_details` and timing descriptions |
| `app/policies.py` | Shipping, COD, return, damaged/defective and cancellation rules, with the brief's policy text verbatim |
| `app/cancellation.py` | `cancel_order`, the only operation that writes |
| `app/schemas.py` | Pydantic request and response models |
| `app/errors.py` | Structured error type and messages |
| `app/cli.py` | `init-db`, `reset-db`, `show` |
| `app/voice/prompt.py` | Aria's system instruction, tool declarations, Live config |
| `app/voice/tokens.py` | Ephemeral-token minting (the only code that uses the API key) |
| `app/voice/tools.py` | Tool gateway: argument validation, cancellation gates, audit log |
| `app/voice/summary.py` | Rules-based post-call summary |
| `app/voice/routes.py` | `/api/voice/...` routes, session secrets, rate limit |
| `tests/` | pytest suite |

### Policy decisions the brief leaves open

These are explicit choices, each covered by a test:

- **Exactly ₹499 shipping:** the policy covers "above ₹499" and "below ₹499" only, so the result is `POLICY_UNSPECIFIED` and Aria is told not to guess.
- **Window edges are inclusive:** a return at exactly 7 days, or a damage report at exactly 48 hours, is still within the window. COD "up to ₹2,500" includes ₹2,500.
- **Damaged items may be opened:** the "unopened" rule applies to standard returns. Damaged/defective claims need the 48-hour window and photos, and the remedy is a replacement, never a refund.
- **Missing facts produce `NEEDS_INFO`,** e.g. whether a product was opened or whether the customer has photos, so Aria asks rather than assumes.

### How cancellation stays safe

`cancel_order` opens `BEGIN IMMEDIATE` (taking SQLite's write lock), re-reads the status, runs `UPDATE … WHERE status = 'Processing'`, checks exactly one row changed, and only then commits. Success is returned after the commit. A test fires 12 simultaneous cancellations at ORD-103: exactly one succeeds, the rest get `ALREADY_CANCELLED`.

## Deploying

- Set `GEMINI_API_KEY` as a secret environment variable on the host, never in a committed file.
- Set `ALLOWED_ORIGINS` to the deployed frontend's exact origin (e.g. `https://aura-ai.example.com`).
- The frontend must be served over **HTTPS**: browsers only allow the microphone on secure pages (and `localhost`).
- Run one instance: the rate limiter is in memory and the database is one SQLite file. Hosts with ephemeral disks reset the database on redeploy.
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.

## Known limitations

- SQLite with one file suits a single-instance demo. Several server instances would each need the same file, or a real database.
- A `reset-db` on a deployed server needs shell access. How evaluators reset ORD-103 on the public demo is still to be decided (Phase 4–6).
- Damaged/defective claims only check eligibility; there is no photo upload or replacement workflow.
- There is no user authentication: anyone who can reach the API can cancel ORD-103 through the REST endpoint. Voice tool calls need their session's secret, but anyone can start a session (rate-limited per IP). Acceptable for this mock demo only.
- The rate limiter is per process and in memory, and keys on the connecting IP. Behind a proxy, every client may share one IP.
- If the browser tab is closed mid-call, `/end` is never called: the session stays `active` in the database until its token expires, and no summary is saved.
- **Calls last about 10 minutes at most.** Google limits audio sessions to 15 minutes and a single Live connection to about 10 minutes, and warns with a `goAway` message before closing it. The app doesn't use session resumption: on `goAway` it ends the call cleanly ("The call reached its time limit") and saves the summary, marked for follow-up if the customer had said anything.
- The post-call transcript doesn't mark Aria's turns that the customer cut off. The live transcript does ("cut off"), but that flag isn't sent to or stored by the backend.
- The system instruction is visible to anyone who inspects the browser's network traffic (it's part of `live_config`). It contains no secrets. It's locked in the token, so it can be read but not changed.
