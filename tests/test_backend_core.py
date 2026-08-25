"""Comprehensive tests for backend core modules: connector, client, ws, state engine, and mock LCU."""

import asyncio
import pytest
from pathlib import Path

from backend.config import Settings, get_settings
from backend.lcu_connector import LCUCredentials, LCUConnector
from backend.lcu_client import LCUClient
from backend.lcu_ws import LCUWebSocket
from backend.state_engine import StateEngine
from backend.mock_lcu import MockLCUServer


@pytest.mark.asyncio
async def test_config():
    """Verify settings defaults and config values."""
    settings = get_settings()
    assert settings.host is not None
    assert settings.port == 8000
    assert settings.mock_port == 8888
    assert settings.ddragon_version == "14.20.1"


@pytest.mark.asyncio
async def test_lcu_connector_lockfile_parsing(tmp_path: Path):
    """Verify lockfile parsing from raw format."""
    connector = LCUConnector()
    content = "LeagueClient:12345:51234:some_secret_auth_token:https"
    creds = connector.parse_lockfile_content(content)
    assert creds is not None
    assert creds.port == 51234
    assert creds.password == "some_secret_auth_token"
    assert creds.protocol == "https"
    assert creds.pid == 12345
    assert creds.base_url == "https://127.0.0.1:51234"
    assert creds.ws_url == "wss://127.0.0.1:51234/"
    assert "Basic " in creds.auth_header
    assert creds.auth_tuple == ("riot", "some_secret_auth_token")

    # Test reading from temp file
    lockfile_path = tmp_path / "lockfile"
    lockfile_path.write_text(content, encoding="utf-8")

    creds_from_file = connector.get_credentials_from_lockfile(lockfile_path)
    assert creds_from_file is not None
    assert creds_from_file.port == 51234


