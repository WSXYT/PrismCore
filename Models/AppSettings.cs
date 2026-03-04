using System.Text.Json;

namespace PrismCore.Models;

/// <summary>应用设置，单例模式，JSON 持久化（对照 settings.py）。</summary>
public sealed class AppSettings
{
    private static readonly Lazy<AppSettings> _instance = new(() => new AppSettings());
    public static AppSettings Instance => _instance.Value;

    private readonly string _filePath;
    private readonly object _lock = new();
    private Dictionary<string, JsonElement> _data = [];
    private CancellationTokenSource? _saveCts;

    private AppSettings()
    {
        var dir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "PrismCore");
        Directory.CreateDirectory(dir);
        _filePath = Path.Combine(dir, "settings.json");
        Load();
    }

    private void Load()
    {
        try
        {
            if (File.Exists(_filePath))
                _data = JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(File.ReadAllText(_filePath)) ?? [];
        }
        catch { _data = []; }
    }

    private void DebounceSave()
    {
        var newCts = new CancellationTokenSource();
        var oldCts = Interlocked.Exchange(ref _saveCts, newCts);
        oldCts?.Cancel();
        oldCts?.Dispose();
        var token = newCts.Token;
        Task.Delay(500, token).ContinueWith(_ => Save(), token, TaskContinuationOptions.OnlyOnRanToCompletion, TaskScheduler.Default);
    }

    private void Save()
    {
        string json;
        lock (_lock)
        {
            json = JsonSerializer.Serialize(_data, new JsonSerializerOptions { WriteIndented = true });
        }
        try { File.WriteAllText(_filePath, json); }
        catch { /* 静默 */ }
    }

    private T Get<T>(string key, T defaultValue)
    {
        lock (_lock)
        {
            if (!_data.TryGetValue(key, out var elem)) return defaultValue;
            try { return elem.Deserialize<T>() ?? defaultValue; }
            catch { return defaultValue; }
        }
    }

    private void Set<T>(string key, T value)
    {
        lock (_lock)
        {
            _data[key] = JsonSerializer.SerializeToElement(value);
        }
        DebounceSave();
    }

    // 后台自动优化
    public bool AutoOptimizeEnabled { get => Get("auto_enabled", true); set => Set("auto_enabled", value); }
    public int AutoOptimizeInterval { get => Get("auto_interval", 10); set => Set("auto_interval", value); }
    public int MemoryThreshold { get => Get("mem_threshold", 60); set => Set("mem_threshold", value); }

    // 虚拟内存
    public bool AutoPagefileEnabled { get => Get("pagefile_auto", true); set => Set("pagefile_auto", value); }
    public int PagefileExpandThreshold { get => Get("pagefile_expand_threshold", 70); set => Set("pagefile_expand_threshold", value); }

    // DPC/ISR 监控
    public bool DpcMonitorEnabled { get => Get("dpc_monitor", true); set => Set("dpc_monitor", value); }

    // 分页文件持久化
    public Dictionary<string, object>? PagefileInfo
    {
        get => Get<Dictionary<string, object>?>("pagefile_info", null);
        set => Set("pagefile_info", value);
    }
    public bool PagefilePendingReboot { get => Get("pagefile_pending_reboot", false); set => Set("pagefile_pending_reboot", value); }

    // 智能调度
    public bool ProBalanceEnabled { get => Get("probalance_enabled", true); set => Set("probalance_enabled", value); }
    public int ProBalanceSystemThreshold { get => Get("probalance_sys_threshold", 45); set => Set("probalance_sys_threshold", value); }
    public int ProBalanceProcessThreshold { get => Get("probalance_proc_threshold", 8); set => Set("probalance_proc_threshold", value); }
    public int ProBalanceSampleInterval { get => Get("probalance_sample_interval", 1); set => Set("probalance_sample_interval", value); }

    // 异常检测
    public bool AnomalyEnabled { get => Get("anomaly_enabled", true); set => Set("anomaly_enabled", value); }
    public double AnomalyZThreshold { get => Get("anomaly_z_threshold", 3.0); set => Set("anomaly_z_threshold", value); }
    public double AnomalyEwmaAlpha { get => Get("anomaly_ewma_alpha", 0.3); set => Set("anomaly_ewma_alpha", value); }

    // 内存优化策略
    public bool PurgeStandbyEnabled { get => Get("purge_standby", true); set => Set("purge_standby", value); }
    public bool TrimWorkingSetsEnabled { get => Get("trim_workingsets", true); set => Set("trim_workingsets", value); }
    public bool PageOutIdleEnabled { get => Get("page_out_idle", true); set => Set("page_out_idle", value); }

    // 智能分页文件建议
    public bool PagefileSuggestionEnabled { get => Get("pagefile_suggestion", true); set => Set("pagefile_suggestion", value); }

    // 开机自启动
    public bool AutoStartEnabled { get => Get("auto_start", false); set => Set("auto_start", value); }
    public bool SilentStartEnabled { get => Get("silent_start", false); set => Set("silent_start", value); }

    // 更新模式：0=不检查, 1=仅检查, 2=自动安装
    public int UpdateMode { get => Get("update_mode", 2); set => Set("update_mode", value); }

    // 更新通道：0=稳定版本, 1=预发布版本
    public int UpdateChannel { get => Get("update_channel", 0); set => Set("update_channel", value); }

    // 记录最近一次安装版本的通道（0=稳定, 1=预发布），用于通道默认值自动对齐
    public int LastInstalledChannel { get => Get("last_installed_channel", -1); set => Set("last_installed_channel", value); }

    /// <summary>恢复所有设置为默认值。</summary>
    public void ResetToDefaults()
    {
        _saveCts?.Cancel();
        lock (_lock) { _data = []; }
        Save();
    }
}
