"""首页视图模型 — 健康评分、智能优化、实时监控、后台自动优化。"""

import logging
import subprocess
import time
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, QThread, Signal

logger = logging.getLogger(__name__)

from src.models.system_info import (
    get_cpu_snapshot, get_disk_snapshots, format_bytes,
)
from src.models.auto_optimizer import (
    calc_health_score, check_and_auto_optimize,
    expand_pagefile_incremental, get_created_pagefiles,
    remove_all_temp_pagefiles, restore_pagefile_state,
)
from src.models.latency_monitor import LatencyMonitor
from src.models.memory import (
    force_purge, trim_background_working_sets,
    is_commit_critical, recommend_pagefile_mb, adjust_pagefile_size,
    get_commit_ratio, page_out_idle_processes,
)
from src.models.cleaner import (
    scan_electron_caches, scan_temp_files, execute_clean,
)
from src.utils.winapi import get_memory_status, measure_responsiveness
from src.utils.constants import (
    MONITOR_INTERVAL_MS, PROBALANCE_SAMPLE_INTERVAL,
)
from src.models.settings import AppSettings
from src.models.cpu_optimizer import ProBalanceEngine


class _SmartOptimizeWorker(QThread):
    """智能一键优化线程：内存清理 + 智能分页 + 垃圾清理 + 自动调优。"""

    progress = Signal(str)
    finished = Signal(str, int, int)  # summary, score_before, score_after
    pagefile_created = Signal(str)

    def __init__(self, settings: "AppSettings", parent=None):
        super().__init__(parent)
        self._settings = settings

    def run(self):
        logger.info("[智能优化] 开始")
        score_before = calc_health_score()
        mem_before = get_memory_status()
        actions = []

        # 1. 清理备用列表（尊重开关）
        if self._settings.purge_standby_enabled:
            self.progress.emit("正在清理内存缓存...")
            if force_purge():
                actions.append("已清理内存缓存")

        # 2. 修剪后台进程工作集（尊重开关）
        if self._settings.trim_workingset_enabled:
            self.progress.emit("正在修剪后台进程...")
            count = trim_background_working_sets()
            if count:
                actions.append(f"已修剪 {count} 个后台进程")

        # 3. 智能进程分页（尊重开关）
        if self._settings.pageout_idle_enabled:
            self.progress.emit("正在智能分页空闲进程...")
            paged = page_out_idle_processes()
            if paged:
                total_mb = sum(mb for _, mb in paged)
                actions.append(f"已分页 {len(paged)} 个空闲进程（约 {total_mb:.0f} MB）")

        # 4. 快速垃圾清理（临时文件 + Electron 缓存）
        self.progress.emit("正在清理垃圾文件...")
        items = scan_temp_files() + scan_electron_caches()
        logger.info("[智能优化] 扫描到 %d 个垃圾项", len(items))
        if items:
            cleaned, _ = execute_clean(items)
            if cleaned > 0:
                mb = cleaned / (1024 ** 2)
                actions.append(f"清理了 {mb:.0f} MB 垃圾")

        # 5. 智能线性扩展分页文件（基于提交费用占比）
        threshold = self._settings.pagefile_expand_threshold
        if self._settings.auto_pagefile_enabled:
            ratio = get_commit_ratio()
            logger.info("[智能优化] 提交比=%.1f%%, 扩展阈值=%d%%",
                        ratio * 100, threshold)
            if ratio * 100 > threshold:
                self.progress.emit("正在智能扩展分页文件...")
                r = expand_pagefile_incremental(threshold)
                if r:
                    actions.append(r)
                    self.pagefile_created.emit(r)

        if is_commit_critical():
            rec = recommend_pagefile_mb()
            if adjust_pagefile_size(size_mb=rec):
                actions.append(f"虚拟内存已调至 {rec} MB（需重启生效）")

        # 6. 计算释放量
        mem_after = get_memory_status()
        freed = mem_after.available - mem_before.available
        logger.info("[智能优化] 完成: freed=%d, actions=%s", freed, actions)
        if freed > 0:
            actions.append(f"释放了 {format_bytes(freed)}")

        summary = "、".join(actions) if actions else "系统已处于最佳状态"
        # 附加内存对比
        pct_before = mem_before.percent
        pct_after = mem_after.percent
        diff = pct_before - pct_after
        if diff > 0:
            summary += f"\n内存: {pct_before:.0f}% → {pct_after:.0f}% (↓{diff:.0f}%)"
        score_after = calc_health_score()
        self.finished.emit(summary, score_before, score_after)


