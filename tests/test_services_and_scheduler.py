import json
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from core.services import service_manager
from shell.opshell import OperatorShellEngine


class FakeStorage:
    def __init__(self, root):
        self.root = root

    def get_os_root(self):
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root


class ShellServiceCommandTests(unittest.TestCase):
    def create_shell(self, username="operator"):
        shell = OperatorShellEngine.__new__(OperatorShellEngine)
        shell.variables = {
            "SYS.USER": username,
            "SYS.CWD": f"/Users/{username}/home",
        }
        shell.services = Mock()
        shell.services.register.return_value = "[SRV REGISTERED] web (always)"
        shell.services.add_job.return_value = "[CRON ADDED] cleanup"
        shell.services.list_jobs.return_value = []
        shell.service_runtime_error = None
        return shell

    def test_scheduled_job_command_is_restricted_to_safe_atlas_actions(self):
        shell = self.create_shell()

        result = shell.eval_command("cron.add cleanup 60 rm -r Users")

        self.assertIn("restricted", result)
        shell.services.add_job.assert_not_called()

    def test_system_backup_and_cleanup_jobs_require_root(self):
        shell = self.create_shell("operator")

        backup = shell.eval_command("cron.add backup 60 backup.create daily")
        cleanup = shell.eval_command("cron.add cleanup 60 storage.cleanup 7")

        self.assertIn("superuser", backup)
        self.assertIn("superuser", cleanup)
        shell.services.add_job.assert_not_called()

    def test_scheduled_job_is_owned_by_current_user(self):
        shell = self.create_shell("operator")

        result = shell.eval_command("cron.add backup 60 echo daily")

        self.assertIn("CRON ADDED", result)
        shell.services.add_job.assert_called_once_with(
            "backup",
            "operator",
            60,
            "echo daily",
        )

    def test_service_registration_requires_root(self):
        shell = self.create_shell("operator")

        result = shell.eval_command(
            'srv.register web --restart always --health process -- python -c "pass"'
        )

        self.assertIn("PERMISSION DENIED", result)
        shell.services.register.assert_not_called()

    def test_root_can_register_a_native_service(self):
        shell = self.create_shell("root")

        result = shell.eval_command(
            'srv.register web --restart always --health process -- python -c "pass"'
        )

        self.assertIn("REGISTERED", result)
        shell.services.register.assert_called_once_with(
            "web",
            ["python", "-c", "pass"],
            "web",
            "always",
            "process",
        )
        shell.services.start.assert_called_once_with("web")

    def test_job_runner_revalidates_command_before_execution(self):
        shell = self.create_shell()
        shell.user_mgr = Mock()
        shell.user_mgr.get_user.return_value = {"username": "operator"}
        shell._validate_scheduled_command = Mock(return_value="unsafe command")

        result = shell._run_scheduled_job("job", "operator", "rm -r /")

        self.assertIn("REJECTED", result)
        shell._validate_scheduled_command.assert_called_once_with("rm -r /", "operator")

    def test_root_can_create_restore_point_and_cleanup_jobs(self):
        shell = self.create_shell("root")
        shell.services.list_jobs.return_value = []
        shell._validate_scheduled_command = Mock(return_value=None)
        shell.services.add_job.return_value = "[CRON ADDED]"

        result = shell.eval_command("cron.add backup 86400 backup.create daily")

        self.assertEqual(result, "[CRON ADDED]")
        shell.services.add_job.assert_called_once_with(
            "backup",
            "root",
            86400,
            "backup.create daily",
        )


