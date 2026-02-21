"""清理视图 — 统一扫描垃圾文件和系统组件。"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QHeaderView,
    QTableWidgetItem, QAbstractItemView,
)
from qfluentwidgets import (
    SubtitleLabel, BodyLabel,
    PrimaryPushButton, PushButton,
    CheckBox, TableWidget, InfoBar, InfoBarPosition,
    IndeterminateProgressBar, FluentIcon, SwitchButton,
    ScrollArea,
)

from src.models.cleaner import ScanResult, CleanItem
from src.models.system_info import format_bytes


# 类别中文映射
_CATEGORY_LABELS = {
    "electron": "应用缓存",
    "temp": "临时文件",
    "large_file": "大文件",
    "recycle_bin": "回收站",
    "winsxs": "组件存储",
    "old_drivers": "旧驱动",
    "orphan_registry": "注册表",
    "win_update": "更新缓存",
    "compact_os": "系统压缩",
}


class CleanerView(ScrollArea):
    """清理页面：垃圾扫描 + 系统清理工具。使用 ScrollArea 支持滚动。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("cleanerView")
        self.setWidgetResizable(True)
        self._items: list[CleanItem] = []

        # 内容容器
        container = QWidget(self)
        self.setWidget(container)
        root = QVBoxLayout(container)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(12)

        # ── 垃圾扫描区 ────────────────────────────────
        root.addWidget(SubtitleLabel("垃圾清理", self))
        root.addWidget(BodyLabel(
            "统一扫描垃圾文件与系统组件（更新缓存、旧驱动、注册表等），勾选后一键清理。",
            self,
        ))

        # 操作栏
        ctrl = QHBoxLayout()
        self.btn_scan = PrimaryPushButton(
            FluentIcon.SEARCH, "扫描", self,
        )
        ctrl.addWidget(self.btn_scan)

        self.deep_switch = SwitchButton(self)
        self.deep_switch.setOffText("快速")
        self.deep_switch.setOnText("深度")
        ctrl.addWidget(BodyLabel("模式:", self))
        ctrl.addWidget(self.deep_switch)
        ctrl.addStretch()

        self.btn_clean = PushButton(
            FluentIcon.DELETE, "清理已选", self,
        )
        self.btn_clean.setEnabled(False)
        ctrl.addWidget(self.btn_clean)
        root.addLayout(ctrl)

        # 进度
        self.progress = IndeterminateProgressBar(self)
        self.progress.setVisible(False)
        root.addWidget(self.progress)
        self.status_label = BodyLabel('点击"扫描"开始检测垃圾文件', self)
        root.addWidget(self.status_label)

        # 结果表格
        self.table = TableWidget(self)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(
            ["", "类别", "描述", "大小"],
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection,
        )
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers,
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(0, 40)
        self.table.setMinimumHeight(160)
        root.addWidget(self.table)

        # 摘要
        self.summary_label = BodyLabel("", self)
        root.addWidget(self.summary_label)


    # ── 公共方法 ─────────────────────────────────────

    def set_scanning(self, active: bool):
        """设置扫描/清理中状态。"""
        self.progress.setVisible(active)
        self.btn_scan.setEnabled(not active)
        self.btn_clean.setEnabled(not active and len(self._items) > 0)

    def set_status(self, text: str):
        """更新状态文字。"""
        self.status_label.setText(text)

    def populate(self, result: ScanResult):
        """填充扫描结果到表格。"""
        self._items = result.items
        self.table.setRowCount(len(self._items))

        for row, item in enumerate(self._items):
            cb = CheckBox(self)
            cb.setChecked(item.selected)
            cb.stateChanged.connect(
                lambda state, r=row: self._on_check(r, state),
            )
            self.table.setCellWidget(row, 0, cb)

            label = _CATEGORY_LABELS.get(item.category, item.category)
            self.table.setItem(row, 1, QTableWidgetItem(label))
            self.table.setItem(row, 2, QTableWidgetItem(item.description))
            self.table.setItem(
                row, 3, QTableWidgetItem(format_bytes(item.size)),
            )

        self._update_summary()
        self.btn_clean.setEnabled(len(self._items) > 0)

    def get_selected_items(self) -> list[CleanItem]:
        """返回用户勾选的项目。"""
        return [i for i in self._items if i.selected]

    def show_result(self, message: str):
        """显示操作完成通知。"""
        InfoBar.success(
            title="完成", content=message,
            parent=self, position=InfoBarPosition.TOP,
            duration=4000,
        )

    # ── 内部方法 ─────────────────────────────────────

    def _on_check(self, row: int, state: int):
        self._items[row].selected = (state == Qt.CheckState.Checked.value)
        self._update_summary()

    def _update_summary(self):
        selected = self.get_selected_items()
        total = sum(i.size for i in selected)
        self.summary_label.setText(
            f"已选 {len(selected)} 项，共 {format_bytes(total)}",
        )
