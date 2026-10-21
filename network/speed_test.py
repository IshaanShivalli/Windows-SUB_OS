"""Network throughput measurements using Cloudflare's public speed-test endpoint."""

import time
import urllib.parse


class NetworkSpeedTester:
    DOWNLOAD_ENDPOINT = "https://speed.cloudflare.com/__down"
    UPLOAD_ENDPOINT = "https://speed.cloudflare.com/__up"

    def __init__(self, network, sample_size_bytes=1_000_000, timeout=30):
        if sample_size_bytes <= 0:
            raise ValueError("sample_size_bytes must be positive")
        self.network = network
        self.sample_size_bytes = sample_size_bytes
        self.timeout = timeout

    def measure_download(self):
        url = self._sample_url(self.DOWNLOAD_ENDPOINT)
        started = time.perf_counter()
        response = self.network.http_request(
            "GET",
            url,
            headers={"Cache-Control": "no-cache"},
            timeout=self.timeout,
            max_bytes=self.sample_size_bytes,
        )
        elapsed = max(time.perf_counter() - started, 1e-9)
        self._check_response(response)
        transferred_bytes = len(response["body"])
        if not transferred_bytes:
            raise RuntimeError("The download speed-test endpoint returned no data")
        return self._measurement(transferred_bytes, elapsed)

    def measure_upload(self):
        payload = b"\0" * self.sample_size_bytes
        url = self._sample_url(self.UPLOAD_ENDPOINT)
        started = time.perf_counter()
        response = self.network.http_request(
            "POST",
            url,
            data=payload,
            headers={"Content-Type": "application/octet-stream"},
            timeout=self.timeout,
            max_bytes=1024,
        )
        elapsed = max(time.perf_counter() - started, 1e-9)
        self._check_response(response)
        return self._measurement(len(payload), elapsed)

    @staticmethod
    def _check_response(response):
        status_code = response.get("status_code", 0)
        if not 200 <= status_code < 300:
            raise RuntimeError(f"Speed-test server returned HTTP {status_code}")

    def _sample_url(self, endpoint):
        query = urllib.parse.urlencode(
            {
                "bytes": self.sample_size_bytes,
                "operator_sample": time.time_ns(),
            }
        )
        return f"{endpoint}?{query}"

    @staticmethod
    def _measurement(transferred_bytes, elapsed_seconds):
        return {
            "bytes": transferred_bytes,
            "seconds": elapsed_seconds,
            "mbps": transferred_bytes * 8 / elapsed_seconds / 1_000_000,
        }
