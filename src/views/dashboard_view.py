"""首页视图 — 健康评分、智能优化按钮、实时状态指标。"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
)
from qfluentwidgets import (
    SubtitleLabel, BodyLabel, CaptionLabel,
    PrimaryPushButton, PushButton, CardWidget, ProgressBar,
    ProgressRing, FluentIcon, IconWidget,
    IndeterminateProgressBar, InfoBar, InfoBarPosition,
    ScrollArea,
)


class _ScoreCard(CardWidget):
    """健康评分卡片：大圆环 + 评分数字 + 状态文字。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 评分圆环
        self._ring = ProgressRing(self)
        self._ring.setRange(0, 100)
        self._ring.setValue(0)
        self._ring.setFixedSize(120, 120)
        self._ring.setStrokeWidth(10)
        layout.addWidget(self._ring, 0, Qt.AlignmentFlag.AlignCenter)

        # 评分文字
        self._score_label = SubtitleLabel("0 分", self)
        self._score_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._score_label)

        # 状态描述
        self._status_label = CaptionLabel("正在检测...", self)
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status_label)

    def set_score(self, score: int):
        """更新健康评分。"""
        self._ring.setValue(score)
        self._score_label.setText(f"{score} 分")
        if score >= 80:
            self._status_label.setText("系统状态良好")
        elif score >= 60:
            self._status_label.setText("系统状态一般，建议优化")
        else:
            self._status_label.setText("系统状态较差，请立即优化")


class _MiniIndicator(CardWidget):
    """迷你指标卡片：图标 + 标题 + 进度条 + 数值。"""

    def __init__(self, icon: FluentIcon, title: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(100)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)

        # 标题行
        header = QHBoxLayout()
        icon_w = IconWidget(icon, self)
        icon_w.setFixedSize(16, 16)
        header.addWidget(icon_w)
        header.addWidget(BodyLabel(title, self))
        header.addStretch()
        self._value = BodyLabel("0%", self)
        header.addWidget(self._value)
        layout.addLayout(header)

        # 进度条
        self._bar = ProgressBar(self)
        self._bar.setRange(0, 100)
        layout.addWidget(self._bar)

        # 详情
        self._detail = CaptionLabel("", self)
        layout.addWidget(self._detail)

    def set_data(self, percent: float, detail: str = ""):
        """更新指标数据。"""
        self._bar.setValue(int(min(percent, 100)))
        self._value.setText(f"{percent:.0f}%")
        if detail:
            self._detail.setText(detail)


class _PagefileStatusCard(CardWidget):
    """分页文件状态卡片 — 始终可见，不可关闭。"""

    reboot_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(56)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)

        self._label = BodyLabel("还没有创建临时分页文件哦~再用用吧", self)
        layout.addWidget(self._label, 1)

        self._btn_reboot = PrimaryPushButton("立即重启清除", self)
        self._btn_reboot.clicked.connect(self.reboot_clicked)
        layout.addWidget(self._btn_reboot)
        self._btn_reboot.setVisible(False)

    def update_info(self, size_mb: int, drive: str):
        self._label.setText(f"已创建 {size_mb} MB 临时分页文件 ({drive})")
        self._btn_reboot.setVisible(True)

    def set_idle(self):
        self._label.setText("还没有创建临时分页文件哦~再用用吧")
        self._btn_reboot.setVisible(False)


