"""
Integration tests for FastAPI application running in Mock LCU simulation mode.

Verifies end-to-end functionality of:
- GET /api/state (normalized state format)
- GET /api/champions (search, role filtering, catalog integrity)
- GET /api/spells (summoner spells)
- GET /api/queues (queue definitions)
- POST /api/lobby/create (create lobby)
- POST /api/lobby/positions (set role preferences)
- POST /api/lobby/queue/start (matchmaking search)
- POST /api/lobby/queue/cancel (cancel search)
- POST /api/matchmaking/accept (ready check accept)
- POST /api/matchmaking/decline (ready check decline)
- POST /api/champ-select/hover & /action (hover and lock in picks/bans)
- POST /api/champ-select/spells (change summoner spells)
- WebSocket gateway (/ws live state broadcast and action execution)
"""

import asyncio

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport

from backend.config import Settings
from backend.server import create_app


@pytest_asyncio.fixture
async def mock_app_and_client():
    """Fixture that initializes the FastAPI application in mock mode and provides an async HTTP client."""
    # Use a high port for mock LCU to avoid collisions
    settings = Settings(
        mock_mode=True,
        mock_port=18888,
        mock_auto_progress=False,  # Controlled step-by-step in tests
        static_dir=None,
    )

    app = create_app(settings)
    hub = app.state.hub

    # Explicitly start hub
    await hub.start()

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield app, client, hub

    # Shutdown hub
    await hub.stop()


@pytest.mark.asyncio
async def test_api_catalog_endpoints(mock_app_and_client):
    """Verify champion, spell, and queue catalog REST endpoints."""
    app, client, hub = mock_app_and_client

    # 1. Champions catalog
    res = await client.get("/api/champions")
    assert res.status_code == 200
    champions = res.json()
    assert isinstance(champions, list)
    assert len(champions) >= 50
    # Check champion fields
    first_champ = champions[0]
    assert "id" in first_champ
    assert "name" in first_champ
    assert "roles" in first_champ
    assert "icon" in first_champ

    # Filter by role
    res_mid = await client.get("/api/champions?role=mid")
    assert res_mid.status_code == 200
    mid_champs = res_mid.json()
    assert len(mid_champs) > 0
    for c in mid_champs:
        assert "mid" in [r.lower() for r in c.get("roles", [])]

    # Search filter
    res_search = await client.get("/api/champions?search=Ahri")
    assert res_search.status_code == 200
    search_results = res_search.json()
    assert any(c["name"] == "Ahri" for c in search_results)
    # Search for Yunara
    res_yunara = await client.get("/api/champions?search=Yunara")
    assert res_yunara.status_code == 200
    yunara_results = res_yunara.json()
    assert len(yunara_results) >= 1
    yunara = yunara_results[0]
    assert yunara["name"] == "Yunara"
    assert yunara["id"] == 804
    assert "bottom" in [r.lower() for r in yunara.get("roles", [])]

    # 2. Summoner Spells
    res_spells = await client.get("/api/spells")
    assert res_spells.status_code == 200
    spells = res_spells.json()
    assert isinstance(spells, list)
    spell_names = [s["name"] for s in spells]
    assert "Flash" in spell_names
    assert "Ignite" in spell_names
    assert "Smite" in spell_names

    # 3. Queues
    res_queues = await client.get("/api/queues")
    assert res_queues.status_code == 200
    queues = res_queues.json()
    assert isinstance(queues, list)
    q_ids = [q["queueId"] for q in queues]
    assert 420 in q_ids  # Ranked Solo/Duo
    assert 450 in q_ids  # ARAM


@pytest.mark.asyncio
async def test_api_state_endpoint(mock_app_and_client):
    """Verify GET /api/state returns valid root schema."""
    app, client, hub = mock_app_and_client

    res = await client.get("/api/state")
    assert res.status_code == 200
    state = res.json()

    assert state["connected"] is True
    assert state["mock"] is True
    assert "phase" in state
    assert "summoner" in state
    assert "lobby" in state
    assert "queue" in state
    assert "readyCheck" in state
    assert "champSelect" in state


