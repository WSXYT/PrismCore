using System.Diagnostics;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Microsoft.UI.Dispatching;
using PrismCore.Helpers;
using PrismCore.Models;

namespace PrismCore.ViewModels;

/// <summary>首页视图模型（对照 dashboard_vm.py）。</summary>
public partial class DashboardViewModel : ObservableObject, IDisposable
{
    private bool _disposed;
    private readonly DispatcherQueueTimer _fastTimer;
    private readonly DispatcherQueueTimer _slowTimer;
    private readonly DispatcherQueueTimer _pbTimer;
    private readonly DispatcherQueueTimer _suggestTimer;
    private readonly ProBalanceEngine _probalance = new();
    private readonly LatencyMonitor _latency = new();

    // CPU 监控 PDH
    private nint _cpuQuery;
    private nint _cpuCounter;

    // 响应延迟反馈闭环状态
    private double _lastThresholdAdjust;
    private bool _thresholdBoosted;
    private int _originalSystemThreshold;

    [ObservableProperty] private int _healthScore;
    [ObservableProperty] private double _cpuPercent, _memPercent;
    [ObservableProperty] private string _memUsed = "", _memTotal = "";
    [ObservableProperty] private List<string> _issues = [];
    [ObservableProperty] private int _proBalanceCount;
    [ObservableProperty] private double _dpcPercent, _isrPercent;
    [ObservableProperty] private string _optimizeStatus = "";
    [ObservableProperty] private bool _isOptimizing;
    [ObservableProperty] private string _pagefileStatus = "";

    // 右侧状态区
    [ObservableProperty] private bool _showProBalance;
    [ObservableProperty] private string _proBalanceMessage = "";
    [ObservableProperty] private bool _showAllClear;

    // 临时分页管理
    [ObservableProperty] private bool _hasTempPagefile;
    [ObservableProperty] private bool _showNoTempPagefile = true;
    [ObservableProperty] private string _tempPagefileDisplay = "";
    [ObservableProperty] private bool _showAddToDefault;
    private int _suggestNeededSeconds;

    partial void OnHasTempPagefileChanged(bool value) => ShowNoTempPagefile = !value;
    partial void OnIssuesChanged(List<string> value) => UpdateShowAllClear();
    partial void OnProBalanceCountChanged(int value)
    {
        ShowProBalance = value > 0;
        ProBalanceMessage = $"智能调度正在约束 {value} 个进程";
        UpdateShowAllClear();
    }
    private void UpdateShowAllClear() => ShowAllClear = Issues.Count == 0 && !ShowProBalance;

    public event Action<string>? AutoAction;
    /// <summary>分页文件状态变更：mode, size_mb, drive。</summary>
    public event Action<string, int, string>? PagefileStatusChanged;

    public DashboardViewModel(DispatcherQueue dispatcher)
    {
        var s = AppSettings.Instance;
        _originalSystemThreshold = s.ProBalanceSystemThreshold;
        _lastThresholdAdjust = Environment.TickCount64 / 1000.0;

        _fastTimer = dispatcher.CreateTimer();
        _fastTimer.Interval = TimeSpan.FromMilliseconds(Constants.MonitorIntervalMs);
        _fastTimer.Tick += (_, _) => Tick();

        _slowTimer = dispatcher.CreateTimer();
        _slowTimer.Interval = TimeSpan.FromSeconds(s.AutoOptimizeInterval);
        _slowTimer.Tick += (_, _) => SlowTick();

        _pbTimer = dispatcher.CreateTimer();
        _pbTimer.Interval = TimeSpan.FromMilliseconds(Constants.MonitorIntervalMs);
        _pbTimer.Tick += (_, _) => ProBalanceTick();

        _suggestTimer = dispatcher.CreateTimer();
        _suggestTimer.Interval = TimeSpan.FromSeconds(30);
        _suggestTimer.IsRepeating = true;
        _suggestTimer.Tick += (_, _) => SuggestCheckTick();
    }

    public void Start()
    {
        try
        {
            var s = AppSettings.Instance;

            // 初始化 CPU PDH 计数器
            if (NativeApi.PdhOpenQueryW(0, 0, out _cpuQuery) == 0)
            {
                NativeApi.PdhAddEnglishCounterW(_cpuQuery,
                    @"\Processor(_Total)\% Processor Time", 0, out _cpuCounter);
                NativeApi.PdhCollectQueryData(_cpuQuery);
            }

            if (s.DpcMonitorEnabled) _latency.Open();
            AutoOptimizer.RestorePagefileState();
            RestorePagefileUi();
            Tick();
            _fastTimer.Start();
            if (s.AutoOptimizeEnabled) _slowTimer.Start();
            if (s.ProBalanceEnabled) _pbTimer.Start();
        }
        catch (Exception ex)
        {
            OptimizeStatus = $"启动错误: {ex.Message}";
        }
    }

