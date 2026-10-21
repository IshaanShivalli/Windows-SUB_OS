import unittest
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


if __name__ == "__main__":
    unittest.main()
