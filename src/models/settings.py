"""应用设置 — 使用 QSettings 持久化配置。"""

import json

from PySide6.QtCore import QSettings

from src.utils.constants import APP_NAME


class AppSettings:
    """全局应用设置，单例模式。"""

    _instance: "AppSettings | None" = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._qs = QSettings(APP_NAME, APP_NAME)
        return cls._instance

    # ── 后台自动优化 ──

    @property
    def auto_optimize_enabled(self) -> bool:
        return self._qs.value("auto/enabled", True, type=bool)

    @auto_optimize_enabled.setter
    def auto_optimize_enabled(self, v: bool):
        self._qs.setValue("auto/enabled", v)

    @property
    def auto_optimize_interval(self) -> int:
        """自动优化检测间隔（秒）。"""
        return self._qs.value("auto/interval", 15, type=int)

    @auto_optimize_interval.setter
    def auto_optimize_interval(self, v: int):
        self._qs.setValue("auto/interval", v)

    @property
    def memory_threshold(self) -> int:
        """内存使用率阈值（%），超过时触发自动优化。"""
        return self._qs.value("auto/mem_threshold", 70, type=int)

    @memory_threshold.setter
    def memory_threshold(self, v: int):
        self._qs.setValue("auto/mem_threshold", v)

    # ── 虚拟内存 ──

    @property
    def auto_pagefile_enabled(self) -> bool:
        """内存紧张时自动创建临时分页文件。"""
        return self._qs.value("pagefile/auto", True, type=bool)

    @auto_pagefile_enabled.setter
    def auto_pagefile_enabled(self, v: bool):
        self._qs.setValue("pagefile/auto", v)

    @property
    def pagefile_expand_threshold(self) -> int:
        """提交费用占比超过此值时触发分页文件动态扩展（%）。"""
        return self._qs.value("pagefile/expand_threshold", 70, type=int)

    @pagefile_expand_threshold.setter
    def pagefile_expand_threshold(self, v: int):
        self._qs.setValue("pagefile/expand_threshold", v)

    # ── DPC/ISR 监控 ──

    @property
    def dpc_monitor_enabled(self) -> bool:
        return self._qs.value("monitor/dpc", True, type=bool)

    @dpc_monitor_enabled.setter
    def dpc_monitor_enabled(self, v: bool):
        self._qs.setValue("monitor/dpc", v)

    # ── 分页文件持久化 ──

    @property
    def pagefile_info(self) -> dict | None:
        """当前活跃的临时分页文件信息。"""
        raw = self._qs.value("pagefile/created_info", "", type=str)
        if not raw:
            return None
        return json.loads(raw)

    @pagefile_info.setter
    def pagefile_info(self, v: dict | None):
        self._qs.setValue("pagefile/created_info", json.dumps(v) if v else "")

    @property
    def pagefile_pending_reboot(self) -> bool:
        """是否处于等待重启状态（用户已撤回分页文件）。"""
        return self._qs.value("pagefile/pending_reboot", False, type=bool)

    @pagefile_pending_reboot.setter
    def pagefile_pending_reboot(self, v: bool):
        self._qs.setValue("pagefile/pending_reboot", v)

    @property
    def suggestion_enabled(self) -> bool:
        """智能建议开关。"""
        return self._qs.value("pagefile/suggestion_enabled", True, type=bool)

    @suggestion_enabled.setter
    def suggestion_enabled(self, v: bool):
        self._qs.setValue("pagefile/suggestion_enabled", v)

    # ── ProBalance CPU 调度 ──

    @property
    def probalance_enabled(self) -> bool:
        """ProBalance 自动 CPU 调度开关。"""
        return self._qs.value("cpu/probalance_enabled", True, type=bool)

    @probalance_enabled.setter
    def probalance_enabled(self, v: bool):
        self._qs.setValue("cpu/probalance_enabled", v)

    @property
    def probalance_system_threshold(self) -> int:
        """系统总 CPU 激活阈值（%）。"""
        return self._qs.value("cpu/system_threshold", 60, type=int)

    @probalance_system_threshold.setter
    def probalance_system_threshold(self, v: int):
        self._qs.setValue("cpu/system_threshold", v)

    @property
    def probalance_process_threshold(self) -> int:
        """单进程 CPU 约束阈值（%）。"""
        return self._qs.value("cpu/process_threshold", 10, type=int)

    @probalance_process_threshold.setter
    def probalance_process_threshold(self, v: int):
        self._qs.setValue("cpu/process_threshold", v)

    @property
    def anomaly_detection_enabled(self) -> bool:
        """Z-score 异常检测开关。"""
        return self._qs.value("cpu/anomaly_enabled", True, type=bool)

    @anomaly_detection_enabled.setter
    def anomaly_detection_enabled(self, v: bool):
        self._qs.setValue("cpu/anomaly_enabled", v)

    @property
    def anomaly_z_threshold(self) -> float:
        """Z-score 异常判定阈值（默认 3.0，越小越敏感）。"""
        return float(self._qs.value("cpu/z_threshold", 2.5, type=float))

    @anomaly_z_threshold.setter
    def anomaly_z_threshold(self, v: float):
        self._qs.setValue("cpu/z_threshold", v)

    @property
    def ewma_alpha(self) -> float:
        """EWMA 平滑系数（默认 0.3，越大越敏感）。"""
        return float(self._qs.value("cpu/ewma_alpha", 0.4, type=float))

    @ewma_alpha.setter
    def ewma_alpha(self, v: float):
        self._qs.setValue("cpu/ewma_alpha", v)

    # ── 内存优化策略开关 ──

    @property
    def purge_standby_enabled(self) -> bool:
        """备用列表清理开关（争议较小，默认开启）。"""
        return self._qs.value("memory/purge_standby", True, type=bool)

    @purge_standby_enabled.setter
    def purge_standby_enabled(self, v: bool):
        self._qs.setValue("memory/purge_standby", v)

    @property
    def trim_workingset_enabled(self) -> bool:
        """工作集修剪开关（有争议，默认开启）。"""
        return self._qs.value("memory/trim_workingset", True, type=bool)

    @trim_workingset_enabled.setter
    def trim_workingset_enabled(self, v: bool):
        self._qs.setValue("memory/trim_workingset", v)

    @property
    def pageout_idle_enabled(self) -> bool:
        """空闲进程分页开关（有争议，默认开启）。"""
        return self._qs.value("memory/pageout_idle", True, type=bool)

    @pageout_idle_enabled.setter
    def pageout_idle_enabled(self, v: bool):
        self._qs.setValue("memory/pageout_idle", v)
