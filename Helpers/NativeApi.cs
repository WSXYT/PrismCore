using System.Runtime.InteropServices;

namespace PrismCore.Helpers;

/// <summary>所有 P/Invoke 声明，按功能分 region。</summary>
public static partial class NativeApi
{
    #region 内存

    [StructLayout(LayoutKind.Sequential)]
    public struct MEMORYSTATUSEX
    {
        public uint dwLength;
        public uint dwMemoryLoad;
        public ulong ullTotalPhys;
        public ulong ullAvailPhys;
        public ulong ullTotalPageFile;
        public ulong ullAvailPageFile;
        public ulong ullTotalVirtual;
        public ulong ullAvailVirtual;
        public ulong ullAvailExtendedVirtual;
    }

    [LibraryImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool GlobalMemoryStatusEx(ref MEMORYSTATUSEX lpBuffer);

    // NtSetSystemInformation - 清空备用列表
    [LibraryImport("ntdll.dll")]
    public static partial int NtSetSystemInformation(int infoClass, ref int info, int length);

    // EmptyWorkingSet
    [LibraryImport("psapi.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool EmptyWorkingSet(nint hProcess);

    // NtCreatePagingFile
    [StructLayout(LayoutKind.Sequential)]
    public struct UNICODE_STRING
    {
        public ushort Length;
        public ushort MaximumLength;
        public nint Buffer;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct LARGE_INTEGER
    {
        public long QuadPart;
    }

    [LibraryImport("ntdll.dll")]
    public static partial int NtCreatePagingFile(
        ref UNICODE_STRING path, ref LARGE_INTEGER minSize, ref LARGE_INTEGER maxSize, int priority);

    #endregion

    #region 磁盘

    [LibraryImport("kernel32.dll", StringMarshalling = StringMarshalling.Utf16, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool GetDiskFreeSpaceExW(
        string lpDirectoryName, out ulong lpFreeBytesAvailableToCaller,
        out ulong lpTotalNumberOfBytes, out ulong lpTotalNumberOfFreeBytes);

    [StructLayout(LayoutKind.Sequential)]
    public struct SHQUERYRBINFO
    {
        public uint cbSize;
        public long i64Size;
        public long i64NumItems;
    }

    [LibraryImport("shell32.dll", StringMarshalling = StringMarshalling.Utf16)]
    public static partial int SHQueryRecycleBinW(string? pszRootPath, ref SHQUERYRBINFO pSHQueryRBInfo);

    [LibraryImport("shell32.dll", StringMarshalling = StringMarshalling.Utf16)]
    public static partial int SHEmptyRecycleBinW(nint hwnd, string? pszRootPath, uint dwFlags);

    public const uint SHERB_NO_UI = 0x00000007;

    #endregion

    #region 进程

    [LibraryImport("user32.dll")]
    public static partial nint GetForegroundWindow();

    [LibraryImport("user32.dll")]
    public static partial uint GetWindowThreadProcessId(nint hWnd, out uint lpdwProcessId);

    // SetProcessInformation - ProcessPowerThrottling
    [StructLayout(LayoutKind.Sequential)]
    public struct PROCESS_POWER_THROTTLING_STATE
    {
        public uint Version;
        public uint ControlMask;
        public uint StateMask;
    }

    [LibraryImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool SetProcessInformation(
        nint hProcess, int processInformationClass, ref PROCESS_POWER_THROTTLING_STATE info, uint size);

    public const int ProcessPowerThrottling = 4;
    public const uint PROCESS_POWER_THROTTLING_CURRENT_VERSION = 1;
    public const uint PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 1;

    [LibraryImport("ntdll.dll")]
    public static partial int NtSuspendProcess(nint processHandle);

    [LibraryImport("ntdll.dll")]
    public static partial int NtResumeProcess(nint processHandle);

    [LibraryImport("kernel32.dll", SetLastError = true)]
    public static partial nint OpenProcess(uint dwDesiredAccess, [MarshalAs(UnmanagedType.Bool)] bool bInheritHandle, uint dwProcessId);

    [LibraryImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool CloseHandle(nint hObject);

    public const uint PROCESS_SET_QUOTA = 0x0100;
    public const uint PROCESS_QUERY_INFORMATION = 0x0400;
    public const uint PROCESS_QUERY_LIMITED_INFORMATION = 0x1000;
    public const uint PROCESS_SET_INFORMATION = 0x0200;
    public const uint PROCESS_ALL_ACCESS = 0x001FFFFF;

    [StructLayout(LayoutKind.Sequential)]
    public struct PROCESS_MEMORY_COUNTERS
    {
        public uint cb;
        public uint PageFaultCount;
        public nuint PeakWorkingSetSize;
        public nuint WorkingSetSize;
        public nuint QuotaPeakPagedPoolUsage;
        public nuint QuotaPagedPoolUsage;
        public nuint QuotaPeakNonPagedPoolUsage;
        public nuint QuotaNonPagedPoolUsage;
        public nuint PagefileUsage;
        public nuint PeakPagefileUsage;
    }

    [LibraryImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool K32GetProcessMemoryInfo(
        nint hProcess, out PROCESS_MEMORY_COUNTERS ppsmemCounters, uint cb);

    #endregion

    #region 窗口测量

    [LibraryImport("user32.dll", StringMarshalling = StringMarshalling.Utf16)]
    public static partial nint SendMessageTimeoutW(
        nint hWnd, uint msg, nint wParam, nint lParam,
        uint fuFlags, uint uTimeout, out nint lpdwResult);

    public const nint HWND_BROADCAST = 0xFFFF;
    public const uint WM_NULL = 0;
    public const uint SMTO_ABORTIFHUNG = 0x0002;

    [StructLayout(LayoutKind.Sequential)]
    public struct RECT
    {
        public int Left, Top, Right, Bottom;
    }

    [LibraryImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool GetWindowRect(nint hWnd, out RECT lpRect);

    [LibraryImport("user32.dll")]
    public static partial int GetSystemMetrics(int nIndex);

    #endregion

    #region ETW

    [StructLayout(LayoutKind.Sequential)]
    public struct GUID
    {
        public uint Data1;
        public ushort Data2;
        public ushort Data3;
        public unsafe fixed byte Data4[8];
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct WNODE_HEADER
    {
        public uint BufferSize;
        public uint ProviderId;
        public ulong HistoricalContext;
        public long TimeStamp;
        public GUID Guid;
        public uint ClientContext;
        public uint Flags;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct EVENT_TRACE_PROPERTIES
    {
        public WNODE_HEADER Wnode;
        public uint BufferSize;
        public uint MinimumBuffers;
        public uint MaximumBuffers;
        public uint MaximumFileSize;
        public uint LogFileMode;
        public uint FlushTimer;
        public uint EnableFlags;
        public int AgeLimit;
        public uint NumberOfBuffers;
        public uint FreeBuffers;
        public uint EventsLost;
        public uint BuffersWritten;
        public uint LogBuffersLost;
        public uint RealTimeBuffersLost;
        public nint LoggerThreadId;
        public uint LogFileNameOffset;
        public uint LoggerNameOffset;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct EVENT_DESCRIPTOR
    {
        public ushort Id;
        public byte Version;
        public byte Channel;
        public byte Level;
        public byte Opcode;
        public ushort Task;
        public ulong Keyword;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct EVENT_HEADER
    {
        public ushort Size;
        public ushort HeaderType;
        public ushort Flags;
        public ushort EventProperty;
        public uint ThreadId;
        public uint ProcessId;
        public long TimeStamp;
        public GUID ProviderId;
        public EVENT_DESCRIPTOR EventDescriptor;
        public ulong ProcessorTime;
        public GUID ActivityId;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct ETW_BUFFER_CONTEXT
    {
        public byte ProcessorNumber;
        public byte Alignment;
        public ushort LoggerId;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct EVENT_RECORD
    {
        public EVENT_HEADER EventHeader;
        public ETW_BUFFER_CONTEXT BufferContext;
        public ushort ExtendedDataCount;
        public ushort UserDataLength;
        public nint ExtendedData;
        public nint UserData;
        public nint UserContext;
    }

    public delegate void EventRecordCallback(ref EVENT_RECORD eventRecord);

    [StructLayout(LayoutKind.Sequential)]
    public unsafe struct EVENT_TRACE_LOGFILEW
    {
        public nint LogFileName;
        public nint LoggerName;
        public long CurrentTime;
        public uint BuffersRead;
        public uint LogFileMode;
        public fixed byte CurrentEventPadding[176];
        public fixed byte LogfileHeaderPadding[272];
        public nint BufferCallback;
        public uint BufferSize;
        public uint Filled;
        public uint EventsLost;
        public nint EventRecordCallback;
        public uint IsKernelTrace;
        public nint Context;
    }

    [LibraryImport("advapi32.dll", StringMarshalling = StringMarshalling.Utf16, SetLastError = true)]
    public static partial uint StartTraceW(out ulong traceHandle, string instanceName, nint properties);

    [LibraryImport("advapi32.dll", StringMarshalling = StringMarshalling.Utf16, SetLastError = true)]
    public static partial uint ControlTraceW(ulong traceHandle, string? instanceName, nint properties, uint controlCode);

    [LibraryImport("advapi32.dll", SetLastError = true)]
    public static partial ulong OpenTraceW(nint logfile);

    [LibraryImport("advapi32.dll", SetLastError = true)]
    public static partial uint ProcessTrace(ref ulong handleArray, uint handleCount, nint startTime, nint endTime);

    [LibraryImport("advapi32.dll", SetLastError = true)]
    public static partial uint CloseTrace(ulong traceHandle);

    public const uint EVENT_TRACE_REAL_TIME_MODE = 0x00000100;
    public const uint EVENT_TRACE_SYSTEM_LOGGER_MODE = 0x02000000;
    public const uint EVENT_TRACE_FLAG_DPC = 0x00000020;
    public const uint EVENT_TRACE_FLAG_INTERRUPT = 0x00000040;
    public const uint WNODE_FLAG_TRACED_GUID = 0x00020000;
    public const uint PROCESS_TRACE_MODE_REAL_TIME = 0x00000100;
    public const uint PROCESS_TRACE_MODE_EVENT_RECORD = 0x10000000;
    public const uint EVENT_TRACE_CONTROL_STOP = 1;
    public const ulong INVALID_PROCESSTRACE_HANDLE = 0xFFFFFFFFFFFFFFFF;

    #endregion

    #region PDH

    [LibraryImport("pdh.dll", StringMarshalling = StringMarshalling.Utf16)]
    public static partial int PdhOpenQueryW(nint dataSource, nint userData, out nint query);

    [LibraryImport("pdh.dll", StringMarshalling = StringMarshalling.Utf16)]
    public static partial int PdhAddCounterW(nint query, string fullCounterPath, nint userData, out nint counter);

    [LibraryImport("pdh.dll", StringMarshalling = StringMarshalling.Utf16)]
    public static partial int PdhAddEnglishCounterW(nint query, string fullCounterPath, nint userData, out nint counter);

    [LibraryImport("pdh.dll")]
    public static partial int PdhCollectQueryData(nint query);

    [StructLayout(LayoutKind.Sequential)]
    public struct PDH_FMT_COUNTERVALUE
    {
        public uint CStatus;
        public double doubleValue;
    }

    [LibraryImport("pdh.dll")]
    public static partial int PdhGetFormattedCounterValue(nint counter, uint dwFormat, out uint lpdwType, out PDH_FMT_COUNTERVALUE pValue);

    [LibraryImport("pdh.dll")]
    public static partial int PdhCloseQuery(nint query);

    public const uint PDH_FMT_DOUBLE = 0x00000200;

    #endregion

    #region MFT

    [LibraryImport("kernel32.dll", StringMarshalling = StringMarshalling.Utf16, SetLastError = true)]
    public static partial nint CreateFileW(
        string lpFileName, uint dwDesiredAccess, uint dwShareMode,
        nint lpSecurityAttributes, uint dwCreationDisposition, uint dwFlagsAndAttributes, nint hTemplateFile);

    [LibraryImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool DeviceIoControl(
        nint hDevice, uint dwIoControlCode,
        nint lpInBuffer, uint nInBufferSize,
        nint lpOutBuffer, uint nOutBufferSize,
        out uint lpBytesReturned, nint lpOverlapped);

    [LibraryImport("kernel32.dll", StringMarshalling = StringMarshalling.Utf16, SetLastError = true)]
    public static partial uint GetCompressedFileSizeW(string lpFileName, out uint lpFileSizeHigh);

    public const uint GENERIC_READ = 0x80000000;
    public const uint FILE_SHARE_READ = 0x00000001;
    public const uint FILE_SHARE_WRITE = 0x00000002;
    public const uint OPEN_EXISTING = 3;
    public static readonly nint INVALID_HANDLE_VALUE = -1;
    public const uint FSCTL_ENUM_USN_DATA = 0x000900B3;
    public const uint FSCTL_QUERY_USN_JOURNAL = 0x000900F4;
    public const uint FILE_ATTRIBUTE_DIRECTORY = 0x10;

    [StructLayout(LayoutKind.Sequential)]
    public struct USN_JOURNAL_DATA
    {
        public ulong UsnJournalID;
        public long FirstUsn, NextUsn, LowestValidUsn, MaxUsn;
        public ulong MaximumSize, AllocationDelta;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct MFT_ENUM_DATA_V0
    {
        public ulong StartFileReferenceNumber;
        public long LowUsn, HighUsn;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct USN_RECORD_V2
    {
        public uint RecordLength;
        public ushort MajorVersion, MinorVersion;
        public ulong FileReferenceNumber, ParentFileReferenceNumber;
        public long Usn, TimeStamp;
        public uint Reason, SourceInfo, SecurityId, FileAttributes;
        public ushort FileNameLength, FileNameOffset;
    }

    #endregion

    #region 系统还原

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct RESTOREPTINFOW
    {
        public uint dwEventType;
        public uint dwRestorePtType;
        public long llSequenceNumber;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)]
        public string szDescription;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct STATEMGRSTATUS
    {
        public uint nStatus;
        public long llSequenceNumber;
    }

    // 保留 DllImport：RESTOREPTINFOW 含 ByValTStr 字段，LibraryImport 源生成器不支持
    [DllImport("srclient.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool SRSetRestorePointW(ref RESTOREPTINFOW pRestorePtSpec, out STATEMGRSTATUS pSMgrStatus);

    [DllImport("srclient.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool SRRemoveRestorePoint(uint dwRPNum);

    public const uint BEGIN_SYSTEM_CHANGE = 100;
    public const uint END_SYSTEM_CHANGE = 101;
    public const uint APPLICATION_INSTALL = 0;

    #endregion

    #region 权限

    [LibraryImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool OpenProcessToken(nint processHandle, uint desiredAccess, out nint tokenHandle);

    [LibraryImport("advapi32.dll", StringMarshalling = StringMarshalling.Utf16, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool LookupPrivilegeValueW(string? lpSystemName, string lpName, out long lpLuid);

    [StructLayout(LayoutKind.Sequential)]
    public struct TOKEN_PRIVILEGES
    {
        public uint PrivilegeCount;
        public long Luid;
        public uint Attributes;
    }

    [LibraryImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool AdjustTokenPrivileges(
        nint tokenHandle, [MarshalAs(UnmanagedType.Bool)] bool disableAllPrivileges,
        ref TOKEN_PRIVILEGES newState, uint bufferLength, nint previousState, nint returnLength);

    public const uint TOKEN_ADJUST_PRIVILEGES = 0x0020;
    public const uint TOKEN_QUERY = 0x0008;
    public const uint SE_PRIVILEGE_ENABLED = 0x00000002;

    [LibraryImport("kernel32.dll")]
    public static partial nint GetCurrentProcess();

    [LibraryImport("shell32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool IsUserAnAdmin();

    #endregion

    #region 内核模块枚举

    [LibraryImport("psapi.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool EnumDeviceDrivers([Out] nint[] lpImageBase, uint cb, out uint lpcbNeeded);

    [LibraryImport("psapi.dll", StringMarshalling = StringMarshalling.Utf16, SetLastError = true)]
    public static partial uint GetDeviceDriverBaseNameW(nint imageBase, [Out] char[] lpBaseName, uint nSize);

    #endregion

    #region 系统托盘

    public const uint WM_COMMAND = 0x0111;
    public const uint WM_DESTROY = 0x0002;
    public const uint WM_LBUTTONUP = 0x0202;
    public const uint WM_RBUTTONUP = 0x0205;
    public const uint WM_APP_TRAY = 0x8000 + 1; // WM_APP + 1

    public const uint NIM_ADD = 0;
    public const uint NIM_DELETE = 2;
    public const uint NIF_MESSAGE = 0x01;
    public const uint NIF_ICON = 0x02;
    public const uint NIF_TIP = 0x04;
    public const uint NIM_MODIFY = 1;

    public const uint MF_STRING = 0x0000;
    public const uint TPM_RIGHTBUTTON = 0x0002;
    public const uint TPM_BOTTOMALIGN = 0x0020;

    public const uint IMAGE_ICON = 1;
    public const uint LR_LOADFROMFILE = 0x0010;
    public const uint LR_DEFAULTSIZE = 0x0040;

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct NOTIFYICONDATAW
    {
        public uint cbSize;
        public nint hWnd;
        public uint uID;
        public uint uFlags;
        public uint uCallbackMessage;
        public nint hIcon;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)]
        public string szTip;
    }

    // 保留 DllImport：NOTIFYICONDATAW 含 ByValTStr 字段，LibraryImport 源生成器不支持
    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool Shell_NotifyIconW(uint dwMessage, ref NOTIFYICONDATAW lpData);

    [LibraryImport("user32.dll")]
    public static partial nint CreatePopupMenu();

    [LibraryImport("user32.dll", StringMarshalling = StringMarshalling.Utf16)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool InsertMenuW(nint hMenu, uint uPosition, uint uFlags, nuint uIDNewItem, string lpNewItem);

    [LibraryImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool TrackPopupMenu(nint hMenu, uint uFlags, int x, int y, int nReserved, nint hWnd, nint prcRect);

    [LibraryImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool DestroyMenu(nint hMenu);

    [LibraryImport("user32.dll", StringMarshalling = StringMarshalling.Utf16)]
    public static partial nint LoadImageW(nint hInst, string name, uint type, int cx, int cy, uint fuLoad);

    [LibraryImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool DestroyIcon(nint hIcon);

    [LibraryImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool SetForegroundWindow(nint hWnd);

    [LibraryImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool DestroyWindow(nint hWnd);

    [LibraryImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool GetCursorPos(out POINT lpPoint);

    [StructLayout(LayoutKind.Sequential)]
    public struct POINT
    {
        public int X, Y;
    }

    public delegate nint WNDPROC(nint hWnd, uint msg, nint wParam, nint lParam);

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct WNDCLASSEXW
    {
        public uint cbSize;
        public uint style;
        public nint lpfnWndProc;
        public int cbClsExtra;
        public int cbWndExtra;
        public nint hInstance;
        public nint hIcon;
        public nint hCursor;
        public nint hbrBackground;
        public string? lpszMenuName;
        public string lpszClassName;
        public nint hIconSm;
    }

    // 保留 DllImport：WNDCLASSEXW 含 string 字段，LibraryImport 源生成器不支持自动封送结构体内的字符串指针
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern ushort RegisterClassExW(ref WNDCLASSEXW lpwcx);

    [LibraryImport("user32.dll", StringMarshalling = StringMarshalling.Utf16, SetLastError = true)]
    public static partial nint CreateWindowExW(
        uint dwExStyle, string lpClassName, string lpWindowName, uint dwStyle,
        int x, int y, int nWidth, int nHeight,
        nint hWndParent, nint hMenu, nint hInstance, nint lpParam);

    [LibraryImport("user32.dll")]
    public static partial nint DefWindowProcW(nint hWnd, uint msg, nint wParam, nint lParam);

    [LibraryImport("kernel32.dll", StringMarshalling = StringMarshalling.Utf16)]
    public static partial nint GetModuleHandleW(string? lpModuleName);

    public static readonly nint HWND_MESSAGE = -3;

    #endregion

    #region CPU 拓扑

    [StructLayout(LayoutKind.Sequential)]
    public struct SYSTEM_CPU_SET_INFORMATION
    {
        public uint Size;
        public uint Type;
        public uint Id;
        public ushort Group;
        public byte LogicalProcessorIndex;
        public byte CoreIndex;
        public byte LastLevelCacheIndex;
        public byte NumaNodeIndex;
        public byte EfficiencyClass;
        public byte AllFlags;
        public uint Reserved;
        public ulong AllocationTag;
    }

    [LibraryImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool GetSystemCpuSetInformation(
        nint information, uint bufferLength, out uint returnedLength, nint process, uint flags);

    #endregion
}
