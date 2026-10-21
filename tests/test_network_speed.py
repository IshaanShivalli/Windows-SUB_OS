import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from network.speed_test import NetworkSpeedTester
from shell.opshell import OperatorShellEngine


class NetworkSpeedTesterTests(unittest.TestCase):
    def test_measures_download_and_upload_throughput(self):
        network = Mock()
        network.http_request.side_effect = [
            {"status_code": 200, "body": b"x" * 1_000_000},
            {"status_code": 200, "body": b"ok"},
        ]
        tester = NetworkSpeedTester(network)

        with patch("network.speed_test.time.perf_counter", side_effect=[10, 12, 20, 24]):
            download = tester.measure_download()
            upload = tester.measure_upload()

        self.assertEqual(download["mbps"], 4)
        self.assertEqual(upload["mbps"], 2)
        get_call, post_call = network.http_request.call_args_list
        self.assertEqual(get_call.args[0], "GET")
        self.assertIn("speed.cloudflare.com/__down?bytes=1000000", get_call.args[1])
        self.assertEqual(post_call.args[0], "POST")
        self.assertIn("speed.cloudflare.com/__up?bytes=1000000", post_call.args[1])
        self.assertEqual(len(post_call.kwargs["data"]), 1_000_000)

    def test_rejects_unsuccessful_speed_test_responses(self):
        network = Mock()
        network.http_request.return_value = {"status_code": 503, "body": b"unavailable"}
        tester = NetworkSpeedTester(network)

        with patch("network.speed_test.time.perf_counter", side_effect=[1, 2]):
            with self.assertRaisesRegex(RuntimeError, "HTTP 503"):
                tester.measure_download()

    def test_net_speed_returns_to_shell_on_ctrl_c(self):
        shell = OperatorShellEngine.__new__(OperatorShellEngine)
        shell.variables = {"SYS.USER": "operator"}
        shell.network = Mock()
        live = Mock()
        live_context = MagicMock()
        live_context.__enter__.return_value = live
        tester = Mock()
        tester.measure_download.side_effect = KeyboardInterrupt

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch("shell.opshell.ROOT_DIR", Path(temp_dir)),
            patch("shell.opshell.Live", return_value=live_context),
            patch("shell.opshell.NetworkSpeedTester", return_value=tester),
        ):
            result = shell.eval_command("net.speed")

        self.assertIn("SPEED TEST STOPPED", result)
        self.assertIn("Download average: N/A", result)
        self.assertIn("Upload average: N/A", result)

    def test_net_speed_runs_the_native_binary_when_it_is_built(self):
        shell = OperatorShellEngine.__new__(OperatorShellEngine)
        shell.variables = {"SYS.USER": "operator"}
        with tempfile.TemporaryDirectory() as temp_dir:
            bin_dir = Path(temp_dir) / "bin"
            bin_dir.mkdir()
            native_binary = bin_dir / "net_speed.exe"
            native_binary.touch()
            with (
                patch("shell.opshell.ROOT_DIR", Path(temp_dir)),
                patch("shell.opshell.subprocess.run") as run_process,
            ):
                run_process.return_value.returncode = 0
                result = shell.eval_command("net.speed")

        self.assertIn("C++ SPEED TEST", result)
        run_process.assert_called_once_with([str(native_binary)], check=False)

    def test_native_net_speed_ctrl_c_returns_to_shell(self):
        shell = OperatorShellEngine.__new__(OperatorShellEngine)
        shell.variables = {"SYS.USER": "operator"}
        with tempfile.TemporaryDirectory() as temp_dir:
            bin_dir = Path(temp_dir) / "bin"
            bin_dir.mkdir()
            (bin_dir / "net_speed.exe").touch()
            with (
                patch("shell.opshell.ROOT_DIR", Path(temp_dir)),
                patch(
                    "shell.opshell.subprocess.run",
                    side_effect=KeyboardInterrupt,
                ),
            ):
                result = shell.eval_command("net.speed")

        self.assertIn("interrupted by Ctrl+C", result)


if __name__ == "__main__":
    unittest.main()