@pytest.mark.asyncio
async def test_lobby_and_matchmaking_flow(mock_app_and_client):
    """Verify creating lobby, setting positions, starting queue, and cancelling queue."""
    app, client, hub = mock_app_and_client

    # 1. Create Lobby (420 Ranked Solo)
    res_create = await client.post("/api/lobby/create", json={"queueId": 420})
    assert res_create.status_code == 200
    assert res_create.json()["success"] is True

    # Check updated state
    res_state = await client.get("/api/state")
    state = res_state.json()
    assert state["phase"] == "LOBBY"
    assert state["lobby"]["queueId"] == 420
    assert state["lobby"]["isLeader"] is True

    # 2. Set Position Preferences
    res_pos = await client.post("/api/lobby/positions", json={"first": "MIDDLE", "second": "TOP"})
    assert res_pos.status_code == 200
    assert res_pos.json()["success"] is True

    # 3. Start Matchmaking Queue
    res_start = await client.post("/api/lobby/queue/start")
    assert res_start.status_code == 200
    assert res_start.json()["success"] is True

    # Verify queue state
    res_state2 = await client.get("/api/state")
    state2 = res_state2.json()
    assert state2["phase"] == "IN_QUEUE"
    assert state2["queue"]["inQueue"] is True

    # 4. Cancel Queue
    res_cancel = await client.post("/api/lobby/queue/cancel")
    assert res_cancel.status_code == 200
    assert res_cancel.json()["success"] is True

    res_state3 = await client.get("/api/state")
    state3 = res_state3.json()
    assert state3["phase"] == "LOBBY"
    assert state3["queue"]["inQueue"] is False


@pytest.mark.asyncio
async def test_ready_check_flow(mock_app_and_client):
    """Verify accepting and declining ready check."""
    app, client, hub = mock_app_and_client

    # Trigger Ready Check on mock server
    await hub.mock_server.trigger_ready_check()
    await asyncio.sleep(0.05)

    res_state = await client.get("/api/state")
    state = res_state.json()
    assert state["phase"] == "READY_CHECK"
    assert state["readyCheck"]["state"] == "InProgress"

    # Accept Match
    res_accept = await client.post("/api/matchmaking/accept")
    assert res_accept.status_code == 200
    assert res_accept.json()["success"] is True

    res_state2 = await client.get("/api/state")
    assert res_state2.json()["readyCheck"]["playerResponse"] == "Accepted"


@pytest.mark.asyncio
async def test_champ_select_flow(mock_app_and_client):
    """Verify full champ select actions: hovering, locking bans/picks, changing spells."""
    app, client, hub = mock_app_and_client

    # 1. Trigger Champ Select
    await hub.mock_server.trigger_champ_select()
    await asyncio.sleep(0.05)

    res_state = await client.get("/api/state")
    state = res_state.json()
    assert state["phase"] == "CHAMP_SELECT"
    assert state["champSelect"]["sessionActive"] is True
    assert state["champSelect"]["isMyTurn"] is True
    assert state["champSelect"]["actionPhase"] == "BAN"

    ban_action_id = state["champSelect"]["activeAction"]["id"]

    # 2. Hover Champion for Ban (e.g. Zed 238)
    res_hover = await client.post(
        "/api/champ-select/hover",
        json={"actionId": ban_action_id, "championId": 238},
    )
    assert res_hover.status_code == 200
    assert res_hover.json()["success"] is True

    # 3. Lock in Ban
    res_ban = await client.post(
        "/api/champ-select/action",
        json={"actionId": ban_action_id, "championId": 238, "completed": True},
    )
    assert res_ban.status_code == 200
    assert res_ban.json()["success"] is True

    # 4. Advance Mock to Pick Phase
    await hub.mock_server.advance_to_pick_phase()
    await asyncio.sleep(0.05)

    res_state2 = await client.get("/api/state")
    state2 = res_state2.json()
    assert state2["champSelect"]["actionPhase"] == "PICK"
    pick_action_id = state2["champSelect"]["activeAction"]["id"]
    # Pre-select / Hover Yunara (804) for pick intent before locking in
    res_preselect = await client.post(
        "/api/champ-select/hover",
        json={"actionId": 0, "championId": 804},
    )
    assert res_preselect.status_code == 200
    assert res_preselect.json()["success"] is True

    res_state_hover = await client.get("/api/state")
    state_hover = res_state_hover.json()
    assert state_hover["champSelect"]["myPickIntent"] == 804

    # 5. Lock in Pick (e.g. Ahri 103)
    res_pick = await client.post(
        "/api/champ-select/action",
        json={"actionId": pick_action_id, "championId": 103, "completed": True},
    )
    assert res_pick.status_code == 200
    assert res_pick.json()["success"] is True

    # 6. Change Summoner Spells (Flash 4 + Ignite 14)
    res_spells = await client.post(
        "/api/champ-select/spells",
        json={"spell1Id": 4, "spell2Id": 14, "selectedChampionId": 103},
    )
    assert res_spells.status_code == 200
    assert res_spells.json()["success"] is True

    res_state3 = await client.get("/api/state")
    state3 = res_state3.json()
    assert state3["champSelect"]["mySelection"]["spell1Id"] == 4
    assert state3["champSelect"]["mySelection"]["spell2Id"] == 14


