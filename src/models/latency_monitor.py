"""DPC/ISR 延迟监控 — ETW 驱动级归因 + PDH 总体百分比。

混合方案：
- ETW（事件追踪）：捕获每个 DPC/ISR 事件的回调地址，映射到具体驱动，
  实现精确到单个驱动的延迟归因。
- PDH（性能计数器）：提供可靠的总体 DPC/ISR 时间百分比。
- 两者结合：PDH 判定是否超阈值，ETW 定位具体问题驱动。
"""

import bisect
import ctypes
import ctypes.wintypes as wintypes
import logging
import threading
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── PDH API 常量 ──────────────────────────────────────────────

PDH_FMT_DOUBLE = 0x00000200
ERROR_SUCCESS = 0

try:
    pdh = ctypes.WinDLL("pdh", use_last_error=True)
except OSError:
    pdh = None

# ── ETW API 常量 ──────────────────────────────────────────────

EVENT_TRACE_REAL_TIME_MODE = 0x00000100
EVENT_TRACE_SYSTEM_LOGGER_MODE = 0x02000000
EVENT_TRACE_FLAG_DPC = 0x00000020
EVENT_TRACE_FLAG_INTERRUPT = 0x00000040
WNODE_FLAG_TRACED_GUID = 0x00020000
PROCESS_TRACE_MODE_REAL_TIME = 0x00000100
PROCESS_TRACE_MODE_EVENT_RECORD = 0x10000000
EVENT_TRACE_CONTROL_STOP = 1
INVALID_PROCESSTRACE_HANDLE = 0xFFFFFFFFFFFFFFFF

# DPC/ISR 事件 Opcode
_OPCODE_DPC = 66
_OPCODE_TIMER_DPC = 67
_OPCODE_ISR = 50


@dataclass
class DriverLatencyInfo:
    """单个驱动的 DPC/ISR 统计。"""
    name: str
    dpc_count: int = 0
    isr_count: int = 0


@dataclass
class LatencySnapshot:
    """延迟检测快照。"""
    dpc_time_percent: float = 0.0
    isr_time_percent: float = 0.0
    dpc_queue_length: float = 0.0
    has_issue: bool = False
    warnings: list[str] = field(default_factory=list)
    # ETW 驱动级归因（按 DPC+ISR 总数降序排列的 top 驱动）
    top_drivers: list[DriverLatencyInfo] = field(default_factory=list)
    # ETW 会话是否可用
    etw_available: bool = True


