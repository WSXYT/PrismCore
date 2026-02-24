using System.Runtime.InteropServices;
using PrismCore.Helpers;

namespace PrismCore.Models;

/// <summary>DPC/ISR 延迟监控（对照 latency_monitor.py）。</summary>
public class LatencyMonitor : IDisposable
{
    public record DriverLatencyInfo(string Name, int DpcCount, int IsrCount);

    public record LatencySnapshot(
        double DpcTimePercent, double IsrTimePercent, double DpcQueueLength,
        bool HasIssue, List<string> Warnings, List<DriverLatencyInfo> TopDrivers, bool EtwAvailable);

    private const double DpcWarnThreshold = 3.0;
    private const double IsrWarnThreshold = 2.0;

    private nint _query;
    private readonly Dictionary<string, nint> _counters = [];
    private bool _pdhOk;
    private EtwDpcSession? _etw;

    public bool EtwAvailable { get; private set; }

    public bool Open()
    {
        _pdhOk = OpenPdh();
        _etw = new EtwDpcSession();
        if (_etw.Start()) EtwAvailable = true;
        else { _etw = null; EtwAvailable = false; }
        return _pdhOk;
    }

    public void Close()
    {
        if (_query != 0) NativeApi.PdhCloseQuery(_query);
        _query = 0; _counters.Clear(); _pdhOk = false;
        _etw?.Stop(); _etw = null;
    }

    public LatencySnapshot Sample()
    {
        double dpc = 0, isr = 0, rate = 0;
        if (_pdhOk) (dpc, isr, rate) = SamplePdh();
        var drivers = _etw?.FlushTop(5) ?? [];
        var warnings = new List<string>();
        bool hasIssue = false;

        if (dpc > DpcWarnThreshold)
        {
            hasIssue = true;
            var drv = FormatTopDrivers(drivers, "dpc");
            warnings.Add(string.IsNullOrEmpty(drv)
                ? $"DPC 延迟偏高 ({dpc:F1}%)，可能有驱动程序导致卡顿"
                : $"DPC 延迟偏高 ({dpc:F1}%)，主要来自: {drv}");
        }
        if (isr > IsrWarnThreshold)
        {
            hasIssue = true;
            var drv = FormatTopDrivers(drivers, "isr");
            warnings.Add(string.IsNullOrEmpty(drv)
                ? $"ISR 延迟偏高 ({isr:F1}%)，建议检查硬件驱动"
                : $"ISR 延迟偏高 ({isr:F1}%)，主要来自: {drv}");
        }
        return new(dpc, isr, rate, hasIssue, warnings, drivers, EtwAvailable);
    }

    public void Dispose() { Close(); GC.SuppressFinalize(this); }

    #region PDH

    private static readonly Dictionary<string, string> PdhCounters = new()
    {
        ["dpc_time"] = @"\Processor(_Total)\% DPC Time",
        ["isr_time"] = @"\Processor(_Total)\% Interrupt Time",
        ["dpc_rate"] = @"\Processor(_Total)\DPCs Queued/sec",
    };

    private bool OpenPdh()
    {
        if (NativeApi.PdhOpenQueryW(0, 0, out _query) != 0) return false;
        foreach (var (key, path) in PdhCounters)
        {
            if (NativeApi.PdhAddEnglishCounterW(_query, path, 0, out var counter) == 0)
                _counters[key] = counter;
        }
        if (_counters.Count == 0) { Close(); return false; }
        NativeApi.PdhCollectQueryData(_query);
        return true;
    }

    private (double Dpc, double Isr, double Rate) SamplePdh()
    {
        if (NativeApi.PdhCollectQueryData(_query) != 0) return (0, 0, 0);
        double dpc = 0, isr = 0, rate = 0;
        foreach (var (key, handle) in _counters)
        {
            if (NativeApi.PdhGetFormattedCounterValue(handle, NativeApi.PDH_FMT_DOUBLE, out _, out var val) == 0)
            {
                if (key == "dpc_time") dpc = Math.Round(val.doubleValue, 2);
                else if (key == "isr_time") isr = Math.Round(val.doubleValue, 2);
                else if (key == "dpc_rate") rate = Math.Round(val.doubleValue, 1);
            }
        }
        return (dpc, isr, rate);
    }

    #endregion

    #region 驱动归因

    private static readonly Dictionary<string, string> KnownDpcDrivers = new()
    {
        ["nvlddmkm"] = "NVIDIA 显卡驱动（建议更新或关闭后台录制）",
        ["atikmdag"] = "AMD 显卡驱动（建议更新驱动）",
        ["igdkmd"] = "Intel 核显驱动（建议更新驱动）",
        ["rtwlane"] = "Realtek 无线网卡驱动（建议更新或禁用节能）",
        ["rt640x64"] = "Realtek 有线网卡驱动（建议更新驱动）",
        ["rtkvhd64"] = "Realtek 音频驱动（建议更新驱动）",
        ["hdaudbus"] = "HD Audio 总线驱动（建议检查音频驱动）",
        ["ndis"] = "网络驱动接口（建议检查网卡驱动）",
        ["tcpip"] = "TCP/IP 协议栈（建议检查网络负载）",
        ["storport"] = "存储端口驱动（建议检查磁盘健康）",
        ["stornvme"] = "NVMe 存储驱动（建议更新固件）",
        ["usbxhci"] = "USB 3.0 控制器（建议检查 USB 设备）",
        ["bthhfenum"] = "蓝牙驱动（建议更新蓝牙驱动）",
    };