    public void Stop()
    {
        if (_disposed) return;
        _fastTimer.Stop();
        _slowTimer.Stop();
        _pbTimer.Stop();
        _suggestTimer.Stop();
        _probalance.ForceRestoreAll();
        _latency.Close();
        if (_cpuQuery != 0) { NativeApi.PdhCloseQuery(_cpuQuery); _cpuQuery = 0; }
    }

    [RelayCommand]
    private async Task SmartOptimizeAsync()
    {
        if (IsOptimizing) return;
        IsOptimizing = true;
        var s = AppSettings.Instance;
        var scoreBefore = AutoOptimizer.CalcHealthScore(CpuPercent);
        var memBefore = SystemInfo.GetMemoryStatus();
        var actions = new List<string>();

        if (s.PurgeStandbyEnabled)
        {
            OptimizeStatus = "正在清理内存缓存...";
            if (await Task.Run(() => MemoryManager.SmartPurge(true)))
                actions.Add("已清理内存缓存");
        }

        if (s.TrimWorkingSetsEnabled)
        {
            OptimizeStatus = "正在修剪后台进程...";
            var count = await Task.Run(() => MemoryManager.TrimBackgroundWorkingSets());
            if (count > 0) actions.Add($"已修剪 {count} 个后台进程");
        }

        if (s.PageOutIdleEnabled)
        {
            OptimizeStatus = "正在智能分页空闲进程...";
            var paged = await Task.Run(() => MemoryManager.PageOutIdleProcesses());
            if (paged.Count > 0)
            {
                var totalMb = paged.Sum(p => p.FreedMb);
                actions.Add($"已分页 {paged.Count} 个空闲进程（约 {totalMb:F0} MB）");
            }
        }

        OptimizeStatus = "正在清理垃圾文件...";
        var items = await Task.Run(() =>
        {
            var list = Cleaner.ScanTempFiles();
            list.AddRange(Cleaner.ScanElectronCaches());
            return list;
        });
        if (items.Count > 0)
        {
            var (cleaned, _) = await Task.Run(() => Cleaner.ExecuteClean(items));
            if (cleaned > 0) actions.Add($"清理了 {SystemInfo.FormatBytes((ulong)cleaned)} 垃圾");
        }

        // 智能线性扩展分页文件（对照 Python _SmartOptimizeWorker.run 步骤5）
        if (s.AutoPagefileEnabled)
        {
            var ratio = MemoryManager.GetCommitRatio();
            if (ratio * 100 > s.PagefileExpandThreshold)
            {
                OptimizeStatus = "正在智能扩展分页文件...";
                var r = await Task.Run(() => AutoOptimizer.ExpandPagefileIncremental(s.PagefileExpandThreshold));
                if (r != null)
                {
                    actions.Add(r);
                    OnPagefileCreated(r);
                }
            }
        }

        if (MemoryManager.IsCommitCritical())
        {
            var rec = MemoryManager.RecommendPagefileMb();
            if (await Task.Run(() => MemoryManager.AdjustPagefileSize(sizeMb: rec)))
                actions.Add($"虚拟内存已调至 {rec} MB（需重启生效）");
        }

        var memAfter = SystemInfo.GetMemoryStatus();
        var freed = (long)memAfter.AvailableBytes - (long)memBefore.AvailableBytes;
        if (freed > 0) actions.Add($"释放了 {SystemInfo.FormatBytes((ulong)freed)}");

        var scoreAfter = AutoOptimizer.CalcHealthScore(CpuPercent);
        OptimizeStatus = actions.Count > 0
            ? string.Join("、", actions) + $"\n健康评分: {scoreBefore} → {scoreAfter}"
            : "系统已处于最佳状态";
        IsOptimizing = false;
    }

    private void Tick()
    {
        try
        {
            var mem = SystemInfo.GetMemoryStatus();
            MemPercent = mem.UsagePercent;
            MemUsed = SystemInfo.FormatBytes(mem.UsedBytes);
            MemTotal = SystemInfo.FormatBytes(mem.TotalBytes);

            // CPU
            if (_cpuQuery != 0 && NativeApi.PdhCollectQueryData(_cpuQuery) == 0
                && NativeApi.PdhGetFormattedCounterValue(_cpuCounter, NativeApi.PDH_FMT_DOUBLE, out _, out var cpuVal) == 0)
                CpuPercent = Math.Round(cpuVal.doubleValue, 1);

            HealthScore = AutoOptimizer.CalcHealthScore(CpuPercent);

            // DPC/ISR（仅在启用时采样）
            LatencyMonitor.LatencySnapshot lat;
            if (AppSettings.Instance.DpcMonitorEnabled)
            {
                lat = _latency.Sample();
                DpcPercent = lat.DpcTimePercent;
                IsrPercent = lat.IsrTimePercent;
            }
            else
            {
                lat = new(0, 0, 0, false, [], [], false);
                DpcPercent = 0;
                IsrPercent = 0;
            }

            // 响应延迟反馈闭环
            UpdateResponsivenessFeedback();

            // 问题提示
            var issues = new List<string>();
            if (mem.UsagePercent > 75) issues.Add($"内存使用偏高 ({mem.UsagePercent:F0}%)");
            if (CpuPercent > 50) issues.Add($"CPU 负载偏高 ({CpuPercent:F0}%)");
            foreach (var d in SystemInfo.GetDiskSnapshots())
                if (d.UsagePercent > 85) issues.Add($"{d.Drive} 空间偏紧 ({d.UsagePercent:F0}%)");
            issues.AddRange(lat.Warnings);
            Issues = issues;
        }
        catch (Exception ex)
        {
            OptimizeStatus = $"监控错误: {ex}";
        }
    }