class LatencyMonitor:
    """DPC/ISR 延迟监控器（PDH 总体百分比 + ETW 驱动级归因）。"""

    _COUNTERS = {
        "dpc_time": r"\Processor(_Total)\% DPC Time",
        "isr_time": r"\Processor(_Total)\% Interrupt Time",
        "dpc_rate": r"\Processor(_Total)\DPCs Queued/sec",
    }
    DPC_WARN_THRESHOLD = 3.0
    ISR_WARN_THRESHOLD = 2.0

    def __init__(self):
        self._query = None
        self._counter_handles: dict[str, ctypes.c_void_p] = {}
        self._pdh_ok = False
        self._etw: _EtwDpcSession | None = None
        self._etw_available = False

    @property
    def etw_available(self) -> bool:
        """ETW 驱动级归因是否可用。"""
        return self._etw_available

    def open(self) -> bool:
        """初始化 PDH + ETW。"""
        self._pdh_ok = self._open_pdh()
        # ETW 驱动级归因（需要管理员权限，失败不影响 PDH）
        self._etw = _EtwDpcSession()
        if self._etw.start():
            self._etw_available = True
        else:
            logger.info("ETW DPC/ISR 会话启动失败，仅使用 PDH")
            self._etw = None
            self._etw_available = False
        return self._pdh_ok

    def close(self):
        """关闭 PDH + ETW。"""
        if self._query and pdh:
            pdh.PdhCloseQuery(self._query)
        self._query = None
        self._counter_handles.clear()
        self._pdh_ok = False
        if self._etw:
            self._etw.stop()
            self._etw = None

    def sample(self) -> LatencySnapshot:
        """采集一次延迟数据。"""
        snap = LatencySnapshot()
        snap.etw_available = self._etw_available
        # PDH 总体百分比
        if self._pdh_ok and pdh:
            self._sample_pdh(snap)
        # ETW 驱动级归因
        if self._etw:
            snap.top_drivers = self._etw.flush_top(5)
        # 生成警告
        self._evaluate(snap)
        return snap

    def __del__(self):
        self.close()

    # ── PDH 内部方法 ──

    def _open_pdh(self) -> bool:
        if pdh is None:
            return False
        query = ctypes.c_void_p()
        if pdh.PdhOpenQueryW(None, 0, ctypes.byref(query)) != ERROR_SUCCESS:
            return False
        self._query = query
        for key, path in self._COUNTERS.items():
            counter = ctypes.c_void_p()
            if pdh.PdhAddCounterW(
                self._query, path, 0, ctypes.byref(counter),
            ) == ERROR_SUCCESS:
                self._counter_handles[key] = counter
        if not self._counter_handles:
            self.close()
            return False
        pdh.PdhCollectQueryData(self._query)
        return True

    def _sample_pdh(self, snap: LatencySnapshot):
        if pdh.PdhCollectQueryData(self._query) != ERROR_SUCCESS:
            return
        for key, handle in self._counter_handles.items():
            fmt_value = _PDH_FMT_COUNTERVALUE()
            if pdh.PdhGetFormattedCounterValue(
                handle, PDH_FMT_DOUBLE, None, ctypes.byref(fmt_value),
            ) == ERROR_SUCCESS:
                if key == "dpc_time":
                    snap.dpc_time_percent = round(fmt_value.doubleValue, 2)
                elif key == "isr_time":
                    snap.isr_time_percent = round(fmt_value.doubleValue, 2)
                elif key == "dpc_rate":
                    snap.dpc_queue_length = round(fmt_value.doubleValue, 1)

    def _evaluate(self, snap: LatencySnapshot):
        """根据 PDH 阈值 + ETW 归因生成警告。"""
        if snap.dpc_time_percent > self.DPC_WARN_THRESHOLD:
            snap.has_issue = True
            drv = self._format_top_drivers(snap.top_drivers, "dpc")
            if drv:
                snap.warnings.append(
                    f"DPC 延迟偏高 ({snap.dpc_time_percent:.1f}%)，"
                    f"主要来自: {drv}"
                )
            else:
                snap.warnings.append(
                    f"DPC 延迟偏高 ({snap.dpc_time_percent:.1f}%)，"
                    "可能有驱动程序导致卡顿"
                )
        if snap.isr_time_percent > self.ISR_WARN_THRESHOLD:
            snap.has_issue = True
            drv = self._format_top_drivers(snap.top_drivers, "isr")
            if drv:
                snap.warnings.append(
                    f"ISR 延迟偏高 ({snap.isr_time_percent:.1f}%)，"
                    f"主要来自: {drv}"
                )
            else:
                snap.warnings.append(
                    f"ISR 延迟偏高 ({snap.isr_time_percent:.1f}%)，"
                    "建议检查硬件驱动"
                )

    @staticmethod
    def _format_top_drivers(
        drivers: list[DriverLatencyInfo], kind: str,
    ) -> str:
        """格式化 top 驱动列表为可读字符串。"""
        filtered = []
        for d in drivers:
            count = d.dpc_count if kind == "dpc" else d.isr_count
            if count > 0:
                advice = _KNOWN_DPC_DRIVERS.get(d.name.replace(".sys", ""), "")
                label = advice if advice else d.name
                filtered.append(label)
        return "、".join(filtered[:3])


# ── PDH 辅助结构 ─────────────────────────────────────────────

class _PDH_FMT_COUNTERVALUE(ctypes.Structure):
    """PDH 格式化计数器值。"""
    _fields_ = [
        ("CStatus", wintypes.DWORD),
        ("doubleValue", ctypes.c_double),
    ]


# ── 驱动级 DPC 延迟诊断 ──────────────────────────────────────

