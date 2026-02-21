"""底层 Windows API 封装（通过 ctypes 调用）。"""

import ctypes
from ctypes import wintypes
from typing import NamedTuple


class MemoryStatus(NamedTuple):
    """系统内存状态快照。"""
    total: int
    available: int
    used: int
    percent: float
    commit_total: int
    commit_limit: int


def get_memory_status() -> MemoryStatus:
    """通过 GlobalMemoryStatusEx 查询全局内存状态。"""

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", wintypes.DWORD),
            ("dwMemoryLoad", wintypes.DWORD),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    ms = MEMORYSTATUSEX()
    ms.dwLength = ctypes.sizeof(ms)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))

    total = ms.ullTotalPhys
    avail = ms.ullAvailPhys
    used = total - avail
    pct = (used / total * 100) if total else 0.0

    return MemoryStatus(
        total=total,
        available=avail,
        used=used,
        percent=round(pct, 1),
        commit_total=ms.ullTotalPageFile - ms.ullAvailPageFile,
        commit_limit=ms.ullTotalPageFile,
    )


def get_disk_free(drive: str = "C:\\") -> int:
    """返回指定驱动器的可用字节数。"""
    free = ctypes.c_ulonglong(0)
    ctypes.windll.kernel32.GetDiskFreeSpaceExW(
        ctypes.c_wchar_p(drive), None, None, ctypes.byref(free),
    )
    return free.value


def purge_standby_list() -> bool:
    """清空内存备用列表（需要管理员权限 + SeProfileSingleProcessPrivilege）。"""
    import logging
    log = logging.getLogger(__name__)

    from src.utils.privilege import enable_privilege

    SYSTEM_MEMORY_LIST_INFO = 80
    PURGE_STANDBY = 4

    class CMD(ctypes.Structure):
        _fields_ = [("Command", ctypes.c_int)]

    priv_ok = enable_privilege("SeProfileSingleProcessPrivilege")
    log.info("提权 SeProfileSingleProcessPrivilege: %s", priv_ok)

    cmd = CMD()
    cmd.Command = PURGE_STANDBY
    ntdll = ctypes.WinDLL("ntdll.dll")
    ntdll.NtSetSystemInformation.restype = ctypes.c_ulong
    status = ntdll.NtSetSystemInformation(
        SYSTEM_MEMORY_LIST_INFO,
        ctypes.byref(cmd),
        ctypes.sizeof(cmd),
    )
    log.info("NtSetSystemInformation 返回 NTSTATUS: 0x%08X", status)
    return status == 0


def empty_working_set(pid: int) -> bool:
    """按 PID 修剪指定进程的工作集。"""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)

    # 声明参数/返回类型，防止 64 位 HANDLE 被截断
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
    psapi.EmptyWorkingSet.restype = wintypes.BOOL

    PROCESS_SET_QUOTA = 0x0100
    PROCESS_QUERY_INFORMATION = 0x0400

    handle = kernel32.OpenProcess(
        PROCESS_SET_QUOTA | PROCESS_QUERY_INFORMATION, False, pid,
    )
    if not handle:
        return False

    result = psapi.EmptyWorkingSet(handle)
    kernel32.CloseHandle(handle)
    return bool(result)


def create_restore_point(description: str = "PrismCore 优化前备份") -> bool:
    """通过 SRSetRestorePointW 创建系统还原点。"""
    BEGIN_SYSTEM_CHANGE = 100
    APPLICATION_INSTALL = 0

    class RESTOREPTINFOW(ctypes.Structure):
        _fields_ = [
            ("dwEventType", wintypes.DWORD),
            ("dwRestorePtType", wintypes.DWORD),
            ("llSequenceNumber", ctypes.c_int64),
            ("szDescription", ctypes.c_wchar * 256),
        ]

    class STATEMGRSTATUS(ctypes.Structure):
        _fields_ = [
            ("nStatus", wintypes.DWORD),
            ("llSequenceNumber", ctypes.c_int64),
        ]

    info = RESTOREPTINFOW()
    info.dwEventType = BEGIN_SYSTEM_CHANGE
    info.dwRestorePtType = APPLICATION_INSTALL
    info.llSequenceNumber = 0
    info.szDescription = description[:255]

    status = STATEMGRSTATUS()
    try:
        srclient = ctypes.WinDLL("srclient.dll", use_last_error=True)
        return bool(srclient.SRSetRestorePointW(
            ctypes.byref(info), ctypes.byref(status),
        ))
    except OSError:
        return False