class _PagefileSuggestionCard(CardWidget):
    """分页文件智能建议卡片 — 始终可见。"""

    accept_clicked = Signal()
    dismiss_clicked = Signal()
    cancel_clicked = Signal()
    reboot_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(56)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)

        self._label = BodyLabel("暂无智能建议哦~再用用吧", self)
        layout.addWidget(self._label, 1)

        self._btn_accept = PushButton("接受建议", self)
        self._btn_dismiss = PushButton("忽略", self)
        self._btn_cancel = PushButton("撤销", self)
        self._btn_reboot = PrimaryPushButton("立即重启", self)
        self._btn_accept.clicked.connect(self.accept_clicked)
        self._btn_dismiss.clicked.connect(self.dismiss_clicked)
        self._btn_cancel.clicked.connect(self.cancel_clicked)
        self._btn_reboot.clicked.connect(self.reboot_clicked)
        layout.addWidget(self._btn_accept)
        layout.addWidget(self._btn_dismiss)
        layout.addWidget(self._btn_cancel)
        layout.addWidget(self._btn_reboot)
        self.set_mode("idle")

    def set_mode(self, mode: str):
        """切换模式: idle / suggest / accepted"""
        self._btn_accept.setVisible(mode == "suggest")
        self._btn_dismiss.setVisible(mode == "suggest")
        self._btn_cancel.setVisible(mode == "accepted")
        self._btn_reboot.setVisible(mode == "accepted")

    def update_suggest(self, rec_mb: int):
        self._label.setText(
            f"临时分页文件已活跃超过 30 分钟，建议将系统虚拟内存增加至 {rec_mb} MB"
        )
        self.set_mode("suggest")

    def set_idle(self):
        self._label.setText("暂无智能建议哦~再用用吧")
        self.set_mode("idle")

    def set_accepted(self):
        self._label.setText("已调整虚拟内存，需重启生效")
        self.set_mode("accepted")


