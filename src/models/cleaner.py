"""智能清理引擎 — Electron 缓存猎手、大文件扫描、临时文件清理。"""

import os
import shutil
import logging
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from src.utils.constants import (
    ELECTRON_CACHE_DIRS,
    TEMP_EXTENSIONS,
    LARGE_FILE_THRESHOLD_BYTES,
)
from src.utils.winapi import empty_recycle_bin

logger = logging.getLogger(__name__)


@dataclass
class CleanItem:
    """单个可清理项。"""
    path: str
    size: int
    category: str  # "electron" | "temp" | "large_file"
    description: str = ""
    selected: bool = True


@dataclass
class ScanResult:
    """扫描结果汇总。"""
    items: list[CleanItem] = field(default_factory=list)

    @property
    def total_size(self) -> int:
        return sum(i.size for i in self.items if i.selected)

    @property
    def count(self) -> int:
        return sum(1 for i in self.items if i.selected)


# ── Electron 缓存猎手 ─────────────────────────────────────────────


def _has_electron_signature(directory: str) -> bool:
    """检查目录是否具有 Electron 应用的特征结构。"""
    markers = {"Cache", "GPUCache"}
    try:
        children = {e.name for e in os.scandir(directory) if e.is_dir()}
    except OSError:
        return False

    if not markers.issubset(children):
        return False

    # 在前两级目录中查找 .asar 文件
    for root, dirs, files in os.walk(directory):
        if any(f.endswith(".asar") for f in files):
            return True
        depth = root.replace(directory, "").count(os.sep)
        if depth >= 2:
            break
    return False


def _dir_size(path: str) -> int:
    """迭代计算目录总大小（栈模拟，避免栈溢出）。"""
    total = 0
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            for entry in os.scandir(current):
                if entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
                elif entry.is_dir(follow_symlinks=False):
                    stack.append(entry.path)
        except OSError:
            pass
    return total


def scan_electron_caches() -> list[CleanItem]:
    """通过签名匹配扫描 AppData 中的 Electron 应用缓存。"""
    items: list[CleanItem] = []
    roots = []
    for var in ("APPDATA", "LOCALAPPDATA"):
        val = os.environ.get(var)
        if val and os.path.isdir(val):
            roots.append(val)

    for root in roots:
        try:
            entries = list(os.scandir(root))
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir():
                continue
            # 检查顶层及下一级子目录
            paths_to_check = [entry.path]
            try:
                paths_to_check.extend(
                    sub.path for sub in os.scandir(entry.path)
                    if sub.is_dir()
                )
            except OSError:
                pass

            for check_path in paths_to_check:
                if not _has_electron_signature(check_path):
                    continue
                for cache_name in ELECTRON_CACHE_DIRS:
                    cache_path = os.path.join(check_path, cache_name)
                    if os.path.isdir(cache_path):
                        size = _dir_size(cache_path)
                        if size > 0:
                            items.append(CleanItem(
                                path=cache_path,
                                size=size,
                                category="electron",
                                description=f"Electron: {Path(check_path).name}",
                            ))
    return items


# ── 临时文件扫描 ───────────────────────────────────────────────────


def scan_temp_files() -> list[CleanItem]:
    """扫描系统和用户临时目录。"""
    items: list[CleanItem] = []
    temp_dirs = set()
    for var in ("TEMP", "TMP"):
        val = os.environ.get(var)
        if val and os.path.isdir(val):
            temp_dirs.add(val)
    win_temp = os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "Temp")
    if os.path.isdir(win_temp):
        temp_dirs.add(win_temp)

    for temp_dir in temp_dirs:
        try:
            for entry in os.scandir(temp_dir):
                try:
                    if entry.is_file(follow_symlinks=False):
                        size = entry.stat(follow_symlinks=False).st_size
                        items.append(CleanItem(
                            path=entry.path,
                            size=size,
                            category="temp",
                            description=f"临时文件: {entry.name}",
                        ))
                    elif entry.is_dir(follow_symlinks=False):
                        size = _dir_size(entry.path)
                        items.append(CleanItem(
                            path=entry.path,
                            size=size,
                            category="temp",
                            description=f"临时目录: {entry.name}",
                        ))
                except OSError:
                    continue
        except OSError:
            continue
    return items


# ── 大文件扫描 ─────────────────────────────────────────────────────


