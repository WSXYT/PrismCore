using System.Runtime.InteropServices;
using PrismCore.Helpers;

namespace PrismCore.Models;

/// <summary>MFT 快速文件扫描（对照 mft_scanner.py）。</summary>
public static class MftScanner
{
    public record MftFileEntry(string Path, long Size);

    public static List<MftFileEntry> ScanLargeFiles(
        string driveLetter = "C", long minSizeBytes = 500L * 1024 * 1024, int maxResults = 500)
    {
        nint handle;
        try { handle = OpenVolume(driveLetter); }
        catch { return []; }

        try
        {
            var journal = QueryUsnJournal(handle);
            if (journal == null) { NativeApi.CloseHandle(handle); return []; }

            var fileMap = EnumerateMft(handle, journal.Value);
            NativeApi.CloseHandle(handle);

            var pathCache = BuildPathCache(fileMap);
            return FilterLargeFiles(driveLetter, fileMap, pathCache, minSizeBytes, maxResults);
        }
        catch { NativeApi.CloseHandle(handle); return []; }
    }

    private static nint OpenVolume(string driveLetter)
    {
        var path = $@"\\.\{driveLetter}:";
        var handle = NativeApi.CreateFileW(path,
            NativeApi.GENERIC_READ, NativeApi.FILE_SHARE_READ | NativeApi.FILE_SHARE_WRITE,
            0, NativeApi.OPEN_EXISTING, 0, 0);
        if (handle == NativeApi.INVALID_HANDLE_VALUE)
            throw new IOException($"无法打开卷 {path}");
        return handle;
    }

    private static NativeApi.USN_JOURNAL_DATA? QueryUsnJournal(nint handle)
    {
        var journal = new NativeApi.USN_JOURNAL_DATA();
        int size = Marshal.SizeOf<NativeApi.USN_JOURNAL_DATA>();
        var ptr = Marshal.AllocHGlobal(size);
        try
        {
            if (!NativeApi.DeviceIoControl(handle, NativeApi.FSCTL_QUERY_USN_JOURNAL,
                    0, 0, ptr, (uint)size, out _, 0))
                return null;
            journal = Marshal.PtrToStructure<NativeApi.USN_JOURNAL_DATA>(ptr);
            return journal;
        }
        finally { Marshal.FreeHGlobal(ptr); }
    }

    // fileRef → (name, parentRef, isDir)
    private static Dictionary<ulong, (string Name, ulong Parent, bool IsDir)> EnumerateMft(
        nint handle, NativeApi.USN_JOURNAL_DATA journal)
    {
        var map = new Dictionary<ulong, (string, ulong, bool)>();
        const int bufSize = 65536;
        var med = new NativeApi.MFT_ENUM_DATA_V0 { LowUsn = 0, HighUsn = journal.NextUsn };
        int medSize = Marshal.SizeOf<NativeApi.MFT_ENUM_DATA_V0>();
        var medPtr = Marshal.AllocHGlobal(medSize);
        var bufPtr = Marshal.AllocHGlobal(bufSize);

        try
        {
            Marshal.StructureToPtr(med, medPtr, false);
            while (NativeApi.DeviceIoControl(handle, NativeApi.FSCTL_ENUM_USN_DATA,
                       medPtr, (uint)medSize, bufPtr, bufSize, out uint returned, 0)
                   && returned > 8)
            {
                int offset = 8;
                while (offset < returned)
                {
                    var rec = Marshal.PtrToStructure<NativeApi.USN_RECORD_V2>(bufPtr + offset);
                    if (rec.RecordLength == 0) break;

                    var namePtr = bufPtr + offset + rec.FileNameOffset;
                    var name = Marshal.PtrToStringUni(namePtr, rec.FileNameLength / 2) ?? "";
                    bool isDir = (rec.FileAttributes & NativeApi.FILE_ATTRIBUTE_DIRECTORY) != 0;
                    ulong fileRef = rec.FileReferenceNumber & 0x0000FFFFFFFFFFFF;
                    ulong parentRef = rec.ParentFileReferenceNumber & 0x0000FFFFFFFFFFFF;
                    map[fileRef] = (name, parentRef, isDir);

                    offset += (int)rec.RecordLength;
                }
                // 更新起始引用号
                Marshal.WriteInt64(medPtr, Marshal.ReadInt64(bufPtr));
            }
        }
        finally
        {
            Marshal.FreeHGlobal(medPtr);
            Marshal.FreeHGlobal(bufPtr);
        }
        return map;
    }

    private static Dictionary<ulong, string> BuildPathCache(
        Dictionary<ulong, (string Name, ulong Parent, bool IsDir)> map)
    {
        var cache = new Dictionary<ulong, string>();

        string Build(ulong r, int depth)
        {
            if (depth > 64) return "";
            if (cache.TryGetValue(r, out var cached)) return cached;
            if (!map.TryGetValue(r, out var entry)) { cache[r] = ""; return ""; }
            var parent = Build(entry.Parent, depth + 1);
            var full = string.IsNullOrEmpty(parent) ? entry.Name : $@"{parent}\{entry.Name}";
            cache[r] = full;
            return full;
        }

        foreach (var r in map.Keys) Build(r, 0);
        return cache;
    }

    private static List<MftFileEntry> FilterLargeFiles(string driveLetter,
        Dictionary<ulong, (string Name, ulong Parent, bool IsDir)> map,
        Dictionary<ulong, string> pathCache, long minSize, int maxResults)
    {
        var results = new List<MftFileEntry>();
        var root = $@"{driveLetter}:\";

        foreach (var (fileRef, (_, _, isDir)) in map)
        {
            if (isDir) continue;
            if (!pathCache.TryGetValue(fileRef, out var rel) || string.IsNullOrEmpty(rel)) continue;
            var fullPath = root + rel;

            var low = NativeApi.GetCompressedFileSizeW(fullPath, out uint high);
            if (low == 0xFFFFFFFF && Marshal.GetLastWin32Error() != 0) continue;
            long size = ((long)high << 32) | (low & 0xFFFFFFFFL);

            if (size >= minSize)
            {
                results.Add(new(fullPath, size));
                if (results.Count >= maxResults) break;
            }
        }
        results.Sort((a, b) => b.Size.CompareTo(a.Size));
        return results;
    }
}
