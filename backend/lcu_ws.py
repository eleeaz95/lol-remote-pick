"""League Client (LCU) WebSocket connection and WAMP event listener."""

import asyncio
import json
import logging
import ssl
from typing import Callable, Optional, Coroutine, Any, List, Union
import websockets

from .lcu_connector import LCUCredentials

logger = logging.getLogger(__name__)

EventCallback = Callable[[str, Any, str], Coroutine[Any, Any, None]]
ConnectionCallback = Callable[[bool], Coroutine[Any, Any, None]]


class LCUWebSocket:
    """Manages WebSocket connection to League Client, subscribing to WAMP events."""

    def __init__(
        self,
        credentials: Optional[LCUCredentials] = None,
        event_callback: Optional[EventCallback] = None,
        connection_callback: Optional[ConnectionCallback] = None,
        reconnect_interval: float = 3.0,
        max_reconnect_interval: float = 30.0,
        disconnect_grace_period: float = 3.0,
    ):
        self._credentials = credentials
        self._event_callback = event_callback
        self._connection_callback = connection_callback
        self._reconnect_interval = reconnect_interval
        self._max_reconnect_interval = max_reconnect_interval
        self._disconnect_grace_period = disconnect_grace_period

        self._running = False
        self._connected = False
        self._ws = None
        self._listen_task: Optional[asyncio.Task] = None
        self._disconnect_debounce_task: Optional[asyncio.Task] = None
        self._subscribers: List[EventCallback] = []
        self._conn_subscribers: List[ConnectionCallback] = []
        if event_callback:
            self._subscribers.append(event_callback)
        if connection_callback:
            self._conn_subscribers.append(connection_callback)

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def credentials(self) -> Optional[LCUCredentials]:
        return self._credentials

    def set_credentials(self, credentials: Optional[LCUCredentials]) -> None:
        """Update credentials. If currently running, will reconnect on next cycle."""
        self._credentials = credentials

    def subscribe(self, callback: EventCallback) -> None:
        """Register an async event callback (uri, data, event_type)."""
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: EventCallback) -> None:
        """Unregister an async event callback."""
        if callback in self._subscribers:
            self._subscribers.remove(callback)


    def subscribe_connection(self, callback: ConnectionCallback) -> None:
        """Register a connection status change callback."""
        if callback not in self._conn_subscribers:
            self._conn_subscribers.append(callback)

    def unsubscribe_connection(self, callback: ConnectionCallback) -> None:
        """Unregister a connection status change callback."""
        if callback in self._conn_subscribers:
            self._conn_subscribers.remove(callback)
    def _create_ssl_context(self) -> Optional[ssl.SSLContext]:
        """Create SSL context that skips certificate verification for local LCU."""
        if not self._credentials or self._credentials.protocol == "http":
            return None
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    async def start(self) -> None:
        """Start the background WebSocket listening loop."""
        if self._running:
            return
        self._running = True
        self._listen_task = asyncio.create_task(self._run_loop(), name="lcu-ws-loop")
        logger.info("LCU WebSocket loop started")

    async def stop(self) -> None:
        """Stop the background WebSocket loop and disconnect."""
        self._running = False
        if self._disconnect_debounce_task and not self._disconnect_debounce_task.done():
            self._disconnect_debounce_task.cancel()
            self._disconnect_debounce_task = None
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        self._set_connected(False, immediate=True)
        logger.info("LCU WebSocket loop stopped")

    def _set_connected(self, connected: bool, immediate: bool = False) -> None:
        if connected:
            if self._disconnect_debounce_task and not self._disconnect_debounce_task.done():
                self._disconnect_debounce_task.cancel()
                self._disconnect_debounce_task = None
            if not self._connected:
                self._connected = True
                for cb in self._conn_subscribers:
                    asyncio.create_task(self._safe_call_conn_cb(cb, True))
        else:
            if immediate or self._disconnect_grace_period <= 0:
                if self._disconnect_debounce_task and not self._disconnect_debounce_task.done():
                    self._disconnect_debounce_task.cancel()
                    self._disconnect_debounce_task = None
                if self._connected:
                    self._connected = False
                    for cb in self._conn_subscribers:
                        asyncio.create_task(self._safe_call_conn_cb(cb, False))
            else:
                if self._connected and (self._disconnect_debounce_task is None or self._disconnect_debounce_task.done()):
                    self._disconnect_debounce_task = asyncio.create_task(self._debounced_disconnect())

    async def _debounced_disconnect(self) -> None:
        """Wait for grace period before declaring disconnection to filter micro-drops."""
        try:
            await asyncio.sleep(self._disconnect_grace_period)
            if not self._ws and self._connected:
                self._connected = False
                for cb in self._conn_subscribers:
                    asyncio.create_task(self._safe_call_conn_cb(cb, False))
        except asyncio.CancelledError:
            pass

    async def _safe_call_conn_cb(self, cb: ConnectionCallback, connected: bool) -> None:
        try:
            res = cb(connected)
            if asyncio.iscoroutine(res):
                await res
        except Exception as e:
            logger.error(f"Error in connection callback: {e}")
    async def _safe_call_conn(self, connected: bool) -> None:
        try:
            if self._connection_callback:
                res = self._connection_callback(connected)
                if asyncio.iscoroutine(res):
                    await res
        except Exception as e:
            logger.error(f"Error in connection callback: {e}")

    async def _dispatch_event(self, uri: str, data: Any, event_type: str = "Update") -> None:
        """Dispatch received LCU event to all registered subscriber callbacks."""
        for cb in self._subscribers:
            try:
                res = cb(uri, data, event_type)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                logger.error(f"Error dispatching LCU event '{uri}' to callback: {e}", exc_info=True)

    async def _handle_message(self, message: Union[str, bytes]) -> None:
        """Parse WAMP message format and dispatch."""
        if not message:
            return
        try:
            if isinstance(message, bytes):
                message = message.decode("utf-8")
            
            data = json.loads(message)
            # WAMP message format: [opcode, eventName, payload]
            # Opcode 8 is EVENT: [8, "OnJsonApiEvent", {"uri": "...", "eventType": "...", "data": ...}]
            if isinstance(data, list) and len(data) >= 3 and data[0] == 8:
                payload = data[2]
                if isinstance(payload, dict):
                    uri = payload.get("uri", "")
                    event_data = payload.get("data")
                    event_type = payload.get("eventType", "Update")
                    if uri:
                        await self._dispatch_event(uri, event_data, event_type)
        except json.JSONDecodeError:
            logger.debug(f"Non-JSON message received from LCU WS: {message[:100]}")
        except Exception as e:
            logger.error(f"Error processing LCU WS message: {e}", exc_info=True)

    async def _run_loop(self) -> None:
        """Main connection and message consumption loop with automatic backoff retry."""
        current_delay = self._reconnect_interval

        while self._running:
            if not self._credentials:
                self._set_connected(False)
                await asyncio.sleep(self._reconnect_interval)
                continue

            ws_url = self._credentials.ws_url
            headers = {"Authorization": self._credentials.auth_header}
            ssl_context = self._create_ssl_context()

            try:
                logger.debug(f"Connecting to LCU WebSocket at {ws_url}...")
                async with websockets.connect(
                    ws_url,
                    additional_headers=headers,
                    ssl=ssl_context,
                    ping_interval=None,
                    ping_timeout=None,
                    close_timeout=5,
                ) as ws:
                    self._ws = ws
                    self._set_connected(True)
                    current_delay = self._reconnect_interval
                    logger.info(f"Connected to LCU WebSocket at {ws_url}")

                    # Subscribe to all JSON API events (WAMP SUBSCRIBE: opcode 5)
                    subscribe_msg = json.dumps([5, "OnJsonApiEvent"])
                    await ws.send(subscribe_msg)

                    # Message loop
                    async for raw_msg in ws:
                        if not self._running:
                            break
                        await self._handle_message(raw_msg)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"LCU WebSocket disconnected / failed: {e}")
            finally:
                self._ws = None
                self._set_connected(False, immediate=False)

            if self._running:
                logger.debug(f"Reconnecting to LCU WebSocket in {current_delay:.1f}s...")
                await asyncio.sleep(current_delay)
                current_delay = min(current_delay * 1.5, self._max_reconnect_interval)
