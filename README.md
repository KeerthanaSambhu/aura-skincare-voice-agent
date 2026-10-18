# Aura AI

A browser-based voice support agent, Aria, for the fictional skincare brand Aura Skincare. Built for the DataStraw AI Voice Agent assessment.

> Work in progress. Phase 4 of 6: real voice calls (Gemini Live), order tools, policy checks and post-call summaries are implemented. The full README, including architecture and the reflection answers, arrives in Phase 6.

## How a call works

```
Browser                                   Aura backend (FastAPI)                Google
───────                                   ──────────────────────                ──────
Start call ─ mic permission
           ─ POST /api/voice/sessions ──▶ mint single-use token, ────────────▶ auth_tokens
                                          config locked in it
           ◀─ token + config + secret ───
           ─ WebSocket (token) ────────────────────────────────────────────────▶ Gemini Live
 16 kHz mic audio ─────────────────────────────────────────────────────────────▶ (gemini-3.8-live)
 24 kHz speech + transcripts ◀──────────────────────────────────────────────────
 toolCall ─ POST …/tool-calls ─────────▶ validate, run on SQLite,
           ◀─ {ok, result|error} ─────── policy rules in Python
 toolResponse ─────────────────────────────────────────────────────────────────▶
End call ─ POST …/end (transcript) ────▶ rules-based summary from
           ◀─ transcript + JSON summary ─ the server's tool log
```

The Gemini API key stays on the server. The browser only ever holds a single-use token that expires within the call's time limit.

## Run it locally

You need Python 3.11+, Node.js 22.12+ or 24+ (the frontend toolchain doesn't run on Node 20, 21, 23 or 25), internet access to PyPI and the npm registry for the installs, and for voice a Gemini API key from <https://aistudio.google.com/apikey>.

**Backend** (terminal 1):

```bash
cd backend
python -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                   # then set GEMINI_API_KEY in .env
uvicorn app.main:app --reload --port 8000
```

**Frontend** (terminal 2):

```bash
cd frontend
npm ci                                 # exact versions from package-lock.json
npm run dev                            # http://localhost:5173
```

The frontend calls the backend at `http://localhost:8000`. To use another address, set `VITE_API_BASE_URL` in `frontend/.env.local` (see `frontend/.env.example`; it's public, never a key) and restart `npm run dev`.

Open <[(https://aura-skincare-voice-agent-notkeerthana.vercel.app/)]>, click **Start call**, and allow the microphone when the browser asks. Without `GEMINI_API_KEY` the page still works, but Start call explains that voice isn't set up.

**Browser requirements:** a recent Chrome, Edge, Firefox or Safari; microphone permission; and a secure page (`https://` or `localhost`). Use headphones for the best results; echo cancellation is on, but speakers can still trigger an interruption.

More detail: [backend/README.md](backend/README.md) (configuration, voice setup, database reset, deployment) and [backend/API_CONTRACT.md](backend/API_CONTRACT.md) (every endpoint, with real example responses).

## Test

```bash
cd backend && python -m pytest && ruff check . && ruff format --check . && mypy
cd frontend && npm test && npm run lint && npm run build
```

No test needs a network connection or an API key. Google's services are replaced by fakes in the tests, so a real spoken call has to be checked by hand.

**Manual call script** (needs a key):

1. Start a call. Aria should greet you as Aria from Aura Skincare.
2. "Where is my order ORD 101?": out for delivery with BlueDart, expected by 6 PM today.
3. "Can I cancel ORD-101?": no, but you can refuse delivery at the doorstep.
4. "I opened ORD-102 and want to return it": outside the 7-day return window.
5. "Is shipping free on a 499 rupee order?": the policy doesn't specify exactly ₹499.
6. "Cancel ORD-103": Aria checks, asks you to confirm, and cancels only after you say yes.
7. "Where is ORD-999?": she can't find it and asks you to check the number.
8. "Book me a flight to Goa": she only helps with Aura Skincare.
9. Interrupt her mid-sentence: she should stop and listen.
10. End the call. The call summary shows the transcript and a JSON summary.

Afterwards, reset the demo orders with `cd backend && python -m app.cli reset-db`.

### If an install or check fails

Both of these mean the dependencies aren't installed, not that the code is broken:

| You see | Cause | Fix |
|---|---|---|
| `pytest`: `Missing test dependencies: google-genai…` (or `No module named 'google'`) | `pip install` didn't finish, or ran in a different environment | In `backend/`, activate `.venv` and run `pip install -r requirements-dev.txt` until it ends without errors |
| `npm run build`: `Can't build yet: … dependencies aren't installed`, or `TS2688: Cannot find type definition file for 'vite/client'` / `'node'` | `npm ci` didn't run or didn't finish, so `node_modules/` has no Vite or Node types | In `frontend/`, run `npm ci` until it ends without errors |
| `npm ci`: `EBADENGINE Unsupported engine` | Node.js version outside 22.12+ / 24+ | Install Node 22 LTS or 24 LTS |

Both installs download packages, from PyPI and registry.npmjs.org. If your network blocks them, the tests and build can't run, and that failure should be reported, not treated as a partial pass. The test suite stops on purpose if a test dependency is missing.

## Structure

```
backend/
  app/                          FastAPI app, SQLite, policy engine, cancel_order
  app/voice/                    voice sessions: tokens, Aria's prompt and tools, summaries
  tests/                        pytest suite
  API_CONTRACT.md               endpoints and response shapes
frontend/
  src/
    App.tsx                     page composition
    index.css                   design tokens (colour, type, radius, motion)
    components/                 layout, sections (VoiceConsole, CallSummary, …), UI primitives
    voice/                      the call: controller, Gemini adapter, audio, transcript, API client
    voice/audio/                microphone (AudioWorklet, 16 kHz PCM) and speaker playback (24 kHz)
    voice/__tests__/            Vitest unit tests
    data/sampleOrders.ts        Test Orders helper copy (display only)
```

Third-party code and licenses: see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Engineering Decisions & Reflections

### 1. Why did you choose this architecture and technology stack?

I chose React with Vite for a responsive frontend and FastAPI for the backend because they provide a lightweight, modular architecture that is straightforward to develop and maintain. Gemini Live enables real-time voice conversations, while the backend handles order operations, business rules, and secure voice session setup. Vercel and Render provide accessible deployment options for the frontend and backend.

### 2. What was the most difficult part of the assignment, and how did you solve it?

The most difficult part was integrating real-time voice interaction with the backend and deploying the application reliably. I tested the API endpoints, checked deployment logs, and debugged environment variable and CORS configuration issues until the frontend could communicate with the backend and the voice experience worked as expected.

### 3. If you had one more week, what would you improve first and why?

I would first improve automated end-to-end testing and error handling for voice sessions, order lookups, and cancellation workflows. This would help identify failures earlier and make the customer experience more reliable, particularly when network connectivity or the voice service is interrupted.

### 4. What would need to change if the agent handled 1,000 customer conversations a day?

I would introduce a production-grade database, stronger monitoring and logging, rate limiting, and more robust error recovery. I would also evaluate concurrent voice-session capacity, Gemini API quotas and costs, and backend scaling requirements, while adding automated load tests to identify bottlenecks before increasing traffic.
