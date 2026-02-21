"""后台自动优化器 — 内存压力监控、自动清理备用列表、临时分页文件管理。"""

import os
import subprocess
import logging
from datetime import datetime

import psutil

# 预热 psutil CPU 采样（首次调用 cpu_percent(interval=0) 返回 0.0）
psutil.cpu_percent(interval=0)

from src.utils.winapi import (
    get_memory_status, purge_standby_list, get_disk_free,
    nt_create_paging_file,
)
from src.utils.constants import (
    FREE_MEM_THRESHOLD_BYTES,
    STANDBY_RATIO_THRESHOLD,
    COMMIT_RATIO_WARNING,
)
from src.models.memory import trim_background_working_sets, smart_purge

logger = logging.getLogger(__name__)

# 跟踪本次会话中创建的临时分页文件：驱动器路径 → 创建方式 ("dynamic" | "wmic")
_created_pagefiles: dict[str, str] = {}
_current_pagefile_size_mb: int = 0


def _save_pagefile_info(drive: str, method: str, size_mb: int):
    """将分页文件信息持久化到 QSettings。"""
    from src.models.settings import AppSettings
    AppSettings().pagefile_info = {
        "drive": drive, "method": method,
        "size_mb": size_mb, "created_at": datetime.now().isoformat(),
    }


def restore_pagefile_state():
    """从 QSettings 恢复上次会话的分页文件跟踪状态。

    检查临时分页文件是否仍存在，不存在则清除记录。
    """
    global _created_pagefiles, _current_pagefile_size_mb
    from src.models.settings import AppSettings
    settings = AppSettings()
    info = settings.pagefile_info
    if not info:
        return
    pagefile_path = os.path.join(info["drive"], "pagefile.sys")
    if not os.path.exists(pagefile_path):
        logger.info("临时分页文件 %s 已不存在，清除记录", pagefile_path)
        settings.pagefile_info = None
        return
    _created_pagefiles[info["drive"]] = info["method"]
    _current_pagefile_size_mb = info["size_mb"]


def calc_health_score() -> int:
    """计算系统健康评分（0-100）。

    评分维度（阈值式，正常使用不扣分）：
    - 内存使用率（40分）：< 70% 满分，70-90% 线性扣分，> 90% 接近 0
    - CPU 使用率（30分）：< 50% 满分，50-90% 线性扣分，> 90% 接近 0
    - 磁盘剩余空间（30分）：< 70% 满分，70-90% 线性扣分，> 90% 接近 0
    """
    mem = get_memory_status()
    cpu_pct = psutil.cpu_percent(interval=0)

    def _score(percent: float, full: int, low: float, high: float) -> int:
        """低于 low 满分，low~high 线性扣分，高于 high 给 0。"""
        if percent <= low:
            return full
        if percent >= high:
            return 0
        return int(full * (high - percent) / (high - low))

    mem_score = _score(mem.percent, 40, 70, 95)
    cpu_score = _score(cpu_pct, 30, 50, 95)

    disk_score = 30
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            s = _score(usage.percent, 30, 70, 95)
            disk_score = min(disk_score, s)
        except OSError:
            continue

    return min(100, mem_score + cpu_score + disk_score)


def check_and_auto_optimize() -> list[str]:
    """检测系统压力并自动执行优化（压力触发式）。返回执行的操作列表。"""
    actions = []
    mem = get_memory_status()
    logger.info("auto_optimize: mem_available=%d, commit=%d/%d",
                 mem.available, mem.commit_total, mem.commit_limit)

    # 压力触发式内存清洗（3.1.2）：全屏检测+页错误增量
    if mem.available < FREE_MEM_THRESHOLD_BYTES:
        logger.info("可用内存不足，尝试压力触发清理。")
        if smart_purge(pressure_mode=True):
            actions.append("已自动清理内存备用列表")
        count = trim_background_working_sets()
        if count > 0:
            actions.append(f"已自动修剪 {count} 个后台进程")

    # 提交费用危险：动态扩展分页文件（3.2）
    if mem.commit_limit > 0:
        ratio = mem.commit_total / mem.commit_limit
        logger.info("提交比: %.1f%% (阈值 %.0f%%)", ratio * 100, COMMIT_RATIO_WARNING * 100)
        if ratio >= COMMIT_RATIO_WARNING:
            logger.info("提交比超限，尝试动态扩展分页文件。")
            result = create_temp_pagefile_dynamic()
            if not result:
                result = create_temp_pagefile()
            if result:
                actions.append(result)

    logger.info("auto_optimize 完成，动作: %s", actions)
    return actions