@pytest.mark.asyncio
async def test_state_engine_phases_and_normalization():
    """Verify StateEngine normalization logic across various game phases."""
    engine = StateEngine()

    # Initial state when disconnected
    state = engine.get_state()
    assert state["connected"] is False
    assert state["phase"] == "DISCONNECTED"

    # Set connected
    engine.set_connected(True)
    state = engine.get_state()
    assert state["connected"] is True
    assert state["phase"] == "NONE"

    # Event: Summoner
    await engine.handle_lcu_event("/lol-summoner/v1/current-summoner", {
        "displayName": "Faker",
        "summonerId": 123456,
        "profileIconId": 6,
        "summonerLevel": 500,
        "tagLine": "T1",
    })
    state = engine.get_state()
    assert state["summoner"]["displayName"] == "Faker#T1"
    assert state["summoner"]["summonerLevel"] == 500

    # Event: Lobby creation
    await engine.handle_lcu_event("/lol-gameflow/v1/gameflow-phase", "Lobby")
    await engine.handle_lcu_event("/lol-lobby/v2/lobby", {
        "gameConfig": {"queueId": 420},
        "canStartActivity": True,
        "members": [
            {
                "summonerId": 123456,
                "summonerName": "Faker",
                "isLeader": True,
                "isLocalMember": True,
                "firstPositionPreference": "MIDDLE",
                "secondPositionPreference": "FILL",
            }
        ]
    })
    state = engine.get_state()
    assert state["phase"] == "LOBBY"
    assert state["lobby"]["queueId"] == 420
    assert state["lobby"]["queueName"] == "Ranked Solo/Duo"
    assert state["lobby"]["isLeader"] is True
    assert state["lobby"]["canStartQueue"] is True
    assert len(state["lobby"]["members"]) == 1

    # Event: Matchmaking search
    await engine.handle_lcu_event("/lol-gameflow/v1/gameflow-phase", "Matchmaking")
    await engine.handle_lcu_event("/lol-matchmaking/v1/search", {
        "searchState": "Searching",
        "timeInQueue": 14.5,
        "estimatedQueueTime": 45.0,
    })
    state = engine.get_state()
    assert state["phase"] == "IN_QUEUE"
    assert state["queue"]["inQueue"] is True
    assert state["queue"]["timeInQueue"] == 14.5

    # Event: Ready Check
    await engine.handle_lcu_event("/lol-gameflow/v1/gameflow-phase", "ReadyCheck")
    await engine.handle_lcu_event("/lol-matchmaking/v1/ready-check", {
        "state": "InProgress",
        "playerResponse": "None",
        "timer": 9.2,
        "timerDuration": 10.0,
        "numAccepted": 6,
        "numDeclined": 0,
        "maxPlayers": 10,
    })
    state = engine.get_state()
    assert state["phase"] == "READY_CHECK"
    assert state["readyCheck"]["state"] == "InProgress"
    assert state["readyCheck"]["playerResponse"] == "None"
    assert state["readyCheck"]["numAccepted"] == 6

    # Event: Champ Select
    await engine.handle_lcu_event("/lol-gameflow/v1/gameflow-phase", "ChampSelect")
    await engine.handle_lcu_event("/lol-champ-select/v1/session", {
        "localPlayerCellId": 0,
        "timer": {
            "phase": "BAN_PICK",
            "adjustedTimeLeftInPhase": 22000,
            "totalTimeInPhase": 30000,
        },
        "bans": {
            "myTeamBans": [84],
            "theirTeamBans": [238],
        },
        "myTeam": [
            {"cellId": 0, "summonerName": "Faker", "assignedPosition": "middle", "championId": 0, "spell1Id": 4, "spell2Id": 14},
            {"cellId": 1, "summonerName": "Oner", "assignedPosition": "jungle", "championId": 64, "spell1Id": 4, "spell2Id": 11},
        ],
        "theirTeam": [
            {"cellId": 5, "assignedPosition": "middle", "championId": 0},
        ],
        "mySelection": {
            "spell1Id": 4,
            "spell2Id": 14,
            "selectedChampionId": 0,
        },
        "actions": [
            [
                {"id": 1, "actorCellId": 0, "championId": 0, "type": "ban", "completed": False, "isInProgress": True},
            ],
            [
                {"id": 6, "actorCellId": 0, "championId": 0, "type": "pick", "completed": False, "isInProgress": False},
            ]
        ]
    })
    state = engine.get_state()
    assert state["phase"] == "CHAMP_SELECT"
    assert state["champSelect"]["sessionActive"] is True
    assert state["champSelect"]["cellId"] == 0
    assert state["champSelect"]["isMyTurn"] is True
    assert state["champSelect"]["actionPhase"] == "BAN"
    assert state["champSelect"]["activeAction"]["id"] == 1
    assert state["champSelect"]["activeAction"]["type"] == "BAN"
    assert state["champSelect"]["timer"]["adjustedTimeLeftInPhase"] == 22.0
    assert state["champSelect"]["bans"]["myTeamBans"] == [84]
    assert len(state["champSelect"]["myTeam"]) == 2
    assert state["champSelect"]["myTeam"][0]["isLocalPlayer"] is True

    # Event: In Game
    await engine.handle_lcu_event("/lol-gameflow/v1/gameflow-phase", "InProgress")
    await engine.handle_lcu_event("/lol-champ-select/v1/session", None, event_type="Delete")
    state = engine.get_state()
    assert state["phase"] == "IN_GAME"
    assert state["champSelect"]["sessionActive"] is False


