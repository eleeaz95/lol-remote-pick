"""Mock LCU Server: simulates League Client REST API and WebSocket event stream."""

import asyncio
import json
import logging
from typing import Dict, Any, List, Optional, Set
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, status
from fastapi.responses import JSONResponse
import uvicorn

from .lcu_connector import LCUCredentials

logger = logging.getLogger(__name__)

# Sample mock champions
MOCK_CHAMPIONS = [
    {"id": 266, "name": "Aatrox", "alias": "Aatrox", "roles": ["top"], "ownership": {"owned": True}},
    {"id": 103, "name": "Ahri", "alias": "Ahri", "roles": ["middle"], "ownership": {"owned": True}},
    {"id": 84, "name": "Akali", "alias": "Akali", "roles": ["middle", "top"], "ownership": {"owned": True}},
    {"id": 12, "name": "Alistar", "alias": "Alistar", "roles": ["support"], "ownership": {"owned": True}},
    {"id": 222, "name": "Jinx", "alias": "Jinx", "roles": ["bottom"], "ownership": {"owned": True}},
    {"id": 64, "name": "Lee Sin", "alias": "LeeSin", "roles": ["jungle"], "ownership": {"owned": True}},
    {"id": 236, "name": "Lucian", "alias": "Lucian", "roles": ["bottom"], "ownership": {"owned": True}},
    {"id": 99, "name": "Lux", "alias": "Lux", "roles": ["support", "middle"], "ownership": {"owned": True}},
    {"id": 157, "name": "Yasuo", "alias": "Yasuo", "roles": ["middle", "top"], "ownership": {"owned": True}},
    {"id": 238, "name": "Zed", "alias": "Zed", "roles": ["middle"], "ownership": {"owned": True}},
    {"id": 147, "name": "Seraphine", "alias": "Seraphine", "roles": ["support", "middle"], "ownership": {"owned": True}},
    {"id": 412, "name": "Thresh", "alias": "Thresh", "roles": ["support"], "ownership": {"owned": True}},
    {"id": 804, "name": "Yunara", "alias": "Yunara", "roles": ["bottom"], "ownership": {"owned": True}},
    {"id": 800, "name": "Mel", "alias": "Mel", "roles": ["middle", "support"], "ownership": {"owned": True}},
    {"id": 799, "name": "Ambessa", "alias": "Ambessa", "roles": ["top", "middle"], "ownership": {"owned": True}},
    {"id": 893, "name": "Aurora", "alias": "Aurora", "roles": ["middle", "top"], "ownership": {"owned": True}},
    {"id": 901, "name": "Smolder", "alias": "Smolder", "roles": ["bottom"], "ownership": {"owned": True}},
    {"id": 910, "name": "Hwei", "alias": "Hwei", "roles": ["middle", "support"], "ownership": {"owned": True}},
]

# Sample mock summoner spells
MOCK_SPELLS = [
    {"id": 4, "name": "Flash", "description": "Teleports your champion a short distance towards your cursor's location.", "iconPath": "/lol-game-data/assets/v1/summoner-spells/4.png"},
    {"id": 14, "name": "Ignite", "description": "Ignites target enemy champion.", "iconPath": "/lol-game-data/assets/v1/summoner-spells/14.png"},
    {"id": 11, "name": "Smite", "description": "Deals true damage to target epic, large, or medium monster or enemy minion.", "iconPath": "/lol-game-data/assets/v1/summoner-spells/11.png"},
    {"id": 12, "name": "Teleport", "description": "After channeling for 4 seconds, teleports your champion to target allied structure.", "iconPath": "/lol-game-data/assets/v1/summoner-spells/12.png"},
    {"id": 7, "name": "Heal", "description": "Restores health and grants movement speed to you and target allied champion.", "iconPath": "/lol-game-data/assets/v1/summoner-spells/7.png"},
    {"id": 3, "name": "Exhaust", "description": "Exhausts target enemy champion, reducing their Movement Speed and damage.", "iconPath": "/lol-game-data/assets/v1/summoner-spells/3.png"},
    {"id": 6, "name": "Ghost", "description": "Gain increased Movement Speed and ignore unit collision.", "iconPath": "/lol-game-data/assets/v1/summoner-spells/6.png"},
    {"id": 21, "name": "Barrier", "description": "Shields your champion from damage for 2.5 seconds.", "iconPath": "/lol-game-data/assets/v1/summoner-spells/21.png"},
    {"id": 1, "name": "Cleanse", "description": "Removes all disables and summoner spell debuffs affecting your champion.", "iconPath": "/lol-game-data/assets/v1/summoner-spells/1.png"},
]