def find_best_drive_for_pagefile() -> str | None:
    """查找最适合创建临时分页文件的分区。

    优先选非 C 盘，若无合适分区则回退到 C 盘。
    选择标准：可用空间最大且 > 8GB。
    """
    best_drive = None
    best_free = 0
    c_drive = None
    c_free = 0
    min_free = 8 * 1024 ** 3  # 至少 8GB 可用

    for part in psutil.disk_partitions(all=False):
        mp = part.mountpoint
        try:
            free = get_disk_free(mp)
        except OSError:
            continue
        if mp.upper().startswith("C"):
            if free > min_free:
                c_drive = mp
                c_free = free
            continue
        if free > min_free and free > best_free:
            best_free = free
            best_drive = mp

    return best_drive if best_drive else c_drive


def create_temp_pagefile_dynamic(size_mb: int = 4096) -> str | None:
    """通过 NtCreatePagingFile 动态扩展分页文件（无需重启，立即生效）。

    优先使用此方法，失败时回退到 wmic 方案。
    """
    drive = find_best_drive_for_pagefile()
    if not drive:
        logger.info("create_temp_pagefile_dynamic: 未找到合适分区。")
        return None

    drive_letter = drive.rstrip("\\").rstrip(":")
    nt_path = f"\\??\\{drive_letter}:\\pagefile.sys"
    size_bytes = size_mb * 1024 * 1024
    logger.info("尝试 NtCreatePagingFile: path=%s, size=%dMB", nt_path, size_mb)

    from src.utils.privilege import enable_privilege
    priv_ok = enable_privilege("SeCreatePagefilePrivilege")
    logger.info("提权 SeCreatePagefilePrivilege: %s", priv_ok)

    if nt_create_paging_file(nt_path, size_bytes, size_bytes):
        logger.info("已通过 NtCreatePagingFile 在 %s 动态创建 %dMB 分页文件。",
                     drive, size_mb)
        _created_pagefiles[drive] = "dynamic"
        _save_pagefile_info(drive, "dynamic", size_mb)
        return f"已在 {drive} 动态扩展 {size_mb}MB 分页文件（立即生效）"

    logger.info("NtCreatePagingFile 失败，将回退到 wmic。")
    return None


def create_temp_pagefile(size_mb: int = 4096) -> str | None:
    """在非系统分区创建临时分页文件以缓解提交限制压力。

    参数:
        size_mb: 临时分页文件大小（MB），默认 4GB

    返回:
        成功时返回描述字符串，失败返回 None
    """
    drive = find_best_drive_for_pagefile()
    if not drive:
        logger.info("create_temp_pagefile: 未找到合适分区。")
        return None

    drive_letter = drive.rstrip("\\")
    logger.info("尝试 wmic 创建分页文件: %s, size=%dMB", drive_letter, size_mb)
    try:
        cmd = (
            f'wmic pagefileset create name="{drive_letter}\\pagefile.sys"'
        )
        subprocess.run(cmd, shell=True, check=True,
                       capture_output=True, timeout=30,
                       creationflags=subprocess.CREATE_NO_WINDOW)

        cmd2 = (
            f'wmic pagefileset where name="{drive_letter}\\\\pagefile.sys" '
            f"set InitialSize={size_mb},MaximumSize={size_mb}"
        )
        subprocess.run(cmd2, shell=True, check=True,
                       capture_output=True, timeout=30,
                       creationflags=subprocess.CREATE_NO_WINDOW)

        logger.info("已在 %s 创建 %dMB 临时分页文件。", drive, size_mb)
        _created_pagefiles[drive] = "wmic"
        _save_pagefile_info(drive, "wmic", size_mb)
        return f"已在 {drive} 创建 {size_mb}MB 临时分页文件（需重启生效）"
    except Exception:
        logger.warning("创建临时分页文件失败。", exc_info=True)
        return None


