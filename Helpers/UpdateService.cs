using Serilog;
using PrismCore.Models;
using System.Reflection;
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
    private readonly Func<IUpdateSource>[] _sources;

    public UpdateService(bool includePrerelease)
    {
        _sources =
        [
            () => new GithubSource(RepoUrl, null, includePrerelease, new ProxyFileDownloader(ProxyBaseUrl)),
            () => new GithubSource(RepoUrl, null, includePrerelease),
        ];
    }

    private static UpdateManager CreateProbeManager() =>
        new(new GithubSource(RepoUrl, null, false));

    private static bool IsInstalledByVelopack()
    {
        try
        {
            var mgr = CreateProbeManager();
            return mgr.IsInstalled;
        }
        catch { /* 非 Velopack 安装环境 */ }

        return false;
    }

    private static bool TryGetInstalledVersion(out string version)
    {
        version = string.Empty;
        try
        {
            var mgr = CreateProbeManager();
            if (!mgr.IsInstalled || mgr.CurrentVersion is null) return false;
            version = mgr.CurrentVersion.ToString();
            return !string.IsNullOrWhiteSpace(version);
        }
        catch { /* 非 Velopack 安装环境 */ }

        return false;
    }

    /// <summary>
    /// 按当前安装版本通道修正设置，并返回生效通道（0=稳定，1=预发布）。
    /// </summary>
    public static int ResolveAndPersistRecommendedChannel(AppSettings settings)
    {
        var recommendedChannel = GetRecommendedChannel();
        if (settings.LastInstalledChannel != recommendedChannel)
        {
            settings.UpdateChannel = recommendedChannel;
            settings.LastInstalledChannel = recommendedChannel;
        }

        return settings.UpdateChannel;
    }

    /// <summary>
    /// 根据当前已安装版本推断推荐通道：0=稳定，1=预发布
    /// </summary>
    public static int GetRecommendedChannel() => IsCurrentBuildPrerelease() ? 1 : 0;

    private static bool IsCurrentBuildPrerelease()
    {
        if (TryGetInstalledVersion(out var installedVersion))
            return IsPrereleaseVersion(installedVersion);

        var infoVersion = typeof(UpdateService).Assembly
            .GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion;

        return !string.IsNullOrWhiteSpace(infoVersion) && IsPrereleaseVersion(infoVersion);
    }

    private static bool IsPrereleaseVersion(string version) =>
        version.Contains('-', StringComparison.Ordinal);

    private UpdateManager? _manager;

    /// <summary>
    /// 获取当前应用版本（Velopack 优先，回退到程序集版本）
    /// </summary>
    public static string GetCurrentVersion()
    {
        if (TryGetInstalledVersion(out var installedVersion))
            return installedVersion;

        return typeof(UpdateService).Assembly.GetName().Version?.ToString(3) ?? "未知";
    }

    /// <summary>
    /// 当前是否为 Velopack 安装环境
    /// </summary>
    public static bool IsVelopackInstalled() => IsInstalledByVelopack();

    /// <summary>
    /// 检查更新，自动尝试多个源。
    /// 返回 UpdateInfo（有新版本）或 null（已是最新）。
    /// 非安装环境抛出 InvalidOperationException。
    /// </summary>
    public async Task<UpdateInfo?> CheckForUpdateAsync()
    {
        for (var i = 0; i < _sources.Length; i++)
        {
            try
            {
                var source = _sources[i]();
                _manager = new UpdateManager(source);

                if (!_manager.IsInstalled)
                    throw new InvalidOperationException("应用未通过 Velopack 安装包安装，无法检查更新");

                var update = await _manager.CheckForUpdatesAsync();
                if (update != null)
                    Log.Information("发现新版本 {Version}（源索引: {Index}）",
                        update.TargetFullRelease.Version, i);

                return update;
            }
            catch (InvalidOperationException) { throw; }
            catch (Exception ex)
            {
                Log.Warning(ex, "更新源 #{Index} 检查失败，尝试下一个", i);
            }
        }

        Log.Error("所有更新源均不可用，无法检查更新");
        throw new Exception("所有更新源均不可用");
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
