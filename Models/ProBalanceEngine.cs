using System.Diagnostics;
using PrismCore.Helpers;

namespace PrismCore.Models;

/// <summary>ProBalance CPU 调度引擎（对照 cpu_optimizer.py）。</summary>
public class ProBalanceEngine
{
    private readonly Dictionary<int, ConstrainedProcess> _constrained = [];
    private readonly Dictionary<int, double> _overThresholdSince = [];
    private readonly Dictionary<int, TrendPredictor> _procPredictors = [];
    private readonly Dictionary<int, AnomalyDetector> _procAnomalies = [];
    private readonly Dictionary<int, (double CpuTime, double WallTime)> _prevCpuTimes = [];
    private readonly TrendPredictor _sysPredictor = new();
    private readonly bool _hasHybrid;
    private readonly int[] _eCores;

    private static readonly HashSet<string> Whitelist =
    [
        .. Constants.ProtectedProcesses,
        .. Constants.AudioProcesses,
        "idle.exe", "registry.exe", "memory compression.exe",
        "dwm.exe", "explorer.exe", "searchhost.exe",
        "shellexperiencehost.exe", "startmenuexperiencehost.exe",
        "runtimebroker.exe", "fontdrvhost.exe",
        "prismcore.exe"
    ];

    public ProBalanceEngine()
    {
        var topo = GetCpuTopology();
        _hasHybrid = topo.IsHybrid;
        _eCores = topo.ECores;
    }

    public record ProBalanceSnapshot(
        double SystemCpu, double PredictedCpu,
        int ConstrainedCount, int RestoredCount,
        List<string> Actions, List<string> AnomalyActions);

    public ProBalanceSnapshot Tick(
        double sysCpu,
        int systemThreshold = 60, int processThreshold = 10,
        int sustainSeconds = 2, int restoreThreshold = 40,
        bool anomalyEnabled = true, double zThreshold = 3.0, double ewmaAlpha = 0.3)
    {
        var actions = new List<string>();
        var anomalyActions = new List<string>();
        var now = Environment.TickCount64 / 1000.0;

        double predicted = _sysPredictor.Update(sysCpu);
        int restored = 0;

        if (sysCpu < restoreThreshold)
        {
            restored = RestoreAll(now);
            _overThresholdSince.Clear();
            _procPredictors.Clear();
            _procAnomalies.Clear();
            _prevCpuTimes.Clear();
            return new(sysCpu, predicted, _constrained.Count, restored, actions, anomalyActions);
        }

        if (predicted < systemThreshold)
        {
            CleanupDead();
            return new(sysCpu, predicted, _constrained.Count, 0, actions, anomalyActions);
        }

        var fgPid = MemoryManager.GetForegroundPid();
        var activePids = new HashSet<int>();

        foreach (var p in Process.GetProcesses())
        {
            try
            {
                var pid = p.Id;
                var name = (p.ProcessName + ".exe").ToLowerInvariant();
                activePids.Add(pid);

                if (Whitelist.Contains(name) || pid == fgPid) continue;
                if (_constrained.ContainsKey(pid)) continue;

                ProcessPriorityClass nice;
                try { nice = p.PriorityClass; } catch { continue; }
                if (nice != ProcessPriorityClass.Normal) continue;

                double cpu = 0;
                try
                {
                    var cpuTime = p.TotalProcessorTime.TotalSeconds;
                    if (_prevCpuTimes.TryGetValue(pid, out var prev) && now > prev.WallTime)
                        cpu = Math.Clamp((cpuTime - prev.CpuTime) / (now - prev.WallTime) / Environment.ProcessorCount * 100, 0, 100);
                    _prevCpuTimes[pid] = (cpuTime, now);
                }
                catch { }
                if (!_procPredictors.TryGetValue(pid, out var pred))
                    _procPredictors[pid] = pred = new TrendPredictor();
                var predictedCpu = pred.Update(cpu);

                double zScore = 0;
                if (anomalyEnabled)
                {
                    if (!_procAnomalies.TryGetValue(pid, out var det))
                        _procAnomalies[pid] = det = new AnomalyDetector(ewmaAlpha, zThreshold);
                    zScore = det.Update(cpu);
                }

                if (predictedCpu >= processThreshold)
                {
                    if (!_overThresholdSince.ContainsKey(pid))
                        _overThresholdSince[pid] = now;
                    else if (now - _overThresholdSince[pid] >= sustainSeconds)
                    {
                        if (Constrain(p, nice))
                            actions.Add($"已约束 {name}(PID {pid})");
                    }
                }
                else if (zScore > zThreshold && cpu > 5.0 && sysCpu >= restoreThreshold)
                {
                    if (Constrain(p, nice))
                        anomalyActions.Add($"异常检测约束 {name}(PID {pid})");
                }
                else
                    _overThresholdSince.Remove(pid);
            }
            catch { }
            finally { p.Dispose(); }
        }

        // 清理已退出进程
        foreach (var pid in _prevCpuTimes.Keys.Where(p => !activePids.Contains(p)).ToList())
        {
            _prevCpuTimes.Remove(pid);
            _overThresholdSince.Remove(pid);
            _procPredictors.Remove(pid);
            _procAnomalies.Remove(pid);
        }
        CleanupDead();

        return new(sysCpu, predicted, _constrained.Count, restored, actions, anomalyActions);
    }

