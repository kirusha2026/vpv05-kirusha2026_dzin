"""Windows toast notifications and always-on-top popup windows."""

from __future__ import annotations

import subprocess
import sys
import threading
from typing import Callable

from database import Reminder

PopupCallback = Callable[[Reminder], None]


def _show_winotify(title: str, message: str) -> bool:
    try:
        from winotify import Notification, audio
    except ImportError:
        return False
    toast = Notification(
        app_id="DzinReminder",
        title=title,
        msg=message or "Наступило время напоминания",
        duration="long",
    )
    toast.set_audio(audio.Default, loop=False)
    toast.show()
    return True


def _show_win10toast(title: str, message: str) -> bool:
    try:
        from win10toast import ToastNotifier
    except ImportError:
        return False
    toaster = ToastNotifier()
    toaster.show_toast(
        title,
        message or "Наступило время напоминания",
        duration=8,
        threaded=True,
    )
    return True


def _show_powershell_toast(title: str, message: str) -> bool:
    """Fallback toast via Windows Runtime from PowerShell."""
    if sys.platform != "win32":
        return False
    def _xml(text: str) -> str:
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("'", "&apos;")
            .replace('"', "&quot;")
        )

    safe_title = _xml(title)[:120]
    safe_msg = _xml(message or "Наступило время напоминания")[:240]
    script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$template = @"
<toast>
  <visual>
    <binding template="ToastGeneric">
      <text>{safe_title}</text>
      <text>{safe_msg}</text>
    </binding>
  </visual>
</toast>
"@
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($template)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('DzinReminder').Show($toast)
"""
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            check=False,
            capture_output=True,
            timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        return True
    except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
        return False


def show_system_notification(title: str, message: str) -> None:
    """Показать системное уведомление Windows, не блокируя GUI."""

    def _run() -> None:
        if _show_winotify(title, message):
            return
        if _show_win10toast(title, message):
            return
        _show_powershell_toast(title, message)

    threading.Thread(target=_run, daemon=True).start()


class NotificationService:
    """Планировщик: помечает просроченные и вызывает callback на главном потоке Tk."""

    def __init__(
        self,
        store,
        on_due: PopupCallback,
        interval_ms: int = 2000,
    ) -> None:
        self.store = store
        self.on_due = on_due
        self.interval_ms = interval_ms
        self._root = None
        self._running = False

    def start(self, root) -> None:
        self._root = root
        self._running = True
        self._tick()

    def stop(self) -> None:
        self._running = False

    def _tick(self) -> None:
        if not self._running or self._root is None:
            return
        try:
            due = self.store.mark_overdue()
            for reminder in due:
                self.store.mark_notified(reminder.id)
                show_system_notification(reminder.title, reminder.description)
                self.on_due(reminder)
        except Exception:
            # Не даём сбою проверки остановить цикл
            pass
        self._root.after(self.interval_ms, self._tick)
