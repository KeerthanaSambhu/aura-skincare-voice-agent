# Third-party notices

## Code adapted from SmoothUI (MIT)

| File in this repo | Upstream file |
|---|---|
| `frontend/src/components/ui/SiriOrb.tsx` | `packages/smoothui/components/siri-orb/index.tsx` |
| `frontend/src/components/ui/MagneticButton.tsx` | `packages/smoothui/components/magnetic-button/index.tsx` |
| `frontend/src/components/ui/ai-state.ts` | `packages/smoothui/components/ai-core/index.tsx` (partial) |

- **Source:** https://github.com/educlopez/smoothui, commit `1534f0d39ab56e64b0ddd207bcc065b386b04d8e` (16 Oct 2026). Copied from a local clone of that commit.
- **License:** the repository's root `LICENSE` file is MIT, Copyright (c) 2024 Eduardo Calvo, reproduced below. The individual component `package.json` files have no `license` field of their own, so the root license is what applies.
- **Changes:** listed in each file's header. `SiriOrb.tsx` is identical to upstream apart from its two import paths. `MagneticButton.tsx` has its own variants and a window-level pointer listener. `ai-state.ts` drops upstream's microphone hook.

### Relationship to 21st.dev

21st.dev lists components named **Siri Orb** and **Magnetic Button** by the same author (`@educalvolpz`, part of the SmoothUI library). **No code in this repository was taken from 21st.dev.** I could not view the 21st.dev copies: their source and install commands require a 21st API key. The listings also differ from the GitHub code — 21st.dev shows Siri Orb's license as *unknown* with no dependencies, and Magnetic Button depending on `framer-motion` rather than `motion` — so they are likely a different revision. The license stated above comes from the GitHub repository, not from 21st.dev.

```
MIT License

Copyright (c) 2024 Eduardo Calvo

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Original code written for this project

These were inspired by 21st.dev listings but written from scratch, because their source couldn't be verified:

| Component | 21st.dev listing it replaces | Why it's original |
|---|---|---|
| `sections/Hero.tsx` | Editorial Hero (`@felipemenezes098/hero-05`, listed as MIT) | Source only available with a 21st API key, so it couldn't be inspected |
| `ui/ScrollWordReveal.tsx` | Scroll word reveal (`@motiondotdev`, listed as MIT) | Points to a Motion example page that states no license |

## npm packages

License fields checked in each package's `package.json`:

| Package | License | Use |
|---|---|---|
| `lenis` | MIT | Smooth scrolling |
| `motion` | MIT | Animation |
| `@fontsource-variable/bodoni-moda` | OFL-1.1 | Self-hosted display font |
| `@fontsource-variable/hanken-grotesk` | OFL-1.1 | Self-hosted body font |
| `@google/genai` | Apache-2.0 | Gemini Live connection in the browser (Phase 4) |
| `vitest` (dev only) | MIT | Frontend unit tests |

## Python packages (backend)

| Package | License | Use |
|---|---|---|
| `google-genai` | Apache-2.0 | Minting Gemini ephemeral tokens on the server (Phase 4) |
| `fastapi`, `pydantic`, `pydantic-settings` | MIT | Web API, validation and settings |
| `uvicorn` | BSD-3-Clause | ASGI server |
| `starlette` | BSD-3-Clause | Web framework under FastAPI (pinned directly) |
| `httpx2` (dev only) | BSD-3-Clause | HTTP client for FastAPI's `TestClient` in tests |
| `tzdata` | Apache-2.0 | Time-zone data |