@pytest.mark.asyncio
async def test_mock_lcu_server_integration():
    """Verify MockLCUServer REST and WebSocket communication with LCUClient and LCUWebSocket."""
    # Start mock server without auto progress on test port
    mock_server = MockLCUServer(host="127.0.0.1", port=8999, auto_progress=False)
    await mock_server.start()

    creds = mock_server.get_credentials()
    client = LCUClient(credentials=creds)
    engine = StateEngine()

    received_events = []

    async def on_ws_event(uri: str, data: any, event_type: str):
        received_events.append((uri, data))
        await engine.handle_lcu_event(uri, data, event_type)

    ws_client = LCUWebSocket(
        credentials=creds,
        event_callback=on_ws_event,
        connection_callback=lambda conn: engine.set_connected(conn)
    )

    try:
        # Start WS client
        await ws_client.start()
        await asyncio.sleep(0.5)

        assert ws_client.is_connected is True
        assert engine.get_state()["connected"] is True

        # Test REST: get summoner
        sum_data = await client.get_summoner()
        assert sum_data is not None
        assert sum_data["displayName"] == "MockSummoner"

        # Test REST: create lobby
        lobby_res = await client.create_lobby(420)
        assert lobby_res is not None
        assert lobby_res["gameConfig"]["queueId"] == 420

        await asyncio.sleep(0.3)
        state = engine.get_state()
        assert state["phase"] == "LOBBY"
        assert state["lobby"]["queueId"] == 420

        # Test REST: position preferences
        pos_res = await client.set_position_preferences("MIDDLE", "TOP")
        assert pos_res is not None

        # Test REST: start queue
        start_q_ok = await client.start_queue()
        assert start_q_ok is True
        await asyncio.sleep(0.3)
        assert engine.get_state()["phase"] == "IN_QUEUE"

        # Test Mock trigger: Ready check
        await mock_server.trigger_ready_check()
        await asyncio.sleep(0.3)
        assert engine.get_state()["phase"] == "READY_CHECK"

        # Test REST: accept ready check
        accept_ok = await client.accept_ready_check()
        assert accept_ok is True
        rc_data = await client.get_ready_check()
        assert rc_data["playerResponse"] == "Accepted"

        # Test Mock trigger: Champ select
        await mock_server.trigger_champ_select()
        await asyncio.sleep(0.3)
        cs_state = engine.get_state()
        assert cs_state["phase"] == "CHAMP_SELECT"
        assert cs_state["champSelect"]["isMyTurn"] is True
        assert cs_state["champSelect"]["actionPhase"] == "BAN"

        # Test REST: patch action (ban champion 84 Akali)
        ban_ok = await client.patch_champ_select_action(action_id=1, champion_id=84, completed=True)
        assert ban_ok is True

        # Test REST: patch spells
        spells_ok = await client.patch_my_selection(spell1_id=4, spell2_id=14, champion_id=157)
        assert spells_ok is True

        # Advance to pick phase
        await mock_server.advance_to_pick_phase()
        await asyncio.sleep(0.3)
        pick_state = engine.get_state()
        assert pick_state["champSelect"]["actionPhase"] == "PICK"

        # Test REST: get metadata
        queues = await client.get_available_queues()
        assert len(queues) > 0
        champs = await client.get_all_champions()
        assert len(champs) > 0
        spells = await client.get_all_summoner_spells()
        assert len(spells) > 0

    finally:
        await client.close()
        await ws_client.stop()
        await mock_server.stop()


@pytest.mark.asyncio
async def test_lcu_connector_caching_and_is_alive(tmp_path: Path):
    """Verify LCUConnector credential caching, is_alive check, and stat caching."""
    import os
    lockfile = tmp_path / "lockfile"
    current_pid = os.getpid()
    lockfile.write_text(f"LeagueClientUx:{current_pid}:55555:testpassword:https", encoding="utf-8")

    connector = LCUConnector(custom_path=str(lockfile))

    # 1. Initial fetch
    creds1 = connector.get_credentials()
    assert creds1 is not None
    assert creds1.port == 55555
    assert creds1.pid == current_pid
    assert connector.is_alive() is True
    assert connector.is_running() is True

    # 2. Second fetch should return cached credentials without re-reading
    creds2 = connector.get_credentials()
    assert creds2 is creds1

    # 3. Microsecond alive check with PID
    assert connector.is_alive() is True


@pytest.mark.asyncio
async def test_lcu_ws_connection_debouncing():
    """Verify LCUWebSocket connection state debouncing on drops."""
    conn_changes = []

    async def on_conn(connected: bool):
        conn_changes.append(connected)

    ws = LCUWebSocket(
        credentials=LCUCredentials(port=9999, password="pw", pid=123),
        connection_callback=on_conn,
        disconnect_grace_period=0.2,
    )

    # Initially not connected
    assert ws.is_connected is False

    # Connect
    ws._set_connected(True)
    assert ws.is_connected is True
    await asyncio.sleep(0.05)
    assert conn_changes == [True]

    # Transient drop (debounced)
    ws._set_connected(False, immediate=False)
    # Still report connected during grace period
    assert ws.is_connected is True
    await asyncio.sleep(0.05)
    assert conn_changes == [True]

    # Reconnect within grace period cancels debounce
    ws._set_connected(True)
    await asyncio.sleep(0.2)
    assert ws.is_connected is True
    assert conn_changes == [True]

    # Stop triggers immediate disconnect
    await ws.stop()
    assert ws.is_connected is False
    await asyncio.sleep(0.05)
    assert False in conn_changes