# Sample mock queues
MOCK_QUEUES = [
    {"id": 420, "name": "Ranked Solo/Duo", "shortName": "Solo/Duo", "description": "5v5 Ranked Solo/Duo on Summoner's Rift", "isRanked": True, "category": "PvP"},
    {"id": 400, "name": "Normal Draft", "shortName": "Draft Pick", "description": "5v5 Normal Draft on Summoner's Rift", "isRanked": False, "category": "PvP"},
    {"id": 440, "name": "Ranked Flex", "shortName": "Flex 5v5", "description": "5v5 Ranked Flex on Summoner's Rift", "isRanked": True, "category": "PvP"},
    {"id": 450, "name": "ARAM", "shortName": "ARAM", "description": "5v5 All Random All Mid on Howling Abyss", "isRanked": False, "category": "PvP"},
]


class MockLCUServer:
    """Mock LCU API and WebSocket server for simulation and offline tests."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8888, auto_progress: bool = True):
        self.host = host
        self.port = port
        self.auto_progress = auto_progress
        self.app = FastAPI(title="Mock LCU Server")

        self._active_connections: Set[WebSocket] = set()
        self._server_task: Optional[asyncio.Task] = None
        self._sim_task: Optional[asyncio.Task] = None
        self._uvicorn_server: Optional[uvicorn.Server] = None

        # State storage
        self.gameflow_phase: str = "None"
        self.summoner: Dict[str, Any] = {
            "accountId": 100000001,
            "displayName": "MockSummoner",
            "gameName": "MockSummoner",
            "tagLine": "PBE",
            "profileIconId": 548,
            "summonerId": 200000001,
            "summonerLevel": 150,
            "puuid": "mock-puuid-0000-1111-2222-333333333333",
        }
        self.lobby: Optional[Dict[str, Any]] = None
        self.queue_search: Optional[Dict[str, Any]] = None
        self.ready_check: Optional[Dict[str, Any]] = None
        self.champ_select: Optional[Dict[str, Any]] = None

        self._setup_routes()

    def get_credentials(self) -> LCUCredentials:
        """Return credentials matching this mock server."""
        return LCUCredentials(
            port=self.port,
            password="mock_auth_token",
            protocol="http",
            pid=99999,
            process_name="MockLeagueClient"
        )

    # --- WebSocket Event Dispatch ---

    async def broadcast_event(self, uri: str, data: Any, event_type: str = "Update") -> None:
        """Broadcast WAMP format event to all connected WebSocket clients."""
        payload = [
            8,
            "OnJsonApiEvent",
            {
                "uri": uri,
                "eventType": event_type,
                "data": data,
            }
        ]
        msg = json.dumps(payload)
        dead = []
        for ws in list(self._active_connections):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._active_connections.discard(ws)

    # --- Route Definitions ---

    def _setup_routes(self) -> None:
        app = self.app

        @app.websocket("/")
        @app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await websocket.accept()
            self._active_connections.add(websocket)
            try:
                while True:
                    text = await websocket.receive_text()
                    # Handle WAMP SUBSCRIBE (e.g. [5, "OnJsonApiEvent"])
                    # Send initial snapshot of events if needed
            except WebSocketDisconnect:
                self._active_connections.discard(websocket)
            except Exception:
                self._active_connections.discard(websocket)

        # Summoner
        @app.get("/lol-summoner/v1/current-summoner")
        async def get_current_summoner():
            return self.summoner

        # Gameflow
        @app.get("/lol-gameflow/v1/gameflow-phase")
        async def get_gameflow_phase():
            return self.gameflow_phase

        @app.get("/lol-gameflow/v1/session")
        async def get_gameflow_session():
            return {
                "phase": self.gameflow_phase,
                "gameData": {"queue": {"id": self.lobby.get("gameConfig", {}).get("queueId", 420) if self.lobby else 0}},
            }

        # Lobby
        @app.get("/lol-lobby/v2/lobby")
        async def get_lobby():
            if not self.lobby:
                raise HTTPException(status_code=404, detail="Lobby does not exist")
            return self.lobby

        @app.post("/lol-lobby/v2/lobby")
        async def create_lobby(body: Dict[str, Any]):
            queue_id = body.get("queueId", 420)
            await self.trigger_lobby(queue_id=queue_id)
            return self.lobby

        @app.delete("/lol-lobby/v2/lobby")
        async def delete_lobby():
            await self.trigger_idle()
            return JSONResponse(status_code=204, content=None)

        @app.put("/lol-lobby/v2/lobby/members/localMember/position-preferences")
        async def set_position_preferences(body: Dict[str, Any]):
            if not self.lobby:
                raise HTTPException(status_code=404, detail="Lobby not found")
            for m in self.lobby.get("members", []):
                if m.get("isLocalMember"):
                    m["firstPositionPreference"] = body.get("firstPreference", "TOP")
                    m["secondPositionPreference"] = body.get("secondPreference", "MIDDLE")
            await self.broadcast_event("/lol-lobby/v2/lobby", self.lobby)
            return {"status": "ok"}

        # Matchmaking
        @app.post("/lol-lobby/v2/lobby/matchmaking/search")
        async def start_queue():
            await self.trigger_queue()
            return JSONResponse(status_code=204, content=None)

        @app.delete("/lol-lobby/v2/lobby/matchmaking/search")
        async def cancel_queue():
            if self.lobby:
                await self.trigger_lobby(self.lobby.get("gameConfig", {}).get("queueId", 420))
            else:
                await self.trigger_idle()
            return JSONResponse(status_code=204, content=None)

        # Ready Check
        @app.get("/lol-matchmaking/v1/ready-check")
        async def get_ready_check():
            if not self.ready_check:
                return {"state": "None", "playerResponse": "None"}
            return self.ready_check

        @app.post("/lol-matchmaking/v1/ready-check/accept")
        async def accept_ready_check():
            if self.ready_check:
                self.ready_check["playerResponse"] = "Accepted"
                self.ready_check["numAccepted"] = min(self.ready_check["totalPlayers"], self.ready_check["numAccepted"] + 1)
                await self.broadcast_event("/lol-matchmaking/v1/ready-check", self.ready_check)
            return JSONResponse(status_code=204, content=None)

        @app.post("/lol-matchmaking/v1/ready-check/declined")
        async def decline_ready_check():
            if self.ready_check:
                self.ready_check["playerResponse"] = "Declined"
                self.ready_check["state"] = "StrangerNotReady"
                await self.broadcast_event("/lol-matchmaking/v1/ready-check", self.ready_check)
                await asyncio.sleep(1)
                if self.lobby:
                    await self.trigger_lobby(self.lobby.get("gameConfig", {}).get("queueId", 420))
                else:
                    await self.trigger_idle()
            return JSONResponse(status_code=204, content=None)

        # Champ Select
        @app.get("/lol-champ-select/v1/session")
        async def get_champ_select_session():
            if not self.champ_select:
                raise HTTPException(status_code=404, detail="Champ select session not active")
            return self.champ_select

        @app.patch("/lol-champ-select/v1/session/actions/{action_id}")
        async def patch_champ_select_action(action_id: int, body: Dict[str, Any]):
            if not self.champ_select:
                raise HTTPException(status_code=404, detail="No champ select session")
            champion_id = body.get("championId", 0)
            completed = body.get("completed", False)

            # Update the action in session
            action_found = False
            for group in self.champ_select.get("actions", []):
                for act in group:
                    if act.get("id") == action_id:
                        act["championId"] = champion_id
                        act["completed"] = completed
                        action_found = True
                        if completed:
                            act["isInProgress"] = False
                            # Add to bans if ban action
                            if act.get("type") == "ban":
                                self.champ_select["bans"]["myTeamBans"].append(champion_id)
                            # Update player champion in team if pick action
                            elif act.get("type") == "pick":
                                for m in self.champ_select.get("myTeam", []):
                                    if m.get("cellId") == act.get("actorCellId"):
                                        m["championId"] = champion_id
                        else:
                            # Hover / Pick intent
                            for m in self.champ_select.get("myTeam", []):
                                if m.get("cellId") == act.get("actorCellId"):
                                    m["championPickIntent"] = champion_id
                if action_found:
                    break

            await self.broadcast_event("/lol-champ-select/v1/session", self.champ_select)
            return JSONResponse(status_code=204, content=None)

        @app.patch("/lol-champ-select/v1/session/my-selection")
        async def patch_my_selection(body: Dict[str, Any]):
            if not self.champ_select:
                raise HTTPException(status_code=404, detail="No champ select session")
            my_sel = self.champ_select.setdefault("mySelection", {})
            if "spell1Id" in body:
                my_sel["spell1Id"] = body["spell1Id"]
            if "spell2Id" in body:
                my_sel["spell2Id"] = body["spell2Id"]
            if "selectedChampionId" in body:
                cid = body["selectedChampionId"]
                my_sel["selectedChampionId"] = cid
                local_cell = self.champ_select.get("localPlayerCellId", 0)
                for m in self.champ_select.get("myTeam", []):
                    if m.get("cellId") == local_cell:
                        m["championPickIntent"] = cid

            # Also update local player in myTeam
            local_cell = self.champ_select.get("localPlayerCellId", 0)
            for m in self.champ_select.get("myTeam", []):
                if m.get("cellId") == local_cell:
                    if "spell1Id" in body:
                        m["spell1Id"] = body["spell1Id"]
                    if "spell2Id" in body:
                        m["spell2Id"] = body["spell2Id"]
            await self.broadcast_event("/lol-champ-select/v1/session", self.champ_select)
            return JSONResponse(status_code=204, content=None)

        # Metadata
        @app.get("/lol-game-queues/v1/queues")
        async def get_queues():
            return MOCK_QUEUES

        @app.get("/lol-champions/v1/owned-champions-minimal")
        async def get_champions():
            return MOCK_CHAMPIONS

        @app.get("/lol-game-data/assets/v1/summoner-spells.json")
        async def get_summoner_spells():
            return MOCK_SPELLS

    # --- Phase State Transitions ---

    async def trigger_idle(self) -> None:
        """Transition to IDLE state."""
        self.gameflow_phase = "None"
        self.lobby = None
        self.queue_search = None
        self.ready_check = None
        self.champ_select = None

        await self.broadcast_event("/lol-gameflow/v1/gameflow-phase", "None")
        await self.broadcast_event("/lol-lobby/v2/lobby", None, event_type="Delete")
        await self.broadcast_event("/lol-matchmaking/v1/search", None, event_type="Delete")
        await self.broadcast_event("/lol-matchmaking/v1/ready-check", None, event_type="Delete")
        await self.broadcast_event("/lol-champ-select/v1/session", None, event_type="Delete")

    async def trigger_lobby(self, queue_id: int = 420) -> None:
        """Transition to LOBBY state."""
        self.gameflow_phase = "Lobby"
        self.queue_search = None
        self.ready_check = None
        self.champ_select = None

        self.lobby = {
            "gameConfig": {
                "queueId": queue_id,
                "isCustom": False,
                "mapId": 11,
            },
            "canStartActivity": True,
            "localMember": {
                "summonerId": self.summoner["summonerId"],
                "summonerName": self.summoner["displayName"],
                "isLeader": True,
                "isLocalMember": True,
                "firstPositionPreference": "TOP",
                "secondPositionPreference": "MIDDLE",
            },
            "members": [
                {
                    "summonerId": self.summoner["summonerId"],
                    "summonerName": self.summoner["displayName"],
                    "isLeader": True,
                    "isLocalMember": True,
                    "firstPositionPreference": "TOP",
                    "secondPositionPreference": "MIDDLE",
                }
            ],
        }

        await self.broadcast_event("/lol-gameflow/v1/gameflow-phase", "Lobby")
        await self.broadcast_event("/lol-lobby/v2/lobby", self.lobby)
        await self.broadcast_event("/lol-matchmaking/v1/search", None, event_type="Delete")
        await self.broadcast_event("/lol-matchmaking/v1/ready-check", None, event_type="Delete")
        await self.broadcast_event("/lol-champ-select/v1/session", None, event_type="Delete")

    async def trigger_queue(self) -> None:
        """Transition to MATCHMAKING queue state."""
        self.gameflow_phase = "Matchmaking"
        self.ready_check = None
        self.champ_select = None

        self.queue_search = {
            "searchState": "Searching",
            "timeInQueue": 0.0,
            "estimatedQueueTime": 35.0,
        }

        await self.broadcast_event("/lol-gameflow/v1/gameflow-phase", "Matchmaking")
        await self.broadcast_event("/lol-matchmaking/v1/search", self.queue_search)

    async def trigger_ready_check(self) -> None:
        """Transition to READY_CHECK state."""
        self.gameflow_phase = "ReadyCheck"
        self.champ_select = None

        self.ready_check = {
            "state": "InProgress",
            "playerResponse": "None",
            "timer": 10.0,
            "timerDuration": 10.0,
            "numAccepted": 0,
            "numDeclined": 0,
            "totalPlayers": 10,
            "maxPlayers": 10,
        }

        await self.broadcast_event("/lol-gameflow/v1/gameflow-phase", "ReadyCheck")
        await self.broadcast_event("/lol-matchmaking/v1/ready-check", self.ready_check)

    async def trigger_champ_select(self) -> None:
        """Transition to CHAMP_SELECT state."""
        self.gameflow_phase = "ChampSelect"
        self.ready_check = None
        self.queue_search = None

        local_cell = 0
        self.champ_select = {
            "localPlayerCellId": local_cell,
            "timer": {
                "phase": "BAN_PICK",
                "adjustedTimeLeftInPhase": 25.0,
                "totalTimeInPhase": 30.0,
            },
            "bans": {
                "myTeamBans": [],
                "theirTeamBans": [238],
            },
            "myTeam": [
                {"cellId": 0, "summonerName": self.summoner["displayName"], "assignedPosition": "top", "championId": 0, "spell1Id": 4, "spell2Id": 12},
                {"cellId": 1, "summonerName": "AlliedJungler", "assignedPosition": "jungle", "championId": 64, "spell1Id": 4, "spell2Id": 11},
                {"cellId": 2, "summonerName": "AlliedMid", "assignedPosition": "middle", "championId": 103, "spell1Id": 4, "spell2Id": 14},
                {"cellId": 3, "summonerName": "AlliedADC", "assignedPosition": "bottom", "championId": 222, "spell1Id": 4, "spell2Id": 7},
                {"cellId": 4, "summonerName": "AlliedSup", "assignedPosition": "support", "championId": 412, "spell1Id": 4, "spell2Id": 3},
            ],
            "theirTeam": [
                {"cellId": 5, "assignedPosition": "top", "championId": 0},
                {"cellId": 6, "assignedPosition": "jungle", "championId": 0},
                {"cellId": 7, "assignedPosition": "middle", "championId": 0},
                {"cellId": 8, "assignedPosition": "bottom", "championId": 0},
                {"cellId": 9, "assignedPosition": "support", "championId": 0},
            ],
            "mySelection": {
                "spell1Id": 4,
                "spell2Id": 12,
                "selectedChampionId": 0,
            },
            "actions": [
                # Ban actions group (Phase 1)
                [
                    {"id": 1, "actorCellId": 0, "championId": 0, "type": "ban", "completed": False, "isInProgress": True, "pickTurn": 1},
                    {"id": 2, "actorCellId": 1, "championId": 0, "type": "ban", "completed": True, "isInProgress": False, "pickTurn": 1},
                    {"id": 3, "actorCellId": 2, "championId": 0, "type": "ban", "completed": True, "isInProgress": False, "pickTurn": 1},
                    {"id": 4, "actorCellId": 3, "championId": 0, "type": "ban", "completed": True, "isInProgress": False, "pickTurn": 1},
                    {"id": 5, "actorCellId": 4, "championId": 0, "type": "ban", "completed": True, "isInProgress": False, "pickTurn": 1},
                ],
                # Pick actions group (Phase 2)
                [
                    {"id": 6, "actorCellId": 0, "championId": 0, "type": "pick", "completed": False, "isInProgress": False, "pickTurn": 2},
                ]
            ]
        }

        await self.broadcast_event("/lol-gameflow/v1/gameflow-phase", "ChampSelect")
        await self.broadcast_event("/lol-champ-select/v1/session", self.champ_select)

    async def advance_to_pick_phase(self) -> None:
        """Advance mock champ select from ban phase to pick phase."""
        if not self.champ_select:
            return

        # Complete ban action
        actions = self.champ_select.get("actions", [])
        if len(actions) >= 1:
            for act in actions[0]:
                if act.get("actorCellId") == 0:
                    act["completed"] = True
                    act["isInProgress"] = False
                    if not act["championId"]:
                        act["championId"] = 84  # Ban Akali by default
                    self.champ_select["bans"]["myTeamBans"].append(act["championId"])

        # Activate pick action
        if len(actions) >= 2:
            for act in actions[1]:
                if act.get("actorCellId") == 0:
                    act["isInProgress"] = True
                    act["completed"] = False

        self.champ_select["timer"]["phase"] = "PICK"
        self.champ_select["timer"]["adjustedTimeLeftInPhase"] = 20.0
        self.champ_select["timer"]["totalTimeInPhase"] = 25.0

        await self.broadcast_event("/lol-champ-select/v1/session", self.champ_select)

    async def advance_to_finalizing_phase(self) -> None:
        """Advance mock champ select to finalizing phase."""
        if not self.champ_select:
            return

        # Complete pick action
        actions = self.champ_select.get("actions", [])
        if len(actions) >= 2:
            for act in actions[1]:
                if act.get("actorCellId") == 0:
                    act["completed"] = True
                    act["isInProgress"] = False
                    if not act["championId"]:
                        act["championId"] = 266  # Pick Aatrox
                    for m in self.champ_select.get("myTeam", []):
                        if m.get("cellId") == 0:
                            m["championId"] = act["championId"]

        self.champ_select["timer"]["phase"] = "FINALIZATION"
        self.champ_select["timer"]["adjustedTimeLeftInPhase"] = 5.0
        self.champ_select["timer"]["totalTimeInPhase"] = 10.0

        await self.broadcast_event("/lol-champ-select/v1/session", self.champ_select)

    async def trigger_in_game(self) -> None:
        """Transition to IN_GAME state."""
        self.gameflow_phase = "InProgress"
        self.champ_select = None

        await self.broadcast_event("/lol-gameflow/v1/gameflow-phase", "InProgress")
        await self.broadcast_event("/lol-champ-select/v1/session", None, event_type="Delete")

    # --- Simulation Auto-Progression Loop ---

    async def _auto_simulation_loop(self) -> None:
        """Runs automated realistic game cycle simulation."""
        logger.info("Mock LCU automated simulation loop started")
        try:
            while True:
                # Start at Lobby
                await self.trigger_lobby(queue_id=420)
                await asyncio.sleep(4.0)

                # Enter Queue
                await self.trigger_queue()
                for q_time in range(1, 6):
                    await asyncio.sleep(1.0)
                    if self.queue_search:
                        self.queue_search["timeInQueue"] = float(q_time)
                        await self.broadcast_event("/lol-matchmaking/v1/search", self.queue_search)

                # Match Found: Ready Check
                await self.trigger_ready_check()
                # Wait 4 seconds then auto accept
                for t in range(10, 5, -1):
                    await asyncio.sleep(1.0)
                    if self.ready_check and self.ready_check["state"] == "InProgress":
                        self.ready_check["timer"] = float(t)
                        self.ready_check["numAccepted"] = min(10, self.ready_check["numAccepted"] + 2)
                        await self.broadcast_event("/lol-matchmaking/v1/ready-check", self.ready_check)

                if self.ready_check:
                    self.ready_check["playerResponse"] = "Accepted"
                    self.ready_check["numAccepted"] = 10
                    self.ready_check["state"] = "EveryoneReady"
                    await self.broadcast_event("/lol-matchmaking/v1/ready-check", self.ready_check)
                await asyncio.sleep(1.5)

                # Champ Select: Ban Phase
                await self.trigger_champ_select()
                for t in range(15, 0, -1):
                    await asyncio.sleep(1.0)
                    if self.champ_select and self.champ_select.get("timer"):
                        self.champ_select["timer"]["adjustedTimeLeftInPhase"] = float(t)
                        await self.broadcast_event("/lol-champ-select/v1/session", self.champ_select)

                # Advance to Pick Phase
                await self.advance_to_pick_phase()
                for t in range(20, 0, -1):
                    await asyncio.sleep(1.0)
                    if self.champ_select and self.champ_select.get("timer"):
                        self.champ_select["timer"]["adjustedTimeLeftInPhase"] = float(t)
                        await self.broadcast_event("/lol-champ-select/v1/session", self.champ_select)

                # Advance to Finalizing
                await self.advance_to_finalizing_phase()
                await asyncio.sleep(4.0)

                # In Game
                await self.trigger_in_game()
                await asyncio.sleep(6.0)

                # Game Ends -> Back to Lobby
                await self.trigger_lobby(queue_id=420)
                await asyncio.sleep(5.0)

        except asyncio.CancelledError:
            logger.info("Mock simulation loop cancelled")
        except Exception as e:
            logger.error(f"Error in mock simulation loop: {e}", exc_info=True)

    # --- Server Lifecycle ---

    async def start(self) -> None:
        """Start the mock uvicorn server and optional simulation loop."""
        config = uvicorn.Config(
            app=self.app,
            host=self.host,
            port=self.port,
            log_level="warning",
            access_log=False,
        )
        self._uvicorn_server = uvicorn.Server(config)
        self._server_task = asyncio.create_task(self._uvicorn_server.serve(), name="mock-lcu-uvicorn")

        # Wait briefly for server to bind
        await asyncio.sleep(0.5)

        if self.auto_progress:
            self._sim_task = asyncio.create_task(self._auto_simulation_loop(), name="mock-lcu-sim")

        logger.info(f"Mock LCU server running at http://{self.host}:{self.port}")

    async def stop(self) -> None:
        """Stop server and simulation loop."""
        if self._sim_task and not self._sim_task.done():
            self._sim_task.cancel()
            try:
                await self._sim_task
            except asyncio.CancelledError:
                pass
            self._sim_task = None

        if self._uvicorn_server:
            self._uvicorn_server.should_exit = True
            if self._server_task:
                await self._server_task
            self._uvicorn_server = None
            self._server_task = None

        logger.info("Mock LCU server stopped")