@unittest.skipUnless(
    service_manager.RUNTIME_PATH.is_file(),
    "Build the C++ service runtime with `python build.py` before running native runtime tests",
)
class NativeServiceRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name) / "operator_os_root"
        self.storage = FakeStorage(self.root)
        self.job_event = threading.Event()
        self.job_runs = []

        def run_job(name, owner, command):
            self.job_runs.append((name, owner, command))
            self.job_event.set()
            return f"executed: {command}"

        self.manager = service_manager.ServiceManager(
            storage=self.storage,
            job_runner=run_job,
        )
        self.addCleanup(self.manager.close)

    def wait_for(self, predicate, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.1)
        return predicate()

    def test_native_process_is_started_stopped_and_logged(self):
        message = "atlas-managed-service"
        result = self.manager.register(
            "worker",
            [sys.executable, "-u", "-c", f"import time; print('{message}', flush=True); time.sleep(30)"],
            "test worker",
            "no",
            "process",
        )
        self.assertIn("REGISTERED", result)
        self.assertIn("STARTING", self.manager.start("worker"))
        self.assertTrue(
            self.wait_for(
                lambda: any(item["pid"] for item in self.manager.list_services())
            )
        )
        self.assertTrue(
            self.wait_for(
                lambda: message in "\n".join(self.manager.get_logs("worker"))
            )
        )

        self.assertIn("STOPPED", self.manager.stop("worker"))
        service = next(item for item in self.manager.list_services() if item["unit"] == "worker")
        self.assertEqual(service["active"], "inactive")
        self.assertFalse(service["pid"])
        self.assertIn("Stopped by operator", "\n".join(self.manager.get_logs("worker")))

    def test_tcp_health_check_reports_a_real_listening_endpoint(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(0.2)
        self.addCleanup(listener.close)
        stop_accepting = threading.Event()

        def accept_connections():
            while not stop_accepting.is_set():
                try:
                    connection, _ = listener.accept()
                    connection.close()
                except socket.timeout:
                    continue
                except OSError:
                    return

        thread = threading.Thread(target=accept_connections, daemon=True)
        thread.start()
        self.addCleanup(stop_accepting.set)

        self.manager.register(
            "tcp-worker",
            [sys.executable, "-c", "import time; time.sleep(30)"],
            "tcp health test",
            "no",
            f"tcp:127.0.0.1:{listener.getsockname()[1]}",
        )
        self.manager.start("tcp-worker")

        self.assertTrue(
            self.wait_for(
                lambda: any(
                    item["unit"] == "tcp-worker" and item["sub"] == "healthy"
                    for item in self.manager.list_services()
                )
            )
        )
        self.manager.stop("tcp-worker")

    def test_on_failure_policy_restarts_a_failed_process(self):
        self.manager.register(
            "flaky",
            [sys.executable, "-c", "raise SystemExit(1)"],
            "restart test",
            "on-failure",
            "process",
        )

        self.manager.start("flaky")

        self.assertTrue(
            self.wait_for(
                lambda: any(
                    item["unit"] == "flaky" and item["restart_count"] >= 1
                    for item in self.manager.list_services()
                )
            )
        )
        self.assertIn("Stopped", self.manager.stop("flaky"))

    def test_service_definitions_and_job_schedules_persist(self):
        self.manager.register("persistent", [sys.executable, "-c", "pass"], "persistent test")
        self.manager.add_job("backup", "operator", 30, "backup.create daily")
        self.manager.close()

        restored = service_manager.ServiceManager(storage=self.storage)
        self.addCleanup(restored.close)
        service = next(item for item in restored.list_services() if item["unit"] == "persistent")
        job = next(item for item in restored.list_jobs() if item["name"] == "backup")
        self.assertEqual(service["restart"], "always")
        self.assertEqual(job["owner"], "operator")
        self.assertEqual(job["command"], "backup.create daily")

    def test_persisted_services_start_automatically_with_the_runtime(self):
        self.manager.register(
            "auto-start",
            [sys.executable, "-u", "-c", "import time; time.sleep(30)"],
            "automatic startup test",
            "always",
            "process",
        )
        self.manager.close()

        restored = service_manager.ServiceManager(storage=self.storage)
        self.addCleanup(restored.close)

        self.assertTrue(
            self.wait_for(
                lambda: any(
                    item["unit"] == "auto-start"
                    and item["active"] == "active"
                    and item["pid"]
                    for item in restored.list_services()
                )
            )
        )

    def test_scheduled_job_runs_and_writes_persistent_logs(self):
        self.manager.add_job("heartbeat", "operator", 10, "echo scheduled")

        self.assertTrue(self.job_event.wait(timeout=12))
        self.assertEqual(
            self.job_runs,
            [("heartbeat", "operator", "echo scheduled")],
        )
        self.assertTrue(
            self.wait_for(
                lambda: any(
                    "executed: echo scheduled" in line
                    for line in self.manager.get_job_logs("heartbeat")
                )
            )
        )

    def test_invalid_service_policy_or_job_interval_is_rejected(self):
        self.assertIn(
            "[SRV ERROR]",
            self.manager.register("bad", [sys.executable], restart_policy="forever"),
        )
        self.assertIn(
            "[CRON ERROR]",
            self.manager.add_job("too-fast", "operator", 0, "echo no"),
        )


if __name__ == "__main__":
    unittest.main()
