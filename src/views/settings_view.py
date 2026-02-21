"""设置视图 — 后台优化、虚拟内存、监控等配置。"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout
from qfluentwidgets import (
    SubtitleLabel, BodyLabel, ScrollArea,
    SwitchButton, SpinBox, DoubleSpinBox, CardWidget, FluentIcon,
)

from src.models.settings import AppSettings


class _SettingRow(CardWidget):
    """单行设置：标题 + 描述 + 控件。"""

    def __init__(self, title: str, desc: str, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QHBoxLayout
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(16, 12, 16, 12)

        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(BodyLabel(title, self))
        d = BodyLabel(desc, self)
        d.setStyleSheet("color: gray; font-size: 12px;")
        col.addWidget(d)
        self._layout.addLayout(col, 1)

    def add_widget(self, w):
        self._layout.addWidget(w)


class SettingsView(ScrollArea):
    """设置页面。"""

    # 设置变更信号
    settings_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsView")
        self.setWidgetResizable(True)
        self._settings = AppSettings()

        container = QWidget(self)
        self.setWidget(container)
        root = QVBoxLayout(container)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(12)

        # ── 后台自动优化 ──
        root.addWidget(SubtitleLabel("后台自动优化", self))

        row1 = _SettingRow(
            "启用后台自动优化",
            "定时检测内存状态，自动清理备用列表和修剪工作集",
            self,
        )
        self.sw_auto = SwitchButton(self)
        self.sw_auto.setChecked(self._settings.auto_optimize_enabled)
        self.sw_auto.checkedChanged.connect(self._on_auto_toggle)
        row1.add_widget(self.sw_auto)
        root.addWidget(row1)

        row2 = _SettingRow(
            "检测间隔（秒）",
            "后台自动优化的检测周期，建议 15~120 秒",
            self,
        )
        self.spin_interval = SpinBox(self)
        self.spin_interval.setRange(15, 120)
        self.spin_interval.setValue(self._settings.auto_optimize_interval)
        self.spin_interval.valueChanged.connect(self._on_interval)
        row2.add_widget(self.spin_interval)
        root.addWidget(row2)

        row3 = _SettingRow(
            "内存阈值（%）",
            "内存使用率超过此值时触发自动优化",
            self,
        )
        self.spin_threshold = SpinBox(self)
        self.spin_threshold.setRange(50, 95)
        self.spin_threshold.setValue(self._settings.memory_threshold)
        self.spin_threshold.valueChanged.connect(self._on_threshold)
        row3.add_widget(self.spin_threshold)
        root.addWidget(row3)

        # ── 虚拟内存 ──
        root.addWidget(SubtitleLabel("虚拟内存", self))

        row4 = _SettingRow(
            "自动创建临时分页文件",
            "智能优化时，若内存仍紧张则在非系统盘创建临时分页文件",
            self,
        )
        self.sw_pagefile = SwitchButton(self)
        self.sw_pagefile.setChecked(self._settings.auto_pagefile_enabled)
        self.sw_pagefile.checkedChanged.connect(self._on_pagefile)
        row4.add_widget(self.sw_pagefile)
        root.addWidget(row4)

        row_pf_threshold = _SettingRow(
            "分页文件扩展阈值（%）",
            "提交费用占比超过此值时触发动态扩展分页文件",
            self,
        )
        self.spin_pf_threshold = SpinBox(self)
        self.spin_pf_threshold.setRange(50, 95)
        self.spin_pf_threshold.setValue(self._settings.pagefile_expand_threshold)
        self.spin_pf_threshold.valueChanged.connect(self._on_pf_threshold)
        row_pf_threshold.add_widget(self.spin_pf_threshold)
        root.addWidget(row_pf_threshold)

        row_suggest = _SettingRow(
            "智能建议",
            "临时分页文件活跃超过30分钟时，建议将其转为永久设置",
            self,
        )
        self.sw_suggest = SwitchButton(self)
        self.sw_suggest.setChecked(self._settings.suggestion_enabled)
        self.sw_suggest.checkedChanged.connect(self._on_suggest)
        row_suggest.add_widget(self.sw_suggest)
        root.addWidget(row_suggest)

        # ── ProBalance CPU 调度 ──
        root.addWidget(SubtitleLabel("CPU 智能调度（ProBalance）", self))

        row_pb = _SettingRow(
            "启用 ProBalance",
            "自动检测 CPU 霸占进程并临时降低优先级，负载恢复后自动还原",
            self,
        )
        self.sw_probalance = SwitchButton(self)
        self.sw_probalance.setChecked(self._settings.probalance_enabled)
        self.sw_probalance.checkedChanged.connect(self._on_probalance)
        row_pb.add_widget(self.sw_probalance)
        root.addWidget(row_pb)

        row_pb_sys = _SettingRow(
            "系统 CPU 激活阈值（%）",
            "系统总 CPU 超过此值时才开始评估进程",
            self,
        )
        self.spin_pb_sys = SpinBox(self)
        self.spin_pb_sys.setRange(30, 95)
        self.spin_pb_sys.setValue(self._settings.probalance_system_threshold)
        self.spin_pb_sys.valueChanged.connect(self._on_pb_sys)
        row_pb_sys.add_widget(self.spin_pb_sys)
        root.addWidget(row_pb_sys)

        row_pb_proc = _SettingRow(
            "单进程 CPU 约束阈值（%）",
            "单个后台进程 CPU 超过此值且持续数秒后被约束",
            self,
        )
        self.spin_pb_proc = SpinBox(self)
        self.spin_pb_proc.setRange(5, 50)
        self.spin_pb_proc.setValue(self._settings.probalance_process_threshold)
        self.spin_pb_proc.valueChanged.connect(self._on_pb_proc)
        row_pb_proc.add_widget(self.spin_pb_proc)
        root.addWidget(row_pb_proc)

        # ── 高级设置（异常检测） ──
        root.addWidget(SubtitleLabel("高级设置（异常检测）", self))

        row_anomaly = _SettingRow(
            "启用 Z-score 异常检测",
            "通过统计学方法检测进程 CPU 行为突变，无需等待绝对阈值即可提前干预",
            self,
        )
        self.sw_anomaly = SwitchButton(self)
        self.sw_anomaly.setChecked(self._settings.anomaly_detection_enabled)
        self.sw_anomaly.checkedChanged.connect(self._on_anomaly)
        row_anomaly.add_widget(self.sw_anomaly)
        root.addWidget(row_anomaly)

        row_z = _SettingRow(
            "Z-score 阈值",
            "偏离历史基线的标准差倍数，越小越敏感（默认 3.0，建议 2.0~5.0）",
            self,
        )
        self.spin_z = DoubleSpinBox(self)
        self.spin_z.setRange(1.0, 10.0)
        self.spin_z.setSingleStep(0.5)
        self.spin_z.setValue(self._settings.anomaly_z_threshold)
        self.spin_z.valueChanged.connect(self._on_z_threshold)
        row_z.add_widget(self.spin_z)
        root.addWidget(row_z)

        row_ewma = _SettingRow(
            "EWMA 平滑系数",
            "指数加权移动平均的敏感度，越大对近期变化越敏感（默认 0.3，建议 0.1~0.5）",
            self,
        )
        self.spin_ewma = DoubleSpinBox(self)
        self.spin_ewma.setRange(0.05, 0.95)
        self.spin_ewma.setSingleStep(0.05)
        self.spin_ewma.setValue(self._settings.ewma_alpha)
        self.spin_ewma.valueChanged.connect(self._on_ewma)
        row_ewma.add_widget(self.spin_ewma)
        root.addWidget(row_ewma)

        # ── 内存优化策略 ──
        root.addWidget(SubtitleLabel("内存优化策略", self))

        row_purge = _SettingRow(
            "备用列表清理",
            "清空系统文件缓存释放内存，争议较小",
            self,
        )
        self.sw_purge = SwitchButton(self)
        self.sw_purge.setChecked(self._settings.purge_standby_enabled)
        self.sw_purge.checkedChanged.connect(self._on_purge)
        row_purge.add_widget(self.sw_purge)
        root.addWidget(row_purge)

        row_trim = _SettingRow(
            "工作集修剪",
            "修剪后台进程内存（有争议：释放内存但可能导致后续硬页错误）",
            self,
        )
        self.sw_trim = SwitchButton(self)
        self.sw_trim.setChecked(self._settings.trim_workingset_enabled)
        self.sw_trim.checkedChanged.connect(self._on_trim)
        row_trim.add_widget(self.sw_trim)
        root.addWidget(row_trim)

        row_pageout = _SettingRow(
            "空闲进程分页",
            "将空闲大内存进程页出到虚拟内存（有争议：同上）",
            self,
        )
        self.sw_pageout = SwitchButton(self)
        self.sw_pageout.setChecked(self._settings.pageout_idle_enabled)
        self.sw_pageout.checkedChanged.connect(self._on_pageout)
        row_pageout.add_widget(self.sw_pageout)
        root.addWidget(row_pageout)

        # ── 监控 ──
        root.addWidget(SubtitleLabel("系统监控", self))

        row5 = _SettingRow(
            "DPC/ISR 延迟监控",
            "监测驱动程序延迟（DPC/ISR），高延迟会导致音频爆音和游戏微卡顿",
            self,
        )
        self.sw_dpc = SwitchButton(self)
        self.sw_dpc.setChecked(self._settings.dpc_monitor_enabled)
        self.sw_dpc.checkedChanged.connect(self._on_dpc)
        row5.add_widget(self.sw_dpc)
        root.addWidget(row5)

        root.addStretch()

    # ── 槽函数 ──

    def _on_auto_toggle(self, checked: bool):
        self._settings.auto_optimize_enabled = checked
        self.settings_changed.emit()

    def _on_interval(self, val: int):
        self._settings.auto_optimize_interval = val
        self.settings_changed.emit()

    def _on_threshold(self, val: int):
        self._settings.memory_threshold = val
        self.settings_changed.emit()

    def _on_pagefile(self, checked: bool):
        self._settings.auto_pagefile_enabled = checked

    def _on_pf_threshold(self, val: int):
        self._settings.pagefile_expand_threshold = val

    def _on_suggest(self, checked: bool):
        self._settings.suggestion_enabled = checked

    def _on_probalance(self, checked: bool):
        self._settings.probalance_enabled = checked
        self.settings_changed.emit()

    def _on_pb_sys(self, val: int):
        self._settings.probalance_system_threshold = val

    def _on_pb_proc(self, val: int):
        self._settings.probalance_process_threshold = val

    def _on_purge(self, checked: bool):
        self._settings.purge_standby_enabled = checked

    def _on_trim(self, checked: bool):
        self._settings.trim_workingset_enabled = checked

    def _on_pageout(self, checked: bool):
        self._settings.pageout_idle_enabled = checked

    def _on_anomaly(self, checked: bool):
        self._settings.anomaly_detection_enabled = checked
        self.settings_changed.emit()

    def _on_z_threshold(self, val: float):
        self._settings.anomaly_z_threshold = val
        self.settings_changed.emit()

    def _on_ewma(self, val: float):
        self._settings.ewma_alpha = val
        self.settings_changed.emit()

    def _on_dpc(self, checked: bool):
        self._settings.dpc_monitor_enabled = checked
        self.settings_changed.emit()
