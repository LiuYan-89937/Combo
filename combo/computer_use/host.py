"""Session-owned CU transport. Cancellation revokes ownership and closes the connection."""

from __future__ import annotations
import json
import logging
import os
import socket
from threading import Event, RLock
from typing import Any
from uuid import uuid4

_logger = logging.getLogger(__name__)


class ComputerHostClient:
    def __init__(
        self, *, address: str, token: str, request_id: str | None = None
    ) -> None:
        host, _, port = address.rpartition(":")
        self._address = (host, int(port))
        self._token = token
        self._request_id = request_id
        self._lock = RLock()
        self._state_lock = RLock()
        self._socket: socket.socket | None = None
        self._reader = None
        self._session_id = str(uuid4())
        self._state = "new"
        self._start_sent = False
        self._cancel_requested = False
        self.cancellation_event = Event()

    @classmethod
    def from_environment(cls) -> ComputerHostClient | None:
        address = os.environ.get("COMBO_COMPUTER_HOST_ADDRESS")
        token = os.environ.get("COMBO_COMPUTER_HOST_TOKEN")
        if not address and not token:
            return None
        if not address or not token:
            raise RuntimeError("native CU host environment is incomplete")
        return cls(address=address, token=token)

    def new_session(self, request_id: str) -> ComputerHostClient:
        return type(self)(
            address=f"{self._address[0]}:{self._address[1]}",
            token=self._token,
            request_id=request_id,
        )

    @property
    def cancel_requested(self) -> bool:
        with self._state_lock:
            return self._cancel_requested

    def _transition(self, state: str, reason: str) -> None:
        previous = self._state
        self._state = state
        _logger.info(
            "Computer use request=%s session=%s phase=session_state from=%s to=%s reason=%s",
            self._request_id,
            self._session_id,
            previous,
            state,
            reason,
        )

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        # The caller owns the I/O lock. Only start() may open a connection.
        with self._state_lock:
            if self._socket is None or self._reader is None or self._state == "closed":
                raise ConnectionError(
                    "native CU session is closed; request was not sent"
                )
            stream, reader = self._socket, self._reader
            if payload["op"] != "stop" and self._cancel_requested:
                raise ConnectionError(
                    "native CU session was cancelled; request was not sent"
                )
            stream.sendall(
                (
                    json.dumps({**payload, "token": self._token}, ensure_ascii=False)
                    + "\n"
                ).encode()
            )
            if payload["op"] == "start":
                self._start_sent = True
        try:
            line = reader.readline()
            if not line:
                raise ConnectionError(
                    "native CU connection closed; in-flight action outcome unknown"
                )
            response = json.loads(line)
            if response.get("ok") is not True:
                raise RuntimeError(response.get("error") or "native CU request failed")
            return response["result"]
        except (OSError, ValueError):
            self.close()
            raise

    def start(self) -> str:
        with self._lock:
            with self._state_lock:
                if self._state != "new":
                    raise RuntimeError("native CU session cannot be restarted")
                self._transition("starting", "start_requested")
            try:
                stream = socket.create_connection(self._address)
                with self._state_lock:
                    if self._state == "closed":
                        stream.close()
                        raise ConnectionError(
                            "native CU session cancelled before start"
                        )
                    self._socket = stream
                    self._reader = stream.makefile("rb")
                result = self._request({"op": "start", "session_id": self._session_id})
                with self._state_lock:
                    if self._cancel_requested:
                        raise ConnectionError(
                            "native CU session cancelled during start"
                        )
                    self._transition("active", "start_acknowledged")
                if (
                    result.get("engine") != "open-computer-use"
                    or result.get("session_id") != self._session_id
                ):
                    self.stop(self._session_id)
                    raise RuntimeError(
                        "the desktop host must be rebuilt for the CU session protocol"
                    )
                return self._session_id
            except BaseException:
                self.close()
                raise

    def _session_request(
        self, session_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        with self._lock:
            with self._state_lock:
                if session_id != self._session_id or self._state != "active":
                    raise RuntimeError("native CU session is not accepting actions")
            return self._request({**payload, "session_id": session_id})

    def tools(self, session_id: str) -> dict[str, Any]:
        return self._session_request(session_id, {"op": "tools"})

    def call(
        self, session_id: str, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        return self._session_request(
            session_id, {"op": "call", "name": name, "arguments": arguments}
        )

    def stop(self, session_id: str) -> None:
        with self._lock:
            with self._state_lock:
                if session_id != self._session_id:
                    raise RuntimeError("native CU session ownership mismatch")
                if self._state == "closed":
                    return
                self._transition("closing", "stop_requested")
            try:
                self._request({"op": "stop", "session_id": session_id})
            finally:
                self.close()

    def cancel_session(self, session_id: str | None = None) -> bool:
        # Serialize revocation with owner close, not with a running request's I/O.
        with self._state_lock:
            if session_id is not None and session_id != self._session_id:
                return False
            if self._cancel_requested or self._state == "closed":
                return False
            self._cancel_requested = True
            self.cancellation_event.set()
            started, pending = self._start_sent, self._state == "starting"
            self._transition("closed", "cancelled")
            stream = self._socket
            try:
                if not started:
                    return True
                # This acknowledgement only revokes the lease. It never waits for engine work.
                with socket.create_connection(self._address) as connection:
                    connection.sendall(
                        (
                            json.dumps(
                                {
                                    "op": "cancel_session",
                                    "session_id": self._session_id,
                                    "start_pending": pending,
                                    "token": self._token,
                                }
                            )
                            + "\n"
                        ).encode()
                    )
                    with connection.makefile("rb") as reader:
                        result = json.loads(reader.readline())
                    if result.get("ok") is not True:
                        raise RuntimeError(
                            result.get("error") or "native CU cancellation failed"
                        )
                    return bool(result.get("result", {}).get("cancelled"))
            finally:
                if stream is not None:
                    try:
                        stream.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass

    def close(self) -> None:
        with self._state_lock:
            stream = self._socket
            if self._state != "closed":
                self._transition("closed", "connection_closed")
        if stream is not None:
            try:
                stream.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        with self._lock:
            reader = self._reader
            self._socket = self._reader = None
            try:
                if reader is not None:
                    reader.close()
            finally:
                if stream is not None:
                    stream.close()