    private void SlowTick()
    {
        var s = AppSettings.Instance;
        if (!s.AutoOptimizeEnabled) return;

        var ratio = MemoryManager.GetCommitRatio();
        var threshold = s.PagefileExpandThreshold;

        // 自动撤回：提交比降至阈值-15% 以下且存在临时分页文件
        if (ratio * 100 < threshold - 15 && AutoOptimizer.GetCreatedPagefiles().Count > 0)
        {
            AutoOptimizer.RemoveAllTempPagefiles();
            ResetSuggestState();
            AppSettings.Instance.PagefileInfo = null;
            HasTempPagefile = false;
            TempPagefileDisplay = "";
            PagefileStatusChanged?.Invoke("idle", 0, "");
            AutoAction?.Invoke("提交比已恢复，已自动清理临时分页文件配置");
        }

        var mem = SystemInfo.GetMemoryStatus();
        if (mem.UsagePercent < s.MemoryThreshold) return;

        var actions = AutoOptimizer.CheckAndAutoOptimize();

        // 自动将空闲进程页出到虚拟内存
        if (s.PageOutIdleEnabled)
        {
            var paged = MemoryManager.PageOutIdleProcesses();
            if (paged.Count > 0)
            {
                var totalMb = paged.Sum(p => p.FreedMb);
                actions.Add($"已自动分页 {paged.Count} 个空闲进程（约 {totalMb:F0} MB）");
            }
        }

        foreach (var a in actions) AutoAction?.Invoke(a);
    }

    private void ProBalanceTick()
    {
        var s = AppSettings.Instance;
        var snap = _probalance.Tick(
            sysCpu: CpuPercent,
            systemThreshold: s.ProBalanceSystemThreshold,
            processThreshold: s.ProBalanceProcessThreshold,
            anomalyEnabled: s.AnomalyEnabled,
            zThreshold: s.AnomalyZThreshold,
            ewmaAlpha: s.AnomalyEwmaAlpha);

        ProBalanceCount = snap.ConstrainedCount;
        foreach (var a in snap.Actions)
            AutoAction?.Invoke($"[智能调度] {a}");
        foreach (var a in snap.AnomalyActions)
            AutoAction?.Invoke($"[智能调度:异常检测] {a}");
        if (snap.RestoredCount > 0)
            AutoAction?.Invoke(
                $"[智能调度] 系统负载恢复，已还原 {snap.RestoredCount} 个进程");
    }

    public void ReloadSettings()
    {
        var s = AppSettings.Instance;
        _slowTimer.Interval = TimeSpan.FromSeconds(s.AutoOptimizeInterval);
        if (s.AutoOptimizeEnabled) _slowTimer.Start(); else _slowTimer.Stop();
        if (s.DpcMonitorEnabled) _latency.Open(); else _latency.Close();
        if (s.ProBalanceEnabled) _pbTimer.Start();
        else { _pbTimer.Stop(); _probalance.ForceRestoreAll(); }
    }

    #region 独立操作入口（对照 Python dashboard_vm）

    /// <summary>强制清理备用列表（用户手动触发）。</summary>
    public bool ForcePurgeMemory() => MemoryManager.ForcePurge();

    /// <summary>修剪后台进程工作集。</summary>
    public int TrimProcesses() => MemoryManager.TrimBackgroundWorkingSets();

    /// <summary>分页空闲进程。</summary>
    public List<(string Name, double FreedMb)> PageOutIdle() => MemoryManager.PageOutIdleProcesses();

    /// <summary>移除所有临时分页文件。</summary>
    public List<string> RemoveTempPagefiles() => AutoOptimizer.RemoveAllTempPagefiles();

    #endregion

    #region 响应延迟反馈闭环

