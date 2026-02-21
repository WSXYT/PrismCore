"""加速视图模型 — 内存优化、启动项管理、进程管理。"""

import logging

from PySide6.QtCore import QObject, QThread, Signal

logger = logging.getLogger(__name__)

from src.models.memory import (
    force_purge, trim_background_working_sets,
    is_commit_critical, get_commit_ratio,
    recommend_pagefile_mb, adjust_pagefile_size,
    page_out_idle_processes,
)
from src.models.auto_optimizer import expand_pagefile_incremental
from src.models.settings import AppSettings
from src.models.process_manager import (
    list_top_processes, boost_foreground, throttle_background,
)
from src.models.startup import (
    StartupItem, list_startup_items,
    toggle_startup_registry, toggle_startup_task,
)
from src.models.system_info import format_bytes
from src.utils.winapi import get_memory_status


# ── 工作线程 ─────────────────────────────────────────


class _OptimizeWorker(QThread):
    """智能内存优化线程：清理 + 修剪 + 智能分页 + 动态扩展。"""

    progress = Signal(str)
    finished = Signal(str)

    def __init__(self, settings: "AppSettings", parent=None):
        super().__init__(parent)
        self._settings = settings

    def run(self):
        logger.info("[加速-智能优化] 开始")
        mem_before = get_memory_status()
        actions = []

        if self._settings.purge_standby_enabled:
            self.progress.emit("正在清理备用列表...")
            if force_purge():
                actions.append("已清理内存缓存")

        if self._settings.trim_workingset_enabled:
            self.progress.emit("正在修剪后台工作集...")
            count = trim_background_working_sets()
            if count:
                actions.append(f"已修剪 {count} 个后台进程")

        if self._settings.pageout_idle_enabled:
            self.progress.emit("正在智能分页空闲进程...")
            paged = page_out_idle_processes()
            if paged:
                total_mb = sum(mb for _, mb in paged)
                actions.append(f"已分页 {len(paged)} 个空闲进程（约 {total_mb:.0f} MB）")

        # 虚拟内存检查与智能线性扩展（基于提交费用占比）
        threshold = self._settings.pagefile_expand_threshold
        if self._settings.auto_pagefile_enabled:
            ratio = get_commit_ratio()
            logger.info("[加速-智能优化] 提交比=%.1f%%, 扩展阈值=%d%%",
                        ratio * 100, threshold)
            if ratio * 100 > threshold:
                self.progress.emit("正在智能扩展分页文件...")
                r = expand_pagefile_incremental(threshold)
                if r:
                    actions.append(r)

        if is_commit_critical():
            rec = recommend_pagefile_mb()
            if adjust_pagefile_size(size_mb=rec):
                actions.append(f"虚拟内存已调至 {rec} MB（需重启生效）")

        mem_after = get_memory_status()
        freed = mem_after.available - mem_before.available
        logger.info("[加速-智能优化] 完成: freed=%d, actions=%s", freed, actions)
        if freed > 0:
            actions.append(f"释放了 {format_bytes(freed)}")

        summary = "、".join(actions) if actions else "系统已处于最佳状态"
        self.finished.emit(summary)


class _RefreshProcessesWorker(QThread):
    """后台进程列表刷新线程。"""

    finished = Signal(list)

    def run(self):
        self.finished.emit(list_top_processes())


class _RefreshMemoryWorker(QThread):
    """后台内存状态刷新线程。"""

    finished = Signal(dict)

    def run(self):
        mem = get_memory_status()
        ratio = get_commit_ratio()
        self.finished.emit({
            "total": format_bytes(mem.total),
            "used": format_bytes(mem.used),
            "available": format_bytes(mem.available),
            "percent": mem.percent,
            "commit_ratio": round(ratio * 100, 1),
            "commit_critical": is_commit_critical(),
            "recommended_pf": recommend_pagefile_mb(),
        })


class _LoadStartupWorker(QThread):
    """后台加载启动项列表。"""

    finished = Signal(list)

    def run(self):
        self.finished.emit(list_startup_items())


# ── 视图模型 ─────────────────────────────────────────


class OptimizerViewModel(QObject):
    """加速页视图模型：内存优化 + 启动项 + 进程管理。"""

    # 内存优化信号
    optimize_progress = Signal(str)
    optimize_done = Signal(str)
    memory_updated = Signal(dict)
    processes_updated = Signal(list)

    # 启动项信号
    startup_loaded = Signal(list)
    startup_toggled = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = AppSettings()
        self._worker: _OptimizeWorker | None = None
        self._proc_worker: _RefreshProcessesWorker | None = None
        self._mem_worker: _RefreshMemoryWorker | None = None
        self._startup_worker: _LoadStartupWorker | None = None

    # ── 内存优化 ─────────────────────────────────────

    def start_optimize(self):
        """启动智能内存优化。"""
        if self._worker and self._worker.isRunning():
            return
        self._worker = _OptimizeWorker(self._settings)
        self._worker.progress.connect(self.optimize_progress.emit)
        self._worker.finished.connect(self.optimize_done.emit)
        self._worker.start()

    def refresh_memory(self):
        """异步刷新内存状态。"""
        if self._mem_worker and self._mem_worker.isRunning():
            return
        self._mem_worker = _RefreshMemoryWorker()
        self._mem_worker.finished.connect(self.memory_updated.emit)
        self._mem_worker.start()

    def refresh_processes(self):
        """异步刷新进程列表。"""
        if self._proc_worker and self._proc_worker.isRunning():
            return
        self._proc_worker = _RefreshProcessesWorker()
        self._proc_worker.finished.connect(self.processes_updated.emit)
        self._proc_worker.start()

    def boost_process(self, pid: int) -> bool:
        """提升进程优先级。"""
        return boost_foreground(pid)

    def throttle_process(self, pid: int) -> bool:
        """降低进程优先级。"""
        return throttle_background(pid)

    # ── 启动项管理 ───────────────────────────────────

    def refresh_startup(self):
        """异步加载启动项列表。"""
        if self._startup_worker and self._startup_worker.isRunning():
            return
        self._startup_worker = _LoadStartupWorker()
        self._startup_worker.finished.connect(self.startup_loaded.emit)
        self._startup_worker.start()

    def toggle_startup(self, item: StartupItem, enable: bool):
        """切换启动项状态。"""
        if item.source == "registry":
            ok = toggle_startup_registry(item, enable)
        else:
            ok = toggle_startup_task(item, enable)
        action = "启用" if enable else "禁用"
        status = "成功" if ok else "失败"
        self.startup_toggled.emit(f"{action} {item.name}: {status}")
