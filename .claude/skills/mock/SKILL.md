---
name: mock
description: Run the app against the built-in mock LCU simulator and drive it through game phases, so a change can be verified end to end without a running League of Legends client. Use when asked to run, preview, or manually verify the app, or when reproducing a lobby / ready check / champion select bug.
---

# Run against the mock LCU simulator

`--mock` starts an in-process fake League client that serves the same REST routes and WAMP WebSocket events
as the real one. Use it instead of asking the user to open League.

## Start it

```bash
python run.py --mock --reload
```

Serves the UI on `http://localhost:8000` (the launcher picks the next free port if 8000 is taken — read the
banner it prints). Add `--no-auto-progress` to stop phases from advancing on their own, which you want when
inspecting a single screen. Run it in the background and tail the log rather than blocking on it.

## Drive the phases

```bash
curl -s -X POST localhost:8000/api/mock/phase -H 'Content-Type: application/json' \
  -d '{"phase": "champ_select", "queueId": 450}'
curl -s -X POST localhost:8000/api/mock/advance     # step to the next phase
curl -s localhost:8000/api/state                    # current normalized snapshot
```

`phase` accepts `none`, `lobby`, `in_queue`, `ready_check`, `champ_select`, `in_game`. `queueId` matters:
ARAM-style queues produce a bench session instead of a pick/ban draft.

## Verify

`/api/state` is the fastest check — it returns exactly what the phone receives. For UI behavior, open the
page in a browser and watch the console, or connect a raw WebSocket client to `/ws` to see the message
sequence the frontend actually gets.

Always stop the server when you are done.
