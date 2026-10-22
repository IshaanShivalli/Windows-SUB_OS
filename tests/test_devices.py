import json
import subprocess
import unittest
from unittest.mock import patch

from core.devices.device_manager import DeviceManager
from shell.opshell import OperatorShellEngine


class DeviceManagerTests(unittest.TestCase):
    def setUp(self):
        self.manager = DeviceManager()
        self.manager.powershell = "powershell"

    def test_classifies_usb_display_and_audio_hardware(self):
        self.assertEqual(
            self.manager._category(
                {"class": "USB", "instance_id": "USB\\VID_0BDA&PID_5574"}
            ),
            "USB",
        )
        self.assertEqual(
            self.manager._category(
                {"class": "Display", "instance_id": "PCI\\VEN_1002"}
            ),
            "Display",
        )
        self.assertEqual(
            self.manager._category(
                {
                    "class": "MEDIA",
                    "name": "AMD High Definition Audio Device",
                    "instance_id": "HDAUDIO\\FUNC_01&VEN_1002&DEV_AA01",
                }
            ),
            "HDMI audio",
        )
        self.assertEqual(
            self.manager._category(
                {
                    "class": "MEDIA",
                    "name": "Realtek(R) Audio",
                    "instance_id": "HDAUDIO\\FUNC_01&VEN_10EC&DEV_0236",
                }
            ),
            "AUX audio",
        )

    @patch("core.devices.device_manager.os.name", "nt")
    @patch("core.devices.device_manager.subprocess.run")
    def test_lists_device_details_and_filters_audio_to_include_hdmi_audio(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=["powershell"],
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "class": "Display",
                        "name": "AMD Radeon(TM) Graphics",
                        "status": "OK",
                        "instance_id": "PCI\\VEN_1002&DEV_1506",
                        "driver_provider": "Advanced Micro Devices, Inc.",
                        "driver_version": "31.0.0.0",
                    },
                    {
                        "class": "MEDIA",
                        "name": "AMD High Definition Audio Device",
                        "status": "OK",
                        "instance_id": "HDAUDIO\\FUNC_01&VEN_1002&DEV_AA01",
                        "driver_provider": "Advanced Micro Devices, Inc.",
                        "driver_version": "10.0.1.0",
                    },
                ]
            ),
            stderr="",
        )

        devices = self.manager.list_devices("audio")

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["category"], "HDMI audio")
        self.assertEqual(devices[0]["driver_provider"], "Advanced Micro Devices, Inc.")
        self.assertEqual(run.call_args.kwargs["timeout"], 30)

    @patch("core.devices.device_manager.os.name", "nt")
    @patch("core.devices.device_manager.subprocess.run")
    def test_reports_powershell_failures(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=["powershell"], returncode=1, stdout="", stderr="PnP query failed"
        )

        with self.assertRaisesRegex(RuntimeError, "PnP query failed"):
            self.manager.list_devices()


class DeviceCommandTests(unittest.TestCase):
    def test_device_list_command_renders_host_device_and_driver_info(self):
        shell = OperatorShellEngine.__new__(OperatorShellEngine)

        class StubDeviceManager:
            def list_devices(self, category=None):
                self.category = category
                return [
                    {
                        "category": "USB",
                        "name": "USB Composite Device",
                        "status": "OK",
                        "driver_provider": "Microsoft",
                        "driver_version": "10.0.1",
                        "instance_id": "USB\\VID_0BDA&PID_5574",
                    }
                ]

        shell.device_manager = StubDeviceManager()
        output = shell.eval_command("device.list usb")

        self.assertIn("USB Composite Device", output)
        self.assertIn("USB\\VID_0BDA", output)
        self.assertIn("Windows host drivers", output)
        self.assertEqual(shell.device_manager.category, "usb")

    def test_device_list_rejects_unknown_category(self):
        shell = OperatorShellEngine.__new__(OperatorShellEngine)

        self.assertEqual(
            shell.eval_command("device.list hdmi"),
            "Device category must be usb, display, or audio.",
        )


if __name__ == "__main__":
    unittest.main()
