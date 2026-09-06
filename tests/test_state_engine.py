"""
Unit tests for StateEngine: verifying state machine transitions,
phase determination, event handling, data normalization, and subscriber broadcasts.
"""

import asyncio
from typing import Any, Dict, List

import pytest

from backend.state_engine import StateEngine


@pytest.mark.asyncio
async def test_state_engine_initial_state():
    """Verify default initial state of the engine."""
    engine = StateEngine()
    state = engine.get_state()

    assert state["connected"] is False
    assert state["phase"] == "DISCONNECTED"
    assert state["summoner"]["displayName"] == ""
    assert state["lobby"]["members"] == []
    assert state["queue"]["inQueue"] is False
    assert state["readyCheck"]["state"] == "None"
    assert state["champSelect"]["sessionActive"] is False


@pytest.mark.asyncio
async def test_state_engine_subscription_and_broadcast():
    """Verify listener registration, state change notification, and unsubscription."""
    engine = StateEngine()
    notifications: List[Dict[str, Any]] = []

    async def listener(state: Dict[str, Any]):
        notifications.append(state)

    engine.subscribe(listener)

    # Trigger connection update
    engine.set_connected(True)
    await asyncio.sleep(0.05)

    assert len(notifications) >= 1
    assert notifications[-1]["connected"] is True
    assert notifications[-1]["phase"] == "NONE"

    # Unsubscribe
    engine.unsubscribe(listener)
    count_before = len(notifications)

    engine.set_connected(False)
    await asyncio.sleep(0.05)

    # Should not have received further updates
    assert len(notifications) == count_before


@pytest.mark.asyncio
async def test_state_engine_summoner_event():
    """Verify summoner profile event normalization."""
    engine = StateEngine()
    engine.set_connected(True)

    summoner_data = {
        "displayName": "Faker",
        "gameName": "Hide on bush",
        "tagLine": "KR1",
        "profileIconId": 6,
        "summonerLevel": 500,
        "summonerId": 12345678,
    }

    await engine.handle_lcu_event("/lol-summoner/v1/current-summoner", summoner_data)
    state = engine.get_state()

    assert "Faker" in state["summoner"]["displayName"]
    assert state["summoner"]["profileIconId"] == 6
    assert state["summoner"]["summonerLevel"] == 500


@pytest.mark.asyncio
async def test_state_engine_lobby_transitions():
    """Verify transitions into and out of Lobby with member details."""
    engine = StateEngine()
    engine.set_connected(True)

    # Create Lobby Event
    lobby_data = {
        "gameConfig": {
            "queueId": 420,
            "isCustom": False,
        },
        "localMember": {
            "isLeader": True,
            "summonerName": "Faker",
            "firstPositionPreference": "MIDDLE",
            "secondPositionPreference": "TOP",
        },
        "members": [
            {
                "summonerId": 12345678,
                "summonerName": "Faker",
                "isLeader": True,
                "firstPositionPreference": "MIDDLE",
                "secondPositionPreference": "TOP",
            },
            {
                "summonerId": 87654321,
                "summonerName": "Oner",
                "isLeader": False,
                "firstPositionPreference": "JUNGLE",
                "secondPositionPreference": "FILL",
            },
        ],
    }

    await engine.handle_lcu_event("/lol-gameflow/v1/gameflow-phase", "Lobby")
    await engine.handle_lcu_event("/lol-lobby/v2/lobby", lobby_data)

    state = engine.get_state()
    assert state["phase"] == "LOBBY"
    assert state["lobby"]["queueId"] == 420
    assert state["lobby"]["isLeader"] is True
    assert state["lobby"]["canStartQueue"] is True
    assert len(state["lobby"]["members"]) == 2
    assert state["lobby"]["members"][0]["summonerName"] == "Faker"
    assert state["lobby"]["members"][1]["firstPositionPreference"] == "JUNGLE"


