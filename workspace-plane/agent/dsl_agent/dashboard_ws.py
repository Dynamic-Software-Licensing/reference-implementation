"""Local WebSocket server for the dashboard."""

import json
import asyncio
import threading
from datetime import datetime, timezone
from typing import Optional

import websockets
from websockets.server import serve


class DashboardServer:
    """WebSocket server that broadcasts agent events to the dashboard.

    The dashboard (HTML/JS) connects to ws://localhost:{port} and receives
    a stream of JSON events representing the entire licensing lifecycle.
    """

    def __init__(self, port: int = 8765):
        self._port = port
        self._clients: set = set()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def start(self) -> None:
        """Start the WebSocket server in a background thread."""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        """Run the asyncio event loop."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())

    async def _serve(self) -> None:
        """Start the WebSocket server and keep it running."""
        async with serve(self._handler, "localhost", self._port):
            await asyncio.Future()  # Run forever

    async def _handler(self, websocket):
        """Handle a new dashboard client connection."""
        self._clients.add(websocket)
        try:
            async for message in websocket:
                pass  # Dashboard doesn't send messages (one-way stream)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._clients.discard(websocket)

    def emit(self, event: str, data: dict) -> None:
        """Broadcast an event to all connected dashboard clients.

        Args:
            event: Event type name.
            data: Event-specific payload.
        """
        message = json.dumps({
            "event": event,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        })

        if self._loop and self._clients:
            asyncio.run_coroutine_threadsafe(
                self._broadcast(message),
                self._loop,
            )

    async def _broadcast(self, message: str) -> None:
        """Send message to all connected clients."""
        if self._clients:
            await asyncio.gather(
                *[client.send(message) for client in self._clients.copy()],
                return_exceptions=True,
            )
