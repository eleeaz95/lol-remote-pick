"""State Engine: maintains normalized state and computes game phases from LCU events."""

import asyncio
import copy
import logging
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

from .champ_data import get_queue_by_id

logger = logging.getLogger(__name__)

StateCallback = Callable[[Dict[str, Any]], Awaitable[None]]

QUEUE_NAMES = {
    0: "Custom Game",
    400: "Normal Draft 5v5",
    420: "Ranked Solo/Duo",
    430: "Normal Blind 5v5",
    440: "Ranked Flex 5v5",
    450: "ARAM 5v5",
    480: "Swiftplay",
    490: "Quickplay",
    700: "Clash",
    830: "Co-op vs AI (Intro)",
    840: "Co-op vs AI (Beginner)",
    850: "Co-op vs AI (Intermediate)",
    900: "URF",
    1020: "One for All",
    1300: "Nexus Blitz",
    1400: "Ultimate Spellbook",
    1700: "Arena (2v2v2v2)",
    1900: "Pick URF",
    2400: "ARAM: Mayhem",
    3270: "ARAM: Mayhem (Custom)",
}

# Queues whose champion select uses random assignment + shared bench instead of pick/ban draft
BENCH_QUEUE_IDS = {450, 720, 721, 2400, 2450, 3220, 3270, 3280}