@pytest.mark.asyncio
async def test_state_engine_matchmaking_queue_transition():
    """Verify Matchmaking queue timer and estimation."""
    engine = StateEngine()
    engine.set_connected(True)

    await engine.handle_lcu_event("/lol-gameflow/v1/gameflow-phase", "Matchmaking")
    search_data = {
        "timeInQueue": 45.2,
        "estimatedQueueTime": 120.0,
        "searchState": "Searching",
    }
    await engine.handle_lcu_event("/lol-lobby/v2/lobby/matchmaking/search-state", search_data)

    state = engine.get_state()
    assert state["phase"] == "IN_QUEUE"
    assert state["queue"]["inQueue"] is True
    assert state["queue"]["timeInQueue"] == 45.2
    assert state["queue"]["estimatedTime"] == 120.0


@pytest.mark.asyncio
async def test_state_engine_ready_check_states():
    """Verify ReadyCheck detection, player responses, and player counts."""
    engine = StateEngine()
    engine.set_connected(True)

    ready_data = {
        "state": "InProgress",
        "playerResponse": "None",
        "timer": 10.0,
        "dodgeWarning": "None",
        "numPossibleDeclines": 1,
        "declinerName": "",
    }

    await engine.handle_lcu_event("/lol-gameflow/v1/gameflow-phase", "ReadyCheck")
    await engine.handle_lcu_event("/lol-matchmaking/v1/ready-check", ready_data)

    state = engine.get_state()
    assert state["phase"] == "READY_CHECK"
    assert state["readyCheck"]["state"] == "InProgress"
    assert state["readyCheck"]["playerResponse"] == "None"
    assert state["readyCheck"]["timer"] == 10.0

    # Simulate player accepting
    ready_data_accepted = dict(ready_data)
    ready_data_accepted["playerResponse"] = "Accepted"
    await engine.handle_lcu_event("/lol-matchmaking/v1/ready-check", ready_data_accepted)

    state2 = engine.get_state()
    assert state2["readyCheck"]["playerResponse"] == "Accepted"


@pytest.mark.asyncio
async def test_state_engine_champ_select_full_flow():
    """Verify Champion Select phases: BAN, PICK, FINALIZING, turns, spells, and team rosters."""
    engine = StateEngine()
    engine.set_connected(True)

    # 1. Enter ChampSelect in Ban Phase
    champ_select_data = {
        "localPlayerCellId": 0,
        "bans": {
            "myTeamBans": [266],  # Aatrox
            "theirTeamBans": [103],  # Ahri
            "numBans": 2,
        },
        "myTeam": [
            {
                "cellId": 0,
                "summonerId": 12345678,
                "assignedPosition": "middle",
                "championId": 0,
                "spell1Id": 4,  # Flash
                "spell2Id": 14,  # Ignite
            },
            {
                "cellId": 1,
                "summonerId": 87654321,
                "assignedPosition": "jungle",
                "championId": 64,  # Lee Sin
                "spell1Id": 4,
                "spell2Id": 11,
            },
        ],
        "theirTeam": [
            {
                "cellId": 5,
                "assignedPosition": "middle",
                "championId": 0,
            }
        ],
        "actions": [
            [
                {
                    "id": 1,
                    "actorCellId": 0,
                    "championId": 0,
                    "type": "ban",
                    "isInProgress": True,
                    "completed": False,
                }
            ],
            [
                {
                    "id": 2,
                    "actorCellId": 0,
                    "championId": 0,
                    "type": "pick",
                    "isInProgress": False,
                    "completed": False,
                }
            ],
        ],
        "timer": {
            "phase": "BAN_PICK",
            "adjustedTimeLeftInPhase": 25.0,
            "totalTimeInPhase": 30.0,
        },
    }

    await engine.handle_lcu_event("/lol-gameflow/v1/gameflow-phase", "ChampSelect")
    await engine.handle_lcu_event("/lol-champ-select/v1/session", champ_select_data)

    state = engine.get_state()
    assert state["phase"] == "CHAMP_SELECT"
    assert state["champSelect"]["sessionActive"] is True
    assert state["champSelect"]["cellId"] == 0
    assert state["champSelect"]["isMyTurn"] is True
    assert state["champSelect"]["actionPhase"] == "BAN"
    assert state["champSelect"]["activeAction"]["id"] == 1
    assert state["champSelect"]["activeAction"]["type"].upper() == "BAN"
    assert state["champSelect"]["bans"]["myTeamBans"] == [266]
    assert state["champSelect"]["bans"]["theirTeamBans"] == [103]
    assert len(state["champSelect"]["myTeam"]) == 2
    assert state["champSelect"]["myTeam"][0]["isLocalPlayer"] is True
    assert state["champSelect"]["localPickActionId"] == 2
    assert state["champSelect"]["localBanActionId"] == 1

    # Simulate Pre-selection / Pick intent (hovering Yunara 804 while banning)
    champ_select_data["myTeam"][0]["championPickIntent"] = 804
    await engine.handle_lcu_event("/lol-champ-select/v1/session", champ_select_data)
    state_intent = engine.get_state()
    assert state_intent["champSelect"]["myPickIntent"] == 804
    assert state_intent["champSelect"]["myTeam"][0]["championPickIntent"] == 804
    assert state_intent["champSelect"]["myTeam"][0]["isPickIntent"] is True
    assert state_intent["champSelect"]["myTeam"][0]["isLocked"] is False
    assert state_intent["champSelect"]["myTeam"][0]["displayedChampionId"] == 804

    # 2. Complete Ban and transition to Pick Phase
    champ_select_data["actions"][0][0]["completed"] = True
    champ_select_data["actions"][0][0]["isInProgress"] = False
    champ_select_data["actions"][0][0]["championId"] = 266

    champ_select_data["actions"][1][0]["isInProgress"] = True
    champ_select_data["actions"][1][0]["championId"] = 157  # Hover Yasuo

    await engine.handle_lcu_event("/lol-champ-select/v1/session", champ_select_data)

    state2 = engine.get_state()
    assert state2["champSelect"]["actionPhase"] == "PICK"
    assert state2["champSelect"]["isMyTurn"] is True
    assert state2["champSelect"]["activeAction"]["type"].upper() == "PICK"
    assert state2["champSelect"]["activeAction"]["championId"] == 157

    # 3. Update my selection (spells & lock)
    my_selection_data = {
        "spell1Id": 4,  # Flash
        "spell2Id": 12,  # Teleport
        "selectedChampionId": 157,
    }
    await engine.handle_lcu_event("/lol-champ-select/v1/session/my-selection", my_selection_data)

    state3 = engine.get_state()
    assert state3["champSelect"]["mySelection"]["spell1Id"] == 4
    assert state3["champSelect"]["mySelection"]["spell2Id"] == 12
    assert state3["champSelect"]["mySelection"]["selectedChampionId"] == 157