# 已知高 DPC 延迟驱动模式 → 建议
_KNOWN_DPC_DRIVERS: dict[str, str] = {
    "nvlddmkm": "NVIDIA 显卡驱动（建议更新或关闭后台录制）",
    "atikmdag": "AMD 显卡驱动（建议更新驱动）",
    "igdkmd": "Intel 核显驱动（建议更新驱动）",
    "rtwlane": "Realtek 无线网卡驱动（建议更新或禁用节能）",
    "rt640x64": "Realtek 有线网卡驱动（建议更新驱动）",
    "rtkvhd64": "Realtek 音频驱动（建议更新驱动）",
    "hdaudbus": "HD Audio 总线驱动（建议检查音频驱动）",
    "ndis": "网络驱动接口（建议检查网卡驱动）",
    "tcpip": "TCP/IP 协议栈（建议检查网络负载）",
    "storport": "存储端口驱动（建议检查磁盘健康）",
    "stornvme": "NVMe 存储驱动（建议更新固件）",
    "usbxhci": "USB 3.0 控制器（建议检查 USB 设备）",
    "bthhfenum": "蓝牙驱动（建议更新蓝牙驱动）",
}


def diagnose_dpc_drivers() -> str:
    """兼容旧接口：返回已知高延迟驱动的诊断摘要。"""
    from src.utils.winapi import enum_kernel_modules
    modules = enum_kernel_modules()
    suspects = []
    for _, name in modules:
        for pattern, desc in _KNOWN_DPC_DRIVERS.items():
            if pattern in name:
                suspects.append(desc)
                break
    seen = set()
    unique = [s for s in suspects if not (s in seen or seen.add(s))]
    return "、".join(unique[:3])


# ── ETW ctypes 结构定义 ──────────────────────────────────────


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


# SystemTraceControlGuid {9e814aad-3204-11d2-9a82-006008a86939}
_KERNEL_TRACE_GUID = _GUID(
    0x9E814AAD, 0x3204, 0x11D2,
    (ctypes.c_ubyte * 8)(0x9A, 0x82, 0x00, 0x60, 0x08, 0xA8, 0x69, 0x39),
)


class _WNODE_HEADER(ctypes.Structure):
    _fields_ = [
        ("BufferSize", wintypes.ULONG),
        ("ProviderId", wintypes.ULONG),
        ("HistoricalContext", ctypes.c_uint64),
        ("TimeStamp", ctypes.c_int64),
        ("Guid", _GUID),
        ("ClientContext", wintypes.ULONG),
        ("Flags", wintypes.ULONG),
    ]


class _EVENT_TRACE_PROPERTIES(ctypes.Structure):
    """变长结构，末尾追加会话名缓冲区。"""
    _fields_ = [
        ("Wnode", _WNODE_HEADER),
        ("BufferSize", wintypes.ULONG),
        ("MinimumBuffers", wintypes.ULONG),
        ("MaximumBuffers", wintypes.ULONG),
        ("MaximumFileSize", wintypes.ULONG),
        ("LogFileMode", wintypes.ULONG),
        ("FlushTimer", wintypes.ULONG),
        ("EnableFlags", wintypes.ULONG),
        ("AgeLimit", ctypes.c_long),
        ("NumberOfBuffers", wintypes.ULONG),
        ("FreeBuffers", wintypes.ULONG),
        ("EventsLost", wintypes.ULONG),
        ("BuffersWritten", wintypes.ULONG),
        ("LogBuffersLost", wintypes.ULONG),
        ("RealTimeBuffersLost", wintypes.ULONG),
        ("LoggerThreadId", ctypes.c_void_p),
        ("LogFileNameOffset", wintypes.ULONG),
        ("LoggerNameOffset", wintypes.ULONG),
    ]


class _EVENT_DESCRIPTOR(ctypes.Structure):
    _fields_ = [
        ("Id", wintypes.USHORT),
        ("Version", ctypes.c_ubyte),
        ("Channel", ctypes.c_ubyte),
        ("Level", ctypes.c_ubyte),
        ("Opcode", ctypes.c_ubyte),
        ("Task", wintypes.USHORT),
        ("Keyword", ctypes.c_uint64),
    ]


