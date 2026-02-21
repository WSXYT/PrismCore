"""MFT 快速文件扫描 — 通过直接读取 NTFS 主文件表实现毫秒级大文件检索。

原理：绕过 os.walk，直接通过 DeviceIoControl 读取 USN 日志，
在内存中构建文件映射表，速度比传统遍历快几个数量级。
需要管理员权限。
"""

import ctypes
import ctypes.wintypes as wintypes
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── Windows 常量 ──────────────────────────────────────────────

GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

FSCTL_ENUM_USN_DATA = 0x000900B3
FSCTL_QUERY_USN_JOURNAL = 0x000900F4

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


# ── 数据结构 ──────────────────────────────────────────────────

class USN_JOURNAL_DATA(ctypes.Structure):
    """USN 日志元数据。"""
    _fields_ = [
        ("UsnJournalID", ctypes.c_uint64),
        ("FirstUsn", ctypes.c_int64),
        ("NextUsn", ctypes.c_int64),
        ("LowestValidUsn", ctypes.c_int64),
        ("MaxUsn", ctypes.c_int64),
        ("MaximumSize", ctypes.c_uint64),
        ("AllocationDelta", ctypes.c_uint64),
    ]


class MFT_ENUM_DATA_V0(ctypes.Structure):
    """MFT 枚举请求参数。"""
    _fields_ = [
        ("StartFileReferenceNumber", ctypes.c_uint64),
        ("LowUsn", ctypes.c_int64),
        ("HighUsn", ctypes.c_int64),
    ]


class USN_RECORD_V2(ctypes.Structure):
    """USN 记录（V2 格式）。"""
    _fields_ = [
        ("RecordLength", wintypes.DWORD),
        ("MajorVersion", wintypes.WORD),
        ("MinorVersion", wintypes.WORD),
        ("FileReferenceNumber", ctypes.c_uint64),
        ("ParentFileReferenceNumber", ctypes.c_uint64),
        ("Usn", ctypes.c_int64),
        ("TimeStamp", ctypes.c_int64),
        ("Reason", wintypes.DWORD),
        ("SourceInfo", wintypes.DWORD),
        ("SecurityId", wintypes.DWORD),
        ("FileAttributes", wintypes.DWORD),
        ("FileNameLength", wintypes.WORD),
        ("FileNameOffset", wintypes.WORD),
    ]


@dataclass
class MftFileEntry:
    """MFT 扫描结果条目。"""
    path: str
    size: int
    is_directory: bool


# ── 核心扫描逻辑 ─────────────────────────────────────────────

BUF_SIZE = 65536  # 64KB 读取缓冲区
FILE_ATTRIBUTE_DIRECTORY = 0x10


def _open_volume(drive_letter: str):
    """打开卷句柄（需要管理员权限）。"""
    path = f"\\\\.\\{drive_letter}:"
    handle = kernel32.CreateFileW(
        path, GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None, OPEN_EXISTING, 0, None,
    )
    if handle == INVALID_HANDLE_VALUE:
        raise OSError(f"无法打开卷 {path}，需要管理员权限")
    return handle


def _query_usn_journal(handle) -> USN_JOURNAL_DATA:
    """查询 USN 日志信息。"""
    journal = USN_JOURNAL_DATA()
    bytes_returned = wintypes.DWORD(0)
    ok = kernel32.DeviceIoControl(
        handle, FSCTL_QUERY_USN_JOURNAL,
        None, 0,
        ctypes.byref(journal), ctypes.sizeof(journal),
        ctypes.byref(bytes_returned), None,
    )
    if not ok:
        raise OSError("查询 USN 日志失败")
    return journal


