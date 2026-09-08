"""Private desktop transport for the vendored upstream CU engine. No MCP client."""

from __future__ import annotations
import json
import os
import socket
from threading import RLock
from typing import Any


class ComputerHostClient:
    def __init__(self, *, address: str, token: str) -> None:
        host, _, port = address.rpartition(":")
        self._address = (host, int(port))
        self._token = token
        self._lock = RLock()
        self._socket: socket.socket | None = None
        self._reader = None
        self._session_id: str | None = None

    @classmethod
    def from_environment(cls) -> ComputerHostClient | None:
        address = os.environ.get("COMBO_COMPUTER_HOST_ADDRESS")
        token = os.environ.get("COMBO_COMPUTER_HOST_TOKEN")
        if not address and not token:
            return None
        if not address or not token:
            raise RuntimeError("native CU host environment is incomplete")
        return cls(address=address, token=token)

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self._socket is None:
                self._socket = socket.create_connection(self._address)
                self._reader = self._socket.makefile("rb")
            try:
                self._socket.sendall(
                    (
                        json.dumps(
                            {**payload, "token": self._token}, ensure_ascii=False
                        )
                        + "\n"
                    ).encode()
                )
                line = self._reader.readline()
                if not line:
                    raise ConnectionError(
                        "native CU connection closed; in-flight action outcome unknown"
                    )
                response = json.loads(line)
                if response.get("ok") is not True:
                    raise RuntimeError(
                        response.get("error") or "native CU request failed"
                    )
                return response["result"]
            except (OSError, ValueError):
                self.close()
                raise

    def start(self) -> str:
        result = self._request({"op": "start"})
        self._session_id = result["session_id"]
        if result.get("engine") != "open-computer-use":
            self.stop(self._session_id)
            raise RuntimeError(
                "the desktop host must be rebuilt for the upstream CU engine"
            )
        return self._session_id

    def tools(self, session_id: str) -> dict[str, Any]:
        return self._request({"op": "tools", "session_id": session_id})

    def call(
        self, session_id: str, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        return self._request(
            {
                "op": "call",
                "session_id": session_id,
                "name": name,
                "arguments": arguments,
            }
        )

    def stop(self, session_id: str) -> None:
        try:
            self._request({"op": "stop", "session_id": session_id})
        finally:
            self._session_id = None
            self.close()

    def cancel_session(self, session_id: str | None = None) -> bool:
        target = session_id or self._session_id
        if target is None:
            return False
        try:
            with socket.create_connection(self._address) as connection:
                connection.sendall(
                    (
                        json.dumps(
                            {
                                "op": "cancel_session",
                                "session_id": target,
                                "token": self._token,
                            }
                        )
                        + "\n"
                    ).encode()
                )
                with connection.makefile("rb") as reader:
                    result = json.loads(reader.readline())
                return bool(result.get("result", {}).get("cancelled"))
        finally:
            self.close()

    def close(self) -> None:
        # Interrupt blocking I/O before taking its lock; never replay a request.
        stream = self._socket
        if stream is not None:
            try:
                stream.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        with self._lock:
            if self._socket is not stream:
                return
            reader = self._reader
            self._socket = self._reader = None
            if reader is not None:
                reader.close()
            if stream is not None:
                stream.close()