@pytest.mark.asyncio
async def test_state_engine_in_game_and_end():
    """Verify transition to IN_GAME and post-game reset."""
    engine = StateEngine()
    engine.set_connected(True)

    await engine.handle_lcu_event("/lol-gameflow/v1/gameflow-phase", "InProgress")
    state = engine.get_state()
    assert state["phase"] == "IN_GAME"

    # Game completes -> WaitingForStats or None
    await engine.handle_lcu_event("/lol-gameflow/v1/gameflow-phase", "None")
    state2 = engine.get_state()
    assert state2["phase"] == "NONE"
    assert state2["champSelect"]["sessionActive"] is False


@pytest.mark.asyncio
async def test_state_engine_connection_debouncing():
    """Verify StateEngine debounces disconnect calls to avoid rapid flickering."""
    engine = StateEngine(disconnect_debounce_delay=0.15)
    engine.set_connected(True)
    assert engine.get_state()["connected"] is True

    # Trigger debounced disconnect
    engine.set_connected(False)
    # Still connected during debounce delay
    assert engine.get_state()["connected"] is True
    await asyncio.sleep(0.05)
    assert engine.get_state()["connected"] is True

    # Reconnect during debounce window cancels disconnection
    engine.set_connected(True)
    await asyncio.sleep(0.15)
    assert engine.get_state()["connected"] is True

    # Immediate disconnect flips immediately
    engine.set_connected(False, immediate=True)
    assert engine.get_state()["connected"] is False


