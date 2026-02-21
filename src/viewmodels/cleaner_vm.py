"""清理器视图模型 — 后台扫描和清理垃圾文件+系统组件。"""

from PySide6.QtCore import QObject, QThread, Signal

from src.models.cleaner import (
    CleanItem, ScanResult,
    scan_electron_caches, scan_temp_files,
    scan_large_files, execute_clean,
)
from src.models.system_cleaner import (
    scan_update_cache_size, scan_old_drivers_info,
    scan_orphan_registry_info, query_compact_os_status,
    cleanup_winsxs, cleanup_windows_update,
    list_old_drivers, delete_driver,
    scan_orphan_registry, backup_and_delete_key,
    enable_compact_os,
)
from src.models.system_info import format_bytes
from src.utils.winapi import query_recycle_bin_size, create_restore_point, empty_recycle_bin

# 系统级清理类别（需要特殊处理，不走 execute_clean）
SYSTEM_CATEGORIES = {"winsxs", "old_drivers", "orphan_registry", "win_update", "compact_os"}


class _ScanWorker(QThread):
    """后台扫描线程（垃圾文件+系统组件统一扫描）。"""

    progress = Signal(str)
    finished = Signal(object)

    def __init__(self, deep: bool = False, parent=None):
        super().__init__(parent)
        self._deep = deep

    def run(self):
        result = ScanResult()

        # ── 垃圾文件扫描 ──
        self.progress.emit("正在扫描临时文件...")
        result.items.extend(scan_temp_files())

        self.progress.emit("正在搜索应用缓存...")
        result.items.extend(scan_electron_caches())

        self.progress.emit("正在检查回收站...")
        rb_size = query_recycle_bin_size()
        if rb_size > 0:
            result.items.append(CleanItem(
                path="$RECYCLE.BIN", size=rb_size,
                category="recycle_bin", description="回收站",
                selected=True,
            ))

        if self._deep:
            self.progress.emit("正在扫描大文件 (C:\\)...")
            result.items.extend(scan_large_files("C:\\"))

        # ── 系统组件扫描 ──
        self.progress.emit("正在分析 Windows Update 缓存...")
        upd_size = scan_update_cache_size()
        if upd_size > 0:
            result.items.append(CleanItem(
                path="$WIN_UPDATE", size=upd_size,
                category="win_update",
                description="Windows Update 下载缓存",
                selected=False,
            ))

        self.progress.emit("正在扫描旧驱动...")
        old_drv = scan_old_drivers_info()
        if old_drv:
            result.items.append(CleanItem(
                path="$OLD_DRIVERS", size=len(old_drv),
                category="old_drivers",
                description=f"旧版驱动包 ({len(old_drv)} 个)",
                selected=False,
            ))

        self.progress.emit("正在扫描孤立注册表项...")
        orphans = scan_orphan_registry_info()
        if orphans:
            result.items.append(CleanItem(
                path="$ORPHAN_REGISTRY", size=len(orphans),
                category="orphan_registry",
                description=f"孤立注册表项 ({len(orphans)} 个)",
                selected=False,
            ))

        if query_compact_os_status():
            result.items.append(CleanItem(
                path="$COMPACT_OS", size=0,
                category="compact_os",
                description="CompactOS 压缩（可节省约 2GB）",
                selected=False,
            ))

        result.items.sort(key=lambda x: x.size, reverse=True)
        self.finished.emit(result)


class _CleanWorker(QThread):
    """后台清理线程（文件级+系统级统一处理）。"""

    progress = Signal(str)
    finished = Signal(str)

    def __init__(self, items: list[CleanItem], parent=None):
        super().__init__(parent)
        self._items = items

    def run(self):
        file_items = [i for i in self._items if i.category not in SYSTEM_CATEGORIES]
        sys_items = [i for i in self._items if i.category in SYSTEM_CATEGORIES]

        cleaned, failed = 0, 0

        if file_items:
            c, f = execute_clean(file_items)
            cleaned += c
            failed += f

        if sys_items:
            self.progress.emit("正在创建系统还原点...")
            create_restore_point("PrismCore 系统清理前备份")

            for item in sys_items:
                cat = item.category
                if cat == "win_update":
                    self.progress.emit("正在清理更新缓存...")
                    r = cleanup_windows_update()
                    cleaned += r.freed_bytes
                elif cat == "old_drivers":
                    self.progress.emit("正在清理旧驱动...")
                    old = list_old_drivers()
                    removed = sum(1 for d in old if delete_driver(d["inf"]))
                    if not removed:
                        failed += 1
                elif cat == "orphan_registry":
                    self.progress.emit("正在清理注册表...")
                    orphans = scan_orphan_registry()
                    c = sum(1 for o in orphans if backup_and_delete_key(o["key"]))
                    if not c:
                        failed += 1
                elif cat == "winsxs":
                    self.progress.emit("正在清理组件存储...")
                    r = cleanup_winsxs()
                    if not r.success:
                        failed += 1
                elif cat == "compact_os":
                    self.progress.emit("正在压缩系统文件...")
                    r = enable_compact_os()
                    if not r.success:
                        failed += 1

        # 直接格式化为字符串避免 int 溢出
        msg = f"已清理 {format_bytes(cleaned)}"
        if failed:
            msg += f"（{failed} 项失败）"
        self.finished.emit(msg)


class CleanerViewModel(QObject):
    """清理器视图模型：扫描 + 清理。"""

    scan_progress = Signal(str)
    scan_done = Signal(object)
    clean_progress = Signal(str)
    clean_done = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scan_worker: _ScanWorker | None = None
        self._clean_worker: _CleanWorker | None = None

    def start_scan(self, deep: bool = False):
        """启动后台扫描。"""
        if self._scan_worker and self._scan_worker.isRunning():
            return
        self._scan_worker = _ScanWorker(deep)
        self._scan_worker.progress.connect(self.scan_progress.emit)
        self._scan_worker.finished.connect(self.scan_done.emit)
        self._scan_worker.start()

    def start_clean(self, items: list[CleanItem]):
        """启动后台清理。"""
        if self._clean_worker and self._clean_worker.isRunning():
            return
        self._clean_worker = _CleanWorker(items)
        self._clean_worker.progress.connect(self.clean_progress.emit)
        self._clean_worker.finished.connect(self.clean_done.emit)
        self._clean_worker.start()
