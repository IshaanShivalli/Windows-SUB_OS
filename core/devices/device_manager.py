"""Read-only discovery of hardware currently managed by the Windows host."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any


class DeviceManager:
    _POWERSHELL_SCRIPT = r"""
$classes = @('USB', 'Display', 'Monitor', 'MEDIA', 'AudioEndpoint')
$ErrorActionPreference = 'Stop'
$drivers = @{}
Get-CimInstance -ClassName Win32_PnPSignedDriver | ForEach-Object {
    $drivers[$_.DeviceID.ToUpperInvariant()] = $_
}
$devices = @(Get-PnpDevice -PresentOnly -ErrorAction Stop |
    Where-Object { $_.Class -in $classes } |
    ForEach-Object {
        $driver = $drivers[$_.InstanceId.ToUpperInvariant()]
        [PSCustomObject]@{
            class = $_.Class
            name = $_.FriendlyName
            status = $_.Status
            instance_id = $_.InstanceId
            driver_provider = $driver.DriverProviderName
            driver_version = $driver.DriverVersion
        }
    })
ConvertTo-Json -InputObject $devices -Compress -Depth 3
"""

    def __init__(self) -> None:
        self.powershell = shutil.which("powershell") or shutil.which("pwsh")

    @staticmethod
    def _category(device: dict[str, Any]) -> str:
        device_class = str(device.get("class") or "").casefold()
        instance_id = str(device.get("instance_id") or "").casefold()
        name = str(device.get("name") or "").casefold()
        if device_class == "usb" or instance_id.startswith(("usb\\", "pci\\ven_1022&dev_150")) and "usb" in name:
            return "USB"
        if device_class in {"display", "monitor"}:
            return "Display"
        if device_class in {"media", "audioendpoint"}:
            if "hdmi" in name or instance_id.startswith("hdaudio\\func_01&ven_1002"):
                return "HDMI audio"
            if instance_id.startswith("hdaudio\\func_01&ven_10ec"):
                return "AUX audio"
            return "Audio"
        return "Other"

    def list_devices(self, category: str | None = None) -> list[dict[str, str]]:
        if os.name != "nt":
            raise RuntimeError("Host device discovery is currently supported on Windows only.")
        if not self.powershell:
            raise RuntimeError("PowerShell was not found; cannot query Windows Plug and Play.")

        try:
            result = subprocess.run(
                [
                    self.powershell,
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    self._POWERSHELL_SCRIPT,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(f"Windows device query could not run: {exc}") from exc

        if result.returncode:
            detail = result.stderr.strip() or f"PowerShell exited with code {result.returncode}"
            raise RuntimeError(f"Windows device query failed: {detail}")
        try:
            raw: Any = json.loads(result.stdout) if result.stdout.strip() else []
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Windows device query returned invalid JSON: {exc}") from exc
        if isinstance(raw, dict):
            raw = [raw]
        if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
            raise RuntimeError("Windows device query returned an unexpected data format.")

        devices = []
        for item in raw:
            device = {
                "category": self._category(item),
                "name": str(item.get("name") or "Unknown device"),
                "status": str(item.get("status") or "Unknown"),
                "instance_id": str(item.get("instance_id") or "Unknown"),
                "driver_provider": str(item.get("driver_provider") or "Unknown"),
                "driver_version": str(item.get("driver_version") or "Unknown"),
            }
            matches_category = category is None or device["category"].casefold() == category.casefold()
            if category == "audio" and device["category"] in {"AUX audio", "HDMI audio"}:
                matches_category = True
            if matches_category:
                devices.append(device)
        return sorted(devices, key=lambda device: (device["category"], device["name"].casefold()))
