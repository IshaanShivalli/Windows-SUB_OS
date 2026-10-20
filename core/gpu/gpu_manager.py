"""User-space GPU capability layer for AI and hardware introspection.

Performs deep probing of host GPU hardware via Windows WMI/CIM, DirectX,
clinfo, and vendor management tools (nvidia-smi, rocminfo) to provide complete
hardware specifications, memory sizes, clock rates, driver versions, and display modes.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List


class GPUManager:
    def __init__(self):
        self.devices: list[dict[str, Any]] = []
        self.probe_errors: list[str] = []
        self.refresh()

    @staticmethod
    def _run(command: list[str]) -> str:
        try:
            return subprocess.check_output(command, text=True, stderr=subprocess.DEVNULL, timeout=5).strip()
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            return ""

    def _query_wmi_gpus(self) -> list[dict[str, Any]]:
        """Query detailed GPU hardware info from Windows CIM/WMI."""
        if os.name != "nt":
            return []
        ps_cmd = (
            "Get-CimInstance Win32_VideoController | Select-Object "
            "Name, VideoProcessor, DriverVersion, AdapterRAM, VideoModeDescription, "
            "CurrentRefreshRate, Status, ConfigManagerErrorCode, PNPDeviceID, "
            "MaxRefreshRate, MinRefreshRate "
            "| ConvertTo-Json"
        )
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True,
                text=True,
                timeout=6,
            )
            if res.returncode:
                message = res.stderr.strip() or f"PowerShell exited with status {res.returncode}"
                self.probe_errors.append(f"Windows GPU query failed: {message}")
            raw = res.stdout.strip()
            if not raw:
                return []
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return [parsed]
            elif isinstance(parsed, list):
                return parsed
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            self.probe_errors.append(f"Windows GPU query failed: {exc}")
            pass
        return []

    def _query_clinfo_details(self) -> dict[str, str]:
        """Extract detailed hardware metrics from clinfo if installed."""
        out = self._run(["clinfo"])
        if not out:
            return {}
        extracted: dict[str, str] = {}
        target_keys = {
            "Board name": "board_name",
            "Device Type": "device_type",
            "Max compute units": "compute_units",
            "Max clock frequency": "clock_frequency",
            "Global memory size": "global_mem_bytes",
            "Max memory allocation": "max_alloc_bytes",
            "Local memory size": "local_mem_bytes",
            "Device OpenCL C version": "opencl_c_version",
            "Driver version": "opencl_driver",
            "Version": "opencl_version",
        }
        for line in out.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                k = k.strip()
                v = v.strip()
                if k in target_keys and target_keys[k] not in extracted:
                    extracted[target_keys[k]] = v
        return extracted

    def refresh(self) -> list[dict[str, Any]]:
        self.devices = []
        self.probe_errors = []

        # 1. Query physical hardware from Windows WMI / CIM
        wmi_gpus = self._query_wmi_gpus()
        clinfo_data = self._query_clinfo_details()

        for g in wmi_gpus:
            name = g.get("Name") or "Unknown GPU"
            vendor = "AMD" if "amd" in name.lower() or "radeon" in name.lower() else (
                "NVIDIA" if "nvidia" in name.lower() or "geforce" in name.lower() else (
                    "Intel" if "intel" in name.lower() or "arc" in name.lower() else "GPU"
                )
            )

            # Calculate dedicated adapter VRAM
            adapter_ram = g.get("AdapterRAM") or 0
            vram_mb = round(adapter_ram / (1024 * 1024)) if adapter_ram > 0 else 0

            # If WMI reports low dedicated VRAM (e.g. APU / unified memory), enrich from clinfo global memory
            cl_global_bytes = int(clinfo_data.get("global_mem_bytes", 0)) if clinfo_data.get("global_mem_bytes", "").isdigit() else 0
            if cl_global_bytes > 0:
                unified_mem_mb = round(cl_global_bytes / (1024 * 1024))
            else:
                unified_mem_mb = vram_mb

            driver_ver = g.get("DriverVersion") or clinfo_data.get("opencl_driver") or "Unknown"
            problem_code = g.get("ConfigManagerErrorCode")
            try:
                driver_loaded = int(problem_code) == 0 if problem_code is not None else (
                    str(g.get("Status", "")).casefold() == "ok" and driver_ver != "Unknown"
                )
            except (TypeError, ValueError):
                driver_loaded = False
            driver_status = (
                "Loaded and device healthy"
                if driver_loaded
                else f"Device problem code {problem_code}"
                if problem_code not in (None, 0, "0")
                else "Driver status unavailable"
            )
            display_mode = g.get("VideoModeDescription") or "Unknown"
            refresh_rate = f"{g.get('CurrentRefreshRate')} Hz" if g.get("CurrentRefreshRate") else "Unknown"
            chip_processor = g.get("VideoProcessor") or clinfo_data.get("board_name") or name
            compute_units = clinfo_data.get("compute_units") or "N/A"
            clock_mhz = clinfo_data.get("clock_frequency") or "N/A"
            device_id = g.get("PNPDeviceID") or "N/A"

            # Determine compute backend availability
            if vendor == "NVIDIA" and shutil.which("nvidia-smi"):
                backend = "WDDM"
            elif clinfo_data:
                backend = "OpenCL"
            else:
                backend = "WDDM" if driver_loaded else "Unavailable"

            self.devices.append({
                "vendor": vendor,
                "name": name,
                "chip": chip_processor,
                "memory_dedicated_mb": vram_mb,
                "memory_available_mb": unified_mem_mb,
                "driver": driver_ver,
                "display_mode": display_mode,
                "refresh_rate": refresh_rate,
                "compute_units": compute_units,
                "clock": clock_mhz,
                "device_id": device_id,
                "status": driver_status,
                "driver_status": driver_status,
                "driver_loaded": driver_loaded,
                "memory_used_mb": "Unknown",
                "memory_free_mb": "Unknown",
                "utilization_pct": "Unknown",
                "backend": backend,
            })

        # 2. Query the NVIDIA driver directly; tool presence alone is not proof it works.
        nvidia_out = self._run([
            "nvidia-smi",
            "--query-gpu=name,memory.total,memory.used,memory.free,driver_version,clocks.current.graphics,utilization.gpu",
            "--format=csv,noheader",
        ])
        if shutil.which("nvidia-smi") and not nvidia_out:
            self.probe_errors.append("nvidia-smi is installed but did not return GPU driver telemetry.")
        if nvidia_out:
            for row in nvidia_out.splitlines():
                parts = [p.strip() for p in row.split(",")]
                if parts:
                    n_name = parts[0]
                    found = False
                    for d in self.devices:
                        if d["vendor"] == "NVIDIA":
                            d["name"] = n_name
                            d["memory_dedicated_mb"] = parts[1] if len(parts) > 1 else d["memory_dedicated_mb"]
                            d["memory_available_mb"] = parts[1] if len(parts) > 1 else d["memory_available_mb"]
                            d["memory_used_mb"] = parts[2] if len(parts) > 2 else "Unknown"
                            d["memory_free_mb"] = parts[3] if len(parts) > 3 else "Unknown"
                            d["driver"] = parts[4] if len(parts) > 4 else d["driver"]
                            d["clock"] = parts[5] if len(parts) > 5 else d["clock"]
                            d["utilization_pct"] = parts[6] if len(parts) > 6 else "Unknown"
                            d["backend"] = "CUDA"
                            d["driver_loaded"] = True
                            d["driver_status"] = "NVIDIA driver responded to nvidia-smi"
                            d["status"] = d["driver_status"]
                            found = True
                            break
                    if not found:
                        total = parts[1] if len(parts) > 1 else "Unknown"
                        driver = parts[4] if len(parts) > 4 else "Unknown"
                        self.devices.append({
                            "vendor": "NVIDIA",
                            "name": n_name,
                            "chip": n_name,
                            "memory_dedicated_mb": total,
                            "memory_available_mb": total,
                            "memory_used_mb": parts[2] if len(parts) > 2 else "Unknown",
                            "memory_free_mb": parts[3] if len(parts) > 3 else "Unknown",
                            "driver": driver,
                            "display_mode": "Active Output",
                            "refresh_rate": "Dynamic",
                            "compute_units": "N/A",
                            "clock": parts[5] if len(parts) > 5 else "N/A",
                            "utilization_pct": parts[6] if len(parts) > 6 else "Unknown",
                            "device_id": "PCI",
                            "status": "NVIDIA driver responded to nvidia-smi",
                            "driver_status": "NVIDIA driver responded to nvidia-smi",
                            "driver_loaded": True,
                            "backend": "CUDA",
                        })

        # 3. Fallback if no devices detected via WMI (non-Windows or stripped environment)
        if not self.devices:
            if clinfo_data:
                b_name = clinfo_data.get("board_name") or "OpenCL GPU Device"
                vendor = "AMD" if "amd" in b_name.lower() or "radeon" in b_name.lower() else "GPU"
                cl_mem = round(int(clinfo_data.get("global_mem_bytes", 0)) / (1024 * 1024)) if clinfo_data.get("global_mem_bytes", "").isdigit() else 0
                self.devices.append({
                    "vendor": vendor,
                    "name": b_name,
                    "chip": b_name,
                    "memory_dedicated_mb": cl_mem,
                    "memory_available_mb": cl_mem,
                    "driver": clinfo_data.get("opencl_driver", "OpenCL"),
                    "display_mode": "Standard",
                    "refresh_rate": "Unknown",
                    "compute_units": clinfo_data.get("compute_units", "N/A"),
                    "clock": clinfo_data.get("clock_frequency", "N/A"),
                    "device_id": "N/A",
                    "status": "OK",
                    "driver_status": "OpenCL device responded to clinfo",
                    "driver_loaded": True,
                    "memory_used_mb": "Unknown",
                    "memory_free_mb": "Unknown",
                    "utilization_pct": "Unknown",
                    "backend": "OpenCL",
                })

        return self.devices

    def status(self) -> dict[str, Any]:
        devices = self.refresh()
        ai_ready = any(
            device.get("driver_loaded")
            and device.get("backend") in {"CUDA", "ROCm", "OpenCL"}
            for device in devices
        )
        return {
            "devices": devices,
            "cuda_tool": shutil.which("nvidia-smi"),
            "rocm_tool": shutil.which("rocminfo"),
            "ai_ready": ai_ready,
            "errors": self.probe_errors,
        }

    def select_backend(self) -> str:
        if any(d.get("backend") == "CUDA" for d in self.devices):
            return "CUDA"
        if any(d.get("backend") == "ROCm" for d in self.devices):
            return "ROCm"
        if any(d.get("backend") == "OpenCL" for d in self.devices):
            return "OpenCL"
        if any(d.get("backend") == "WDDM" and d.get("driver_loaded") for d in self.devices):
            return "DirectX / WDDM (host driver)"
        return "DirectX / CPU"

    def probe_compute(self) -> dict[str, Any]:
        """Perform comprehensive GPU hardware and compute probe."""
        devices = self.refresh()
        backend = self.select_backend()
        live = any(device.get("driver_loaded", False) for device in devices)
        return {"backend": backend, "devices": devices, "live": live, "errors": self.probe_errors}

    def environment(self) -> dict[str, str]:
        """Return safe environment hints for launching GPU-aware programs."""
        backend = self.select_backend()
        env = {"OPERATOR_GPU_BACKEND": backend}
        if backend == "CUDA":
            env["CUDA_VISIBLE_DEVICES"] = os.environ.get("CUDA_VISIBLE_DEVICES", "0")
        elif backend == "ROCm":
            env["HIP_VISIBLE_DEVICES"] = os.environ.get("HIP_VISIBLE_DEVICES", "0")
            env["ROCR_VISIBLE_DEVICES"] = os.environ.get("ROCR_VISIBLE_DEVICES", "0")
        elif backend == "OpenCL":
            env["OPERATOR_OPENCL_DEVICE"] = "0"
        return env

    def launch_command(self, executable: str, args: list[str] | None = None, cwd: str | Path | None = None) -> subprocess.Popen:
        """Launch a game or compute executable with detected GPU visibility."""
        command = [executable, *(args or [])]
        env = os.environ.copy()
        env.update(self.environment())
        return subprocess.Popen(command, cwd=str(cwd) if cwd else None, env=env)
