using System.Diagnostics;
using Serilog;

namespace PrismCore.Helpers;

/// <summary>
/// 通过 Windows 任务计划程序实现开机自启动（以最高权限运行，避免 UAC 弹窗）。
/// </summary>
public static class AutoStartHelper
{
    private const string TaskName = "PrismCoreAutoStart";

    /// <summary>注册或删除开机自启动任务。</summary>
    public static void SetAutoStart(bool enable, bool silent)
    {
        try
        {
            if (enable)
            {
                CreateTask(silent);
                Log.Information("开机自启动任务已创建（静默={Silent}）", silent);
            }
            else
            {
                DeleteTask();
                Log.Information("开机自启动任务已删除");
            }
        }
        catch (Exception ex)
        {
            Log.Error(ex, "设置开机自启动失败");
        }
    }

    private static void CreateTask(bool silent)
    {
        // 先删除旧任务（静默参数可能变化）
        DeleteTask();

        var exePath = Environment.ProcessPath!;
        var arguments = silent ? "--silent" : "";

        // 使用 schtasks 创建任务，ONLOGON 触发，以最高权限运行
        // /RL HIGHEST 确保以管理员权限启动，不弹 UAC
        var xmlContent = $@"<?xml version=""1.0"" encoding=""UTF-16""?>
<Task version=""1.2"" xmlns=""http://schemas.microsoft.com/windows/2004/02/mit/task"">
  <RegistrationInfo>
    <Description>PrismCore 开机自启动</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{Environment.UserDomainName}\{Environment.UserName}</UserId>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id=""Author"">
      <UserId>{Environment.UserDomainName}\{Environment.UserName}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>false</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context=""Author"">
    <Exec>
      <Command>""{exePath}""</Command>
      <Arguments>{arguments}</Arguments>
      <WorkingDirectory>{Path.GetDirectoryName(exePath)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>";

        var tempFile = Path.Combine(Path.GetTempPath(), $"{TaskName}.xml");
        try
        {
            File.WriteAllText(tempFile, xmlContent, System.Text.Encoding.Unicode);

            var psi = new ProcessStartInfo
            {
                FileName = "schtasks",
                Arguments = $"/Create /TN \"{TaskName}\" /XML \"{tempFile}\" /F",
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true
            };

            using var proc = Process.Start(psi);
            proc?.WaitForExit(10000);

            if (proc?.ExitCode != 0)
            {
                var err = proc?.StandardError.ReadToEnd();
                Log.Warning("schtasks 创建任务失败（ExitCode={Code}）: {Error}", proc?.ExitCode, err);
            }
            else
            {
                Log.Debug("schtasks 任务创建成功: {TaskName}", TaskName);
            }
        }
        finally
        {
            try { File.Delete(tempFile); } catch { }
        }
    }

    private static void DeleteTask()
    {
        var psi = new ProcessStartInfo
        {
            FileName = "schtasks",
            Arguments = $"/Delete /TN \"{TaskName}\" /F",
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };

        using var proc = Process.Start(psi);
        proc?.WaitForExit(10000);
    }
}