@pytest.mark.asyncio
async def test_state_engine_smooth_lobby_recreation():
    """Verify StateEngine holds LOBBY phase during game mode recreation grace period."""
    engine = StateEngine(lobby_grace_delay=0.15)
    engine.set_connected(True)

    # 1. Enter Lobby with Draft (400)
    await engine.handle_lcu_event("/lol-gameflow/v1/gameflow-phase", "Lobby")
    await engine.handle_lcu_event(
        "/lol-lobby/v2/lobby",
        {
            "gameConfig": {"queueId": 400},
            "members": [{"summonerName": "Player1", "isLeader": True, "isLocalMember": True}],
        },
    )
    state1 = engine.get_state()
    assert state1["phase"] == "LOBBY"
    assert state1["lobby"]["queueId"] == 400

    # 2. LCU Client deletes old lobby during mode switch
    await engine.handle_lcu_event("/lol-lobby/v2/lobby", None, event_type="Delete")
    # During grace period, phase remains LOBBY rather than flickering to NONE
    state_transient = engine.get_state()
    assert state_transient["phase"] == "LOBBY"
    assert state_transient["lobby"]["queueId"] == 400

    # 3. New lobby arrives within grace window (e.g. ARAM 450)
    await engine.handle_lcu_event(
        "/lol-lobby/v2/lobby",
        {
            "gameConfig": {"queueId": 450},
            "members": [{"summonerName": "Player1", "isLeader": True, "isLocalMember": True}],
        },
    )
    state2 = engine.get_state()
    assert state2["phase"] == "LOBBY"
    assert state2["lobby"]["queueId"] == 450

    # 4. Explicit leave to main menu (phase None) clears lobby immediately
    await engine.handle_lcu_event("/lol-gameflow/v1/gameflow-phase", "None")
    state_none = engine.get_state()
    assert state_none["phase"] == "NONE"
    assert state_none["lobby"]["members"] == []


@pytest.mark.asyncio
async def test_state_engine_server_time_and_emission_deduplication():
    """Verify serverTime is attached and redundant state emissions are deduplicated."""

    engine = StateEngine()
    engine.set_connected(True)

    emissions = []

    async def on_change(state):
        emissions.append(state)

    engine.subscribe(on_change)

    # Initial state should have serverTime
    st = engine.get_state()
    assert "serverTime" in st
    assert isinstance(st["serverTime"], (int, float))
    assert st["serverTime"] > 0

    # 1. Update with initial summoner data -> should trigger emission
    await engine.handle_lcu_event(
        "/lol-summoner/v1/current-summoner",
        {
            "displayName": "Hide on bush",
            "summonerId": 999,
            "profileIconId": 1,
            "summonerLevel": 100,
        },
    )
    await asyncio.sleep(0.05)
    assert len(emissions) == 1
    assert emissions[0]["summoner"]["displayName"] == "Hide on bush"
    assert "serverTime" in emissions[0]

    # 2. Update with identical summoner data -> deduplicated, no new emission!
    await engine.handle_lcu_event(
        "/lol-summoner/v1/current-summoner",
        {
            "displayName": "Hide on bush",
            "summonerId": 999,
            "profileIconId": 1,
            "summonerLevel": 100,
        },
    )
    await asyncio.sleep(0.05)
    assert len(emissions) == 1

    # 3. Update with new summoner data -> triggers emission
    await engine.handle_lcu_event(
        "/lol-summoner/v1/current-summoner",
        {
            "displayName": "T1 Faker",
            "summonerId": 999,
            "profileIconId": 6,
            "summonerLevel": 500,
        },
    )
    await asyncio.sleep(0.05)
    assert len(emissions) == 2
    assert emissions[1]["summoner"]["displayName"] == "T1 Faker"

    # 4. update_from_poll with identical data -> deduplicated!
    engine.update_from_poll(
        summoner={
            "displayName": "T1 Faker",
            "summonerId": 999,
            "profileIconId": 6,
            "summonerLevel": 500,
        }
    )
    await asyncio.sleep(0.05)
    assert len(emissions) == 2