@pytest.mark.asyncio
async def test_app_hub_action_execution(mock_app_and_client):
    """Verify AppHub direct action execution dispatcher."""
    app, client, hub = mock_app_and_client

    # Test unknown action handling
    res_err = await hub.execute_action("NON_EXISTENT_ACTION", {})
    assert res_err["success"] is False
    assert "Unknown action" in res_err.get("error", "")

    # Test GET_STATE action
    res_state = await hub.execute_action("GET_STATE", {})
    assert res_state["success"] is True
    assert "state" in res_state
    assert res_state["state"]["connected"] is True

    # Test MOCK_SET_PHASE
    res_phase = await hub.execute_action("MOCK_SET_PHASE", {"phase": "Lobby", "queueId": 450})
    assert res_phase["success"] is True
    state = hub.state_engine.get_state()
    assert state["lobby"]["queueId"] == 450


@pytest.mark.asyncio
async def test_aram_champ_select_bench_swap(mock_app_and_client):
    """Verify ARAM champ select exposes a bench and swapping replaces the assigned champion."""
    app, client, hub = mock_app_and_client

    await hub.mock_server.trigger_lobby(queue_id=450)
    await hub.mock_server.trigger_champ_select(queue_id=450)
    await hub.mock_server.open_bench_pool()
    await asyncio.sleep(0.05)

    state = (await client.get("/api/state")).json()
    cs = state["champSelect"]
    assert cs["pickMode"] == "BENCH"
    assert cs["benchEnabled"] is True
    assert cs["bans"]["myTeamBans"] == []
    assert cs["isMyTurn"] is False

    me = next(m for m in cs["myTeam"] if m["isLocalPlayer"])
    assigned_champion = me["championId"]
    assert assigned_champion > 0

    bench_target = cs["bench"][0]["championId"]
    assert bench_target != assigned_champion

    # Swap into a bench champion
    res_swap = await client.post("/api/champ-select/bench-swap", json={"championId": bench_target})
    assert res_swap.status_code == 200
    assert res_swap.json()["success"] is True
    await asyncio.sleep(0.05)

    cs2 = (await client.get("/api/state")).json()["champSelect"]
    me2 = next(m for m in cs2["myTeam"] if m["isLocalPlayer"])
    bench_ids = [entry["championId"] for entry in cs2["bench"]]
    assert me2["championId"] == bench_target
    assert bench_target not in bench_ids
    # Previously assigned champion returns to the shared bench
    assert assigned_champion in bench_ids

    # Champions outside the bench cannot be taken
    res_invalid = await client.post("/api/champ-select/bench-swap", json={"championId": 999999})
    assert res_invalid.status_code == 400


@pytest.mark.asyncio
async def test_aram_mayhem_lobby_and_champ_select(mock_app_and_client):
    """Verify creating lobby with queue 2400 (ARAM Mayhem) and entering bench champ select."""
    app, client, hub = mock_app_and_client

    # Create ARAM Mayhem lobby
    res_lobby = await client.post("/api/lobby/create", json={"queueId": 2400})
    assert res_lobby.status_code == 200
    assert res_lobby.json()["success"] is True
    await asyncio.sleep(0.05)

    state_lobby = (await client.get("/api/state")).json()
    assert state_lobby["lobby"]["queueId"] == 2400
    assert "Mayhem" in state_lobby["lobby"]["queueName"]

    # Enter Champ Select, which opens on the card subphase
    await hub.mock_server.trigger_champ_select(queue_id=2400)
    cs = await _wait_for_dealt_cards(client)

    assert cs["pickMode"] == "BENCH"
    assert cs["benchEnabled"] is True
    assert cs["localPickCompleted"] is False
    assert cs["myTeam"][0]["championId"] == 0, "no champion is assigned until a card is claimed"
    assert cs["bans"]["myTeamBans"] == []

    # Once the cards close, the shared pool takes over
    await hub.mock_server.open_bench_pool()
    await asyncio.sleep(0.05)

    cs_pool = (await client.get("/api/state")).json()["champSelect"]
    assert cs_pool["localPickCompleted"] is True
    assert cs_pool["myTeam"][0]["championId"] > 0
    assert len(cs_pool["bench"]) > 0


async def _wait_for_dealt_cards(client, timeout: float = 2.0) -> dict:
    """Wait for the cards fetched behind the REST route to reach the normalized state."""
    deadline = timeout
    cs = {}
    while deadline > 0:
        await asyncio.sleep(0.05)
        deadline -= 0.05
        cs = (await client.get("/api/state")).json()["champSelect"]
        if any(entry["isPriority"] for entry in cs["bench"]):
            return cs
    return cs


