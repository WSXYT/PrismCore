"""系统信息采集模块。"""

import platform
from typing import NamedTuple

import psutil


class CpuSnapshot(NamedTuple):
    """CPU 状态快照。"""
    name: str
    cores_physical: int
    cores_logical: int
    percent: float
    freq_current: float
    freq_max: float


class DiskSnapshot(NamedTuple):
    """磁盘分区状态快照。"""
    device: str
    mountpoint: str
    total: int
    used: int
    free: int
    percent: float


def get_cpu_snapshot() -> CpuSnapshot:
    """获取当前 CPU 状态快照。"""
    freq = psutil.cpu_freq()
    return CpuSnapshot(
        name=platform.processor() or "Unknown",
        cores_physical=psutil.cpu_count(logical=False) or 0,
        cores_logical=psutil.cpu_count(logical=True) or 0,
        percent=psutil.cpu_percent(interval=0),
        freq_current=freq.current if freq else 0.0,
        freq_max=freq.max if freq else 0.0,
    )


def get_disk_snapshots() -> list[DiskSnapshot]:
    """获取所有磁盘分区的使用情况。"""
    results = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        results.append(DiskSnapshot(
            device=part.device,
            mountpoint=part.mountpoint,
            total=usage.total,
            used=usage.used,
            free=usage.free,
            percent=usage.percent,
        ))
    return results


def format_bytes(n: int) -> str:
    """将字节数格式化为易读字符串（如 1.5 GB）。"""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"