class DashboardView(ScrollArea):
    """首页：健康评分 + 智能优化 + 实时监控。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dashboardView")
        self.setWidgetResizable(True)

        container = QWidget(self)
        self.setWidget(container)
        root = QVBoxLayout(container)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(16)

        # 顶部标题
        root.addWidget(SubtitleLabel("系统概览", self))

        # 评分卡片 + 优化按钮
        top_row = QHBoxLayout()
        top_row.setSpacing(16)

        self.score_card = _ScoreCard(self)
        top_row.addWidget(self.score_card)

        # 右侧：优化按钮 + 进度
        right_panel = QVBoxLayout()
        right_panel.setSpacing(10)

        self.btn_optimize = PrimaryPushButton(
            FluentIcon.SPEED_HIGH, "智能优化", self,
        )
        self.btn_optimize.setFixedHeight(48)
        right_panel.addWidget(self.btn_optimize)

        right_panel.addWidget(CaptionLabel(
            "一键优化：内存清理 + 智能进程分页 + 垃圾清理 + 虚拟内存调整",
            self,
        ))

        self.progress = IndeterminateProgressBar(self)
        self.progress.setVisible(False)
        right_panel.addWidget(self.progress)

        self.status_label = BodyLabel("", self)
        self.status_label.setWordWrap(True)
        right_panel.addWidget(self.status_label)

        # 问题提示区域
        self._issues_label = BodyLabel("", self)
        self._issues_label.setWordWrap(True)
        right_panel.addWidget(self._issues_label)
        right_panel.addStretch()

        top_row.addLayout(right_panel, 1)
        root.addLayout(top_row)

        # 分页文件状态卡片（始终可见）
        self.pagefile_card = _PagefileStatusCard(self)
        root.addWidget(self.pagefile_card)

        # 智能建议卡片（始终可见）
        self.suggestion_card = _PagefileSuggestionCard(self)
        root.addWidget(self.suggestion_card)

        # 实时指标行
        root.addWidget(SubtitleLabel("实时监控", self))
        indicators = QGridLayout()
        indicators.setSpacing(12)

        self.cpu_indicator = _MiniIndicator(
            FluentIcon.SPEED_HIGH, "CPU", self,
        )
        self.mem_indicator = _MiniIndicator(
            FluentIcon.IOT, "内存", self,
        )
        self.dpc_indicator = _MiniIndicator(
            FluentIcon.SPEED_HIGH, "DPC 延迟", self,
        )
        self.isr_indicator = _MiniIndicator(
            FluentIcon.SPEED_HIGH, "ISR 延迟", self,
        )
        indicators.addWidget(self.cpu_indicator, 0, 0)
        indicators.addWidget(self.mem_indicator, 0, 1)
        indicators.addWidget(self.dpc_indicator, 1, 0)
        indicators.addWidget(self.isr_indicator, 1, 1)

        # 磁盘指标（动态创建）
        self._disk_indicators: list[_MiniIndicator] = []
        self._disk_grid = indicators
        self._disk_row = 2
        root.addLayout(indicators)

        root.addStretch()

    # ── 公共方法 ─────────────────────────────────────

    def update_status(self, data: dict):
        """更新首页全部数据。"""
        self.score_card.set_score(data["score"])
        pb = data.get("probalance_count", 0)
        pb_t = data.get("probalance_threshold", 0)
        pb_a = data.get("probalance_anomaly", 0)
        if pb:
            parts = []
            if pb_t:
                parts.append(f"阈值触发 {pb_t}")
            if pb_a:
                parts.append(f"异常检测 {pb_a}")
            cpu_detail = f"ProBalance 约束中: {pb} 个进程（{'、'.join(parts)}）"
        else:
            cpu_detail = ""
        self.cpu_indicator.set_data(data["cpu_pct"], cpu_detail)
        self.mem_indicator.set_data(
            data["mem_pct"],
            f"{data['mem_used']} / {data['mem_total']}",
        )

        # DPC/ISR 延迟指标（百分比映射到 0-100 进度条，放大 10 倍便于观察）
        dpc = data.get("dpc_pct", 0.0)
        isr = data.get("isr_pct", 0.0)
        self.dpc_indicator.set_data(
            min(dpc * 10, 100), f"DPC 占用: {dpc:.2f}%",
        )
        self.isr_indicator.set_data(
            min(isr * 10, 100), f"ISR 占用: {isr:.2f}%",
        )

        # 磁盘指标
        disks = data["disks"]
        if len(disks) != len(self._disk_indicators):
            for ind in self._disk_indicators:
                ind.deleteLater()
            self._disk_indicators.clear()
            for i, _ in enumerate(disks):
                ind = _MiniIndicator(FluentIcon.FOLDER, "", self)
                self._disk_grid.addWidget(ind, self._disk_row + i // 2, i % 2)
                self._disk_indicators.append(ind)

        for ind, d in zip(self._disk_indicators, disks):
            ind.set_data(d["percent"], f"{d['mount']} 可用: {d['free']}")

        # 问题提示（与评分一致）
        issues = data.get("issues", [])
        score = data.get("score", 0)
        if issues:
            self._issues_label.setText("⚠ " + "；".join(issues))
        elif score >= 80:
            self._issues_label.setText("✓ 系统状态良好")
        else:
            self._issues_label.setText("⚠ 系统资源使用偏高，建议优化")

    def set_optimizing(self, active: bool):
        """设置优化中状态。"""
        self.progress.setVisible(active)
        self.btn_optimize.setEnabled(not active)

    def set_progress_text(self, text: str):
        """更新优化进度文字。"""
        self.status_label.setText(text)

    def show_result(self, message: str, score_before: int = -1, score_after: int = -1):
        """显示优化完成通知，含评分变化。"""
        if score_before >= 0 and score_after >= 0:
            diff = score_after - score_before
            sign = "+" if diff >= 0 else ""
            title = f"优化完成 · 评分 {score_before} → {score_after} ({sign}{diff})"
        else:
            title = "优化完成"
        InfoBar.success(
            title=title, content=message,
            parent=self, position=InfoBarPosition.TOP,
            duration=8000,
        )

    def show_auto_action(self, message: str):
        """显示后台自动优化通知。"""
        InfoBar.info(
            title="后台自动优化", content=message,
            parent=self, position=InfoBarPosition.BOTTOM_RIGHT,
            duration=3000,
        )

