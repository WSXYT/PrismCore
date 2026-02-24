using PrismCore.Helpers;

namespace PrismCore.Models;

/// <summary>智能清理引擎（对照 cleaner.py）。</summary>
public static class Cleaner
{
    public class CleanItem(string path, long size, string category, string description, bool selected = true)
    {
        public string Path { get; } = path;
        public long Size { get; } = size;
        public string Category { get; } = category;
        public string Description { get; } = description;
        public bool Selected { get; set; } = selected;
        public string SizeText => SystemInfo.FormatBytes((ulong)Size);
    }

    public record ScanResult(List<CleanItem> Items)
    {
        public long TotalSize => Items.Where(i => i.Selected).Sum(i => i.Size);
        public int Count => Items.Count(i => i.Selected);
    }

    // ── Electron 缓存扫描 ──

    public static List<CleanItem> ScanElectronCaches()
    {
        var items = new List<CleanItem>();
        var roots = new List<string>();
        foreach (var v in new[] { "APPDATA", "LOCALAPPDATA" })
        {
            var val = Environment.GetEnvironmentVariable(v);
            if (val != null && Directory.Exists(val)) roots.Add(val);
        }

        foreach (var root in roots)
        {
            try
            {
                foreach (var entry in Directory.GetDirectories(root))
                {
                    var toCheck = new List<string> { entry };
                    try { toCheck.AddRange(Directory.GetDirectories(entry)); } catch { }

                    foreach (var dir in toCheck)
                    {
                        if (!HasElectronSignature(dir)) continue;
                        foreach (var cacheName in Constants.ElectronCacheDirs)
                        {
                            var cachePath = Path.Combine(dir, cacheName);
                            if (!Directory.Exists(cachePath)) continue;
                            var size = DirSize(cachePath);
                            if (size > 0)
                                items.Add(new(cachePath, size, "electron",
                                    $"Electron: {Path.GetFileName(dir)}"));
                        }
                    }
                }
            }
            catch { }
        }
        return items;
    }

    private static bool HasElectronSignature(string dir)
    {
        try
        {
            var children = Directory.GetDirectories(dir).Select(Path.GetFileName).ToHashSet();
            if (!children.Contains("Cache") || !children.Contains("GPUCache")) return false;
            // 查找前两级 .asar 文件
            foreach (var f in Directory.EnumerateFiles(dir, "*.asar", SearchOption.AllDirectories))
                return true;
        }
        catch { }
        return false;
    }

    // ── 临时文件扫描 ──

