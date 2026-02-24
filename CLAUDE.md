# PrismCore C# 项目规范

以下所有（除简体中文注释和文档）可根据实际情况优化
## 架构
- MVVM：Model（业务逻辑）→ ViewModel（适配）→ View（UI）
- 命名空间：PrismCore / PrismCore.Models / PrismCore.ViewModels / PrismCore.Views / PrismCore.Helpers / PrismCore.Converters

## 命名约定
- 简体中文注释和文档
- P/Invoke 集中在 `Helpers/NativeApi.cs`，使用 `[LibraryImport]`
- 异步方法后缀 `Async`，返回 `Task` / `Task<T>`
- UI 线程更新用 `DispatcherQueue.TryEnqueue()`

## 关键常量（可以想出更好的方法）
- FreeMemThresholdBytes = 2GB
- StandbyRatioThreshold = 0.25
- CommitRatioWarning = 0.80
- MonitorIntervalMs = 1500
- LargeFileThresholdBytes = 500MB

## 依赖
- Microsoft.WindowsAppSDK
- CommunityToolkit.Mvvm（ObservableObject, RelayCommand, [ObservableProperty]）
- System.Text.Json（.NET 10 内置）

## 目标框架
- net10.0-windows10.0.19041.0

## 项目结构
- Git 根目录：`D:\NAS\bc\PrismCore-C#\PrismCore\PrismCore\`（即 csproj 所在目录）
- `.github/workflows/`、`artifacts/`、`build-pack.sh` 等均放在 Git 根目录下
- 所有文件操作和路径引用以 Git 根目录为基准

## 注意
- 请确保在使用前阅读并理解所有代码，特别是依赖库的使用和配置。
- 对于大型文件处理，建议使用异步操作以避免阻塞主线程。
- 确保代码正常运行，遵循最佳实践，且仔细检查是否存在问题。
- 对话/文档/注释/页面 全部使用简体中文（除非有特殊需求）
- 请尽可能确保依赖等为最新，以避免潜在的兼容性问题和漏洞。