    /// <summary>根据 UI 响应延迟动态调整 ProBalance 阈值。</summary>
    private void UpdateResponsivenessFeedback()
    {
        var now = Environment.TickCount64 / 1000.0;
        if (now - _lastThresholdAdjust < 30) return;

        var latencyMs = SystemInfo.MeasureResponsiveness();
        var s = AppSettings.Instance;

        if (latencyMs > 200 && !_thresholdBoosted)
        {
            s.ProBalanceSystemThreshold = Math.Max(50, _originalSystemThreshold - 15);
            _thresholdBoosted = true;
            _lastThresholdAdjust = now;
        }
        else if (latencyMs <= 100 && _thresholdBoosted)
        {
            s.ProBalanceSystemThreshold = _originalSystemThreshold;
            _thresholdBoosted = false;
            _lastThresholdAdjust = now;
        }
    }

    #endregion

    #region 分页文件智能建议系统

    private void OnPagefileCreated(string msg)
    {
        var info = AppSettings.Instance.PagefileInfo;
        if (info == null) return;
        var drive = info.TryGetValue("drive", out var d) ? d?.ToString() ?? "" : "";
        var sizeMb = ParseSizeMb(info);
        HasTempPagefile = true;
        TempPagefileDisplay = $"临时分页文件 {sizeMb} MB ({drive})";
        PagefileStatusChanged?.Invoke("active", sizeMb, drive);
        StartSuggestTimer();
    }

    private static int ParseSizeMb(Dictionary<string, object> info)
        => info.TryGetValue("size_mb", out var s) && int.TryParse(s?.ToString(), out var v) ? v : 0;

    private void StartSuggestTimer()
    {
        if (!AppSettings.Instance.PagefileSuggestionEnabled) return;
        _suggestNeededSeconds = 0;
        ShowAddToDefault = false;
        _suggestTimer.Start();
    }

    private void ResetSuggestState()
    {
        _suggestTimer.Stop();
        _suggestNeededSeconds = 0;
        ShowAddToDefault = false;
    }

    /// <summary>判断临时分页文件是否仍被需要：移除后提交比是否会超过阈值。</summary>
    private bool IsTempPagefileStillNeeded()
    {
        if (AutoOptimizer.GetCreatedPagefiles().Count == 0) return false;
        var mem = SystemInfo.GetMemoryStatus();
        if (mem.CommitLimit == 0) return false;
        var tempBytes = (long)AutoOptimizer.CurrentPagefileSizeMb * 1024 * 1024;
        var limitWithout = (long)mem.CommitLimit - tempBytes;
        if (limitWithout <= 0) return true;
        var ratioWithout = (double)mem.CommitTotal / limitWithout * 100;
        return ratioWithout > AppSettings.Instance.PagefileExpandThreshold;
    }

    /// <summary>每 30 秒检测一次，连续需要 30 分钟后显示"增加到默认分页"按钮。</summary>
    private void SuggestCheckTick()
    {
        if (!HasTempPagefile) { ResetSuggestState(); return; }
        if (IsTempPagefileStillNeeded())
        {
            _suggestNeededSeconds += 30;
            if (_suggestNeededSeconds >= 1800)
                ShowAddToDefault = true;
        }
        else
        {
            _suggestNeededSeconds = 0;
        }
    }

    /// <summary>用户点击"增加到默认分页"：调整系统默认分页文件大小，临时文件保留到重启后自动失效。</summary>
    [RelayCommand]
    private void AddToDefaultPagefile()
    {
        var recMb = MemoryManager.RecommendPagefileMb();
        if (!MemoryManager.AdjustPagefileSize(sizeMb: recMb)) return;
        ResetSuggestState();
        TempPagefileDisplay += "（已调整默认分页，重启后生效）";
        AutoAction?.Invoke($"已将系统默认分页文件调整为 {recMb} MB（重启后生效，届时临时分页将自动失效）");
    }

    /// <summary>用户点击"立即重启清除"。</summary>
    [RelayCommand]
    private void RequestRebootClear()
    {
        AutoOptimizer.RemoveAllTempPagefiles();
        ResetSuggestState();
        AppSettings.Instance.PagefileInfo = null;
        HasTempPagefile = false;
        TempPagefileDisplay = "";
        Process.Start(new ProcessStartInfo("shutdown", "/r /t 3")
            { CreateNoWindow = true, UseShellExecute = false });
    }

    /// <summary>从设置恢复分页文件卡片 UI 状态。</summary>
    private void RestorePagefileUi()
    {
        var info = AppSettings.Instance.PagefileInfo;
        if (info == null) return;
        var drive = info.TryGetValue("drive", out var d) ? d?.ToString() ?? "" : "";
        var sizeMb = ParseSizeMb(info);
        HasTempPagefile = true;
        TempPagefileDisplay = $"临时分页文件 {sizeMb} MB ({drive})";
        PagefileStatusChanged?.Invoke("active", sizeMb, drive);
        StartSuggestTimer();
    }

    #endregion

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        Stop();
    }
}