def empty_recycle_bin() -> bool:
    """清空回收站。"""
    SHERB_NO_UI = 0x00000001 | 0x00000002 | 0x00000004
    result = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, SHERB_NO_UI)
    return result == 0


def query_recycle_bin_size() -> int:
    """查询回收站总大小（字节）。"""

    class SHQUERYRBINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("i64Size", ctypes.c_int64),
            ("i64NumItems", ctypes.c_int64),
        ]

    info = SHQUERYRBINFO()
    info.cbSize = ctypes.sizeof(info)
    result = ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
    return info.i64Size if result == 0 else 0


def get_foreground_window_pid() -> int:
    """获取前台窗口所属进程 PID。"""
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    hwnd = user32.GetForegroundWindow()
    pid = wintypes.DWORD(0)
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def is_foreground_fullscreen() -> bool:
    """检测前台窗口是否为全屏（游戏/视频等）。"""
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long), ("top", ctypes.c_long),
            ("right", ctypes.c_long), ("bottom", ctypes.c_long),
        ]

    rect = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    # 获取窗口所在显示器的分辨率
    screen_w = user32.GetSystemMetrics(0)  # SM_CXSCREEN
    screen_h = user32.GetSystemMetrics(1)  # SM_CYSCREEN
    # 窗口覆盖整个屏幕即视为全屏
    return (
        rect.left <= 0 and rect.top <= 0
        and rect.right >= screen_w and rect.bottom >= screen_h
    )


def nt_create_paging_file(path: str, min_size: int, max_size: int) -> bool:
    """通过 NtCreatePagingFile 动态创建/扩展分页文件（无需重启）。

    参数:
        path: 分页文件路径，如 "\\??\\D:\\pagefile.sys"
        min_size: 最小大小（字节）
        max_size: 最大大小（字节）
    """
    import logging
    log = logging.getLogger(__name__)

    ntdll = ctypes.WinDLL("ntdll.dll")

    class UNICODE_STRING(ctypes.Structure):
        _fields_ = [
            ("Length", ctypes.c_ushort),
            ("MaximumLength", ctypes.c_ushort),
            ("Buffer", ctypes.c_wchar_p),
        ]

    class LARGE_INTEGER(ctypes.Structure):
        _fields_ = [("QuadPart", ctypes.c_longlong)]

    us = UNICODE_STRING()
    us.Buffer = path
    us.Length = len(path) * 2
    us.MaximumLength = us.Length + 2

    min_li = LARGE_INTEGER(min_size)
    max_li = LARGE_INTEGER(max_size)

    ntdll.NtCreatePagingFile.restype = ctypes.c_ulong
    status = ntdll.NtCreatePagingFile(
        ctypes.byref(us), ctypes.byref(min_li), ctypes.byref(max_li), 0,
    )
    log.info("NtCreatePagingFile(%s) 返回 NTSTATUS: 0x%08X", path, status)
    return status == 0


def measure_responsiveness(timeout_ms: int = 5000) -> float:
    """通过 SendMessageTimeout 测量系统 UI 响应延迟（毫秒）。

    向桌面广播 WM_NULL 空消息，测量响应时间。
    延迟越高说明 UI 线程越拥堵，系统越卡顿。
    """
    import time
    user32 = ctypes.windll.user32
    HWND_BROADCAST = 0xFFFF
    WM_NULL = 0x0000
    SMTO_ABORTIFHUNG = 0x0002
    result = wintypes.DWORD(0)

    start = time.perf_counter()
    ret = user32.SendMessageTimeoutW(
        HWND_BROADCAST, WM_NULL, 0, 0,
        SMTO_ABORTIFHUNG, timeout_ms, ctypes.byref(result),
    )
    elapsed = (time.perf_counter() - start) * 1000

    if not ret:
        # 超时或挂起，返回超时值
        return float(timeout_ms)
    return round(elapsed, 2)


def get_system_page_fault_count() -> int:
    """通过性能计数器获取系统总页错误数/秒。"""
    try:
        import psutil
        counters = psutil.swap_memory()
        # sin + sout 近似反映页错误活动
        return counters.sin + counters.sout
    except Exception:
        log.warning("获取系统页错误数失败", exc_info=True)
        return 0
class CpuTopology(NamedTuple):
    """CPU 核心拓扑信息。"""
    p_cores: list[int]   # P-Core 逻辑处理器索引列表
    e_cores: list[int]   # E-Core 逻辑处理器索引列表
    is_hybrid: bool      # 是否为混合架构


