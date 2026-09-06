# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A FastAPI backend that talks to a locally running League of Legends client through its LCU API, plus a
phone-facing web UI served from the same process. The phone accepts ready checks, picks/bans champions and
swaps summoner spells over a LAN WebSocket.

Setup and contribution steps live in @CONTRIBUTING.md.

## Running it

```bash
python run.py --mock --reload      # built-in fake LCU; no League client needed
python run.py --reload             # against a real, running League client
```

Prefer `--mock` for development and for verifying changes. It starts an in-process fake LCU server
(`backend/mock_lcu.py`) that serves the same REST routes and WAMP WebSocket events as the real client, so
every phase can be driven without launching a game. Phases are triggered through `/api/mock/*`.

## Architecture

State flows one way and must stay that way:

```
League client (LCU WebSocket events, HTTP polling fallback)
  -> StateEngine        normalizes into one snapshot dict
  -> AppHub             broadcasts to every connected phone
  -> frontend           renders from that snapshot
```

- `StateEngine` owns all normalization. Never forward raw LCU payloads to the frontend — add the field to
  the normalizer instead, so mock and live modes produce identical shapes.
- `StateEngine` debounces disconnects and lobby deletions on purpose: the League client emits brief empty
  states mid-transition, and reacting to them immediately makes the phone flicker.
- The LCU WebSocket is the primary transport; HTTP polling only runs while it is down.

## Adding an action the phone can trigger

Wiring one up touches several files, and skipping a step fails silently:

1. `LCUClient` — the method that calls the real LCU endpoint.
2. `AppHub.execute_action` — a branch handling the action name (each accepts several aliases).
3. `create_app` — the REST route.
4. The `/ws` gateway's endpoint-to-action mapping — **easy to miss.** The frontend prefers the WebSocket and
   only falls back to REST, so an unmapped endpoint makes the action do nothing while the socket is healthy.
5. `mock_lcu.py` — the matching fake endpoint, so tests can cover it without a League client.

## Frontend

- Vanilla HTML/CSS/JS in `frontend/`, served directly. There is no build step and no framework.
- `/ws` carries two message shapes: normalized state snapshots, and `{"type": "action_result", ...}` replies.
  Only snapshots may go through state normalization — an envelope has no `phase`, and treating it as state
  drops the UI onto the disconnected screen.
- Bump the `?v=` query on the `css`/`js` tags in `index.html` when you change those files. Phones cache hard.
- Champion and spell art comes from DataDragon; the version is a setting, not a hardcoded URL.

## Tests

```bash
pytest -q                 # whole suite
pytest -k test_name       # single test
```

`asyncio_mode = "auto"`, so async tests need no `@pytest.mark.asyncio`. Tests run against the mock LCU server
and must never require a real League client — CI runs them on Ubuntu as well as Windows, so keep Windows-only
discovery code (registry, process inspection) out of import paths that tests touch.

## Lint and format

```bash
ruff format . && ruff check --fix .          # Python, enforced in CI
npx prettier --write "frontend/**/*.{js,css}"  # frontend JS/CSS only
```

`frontend/index.html` is deliberately excluded from Prettier via `.prettierignore`.

## Conventions

- Conventional Commits (`feat:`, `fix:`, `docs:`, `style:`, `refactor:`, `test:`, `chore:`).
- Branch off `main`; open a PR against `main` and fill in the template.

## Constraints

This project only drives the player's own League client through the local LCU API that Riot exposes. Do not
add anything that automates gameplay, reads or writes game memory, or intercepts game traffic.
