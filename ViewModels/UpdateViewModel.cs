using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PrismCore.Helpers;
using PrismCore.Models;
using Serilog;
using Velopack;

namespace PrismCore.ViewModels;

/// <summary>更新页面视图模型。</summary>
public partial class UpdateViewModel : ObservableObject
{
    private readonly AppSettings _settings = AppSettings.Instance;
    private UpdateInfo? _cachedUpdate;
    private UpdateService? _activeUpdateService;

    [ObservableProperty] private string _currentVersion = UpdateService.GetCurrentVersion();
    [ObservableProperty] private string _latestVersion = "未检查";
    [ObservableProperty] private bool _isUpToDate;
    [ObservableProperty] private bool _isChecking;
    [ObservableProperty] private bool _isUpdating;
    [ObservableProperty] private int _updateProgress;
    [ObservableProperty] private string _statusMessage = "";
    [ObservableProperty] private int _selectedUpdateMode;
    [ObservableProperty] private int _selectedUpdateChannel;

    public UpdateViewModel()
    {
        var recommendedChannel = UpdateService.GetRecommendedChannel();
        if (_settings.LastInstalledChannel != recommendedChannel)
        {
            _settings.UpdateChannel = recommendedChannel;
            _settings.LastInstalledChannel = recommendedChannel;
        }

        _selectedUpdateMode = _settings.UpdateMode;
        _selectedUpdateChannel = _settings.UpdateChannel;
    }

    partial void OnSelectedUpdateModeChanged(int value)
    {
        _settings.UpdateMode = value;
    }

    partial void OnSelectedUpdateChannelChanged(int value)
    {
        _settings.UpdateChannel = value;
    }

    public bool HasUpdate => _cachedUpdate != null && !IsUpToDate;

    [RelayCommand]
    private async Task CheckForUpdateAsync()
    {
        if (IsChecking) return;
        IsChecking = true;
        StatusMessage = "正在检查更新...";

        try
        {
            _activeUpdateService = new UpdateService(SelectedUpdateChannel == 1);
            _cachedUpdate = await _activeUpdateService.CheckForUpdateAsync();
            if (_cachedUpdate != null)
            {
                LatestVersion = _cachedUpdate.TargetFullRelease.Version.ToString();
                IsUpToDate = false;
                StatusMessage = "发现新版本";
            }
            else
            {
                LatestVersion = CurrentVersion;
                IsUpToDate = true;
                StatusMessage = "已是最新版本";
            }
        }
        catch (InvalidOperationException)
        {
            LatestVersion = "不可用";
            StatusMessage = "当前为非安装版本，无法检查更新";
        }
        catch (Exception ex)
        {
            Log.Error(ex, "检查更新失败");
            LatestVersion = "检查失败";
            StatusMessage = "检查更新失败";
        }
        finally
        {
            IsChecking = false;
            OnPropertyChanged(nameof(HasUpdate));
        }
    }

    [RelayCommand]
    private async Task UpdateAsync()
    {
        if (IsUpdating || _cachedUpdate == null || _activeUpdateService == null) return;
        IsUpdating = true;
        UpdateProgress = 0;
        StatusMessage = "正在下载更新...";

        try
        {
            await _activeUpdateService.DownloadAndApplyAsync(_cachedUpdate, progress =>
            {
                App.MainWindow?.DispatcherQueue.TryEnqueue(() =>
                {
                    UpdateProgress = progress;
                    StatusMessage = $"正在下载更新... {progress}%";
                });
            });
        }
        catch (Exception ex)
        {
            Log.Error(ex, "更新失败");
            StatusMessage = "更新失败";
            IsUpdating = false;
        }
    }
}
