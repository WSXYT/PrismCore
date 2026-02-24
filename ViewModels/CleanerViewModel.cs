using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PrismCore.Helpers;
using PrismCore.Models;

namespace PrismCore.ViewModels;

/// <summary>清理器视图模型（对照 cleaner_vm.py）。</summary>
public partial class CleanerViewModel : ObservableObject
{
    private static readonly HashSet<string> SystemCategories =
        ["winsxs", "old_drivers", "orphan_registry", "win_update", "compact_os"];

    [ObservableProperty] private string _scanStatus = "";
    [ObservableProperty] private bool _isScanning;
    [ObservableProperty] private bool _isCleaning;
    [ObservableProperty] private List<Cleaner.CleanItem> _scanItems = [];
    [ObservableProperty] private string _totalSizeText = "";

    [RelayCommand]
    private async Task ScanAsync(bool deep)
    {
        if (IsScanning) return;
        IsScanning = true;
        ScanItems = [];

        var items = new List<Cleaner.CleanItem>();

        ScanStatus = "正在扫描临时文件...";
        items.AddRange(await Task.Run(Cleaner.ScanTempFiles));

        ScanStatus = "正在搜索应用缓存...";
        items.AddRange(await Task.Run(Cleaner.ScanElectronCaches));

        ScanStatus = "正在检查回收站...";
        var rbSize = await Task.Run(QueryRecycleBinSize);
        if (rbSize > 0)
            items.Add(new("$RECYCLE.BIN", rbSize, "recycle_bin", "回收站"));

        if (deep)
        {
            ScanStatus = @"正在扫描大文件 (C:\)...";
            items.AddRange(await Task.Run(() => Cleaner.ScanLargeFiles()));
        }

        // 系统组件扫描
        ScanStatus = "正在分析系统组件...";
        await Task.Run(() => ScanSystemComponents(items));

        items.Sort((a, b) => b.Size.CompareTo(a.Size));
        ScanItems = items;
        TotalSizeText = $"共 {items.Count} 项，{SystemInfo.FormatBytes((ulong)items.Where(i => i.Selected).Sum(i => i.Size))}";
        ScanStatus = "扫描完成";
        IsScanning = false;
    }

    [RelayCommand]
    private async Task CleanAsync()
    {
        if (IsCleaning || ScanItems.Count == 0) return;
        IsCleaning = true;
        var selected = ScanItems.Where(i => i.Selected).ToList();

        var fileItems = selected.Where(i => !SystemCategories.Contains(i.Category)).ToList();
        var sysItems = selected.Where(i => SystemCategories.Contains(i.Category)).ToList();

        long cleaned = 0; int failed = 0;

        if (fileItems.Count > 0)
        {
            ScanStatus = "正在清理文件...";
            var (c, f) = await Task.Run(() => Cleaner.ExecuteClean(fileItems));
            cleaned += c; failed += f;
        }

        if (sysItems.Count > 0)
        {
            ScanStatus = "正在创建系统还原点...";
            await Task.Run(() => SystemCleaner.CreateRestorePoint("PrismCore 系统清理前备份"));

            foreach (var item in sysItems)
            {
                var (c, f) = await Task.Run(() => CleanSystemItem(item));
                cleaned += c; failed += f;
            }
        }

        var msg = $"已清理 {SystemInfo.FormatBytes((ulong)cleaned)}";
        if (failed > 0) msg += $"（{failed} 项失败）";
        ScanStatus = msg;
        ScanItems = [];
        IsCleaning = false;
    }

    private static void ScanSystemComponents(List<Cleaner.CleanItem> items)
    {
        var updSize = SystemCleaner.ScanUpdateCacheSize();
        if (updSize > 0)
            items.Add(new("$WIN_UPDATE", updSize, "win_update",
                "Windows Update 下载缓存", false));

        var oldDrv = SystemCleaner.ListOldDrivers();
        if (oldDrv.Count > 0)
            items.Add(new("$OLD_DRIVERS", oldDrv.Count, "old_drivers",
                $"旧版驱动包 ({oldDrv.Count} 个)", false));

        var orphans = SystemCleaner.ScanOrphanRegistry();
        if (orphans.Count > 0)
            items.Add(new("$ORPHAN_REGISTRY", orphans.Count, "orphan_registry",
                $"孤立注册表项 ({orphans.Count} 个)", false));

        if (SystemCleaner.QueryCompactOsStatus())
            items.Add(new("$COMPACT_OS", 0, "compact_os",
                "CompactOS 压缩（可节省约 2GB）", false));
    }

    private static (long Cleaned, int Failed) CleanSystemItem(Cleaner.CleanItem item)
    {
        switch (item.Category)
        {
            case "win_update":
                var r = SystemCleaner.CleanupWindowsUpdate();
                return (r.FreedBytes, r.Success ? 0 : 1);
            case "old_drivers":
                var old = SystemCleaner.ListOldDrivers();
                int removed = old.Count(d => SystemCleaner.DeleteDriver(d["inf"]));
                return (0, removed > 0 ? 0 : 1);
            case "orphan_registry":
                var orphans = SystemCleaner.ScanOrphanRegistry();
                int c = orphans.Count(o => SystemCleaner.BackupAndDeleteKey(o["key"]));
                return (0, c > 0 ? 0 : 1);
            case "winsxs":
                var wr = SystemCleaner.CleanupWinsxs();
                return (0, wr.Success ? 0 : 1);
            case "compact_os":
                var cr = SystemCleaner.EnableCompactOs();
                return (0, cr.Success ? 0 : 1);
            default: return (0, 1);
        }
    }

    private static long QueryRecycleBinSize()
    {
        var info = new NativeApi.SHQUERYRBINFO { cbSize = (uint)System.Runtime.InteropServices.Marshal.SizeOf<NativeApi.SHQUERYRBINFO>() };
        return NativeApi.SHQueryRecycleBinW(null, ref info) == 0 ? info.i64Size : 0;
    }
}