@pytest.mark.asyncio
async def test_state_engine_bench_mode_champ_select():
    """Verify ARAM-like sessions expose BENCH pick mode and a normalized shared bench."""
    engine = StateEngine()
    engine.set_connected(True)

    await engine.handle_lcu_event("/lol-gameflow/v1/gameflow-phase", "ChampSelect")
    await engine.handle_lcu_event(
        "/lol-champ-select/v1/session",
        {
            "localPlayerCellId": 0,
            "benchEnabled": True,
            "benchChampions": [
                {"championId": 22, "isPriority": True},
                {"championId": 51, "isPriority": False},
                {"championId": 0, "isPriority": False},
            ],
            "bans": {"myTeamBans": [], "theirTeamBans": []},
            "myTeam": [
                {"cellId": 0, "championId": 32, "spell1Id": 4, "spell2Id": 32},
                {"cellId": 1, "championId": 64, "spell1Id": 4, "spell2Id": 32},
            ],
            "theirTeam": [{"cellId": 5, "championId": 0}],
            "mySelection": {"spell1Id": 4, "spell2Id": 32, "selectedChampionId": 32},
            "actions": [
                [
                    {
                        "id": 1,
                        "actorCellId": 0,
                        "championId": 32,
                        "type": "pick",
                        "isInProgress": False,
                        "completed": True,
                    }
                ]
            ],
        },
    )

    cs = engine.get_state()["champSelect"]
    assert cs["pickMode"] == "BENCH"
    assert cs["benchEnabled"] is True
    # Invalid ids dropped, priority flag preserved
    assert cs["bench"] == [
        {"championId": 22, "isPriority": True},
        {"championId": 51, "isPriority": False},
    ]
    # No ban phase and no turn to act in bench modes
    assert cs["isMyTurn"] is False
    assert cs["bans"]["myTeamBans"] == []


@pytest.mark.asyncio
async def test_state_engine_bench_mode_inferred_from_aram_queue():
    """Verify ARAM queues fall back to BENCH mode before the bench is populated."""
    engine = StateEngine()
    engine.set_connected(True)

    await engine.handle_lcu_event(
        "/lol-lobby/v2/lobby",
        {
            "gameConfig": {"queueId": 450, "gameMode": "ARAM"},
            "members": [],
            "localMember": {"isLeader": True},
        },
    )
    await engine.handle_lcu_event("/lol-gameflow/v1/gameflow-phase", "ChampSelect")
    await engine.handle_lcu_event(
        "/lol-champ-select/v1/session",
        {
            "localPlayerCellId": 0,
            "myTeam": [{"cellId": 0, "championId": 32}],
            "theirTeam": [],
            "actions": [],
        },
    )

    cs = engine.get_state()["champSelect"]
    assert cs["pickMode"] == "BENCH"
    assert cs["bench"] == []


@pytest.mark.asyncio
async def test_state_engine_draft_queue_keeps_draft_pick_mode():
    """Verify draft queues are never treated as bench modes."""
    engine = StateEngine()
    engine.set_connected(True)

    await engine.handle_lcu_event(
        "/lol-lobby/v2/lobby",
        {
            "gameConfig": {"queueId": 420, "gameMode": "CLASSIC"},
            "members": [],
            "localMember": {"isLeader": True},
        },
    )
    await engine.handle_lcu_event("/lol-gameflow/v1/gameflow-phase", "ChampSelect")
    await engine.handle_lcu_event(
        "/lol-champ-select/v1/session",
        {
            "localPlayerCellId": 0,
            "myTeam": [{"cellId": 0, "championId": 0}],
            "theirTeam": [],
            "actions": [
                [{"id": 1, "actorCellId": 0, "championId": 0, "type": "ban", "isInProgress": True, "completed": False}]
            ],
        },
    )

    cs = engine.get_state()["champSelect"]
    assert cs["pickMode"] == "DRAFT"
    assert cs["benchEnabled"] is False
    assert cs["actionPhase"] == "BAN"


@pytest.mark.asyncio
async def test_state_engine_aram_normal_with_bench_enabled_false():
    """Verify normal ARAM (450) is still BENCH pickMode even if LCU session sends benchEnabled: False."""
    engine = StateEngine()
    engine.set_connected(True)

    await engine.handle_lcu_event(
        "/lol-lobby/v2/lobby",
        {
            "gameConfig": {"queueId": 450, "gameMode": "ARAM"},
            "members": [],
            "localMember": {"isLeader": True},
        },
    )
    # Lobby deleted when entering champ select
    await engine.handle_lcu_event("/lol-gameflow/v1/gameflow-phase", "ChampSelect")
    await engine.handle_lcu_event("/lol-lobby/v2/lobby", None, event_type="Delete")
    await engine.handle_lcu_event(
        "/lol-champ-select/v1/session",
        {
            "localPlayerCellId": 0,
            "benchEnabled": False,
            "benchChampions": [],
            "myTeam": [{"cellId": 0, "championId": 32}],
            "theirTeam": [],
            "actions": [],
        },
    )

    cs = engine.get_state()["champSelect"]
    assert cs["pickMode"] == "BENCH"
    assert cs["benchEnabled"] is True
    assert cs["isMyTurn"] is False


