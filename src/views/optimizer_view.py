"""加速视图 — 内存优化 + 启动项管理 + 进程管理。"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QHeaderView,
    QTableWidgetItem, QAbstractItemView,
)
from qfluentwidgets import (
    SubtitleLabel, BodyLabel, CaptionLabel,
    PrimaryPushButton, PushButton, CardWidget,
    TableWidget, InfoBar, InfoBarPosition,
    IndeterminateProgressBar, FluentIcon, ProgressBar,
    IconWidget, SwitchButton, ScrollArea,
)


class _MemoryCard(CardWidget):
    """内存状态卡片。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(130)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)

        header = QHBoxLayout()
        icon = IconWidget(FluentIcon.IOT, self)
        icon.setFixedSize(20, 20)
        header.addWidget(icon)
        header.addWidget(SubtitleLabel("内存状态", self))
        header.addStretch()
        layout.addLayout(header)

        self._label = BodyLabel("已用: — / —", self)
        layout.addWidget(self._label)

        self._bar = ProgressBar(self)
        self._bar.setRange(0, 100)
        layout.addWidget(self._bar)

        self._commit = CaptionLabel("提交费用: —%", self)
        layout.addWidget(self._commit)

    def set_data(self, data: dict):
        """更新内存数据。"""
        self._label.setText(
            f"已用: {data['used']} / {data['total']}  "
            f"(可用: {data['available']})"
        )
        self._bar.setValue(int(data["percent"]))
        cr = data["commit_ratio"]
        warn = " ⚠ 危险" if data["commit_critical"] else ""
        self._commit.setText(f"提交费用: {cr}%{warn}")


class OptimizerView(ScrollArea):
    """加速页面：内存优化 + 启动项 + 进程管理。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("optimizerView")
        self.setWidgetResizable(True)

        container = QWidget(self)
        self.setWidget(container)
        root = QVBoxLayout(container)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(12)

        root.addWidget(SubtitleLabel("性能加速", self))

        # ── 内存卡片 + 优化按钮 ──────────────────────
        self.mem_card = _MemoryCard(self)
        root.addWidget(self.mem_card)

        mem_row = QHBoxLayout()
        self.btn_optimize = PrimaryPushButton(
            FluentIcon.SPEED_HIGH, "智能优化", self,
        )
        mem_row.addWidget(self.btn_optimize)
        self.btn_refresh = PushButton(
            FluentIcon.SYNC, "刷新", self,
        )
        mem_row.addWidget(self.btn_refresh)
        mem_row.addStretch()
        root.addLayout(mem_row)

        root.addWidget(CaptionLabel(
            "智能优化：清理备用列表 + 智能进程分页 + 修剪工作集 + 动态扩展分页文件",
            self,
        ))

        self.progress = IndeterminateProgressBar(self)
        self.progress.setVisible(False)
        root.addWidget(self.progress)
        self.status_label = BodyLabel("", self)
        root.addWidget(self.status_label)

        # ── 启动项管理 ───────────────────────────────
        startup_header = QHBoxLayout()
        startup_header.addWidget(BodyLabel("启动项管理", self))
        startup_header.addStretch()
        self.btn_startup_refresh = PushButton(
            FluentIcon.SYNC, "刷新", self,
        )
        startup_header.addWidget(self.btn_startup_refresh)
        root.addLayout(startup_header)

        self.startup_table = TableWidget(self)
        self.startup_table.setColumnCount(4)
        self.startup_table.setHorizontalHeaderLabels(
            ["名称", "来源", "状态", "开关"],
        )
        self.startup_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers,
        )
        self.startup_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection,
        )
        sh = self.startup_table.horizontalHeader()
        sh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        sh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        sh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        sh.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.startup_table.setColumnWidth(3, 100)
        self.startup_table.setMinimumHeight(200)
        root.addWidget(self.startup_table)

        # ── 进程管理 ─────────────────────────────────
        root.addWidget(BodyLabel("进程管理（按内存排序）", self))
        self.proc_table = TableWidget(self)
        self.proc_table.setColumnCount(5)
        self.proc_table.setHorizontalHeaderLabels(
            ["PID", "名称", "内存", "CPU%", "操作"],
        )
        self.proc_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers,
        )
        ph = self.proc_table.horizontalHeader()
        ph.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for col in (0, 2, 3, 4):
            ph.setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents,
            )
        self.proc_table.setMinimumHeight(400)
        root.addWidget(self.proc_table)

    # ── 内存相关 ─────────────────────────────────────

    def set_running(self, active: bool):
        """设置优化中状态。"""
        self.progress.setVisible(active)
        self.btn_optimize.setEnabled(not active)

    def set_status(self, text: str):
        """更新状态文字。"""
        self.status_label.setText(text)

    def show_result(self, message: str):
        """显示操作完成通知。"""
        InfoBar.success(
            title="完成", content=message,
            parent=self, position=InfoBarPosition.TOP,
            duration=4000,
        )

    # ── 启动项相关 ───────────────────────────────────

    def populate_startup(self, items, on_toggle=None):
        """填充启动项表格。"""
        self.startup_table.setRowCount(len(items))
        for row, item in enumerate(items):
            self.startup_table.setItem(
                row, 0, QTableWidgetItem(item.name),
            )
            src = "注册表" if item.source == "registry" else "计划任务"
            self.startup_table.setItem(
                row, 1, QTableWidgetItem(src),
            )
            self.startup_table.setItem(
                row, 2,
                QTableWidgetItem("已启用" if item.enabled else "已禁用"),
            )
            sw = SwitchButton(self)
            sw.setChecked(item.enabled)
            if on_toggle:
                sw.checkedChanged.connect(
                    lambda checked, i=item: on_toggle(i, checked),
                )
            self.startup_table.setCellWidget(row, 3, sw)

    # ── 进程相关 ─────────────────────────────────────

    def populate_processes(self, procs, on_boost=None, on_throttle=None):
        """填充进程表格。"""
        self.proc_table.setRowCount(len(procs))
        for row, p in enumerate(procs):
            self.proc_table.setItem(
                row, 0, QTableWidgetItem(str(p.pid)),
            )
            self.proc_table.setItem(
                row, 1, QTableWidgetItem(p.name),
            )
            self.proc_table.setItem(
                row, 2, QTableWidgetItem(f"{p.memory_mb:.1f} MB"),
            )
            self.proc_table.setItem(
                row, 3, QTableWidgetItem(f"{p.cpu_percent:.1f}"),
            )

            action_w = QFrame(self)
            action_l = QHBoxLayout(action_w)
            action_l.setContentsMargins(2, 2, 2, 2)

            btn_b = PushButton("优先级↑", self)
            btn_b.setFixedWidth(80)
            if on_boost:
                btn_b.clicked.connect(
                    lambda _, pid=p.pid: on_boost(pid),
                )
            action_l.addWidget(btn_b)

            btn_t = PushButton("优先级↓", self)
            btn_t.setFixedWidth(80)
            if on_throttle:
                btn_t.clicked.connect(
                    lambda _, pid=p.pid: on_throttle(pid),
                )
            action_l.addWidget(btn_t)

            self.proc_table.setCellWidget(row, 4, action_w)
