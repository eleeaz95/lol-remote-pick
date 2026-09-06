---
name: add-lcu-action
description: Wire up a new action the phone can trigger on the League client (accept, pick, swap, set spells, etc.) across every layer it has to be registered in. Use when adding or debugging a client-triggered LCU action, or when an action works over REST but does nothing in the app.
---

# Add an action the phone can trigger

An action is only reachable once it is registered in **every** layer below. Missing one fails silently
rather than erroring, so work through them in order and confirm each.

## 1. `backend/lcu_client.py`

Add the method that calls the real LCU endpoint. Return a plain `bool` for fire-and-forget calls, or the
parsed body when the caller needs it. `request()` already swallows connection errors and returns `None`.

## 2. `backend/server.py` — `AppHub.execute_action`

Add a branch. Match on a tuple of aliases the way the existing branches do, coerce the payload fields with
explicit `int()` / `str()`, and return a `{"success": ..., "action": ...}` dict. Validate against current
state here when the action only makes sense in some phases.

## 3. `backend/server.py` — REST route in `create_app`

Add the `@app.post("/api/...")` route with a Pydantic request model, delegating to `hub.execute_action`.

## 4. `backend/server.py` — the `/ws` gateway mapping

**The step that gets forgotten.** The gateway translates endpoint paths to action names; add an
`elif "/api/your-endpoint" in endpoint:` line. The frontend prefers the WebSocket and only falls back to
REST, so without this the action silently does nothing whenever the socket is healthy.

## 5. `backend/mock_lcu.py`

Add the matching fake endpoint so the action is testable without a League client, and broadcast the state
change the real client would emit. Then cover it in `tests/test_mock_integration.py`.

## 6. Frontend

Call it with `sendApiRequest('/api/your-endpoint', { ... })`. Note that the WebSocket reply is an
`action_result` envelope, not a state snapshot — the UI must not read state out of it. Apply optimistic UI
updates only if you also restore the previous values when the request fails.

## Verify

Run the app with the mock simulator (see the `mock` skill), trigger the action, and confirm the resulting
`/api/state` snapshot changed. Then run `pytest -q`.