class _EVENT_HEADER(ctypes.Structure):
    _fields_ = [
        ("Size", wintypes.USHORT),
        ("HeaderType", wintypes.USHORT),
        ("Flags", wintypes.USHORT),
        ("EventProperty", wintypes.USHORT),
        ("ThreadId", wintypes.ULONG),
        ("ProcessId", wintypes.ULONG),
        ("TimeStamp", ctypes.c_int64),
        ("ProviderId", _GUID),
        ("EventDescriptor", _EVENT_DESCRIPTOR),
        ("ProcessorTime", ctypes.c_uint64),
        ("ActivityId", _GUID),
    ]


class _ETW_BUFFER_CONTEXT(ctypes.Structure):
    _fields_ = [
        ("ProcessorNumber", ctypes.c_ubyte),
        ("Alignment", ctypes.c_ubyte),
        ("LoggerId", wintypes.USHORT),
    ]


class _EVENT_RECORD(ctypes.Structure):
    _fields_ = [
        ("EventHeader", _EVENT_HEADER),
        ("BufferContext", _ETW_BUFFER_CONTEXT),
        ("ExtendedDataCount", wintypes.USHORT),
        ("UserDataLength", wintypes.USHORT),
        ("ExtendedData", ctypes.c_void_p),
        ("UserData", ctypes.c_void_p),
        ("UserContext", ctypes.c_void_p),
    ]


# 回调函数类型
_EVENT_RECORD_CALLBACK = ctypes.WINFUNCTYPE(None, ctypes.POINTER(_EVENT_RECORD))


class _EVENT_TRACE_LOGFILEW(ctypes.Structure):
    _fields_ = [
        ("LogFileName", ctypes.c_wchar_p),
        ("LoggerName", ctypes.c_wchar_p),
        ("CurrentTime", ctypes.c_int64),
        ("BuffersRead", wintypes.ULONG),
        ("LogFileMode_union", wintypes.ULONG),
        ("CurrentEvent_Padding", ctypes.c_ubyte * 176),  # EVENT_TRACE 结构占位
        ("LogfileHeader_Padding", ctypes.c_ubyte * 272),  # TRACE_LOGFILE_HEADER
        ("BufferCallback", ctypes.c_void_p),
        ("BufferSize", wintypes.ULONG),
        ("Filled", wintypes.ULONG),
        ("EventsLost", wintypes.ULONG),
        ("EventRecordCallback", _EVENT_RECORD_CALLBACK),
        ("IsKernelTrace", wintypes.ULONG),
        ("Context", ctypes.c_void_p),
    ]


# ── 驱动地址映射器 ───────────────────────────────────────────


class _DriverMapper:
    """将内核回调地址映射到驱动模块名。

    通过 EnumDeviceDrivers 获取所有已加载内核模块的基地址和名称，
    用二分查找将 DPC/ISR 回调地址归属到具体驱动。
    """

    def __init__(self):
        self._bases: list[int] = []
        self._names: list[str] = []
        self._refresh()

    def _refresh(self):
        from src.utils.winapi import enum_kernel_modules
        modules = enum_kernel_modules()
        self._bases = [b for b, _ in modules]
        self._names = [n for _, n in modules]

    def lookup(self, addr: int) -> str:
        """根据地址查找所属驱动名，未找到返回空字符串。"""
        if not self._bases:
            return ""
        idx = bisect.bisect_right(self._bases, addr) - 1
        if idx < 0:
            return ""
        return self._names[idx]


# ── ETW DPC/ISR 会话 ─────────────────────────────────────────

_SESSION_NAME = "PrismCore_DpcIsr"

try:
    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
except OSError:
    _advapi32 = None

