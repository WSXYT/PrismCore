using Serilog;
using Velopack;
using Velopack.Sources;

namespace PrismCore.Helpers;

/// <summary>
/// 通过前缀式反向代理转发所有请求的下载器。
/// 将 https://api.github.com/... 转换为 https://proxy.example.com/https://api.github.com/...
/// </summary>
internal sealed class ProxyFileDownloader(string proxyBaseUrl) : IFileDownloader
{
    private readonly HttpClientFileDownloader _inner = new();
    private readonly string _proxyBase = proxyBaseUrl.TrimEnd('/');

    private string Proxied(string url) => $"{_proxyBase}/{url}";

    public Task DownloadFile(string url, string targetFile, Action<int> progress,
        IDictionary<string, string>? headers = null, double timeout = 30, CancellationToken cancelToken = default)
        => _inner.DownloadFile(Proxied(url), targetFile, progress, headers, timeout, cancelToken);

    public Task<byte[]> DownloadBytes(string url, IDictionary<string, string>? headers = null, double timeout = 30)
        => _inner.DownloadBytes(Proxied(url), headers, timeout);

    public Task<string> DownloadString(string url, IDictionary<string, string>? headers = null, double timeout = 30)
        => _inner.DownloadString(Proxied(url), headers, timeout);
}

/// <summary>
/// 应用更新服务，基于 Velopack，支持多源自动回退。
/// 默认通过反向代理访问 GitHub，直连作为备用。
/// </summary>
public sealed class UpdateService
{
    private const string RepoUrl = "https://github.com/WSXYT/PrismCore";
    private const string ProxyBaseUrl = "https://gemini.435535.xyz";

    /// <summary>
    /// 更新源列表，按优先级排列。代理优先，直连备用。
    /// </summary>
    private static readonly Func<IUpdateSource>[] Sources =
    [
        () => new GithubSource(RepoUrl, null, true, new ProxyFileDownloader(ProxyBaseUrl)),
        () => new GithubSource(RepoUrl, null, true),
    ];

    private UpdateManager? _manager;

    /// <summary>
    /// 获取当前应用版本（Velopack 优先，回退到程序集版本）
    /// </summary>
    public static string GetCurrentVersion()
    {
        try
        {
            var mgr = new UpdateManager(new GithubSource(RepoUrl, null, true));
            if (mgr.CurrentVersion is { } v) return v.ToString();
        }
        catch { /* 非 Velopack 安装环境 */ }

        return typeof(UpdateService).Assembly.GetName().Version?.ToString(3) ?? "未知";
    }

    /// <summary>
    /// 检查更新，自动尝试多个源
    /// </summary>
    public async Task<UpdateInfo?> CheckForUpdateAsync()
    {
        for (var i = 0; i < Sources.Length; i++)
        {
            try
            {
                var source = Sources[i]();
                _manager = new UpdateManager(source);

                if (!_manager.IsInstalled)
                {
                    Log.Warning("应用未通过安装包安装，跳过更新检查");
                    return null;
                }

                var update = await _manager.CheckForUpdatesAsync();
                if (update != null)
                    Log.Information("发现新版本 {Version}（源索引: {Index}）",
                        update.TargetFullRelease.Version, i);

                return update;
            }
            catch (Exception ex)
            {
                Log.Warning(ex, "更新源 #{Index} 检查失败，尝试下一个", i);
            }
        }

        Log.Error("所有更新源均不可用，无法检查更新");
        return null;
    }

    /// <summary>
    /// 下载并应用更新，完成后重启应用
    /// </summary>
    public async Task DownloadAndApplyAsync(UpdateInfo update, Action<int>? onProgress = null)
    {
        if (_manager is null)
            throw new InvalidOperationException("请先调用 CheckForUpdateAsync");

        await _manager.DownloadUpdatesAsync(update, onProgress);
        Log.Information("更新下载完成，准备重启");
        _manager.ApplyUpdatesAndRestart(update);
    }
}
