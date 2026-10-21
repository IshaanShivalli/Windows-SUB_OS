"""Read-only NTP synchronization and local clock reporting for Operator OS."""

import socket
import struct
import threading
import time
from datetime import datetime


NTP_EPOCH_OFFSET = 2_208_988_800
NTP_TIMESTAMP_SCALE = 2**32
DEFAULT_NTP_SERVERS = (
    "time.cloudflare.com",
    "time.google.com",
    "time.windows.com",
)


class TimeService:
    def __init__(self, servers=DEFAULT_NTP_SERVERS, sync_interval=900):
        self.servers = tuple(servers)
        self.sync_interval = sync_interval
        self._stop_event = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._offset_seconds = None
        self._last_sync = None
        self._last_error = None

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="operator-time-service",
                daemon=True,
            )
            self._thread.start()

    def close(self):
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=8)
            if thread.is_alive():
                raise RuntimeError("Time service did not stop before the shutdown timeout.")
        self._thread = None

    def _run(self):
        while not self._stop_event.is_set():
            self.sync_now()
            self._stop_event.wait(self.sync_interval)

    def _query_server(self, server):
        request = bytearray(48)
        request[0] = 0x23
        sent_at = time.time()
        seconds = int(sent_at) + NTP_EPOCH_OFFSET
        fraction = int((sent_at % 1) * NTP_TIMESTAMP_SCALE)
        transmit_timestamp = struct.pack("!II", seconds, fraction)
        request[40:48] = transmit_timestamp

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.settimeout(2)
            client.sendto(request, (server, 123))
            response, _ = client.recvfrom(512)
        received_at = time.time()

        if len(response) < 48:
            raise ValueError("NTP response was shorter than 48 bytes.")
        mode = response[0] & 0x07
        stratum = response[1]
        if mode != 4 or not 1 <= stratum <= 15:
            raise ValueError("NTP response was not from a valid time server.")
        if response[24:32] != transmit_timestamp:
            raise ValueError("NTP response did not match the request.")

        receive_seconds, receive_fraction = struct.unpack("!II", response[32:40])
        server_seconds, server_fraction = struct.unpack("!II", response[40:48])
        server_received = (
            receive_seconds - NTP_EPOCH_OFFSET
            + receive_fraction / NTP_TIMESTAMP_SCALE
        )
        server_sent = (
            server_seconds - NTP_EPOCH_OFFSET
            + server_fraction / NTP_TIMESTAMP_SCALE
        )
        return ((server_received - sent_at) + (server_sent - received_at)) / 2

    def sync_now(self, server=None):
        candidates = (server,) if server else self.servers
        errors = []
        for candidate in candidates:
            try:
                offset = self._query_server(candidate)
            except (OSError, ValueError) as exc:
                errors.append(f"{candidate}: {exc}")
                continue
            with self._lock:
                self._offset_seconds = offset
                self._last_sync = datetime.now().astimezone()
                self._last_error = None
            return f"Synchronized with {candidate}; local clock offset is {offset:+.3f} seconds."

        error = "; ".join(errors) or "No NTP servers are configured."
        with self._lock:
            self._last_error = error
        return f"Time synchronization failed: {error}"

    def current_time(self):
        with self._lock:
            offset = self._offset_seconds
        timestamp = time.time() + (offset or 0.0)
        return datetime.fromtimestamp(timestamp).astimezone()

    def status(self):
        with self._lock:
            thread = self._thread
            running = bool(thread and thread.is_alive())
            return {
                "running": running,
                "offset_seconds": self._offset_seconds,
                "last_sync": self._last_sync,
                "last_error": self._last_error,
            }
