import os
import subprocess
import ctypes
from typing import Optional

class WindowsIntegrationLayer:
    """
    Direct Windows Host Integration Layer:
    - Native Clipboard Read / Write
    - Windows Toast / PowerShell Notifications
    - Windows Environment Variables inspection
    - Windows Terminal launch integration
    - Launching native Windows GUI applications (Notepad, Explorer, Taskmgr, Calc)
    """

    @staticmethod
    def get_clipboard() -> str:
        try:
            # Fast PowerShell clipboard retrieval
            res = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard"], capture_output=True, text=True, timeout=5)
            return res.stdout.strip()
        except:
            return ""

    @staticmethod
    def set_clipboard(text: str) -> bool:
        try:
            p = subprocess.Popen(["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value $input"], stdin=subprocess.PIPE, text=True)
            p.communicate(input=text)
            return p.returncode == 0
        except:
            return False

    @staticmethod
    def show_notification(title: str, message: str) -> bool:
        ps_cmd = f"""
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
        $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
        $textNodes = $template.GetElementsByTagName('text')
        $textNodes.Item(0).AppendChild($template.CreateTextNode('{title}')) > $null
        $textNodes.Item(1).AppendChild($template.CreateTextNode('{message}')) > $null
        $toast = [Windows.UI.Notifications.ToastNotification]::new($template)
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Operator OS').Show($toast)
        """
        try:
            subprocess.Popen(["powershell", "-NoProfile", "-Command", ps_cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except:
            return False

    @staticmethod
    def get_env_var(name: str) -> Optional[str]:
        return os.environ.get(name)

    @staticmethod
    def launch_windows_app(app_name: str) -> str:
        app_name = app_name.lower().strip()
        common_apps = {
            "notepad": "notepad.exe",
            "explorer": "explorer.exe",
            "calc": "calc.exe",
            "taskmgr": "taskmgr.exe",
            "terminal": "wt.exe",
            "cmd": "cmd.exe",
            "powershell": "powershell.exe"
        }
        target = common_apps.get(app_name, app_name)
        try:
            subprocess.Popen(target, shell=True)
            return f"\033[1;32m[WIN EXEC]\033[0m Launched host application '{target}'"
        except Exception as e:
            return f"\033[31m[WIN ERR] Failed to launch '{target}': {str(e)}\033[0m"
