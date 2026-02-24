using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PrismCore.Models;

namespace PrismCore.ViewModels;

/// <summary>工具箱视图模型（对照 toolbox_vm.py）。</summary>
public partial class ToolboxViewModel : ObservableObject
{
    [ObservableProperty] private string _toolStatus = "";
    [ObservableProperty] private bool _isRunning;

    [RelayCommand]
    private async Task RunDnsAsync()
        => await RunToolAsync("dns", NetworkTools.FlushDns,
            "DNS 缓存已刷新", "DNS 刷新失败");

    [RelayCommand]
    private async Task RunWinsockAsync()
        => await RunToolAsync("winsock", NetworkTools.ResetWinsock,
            "Winsock 已重置（需重启生效）", "Winsock 重置失败");

    [RelayCommand]
    private async Task RunTcpAsync()
        => await RunToolAsync("tcp", NetworkTools.ResetTcpIp,
            "TCP/IP 已重置（需重启生效）", "TCP/IP 重置失败");

    private async Task RunToolAsync(string name, Func<bool> action,
        string successMsg, string failMsg)
    {
        if (IsRunning) return;
        IsRunning = true;
        ToolStatus = $"正在执行 {name}...";
        var ok = await Task.Run(action);
        ToolStatus = ok ? successMsg : failMsg;
        IsRunning = false;
    }
}