@pytest.mark.asyncio
async def test_app_hub_broadcast_deduplication():
    """Verify AppHub.broadcast_state skips sending when state payload is materially unchanged."""
    from backend.server import AppHub
    from unittest.mock import AsyncMock

    settings = Settings(mock_mode=False)
    hub = AppHub(settings)

    # Create mock client websocket
    mock_ws = AsyncMock()
    hub.active_websockets.add(mock_ws)

    # Broadcast initial state
    st1 = {"connected": True, "phase": "LOBBY", "serverTime": 100.0}
    await hub.broadcast_state(st1)
    assert mock_ws.send_text.call_count == 1

    # Broadcast identical state with different timestamp -> deduplicated!
    st2 = {"connected": True, "phase": "LOBBY", "serverTime": 101.5}
    await hub.broadcast_state(st2)
    assert mock_ws.send_text.call_count == 1

    # Broadcast changed state -> sends!
    st3 = {"connected": True, "phase": "IN_QUEUE", "serverTime": 102.0}
    await hub.broadcast_state(st3)
    assert mock_ws.send_text.call_count == 2


@pytest.mark.asyncio
async def test_server_poll_loop_skips_http_when_ws_connected():
    """Verify _lcu_poll_loop skips REST HTTP polling calls when LCU WebSocket is connected."""
    from backend.server import AppHub
    from unittest.mock import AsyncMock, MagicMock

    settings = Settings(mock_mode=False, lcu_poll_interval=0.05)
    hub = AppHub(settings)

    mock_creds = LCUCredentials(port=12345, password="secret", pid=999)
    mock_connector = MagicMock()
    mock_connector.get_credentials.return_value = mock_creds
    mock_connector.is_alive.return_value = True
    hub.lcu_connector = mock_connector

    # Mock client methods
    hub.lcu_client.get_gameflow_phase = AsyncMock(return_value="Lobby")
    hub.lcu_client.get_summoner = AsyncMock(return_value={"displayName": "Test"})
    hub.lcu_client.get_lobby = AsyncMock(return_value={"queueId": 420})
    hub.lcu_client.get_ready_check = AsyncMock(return_value={})
    hub.lcu_client.get_champ_select_session = AsyncMock(return_value={})

    # Start hub running
    hub._is_running = True
    poll_task = asyncio.create_task(hub._lcu_poll_loop())

    # Initial cycle should seed state
    await asyncio.sleep(0.1)
    assert hub.lcu_client.get_gameflow_phase.call_count >= 1
    initial_call_count = hub.lcu_client.get_gameflow_phase.call_count

    # Now simulate LCU WS being connected
    hub.lcu_ws._connected = True

    # Wait across multiple poll intervals
    await asyncio.sleep(0.15)

    # Calls should NOT have increased because HTTP polling is skipped while WS is connected!
    assert hub.lcu_client.get_gameflow_phase.call_count == initial_call_count

    # Cleanup
    hub._is_running = False
    poll_task.cancel()
    try:
        await poll_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_lcu_connector_riot_metadata_discovery(tmp_path: Path, monkeypatch):
    """Verify discovery of League lockfile from Riot Client metadata files."""
    # Create mock ProgramData structure
    mock_program_data = tmp_path / "ProgramData"
    meta_dir = mock_program_data / "Riot Games" / "Metadata" / "league_of_legends.live"
    meta_dir.mkdir(parents=True)

    fake_install_dir = tmp_path / "CustomGames" / "Riot Games" / "League of Legends"
    fake_install_dir.mkdir(parents=True)
    fake_lockfile = fake_install_dir / "lockfile"
    fake_lockfile.write_text("LeagueClient:999:50000:secret:https", encoding="utf-8")

    yaml_content = f'product_install_full_path: "{fake_install_dir.as_posix()}"\n'
    (meta_dir / "league_of_legends.live.product_settings.yaml").write_text(yaml_content, encoding="utf-8")

    monkeypatch.setenv("ProgramData", str(mock_program_data))

    connector = LCUConnector()
    found_lockfile = connector._find_lockfile_from_riot_metadata()
    assert found_lockfile is not None
    assert found_lockfile.is_file()
    assert found_lockfile == fake_lockfile

    creds = connector.get_credentials_from_lockfile(found_lockfile)
    assert creds is not None
    assert creds.port == 50000


