import json
import platform
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import boot


class BootShellTests(unittest.TestCase):
    def test_shell_launcher_waits_cleanly_after_ctrl_c(self):
        process = Mock()
        process.wait.side_effect = [KeyboardInterrupt, 0]

        with patch.object(boot.subprocess, "Popen", return_value=process) as popen:
            result = boot._run_shell(boot.ROOT_DIR / "shell" / "opshell.py", {})

        self.assertEqual(result, 0)
        self.assertEqual(process.wait.call_count, 2)
        self.assertEqual(popen.call_args.kwargs["cwd"], boot.ROOT_DIR)

    def test_boot_prefers_packaged_runtime_and_shares_virtual_storage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            system = root / "storage" / "operator_os_root" / "System"
            system.mkdir(parents=True)
            (system / "boot.pyc").write_bytes(b"bytecode")
            (system / "runtime_manifest.json").write_text(
                json.dumps(
                    {
                        "python_implementation": platform.python_implementation(),
                        "python_version": ".".join(map(str, sys.version_info[:3])),
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(boot, "ROOT_DIR", root),
                patch.object(boot.subprocess, "call", return_value=0) as run,
            ):
                result = boot.main(["--verbose"])

        self.assertEqual(result, 0)
        self.assertEqual(
            run.call_args.args[0],
            [sys.executable, str(system / "boot.pyc"), "--verbose"],
        )
        environment = run.call_args.kwargs["env"]
        self.assertEqual(environment["OPERATOR_OS_ROOT_PATH"], str(system.parent))
        self.assertEqual(
            environment["OPERATOR_STORAGE_IMAGE"],
            str(root / "storage" / "operator_storage_2gb.img"),
        )


if __name__ == "__main__":
    unittest.main()