def _scan_large_files_mft(
    drive_letter: str,
    threshold: int,
    max_results: int,
) -> list[CleanItem] | None:
    """尝试通过 MFT 快速扫描大文件（需要管理员权限）。失败返回 None。"""
    try:
        from src.models.mft_scanner import scan_mft_large_files
        entries = scan_mft_large_files(
            drive_letter=drive_letter,
            min_size_bytes=threshold,
            max_results=max_results,
        )
        if not entries:
            return None
        items = []
        for e in entries:
            ext = os.path.splitext(e.path)[1].lower()
            items.append(CleanItem(
                path=e.path,
                size=e.size,
                category="large_file",
                description=e.path,
                selected=ext in TEMP_EXTENSIONS,
            ))
        return items
    except Exception:
        logger.debug("MFT 扫描不可用，回退到 os.walk", exc_info=True)
        return None


def _scan_large_files_walk(
    root: str,
    threshold: int,
    max_results: int,
) -> list[CleanItem]:
    """通过 os.walk 遍历扫描大文件（兜底方案）。"""
    items: list[CleanItem] = []
    skip_prefixes = (
        os.path.join(root, "Windows"),
        os.path.join(root, "Program Files"),
        os.path.join(root, "Program Files (x86)"),
        os.path.join(root, "$"),
    )

    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        if any(dirpath.startswith(p) for p in skip_prefixes):
            dirnames.clear()
            continue
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith("$") and not d.startswith(".")
        ]
        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            try:
                size = os.path.getsize(fpath)
            except OSError:
                continue
            if size >= threshold:
                ext = os.path.splitext(fname)[1].lower()
                items.append(CleanItem(
                    path=fpath,
                    size=size,
                    category="large_file",
                    description=fpath,
                    selected=ext in TEMP_EXTENSIONS,
                ))
                if len(items) >= max_results:
                    return items
    return items


def scan_large_files(
    root: str = "C:\\",
    threshold: int = LARGE_FILE_THRESHOLD_BYTES,
    max_results: int = 200,
) -> list[CleanItem]:
    """扫描大文件。优先使用 MFT 快速扫描，失败时回退到 os.walk。"""
    drive_letter = root.rstrip("\\").rstrip(":")
    if len(drive_letter) == 1 and drive_letter.isalpha():
        result = _scan_large_files_mft(drive_letter, threshold, max_results)
        if result is not None:
            return result
    return _scan_large_files_walk(root, threshold, max_results)


# ── 清理执行 ───────────────────────────────────────────────────────


def _is_path_locked(path: str) -> bool:
    """检查是否有运行中的进程锁定了该路径。"""
    path_lower = os.path.normpath(path).lower()
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            for f in proc.open_files():
                if os.path.normpath(f.path).lower().startswith(path_lower):
                    return True
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    return False


def _safe_remove_file(path: str) -> int:
    """安全删除单个文件，返回释放的字节数。失败返回 0。"""
    try:
        size = os.path.getsize(path)
        os.remove(path)
        return size
    except (PermissionError, OSError):
        return 0


def _safe_remove_tree(path: str) -> int:
    """安全删除目录树，跳过被占用的文件，返回实际释放的字节数。"""
    freed = 0
    for root, dirs, files in os.walk(path, topdown=False):
        for name in files:
            freed += _safe_remove_file(os.path.join(root, name))
        for name in dirs:
            try:
                os.rmdir(os.path.join(root, name))
            except OSError:
                pass
    try:
        os.rmdir(path)
    except OSError:
        pass
    return freed


def execute_clean(items: list[CleanItem]) -> tuple[int, int]:
    """删除已选中的项目。返回 (已清理字节数, 失败数量)。

    对被占用或无权限的文件静默跳过，不中断整体清理流程。
    """
    cleaned = 0
    failed = 0
    for item in items:
        if not item.selected:
            continue
        try:
            if item.category == "recycle_bin":
                if empty_recycle_bin():
                    cleaned += item.size
                else:
                    failed += 1
            elif os.path.isdir(item.path):
                freed = _safe_remove_tree(item.path)
                cleaned += freed
                if freed == 0:
                    failed += 1
            elif os.path.isfile(item.path):
                freed = _safe_remove_file(item.path)
                if freed > 0:
                    cleaned += freed
                else:
                    failed += 1
            else:
                # 文件已不存在，视为已清理
                cleaned += item.size
        except Exception:
            logger.warning("清理失败: %s", item.path, exc_info=True)
            failed += 1
    return cleaned, failed