class DashboardViewModel(QObject):
    """首页视图模型：实时监控 + 健康评分 + 智能优化。"""

    # 实时状态信号
    status_updated = Signal(dict)
    # 智能优化信号
    optimize_progress = Signal(str)
    optimize_done = Signal(str, int, int)  # summary, score_before, score_after
    # 后台自动优化通知
    auto_action = Signal(str)
    # 分页文件状态变更：{"mode", "size_mb", "drive"}
    pagefile_status_changed = Signal(dict)
    # 智能建议：推荐大小 MB
    pagefile_suggest = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = AppSettings()

        self._timer = QTimer(self)
        self._timer.setInterval(MONITOR_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)

        # 后台自动优化定时器
        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(self._settings.auto_optimize_interval * 1000)
        self._auto_timer.timeout.connect(self._auto_check)

        self._worker: _SmartOptimizeWorker | None = None
        self._latency = LatencyMonitor()

        # ProBalance CPU 调度引擎 + 定时器
        self._probalance = ProBalanceEngine()
        self._pb_timer = QTimer(self)
        self._pb_timer.setInterval(PROBALANCE_SAMPLE_INTERVAL * 1000)
        self._pb_timer.timeout.connect(self._probalance_tick)

        # 30分钟建议计时器
        self._suggest_timer = QTimer(self)
        self._suggest_timer.setSingleShot(True)
        self._suggest_timer.timeout.connect(self._on_suggest_timeout)

        # ETW 降级通知（仅首次）
        self._etw_warned = False
        # 响应延迟反馈闭环状态
        self._last_threshold_adjust = time.monotonic()  # 启动后 30 秒内跳过
        self._threshold_boosted = False
        self._original_system_threshold = self._settings.probalance_system_threshold

    def start(self):
        """启动实时监控和后台自动优化。"""
        if self._settings.dpc_monitor_enabled:
            self._latency.open()
        self._tick()
        self._timer.start()
        if self._settings.auto_optimize_enabled:
            self._auto_timer.start()
        if self._settings.probalance_enabled:
            self._pb_timer.start()
        # 恢复分页文件状态
        restore_pagefile_state()
        self._restore_pagefile_ui()

    def stop(self):
        """停止所有定时器并还原 ProBalance 约束。"""
        self._timer.stop()
        self._auto_timer.stop()
        self._pb_timer.stop()
        self._probalance.force_restore_all()
        self._latency.close()

    def start_smart_optimize(self):
        """启动智能一键优化。"""
        if self._worker and self._worker.isRunning():
            return
        self._worker = _SmartOptimizeWorker(self._settings)
        self._worker.progress.connect(self.optimize_progress.emit)
        self._worker.finished.connect(self.optimize_done.emit)
        self._worker.pagefile_created.connect(self._on_pagefile_created)
        self._worker.start()

    def reload_settings(self):
        """设置变更后重新加载定时器参数。"""
        self._auto_timer.setInterval(self._settings.auto_optimize_interval * 1000)
        if self._settings.auto_optimize_enabled:
            self._auto_timer.start()
        else:
            self._auto_timer.stop()
        # DPC 监控开关
        if self._settings.dpc_monitor_enabled:
            self._latency.open()
        else:
            self._latency.close()
        # ProBalance 开关
        if self._settings.probalance_enabled:
            self._pb_timer.start()
        else:
            self._pb_timer.stop()
            self._probalance.force_restore_all()

    def _tick(self):
        """定时采集系统状态。"""
        cpu = get_cpu_snapshot()
        mem = get_memory_status()
        disks = get_disk_snapshots()
        score = calc_health_score()

        # DPC/ISR 延迟采集
        latency = self._latency.sample()

        # 响应延迟反馈闭环：采集 UI 响应延迟并动态调整 ProBalance 阈值
        self._update_responsiveness_feedback()

        # 生成问题提示（与评分阈值对齐）
        issues = []
        if mem.percent > 70:
            issues.append(f"内存使用偏高 ({mem.percent:.0f}%)")
        if cpu.percent > 50:
            issues.append(f"CPU 负载偏高 ({cpu.percent:.0f}%)")
        for d in disks:
            if d.percent > 70:
                issues.append(f"{d.mountpoint} 空间偏紧 ({d.percent:.0f}%)")
        issues.extend(latency.warnings)

        # ETW 降级通知（仅首次）
        if not latency.etw_available and not self._etw_warned:
            issues.append("DPC/ISR 驱动级归因不可用（需管理员权限）")
            self._etw_warned = True

        # ProBalance 状态
        pb_procs = self._probalance.constrained_processes
        pb_count = len(pb_procs)
        pb_threshold = sum(1 for *_, r in pb_procs if r == "threshold")
        pb_anomaly = sum(1 for *_, r in pb_procs if r == "anomaly")
        if pb_count:
            issues.append(f"ProBalance 正在约束 {pb_count} 个进程")

        self.status_updated.emit({
            "score": score,
            "cpu_pct": cpu.percent,
            "mem_pct": mem.percent,
            "mem_used": format_bytes(mem.used),
            "mem_total": format_bytes(mem.total),
            "dpc_pct": latency.dpc_time_percent,
            "isr_pct": latency.isr_time_percent,
            "probalance_count": pb_count,
            "probalance_threshold": pb_threshold,
            "probalance_anomaly": pb_anomaly,
            "disks": [
                {
                    "mount": d.mountpoint,
                    "percent": d.percent,
                    "free": format_bytes(d.free),
                }
                for d in disks
            ],
            "issues": issues,
        })

    def _on_pagefile_created(self, msg: str):
        """Worker 创建分页文件后更新卡片状态并启动建议计时器。"""
        info = self._settings.pagefile_info
        if info:
            self.pagefile_status_changed.emit({
                "mode": "active",
                "size_mb": info["size_mb"],
                "drive": info["drive"],
            })
            self._start_suggest_timer()

    def _start_suggest_timer(self):
        """启动或恢复30分钟建议计时器。"""
        if not self._settings.suggestion_enabled:
            return
        info = self._settings.pagefile_info
        if not info or "created_at" not in info:
            return
        created = datetime.fromisoformat(info["created_at"])
        elapsed = (datetime.now() - created).total_seconds()
        remain_ms = max(0, int((30 * 60 - elapsed) * 1000))
        if remain_ms == 0:
            self._on_suggest_timeout()
        else:
            self._suggest_timer.start(remain_ms)

    def _on_suggest_timeout(self):
        """30分钟到期，发出建议信号。"""
        if self._settings.suggestion_enabled and get_created_pagefiles():
            self.pagefile_suggest.emit(recommend_pagefile_mb())

    def request_reboot_clear(self):
        """用户点击"立即重启清除"：清理分页文件配置后重启。"""
        remove_all_temp_pagefiles()
        self._suggest_timer.stop()
        self._settings.pagefile_info = None
        subprocess.Popen("shutdown /r /t 3", shell=True)

    def accept_suggestion(self, rec_mb: int):
        """用户接受建议：调整系统虚拟内存大小。"""
        if adjust_pagefile_size(size_mb=rec_mb):
            self.pagefile_suggest.emit(-1)  # -1 表示已接受

    def dismiss_suggestion(self):
        """用户忽略建议。"""
        self._suggest_timer.stop()
        self.pagefile_suggest.emit(0)

    def cancel_suggestion(self):
        """用户撤销已接受的建议（不重启即不生效）。"""
        self.pagefile_suggest.emit(0)

    def _restore_pagefile_ui(self):
        """从 QSettings 恢复卡片状态。"""
        info = self._settings.pagefile_info
        if info:
            self.pagefile_status_changed.emit({
                "mode": "active",
                "size_mb": info["size_mb"],
                "drive": info["drive"],
            })
            self._start_suggest_timer()

    def _probalance_tick(self):
        """ProBalance 定时采样：自动约束/还原 CPU 霸占进程。"""
        snap = self._probalance.tick(
            system_threshold=self._settings.probalance_system_threshold,
            process_threshold=self._settings.probalance_process_threshold,
            anomaly_enabled=self._settings.anomaly_detection_enabled,
            z_threshold=self._settings.anomaly_z_threshold,
            ewma_alpha=self._settings.ewma_alpha,
        )
        for action in snap.actions:
            self.auto_action.emit(f"[ProBalance] {action}")
        for action in snap.anomaly_actions:
            self.auto_action.emit(f"[ProBalance:异常检测] {action}")
        if snap.restored_count:
            self.auto_action.emit(
                f"[ProBalance] 系统负载恢复，已还原 {snap.restored_count} 个进程"
            )

    def _update_responsiveness_feedback(self):
        """响应延迟反馈闭环：根据 UI 响应延迟动态调整 ProBalance 阈值。"""
        now = time.monotonic()
        # 冷却期 30 秒
        if now - self._last_threshold_adjust < 30:
            return

        latency_ms = measure_responsiveness()

        if latency_ms > 200 and not self._threshold_boosted:
            # 延迟飙升：降低阈值使 ProBalance 更积极干预（下限 50%）
            new_threshold = max(50, self._original_system_threshold - 15)
            self._settings.probalance_system_threshold = new_threshold
            self._threshold_boosted = True
            self._last_threshold_adjust = now
            logger.info("响应延迟 %dms，ProBalance 阈值降至 %d%%",
                        latency_ms, new_threshold)
        elif latency_ms <= 100 and self._threshold_boosted:
            # 延迟正常：恢复默认阈值
            self._settings.probalance_system_threshold = self._original_system_threshold
            self._threshold_boosted = False
            self._last_threshold_adjust = now
            logger.info("响应延迟恢复正常 %dms，ProBalance 阈值恢复 %d%%",
                        latency_ms, self._original_system_threshold)

    def _auto_check(self):
        """后台自动检测并优化（静默执行，尊重设置阈值和策略开关）。"""
        mem = get_memory_status()
        threshold = self._settings.pagefile_expand_threshold
        ratio = get_commit_ratio()

        # 自动撤回：提交比降至阈值-15% 以下且存在临时分页文件
        if ratio * 100 < threshold - 15 and get_created_pagefiles():
            remove_all_temp_pagefiles()
            self._settings.pagefile_info = None
            self.pagefile_status_changed.emit({"mode": "idle"})
            self.auto_action.emit("提交比已恢复，已自动清理临时分页文件配置")

        if mem.percent < self._settings.memory_threshold:
            return
        actions = check_and_auto_optimize()

        # 自动将空闲进程页出到虚拟内存（尊重开关）
        if self._settings.pageout_idle_enabled:
            paged = page_out_idle_processes()
            if paged:
                total_mb = sum(mb for _, mb in paged)
                actions.append(
                    f"已自动分页 {len(paged)} 个空闲进程（约 {total_mb:.0f} MB）"
                )

        for action in actions:
            self.auto_action.emit(action)