def _extract_bench(session: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normalize the shared champion bench, accepting object or plain-id LCU payloads."""
    raw = session.get("benchChampions")
    if raw is None:
        raw = session.get("benchChampionIds")

    subset_ids: Set[int] = set()
    raw_subsets = session.get("subsetChampionIds") or []
    for s in raw_subsets:
        try:
            val = int(s)
            if val > 0:
                subset_ids.add(val)
        except (TypeError, ValueError):
            pass

    bench: List[Dict[str, Any]] = []
    seen: Set[int] = set()
    for entry in raw or []:
        if isinstance(entry, dict):
            champion_id = int(entry.get("championId", 0) or 0)
            is_priority = bool(entry.get("isPriority", False)) or (champion_id in subset_ids)
        else:
            try:
                champion_id = int(entry)
            except (TypeError, ValueError):
                continue
            is_priority = champion_id in subset_ids

        if champion_id <= 0 or champion_id in seen:
            continue
        seen.add(champion_id)
        bench.append({"championId": champion_id, "isPriority": is_priority})

    # Ensure all subsetChampionIds are present on the bench as priority cards
    for sid in subset_ids:
        if sid not in seen:
            seen.add(sid)
            bench.append({"championId": sid, "isPriority": True})

    return bench


class StateEngine:
    """Maintains and normalizes the full LoL client state."""

    def __init__(self, disconnect_debounce_delay: float = 0.5, lobby_grace_delay: float = 0.25):
        self._lock = asyncio.Lock()
        self._listeners: List[StateCallback] = []
        self._disconnect_debounce_delay = disconnect_debounce_delay
        self._lobby_grace_delay = lobby_grace_delay

        # Raw internal states
        self._connected: bool = False
        self._gameflow_phase: str = "None"
        self._raw_summoner: Dict[str, Any] = {}
        self._raw_lobby: Optional[Dict[str, Any]] = None
        self._raw_queue: Optional[Dict[str, Any]] = None
        self._raw_ready_check: Optional[Dict[str, Any]] = None
        self._raw_champ_select: Optional[Dict[str, Any]] = None
        self._raw_gameflow_session: Optional[Dict[str, Any]] = None

        # Background timers for smoothing transient events
        self._disconnect_task: Optional[asyncio.Task] = None
        self._active_queue_id: int = 0
        self._active_game_mode: str = ""
        self._active_queue_name: str = ""

        self._lobby_delete_task: Optional[asyncio.Task] = None

        # Cached normalized state & emission deduplication
        self._cached_state: Optional[Dict[str, Any]] = None
        self._last_emitted_state: Optional[Dict[str, Any]] = None

    def subscribe(self, callback: StateCallback) -> None:
        """Register a callback for state changes."""
        if callback not in self._listeners:
            self._listeners.append(callback)

    def unsubscribe(self, callback: StateCallback) -> None:
        """Unregister a state change callback."""
        if callback in self._listeners:
            self._listeners.remove(callback)

    async def _emit_state_change(self) -> None:
        """Notify all listeners with the updated normalized state if materially changed."""
        state = self.get_state()
        comparable = {k: v for k, v in state.items() if k != "serverTime"}
        if self._last_emitted_state == comparable:
            return
        self._last_emitted_state = copy.deepcopy(comparable)

        for cb in list(self._listeners):
            try:
                res = cb(state)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                logger.error(f"Error in state change listener: {e}", exc_info=True)

    def set_connected(self, connected: bool, immediate: bool = False) -> None:
        """Update connection status with debounced disconnect support."""
        if connected:
            if self._disconnect_task and not self._disconnect_task.done():
                self._disconnect_task.cancel()
                self._disconnect_task = None
            if not self._connected:
                self._connected = True
                self._cached_state = None
                asyncio.create_task(self._emit_state_change())
        else:
            if immediate or self._disconnect_debounce_delay <= 0:
                if self._disconnect_task and not self._disconnect_task.done():
                    self._disconnect_task.cancel()
                    self._disconnect_task = None
                if self._connected:
                    self._connected = False
                    self._gameflow_phase = "None"
                    self._raw_lobby = None
                    self._raw_queue = None
                    self._raw_ready_check = None
                    self._raw_champ_select = None
                    self._cached_state = None
                    asyncio.create_task(self._emit_state_change())
            else:
                if self._connected and (self._disconnect_task is None or self._disconnect_task.done()):
                    self._disconnect_task = asyncio.create_task(self._delayed_disconnect())

    async def _delayed_disconnect(self) -> None:
        """Debounce disconnection to filter microsecond polling jitters."""
        try:
            await asyncio.sleep(self._disconnect_debounce_delay)
            async with self._lock:
                self._connected = False
                self._gameflow_phase = "None"
                self._raw_lobby = None
                self._raw_queue = None
                self._raw_ready_check = None
                self._raw_champ_select = None
                self._cached_state = None
            await self._emit_state_change()
        except asyncio.CancelledError:
            pass

    async def _delayed_clear_lobby(self) -> None:
        """Grace period before clearing lobby to allow recreation on mode switch."""
        try:
            await asyncio.sleep(self._lobby_grace_delay)
            async with self._lock:
                self._raw_lobby = None
                self._cached_state = None
            await self._emit_state_change()
        except asyncio.CancelledError:
            pass

    async def handle_lcu_event(self, uri: str, data: Any, event_type: str = "Update") -> None:
        """Process incoming LCU WebSocket event and update internal state."""
        async with self._lock:
            state_changed = False

            if "/lol-summoner/v1/current-summoner" in uri:
                if event_type == "Delete":
                    self._raw_summoner = {}
                elif isinstance(data, dict):
                    self._raw_summoner = data
                state_changed = True

            elif "/lol-gameflow/v1/gameflow-phase" in uri:
                phase_val = data if isinstance(data, str) else "None"
                self._gameflow_phase = phase_val
                # Clear transient states based on new phase
                if phase_val in ("ChampSelect", "InProgress", "GameStart", "None", "Lobby"):
                    self._raw_ready_check = None
                    self._raw_queue = None
                if phase_val in ("None", "Lobby", "InProgress", "GameStart"):
                    self._raw_champ_select = None
                if phase_val == "None":
                    if self._lobby_delete_task and not self._lobby_delete_task.done():
                        self._lobby_delete_task.cancel()
                        self._lobby_delete_task = None
                    self._raw_lobby = None
                    self._active_queue_id = 0
                    self._active_game_mode = ""
                    self._active_queue_name = ""
                state_changed = True
            elif "/lol-gameflow/v1/session" in uri:
                if event_type == "Delete":
                    self._raw_gameflow_session = None
                elif isinstance(data, dict):
                    self._raw_gameflow_session = data
                    phase = data.get("phase")
                    if phase:
                        self._gameflow_phase = phase
                    gdata = data.get("gameData") or {}
                    q = gdata.get("queue") or {}
                    qid = q.get("id") or 0
                    if qid:
                        try:
                            self._active_queue_id = int(qid)
                        except (ValueError, TypeError):
                            pass
                    gmode = q.get("gameMode") or (data.get("map") or {}).get("gameMode") or ""
                    if gmode:
                        self._active_game_mode = str(gmode).upper()
                    qname = q.get("name") or q.get("shortName") or ""
                    if qname:
                        self._active_queue_name = str(qname)
                state_changed = True
            elif (
                "/lol-matchmaking/v1/search" in uri
                or "matchmaking/search" in uri
                or "search-state" in uri
                or "/lobby/matchmaking" in uri
            ):
                if event_type == "Delete":
                    self._raw_queue = None
                elif isinstance(data, dict):
                    self._raw_queue = data
                state_changed = True

            elif "/lol-lobby/v2/lobby" in uri:
                if event_type == "Delete":
                    raw_phase = (self._gameflow_phase or "None").lower()
                    if raw_phase == "lobby":
                        if self._lobby_delete_task and not self._lobby_delete_task.done():
                            self._lobby_delete_task.cancel()
                        self._lobby_delete_task = asyncio.create_task(self._delayed_clear_lobby())
                    else:
                        if self._lobby_delete_task and not self._lobby_delete_task.done():
                            self._lobby_delete_task.cancel()
                            self._lobby_delete_task = None
                        self._raw_lobby = None
                        state_changed = True
                elif isinstance(data, dict):
                    if self._lobby_delete_task and not self._lobby_delete_task.done():
                        self._lobby_delete_task.cancel()
                        self._lobby_delete_task = None
                    self._raw_lobby = data
                    game_config = data.get("gameConfig") or {}
                    qid = game_config.get("queueId") or data.get("queueId") or 0
                    if qid:
                        try:
                            self._active_queue_id = int(qid)
                        except (ValueError, TypeError):
                            pass
                    gmode = game_config.get("gameMode") or ""
                    if gmode:
                        self._active_game_mode = str(gmode).upper()
                    state_changed = True
            elif "/lol-matchmaking/v1/ready-check" in uri:
                if event_type == "Delete":
                    self._raw_ready_check = None
                elif isinstance(data, dict):
                    self._raw_ready_check = data
                state_changed = True
            elif "/lol-champ-select/v1/session/my-selection" in uri or "/my-selection" in uri:
                if isinstance(data, dict):
                    if self._raw_champ_select is None:
                        self._raw_champ_select = {}
                    self._raw_champ_select["mySelection"] = data
                state_changed = True

            elif "/lol-champ-select/v1/session" in uri:
                if event_type == "Delete":
                    self._raw_champ_select = None
                elif isinstance(data, dict):
                    old_my_selection = (
                        self._raw_champ_select.get("mySelection") if isinstance(self._raw_champ_select, dict) else None
                    )
                    self._raw_champ_select = data
                    if old_my_selection and "mySelection" not in data:
                        self._raw_champ_select["mySelection"] = old_my_selection
                state_changed = True
            if state_changed:
                self._cached_state = None

        if state_changed:
            await self._emit_state_change()

    def set_subset_champion_ids(self, champion_ids: List[Any]) -> None:
        """Attach the pickable card list, which only the REST endpoint exposes.

        Card-selection modes deal a few champions before the shared bench exists, and the
        champ select session pushed over the WebSocket does not carry them.
        """
        if not self._raw_champ_select:
            return

        clean = []
        for value in champion_ids or []:
            try:
                champion_id = int(value)
            except (TypeError, ValueError):
                continue
            if champion_id > 0 and champion_id not in clean:
                clean.append(champion_id)

        if self._raw_champ_select.get("subsetChampionIds") == clean:
            return

        self._raw_champ_select["subsetChampionIds"] = clean
        self._cached_state = None
        asyncio.create_task(self._emit_state_change())

    def update_from_poll(
        self,
        summoner: Optional[Dict[str, Any]] = None,
        gameflow_phase: Optional[str] = None,
        phase: Optional[str] = None,
        lobby: Optional[Dict[str, Any]] = None,
        ready_check: Optional[Dict[str, Any]] = None,
        champ_select: Optional[Dict[str, Any]] = None,
        gameflow_session: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Synchronize state from periodic HTTP polling."""
        if summoner is not None:
            self._raw_summoner = summoner
        p = gameflow_phase if gameflow_phase is not None else phase
        if p is not None:
            self._gameflow_phase = p
            if p == "None":
                self._active_queue_id = 0
                self._active_game_mode = ""
                self._active_queue_name = ""
        if lobby is not None:
            if self._lobby_delete_task and not self._lobby_delete_task.done():
                self._lobby_delete_task.cancel()
                self._lobby_delete_task = None
            self._raw_lobby = lobby
            game_config = lobby.get("gameConfig") or {}
            qid = game_config.get("queueId") or lobby.get("queueId") or 0
            if qid:
                try:
                    self._active_queue_id = int(qid)
                except (ValueError, TypeError):
                    pass
            gmode = game_config.get("gameMode") or ""
            if gmode:
                self._active_game_mode = str(gmode).upper()
        if gameflow_session is not None:
            self._raw_gameflow_session = gameflow_session
            gdata = gameflow_session.get("gameData") or {}
            q = gdata.get("queue") or {}
            qid = q.get("id") or 0
            if qid:
                try:
                    self._active_queue_id = int(qid)
                except (ValueError, TypeError):
                    pass
            gmode = q.get("gameMode") or (gameflow_session.get("map") or {}).get("gameMode") or ""
            if gmode:
                self._active_game_mode = str(gmode).upper()
            qname = q.get("name") or q.get("shortName") or ""
            if qname:
                self._active_queue_name = str(qname)
        if ready_check is not None:
            self._raw_ready_check = ready_check
        if champ_select is not None:
            self._raw_champ_select = champ_select

        self._cached_state = None
        asyncio.create_task(self._emit_state_change())

    def get_state(self) -> Dict[str, Any]:
        """Compute and return the normalized root state dictionary."""
        if self._cached_state is not None:
            res = copy.deepcopy(self._cached_state)
            res["serverTime"] = time.time()
            return res
        # 1. Compute Phase
        computed_phase = self._compute_normalized_phase()

        # 2. Normalize Summoner
        summoner = self._normalize_summoner()

        # 3. Normalize Lobby
        lobby = self._normalize_lobby()

        # 4. Normalize Queue
        queue = self._normalize_queue()

        # 5. Normalize Ready Check
        ready_check = self._normalize_ready_check()

        # 6. Normalize Champion Select
        champ_select = self._normalize_champ_select()

        state = {
            "connected": self._connected,
            "phase": computed_phase,
            "summoner": summoner,
            "lobby": lobby,
            "queue": queue,
            "readyCheck": ready_check,
            "champSelect": champ_select,
            "inGame": self._normalize_in_game(),
        }

        self._cached_state = state
        res = copy.deepcopy(state)
        res["serverTime"] = time.time()
        return res

    def _compute_normalized_phase(self) -> str:
        """Determine high-level phase: NONE, LOBBY, IN_QUEUE, READY_CHECK, CHAMP_SELECT, IN_GAME, DISCONNECTED."""
        if not self._connected:
            return "DISCONNECTED"

        raw_phase = (self._gameflow_phase or "None").lower()

        # Check in game first
        if raw_phase in ("inprogress", "gamestart", "reconnect", "waitingforstats", "preendofgame", "endofgame"):
            return "IN_GAME"

        # Check champ select
        if raw_phase == "champselect" or (self._raw_champ_select and self._raw_champ_select.get("timer")):
            return "CHAMP_SELECT"

        # Check ready check
        if raw_phase == "readycheck" or (self._raw_ready_check and self._raw_ready_check.get("state") == "InProgress"):
            return "READY_CHECK"

        # Check queue
        if raw_phase == "matchmaking" or (self._raw_queue and self._raw_queue.get("searchState") == "Searching"):
            return "IN_QUEUE"

        # Check lobby
        if raw_phase == "lobby" or (self._raw_lobby and self._raw_lobby.get("gameConfig")):
            return "LOBBY"

        return "NONE"

    def has_summoner(self) -> bool:
        """True once the summoner profile has been fetched from the client."""
        return bool(self._raw_summoner)

    def _normalize_summoner(self) -> Dict[str, Any]:
        """Normalize summoner profile."""
        if not self._raw_summoner:
            return {
                "displayName": "",
                "profileIconId": 0,
                "summonerLevel": 1,
            }
        display_name = self._raw_summoner.get("displayName") or self._raw_summoner.get("gameName") or ""
        tag_line = self._raw_summoner.get("tagLine")
        if tag_line and "#" not in display_name and display_name:
            display_name = f"{display_name}#{tag_line}"

        return {
            "displayName": display_name,
            "profileIconId": self._raw_summoner.get("profileIconId", 0),
            "summonerLevel": self._raw_summoner.get("summonerLevel", 1),
        }

    def _normalize_lobby(self) -> Dict[str, Any]:
        """Normalize lobby information."""
        if not self._raw_lobby:
            return {
                "queueId": 0,
                "queueName": "None",
                "isLeader": False,
                "canStartQueue": False,
                "hasPositions": True,
                "members": [],
            }

        game_config = self._raw_lobby.get("gameConfig", {})
        queue_id = game_config.get("queueId", self._raw_lobby.get("queueId", 0))
        queue_name = QUEUE_NAMES.get(queue_id, f"Queue {queue_id}")

        members_raw = self._raw_lobby.get("members", [])
        members_normalized = []
        is_local_leader = bool(self._raw_lobby.get("localMember", {}).get("isLeader", False))

        local_sum_id = self._raw_summoner.get("summonerId")
        local_puuid = self._raw_summoner.get("puuid")
        local_display_name = self._normalize_summoner()["displayName"]

        for m in members_raw:
            is_leader = m.get("isLeader", False)
            # Live lobby payloads carry no isLocalMember flag, so identity rests on matching the profile.
            is_local = (
                m.get("isLocalMember", False)
                or bool(local_puuid and m.get("puuid") == local_puuid)
                or bool(local_sum_id and m.get("summonerId") == local_sum_id)
            )
            if is_local and is_leader:
                is_local_leader = True

            first_pref = m.get("firstPositionPreference", "UNSELECTED")
            second_pref = m.get("secondPositionPreference", "UNSELECTED")

            # Riot ID migration left summonerName empty on lobby members, and the payload carries no
            # gameName/tagLine to rebuild it from. The local player is filled in from the fetched profile;
            # naming the others needs a per-puuid lookup, which normalization cannot perform.
            summoner_name = m.get("summonerName") or m.get("summonerInternalName") or ""
            if not summoner_name and is_local:
                summoner_name = local_display_name

            members_normalized.append(
                {
                    "summonerId": m.get("summonerId", 0),
                    "summonerName": summoner_name,
                    "profileIconId": m.get("summonerIconId", 0) or m.get("profileIconId", 0),
                    "summonerLevel": m.get("summonerLevel", 0),
                    "firstPositionPreference": first_pref,
                    "secondPositionPreference": second_pref,
                    "positionPreferences": {
                        "first": first_pref,
                        "second": second_pref,
                    },
                    "isLeader": is_leader,
                    "isLocalMember": is_local,
                }
            )

        can_start = self._raw_lobby.get("canStartActivity", is_local_leader)

        # The client states outright whether the lane picker applies to this lobby, which beats
        # any table we keep: Riot rotates queues, and Swiftplay puts positions on per-champion
        # slots instead. Fall back to the static catalogue only when the field is absent.
        if "showPositionSelector" in game_config:
            has_positions = bool(game_config.get("showPositionSelector"))
        else:
            queue_meta = get_queue_by_id(queue_id) or {}
            has_positions = bool(queue_meta.get("hasPositions", True)) and queue_id not in BENCH_QUEUE_IDS

        return {
            "queueId": queue_id,
            "queueName": queue_name,
            "isLeader": is_local_leader,
            "canStartQueue": can_start,
            "hasPositions": has_positions,
            "members": members_normalized,
        }

    def _normalize_queue(self) -> Dict[str, Any]:
        """Normalize matchmaking queue timer."""
        if not self._raw_queue:
            # Fallback if in matchmaking gameflow phase
            if self._gameflow_phase.lower() == "matchmaking":
                return {
                    "inQueue": True,
                    "timeInQueue": 0.0,
                    "estimatedTime": 0.0,
                }
            return {
                "inQueue": False,
                "timeInQueue": 0.0,
                "estimatedTime": 0.0,
            }

        search_state = self._raw_queue.get("searchState", "")
        in_queue = search_state == "Searching" or self._gameflow_phase.lower() == "matchmaking"
        time_in_queue = float(self._raw_queue.get("timeInQueue", 0.0))
        est_time = float(self._raw_queue.get("estimatedQueueTime", 0.0))

        return {
            "inQueue": in_queue,
            "timeInQueue": time_in_queue,
            "estimatedTime": est_time,
        }

    def _normalize_ready_check(self) -> Dict[str, Any]:
        """Normalize ready check popup info."""
        if not self._raw_ready_check:
            return {
                "state": "None",
                "playerResponse": "None",
                "timer": 0.0,
                "timerMax": 10.0,
                "numAccepted": 0,
                "numDeclined": 0,
                "totalPlayers": 10,
            }

        state = self._raw_ready_check.get("state", "None")
        response = self._raw_ready_check.get("playerResponse", "None")
        timer = float(self._raw_ready_check.get("timer", 0.0))
        timer_max = float(self._raw_ready_check.get("timerDuration", 10.0) or 10.0)
        num_accepted = int(self._raw_ready_check.get("numAccepted", 0))
        num_declined = int(self._raw_ready_check.get("numDeclined", 0))
        total_players = int(self._raw_ready_check.get("maxPlayers", 10) or 10)

        # Some LCU versions provide playerResponse as boolean or Accepted/Declined string
        if response is True:
            response = "Accepted"
        elif response is False:
            response = "Declined"
        elif not response:
            response = "None"

        return {
            "state": state,
            "playerResponse": response,
            "timer": timer,
            "timerMax": timer_max,
            "numAccepted": num_accepted,
            "numDeclined": num_declined,
            "totalPlayers": total_players,
        }

    def _detect_bench_mode(self, session: Dict[str, Any], bench: List[Dict[str, Any]]) -> bool:
        """True when champion select assigns random champions with a shared bench (ARAM, Mayhem, & variants)."""
        # 1. Direct positive indicators
        if session.get("benchEnabled") is True:
            return True
        if bench:
            return True

        # 2. Check active persistent queue
        qid = self._active_queue_id
        if not qid:
            game_config = (self._raw_lobby or {}).get("gameConfig") or {}
            gameflow = self._raw_gameflow_session or {}
            gf_queue = (gameflow.get("gameData") or {}).get("queue") or {}
            qid = game_config.get("queueId") or gf_queue.get("id") or 0

        try:
            queue_id = int(qid)
        except (TypeError, ValueError):
            queue_id = 0

        if queue_id in BENCH_QUEUE_IDS:
            return True

        # 3. Check gameMode or queue name
        gmode = (self._active_game_mode or "").upper()
        if not gmode:
            game_config = (self._raw_lobby or {}).get("gameConfig") or {}
            gameflow = self._raw_gameflow_session or {}
            gf_queue = (gameflow.get("gameData") or {}).get("queue") or {}
            gf_map = gameflow.get("map") or {}
            gmode = str(game_config.get("gameMode") or gf_queue.get("gameMode") or gf_map.get("gameMode") or "").upper()

        qname = (self._active_queue_name or "").upper()
        if not qname:
            gameflow = self._raw_gameflow_session or {}
            gf_queue = (gameflow.get("gameData") or {}).get("queue") or {}
            qname = str(gf_queue.get("name") or gf_queue.get("shortName") or "").upper()

        if gmode.startswith("ARAM") or gmode == "KIWI" or "MAYHEM" in gmode:
            return True
        if "ARAM" in qname or "MAYHEM" in qname:
            return True

        # 4. If session explicitly has ban actions, it's definitely a draft mode
        has_ban_action = False
        for group in session.get("actions", []):
            if isinstance(group, list):
                for act in group:
                    if isinstance(act, dict) and act.get("type", "").upper() == "BAN":
                        has_ban_action = True
                        break

        if has_ban_action:
            return False

        # 5. If no bans and no pick turns (or pre-locked picks), treat as bench mode if on Howling Abyss
        map_id = (self._raw_gameflow_session or {}).get("map", {}).get("id") or 0
        if map_id == 12:  # Howling Abyss
            return True

        return False

    def _normalize_in_game(self) -> Dict[str, Any]:
        """Normalize the live match roster from the gameflow session."""
        empty: Dict[str, Any] = {"queueId": 0, "queueName": "", "myChampionId": 0, "myTeam": [], "theirTeam": []}

        # The gameflow session outlives the match it describes, so the roster is only reported while a
        # game is actually running - otherwise the last match would linger into the next lobby.
        if self._compute_normalized_phase() != "IN_GAME":
            return empty

        game_data = (self._raw_gameflow_session or {}).get("gameData") or {}
        team_one = game_data.get("teamOne") or []
        team_two = game_data.get("teamTwo") or []
        if not team_one and not team_two:
            return empty

        local_puuid = self._raw_summoner.get("puuid")
        local_sum_id = self._raw_summoner.get("summonerId")

        def is_local(player: Dict[str, Any]) -> bool:
            return bool(
                (local_puuid and player.get("puuid") == local_puuid)
                or (local_sum_id and player.get("summonerId") == local_sum_id)
            )

        def normalize(team: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            players = []
            for player in team:
                if not isinstance(player, dict):
                    continue
                try:
                    champion_id = int(player.get("championId") or 0)
                except (TypeError, ValueError):
                    champion_id = 0
                position = str(player.get("selectedPosition") or "").upper()
                players.append(
                    {
                        "championId": champion_id,
                        # Player names are deliberately absent: live payloads leave summonerName empty
                        # since the Riot ID migration, and rebuilding them needs a lookup per puuid.
                        "profileIconId": player.get("profileIconId", 0),
                        "position": "" if position == "NONE" else position,
                        "isLocalPlayer": is_local(player),
                    }
                )
            return players

        side_one, side_two = normalize(team_one), normalize(team_two)
        # Whichever side lists the local player is "mine"; teamOne stands in when the profile has not
        # been fetched yet and nobody can be matched.
        if any(p["isLocalPlayer"] for p in side_two):
            my_team, their_team = side_two, side_one
        else:
            my_team, their_team = side_one, side_two

        queue = game_data.get("queue") or {}
        try:
            queue_id = int(queue.get("id") or self._active_queue_id or 0)
        except (TypeError, ValueError):
            queue_id = 0

        return {
            "queueId": queue_id,
            "queueName": queue.get("name") or QUEUE_NAMES.get(queue_id, ""),
            "myChampionId": next((p["championId"] for p in my_team if p["isLocalPlayer"]), 0),
            "myTeam": my_team,
            "theirTeam": their_team,
        }

    def _normalize_champ_select(self) -> Dict[str, Any]:
        """Normalize champion select session, actions, teams, timer, and turn status."""
        empty_cs = {
            "sessionActive": False,
            "cellId": -1,
            "isMyTurn": False,
            "actionPhase": "NONE",
            "activeAction": None,
            "timer": {
                "phase": "NONE",
                "adjustedTimeLeftInPhase": 0.0,
                "totalTimeInPhase": 0.0,
            },
            "bans": {
                "myTeamBans": [],
                "theirTeamBans": [],
            },
            "myTeam": [],
            "theirTeam": [],
            "mySelection": {
                "spell1Id": 0,
                "spell2Id": 0,
                "selectedChampionId": 0,
            },
            "pickMode": "DRAFT",
            "benchEnabled": False,
            "bench": [],
        }

        if not self._raw_champ_select:
            return empty_cs

        session = self._raw_champ_select
        local_cell_id = session.get("localPlayerCellId", -1)

        # 1. Timer parsing
        timer_raw = session.get("timer", {})
        timer_phase = timer_raw.get("phase", "NONE")
        # Time left might be in milliseconds in LCU
        raw_left = timer_raw.get("adjustedTimeLeftInPhase", 0)
        raw_total = timer_raw.get("totalTimeInPhase", 0)
        time_left = raw_left / 1000.0 if raw_left > 100 else float(raw_left)
        total_time = raw_total / 1000.0 if raw_total > 100 else float(raw_total)

        timer_norm = {
            "phase": timer_phase,
            "adjustedTimeLeftInPhase": max(0.0, time_left),
            "totalTimeInPhase": max(0.0, total_time),
        }

        # 2. Actions & Turn calculation
        actions_matrix = session.get("actions", [])
        is_my_turn = False
        active_action = None
        action_phase = "NONE"
        local_pick_action_id = None
        local_ban_action_id = None

        # Discover all actions and search for local player active action
        for group in actions_matrix:
            if not isinstance(group, list):
                continue
            for action in group:
                if not isinstance(action, dict):
                    continue
                act_type = action.get("type", "").upper()
                is_in_progress = action.get("isInProgress", False)
                is_completed = action.get("completed", False)
                actor_cell = action.get("actorCellId", -1)

                # Track local player action IDs
                if actor_cell == local_cell_id:
                    if act_type == "PICK" and local_pick_action_id is None:
                        local_pick_action_id = action.get("id")
                    elif act_type == "BAN" and local_ban_action_id is None:
                        local_ban_action_id = action.get("id")

                if actor_cell == local_cell_id and is_in_progress and not is_completed:
                    is_my_turn = True
                    active_action = {
                        "id": action.get("id", 0),
                        "type": act_type,
                        "championId": action.get("championId", 0),
                        "completed": is_completed,
                        "isInProgress": True,
                    }
                    action_phase = act_type
        # If not local turn, determine the general phase
        if not is_my_turn:
            has_ban_in_progress = False
            has_pick_in_progress = False

            for group in actions_matrix:
                if not isinstance(group, list):
                    continue
                for action in group:
                    if action.get("isInProgress", False) and not action.get("completed", False):
                        if action.get("type", "").upper() == "BAN":
                            has_ban_in_progress = True
                        elif action.get("type", "").upper() == "PICK":
                            has_pick_in_progress = True

            if has_ban_in_progress:
                action_phase = "BAN"
            elif has_pick_in_progress:
                action_phase = "PICK"
            elif "PLANNING" in timer_phase.upper():
                action_phase = "PLANNING"
            elif "FINAL" in timer_phase.upper():
                action_phase = "FINALIZING"
            else:
                action_phase = "NONE"

        # 3. Bans parsing
        bans_raw = session.get("bans", {})
        my_team_bans = bans_raw.get("myTeamBans", [])
        their_team_bans = bans_raw.get("theirTeamBans", [])

        # 4. My Team parsing
        my_team = []
        local_pick_intent = 0
        for m in session.get("myTeam", []):
            cid = m.get("cellId", -1)
            is_local = cid == local_cell_id
            locked_champ_id = m.get("championId", 0) or 0
            pick_intent_id = m.get("championPickIntent", 0) or 0
            is_locked = bool(locked_champ_id > 0)
            displayed_champ = locked_champ_id if is_locked else pick_intent_id

            if is_local:
                local_pick_intent = pick_intent_id or (0 if is_locked else locked_champ_id)

            my_team.append(
                {
                    "cellId": cid,
                    "summonerName": m.get("summonerName") or m.get("displayName") or f"Player {cid}",
                    "assignedPosition": m.get("assignedPosition", ""),
                    "championId": locked_champ_id,
                    "championPickIntent": pick_intent_id,
                    "displayedChampionId": displayed_champ,
                    "isLocked": is_locked,
                    "isPickIntent": bool(pick_intent_id > 0 and not is_locked),
                    "spell1Id": m.get("spell1Id", 0),
                    "spell2Id": m.get("spell2Id", 0),
                    "isLocalPlayer": is_local,
                }
            )

        # 5. Their Team parsing
        their_team = []
        for m in session.get("theirTeam", []):
            cid = m.get("cellId", -1)
            their_team.append(
                {
                    "cellId": cid,
                    "assignedPosition": m.get("assignedPosition", ""),
                    "championId": m.get("championId", 0),
                }
            )

        # 6. My Selection
        my_selection_raw = session.get("mySelection", {})
        my_selection = {
            "spell1Id": my_selection_raw.get("spell1Id", 0),
            "spell2Id": my_selection_raw.get("spell2Id", 0),
            "selectedChampionId": my_selection_raw.get("selectedChampionId", 0),
        }
        # Fallback to local player in myTeam if mySelection missing spells
        if not my_selection["spell1Id"] or not my_selection["spell2Id"]:
            for tm in my_team:
                if tm["isLocalPlayer"]:
                    if not my_selection["spell1Id"]:
                        my_selection["spell1Id"] = tm["spell1Id"]
                    if not my_selection["spell2Id"]:
                        my_selection["spell2Id"] = tm["spell2Id"]
                    if not my_selection["selectedChampionId"]:
                        my_selection["selectedChampionId"] = tm["championId"]
                    break

        # 7. Bench / random-pick modes (ARAM and variants)
        bench = _extract_bench(session)
        bench_enabled = self._detect_bench_mode(session, bench)

        return {
            "sessionActive": True,
            "cellId": local_cell_id,
            "isMyTurn": is_my_turn,
            "actionPhase": action_phase,
            "activeAction": active_action,
            "localPickActionId": local_pick_action_id,
            "localBanActionId": local_ban_action_id,
            "myPickIntent": local_pick_intent,
            "timer": timer_norm,
            "bans": {
                "myTeamBans": my_team_bans,
                "theirTeamBans": their_team_bans,
            },
            "myTeam": my_team,
            "theirTeam": their_team,
            "mySelection": my_selection,
            "pickMode": "BENCH" if bench_enabled else "DRAFT",
            "benchEnabled": bench_enabled,
            "bench": bench,
        }
