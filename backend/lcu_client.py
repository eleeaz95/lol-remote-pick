"""Asynchronous HTTP client for League Client (LCU) REST API."""

import logging
from typing import Optional, Any, Dict, List
import httpx

from .lcu_connector import LCUCredentials

logger = logging.getLogger(__name__)


class LCUClient:
    """Async REST API client for communicating with the local League Client."""

    def __init__(
        self,
        credentials: Optional[LCUCredentials] = None,
        base_url: Optional[str] = None,
        auth: Optional[tuple[str, str]] = None,
        timeout: float = 5.0,
    ):
        self._credentials = credentials
        self._custom_base_url = base_url
        self._custom_auth = auth
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def credentials(self) -> Optional[LCUCredentials]:
        return self._credentials

    def set_credentials(self, credentials: Optional[LCUCredentials]) -> None:
        """Update LCU connection credentials and reset the underlying HTTP client."""
        self._credentials = credentials
        if self._client and not self._client.is_closed:
            # We don't await close here synchronously, but client will be recreated on next request
            pass
        self._client = None

    def _get_base_url(self) -> str:
        if self._custom_base_url:
            return self._custom_base_url
        if self._credentials:
            return self._credentials.base_url
        return "https://127.0.0.1:2999"

    def _get_auth(self) -> Optional[tuple[str, str]]:
        if self._custom_auth:
            return self._custom_auth
        if self._credentials:
            return self._credentials.auth_tuple
        return None

    async def get_client(self) -> httpx.AsyncClient:
        """Get or initialize the underlying httpx.AsyncClient."""
        if self._client is None or self._client.is_closed:
            base_url = self._get_base_url()
            auth = self._get_auth()
            # Only skip SSL verification when communicating with local LCU on loopback
            is_loopback = "127.0.0.1" in base_url or "localhost" in base_url
            self._client = httpx.AsyncClient(
                base_url=base_url,
                auth=auth,
                verify=not is_loopback,
                timeout=self._timeout,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "LCUClient":
        await self.get_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def request(self, method: str, endpoint: str, **kwargs) -> Optional[httpx.Response]:
        """Send an HTTP request to LCU REST API with error handling."""
        try:
            client = await self.get_client()
            response = await client.request(method, endpoint, **kwargs)
            return response
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            logger.debug(f"Connection failed to LCU at {endpoint}: {e}")
            return None
        except httpx.HTTPError as e:
            logger.warning(f"HTTP error during LCU request {method} {endpoint}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during LCU request {method} {endpoint}: {e}")
            return None

    # --- Summoner Endpoints ---

    async def get_summoner(self) -> Optional[Dict[str, Any]]:
        """Fetch current summoner profile info."""
        res = await self.request("GET", "/lol-summoner/v1/current-summoner")
        if res and res.status_code == 200:
            return res.json()
        return None

    # --- Gameflow Endpoints ---

    async def get_gameflow_phase(self) -> Optional[str]:
        """Fetch current gameflow phase (e.g., 'None', 'Lobby', 'Matchmaking', 'ReadyCheck', 'ChampSelect', 'InProgress')."""
        res = await self.request("GET", "/lol-gameflow/v1/gameflow-phase")
        if res and res.status_code == 200:
            return res.json()
        return None

    async def get_gameflow_session(self) -> Optional[Dict[str, Any]]:
        """Fetch full gameflow session object."""
        res = await self.request("GET", "/lol-gameflow/v1/session")
        if res and res.status_code == 200:
            return res.json()
        return None

    # --- Lobby & Matchmaking Endpoints ---

    async def get_lobby(self) -> Optional[Dict[str, Any]]:
        """Fetch current lobby state."""
        res = await self.request("GET", "/lol-lobby/v2/lobby")
        if res and res.status_code == 200:
            return res.json()
        return None

    async def create_lobby(self, queue_id: int) -> Optional[Dict[str, Any]]:
        """Create a new lobby with specified queue ID (e.g., 420 for Ranked Solo, 400 for Normal Draft, 450 for ARAM)."""
        res = await self.request("POST", "/lol-lobby/v2/lobby", json={"queueId": queue_id})
        if res and res.status_code in (200, 201):
            return res.json()
        return None

    async def delete_lobby(self) -> bool:
        """Leave or delete current lobby."""
        res = await self.request("DELETE", "/lol-lobby/v2/lobby")
        return bool(res and res.status_code in (200, 204))

    async def set_position_preferences(self, first: str, second: str) -> Optional[Dict[str, Any]]:
        """Set lane/position preferences for local lobby member (e.g. 'TOP', 'JUNGLE', 'MIDDLE', 'BOTTOM', 'UTILITY', 'FILL')."""
        payload = {
            "firstPreference": first.upper(),
            "secondPreference": second.upper(),
        }
        res = await self.request("PUT", "/lol-lobby/v2/lobby/members/localMember/position-preferences", json=payload)
        if res and res.status_code in (200, 204):
            return res.json() if res.content else {}
        return None

    async def start_queue(self) -> bool:
        """Start matchmaking queue search."""
        res = await self.request("POST", "/lol-lobby/v2/lobby/matchmaking/search")
        return bool(res and res.status_code in (200, 204))

    async def cancel_queue(self) -> bool:
        """Cancel matchmaking queue search."""
        res = await self.request("DELETE", "/lol-lobby/v2/lobby/matchmaking/search")
        return bool(res and res.status_code in (200, 204))

    # --- Ready Check (Match Acceptance) ---

    async def get_ready_check(self) -> Optional[Dict[str, Any]]:
        """Get current ready check state."""
        res = await self.request("GET", "/lol-matchmaking/v1/ready-check")
        if res and res.status_code == 200:
            return res.json()
        return None

    async def accept_ready_check(self) -> bool:
        """Accept match ready check."""
        res = await self.request("POST", "/lol-matchmaking/v1/ready-check/accept")
        return bool(res and res.status_code in (200, 204))

    async def decline_ready_check(self) -> bool:
        """Decline match ready check."""
        res = await self.request("POST", "/lol-matchmaking/v1/ready-check/declined")
        return bool(res and res.status_code in (200, 204))

    # --- Champion Select Endpoints ---

    async def get_champ_select_session(self) -> Optional[Dict[str, Any]]:
        """Get full champion select session."""
        res = await self.request("GET", "/lol-champ-select/v1/session")
        if res and res.status_code == 200:
            return res.json()
        return None

    async def patch_champ_select_action(
        self,
        action_id: int,
        champion_id: int,
        completed: bool = False
    ) -> bool:
        """Hover (completed=False) or lock in/ban (completed=True) a champion."""
        payload = {
            "championId": champion_id,
            "completed": completed,
        }
        res = await self.request("PATCH", f"/lol-champ-select/v1/session/actions/{action_id}", json=payload)
        return bool(res and res.status_code in (200, 204))

    async def patch_my_selection(
        self,
        spell1_id: Optional[int] = None,
        spell2_id: Optional[int] = None,
        champion_id: Optional[int] = None,
    ) -> bool:
        """Update summoner spells or selected champion in champ select."""
        payload: Dict[str, Any] = {}
        if spell1_id is not None:
            payload["spell1Id"] = spell1_id
        if spell2_id is not None:
            payload["spell2Id"] = spell2_id
        if champion_id is not None:
            payload["selectedChampionId"] = champion_id

        if not payload:
            return True

        res = await self.request("PATCH", "/lol-champ-select/v1/session/my-selection", json=payload)
        return bool(res and res.status_code in (200, 204))

    # --- Static / Metadata Endpoints ---

    async def get_available_queues(self) -> List[Dict[str, Any]]:
        """Fetch list of all available game queues."""
        res = await self.request("GET", "/lol-game-queues/v1/queues")
        if res and res.status_code == 200:
            return res.json()
        return []

    async def get_all_champions(self) -> List[Dict[str, Any]]:
        """Fetch list of owned / available champions."""
        res = await self.request("GET", "/lol-champions/v1/owned-champions-minimal")
        if res and res.status_code == 200:
            return res.json()
        return []
    async def get_champions_data(self) -> List[Dict[str, Any]]:
        """Fetch full champion summary from local game data service."""
        res = await self.request("GET", "/lol-game-data/assets/v1/champion-summary.json")
        if res and res.status_code == 200:
            return res.json()
        res2 = await self.request("GET", "/lol-champions/v1/owned-champions-minimal")
        if res2 and res2.status_code == 200:
            return res2.json()
        return []

    async def get_all_summoner_spells(self) -> List[Dict[str, Any]]:
        """Fetch summoner spells metadata."""
        res = await self.request("GET", "/lol-game-data/assets/v1/summoner-spells.json")
        if res and res.status_code == 200:
            return res.json()
        return []
