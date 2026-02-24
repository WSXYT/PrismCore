namespace PrismCore.Helpers;

/// <summary>全局常量定义（对照 constants.py）。</summary>
public static class Constants
{
    public const string AppName = "PrismCore";
    public const string AppVersion = "1.0.0";

    // 内存阈值
    public const long FreeMemThresholdBytes = 2L * 1024 * 1024 * 1024;       // 2 GB
    public const double StandbyRatioThreshold = 0.25;                         // 总内存 25%
    public const double CommitRatioWarning = 0.80;                            // 80%

    // 磁盘阈值
    public const long DiskCriticalBytes = 10L * 1024 * 1024 * 1024;          // 10 GB
    public const long LargeFileThresholdBytes = 500L * 1024 * 1024;          // 500 MB

    // Electron 缓存特征目录
    public static readonly string[] ElectronCacheDirs =
        ["Cache", "Code Cache", "GPUCache", "blob_storage", "Service Worker"];

    public static readonly string[] ElectronSafeDirs =
        ["Local Storage", "Session Storage", "Cookies", "Preferences"];

    // 临时文件扩展名
    public static readonly HashSet<string> TempExtensions =
        [".tmp", ".temp", ".log", ".old", ".bak", ".dmp", ".etl", ".chk"];

    // 受保护进程
    public static readonly HashSet<string> ProtectedProcesses =
    [
        "audiodg.exe", "csrss.exe", "smss.exe", "wininit.exe",
        "services.exe", "lsass.exe", "svchost.exe", "system.exe"
    ];

    // 音频相关进程
    public static readonly HashSet<string> AudioProcesses =
    [
        "audiodg.exe", "audiosrv.exe", "spotify.exe", "music.ui.exe",
        "foobar2000.exe", "aimp.exe", "vlc.exe", "wmplayer.exe"
    ];

    // 监控刷新间隔
    public const int MonitorIntervalMs = 1500;

    // ProBalance CPU 调度默认参数
    public const int ProBalanceSystemThreshold = 60;
    public const int ProBalanceProcessThreshold = 10;
    public const int ProBalanceSustainSeconds = 2;
    public const int ProBalanceMinConstrainSeconds = 3;
    public const int ProBalanceRestoreThreshold = 40;
    // 采样间隔（秒）
    public const int ProBalanceSampleInterval = 1;

    // 页错误增量阈值
    public const long PageFaultDeltaThreshold = 50000;

    // 注册表备份目录
    public static readonly string RegistryBackupDir = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "PrismCore", "RegBackup");
}