    private bool Constrain(Process proc, ProcessPriorityClass originalNice)
    {
        try
        {
            proc.PriorityClass = ProcessPriorityClass.BelowNormal;
        }
        catch { return false; }

        nint[]? origAffinity = null;
        if (_hasHybrid && _eCores.Length > 0)
        {
            try
            {
                origAffinity = [proc.ProcessorAffinity];
                proc.ProcessorAffinity = BuildAffinityMask(_eCores);
            }
            catch { }
        }

        _constrained[proc.Id] = new(proc.Id, proc.ProcessName, originalNice,
            origAffinity?[0], Environment.TickCount64 / 1000.0);
        _overThresholdSince.Remove(proc.Id);
        return true;
    }

    private int RestoreAll(double now)
    {
        int restored = 0;
        var toRemove = new List<int>();
        foreach (var (pid, info) in _constrained)
        {
            if (now - info.ConstrainedAt < Constants.ProBalanceMinConstrainSeconds) continue;
            if (RestoreOne(pid, info)) { restored++; toRemove.Add(pid); }
        }
        foreach (var pid in toRemove) _constrained.Remove(pid);
        return restored;
    }

    private static bool RestoreOne(int pid, ConstrainedProcess info)
    {
        try
        {
            using var p = Process.GetProcessById(pid);
            p.PriorityClass = info.OriginalPriority;
            if (info.OriginalAffinity.HasValue)
                p.ProcessorAffinity = info.OriginalAffinity.Value;
            return true;
        }
        catch (ArgumentException) { return true; } // 进程已退出
        catch { return false; }
    }

    private void CleanupDead()
    {
        var dead = _constrained.Keys.Where(pid =>
        {
            try { using var p = Process.GetProcessById(pid); return false; }
            catch { return true; }
        }).ToList();
        foreach (var pid in dead)
        {
            _constrained.Remove(pid);
            _procPredictors.Remove(pid);
            _procAnomalies.Remove(pid);
            _prevCpuTimes.Remove(pid);
        }
    }

    public void ForceRestoreAll()
    {
        foreach (var (pid, info) in _constrained)
            RestoreOne(pid, info);
        _constrained.Clear();
        _overThresholdSince.Clear();
        _prevCpuTimes.Clear();
    }

    private static nint BuildAffinityMask(int[] cores)
    {
        long mask = 0;
        foreach (var c in cores) mask |= 1L << c;
        return (nint)mask;
    }

    private static CpuTopology GetCpuTopology()
    {
        try
        {
            uint needed = 0;
            NativeApi.GetSystemCpuSetInformation(0, 0, out needed, 0, 0);
            if (needed == 0) return FallbackTopology();

            var buf = new byte[needed];
            unsafe
            {
                fixed (byte* ptr = buf)
                {
                    if (!NativeApi.GetSystemCpuSetInformation((nint)ptr, needed, out needed, 0, 0))
                        return FallbackTopology();
                }
            }

            var pCores = new List<int>();
            var eCores = new List<int>();
            int offset = 0;
            int structSize = System.Runtime.InteropServices.Marshal.SizeOf<NativeApi.SYSTEM_CPU_SET_INFORMATION>();
            while (offset + structSize <= needed)
            {
                var info = System.Runtime.InteropServices.Marshal.PtrToStructure<NativeApi.SYSTEM_CPU_SET_INFORMATION>(
                    System.Runtime.InteropServices.Marshal.UnsafeAddrOfPinnedArrayElement(buf, offset));
                if (info.Size == 0) break;
                if (info.EfficiencyClass == 0) pCores.Add(info.LogicalProcessorIndex);
                else eCores.Add(info.LogicalProcessorIndex);
                offset += (int)info.Size;
            }
            return new(pCores.ToArray(), eCores.ToArray(), pCores.Count > 0 && eCores.Count > 0);
        }
        catch { return FallbackTopology(); }
    }

    private static CpuTopology FallbackTopology()
    {
        int logical = Environment.ProcessorCount;
        return new(Enumerable.Range(0, logical).ToArray(), [], false);
    }

    private record struct CpuTopology(int[] PCores, int[] ECores, bool IsHybrid);
    private record struct ConstrainedProcess(int Pid, string Name, ProcessPriorityClass OriginalPriority, nint? OriginalAffinity, double ConstrainedAt);

    /// <summary>EWMA 趋势预测器。</summary>
    private class TrendPredictor(double alpha = 0.3, int lookahead = 2)
    {
        private double _ewma, _rate;
        private bool _hasData;

        public double Update(double value)
        {
            var prev = _ewma;
            if (!_hasData) { _ewma = value; _hasData = true; }
            else _ewma = alpha * value + (1 - alpha) * _ewma;
            _rate = _ewma - prev;
            return Math.Clamp(_ewma + _rate * lookahead, 0, 100);
        }
    }
}
