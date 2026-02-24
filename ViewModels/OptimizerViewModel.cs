using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PrismCore.Models;

namespace PrismCore.ViewModels;

/// <summary>加速页视图模型（对照 optimizer_vm.py）。</summary>
public partial class OptimizerViewModel : ObservableObject
{
    [ObservableProperty] private string _optimizeStatus = "";
    [ObservableProperty] private bool _isOptimizing;
    [ObservableProperty] private string _memTotal = "", _memUsed = "", _memAvailable = "";
    [ObservableProperty] private double _memPercent;
    [ObservableProperty] private double _commitRatio;
    [ObservableProperty] private List<ProcessManager.ProcessInfo> _processes = [];
    [ObservableProperty] private List<StartupManager.StartupItem> _startupItems = [];
    [ObservableProperty] private bool _isLoadingStartup;
    [ObservableProperty] private bool _isLoadingProcesses;

    [RelayCommand]
    private async Task OptimizeMemoryAsync()
    {
        if (IsOptimizing) return;
        IsOptimizing = true;
        var actions = new List<string>();
        var settings = AppSettings.Instance;
        var memBefore = SystemInfo.GetMemoryStatus();

        if (settings.PurgeStandbyEnabled)
        {
            OptimizeStatus = "正在清理备用列表...";
            if (await Task.Run(() => MemoryManager.PurgeStandbyList()))
                actions.Add("已清理内存缓存");
        }

        if (settings.TrimWorkingSetsEnabled)
        {
            OptimizeStatus = "正在修剪后台工作集...";
            var count = await Task.Run(() => MemoryManager.TrimBackgroundWorkingSets());
            if (count > 0) actions.Add($"已修剪 {count} 个后台进程");
        }

        if (settings.PageOutIdleEnabled)
        {
            OptimizeStatus = "正在智能分页空闲进程...";
            var paged = await Task.Run(() => MemoryManager.PageOutIdleProcesses());
            if (paged.Count > 0)
            {
                var totalMb = paged.Sum(p => p.FreedMb);
                actions.Add($"已分页 {paged.Count} 个空闲进程（约 {totalMb:F0} MB）");
            }
        }

        var memAfter = SystemInfo.GetMemoryStatus();
        var freed = (long)memAfter.AvailableBytes - (long)memBefore.AvailableBytes;
        if (freed > 0) actions.Add($"释放了 {SystemInfo.FormatBytes((ulong)freed)}");

        OptimizeStatus = actions.Count > 0 ? string.Join("、", actions) : "系统已处于最佳状态";
        IsOptimizing = false;
    }

    [RelayCommand]
    private async Task RefreshMemoryAsync()
    {
        var mem = await Task.Run(SystemInfo.GetMemoryStatus);
        MemTotal = SystemInfo.FormatBytes(mem.TotalBytes);
        MemUsed = SystemInfo.FormatBytes(mem.UsedBytes);
        MemAvailable = SystemInfo.FormatBytes(mem.AvailableBytes);
        MemPercent = mem.UsagePercent;
        CommitRatio = Math.Round(MemoryManager.GetCommitRatio() * 100, 1);
    }

    [RelayCommand]
    private async Task RefreshProcessesAsync()
    {
        IsLoadingProcesses = true;
        Processes = await Task.Run(() => ProcessManager.ListTopProcesses());
        IsLoadingProcesses = false;
    }

    [RelayCommand]
    private async Task RefreshStartupAsync()
    {
        IsLoadingStartup = true;
        StartupItems = await Task.Run(StartupManager.ListStartupItems);
        IsLoadingStartup = false;
    }

    public async Task LoadAsync()
    {
        await Task.WhenAll(RefreshMemoryAsync(), RefreshStartupAsync(), RefreshProcessesAsync());
    }

    public bool BoostProcess(int pid) => ProcessManager.BoostForeground(pid);
    public bool ThrottleProcess(int pid) => ProcessManager.ThrottleBackground(pid);

    public string ToggleStartup(StartupManager.StartupItem item, bool enable)
    {
        var ok = item.Source == "注册表"
            ? StartupManager.ToggleStartupRegistry(item, enable)
            : StartupManager.ToggleStartupTask(item, enable);
        var action = enable ? "启用" : "禁用";
        return $"{action} {item.Name}: {(ok ? "成功" : "失败")}";
    }
}
