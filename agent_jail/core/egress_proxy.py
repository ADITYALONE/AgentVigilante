"""Async HTTP CONNECT egress proxy with domain whitelist."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Deque, Literal

logger = logging.getLogger(__name__)

DEFAULT_WHITELIST: set[str] = {
    "pypi.org",
    "files.pythonhosted.org",
    "registry.npmjs.org",
    "github.com",
    "objects.githubusercontent.com",
    "nodejs.org",
}

EgressAction = Literal["allowed", "blocked"]


@dataclass(frozen=True)
class EgressEvent:
    action: EgressAction
    host: str
    port: int
    timestamp: str
    detail: str = ""


class WhitelistProxy:
    """TCP CONNECT proxy that only tunnels whitelisted destinations.

    Does not MITM TLS — it inspects the CONNECT target host, then pipes
    encrypted bytes end-to-end when allowed.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8888,
        whitelist: set[str] | None = None,
        event_limit: int = 200,
    ) -> None:
        self.host = host
        self.port = port
        self.whitelist = set(whitelist or DEFAULT_WHITELIST)
        self._events: Deque[EgressEvent] = deque(maxlen=event_limit)
        self._events_lock = asyncio.Lock()
        self._server: asyncio.AbstractServer | None = None
        self._serve_task: asyncio.Task[None] | None = None

    def _is_allowed(self, target_host: str) -> bool:
        host = target_host.lower().rstrip(".")
        if host in self.whitelist:
            return True
        return any(host.endswith(f".{domain}") for domain in self.whitelist)

    async def record_event(
        self,
        action: EgressAction,
        host: str,
        port: int,
        detail: str = "",
    ) -> None:
        event = EgressEvent(
            action=action,
            host=host,
            port=port,
            timestamp=datetime.now(timezone.utc).isoformat(),
            detail=detail,
        )
        async with self._events_lock:
            self._events.appendleft(event)
        if action == "blocked":
            logger.error(
                "[BLOCKED] Security violation: agent attempted egress to %s:%s",
                host,
                port,
            )
        else:
            logger.info("[ALLOWED] Tunnel to %s:%s", host, port)

    async def recent_events(self, limit: int = 50) -> list[EgressEvent]:
        async with self._events_lock:
            return list(self._events)[:limit]

    async def handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        peer = writer.get_extra_info("peername")
        target_writer: asyncio.StreamWriter | None = None
        try:
            request_line = await reader.readline()
            if not request_line:
                return

            req = request_line.decode("utf-8", errors="replace").strip()
            if not req.upper().startswith("CONNECT "):
                logger.warning("Blocked non-CONNECT request from %s: %s", peer, req)
                writer.write(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
                await writer.drain()
                return

            parts = req.split()
            if len(parts) < 2:
                writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
                await writer.drain()
                return

            target = parts[1]
            if ":" in target:
                target_host, target_port_s = target.rsplit(":", 1)
                target_port = int(target_port_s)
            else:
                target_host, target_port = target, 443

            # Drain remaining request headers before opening the tunnel.
            while True:
                line = await reader.readline()
                if line in (b"", b"\r\n"):
                    break

            if not self._is_allowed(target_host):
                await self.record_event(
                    "blocked",
                    target_host,
                    target_port,
                    detail="CONNECT denied by whitelist",
                )
                writer.write(b"HTTP/1.1 403 Forbidden\r\n\r\n")
                await writer.drain()
                return

            try:
                target_reader, target_writer = await asyncio.open_connection(
                    target_host,
                    target_port,
                )
            except OSError as exc:
                await self.record_event(
                    "blocked",
                    target_host,
                    target_port,
                    detail=f"upstream connect failed: {exc}",
                )
                writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                await writer.drain()
                return

            await self.record_event("allowed", target_host, target_port)
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()

            await asyncio.gather(
                self._pipe(reader, target_writer),
                self._pipe(target_reader, writer),
            )
        except Exception as exc:
            logger.debug("Proxy connection closed (%s): %s", peer, exc)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            if target_writer is not None:
                try:
                    target_writer.close()
                    await target_writer.wait_closed()
                except Exception:
                    pass

    @staticmethod
    async def _pipe(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            while True:
                data = await reader.read(8192)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
        except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError):
            pass
        except Exception:
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def start(self) -> None:
        """Start serving (blocks until ``stop`` closes the server)."""
        self._server = await asyncio.start_server(
            self.handle_client,
            self.host,
            self.port,
        )
        sockets = self._server.sockets or []
        bound = ", ".join(str(s.getsockname()) for s in sockets) or f"{self.host}:{self.port}"
        logger.info("Egress proxy active on %s", bound)
        async with self._server:
            await self._server.serve_forever()

    async def start_background(self) -> asyncio.Task[None]:
        self._serve_task = asyncio.create_task(self.start(), name="egress-proxy")
        # Give the server a tick to bind.
        await asyncio.sleep(0)
        return self._serve_task

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self._serve_task is not None:
            self._serve_task.cancel()
            try:
                await self._serve_task
            except asyncio.CancelledError:
                pass
            self._serve_task = None
        logger.info("Egress proxy stopped")