    private static string FormatTopDrivers(List<DriverLatencyInfo> drivers, string kind)
    {
        var filtered = new List<string>();
        foreach (var d in drivers)
        {
            var count = kind == "dpc" ? d.DpcCount : d.IsrCount;
            if (count <= 0) continue;
            var key = d.Name.Replace(".sys", "");
            filtered.Add(KnownDpcDrivers.TryGetValue(key, out var advice) ? advice : d.Name);
        }
        return string.Join("、", filtered.Take(3));
    }

    #endregion

    #region 嵌套类

    /// <summary>内核模块地址映射器。</summary>
    private class DriverMapper
    {
        private readonly long[] _bases;
        private readonly string[] _names;

        public DriverMapper()
        {
            var modules = EnumKernelModules();
            _bases = modules.Select(m => m.Base).ToArray();
            _names = modules.Select(m => m.Name).ToArray();
        }

        public string Lookup(ulong addr)
        {
            if (_bases.Length == 0) return "";
            int idx = Array.BinarySearch(_bases, (long)addr);
            if (idx < 0) idx = ~idx - 1;
            return idx >= 0 ? _names[idx] : "";
        }

        private static List<(long Base, string Name)> EnumKernelModules()
        {
            var result = new List<(long Base, string Name)>();
            try
            {
                NativeApi.EnumDeviceDrivers(null!, 0, out uint needed);
                int count = (int)(needed / (uint)IntPtr.Size);
                var bases = new nint[count];
                if (!NativeApi.EnumDeviceDrivers(bases, needed, out _)) return result;
                var buf = new char[260];
                foreach (var b in bases)
                {
                    uint len = NativeApi.GetDeviceDriverBaseNameW(b, buf, 260);
                    if (len > 0) result.Add((b, new string(buf, 0, (int)len)));
                }
                result.Sort((a, b) => a.Base.CompareTo(b.Base));
            }
            catch { }
            return result;
        }
    }

    /// <summary>ETW 实时会话：捕获 DPC/ISR 事件并归因到驱动。</summary>
    private class EtwDpcSession
    {
        private const string SessionName = "PrismCore_DpcIsr";
        private const byte OpcodeDpc = 66, OpcodeTimerDpc = 67, OpcodeIsr = 50;

        private ulong _sessionHandle;
        private ulong _traceHandle = NativeApi.INVALID_PROCESSTRACE_HANDLE;
        private Thread? _thread;
        private readonly Lock _lock = new();
        private readonly Dictionary<string, int[]> _stats = [];
        private readonly DriverMapper _mapper = new();
        private nint _propsBuf;
        private nint _loggerNamePtr;
        private string _sessionName = SessionName;
        private GCHandle _callbackPin;

        public bool Start()
        {
            try { return StartSession(); }
            catch { return false; }
        }

        public List<DriverLatencyInfo> FlushTop(int n = 5)
        {
            List<KeyValuePair<string, int[]>> items;
            lock (_lock) { items = [.. _stats]; _stats.Clear(); }
            items.Sort((a, b) => (b.Value[0] + b.Value[1]).CompareTo(a.Value[0] + a.Value[1]));
            return items.Take(n)
                .Select(kv => new DriverLatencyInfo(kv.Key, kv.Value[0], kv.Value[1]))
                .ToList();
        }

        public void Stop()
        {
            StopSession();
            _thread?.Join(3000);
            _thread = null;
        }

        private bool StartSession()
        {
            PrivilegeHelper.EnablePrivilege("SeSystemProfilePrivilege");
            (string name, bool useSys)[] attempts =
                [(SessionName, true), ("NT Kernel Logger", false)];
            bool started = false;

            foreach (var (name, useSys) in attempts)
            {
                var stopBuf = BuildProps(name, useSys);
                NativeApi.ControlTraceW(0, name, stopBuf,
                    NativeApi.EVENT_TRACE_CONTROL_STOP);
                Marshal.FreeHGlobal(stopBuf);

                var buf = BuildProps(name, useSys);
                _propsBuf = buf; _sessionName = name;
                var status = NativeApi.StartTraceW(
                    out _sessionHandle, name, buf);
                if (status == 0) { started = true; break; }
                Marshal.FreeHGlobal(buf); _propsBuf = 0;
            }
            if (!started) return false;
            if (!OpenTrace()) { StopSession(); return false; }

            _thread = new Thread(ProcessThread)
                { IsBackground = true, Name = "etw-dpc" };
            _thread.Start();
            return true;
        }