@pytest.mark.asyncio
async def test_state_engine_aram_mayhem_queue_2400():
    """Verify ARAM: Mayhem (queue 2400, mode KIWI) is recognized as BENCH mode."""
    engine = StateEngine()
    engine.set_connected(True)

    await engine.handle_lcu_event(
        "/lol-lobby/v2/lobby",
        {
            "gameConfig": {"queueId": 2400, "gameMode": "KIWI"},
            "members": [],
            "localMember": {"isLeader": True},
        },
    )
    await engine.handle_lcu_event("/lol-gameflow/v1/gameflow-phase", "ChampSelect")
    await engine.handle_lcu_event(
        "/lol-champ-select/v1/session",
        {
            "localPlayerCellId": 0,
            "benchEnabled": True,
            "benchChampions": [
                {"championId": 22, "isPriority": True},
                {"championId": 141, "isPriority": True},
                {"championId": 51, "isPriority": False},
            ],
            "myTeam": [{"cellId": 0, "championId": 32}],
            "theirTeam": [],
            "actions": [],
        },
    )

    cs = engine.get_state()["champSelect"]
    assert cs["pickMode"] == "BENCH"
    assert cs["benchEnabled"] is True
    assert len(cs["bench"]) == 3
    assert cs["bench"][0]["championId"] == 22
    assert cs["bench"][0]["isPriority"] is True


async def test_state_engine_reports_missing_summoner_until_fetched():
    """has_summoner() gates the poll-loop retry that recovers a profile fetched too early."""
    engine = StateEngine()
    engine.set_connected(True)

    assert engine.has_summoner() is False
    state = engine.get_state()
    assert state["summoner"]["displayName"] == ""
    assert state["summoner"]["profileIconId"] == 0
    assert state["summoner"]["summonerLevel"] == 1

    engine.update_from_poll(
        summoner={
            "displayName": "",
            "gameName": "Eleeaz",
            "tagLine": "LAS",
            "profileIconId": 3456,
            "summonerLevel": 456,
        }
    )

    assert engine.has_summoner() is True
    state = engine.get_state()
    # Modern clients leave displayName empty and carry the Riot ID in gameName/tagLine
    assert state["summoner"]["displayName"] == "Eleeaz#LAS"
    assert state["summoner"]["profileIconId"] == 3456
    assert state["summoner"]["summonerLevel"] == 456


async def test_state_engine_lobby_member_uses_riot_id_and_icon():
    """Live lobby members carry an empty summonerName and an unused summonerIconId."""
    engine = StateEngine()
    engine.set_connected(True)
    engine.update_from_poll(
        summoner={
            "displayName": "",
            "gameName": "Eleeaz",
            "tagLine": "LAS",
            "summonerId": 833435,
            "puuid": "abc-123",
            "profileIconId": 3456,
            "summonerLevel": 456,
        }
    )

    await engine.handle_lcu_event(
        "/lol-lobby/v2/lobby",
        {
            "gameConfig": {"queueId": 400},
            "members": [
                # Shape taken from a real client: no isLocalMember, empty names, icon under summonerIconId
                {
                    "summonerId": 833435,
                    "puuid": "abc-123",
                    "summonerName": "",
                    "summonerInternalName": "",
                    "summonerIconId": 3456,
                    "summonerLevel": 456,
                    "isLeader": True,
                },
                {"summonerId": 999, "puuid": "def-456", "summonerName": "", "summonerIconId": 12, "isLeader": False},
            ],
        },
    )

    members = engine.get_state()["lobby"]["members"]
    assert members[0]["isLocalMember"] is True
    assert members[0]["summonerName"] == "Eleeaz#LAS"
    assert members[0]["profileIconId"] == 3456
    assert members[0]["summonerLevel"] == 456
    # Other members still get their avatar; naming them needs a puuid lookup the engine cannot do
    assert members[1]["isLocalMember"] is False
    assert members[1]["profileIconId"] == 12


