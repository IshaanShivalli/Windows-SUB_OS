"""Python command adapter for the native C++ service and scheduler runtime."""

import ctypes
import json
import os
import shlex
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent.parent
RUNTIME_PATH = ROOT_DIR / "bin" / "atlas_service_runtime.dll"
_DLL_DIRECTORY = (
    os.add_dll_directory(str(RUNTIME_PATH.parent))
    if sys.platform == "win32" and RUNTIME_PATH.parent.is_dir()
    else None
)
JOB_CALLBACK = ctypes.CFUNCTYPE(
    None,
    ctypes.c_char_p,
    ctypes.c_char_p,
    ctypes.c_char_p,
    ctypes.POINTER(ctypes.c_char),
    ctypes.c_size_t,
)


class ServiceManager:
    def __init__(self, storage=None, job_runner=None):
        self.storage = storage
        self.job_runner = job_runner
        if not RUNTIME_PATH.is_file():
            raise RuntimeError(
                "Native C++ service runtime is not built. Run `python build.py`."
            )
        self._library = ctypes.CDLL(str(RUNTIME_PATH))
        self._configure_api()
        root = (
            Path(storage.get_os_root())
            if storage is not None
            else Path(
                os.environ.get(
                    "OPERATOR_OS_ROOT_PATH",
                    ROOT_DIR / "storage" / "operator_os_root",
                )
            )
        )
        self._job_callback = JOB_CALLBACK(self._run_scheduled_job)
        self._handle = self._library.atlas_runtime_create(
            os.fsencode(root / "var" / "lib" / "services"),
            self._job_callback,
        )
        if not self._handle:
            raise RuntimeError("The C++ service runtime failed to initialize.")

    def _configure_api(self):
        library = self._library
        library.atlas_runtime_create.argtypes = [ctypes.c_char_p, JOB_CALLBACK]
        library.atlas_runtime_create.restype = ctypes.c_void_p
        library.atlas_runtime_destroy.argtypes = [ctypes.c_void_p]
        for name, argument_count in (
            ("atlas_service_register", 5),
            ("atlas_service_start", 1),
            ("atlas_service_stop", 1),
            ("atlas_service_remove", 1),
            ("atlas_service_list", 0),
            ("atlas_service_logs", 2),
            ("atlas_job_add", 4),
            ("atlas_job_remove", 1),
            ("atlas_job_list", 0),
            ("atlas_job_logs", 2),
        ):
            function = getattr(library, name)
            function.argtypes = [ctypes.c_void_p] + [ctypes.c_char_p] * argument_count
            function.restype = ctypes.c_char_p

    @staticmethod
    def _decode(result):
        return result.decode("utf-8", errors="replace") if result else ""

    def _call(self, function, *arguments):
        return self._decode(function(self._handle, *(os.fsencode(arg) for arg in arguments)))

    def _run_scheduled_job(self, name, owner, command, output, output_capacity):
        result = "Scheduled job runner is not configured."
        if self.job_runner is not None:
            try:
                result = str(self.job_runner(
                    name.decode("utf-8"),
                    owner.decode("utf-8"),
                    command.decode("utf-8"),
                ) or "Completed.")
            except Exception as exc:
                result = f"Scheduled job failed: {exc}"
        encoded = result.encode("utf-8", errors="replace")[:max(0, output_capacity - 1)]
        if output_capacity:
            ctypes.memmove(output, encoded, len(encoded))
            output[len(encoded)] = b"\0"

    def register(self, name, command, description="", restart_policy="always", health_check=""):
        command_line = command if isinstance(command, str) else subprocess_command_line(command)
        return self._call(
            self._library.atlas_service_register,
            name,
            description or name,
            command_line,
            restart_policy,
            health_check,
        )

    def start(self, name):
        return self._call(self._library.atlas_service_start, name)

    def restart(self, name):
        stopped = self.stop(name)
        if stopped.startswith("[SRV ERROR]"):
            return stopped
        return self.start(name)

    def stop(self, name):
        return self._call(self._library.atlas_service_stop, name)

    def remove(self, name):
        return self._call(self._library.atlas_service_remove, name)

    def list_services(self):
        data = json.loads(self._call(self._library.atlas_service_list))
        return data

    def get_logs(self, name, limit=100):
        return json.loads(self._call(self._library.atlas_service_logs, name, str(limit)))

    def add_job(self, name, owner, interval_seconds, command):
        return self._call(
            self._library.atlas_job_add,
            name,
            owner,
            str(interval_seconds),
            command,
        )

    def remove_job(self, name):
        return self._call(self._library.atlas_job_remove, name)

    def list_jobs(self):
        return json.loads(self._call(self._library.atlas_job_list))

    def get_job_logs(self, name, limit=100):
        return json.loads(self._call(self._library.atlas_job_logs, name, str(limit)))

    def close(self):
        if self._handle:
            self._library.atlas_runtime_destroy(self._handle)
            self._handle = None


def subprocess_command_line(command):
    import subprocess

    return subprocess.list2cmdline(list(command))