        private unsafe bool OpenTrace()
        {
            var logfile = new NativeApi.EVENT_TRACE_LOGFILEW();
            _loggerNamePtr = Marshal.StringToHGlobalUni(_sessionName);
            logfile.LoggerName = _loggerNamePtr;
            logfile.LogFileMode = NativeApi.PROCESS_TRACE_MODE_REAL_TIME
                | NativeApi.PROCESS_TRACE_MODE_EVENT_RECORD;

            NativeApi.EventRecordCallback callback = OnEvent;
            _callbackPin = GCHandle.Alloc(callback);
            logfile.EventRecordCallback =
                Marshal.GetFunctionPointerForDelegate(callback);

            var ptr = Marshal.AllocHGlobal(
                Marshal.SizeOf<NativeApi.EVENT_TRACE_LOGFILEW>());
            Marshal.StructureToPtr(logfile, ptr, false);
            var handle = NativeApi.OpenTraceW(ptr);
            Marshal.FreeHGlobal(ptr);

            if (handle == NativeApi.INVALID_PROCESSTRACE_HANDLE)
            {
                if (_callbackPin.IsAllocated) _callbackPin.Free();
                Marshal.FreeHGlobal(_loggerNamePtr); _loggerNamePtr = 0;
                return false;
            }
            _traceHandle = handle;
            return true;
        }

        private void ProcessThread()
        {
            try
            {
                var h = _traceHandle;
                NativeApi.ProcessTrace(ref h, 1, 0, 0);
            }
            catch { }
        }

        private void OnEvent(ref NativeApi.EVENT_RECORD rec)
        {
            try
            {
                var opcode = rec.EventHeader.EventDescriptor.Opcode;
                if (opcode != OpcodeDpc && opcode != OpcodeTimerDpc
                    && opcode != OpcodeIsr) return;
                if (rec.UserDataLength < 8 || rec.UserData == 0) return;
                var addr = (ulong)Marshal.ReadInt64(rec.UserData);
                if (addr == 0) return;
                var driver = _mapper.Lookup(addr);
                if (string.IsNullOrEmpty(driver)) return;

                bool isDpc = opcode is OpcodeDpc or OpcodeTimerDpc;
                lock (_lock)
                {
                    if (!_stats.TryGetValue(driver, out var c))
                        _stats[driver] = c = [0, 0];
                    if (isDpc) c[0]++; else c[1]++;
                }
            }
            catch { }
        }

        private static nint BuildProps(string name, bool useSysLogger)
        {
            int propsSize = Marshal.SizeOf<NativeApi.EVENT_TRACE_PROPERTIES>();
            int total = propsSize + 512;
            var buf = Marshal.AllocHGlobal(total);
            unsafe { new Span<byte>((void*)buf, total).Clear(); }

            var props = new NativeApi.EVENT_TRACE_PROPERTIES();
            props.Wnode.BufferSize = (uint)total;
            props.Wnode.Flags = NativeApi.WNODE_FLAG_TRACED_GUID;
            props.Wnode.ClientContext = 1;
            uint mode = NativeApi.EVENT_TRACE_REAL_TIME_MODE;
            if (useSysLogger)
                mode |= NativeApi.EVENT_TRACE_SYSTEM_LOGGER_MODE;
            props.LogFileMode = mode;
            props.EnableFlags = NativeApi.EVENT_TRACE_FLAG_DPC
                | NativeApi.EVENT_TRACE_FLAG_INTERRUPT;
            props.BufferSize = 64;
            props.LoggerNameOffset = (uint)propsSize;
            Marshal.StructureToPtr(props, buf, false);
            return buf;
        }

        private void StopSession()
        {
            if (_traceHandle != NativeApi.INVALID_PROCESSTRACE_HANDLE)
            {
                NativeApi.CloseTrace(_traceHandle);
                _traceHandle = NativeApi.INVALID_PROCESSTRACE_HANDLE;
            }
            if (_propsBuf != 0)
            {
                NativeApi.ControlTraceW(0, _sessionName, _propsBuf,
                    NativeApi.EVENT_TRACE_CONTROL_STOP);
                Marshal.FreeHGlobal(_propsBuf);
                _propsBuf = 0;
            }
            if (_loggerNamePtr != 0)
            {
                Marshal.FreeHGlobal(_loggerNamePtr);
                _loggerNamePtr = 0;
            }
            _sessionHandle = 0;
            if (_callbackPin.IsAllocated) _callbackPin.Free();
        }
    }

    #endregion

    /// <summary>诊断高延迟驱动（独立调用，对照 diagnose_dpc_drivers）。</summary>
    public static List<DriverLatencyInfo> DiagnoseDpcDrivers(int durationMs = 3000)
    {
        using var monitor = new LatencyMonitor();
        if (!monitor.Open()) return [];
        Thread.Sleep(durationMs);
        var snap = monitor.Sample();
        monitor.Close();
        return snap.TopDrivers;
    }
}