def scan_mft_large_files(
    drive_letter: str = "C",
    min_size_bytes: int = 500 * 1024 * 1024,
    max_results: int = 500,
) -> list[MftFileEntry]:
    """通过 MFT 枚举快速扫描大文件。

    参数:
        drive_letter: 盘符（不含冒号），如 "C"
        min_size_bytes: 最小文件大小阈值（字节）
        max_results: 最大返回条目数

    返回:
        MftFileEntry 列表，按大小降序排列
    """
    try:
        handle = _open_volume(drive_letter)
    except OSError:
        logger.warning("MFT 扫描失败：无法打开卷 %s", drive_letter)
        return []

    try:
        journal = _query_usn_journal(handle)
    except OSError:
        logger.warning("MFT 扫描失败：无法查询 USN 日志")
        kernel32.CloseHandle(handle)
        return []

    # 第一遍：枚举所有 MFT 记录，构建文件名映射和父目录映射
    file_map: dict[int, tuple[str, int, bool, int]] = {}
    # key=FileRef, value=(name, parent_ref, is_dir, size_placeholder)

    med = MFT_ENUM_DATA_V0()
    med.StartFileReferenceNumber = 0
    med.LowUsn = 0
    med.HighUsn = journal.NextUsn

    buf = ctypes.create_string_buffer(BUF_SIZE)
    bytes_returned = wintypes.DWORD(0)

    while True:
        ok = kernel32.DeviceIoControl(
            handle, FSCTL_ENUM_USN_DATA,
            ctypes.byref(med), ctypes.sizeof(med),
            buf, BUF_SIZE,
            ctypes.byref(bytes_returned), None,
        )
        if not ok or bytes_returned.value <= 8:
            break

        # 跳过前 8 字节（下一次枚举的起始引用号）
        offset = 8
        while offset < bytes_returned.value:
            record = ctypes.cast(
                ctypes.byref(buf, offset), ctypes.POINTER(USN_RECORD_V2),
            ).contents

            if record.RecordLength == 0:
                break

            # 提取文件名（UTF-16LE）
            name_offset = offset + record.FileNameOffset
            name_len = record.FileNameLength
            try:
                name = buf[name_offset:name_offset + name_len].decode("utf-16-le")
            except Exception:
                logger.warning("MFT 记录解码失败 (offset=%d)", offset, exc_info=True)
                offset += record.RecordLength
                continue

            is_dir = bool(record.FileAttributes & FILE_ATTRIBUTE_DIRECTORY)
            file_ref = record.FileReferenceNumber & 0x0000FFFFFFFFFFFF
            parent_ref = record.ParentFileReferenceNumber & 0x0000FFFFFFFFFFFF

            file_map[file_ref] = (name, parent_ref, is_dir, 0)
            offset += record.RecordLength

        # 更新起始引用号
        med.StartFileReferenceNumber = ctypes.c_uint64.from_buffer_copy(
            buf, 0,
        ).value

    kernel32.CloseHandle(handle)

    # 第二遍：通过 Win32 API 获取文件大小并过滤
    # 先构建路径缓存
    path_cache: dict[int, str] = {}

    def _build_path(ref: int, depth: int = 0) -> str:
        if depth > 64:
            return ""
        if ref in path_cache:
            return path_cache[ref]
        entry = file_map.get(ref)
        if not entry:
            path_cache[ref] = ""
            return ""
        name, parent, _, _ = entry
        parent_path = _build_path(parent, depth + 1)
        full = f"{parent_path}\\{name}" if parent_path else name
        path_cache[ref] = full
        return full

    # 构建所有路径
    for ref in file_map:
        _build_path(ref)

    # 使用 GetCompressedFileSizeW 获取真实大小并过滤
    results: list[MftFileEntry] = []
    high = wintypes.DWORD(0)
    root = f"{drive_letter}:\\"

    for ref, (name, parent, is_dir, _) in file_map.items():
        if is_dir:
            continue
        rel_path = path_cache.get(ref, "")
        if not rel_path:
            continue
        full_path = root + rel_path

        low = kernel32.GetCompressedFileSizeW(
            full_path, ctypes.byref(high),
        )
        if low == 0xFFFFFFFF and ctypes.get_last_error() != 0:
            continue
        size = (high.value << 32) | (low & 0xFFFFFFFF)
        high.value = 0

        if size >= min_size_bytes:
            results.append(MftFileEntry(
                path=full_path, size=size, is_directory=False,
            ))
            if len(results) >= max_results:
                break

    results.sort(key=lambda x: x.size, reverse=True)
    return results