def get_cpu_topology() -> CpuTopology:
    """通过 GetSystemCpuSetInformation 获取精确的 P/E 核心拓扑。

    EfficiencyClass=0 为 P-Core（性能核），>0 为 E-Core（能效核）。
    若 API 不可用则回退到启发式检测。
    """
    import logging
    log = logging.getLogger(__name__)

    # SYSTEM_CPU_SET_INFORMATION 结构（简化，只取需要的字段）
    # 完整结构大小为 32 字节（x64）
    class SYSTEM_CPU_SET_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("Size", wintypes.DWORD),
            ("Type", wintypes.DWORD),       # CpuSetInformation = 0
            ("Id", wintypes.DWORD),
            ("Group", wintypes.WORD),
            ("LogicalProcessorIndex", ctypes.c_ubyte),
            ("CoreIndex", ctypes.c_ubyte),
            ("LastLevelCacheIndex", ctypes.c_ubyte),
            ("NumaNodeIndex", ctypes.c_ubyte),
            ("EfficiencyClass", ctypes.c_ubyte),
            ("AllFlags", ctypes.c_ubyte),
            ("Reserved", wintypes.DWORD),
            ("AllocationTag", ctypes.c_uint64),
        ]

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        func = kernel32.GetSystemCpuSetInformation
        func.restype = wintypes.BOOL
    except (OSError, AttributeError):
        log.debug("GetSystemCpuSetInformation 不可用，回退启发式检测")
        return _fallback_cpu_topology()

    # 先查询所需缓冲区大小
    length = wintypes.DWORD(0)
    func(None, 0, ctypes.byref(length), None, 0)
    if length.value == 0:
        return _fallback_cpu_topology()

    buf = (ctypes.c_ubyte * length.value)()
    if not func(buf, length.value, ctypes.byref(length), None, 0):
        log.debug("GetSystemCpuSetInformation 调用失败")
        return _fallback_cpu_topology()

    # 解析结果
    p_cores, e_cores = [], []
    offset = 0
    while offset < length.value:
        info = SYSTEM_CPU_SET_INFORMATION.from_buffer_copy(
            bytes(buf[offset:offset + ctypes.sizeof(SYSTEM_CPU_SET_INFORMATION)])
        )
        if info.Size == 0:
            break
        idx = info.LogicalProcessorIndex
        if info.EfficiencyClass == 0:
            p_cores.append(idx)
        else:
            e_cores.append(idx)
        offset += info.Size

    is_hybrid = bool(p_cores and e_cores)
    log.info("CPU 拓扑: P-Core=%s, E-Core=%s, hybrid=%s",
             p_cores, e_cores, is_hybrid)
    return CpuTopology(p_cores=p_cores, e_cores=e_cores, is_hybrid=is_hybrid)


def _fallback_cpu_topology() -> CpuTopology:
    """启发式回退：无法使用 GetSystemCpuSetInformation 时的降级方案。"""
    import psutil
    logical = psutil.cpu_count(logical=True) or 1
    physical = psutil.cpu_count(logical=False) or 1
    if logical > physical * 1.5:
        # 可能是混合架构，但无法确定具体分配，不做 E-Core 绑定
        return CpuTopology(
            p_cores=list(range(physical)),
            e_cores=list(range(physical, logical)),
            is_hybrid=True,
        )
    return CpuTopology(p_cores=list(range(logical)), e_cores=[], is_hybrid=False)


def enum_kernel_modules() -> list[tuple[int, str]]:
    """枚举已加载的内核模块，返回 [(基地址, 模块名), ...] 按基地址排序。

    用于将 DPC/ISR 回调地址映射到具体驱动程序。
    """
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    # 声明参数类型，避免 64 位内核地址溢出
    psapi.GetDeviceDriverBaseNameW.argtypes = [
        ctypes.c_void_p, ctypes.c_wchar_p, wintypes.DWORD,
    ]
    psapi.GetDeviceDriverBaseNameW.restype = wintypes.DWORD
    # 先获取所需数组大小
    needed = wintypes.DWORD(0)
    psapi.EnumDeviceDrivers(None, 0, ctypes.byref(needed))
    count = needed.value // ctypes.sizeof(ctypes.c_void_p)
    if count == 0:
        return []

    arr = (ctypes.c_void_p * count)()
    psapi.EnumDeviceDrivers(arr, needed, ctypes.byref(needed))

    result = []
    name_buf = ctypes.create_unicode_buffer(260)
    for base in arr:
        if not base:
            continue
        ret = psapi.GetDeviceDriverBaseNameW(base, name_buf, 260)
        name = name_buf.value if ret else ""
        result.append((base, name.lower()))

    result.sort(key=lambda x: x[0])
    return result