    public static List<CleanItem> ScanTempFiles()
    {
        var items = new List<CleanItem>();
        var tempDirs = new HashSet<string>();
        foreach (var v in new[] { "TEMP", "TMP" })
        {
            var val = Environment.GetEnvironmentVariable(v);
            if (val != null && Directory.Exists(val)) tempDirs.Add(val);
        }
        var winTemp = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), "Temp");
        if (Directory.Exists(winTemp)) tempDirs.Add(winTemp);

        foreach (var tempDir in tempDirs)
        {
            try
            {
                foreach (var entry in new DirectoryInfo(tempDir).EnumerateFileSystemInfos())
                {
                    try
                    {
                        if (entry is FileInfo fi)
                            items.Add(new(fi.FullName, fi.Length, "temp", $"临时文件: {fi.Name}"));
                        else if (entry is DirectoryInfo di)
                            items.Add(new(di.FullName, DirSize(di.FullName), "temp", $"临时目录: {di.Name}"));
                    }
                    catch { }
                }
            }
            catch { }
        }
        return items;
    }

    // ── 大文件扫描 ──

    public static List<CleanItem> ScanLargeFiles(
        string root = @"C:\", long threshold = 0, int maxResults = 200)
    {
        if (threshold == 0) threshold = Constants.LargeFileThresholdBytes;
        var letter = root.TrimEnd('\\').TrimEnd(':');
        if (letter.Length == 1 && char.IsLetter(letter[0]))
        {
            var mftResult = ScanLargeFilesMft(letter, threshold, maxResults);
            if (mftResult != null) return mftResult;
        }
        return ScanLargeFilesWalk(root, threshold, maxResults);
    }

    private static List<CleanItem>? ScanLargeFilesMft(string letter, long threshold, int max)
    {
        try
        {
            var entries = MftScanner.ScanLargeFiles(letter, threshold, max);
            if (entries.Count == 0) return null;
            return entries.Select(e =>
            {
                var ext = Path.GetExtension(e.Path).ToLowerInvariant();
                return new CleanItem(e.Path, e.Size, "large_file", e.Path,
                    Constants.TempExtensions.Contains(ext));
            }).ToList();
        }
        catch { return null; }
    }

    private static List<CleanItem> ScanLargeFilesWalk(string root, long threshold, int max)
    {
        var items = new List<CleanItem>();
        var skipPrefixes = new[]
        {
            Path.Combine(root, "Windows"), Path.Combine(root, "Program Files"),
            Path.Combine(root, "Program Files (x86)"), Path.Combine(root, "$")
        };

        var stack = new Stack<string>();
        stack.Push(root);
        while (stack.Count > 0 && items.Count < max)
        {
            var dir = stack.Pop();
            if (skipPrefixes.Any(dir.StartsWith)) continue;
            try
            {
                foreach (var d in Directory.GetDirectories(dir))
                {
                    var name = Path.GetFileName(d);
                    if (!name.StartsWith('$') && !name.StartsWith('.'))
                        stack.Push(d);
                }
                foreach (var f in Directory.GetFiles(dir))
                {
                    try
                    {
                        var fi = new FileInfo(f);
                        if (fi.Length >= threshold)
                        {
                            var ext = fi.Extension.ToLowerInvariant();
                            items.Add(new(f, fi.Length, "large_file", f,
                                Constants.TempExtensions.Contains(ext)));
                            if (items.Count >= max) break;
                        }
                    }
                    catch { }
                }
            }
            catch { }
        }
        return items;
    }

    // ── 清理执行 ──

    public static (long Cleaned, int Failed) ExecuteClean(List<CleanItem> items)
    {
        long cleaned = 0;
        int failed = 0;
        foreach (var item in items.Where(i => i.Selected))
        {
            try
            {
                if (item.Category == "recycle_bin")
                {
                    if (NativeApi.SHEmptyRecycleBinW(0, null, NativeApi.SHERB_NO_UI) == 0)
                        cleaned += item.Size;
                    else failed++;
                }
                else if (Directory.Exists(item.Path))
                {
                    var freed = SafeRemoveTree(item.Path);
                    cleaned += freed;
                    if (freed == 0) failed++;
                }
                else if (File.Exists(item.Path))
                {
                    var size = new FileInfo(item.Path).Length;
                    File.Delete(item.Path);
                    cleaned += size;
                }
                else cleaned += item.Size; // 已不存在
            }
            catch { failed++; }
        }
        return (cleaned, failed);
    }

    private static long SafeRemoveTree(string path)
    {
        long freed = 0;
        try
        {
            foreach (var f in Directory.EnumerateFiles(path, "*", SearchOption.AllDirectories))
            {
                try { var len = new FileInfo(f).Length; File.Delete(f); freed += len; } catch { }
            }
            try { Directory.Delete(path, true); } catch { }
        }
        catch { }
        return freed;
    }

    private static long DirSize(string path)
    {
        long total = 0;
        var stack = new Stack<string>();
        stack.Push(path);
        while (stack.Count > 0)
        {
            var dir = stack.Pop();
            try
            {
                foreach (var f in Directory.GetFiles(dir))
                    try { total += new FileInfo(f).Length; } catch { }
                foreach (var d in Directory.GetDirectories(dir))
                    stack.Push(d);
            }
            catch { }
        }
        return total;
    }
}
