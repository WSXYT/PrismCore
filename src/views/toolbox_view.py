"""工具箱视图 — 网络修复工具集合。"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
)
from qfluentwidgets import (
    SubtitleLabel, BodyLabel, PushButton, CardWidget,
    FluentIcon, IconWidget, InfoBar, InfoBarPosition,
    IndeterminateProgressBar, ScrollArea,
)


class _ToolCard(CardWidget):
    """工具卡片：图标 + 标题 + 描述 + 按钮。"""

    def __init__(self, icon, title, desc, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)

        icon_w = IconWidget(icon, self)
        icon_w.setFixedSize(24, 24)
        layout.addWidget(icon_w)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        text_col.addWidget(BodyLabel(title, self))
        desc_label = BodyLabel(desc, self)
        desc_label.setStyleSheet("color: gray; font-size: 12px;")
        text_col.addWidget(desc_label)
        layout.addLayout(text_col, 1)

        self.btn = PushButton("执行", self)
        self.btn.setFixedWidth(80)
        layout.addWidget(self.btn)


class ToolboxView(ScrollArea):
    """工具箱页面：网络修复工具。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("toolboxView")
        self.setWidgetResizable(True)

        container = QWidget(self)
        self.setWidget(container)
        root = QVBoxLayout(container)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(12)

        root.addWidget(SubtitleLabel("工具箱", self))
        root.addWidget(BodyLabel("网络修复工具，按需使用。", self))

        # 进度
        self.progress = IndeterminateProgressBar(self)
        self.progress.setVisible(False)
        root.addWidget(self.progress)
        self.status_label = BodyLabel("", self)
        root.addWidget(self.status_label)

        # ── 网络工具 ─────────────────────────────────
        self.card_dns = _ToolCard(
            FluentIcon.GLOBE, "刷新 DNS",
            "网页打不开时尝试", self,
        )
        root.addWidget(self.card_dns)

        self.card_winsock = _ToolCard(
            FluentIcon.GLOBE, "重置 Winsock",
            "修复网络异常（需重启）", self,
        )
        root.addWidget(self.card_winsock)

        self.card_tcp = _ToolCard(
            FluentIcon.GLOBE, "重置 TCP/IP",
            "彻底重置网络协议（需重启）", self,
        )
        root.addWidget(self.card_tcp)

        root.addStretch()

    # ── 公共方法 ─────────────────────────────────────

    def set_running(self, active: bool):
        """设置工具执行中状态。"""
        self.progress.setVisible(active)

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
