"""系统级清理操作 — WinSxS、驱动商店、CompactOS、注册表、Windows Update。"""

import logging
import os
import shutil
import subprocess
import winreg
from dataclasses import dataclass, field
from itertools import groupby

from src.utils.constants import REGISTRY_BACKUP_DIR, DISK_CRITICAL_BYTES
from src.utils.winapi import get_disk_free

logger = logging.getLogger(__name__)


@dataclass
class SystemCleanResult:
    """系统清理操作结果。"""
    action: str
    success: bool
    message: str
    freed_bytes: int = 0


# ── WinSxS 组件存储 ──────────────────────────────────────────

def cleanup_winsxs(aggressive: bool = False) -> SystemCleanResult:
    """清理 WinSxS 组件存储。aggressive=True 时使用 /ResetBase。"""
    cmd = ["Dism.exe", "/Online", "/Cleanup-Image", "/StartComponentCleanup"]
    if aggressive:
        cmd.append("/ResetBase")
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=600,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        return SystemCleanResult("WinSxS", True, "组件存储清理完成")
    except Exception as e:
        return SystemCleanResult("WinSxS", False, f"清理失败: {e}")


# ── 驱动商店 ──────────────────────────────────────────────────

def list_old_drivers() -> list[dict]:
    """枚举驱动商店中的旧版本驱动，返回可删除列表。

    使用位置解析（按空行分隔记录，按字段顺序匹配），
    兼容任意 locale 的 pnputil 输出。
    """
    try:
        result = subprocess.run(
            ["pnputil", "/enum-drivers"],
            capture_output=True, text=True, timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        logger.error("枚举驱动商店失败")
        return []
    drivers = []
    blocks = result.stdout.split("\n\n")
    for block in blocks:
        fields = []
        for line in block.strip().splitlines():
            if ":" not in line:
                continue
            _, _, val = line.partition(":")
            fields.append(val.strip())
        # pnputil 每条记录至少有：发布名称、原始名称、提供程序、类名、类GUID、版本、签名者
        if len(fields) < 4:
            continue
        current = {"inf": fields[0]}
        # 类名在第4个字段（索引3），版本在第6个字段（索引5）
        if len(fields) > 3:
            current["class"] = fields[3]
        if len(fields) > 5:
            current["version"] = fields[5]
        if current.get("inf"):
            drivers.append(current)

    # 按类分组，保留最新，标记旧版本
    drivers.sort(key=lambda d: d.get("class", ""))
    removable = []
    for _, group in groupby(drivers, key=lambda d: d.get("class", "")):
        items = list(group)
        if len(items) > 1:
            removable.extend(items[:-1])
    return removable


def delete_driver(inf_name: str) -> bool:
    """删除指定旧驱动包。"""
    try:
        subprocess.run(
            ["pnputil", "/delete-driver", inf_name],
            check=True, capture_output=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return True
    except Exception:
        logger.error("删除驱动 %s 失败", inf_name)
        return False


# ── CompactOS ─────────────────────────────────────────────────

def should_compact_os() -> bool:
    """判断是否建议启用 CompactOS（C盘空间 < 10GB）。"""
    return get_disk_free("C:\\") < DISK_CRITICAL_BYTES


def enable_compact_os() -> SystemCleanResult:
    """启用 CompactOS 压缩系统文件。"""
    try:
        subprocess.run(
            ["compact.exe", "/CompactOS:always"],
            check=True, capture_output=True, timeout=600,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return SystemCleanResult("CompactOS", True, "系统文件已压缩")
    except Exception as e:
        return SystemCleanResult("CompactOS", False, f"压缩失败: {e}")


# ── 注册表孤立项清理 ─────────────────────────────────────────

def scan_orphan_registry() -> list[dict]:
    """扫描孤立注册表项（引用的文件不存在）。"""
    orphans: list[dict] = []
    _scan_clsid_orphans(orphans)
    _scan_app_paths_orphans(orphans)
    _scan_uninstall_orphans(orphans)
    return orphans


def _scan_clsid_orphans(orphans: list):
    try:
        key = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"CLSID")
        i = 0
        while True:
            try:
                name = winreg.EnumKey(key, i)
                i += 1
                try:
                    srv = winreg.OpenKey(key, f"{name}\\InProcServer32")
                    dll, _ = winreg.QueryValueEx(srv, "")
                    winreg.CloseKey(srv)
                    if dll and not os.path.exists(os.path.expandvars(dll)):
                        orphans.append({
                            "key": f"HKCR\\CLSID\\{name}",
                            "type": "CLSID",
                            "ref": dll,
                        })
                except OSError:
                    pass
            except OSError:
                break
        winreg.CloseKey(key)
    except OSError:
        pass


def _scan_app_paths_orphans(orphans: list):
    path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
        i = 0
        while True:
            try:
                name = winreg.EnumKey(key, i)
                i += 1
                sub = winreg.OpenKey(key, name)
                exe, _ = winreg.QueryValueEx(sub, "")
                winreg.CloseKey(sub)
                if exe and not os.path.exists(os.path.expandvars(exe)):
                    orphans.append({
                        "key": f"HKLM\\{path}\\{name}",
                        "type": "AppPath",
                        "ref": exe,
                    })
            except OSError:
                break
        winreg.CloseKey(key)
    except OSError:
        pass


def _scan_uninstall_orphans(orphans: list):
    path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
        i = 0
        while True:
            try:
                name = winreg.EnumKey(key, i)
                i += 1
                sub = winreg.OpenKey(key, name)
                try:
                    loc, _ = winreg.QueryValueEx(sub, "InstallLocation")
                    if loc and loc.strip() and not os.path.exists(os.path.expandvars(loc)):
                        orphans.append({
                            "key": f"HKLM\\{path}\\{name}",
                            "type": "Uninstall",
                            "ref": loc,
                        })
                except OSError:
                    pass
                winreg.CloseKey(sub)
            except OSError:
                break
        winreg.CloseKey(key)
    except OSError:
        pass


def backup_and_delete_key(key_path: str) -> bool:
    """备份注册表项后删除（reg export → reg delete）。"""
    os.makedirs(REGISTRY_BACKUP_DIR, exist_ok=True)
    safe_name = key_path.replace("\\", "_").replace("/", "_")
    backup_file = os.path.join(REGISTRY_BACKUP_DIR, f"{safe_name}.reg")
    try:
        subprocess.run(
            ["reg", "export", key_path, backup_file, "/y"],
            check=True, capture_output=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        subprocess.run(
            ["reg", "delete", key_path, "/f"],
            check=True, capture_output=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return True
    except Exception:
        logger.error("备份/删除注册表项失败: %s", key_path)
        return False


# ── Windows Update 缓存 ──────────────────────────────────────

def cleanup_windows_update() -> SystemCleanResult:
    """清理 SoftwareDistribution\\Download 文件夹。"""
    dl_path = os.path.join(
        os.environ.get("SYSTEMROOT", r"C:\Windows"),
        "SoftwareDistribution", "Download",
    )
    if not os.path.isdir(dl_path):
        return SystemCleanResult("WinUpdate", False, "目录不存在")
    freed = 0
    for entry in os.scandir(dl_path):
        try:
            if entry.is_dir(follow_symlinks=False):
                size = _dir_size(entry.path)
                shutil.rmtree(entry.path)
                freed += size
            else:
                freed += entry.stat(follow_symlinks=False).st_size
                os.remove(entry.path)
        except OSError:
            continue
    return SystemCleanResult("WinUpdate", True, "已清理更新缓存", freed)


def _dir_size(path: str) -> int:
    """迭代计算目录总大小（栈模拟，避免栈溢出）。"""
    total = 0
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            for e in os.scandir(current):
                if e.is_file(follow_symlinks=False):
                    total += e.stat(follow_symlinks=False).st_size
                elif e.is_dir(follow_symlinks=False):
                    stack.append(e.path)
        except OSError:
            pass
    return total


# ── 扫描估算函数（用于整合到统一扫描流程）─────────────────────

def scan_update_cache_size() -> int:
    """估算 Windows Update 缓存大小（字节）。"""
    dl_path = os.path.join(
        os.environ.get("SYSTEMROOT", r"C:\Windows"),
        "SoftwareDistribution", "Download",
    )
    return _dir_size(dl_path) if os.path.isdir(dl_path) else 0


def scan_old_drivers_info() -> list[dict]:
    """扫描旧驱动，返回可删除列表。复用 list_old_drivers。"""
    return list_old_drivers()


def scan_orphan_registry_info() -> list[dict]:
    """扫描孤立注册表项。复用 scan_orphan_registry。"""
    return scan_orphan_registry()


def query_compact_os_status() -> bool:
    """查询 CompactOS 是否已启用。返回 True 表示未启用（可压缩）。"""
    try:
        r = subprocess.run(
            ["compact.exe", "/CompactOS:query"],
            capture_output=True, text=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        # 输出包含 "未" 或 "not" 表示未压缩
        return "未" in r.stdout or "not" in r.stdout.lower()
    except Exception:
        logger.warning("查询 CompactOS 状态失败", exc_info=True)
        return False