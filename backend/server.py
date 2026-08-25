"""
FastAPI Backend Server & WebSocket Hub for LoL Remote Pick.

Coordinates between:
1. Local League Client (LCU API / WebSocket or Mock LCU Simulator)
2. StateEngine for normalized state representation
3. Mobile Web App (REST API + WebSocket live push)
4. Static file serving for PWA mobile frontend
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .champ_data import (
    get_all_champions,
    get_all_queues,
    get_all_spells,
    get_champion_by_id,
    get_queue_by_id,
    get_spell_by_id,
    init_champ_data,
)
from .config import Settings, get_settings
from .lcu_client import LCUClient
from .lcu_connector import LCUConnector, LCUCredentials
from .lcu_ws import LCUWebSocket
from .mock_lcu import MockLCUServer
from .state_engine import StateEngine

logger = logging.getLogger("server")

# ---------------------------------------------------------------------------
# Request / Response Schemas
# ---------------------------------------------------------------------------


class CreateLobbyRequest(BaseModel):
    queueId: int = Field(default=420, description="Queue ID (e.g. 420 for Solo/Duo, 400 for Draft, 450 for ARAM)")


class PositionPreferencesRequest(BaseModel):
    first: str = Field(..., description="First lane preference (TOP, JUNGLE, MIDDLE, BOTTOM, UTILITY, FILL)")
    second: str = Field(default="FILL", description="Second lane preference")


class ChampSelectActionRequest(BaseModel):
    actionId: int = Field(..., description="Action ID in champ select session")
    championId: int = Field(..., description="Champion ID to pick or ban")
    completed: bool = Field(default=True, description="True to lock in, False to hover")


class ChampSelectHoverRequest(BaseModel):
    actionId: int = Field(..., description="Action ID in champ select session")
    championId: int = Field(..., description="Champion ID to hover")


class ChampSelectSpellsRequest(BaseModel):
    spell1Id: Optional[int] = Field(default=None, description="Summoner spell 1 ID (e.g. 4 for Flash)")
    spell2Id: Optional[int] = Field(default=None, description="Summoner spell 2 ID (e.g. 14 for Ignite)")
    selectedChampionId: Optional[int] = Field(default=None, description="Optional selected champion ID")


class MockPhaseRequest(BaseModel):
    phase: str = Field(..., description="Phase name (None, Lobby, Matchmaking, ReadyCheck, ChampSelect, InProgress)")
    queueId: Optional[int] = Field(default=420, description="Queue ID for lobby simulation")


# ---------------------------------------------------------------------------
# Network & QR Code Utilities
# ---------------------------------------------------------------------------

def get_all_lan_ips() -> List[Dict[str, Any]]:
    """
    Discovers all active LAN IPv4 addresses on the host system,
    filtering and categorizing Wi-Fi, Ethernet, and virtual adapters.
    """
    results: List[Dict[str, Any]] = []
    seen_ips: Set[str] = set()

    # 1. Inspect interfaces via psutil if available
    try:
        import psutil
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats() if hasattr(psutil, "net_if_stats") else {}

        for iface_name, iface_addrs in addrs.items():
            stat = stats.get(iface_name)
            is_up = stat.isup if stat else True
            if not is_up:
                continue

            lower_name = iface_name.lower()
            is_virtual = any(
                v in lower_name
                for v in [
                    "virtual", "vbox", "vmware", "wsl", "vethernet", "docker",
                    "tailscale", "zerotier", "hamachi", "loopback", "bluetooth",
                    "npcap", "teredo", "isatap"
                ]
            )

            for addr in iface_addrs:
                if getattr(addr, "family", None) == socket.AF_INET:
                    ip = addr.address
                    if not ip or ip.startswith("127.") or ip.startswith("169.254.") or ip in seen_ips:
                        continue
                    seen_ips.add(ip)

                    # Classify type & priority
                    if any(w in lower_name for w in ["wi-fi", "wifi", "wlan", "wireless"]):
                        iface_type = "Wi-Fi"
                        priority = 100 if not is_virtual else 40
                    elif any(e in lower_name for e in ["ethernet", "eth", "lan", "local area"]):
                        iface_type = "Ethernet"
                        priority = 90 if not is_virtual else 35
                    elif is_virtual:
                        iface_type = "Virtual / VPN"
                        priority = 20
                    else:
                        iface_type = "Network"
                        priority = 50

                    results.append({
                        "ip": ip,
                        "interface": iface_name,
                        "type": iface_type,
                        "is_virtual": is_virtual,
                        "priority": priority,
                    })
    except Exception as e:
        logger.debug(f"psutil network interface inspection failed: {e}")

    # 2. Socket routing check fallback / cross-check
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        route_ip = s.getsockname()[0]
        s.close()
        if route_ip and not route_ip.startswith("127.") and not route_ip.startswith("169.254."):
            if route_ip not in seen_ips:
                seen_ips.add(route_ip)
                results.append({
                    "ip": route_ip,
                    "interface": "Default Gateway Route",
                    "type": "LAN",
                    "is_virtual": False,
                    "priority": 80,
                })
            else:
                # Boost priority of the routed IP if it's not virtual
                for item in results:
                    if item["ip"] == route_ip and not item.get("is_virtual"):
                        item["priority"] += 15
    except Exception:
        pass

    # 3. Hostname lookup fallback
    if not results:
        try:
            host_ips = socket.gethostbyname_ex(socket.gethostname())[2]
            for ip in host_ips:
                if not ip.startswith("127.") and not ip.startswith("169.254.") and ip not in seen_ips:
                    seen_ips.add(ip)
                    results.append({
                        "ip": ip,
                        "interface": "Local Adapter",
                        "type": "LAN",
                        "is_virtual": False,
                        "priority": 60,
                    })
        except Exception:
            pass

    # Fallback to localhost if no LAN IP was found
    if not results:
        results.append({
            "ip": "127.0.0.1",
            "interface": "Loopback",
            "type": "Localhost",
            "is_virtual": False,
            "priority": 0,
        })

    results.sort(key=lambda x: x.get("priority", 0), reverse=True)
    return results


def get_best_lan_ip() -> str:
    """Discovers the most reliable local LAN IPv4 address for mobile access."""
    lan_ips = get_all_lan_ips()
    return lan_ips[0]["ip"] if lan_ips else "127.0.0.1"


def get_local_ip() -> str:
    """Compatibility alias for get_best_lan_ip."""
    return get_best_lan_ip()
def generate_ascii_qr(url: str) -> str:
    """
    Renders a compact, high-contrast ASCII/Unicode block QR code for terminal display.
    Falls back gracefully if qrcode library is not installed.
    """
    try:
        import qrcode

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=1,
            border=2,
        )
        qr.add_data(url)
        qr.make(fit=True)

        matrix = qr.get_matrix()
        lines: List[str] = []
        # Render 2 rows per character using half block characters
        for y in range(0, len(matrix), 2):
            line = ""
            for x in range(len(matrix[0])):
                top = matrix[y][x]
                bottom = matrix[y + 1][x] if y + 1 < len(matrix) else False
                if top and bottom:
                    line += "█"
                elif top and not bottom:
                    line += "▀"
                elif not top and bottom:
                    line += "▄"
                else:
                    line += " "
            lines.append("  " + line)
        return "\n".join(lines)
    except Exception:
        # Fallback placeholder if qrcode module unavailable
        return f"  [ QR Code Generator requires 'qrcode' library ]\n  Open URL directly: {url}"


def generate_svg_qr(url: str) -> str:
    """Generates an inline SVG string for the QR code to display in web UI."""
    try:
        import io
        import qrcode
        import qrcode.image.svg

        factory = qrcode.image.svg.SvgPathImage
        img = qrcode.make(url, image_factory=factory, box_size=8, border=2)
        stream = io.BytesIO()
        img.save(stream)
        return stream.getvalue().decode("utf-8")
    except Exception as e:
        logger.debug("SVG QR generation failed: %s", e)
        return ""

# ---------------------------------------------------------------------------
# Application State & Hub Manager
# ---------------------------------------------------------------------------


class AppHub:
    """Coordinates state engine, LCU connector/client/websocket, and client connections."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.state_engine = StateEngine()
        self.lcu_connector: Optional[LCUConnector] = None
        self.lcu_client = LCUClient()
        self.lcu_ws = LCUWebSocket()
        self.mock_server: Optional[MockLCUServer] = None

        self.active_websockets: Set[WebSocket] = set()
        self.background_tasks: List[asyncio.Task] = []
        self._is_running = False
        self._last_broadcast_payload: Optional[Dict[str, Any]] = None
    async def broadcast_state(self, state: Dict[str, Any]) -> None:
        """Broadcast normalized state JSON to all connected mobile WebSockets."""
        if not self.active_websockets:
            return

        # Add mock flag into payload for frontend awareness
        payload = dict(state)
        payload["mock"] = bool(self.mock_server is not None)

        # Deduplicate state broadcast if payload hasn't materially changed
        comparable_payload = {k: v for k, v in payload.items() if k != "serverTime"}
        if comparable_payload == self._last_broadcast_payload:
            return
        self._last_broadcast_payload = comparable_payload

        msg = json.dumps(payload)
        dead_sockets: List[WebSocket] = []

        for ws in list(self.active_websockets):
            try:
                await ws.send_text(msg)
            except Exception:
                dead_sockets.append(ws)

        for ws in dead_sockets:
            self.active_websockets.discard(ws)
    async def _on_state_engine_change(self, state: Dict[str, Any]) -> None:
        """Callback registered with StateEngine."""
        await self.broadcast_state(state)

    async def _lcu_poll_loop(self) -> None:
        """Background loop to discover LCU or poll HTTP status if needed."""
        logger.info("Started LCU discovery & polling background loop")
        last_had_creds = False
        consecutive_failures = 0
        MAX_CONSECUTIVE_FAILURES = 3

        while self._is_running:
            try:
                if self.mock_server is not None:
                    # In mock mode, credentials are fixed
                    await asyncio.sleep(self.settings.lcu_poll_interval)
                    continue

                # Real LCU mode: check for credentials via connector
                if self.lcu_connector is not None:
                    creds = self.lcu_connector.get_credentials()
                    if creds is not None:
                        consecutive_failures = 0
                        if not last_had_creds:
                            logger.info("Discovered League Client LCU lockfile / process at port %d", creds.port)
                            self.lcu_client.set_credentials(creds)
                            self.lcu_ws.set_credentials(creds)
                            last_had_creds = True

                            # Initial poll on discovery to seed state immediately
                            phase = await self.lcu_client.get_gameflow_phase()
                            if phase is not None:
                                summoner = await self.lcu_client.get_summoner()
                                lobby = await self.lcu_client.get_lobby()
                                ready_check = await self.lcu_client.get_ready_check()
                                champ_select = await self.lcu_client.get_champ_select_session()

                                self.state_engine.update_from_poll(
                                    phase=phase,
                                    summoner=summoner,
                                    lobby=lobby,
                                    ready_check=ready_check,
                                    champ_select=champ_select,
                                )
                                self.state_engine.set_connected(True)
                        elif self.lcu_ws.is_connected:
                            # WebSocket is actively receiving real-time events.
                            # Skip HTTP REST polling! Only verify process liveness.
                            if not self.lcu_connector.is_alive():
                                logger.warning("League Client process exited")
                                last_had_creds = False
                                self.state_engine.set_connected(False)
                        else:
                            # Fallback HTTP polling when WebSocket is disconnected
                            phase = await self.lcu_client.get_gameflow_phase()
                            if phase is not None:
                                summoner = await self.lcu_client.get_summoner()
                                lobby = await self.lcu_client.get_lobby()
                                ready_check = await self.lcu_client.get_ready_check()
                                champ_select = await self.lcu_client.get_champ_select_session()

                                self.state_engine.update_from_poll(
                                    phase=phase,
                                    summoner=summoner,
                                    lobby=lobby,
                                    ready_check=ready_check,
                                    champ_select=champ_select,
                                )
                                self.state_engine.set_connected(True)
                            else:
                                consecutive_failures += 1
                                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                                    logger.warning("League Client unresponsive (%d consecutive failed polls)", consecutive_failures)
                                    last_had_creds = False
                                    self.state_engine.set_connected(False)
                    else:
                        consecutive_failures += 1
                        if last_had_creds and consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                            logger.warning("League Client disconnected or closed (%d consecutive failed polls)", consecutive_failures)
                            last_had_creds = False
                            self.state_engine.set_connected(False)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("LCU poll loop exception: %s", exc)

            await asyncio.sleep(self.settings.lcu_poll_interval)
    async def start(self) -> None:
        """Initialize all backend components and background tasks."""
        self._is_running = True

        # 1. Initialize champion catalog
        await init_champ_data(self.settings.ddragon_version)

        # 2. Register StateEngine listener
        self.state_engine.subscribe(self._on_state_engine_change)

        # 3. Start Mock or Real LCU connector
        if self.settings.mock_mode:
            logger.info("Initializing in MOCK LCU mode on port %d", self.settings.mock_port)
            self.mock_server = MockLCUServer(
                host="127.0.0.1",
                port=self.settings.mock_port,
                auto_progress=self.settings.mock_auto_progress,
            )
            await self.mock_server.start()

            mock_creds = self.mock_server.get_credentials()
            self.lcu_client.set_credentials(mock_creds)
            self.lcu_ws.set_credentials(mock_creds)

            # Wire LCU WebSocket to StateEngine
            self.lcu_ws.subscribe(self.state_engine.handle_lcu_event)
            self.lcu_ws.subscribe_connection(self._on_lcu_ws_connection)
            await self.lcu_ws.start()

            # Seed initial mock state
            self.state_engine.set_connected(True)
            summoner = await self.lcu_client.get_summoner()
            phase = await self.lcu_client.get_gameflow_phase()
            lobby = await self.lcu_client.get_lobby()
            self.state_engine.update_from_poll(gameflow_phase=phase or "None", summoner=summoner, lobby=lobby)
        else:
            logger.info("Initializing in REAL LCU mode (auto-discovering LeagueClient.exe)")
            self.lcu_connector = LCUConnector(custom_path=self.settings.custom_league_path)

            self.lcu_ws.subscribe(self.state_engine.handle_lcu_event)
            self.lcu_ws.subscribe_connection(self._on_lcu_ws_connection)
            await self.lcu_ws.start()

            # Background poller task
            poll_task = asyncio.create_task(self._lcu_poll_loop(), name="lcu-poll-loop")
            self.background_tasks.append(poll_task)

    async def _on_lcu_ws_connection(self, connected: bool) -> None:
        """Handle LCU WebSocket connect/disconnect events."""
        self.state_engine.set_connected(connected)

    async def stop(self) -> None:
        """Gracefully shutdown all components."""
        self._is_running = False

        # Cancel background tasks
        for task in self.background_tasks:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self.background_tasks.clear()

        # Stop LCU WebSocket
        await self.lcu_ws.stop()

        # Close LCU Client
        await self.lcu_client.close()

        # Stop Mock server if running
        if self.mock_server is not None:
            await self.mock_server.stop()
            self.mock_server = None

        # Close all mobile WebSockets
        for ws in list(self.active_websockets):
            try:
                await ws.close()
            except Exception:
                pass
        self.active_websockets.clear()

        logger.info("AppHub shutdown complete")

    async def execute_action(self, action_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Unified action dispatcher for both REST and WebSocket invocations."""
        action = action_name.upper().strip()
        logger.info("Executing client action: %s with payload: %s", action, payload)

        try:
            if action in ("ACCEPT_MATCH", "ACCEPT", "MATCHMAKING_ACCEPT"):
                success = await self.lcu_client.accept_ready_check()
                return {"success": success, "action": action}

            elif action in ("DECLINE_MATCH", "DECLINE", "MATCHMAKING_DECLINE"):
                success = await self.lcu_client.decline_ready_check()
                return {"success": success, "action": action}

            elif action in ("START_QUEUE", "QUEUE_START"):
                success = await self.lcu_client.start_queue()
                return {"success": success, "action": action}

            elif action in ("CANCEL_QUEUE", "QUEUE_CANCEL"):
                success = await self.lcu_client.cancel_queue()
                return {"success": success, "action": action}

            elif action in ("CREATE_LOBBY", "LOBBY_CREATE"):
                qid = int(payload.get("queueId", payload.get("queue_id", 420)))
                lobby = await self.lcu_client.create_lobby(qid)
                if lobby is not None:
                    self.state_engine.update_from_poll(lobby=lobby, gameflow_phase="Lobby")
                    return {"success": True, "action": action, "queueId": qid}
                elif self.mock_server is not None:
                    await self.mock_server.trigger_lobby(queue_id=qid)
                    if self.mock_server.lobby:
                        self.state_engine.update_from_poll(lobby=self.mock_server.lobby, gameflow_phase="Lobby")
                    return {"success": True, "action": action, "queueId": qid}
                return {"success": False, "action": action, "queueId": qid}

            elif action in ("SET_POSITIONS", "SET_POSITION_PREFERENCES", "LOBBY_POSITIONS"):
                first = str(payload.get("first", payload.get("firstPreference", "FILL")))
                second = str(payload.get("second", payload.get("secondPreference", "FILL")))
                res = await self.lcu_client.set_position_preferences(first, second)
                return {"success": res is not None, "action": action, "first": first, "second": second}

            elif action in ("CHAMP_ACTION", "ACTION", "CHAMP_SELECT_ACTION"):
                action_id = int(payload.get("actionId", 0))
                champion_id = int(payload.get("championId", 0))
                completed = bool(payload.get("completed", True))
                success = await self.lcu_client.patch_champ_select_action(action_id, champion_id, completed=completed)
                return {"success": success, "action": action, "actionId": action_id, "championId": champion_id, "completed": completed}

            elif action in ("CHAMP_HOVER", "HOVER", "CHAMP_SELECT_HOVER", "PRESELECT", "PICK_INTENT"):
                action_id = int(payload.get("actionId", 0))
                champion_id = int(payload.get("championId", 0))

                # If action_id not provided or 0, fallback to activeAction or localPickActionId
                if not action_id:
                    cs_state = self.state_engine.get_state().get("champSelect", {})
                    if cs_state.get("activeAction"):
                        action_id = int(cs_state["activeAction"].get("id", 0))
                    elif cs_state.get("localPickActionId"):
                        action_id = int(cs_state.get("localPickActionId", 0))

                success = False
                if action_id:
                    success = await self.lcu_client.patch_champ_select_action(action_id, champion_id, completed=False)

                # Also always patch my-selection to update championPickIntent in LCU
                my_sel_success = await self.lcu_client.patch_my_selection(champion_id=champion_id)
                success = success or my_sel_success
                return {"success": success, "action": action, "actionId": action_id, "championId": champion_id}
            elif action in ("SET_SPELLS", "SPELLS", "CHAMP_SELECT_SPELLS"):
                s1 = payload.get("spell1Id")
                s2 = payload.get("spell2Id")
                s1_id = int(s1) if s1 is not None else None
                s2_id = int(s2) if s2 is not None else None
                cid = payload.get("selectedChampionId")
                c_id = int(cid) if cid is not None else None
                success = await self.lcu_client.patch_my_selection(spell1_id=s1_id, spell2_id=s2_id, champion_id=c_id)
                return {"success": success, "action": action}

            elif action in ("GET_STATE", "PING"):
                state = self.state_engine.get_state()
                state["mock"] = bool(self.mock_server is not None)
                return {"success": True, "action": action, "state": state}

            elif action in ("MOCK_SET_PHASE", "MOCK_PHASE") and self.mock_server is not None:
                phase = str(payload.get("phase", "Lobby"))
                qid = int(payload.get("queueId", 420))
                if phase.lower() == "lobby":
                    await self.mock_server.trigger_lobby(queue_id=qid)
                elif phase.lower() in ("in_queue", "matchmaking", "queue"):
                    await self.mock_server.trigger_queue()
                elif phase.lower() in ("ready_check", "readycheck"):
                    await self.mock_server.trigger_ready_check()
                elif phase.lower() in ("champ_select", "champselect"):
                    await self.mock_server.trigger_champ_select()
                elif phase.lower() in ("in_game", "inprogress"):
                    await self.mock_server.trigger_in_game()
                elif phase.lower() == "none":
                    await self.mock_server.trigger_none()
                await asyncio.sleep(0.05)
                return {"success": True, "action": action, "phase": phase}

            elif action in ("MOCK_ADVANCE",) and self.mock_server is not None:
                cur_phase = self.mock_server.gameflow_phase
                if cur_phase == "None":
                    await self.mock_server.trigger_lobby(420)
                elif cur_phase == "Lobby":
                    await self.mock_server.trigger_queue()
                elif cur_phase == "Matchmaking":
                    await self.mock_server.trigger_ready_check()
                elif cur_phase == "ReadyCheck":
                    await self.mock_server.trigger_champ_select()
                elif cur_phase == "ChampSelect":
                    await self.mock_server.trigger_in_game()
                elif cur_phase == "InProgress":
                    await self.mock_server.trigger_lobby(420)
                await asyncio.sleep(0.05)
                return {"success": True, "action": action, "currentPhase": self.mock_server.gameflow_phase}
            else:
                logger.warning("Unrecognized action received: %s", action_name)
                return {"success": False, "error": f"Unknown action: {action_name}"}

        except Exception as err:
            logger.error("Error executing action %s: %s", action_name, err, exc_info=True)
            return {"success": False, "error": str(err)}


# ---------------------------------------------------------------------------
# FastAPI Application Factory
# ---------------------------------------------------------------------------


def create_app(custom_settings: Optional[Settings] = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    app_settings = custom_settings or get_settings()
    hub = AppHub(app_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        logger.info("Starting LoL Remote Pick backend...")
        await hub.start()
        app.state.hub = hub
        yield
        # Shutdown
        logger.info("Stopping LoL Remote Pick backend...")
        await hub.stop()

    app = FastAPI(
        title="LoL Remote Pick API",
        version="0.1.0",
        description="Remote controller and pick/ban API for League Client (LCU)",
        lifespan=lifespan,
    )

    # CORS configuration - disable credentials when wildcard origin is configured
    allow_creds = False if "*" in app_settings.cors_origins else True
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=allow_creds,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Store hub in state
    app.state.hub = hub

    # -----------------------------------------------------------------------
    # REST Endpoints
    # -----------------------------------------------------------------------

    @app.get("/api/state")
    async def get_current_state():
        """Returns the current normalized state."""
        st = hub.state_engine.get_state()
        st["mock"] = bool(hub.mock_server is not None)
        return st


    @app.get("/api/network-info")
    async def get_network_info():
        """Returns LAN connection URLs, QR code SVG, and network interfaces."""
        all_ips = get_all_lan_ips()
        primary_ip = all_ips[0]["ip"] if all_ips else "127.0.0.1"
        port = app_settings.port
        primary_url = f"http://{primary_ip}:{port}"
        svg_qr = generate_svg_qr(primary_url)

        interfaces = []
        for item in all_ips:
            ip = item["ip"]
            interfaces.append({
                "ip": ip,
                "url": f"http://{ip}:{port}",
                "interface": item.get("interface", "Network"),
                "type": item.get("type", "LAN"),
                "is_virtual": item.get("is_virtual", False),
                "is_primary": (ip == primary_ip),
            })

        return {
            "primary_ip": primary_ip,
            "port": port,
            "primary_url": primary_url,
            "pc_url": f"http://localhost:{port}",
            "qr_svg": svg_qr,
            "interfaces": interfaces,
        }
    @app.get("/api/champions")
    async def get_champions(role: Optional[str] = None, search: Optional[str] = None):
        """Returns catalog of League champions with role/search filtering."""
        return get_all_champions(role_filter=role, search=search)

    @app.get("/api/spells")
    async def get_spells(mode: Optional[str] = None):
        """Returns catalog of summoner spells."""
        return get_all_spells()

    @app.get("/api/queues")
    async def get_queues():
        """Returns list of supported game queues."""
        return get_all_queues()

    @app.post("/api/lobby/create")
    async def create_lobby(body: CreateLobbyRequest):
        """Creates a new lobby with the requested queue ID."""
        res = await hub.execute_action("CREATE_LOBBY", body.model_dump())
        if not res.get("success"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to create lobby")
        return res

    @app.post("/api/lobby/positions")
    async def set_positions(body: PositionPreferencesRequest):
        """Sets lane position preferences for local player."""
        res = await hub.execute_action("SET_POSITIONS", body.model_dump())
        if not res.get("success"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to set positions")
        return res

    @app.post("/api/lobby/queue/start")
    async def start_queue():
        """Starts matchmaking queue search."""
        res = await hub.execute_action("START_QUEUE", {})
        if not res.get("success"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to start queue")
        return res

    @app.post("/api/lobby/queue/cancel")
    async def cancel_queue():
        """Cancels matchmaking queue search."""
        res = await hub.execute_action("CANCEL_QUEUE", {})
        if not res.get("success"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to cancel queue")
        return res

    @app.post("/api/matchmaking/accept")
    async def accept_match():
        """Accepts match ready check."""
        res = await hub.execute_action("ACCEPT_MATCH", {})
        if not res.get("success"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to accept match")
        return res

    @app.post("/api/matchmaking/decline")
    async def decline_match():
        """Declines match ready check."""
        res = await hub.execute_action("DECLINE_MATCH", {})
        if not res.get("success"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to decline match")
        return res

    @app.post("/api/champ-select/action")
    async def champ_select_action(body: ChampSelectActionRequest):
        """Locks in or performs an action in champion select."""
        res = await hub.execute_action("CHAMP_ACTION", body.model_dump())
        if not res.get("success"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to perform champ select action")
        return res

    @app.post("/api/champ-select/hover")
    async def champ_select_hover(body: ChampSelectHoverRequest):
        """Hovers a champion in champion select without locking in."""
        res = await hub.execute_action("CHAMP_HOVER", body.model_dump())
        if not res.get("success"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to hover champion")
        return res

    @app.post("/api/champ-select/spells")
    async def champ_select_spells(body: ChampSelectSpellsRequest):
        """Updates selected summoner spells in champion select."""
        res = await hub.execute_action("SET_SPELLS", body.model_dump())
        if not res.get("success"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to set summoner spells")
        return res

    # Mock helper endpoints
    @app.post("/api/mock/phase")
    async def mock_set_phase(body: MockPhaseRequest):
        """Mock simulation helper to switch phases."""
        if hub.mock_server is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mock mode is not active")
        return await hub.execute_action("MOCK_SET_PHASE", body.model_dump())

    @app.post("/api/mock/advance")
    async def mock_advance():
        """Mock simulation helper to advance to next game phase."""
        if hub.mock_server is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mock mode is not active")
        return await hub.execute_action("MOCK_ADVANCE", {})

    # -----------------------------------------------------------------------
    # WebSocket Gateway
    # -----------------------------------------------------------------------

    MAX_WS_CONNECTIONS = 32
    MAX_WS_MESSAGE_SIZE = 65536  # 64 KB limit

    @app.websocket("/ws")
    async def websocket_gateway(websocket: WebSocket):
        """
        Bidirectional real-time WebSocket connection for mobile clients.
        Pushes normalized state on connection and whenever state changes.
        Receives action commands from mobile UI.
        """
        if len(hub.active_websockets) >= MAX_WS_CONNECTIONS:
            await websocket.close(code=1008, reason="Connection limit exceeded")
            return

        await websocket.accept()
        hub.active_websockets.add(websocket)
        logger.info("Mobile client connected via WebSocket (%d active)", len(hub.active_websockets))

        # Send initial snapshot immediately upon connect
        try:
            initial_state = hub.state_engine.get_state()
            initial_state["mock"] = bool(hub.mock_server is not None)
            await websocket.send_text(json.dumps(initial_state))
        except Exception as e:
            logger.debug("Failed to send initial WS state: %s", e)

        try:
            while True:
                msg_text = await websocket.receive_text()
                if not msg_text or len(msg_text) > MAX_WS_MESSAGE_SIZE:
                    continue

                try:
                    payload = json.loads(msg_text)
                except Exception:
                    continue
                # Support both endpoint style and action style
                endpoint = payload.get("endpoint", "")
                action = payload.get("action", payload.get("type", ""))

                if not action and endpoint:
                    # Map endpoint path to action name
                    if "/api/matchmaking/accept" in endpoint:
                        action = "ACCEPT_MATCH"
                    elif "/api/matchmaking/decline" in endpoint:
                        action = "DECLINE_MATCH"
                    elif "/api/lobby/queue/start" in endpoint:
                        action = "START_QUEUE"
                    elif "/api/lobby/queue/cancel" in endpoint:
                        action = "CANCEL_QUEUE"
                    elif "/api/lobby/create" in endpoint:
                        action = "CREATE_LOBBY"
                    elif "/api/lobby/positions" in endpoint:
                        action = "SET_POSITIONS"
                    elif "/api/champ-select/action" in endpoint:
                        action = "CHAMP_ACTION"
                    elif "/api/champ-select/hover" in endpoint:
                        action = "CHAMP_HOVER"
                    elif "/api/champ-select/spells" in endpoint:
                        action = "SET_SPELLS"
                    elif "/api/state" in endpoint:
                        action = "GET_STATE"

                if action:
                    result = await hub.execute_action(action, payload)
                    # Respond with result if requested or needed
                    try:
                        await websocket.send_text(json.dumps({"type": "action_result", "data": result}))
                    except Exception:
                        pass

        except WebSocketDisconnect:
            hub.active_websockets.discard(websocket)
            logger.info("Mobile client disconnected (%d active)", len(hub.active_websockets))
        except Exception as exc:
            hub.active_websockets.discard(websocket)
            logger.debug("WebSocket client error: %s", exc)

    # -----------------------------------------------------------------------
    # Static Files & SPA Fallback Serving
    # -----------------------------------------------------------------------

    static_path = app_settings.get_static_path()
    if static_path.is_dir():
        logger.info("Mounting frontend static directory from: %s", static_path)

        # Serve static assets (js, css, icons, manifest, etc.)
        app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

        # Root index route
        @app.get("/")
        async def serve_root():
            index_file = static_path / "index.html"
            if index_file.is_file():
                return FileResponse(str(index_file))
            return JSONResponse({"message": "LoL Remote Pick Backend running"})

        # Catch-all route for SPA navigation (HTML5 pushState) and direct assets
        resolved_static_path = static_path.resolve()

        @app.get("/{full_path:path}")
        async def serve_spa_or_file(full_path: str):
            # Skip API and WS routes
            if full_path.startswith("api/") or full_path.startswith("ws"):
                raise HTTPException(status_code=404, detail="Not Found")

            try:
                # Prevent directory traversal by resolving path and verifying containment
                target_file = (static_path / full_path).resolve()
                if target_file.is_relative_to(resolved_static_path) and target_file.is_file():
                    return FileResponse(str(target_file))
            except (ValueError, RuntimeError):
                pass

            # Fallback to index.html for SPA routes
            index_file = resolved_static_path / "index.html"
            if index_file.is_file():
                return FileResponse(str(index_file))

            raise HTTPException(status_code=404, detail="File Not Found")
    else:
        logger.warning("Frontend static directory '%s' not found.", static_path)

        @app.get("/")
        async def serve_api_root():
            return {
                "name": "LoL Remote Pick Backend",
                "status": "online",
                "mock": hub.settings.mock_mode,
                "docs": "/docs",
            }

    return app


# Default app instance
app = create_app()
