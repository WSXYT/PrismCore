"""智能内存管理 — 备用列表清理、工作集修剪、页面文件调整。"""

import logging
import subprocess

import psutil

from src.utils.constants import (
    FREE_MEM_THRESHOLD_BYTES,
    STANDBY_RATIO_THRESHOLD,
    COMMIT_RATIO_WARNING,
    PROTECTED_PROCESSES,
    AUDIO_PROCESSES,
    PAGE_FAULT_DELTA_THRESHOLD,
)
from src.utils.winapi import (
    get_memory_status,
    purge_standby_list,
    empty_working_set,
    get_foreground_window_pid,
    is_foreground_fullscreen,
)

logger = logging.getLogger(__name__)

# 页错误增量追踪（用于压力触发判断）
_last_page_fault_count: int = 0


def _get_total_page_faults() -> int:
    """获取系统所有进程的页错误总数。"""
    total = 0
    for proc in psutil.process_iter(["pid"]):
        try:
            mi = proc.memory_info()
            total += mi.num_page_faults
        except (psutil.AccessDenied, psutil.NoSuchProcess, AttributeError):
            continue
    return total


def get_page_fault_delta() -> int:
    """返回自上次调用以来的页错误增量。"""
    global _last_page_fault_count
    current = _get_total_page_faults()
    delta = current - _last_page_fault_count if _last_page_fault_count else 0
    _last_page_fault_count = current
    return max(delta, 0)


def should_purge_standby(pressure_mode: bool = False) -> bool:
    """判断是否需要清理备用列表。

    pressure_mode=True 时使用压力触发逻辑（3.1.2）：
    - 空闲内存 < 1GB
    - 备用列表 > 总内存 40%
    - 前台窗口为全屏（游戏/视频）或页错误增量高
    """
    mem = get_memory_status()
    logger.info("should_purge: available=%d, total=%d, used=%.1f%%, pressure=%s",
                mem.available, mem.total, mem.percent, pressure_mode)
    if mem.available >= FREE_MEM_THRESHOLD_BYTES:
        logger.info("可用内存充足 (%d >= %d)，跳过清理。", mem.available, FREE_MEM_THRESHOLD_BYTES)
        return False
    standby_est = max(0, mem.total - mem.used - mem.available)
    threshold = mem.total * STANDBY_RATIO_THRESHOLD
    logger.info("备用列表估算: %d, 阈值: %d", standby_est, int(threshold))
    if standby_est <= threshold:
        return False

    if not pressure_mode:
        return True

    # 压力触发：全屏应用或页错误增量高
    if is_foreground_fullscreen():
        logger.info("检测到全屏应用，触发压力清理。")
        return True
    pf_delta = get_page_fault_delta()
    logger.info("页错误增量: %d", pf_delta)
    if pf_delta > PAGE_FAULT_DELTA_THRESHOLD:
        logger.info("页错误增量 %d，触发压力清理。", pf_delta)
        return True
    return False


def smart_purge(pressure_mode: bool = False) -> bool:
    """智能清理备用列表。

    pressure_mode=True 时使用压力触发算法（全屏检测+页错误增量）。
    """
    logger.info("smart_purge: pressure_mode=%s", pressure_mode)
    if not should_purge_standby(pressure_mode):
        logger.info("smart_purge: 条件不满足，跳过。")
        return False
    return force_purge()


def force_purge() -> bool:
    """强制清理备用列表（用于用户手动触发）。"""
    logger.info("force_purge: 开始调用 purge_standby_list()")
    ok = purge_standby_list()
    if ok:
        logger.info("备用列表清理成功。")
    else:
        logger.exception("备用列表清理失败")
    return ok


def trim_background_working_sets() -> int:
    """修剪后台进程工作集，保护前台窗口和音频进程。"""
    trimmed = 0
    fg_pid = get_foreground_window_pid()
    logger.info("trim_background_working_sets: 前台窗口 PID=%d", fg_pid)
    for proc in psutil.process_iter(["pid", "name", "status"]):
        try:
            name = (proc.info["name"] or "").lower()
            pid = proc.info["pid"]
            if name in PROTECTED_PROCESSES or name in AUDIO_PROCESSES:
                continue
            if pid == fg_pid:
                continue
            nice = proc.nice()
            if nice < psutil.BELOW_NORMAL_PRIORITY_CLASS:
                continue
            if empty_working_set(pid):
                trimmed += 1
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    logger.info("已修剪 %d 个进程的工作集。", trimmed)
    return trimmed


def get_commit_ratio() -> float:
    """返回提交费用/提交限制比率（0.0 – 1.0）。"""
    mem = get_memory_status()
    if mem.commit_limit == 0:
        return 0.0
    return mem.commit_total / mem.commit_limit


def is_commit_critical() -> bool:
    return get_commit_ratio() >= COMMIT_RATIO_WARNING


def adjust_pagefile_size(drive: str = "C:", size_mb: int = 8192) -> bool:
    """通过 wmic 调整页面文件（需要管理员权限）。设置初始=最大=size_mb。"""
    try:
        cmd = (
            f'wmic pagefileset where name="{drive}\\\\pagefile.sys" '
            f"set InitialSize={size_mb},MaximumSize={size_mb}"
        )
        subprocess.run(
            cmd, shell=True, check=True,
            capture_output=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        logger.info("已将 %s 上的页面文件设为 %d MB。", drive, size_mb)
        return True
    except Exception:
        logger.error("调整页面文件失败")
        return False


def recommend_pagefile_mb() -> int:
    """推荐页面文件大小：物理内存的 1.5 倍，上限 32 GB。"""
    mem = get_memory_status()
    recommended = int(mem.total * 1.5 / (1024 ** 2))
    return min(recommended, 32768)


def page_out_idle_processes(min_mb: float = 10.0) -> list[tuple[str, float]]:
    """智能识别空闲大内存进程并将其工作集页出到虚拟内存。

    判断标准：非保护/音频进程、非前台、CPU≈0%、内存>min_mb。
    返回 [(进程名, 释放MB), ...]。
    """
    results = []
    fg_pid = get_foreground_window_pid()
    min_bytes = min_mb * 1024 * 1024

    for proc in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            name = (proc.info["name"] or "").lower()
            pid = proc.info["pid"]
            mem_info = proc.info["memory_info"]
            if not mem_info or mem_info.rss < min_bytes:
                continue
            if name in PROTECTED_PROCESSES or name in AUDIO_PROCESSES:
                continue
            if pid == fg_pid:
                continue
            # CPU 使用率≈0 表示近期无活动
            cpu = proc.cpu_percent(interval=0)
            if cpu > 5.0:
                continue
            rss_before = mem_info.rss
            if empty_working_set(pid):
                # 重新读取 RSS 估算释放量
                try:
                    rss_after = proc.memory_info().rss
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    rss_after = 0
                freed_mb = (rss_before - rss_after) / (1024 ** 2)
                if freed_mb > 0:
                    results.append((name, round(freed_mb, 1)))
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue

    total = sum(mb for _, mb in results)
    logger.info("智能进程分页: 处理 %d 个进程，释放约 %.0f MB", len(results), total)
    return results
