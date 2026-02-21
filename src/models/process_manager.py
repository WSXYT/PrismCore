"""进程和 CPU 亲和性管理。"""

import logging
from dataclasses import dataclass

import psutil

from src.utils.constants import PROTECTED_PROCESSES

logger = logging.getLogger(__name__)


@dataclass
class ProcessInfo:
    pid: int
    name: str
    cpu_percent: float
    memory_mb: float
    priority: int
    status: str


def list_top_processes(count: int = 30) -> list[ProcessInfo]:
    """返回按内存使用量排序的顶部进程。"""
    procs = []
    for p in psutil.process_iter(["pid", "name", "memory_info", "status"]):
        try:
            mem = p.info["memory_info"]
            procs.append(ProcessInfo(
                pid=p.info["pid"],
                name=p.info["name"] or "未知",
                cpu_percent=p.cpu_percent(interval=0),
                memory_mb=(mem.rss / 1024 ** 2) if mem else 0,
                priority=p.nice(),
                status=p.info["status"],
            ))
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    procs.sort(key=lambda x: x.memory_mb, reverse=True)
    return procs[:count]


def set_process_priority(pid: int, priority: int) -> bool:
    """设置进程优先级类。"""
    try:
        p = psutil.Process(pid)
        if p.name().lower() in PROTECTED_PROCESSES:
            return False
        p.nice(priority)
        return True
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        return False


def set_process_affinity(pid: int, cpus: list[int]) -> bool:
    """将进程绑定到特定 CPU 核心。"""
    try:
        p = psutil.Process(pid)
        if p.name().lower() in PROTECTED_PROCESSES:
            return False
        p.cpu_affinity(cpus)
        return True
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        return False


def boost_foreground(pid: int) -> bool:
    """将进程设为高优先级并绑定到 P 核心（逻辑 CPU 的前半部分）。"""
    logical = psutil.cpu_count(logical=True) or 1
    physical = psutil.cpu_count(logical=False) or 1
    # 启发式方法：混合 CPU 上的前 `physical` 个逻辑 CPU 是 P 核心
    p_cores = list(range(min(physical, logical)))
    ok1 = set_process_priority(pid, psutil.HIGH_PRIORITY_CLASS)
    ok2 = set_process_affinity(pid, p_cores)
    return ok1 or ok2


def throttle_background(pid: int) -> bool:
    """将后台进程移至 E 核心并设为空闲优先级。"""
    logical = psutil.cpu_count(logical=True) or 1
    physical = psutil.cpu_count(logical=False) or 1
    if logical <= physical:
        return set_process_priority(pid, psutil.IDLE_PRIORITY_CLASS)
    e_cores = list(range(physical, logical))
    ok1 = set_process_priority(pid, psutil.IDLE_PRIORITY_CLASS)
    ok2 = set_process_affinity(pid, e_cores)
    return ok1 or ok2