def get_created_pagefiles() -> list[str]:
    """返回本次会话中创建的临时分页文件驱动器列表。"""
    return list(_created_pagefiles.keys())


def remove_temp_pagefile(drive: str) -> bool:
    """通过 wmic 删除指定驱动器的分页文件配置（需重启生效）。"""
    drive_letter = drive.rstrip("\\")
    try:
        cmd = (
            f'wmic pagefileset where name="{drive_letter}\\\\pagefile.sys" delete'
        )
        subprocess.run(cmd, shell=True, check=True,
                       capture_output=True, timeout=30,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        logger.info("已删除 %s 上的分页文件配置（重启后生效）。", drive)
        return True
    except Exception:
        logger.warning("删除分页文件失败: %s", drive, exc_info=True)
        return False


def remove_all_temp_pagefiles() -> list[str]:
    """删除所有本次会话创建的临时分页文件，返回成功的驱动器列表。"""
    global _current_pagefile_size_mb
    removed = []
    for drive, method in list(_created_pagefiles.items()):
        if method == "dynamic":
            # NtCreatePagingFile 创建的动态分页文件无法运行时删除，重启后自动消失
            removed.append(drive)
        elif remove_temp_pagefile(drive):
            removed.append(drive)
    for d in removed:
        _created_pagefiles.pop(d, None)
    _current_pagefile_size_mb = 0
    from src.models.settings import AppSettings
    AppSettings().pagefile_info = None
    logger.info("批量撤回临时分页文件: %s", removed)
    return removed


def expand_pagefile_incremental(threshold_pct: int = 80) -> str | None:
    """根据实际提交费用需求智能线性扩展分页文件。

    计算超出阈值的部分 + 20% 余量，累计上限 8GB。
    """
    global _current_pagefile_size_mb

    if _current_pagefile_size_mb >= 8192:
        logger.info("分页文件已达上限 8GB，跳过扩展。")
        return None

    mem = get_memory_status()
    if mem.commit_limit == 0:
        return None

    ratio = mem.commit_total / mem.commit_limit
    if ratio * 100 <= threshold_pct:
        return None

    # 计算需要扩展的大小：超出阈值的部分 + 20% 余量
    threshold_bytes = mem.commit_limit * threshold_pct / 100
    need_bytes = mem.commit_total - threshold_bytes
    expand_mb = max(256, int(need_bytes * 1.2 / (1024 ** 2)))

    new_total = min(_current_pagefile_size_mb + expand_mb, 8192)
    if new_total <= _current_pagefile_size_mb:
        return None

    logger.info("智能扩展分页文件: 当前=%dMB, 扩展=%dMB, 新总量=%dMB",
                _current_pagefile_size_mb, expand_mb, new_total)

    drive = find_best_drive_for_pagefile()
    if not drive:
        return None

    drive_letter = drive.rstrip("\\").rstrip(":")
    nt_path = f"\\??\\{drive_letter}:\\pagefile.sys"
    size_bytes = new_total * 1024 * 1024

    from src.utils.privilege import enable_privilege
    enable_privilege("SeCreatePagefilePrivilege")

    if nt_create_paging_file(nt_path, size_bytes, size_bytes):
        _current_pagefile_size_mb = new_total
        _created_pagefiles[drive] = "dynamic"
        _save_pagefile_info(drive, "dynamic", new_total)
        msg = f"已在 {drive} 扩展分页文件至 {new_total}MB（立即生效）"
        logger.info(msg)
        return msg

    # NtCreatePagingFile 失败，回退到 wmic
    result = create_temp_pagefile(size_mb=new_total)
    if result:
        _current_pagefile_size_mb = new_total
    return result