@pytest.mark.asyncio
async def test_card_selection_pick_claims_the_card(mock_app_and_client):
    """Tapping a dealt card must claim it, which the bench swap endpoint cannot do yet."""
    app, client, hub = mock_app_and_client

    await hub.mock_server.trigger_lobby(queue_id=2400)
    await hub.mock_server.trigger_champ_select(queue_id=2400)
    cs = await _wait_for_dealt_cards(client)

    card = hub.mock_server.subset_champion_ids[0]
    assert card in [entry["championId"] for entry in cs["bench"]]

    res = await client.post("/api/champ-select/bench-swap", json={"championId": card})
    assert res.status_code == 200
    assert res.json()["success"] is True
    await asyncio.sleep(0.05)

    cs2 = (await client.get("/api/state")).json()["champSelect"]
    me = next(m for m in cs2["myTeam"] if m["isLocalPlayer"])
    assert me["championId"] == card
    assert cs2["mySelection"]["selectedChampionId"] == card
    assert cs2["localPickCompleted"] is True
    assert card not in [entry["championId"] for entry in cs2["bench"]], "own champion is not swappable"


@pytest.mark.asyncio
async def test_dealt_cards_survive_further_session_events(mock_app_and_client):
    """The client republishes the whole session every timer tick; the cards must not wash away."""
    app, client, hub = mock_app_and_client

    await hub.mock_server.trigger_lobby(queue_id=2400)
    await hub.mock_server.trigger_champ_select(queue_id=2400)
    await _wait_for_dealt_cards(client)

    # A plain timer tick, exactly as the client sends it
    hub.mock_server.champ_select["timer"]["adjustedTimeLeftInPhase"] = 20.0
    await hub.mock_server.broadcast_event("/lol-champ-select/v1/session", hub.mock_server.champ_select)
    await asyncio.sleep(0.1)

    bench = (await client.get("/api/state")).json()["champSelect"]["bench"]
    dealt = [entry["championId"] for entry in bench if entry["isPriority"]]
    for champion_id in hub.mock_server.subset_champion_ids:
        assert champion_id in dealt, f"card {champion_id} was dropped by a later session event"


@pytest.mark.asyncio
async def test_card_selection_champions_arrive_over_the_websocket(mock_app_and_client):
    """The dealt cards must reach the phone as soon as champ select opens.

    They live behind a REST route the champ select session never carries, and the poll loop
    that used to fetch them is skipped entirely while the LCU WebSocket is healthy.
    """
    app, client, hub = mock_app_and_client

    await hub.mock_server.trigger_lobby(queue_id=2400)
    await hub.mock_server.trigger_champ_select(queue_id=2400)

    # Give the event dispatch and the follow-up fetch a moment, without polling ever running
    for _ in range(40):
        await asyncio.sleep(0.05)
        bench = (await client.get("/api/state")).json()["champSelect"]["bench"]
        if any(entry["isPriority"] for entry in bench):
            break

    assert hub.lcu_ws.is_connected, "the fetch must work while the socket is up, not via polling"

    state = (await client.get("/api/state")).json()
    assert state["phase"] == "CHAMP_SELECT"
    assert state["champSelect"]["pickMode"] == "BENCH"

    bench = state["champSelect"]["bench"]
    dealt = [entry["championId"] for entry in bench if entry["isPriority"]]
    for champion_id in hub.mock_server.subset_champion_ids:
        assert champion_id in dealt, f"card {champion_id} never reached the client"

    # Leaving champ select must not strand the cards in the next session
    await hub.mock_server.trigger_lobby(queue_id=2400)
    await asyncio.sleep(0.2)
    assert (await client.get("/api/state")).json()["champSelect"]["bench"] == []


@pytest.mark.asyncio
async def test_party_member_names_are_resolved_by_puuid(mock_app_and_client):
    """Everyone but the local player arrives nameless, so the hub has to look them up."""
    app, client, hub = mock_app_and_client

    await hub.mock_server.trigger_lobby(queue_id=420)

    members = []
    for _ in range(40):
        await asyncio.sleep(0.05)
        members = (await client.get("/api/state")).json()["lobby"]["members"]
        if len(members) > 1 and members[1]["summonerName"]:
            break

    assert len(members) == 2
    assert members[0]["summonerName"] == "MockSummoner#PBE"
    assert members[1]["isLocalMember"] is False
    assert members[1]["summonerName"] == "MockDuo#LAS", "the party member never got named"
    assert members[1]["profileIconId"] == 4567
