"""主窗口 — 四页导航：首页、清理、加速、工具箱。"""

from PySide6.QtCore import QSize, QTimer
from PySide6.QtWidgets import QApplication
from qfluentwidgets import (
    FluentWindow, FluentIcon, NavigationItemPosition,
    setTheme, Theme, NavigationAvatarWidget,
)

from src.views.dashboard_view import DashboardView
from src.views.cleaner_view import CleanerView
from src.views.optimizer_view import OptimizerView
from src.views.toolbox_view import ToolboxView
from src.views.settings_view import SettingsView
from src.viewmodels.dashboard_vm import DashboardViewModel
from src.viewmodels.cleaner_vm import CleanerViewModel
from src.viewmodels.optimizer_vm import OptimizerViewModel
from src.viewmodels.toolbox_vm import ToolboxViewModel
from src.utils.constants import APP_NAME, APP_VERSION


class MainWindow(FluentWindow):
    """应用主窗口，四页导航结构。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(1100, 720)
        self.setMinimumSize(QSize(860, 560))
        self._center_on_screen()
        setTheme(Theme.AUTO)

        # ── 视图 ─────────────────────────────────────
        self.dashboard_view = DashboardView(self)
        self.cleaner_view = CleanerView(self)
        self.optimizer_view = OptimizerView(self)
        self.toolbox_view = ToolboxView(self)
        self.settings_view = SettingsView(self)

        # ── 视图模型 ─────────────────────────────────
        self.dashboard_vm = DashboardViewModel(self)
        self.cleaner_vm = CleanerViewModel(self)
        self.optimizer_vm = OptimizerViewModel(self)
        self.toolbox_vm = ToolboxViewModel(self)

        self._init_navigation()
        self._connect_signals()
        self.dashboard_vm.start()

        # 页面切换动画完成后再加载数据，避免阻塞动画
        self.stackedWidget.view.aniFinished.connect(self._on_page_changed)

    # ── 导航 ─────────────────────────────────────────

    def _init_navigation(self):
        self.addSubInterface(
            self.dashboard_view, FluentIcon.HOME, "首页",
        )
        self.addSubInterface(
            self.cleaner_view, FluentIcon.DELETE, "清理",
        )
        self.addSubInterface(
            self.optimizer_view, FluentIcon.SPEED_HIGH, "加速",
        )
        self.addSubInterface(
            self.toolbox_view, FluentIcon.DEVELOPER_TOOLS, "工具箱",
        )
        self.navigationInterface.addWidget(
            "avatar",
            NavigationAvatarWidget("P", APP_NAME),
            lambda: None,
            NavigationItemPosition.BOTTOM,
        )
        self.addSubInterface(
            self.settings_view, FluentIcon.SETTING, "设置",
            NavigationItemPosition.BOTTOM,
        )

    # ── 信号连接 ─────────────────────────────────────

    def _connect_signals(self):
        # 首页
        self.dashboard_vm.status_updated.connect(
            self.dashboard_view.update_status,
        )
        self.dashboard_view.btn_optimize.clicked.connect(
            self._on_smart_optimize,
        )
        self.dashboard_vm.optimize_progress.connect(
            self.dashboard_view.set_progress_text,
        )
        self.dashboard_vm.optimize_done.connect(
            self._on_smart_optimize_done,
        )
        self.dashboard_vm.auto_action.connect(
            self.dashboard_view.show_auto_action,
        )
        # 分页文件状态卡片
        self.dashboard_vm.pagefile_status_changed.connect(
            self._on_pagefile_status,
        )
        self.dashboard_vm.pagefile_suggest.connect(
            self._on_pagefile_suggest,
        )
        dv = self.dashboard_view
        dv.pagefile_card.reboot_clicked.connect(
            self.dashboard_vm.request_reboot_clear,
        )
        dv.suggestion_card.accept_clicked.connect(
            self._on_accept_suggestion,
        )
        dv.suggestion_card.dismiss_clicked.connect(
            self.dashboard_vm.dismiss_suggestion,
        )
        dv.suggestion_card.cancel_clicked.connect(
            self.dashboard_vm.cancel_suggestion,
        )
        dv.suggestion_card.reboot_clicked.connect(
            self.dashboard_vm.request_reboot_clear,
        )

        # 清理
        self.cleaner_view.btn_scan.clicked.connect(self._on_scan)
        self.cleaner_view.btn_clean.clicked.connect(self._on_clean)
        self.cleaner_vm.scan_progress.connect(
            self.cleaner_view.set_status,
        )
        self.cleaner_vm.scan_done.connect(self._on_scan_done)
        self.cleaner_vm.clean_done.connect(self._on_clean_done)

        # 加速 — 内存
        self.optimizer_view.btn_optimize.clicked.connect(
            self._on_mem_optimize,
        )
        self.optimizer_view.btn_refresh.clicked.connect(
            self._on_refresh_boost,
        )
        self.optimizer_vm.optimize_progress.connect(
            self.optimizer_view.set_status,
        )
        self.optimizer_vm.optimize_done.connect(
            self._on_mem_optimize_done,
        )
        self.optimizer_vm.memory_updated.connect(
            self.optimizer_view.mem_card.set_data,
        )
        self.optimizer_vm.processes_updated.connect(
            lambda procs: self.optimizer_view.populate_processes(
                procs,
                on_boost=self._on_boost,
                on_throttle=self._on_throttle,
            ),
        )

        # 加速 — 启动项
        self.optimizer_view.btn_startup_refresh.clicked.connect(
            self.optimizer_vm.refresh_startup,
        )
        self.optimizer_vm.startup_loaded.connect(
            lambda items: self.optimizer_view.populate_startup(
                items, on_toggle=self._on_startup_toggle,
            ),
        )
        self.optimizer_vm.startup_toggled.connect(
            self.optimizer_view.show_result,
        )

        # 清理页清理进度
        self.cleaner_vm.clean_progress.connect(
            self.cleaner_view.set_status,
        )

        # 工具箱
        self._connect_toolbox()
        self.toolbox_vm.tool_progress.connect(self.toolbox_view.set_status)
        self.toolbox_vm.tool_done.connect(self._on_tool_done)

        # 设置
        self.settings_view.settings_changed.connect(
            self.dashboard_vm.reload_settings,
        )

    def _connect_toolbox(self):
        """连接工具箱页网络工具按钮。"""
        mapping = {
            self.toolbox_view.card_dns.btn: "dns",
            self.toolbox_view.card_winsock.btn: "winsock",
            self.toolbox_view.card_tcp.btn: "tcp",
        }
        for btn, action in mapping.items():
            btn.clicked.connect(
                lambda _, a=action: self._on_run_tool(a),
            )

    # ── 首页槽函数 ───────────────────────────────────

    def _on_smart_optimize(self):
        self.dashboard_view.set_optimizing(True)
        self.dashboard_vm.start_smart_optimize()

    def _on_smart_optimize_done(self, msg: str, score_before: int, score_after: int):
        self.dashboard_view.set_optimizing(False)
        self.dashboard_view.set_progress_text("")
        self.dashboard_view.show_result(msg, score_before, score_after)

    def _on_pagefile_status(self, data: dict):
        """更新分页文件状态卡片。"""
        card = self.dashboard_view.pagefile_card
        if data.get("mode") == "active":
            card.update_info(data["size_mb"], data["drive"])
        else:
            card.set_idle()

    def _on_pagefile_suggest(self, rec_mb: int):
        """更新智能建议卡片。"""
        card = self.dashboard_view.suggestion_card
        if rec_mb > 0:
            card.update_suggest(rec_mb)
            self._pending_suggest_mb = rec_mb
        elif rec_mb == -1:
            card.set_accepted()
        else:
            card.set_idle()

    def _on_accept_suggestion(self):
        """用户接受建议。"""
        rec = getattr(self, "_pending_suggest_mb", 0)
        if rec > 0:
            self.dashboard_vm.accept_suggestion(rec)

    # ── 清理槽函数 ───────────────────────────────────

    def _on_scan(self):
        deep = self.cleaner_view.deep_switch.isChecked()
        self.cleaner_view.set_scanning(True)
        self.cleaner_vm.start_scan(deep=deep)

    def _on_scan_done(self, result):
        self.cleaner_view.set_scanning(False)
        self.cleaner_view.populate(result)
        self.cleaner_view.set_status("扫描完成")

    def _on_clean(self):
        items = self.cleaner_view.get_selected_items()
        if items:
            self.cleaner_view.set_scanning(True)
            self.cleaner_vm.start_clean(items)

    def _on_clean_done(self, msg: str):
        self.cleaner_view.set_scanning(False)
        self.cleaner_view.set_status("")
        self.cleaner_view.show_result(msg)

    # ── 加速槽函数 ───────────────────────────────────

    def _on_mem_optimize(self):
        self.optimizer_view.set_running(True)
        self.optimizer_vm.start_optimize()

    def _on_mem_optimize_done(self, msg: str):
        self.optimizer_view.set_running(False)
        self.optimizer_view.set_status("")
        self.optimizer_view.show_result(msg)
        self._on_refresh_boost()

    def _on_refresh_boost(self):
        self.optimizer_vm.refresh_memory()
        self.optimizer_vm.refresh_processes()

    def _on_boost(self, pid: int):
        self.optimizer_vm.boost_process(pid)
        self.optimizer_vm.refresh_processes()

    def _on_throttle(self, pid: int):
        self.optimizer_vm.throttle_process(pid)
        self.optimizer_vm.refresh_processes()

    def _on_startup_toggle(self, item, enable: bool):
        self.optimizer_vm.toggle_startup(item, enable)

    # ── 工具槽函数 ───────────────────────────────────

    def _on_run_tool(self, action: str):
        """网络工具（工具箱页触发）。"""
        self.toolbox_view.set_running(True)
        self.toolbox_vm.run_tool(action)

    def _on_tool_done(self, msg: str):
        self.toolbox_view.set_running(False)
        self.toolbox_view.set_status("")
        self.toolbox_view.show_result(msg)

    # ── 页面切换 ─────────────────────────────────────

    def _on_page_changed(self):
        """页面切换动画完成后加载对应数据。"""
        current = self.stackedWidget.currentWidget()
        if current is self.optimizer_view:
            self._on_refresh_boost()
            QTimer.singleShot(200, self.optimizer_vm.refresh_startup)

    # ── 辅助方法 ─────────────────────────────────────

    def _center_on_screen(self):
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = (geo.width() - self.width()) // 2
            y = (geo.height() - self.height()) // 2
            self.move(x, y)

    def closeEvent(self, event):
        self.dashboard_vm.stop()
        super().closeEvent(event)
