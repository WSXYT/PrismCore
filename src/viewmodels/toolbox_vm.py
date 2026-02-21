"""工具箱视图模型 — 网络工具的后台执行。"""

from PySide6.QtCore import QObject, QThread, Signal

from src.models.network import flush_dns, reset_winsock, reset_tcp_ip


class _ToolWorker(QThread):
    """通用工具执行线程。"""

    progress = Signal(str)
    finished = Signal(str)

    def __init__(self, action: str, parent=None):
        super().__init__(parent)
        self._action = action

    def run(self):
        handlers = {
            "dns": self._dns,
            "winsock": self._winsock,
            "tcp": self._tcp,
        }
        fn = handlers.get(self._action)
        if fn:
            fn()
        else:
            self.finished.emit("未知操作")

    def _dns(self):
        ok = flush_dns()
        self.finished.emit("DNS 缓存已刷新" if ok else "DNS 刷新失败")

    def _winsock(self):
        ok = reset_winsock()
        self.finished.emit(
            "Winsock 已重置（需重启生效）" if ok else "Winsock 重置失败",
        )

    def _tcp(self):
        ok = reset_tcp_ip()
        self.finished.emit(
            "TCP/IP 已重置（需重启生效）" if ok else "TCP/IP 重置失败",
        )


class ToolboxViewModel(QObject):
    """工具箱视图模型。"""

    tool_progress = Signal(str)
    tool_done = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: _ToolWorker | None = None

    def run_tool(self, action: str):
        """执行指定工具操作。"""
        if self._worker and self._worker.isRunning():
            return
        self._worker = _ToolWorker(action)
        self._worker.progress.connect(self.tool_progress.emit)
        self._worker.finished.connect(self.tool_done.emit)
        self._worker.start()