@pytest.mark.asyncio
async def test_network_ip_detection_and_qr():
    """Verify get_all_lan_ips, get_best_lan_ip, and generate_svg_qr."""
    from backend.server import get_all_lan_ips, get_best_lan_ip, generate_svg_qr

    all_ips = get_all_lan_ips()
    assert isinstance(all_ips, list)
    assert len(all_ips) >= 1
    for entry in all_ips:
        assert "ip" in entry
        assert "type" in entry
        assert "priority" in entry

    best_ip = get_best_lan_ip()
    assert isinstance(best_ip, str)
    assert len(best_ip.split(".")) == 4

    # Test SVG QR Code generation
    svg = generate_svg_qr("http://192.168.1.100:8000")
    assert isinstance(svg, str)
    assert "<svg" in svg.lower() or svg == ""


@pytest.mark.asyncio
async def test_network_info_endpoint():
    """Verify /api/network-info endpoint response."""
    from httpx import AsyncClient, ASGITransport
    from backend.server import create_app

    app = create_app(Settings(mock_mode=True))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/network-info")
        assert resp.status_code == 200
        data = resp.json()
        assert "primary_ip" in data
        assert "primary_url" in data
        assert "interfaces" in data
        assert isinstance(data["interfaces"], list)


@pytest.mark.asyncio
async def test_frozen_path_resolution(tmp_path: Path, monkeypatch):
    """Verify Settings.get_static_path handles PyInstaller frozen bundles."""
    fake_meipass = tmp_path / "meipass_extracted"
    fake_frontend = fake_meipass / "frontend"
    fake_frontend.mkdir(parents=True)
    (fake_frontend / "index.html").write_text("<html></html>", encoding="utf-8")

    import sys
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(fake_meipass), raising=False)

    s = Settings()
    static_p = s.get_static_path()
    assert static_p == fake_frontend
    assert (static_p / "index.html").is_file()


@pytest.mark.asyncio
async def test_security_path_traversal_blocked(tmp_path: Path):
    """Verify that catch-all static route blocks path traversal attempts outside static_dir."""
    from httpx import AsyncClient, ASGITransport
    from backend.server import create_app

    fake_static = tmp_path / "frontend"
    fake_static.mkdir()
    (fake_static / "index.html").write_text("<h1>App</h1>", encoding="utf-8")
    (fake_static / "style.css").write_text("body {}", encoding="utf-8")

    # Create sensitive file outside static folder
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("SUPER_SECRET_TOKEN", encoding="utf-8")

    app = create_app(Settings(mock_mode=True, static_dir=str(fake_static)))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Valid asset access
        resp_valid = await client.get("/style.css")
        assert resp_valid.status_code == 200
        assert "body {}" in resp_valid.text

        # Traversal attempts should be blocked (404/403) and never return secret content
        resp_traversal = await client.get("/../secret.txt")
        assert "SUPER_SECRET_TOKEN" not in resp_traversal.text

        resp_traversal_encoded = await client.get("/%2e%2e/secret.txt")
        assert "SUPER_SECRET_TOKEN" not in resp_traversal_encoded.text


@pytest.mark.asyncio
async def test_security_cors_policy():
    """Verify CORS policy is secure and does not allow wildcard credentials."""
    from httpx import AsyncClient, ASGITransport
    from backend.server import create_app

    # 1. Wildcard origin -> credentials disabled
    app_wildcard = create_app(Settings(mock_mode=True, cors_origins=["*"]))
    transport = ASGITransport(app=app_wildcard)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.options(
            "/api/state",
            headers={"Origin": "https://malicious-site.com", "Access-Control-Request-Method": "GET"}
        )
        assert resp.headers.get("access-control-allow-credentials") != "true"