# 声明 ETW 函数签名，防止 64 位指针截断
if _advapi32 is not None:
    _advapi32.StartTraceW.argtypes = [
        ctypes.POINTER(ctypes.c_uint64), ctypes.c_wchar_p, ctypes.c_void_p,
    ]
    _advapi32.StartTraceW.restype = wintypes.ULONG
    _advapi32.ControlTraceW.argtypes = [
        ctypes.c_uint64, ctypes.c_wchar_p, ctypes.c_void_p, wintypes.ULONG,
    ]
    _advapi32.ControlTraceW.restype = wintypes.ULONG
    _advapi32.OpenTraceW.argtypes = [ctypes.c_void_p]
    _advapi32.OpenTraceW.restype = ctypes.c_uint64
    _advapi32.ProcessTrace.argtypes = [
        ctypes.POINTER(ctypes.c_uint64), wintypes.ULONG,
        ctypes.c_void_p, ctypes.c_void_p,
    ]
    _advapi32.ProcessTrace.restype = wintypes.ULONG
    _advapi32.CloseTrace.argtypes = [ctypes.c_uint64]
    _advapi32.CloseTrace.restype = wintypes.ULONG


class _EtwDpcSession:
    """ETW 实时会话：捕获 DPC/ISR 事件并归因到驱动。

    在后台线程中运行 ProcessTrace，通过回调统计每个驱动的
    DPC/ISR 事件数量。调用 flush_top() 获取并重置统计。
    """

    def __init__(self):
        self._session_handle = ctypes.c_uint64(0)
        self._trace_handle = ctypes.c_uint64(INVALID_PROCESSTRACE_HANDLE)
        self._thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()
        # 驱动名 → [dpc_count, isr_count]
        self._stats: dict[str, list[int]] = {}
        self._mapper = _DriverMapper()
        self._props_buf: ctypes.Array | None = None
        self._session_name: str = _SESSION_NAME

    def start(self) -> bool:
        """启动 ETW 内核追踪会话。需要管理员权限。"""
        if _advapi32 is None:
            return False
        try:
            return self._start_session()
        except Exception:
            logger.debug("ETW 会话启动异常", exc_info=True)
            return False

    def _build_props(self, session_name: str, use_system_logger: bool):
        """构造 EVENT_TRACE_PROPERTIES 变长缓冲区。"""
        props_size = ctypes.sizeof(_EVENT_TRACE_PROPERTIES)
        name_buf_size = 256 * 2  # wchar
        total = props_size + name_buf_size
        buf = (ctypes.c_ubyte * total)()
        props = _EVENT_TRACE_PROPERTIES.from_buffer(buf)
        props.Wnode.BufferSize = total
        props.Wnode.Flags = WNODE_FLAG_TRACED_GUID
        props.Wnode.ClientContext = 1  # QPC 时钟
        props.Wnode.Guid = _KERNEL_TRACE_GUID
        mode = EVENT_TRACE_REAL_TIME_MODE
        if use_system_logger:
            mode |= EVENT_TRACE_SYSTEM_LOGGER_MODE
        props.LogFileMode = mode
        props.EnableFlags = EVENT_TRACE_FLAG_DPC | EVENT_TRACE_FLAG_INTERRUPT
        props.BufferSize = 64  # KB
        props.LoggerNameOffset = props_size
        return buf, props

    def _start_session(self) -> bool:
        from src.utils.privilege import enable_privilege
        enable_privilege("SeSystemProfilePrivilege")

        # 尝试两种模式：自定义会话名 → "NT Kernel Logger" 回退
        attempts = [
            (_SESSION_NAME, True),
            ("NT Kernel Logger", False),
        ]
        for name, use_sys in attempts:
            # 先停止同名旧会话（用独立缓冲区）
            stop_buf, stop_props = self._build_props(name, use_sys)
            _advapi32.ControlTraceW(
                0, name, ctypes.byref(stop_props), EVENT_TRACE_CONTROL_STOP,
            )

            buf, props = self._build_props(name, use_sys)
            self._props_buf = buf
            self._session_name = name

            handle = ctypes.c_uint64(0)
            status = _advapi32.StartTraceW(
                ctypes.byref(handle), name, ctypes.byref(props),
            )
            if status == 0:
                self._session_handle = handle
                logger.info("ETW 会话已启动: %s", name)
                break
            logger.info("StartTraceW(%s) 失败: 0x%08X", name, status)
        else:
            return False

        # 打开实时消费
        if not self._open_trace():
            self._stop_session()
            return False

        # 启动后台处理线程
        self._running = True
        self._thread = threading.Thread(
            target=self._process_thread, daemon=True, name="etw-dpc",
        )
        self._thread.start()
        logger.info("ETW DPC/ISR 会话已启动")
        return True

    def _open_trace(self) -> bool:
        """打开实时追踪消费句柄。"""
        # 保持回调引用防止被 GC
        self._callback = _EVENT_RECORD_CALLBACK(self._on_event)

        logfile = _EVENT_TRACE_LOGFILEW()
        ctypes.memset(ctypes.byref(logfile), 0, ctypes.sizeof(logfile))
        logfile.LoggerName = self._session_name
        logfile.LogFileMode_union = (
            PROCESS_TRACE_MODE_REAL_TIME | PROCESS_TRACE_MODE_EVENT_RECORD
        )
        logfile.EventRecordCallback = self._callback

        handle = _advapi32.OpenTraceW(ctypes.byref(logfile))
        if handle == INVALID_PROCESSTRACE_HANDLE:
            logger.debug("OpenTraceW 失败")
            return False
        self._trace_handle = ctypes.c_uint64(handle)
        return True

    def _process_thread(self):
        """后台线程：阻塞式处理 ETW 事件，直到会话停止。"""
        try:
            arr = (ctypes.c_uint64 * 1)(self._trace_handle.value)
            _advapi32.ProcessTrace(arr, 1, None, None)
        except Exception:
            logger.debug("ProcessTrace 异常", exc_info=True)
        self._running = False

    def _on_event(self, event_record_ptr):
        """ETW 事件回调：解析 DPC/ISR 事件，归因到驱动。"""
        try:
            rec = event_record_ptr.contents
            opcode = rec.EventHeader.EventDescriptor.Opcode

            if opcode not in (_OPCODE_DPC, _OPCODE_TIMER_DPC, _OPCODE_ISR):
                return

            # UserData 首 8 字节为 RoutineAddress（x64）
            if rec.UserDataLength < 8 or not rec.UserData:
                return
            addr = ctypes.c_uint64.from_address(rec.UserData).value
            if addr == 0:
                return

            driver = self._mapper.lookup(addr)
            if not driver:
                return

            is_dpc = opcode in (_OPCODE_DPC, _OPCODE_TIMER_DPC)
            with self._lock:
                if driver not in self._stats:
                    self._stats[driver] = [0, 0]
                if is_dpc:
                    self._stats[driver][0] += 1
                else:
                    self._stats[driver][1] += 1
        except Exception:
            pass

    def flush_top(self, n: int = 5) -> list[DriverLatencyInfo]:
        """获取 top-N 驱动统计并重置计数器。"""
        with self._lock:
            items = list(self._stats.items())
            self._stats.clear()
        # 按 DPC+ISR 总数降序
        items.sort(key=lambda x: x[1][0] + x[1][1], reverse=True)
        return [
            DriverLatencyInfo(name=name, dpc_count=counts[0], isr_count=counts[1])
            for name, counts in items[:n]
        ]

    def stop(self):
        """停止 ETW 会话并等待后台线程退出。"""
        self._stop_session()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._thread = None

    def _stop_session(self):
        """停止内核追踪会话。"""
        if _advapi32 is None:
            return
        # 关闭消费句柄（使 ProcessTrace 返回）
        if self._trace_handle.value != INVALID_PROCESSTRACE_HANDLE:
            _advapi32.CloseTrace(self._trace_handle)
            self._trace_handle = ctypes.c_uint64(INVALID_PROCESSTRACE_HANDLE)
        # 停止会话
        if self._props_buf is not None:
            props = _EVENT_TRACE_PROPERTIES.from_buffer(self._props_buf)
            _advapi32.ControlTraceW(
                0, self._session_name, ctypes.byref(props),
                EVENT_TRACE_CONTROL_STOP,
            )
        self._session_handle = ctypes.c_uint64(0)
        self._props_buf = None