async def test_state_engine_in_game_roster_from_gameflow_session():
    """The live match roster comes from gameData teams, with the local side detected by puuid."""
    engine = StateEngine()
    engine.set_connected(True)
    engine.update_from_poll(summoner={"gameName": "Eleeaz", "tagLine": "LAS", "puuid": "me-1", "summonerId": 833435})

    await engine.handle_lcu_event("/lol-gameflow/v1/gameflow-phase", "InProgress")
    await engine.handle_lcu_event(
        "/lol-gameflow/v1/session",
        {
            "phase": "InProgress",
            "gameData": {
                "queue": {"id": 2400, "name": "ARAM: Mayhem", "gameMode": "KIWI"},
                # Shape taken from a live client: names empty, local player on teamTwo, uneven sides
                "teamOne": [
                    {"championId": 127, "profileIconId": 6484, "selectedPosition": "NONE", "puuid": "enemy-1"},
                    {"championId": 432, "profileIconId": 4649, "selectedPosition": "NONE", "puuid": "enemy-2"},
                ],
                "teamTwo": [
                    {"championId": 11, "profileIconId": 3456, "selectedPosition": "NONE", "puuid": "me-1"},
                    {"championId": 79, "profileIconId": 5602, "selectedPosition": "MIDDLE", "puuid": "ally-1"},
                    {"championId": 904, "profileIconId": 15, "selectedPosition": "NONE", "puuid": "ally-2"},
                ],
            },
        },
    )

    state = engine.get_state()
    assert state["phase"] == "IN_GAME"
    in_game = state["inGame"]
    assert in_game["queueId"] == 2400
    assert in_game["queueName"] == "ARAM: Mayhem"
    # The local player sits on teamTwo, so that side is reported as "mine"
    assert in_game["myChampionId"] == 11
    assert [p["championId"] for p in in_game["myTeam"]] == [11, 79, 904]
    assert [p["championId"] for p in in_game["theirTeam"]] == [127, 432]
    assert in_game["myTeam"][0]["isLocalPlayer"] is True
    assert in_game["myTeam"][1]["isLocalPlayer"] is False
    assert in_game["myTeam"][0]["profileIconId"] == 3456
    # "NONE" is not a position worth showing; a real lane is kept
    assert in_game["myTeam"][0]["position"] == ""
    assert in_game["myTeam"][1]["position"] == "MIDDLE"


async def test_state_engine_in_game_roster_empty_without_session():
    """No gameflow teams means an empty roster rather than a half-filled one."""
    engine = StateEngine()
    engine.set_connected(True)
    await engine.handle_lcu_event("/lol-gameflow/v1/gameflow-phase", "InProgress")

    in_game = engine.get_state()["inGame"]
    assert in_game["myTeam"] == []
    assert in_game["theirTeam"] == []
    assert in_game["myChampionId"] == 0


async def test_state_engine_in_game_roster_cleared_after_the_match():
    """The gameflow session outlives the match, so the roster must not leak into the next lobby."""
    engine = StateEngine()
    engine.set_connected(True)
    engine.update_from_poll(summoner={"gameName": "Eleeaz", "puuid": "me-1"})

    await engine.handle_lcu_event("/lol-gameflow/v1/gameflow-phase", "InProgress")
    await engine.handle_lcu_event(
        "/lol-gameflow/v1/session",
        {
            "phase": "InProgress",
            "gameData": {
                "queue": {"id": 450},
                "teamOne": [{"championId": 11, "puuid": "me-1"}],
                "teamTwo": [{"championId": 24, "puuid": "enemy-1"}],
            },
        },
    )
    assert engine.get_state()["inGame"]["myTeam"] != []

    # Back to a lobby: the client keeps serving the finished match's session
    await engine.handle_lcu_event("/lol-gameflow/v1/gameflow-phase", "Lobby")
    await engine.handle_lcu_event("/lol-lobby/v2/lobby", {"gameConfig": {"queueId": 450}, "members": []})

    state = engine.get_state()
    assert state["phase"] == "LOBBY"
    assert state["inGame"]["myTeam"] == []
    assert state["inGame"]["theirTeam"] == []
