# PrismCore

[✓ English](./README-en.md) | [简体中文](./README.md)

### Friendly Reminder

Optimization software means optimization, not upgrading ( )
So if your PC is already well-optimized or has few software processes running, the effects may not be very noticeable qwq (please understand~
Also, this project is developed by a middle school student, so maintenance may not always be timely — please understand qwq

---

Windows System Optimization Tool built with WinUI 3, providing six core features: Memory Management, CPU Smart Scheduling, DPC/ISR Latency Diagnostics, Deep Disk Cleanup, Network Repair, and Startup Item Management.

## Features Overview

### Dashboard
Real-time system health score based on CPU, memory, disk, DPC/ISR latency metrics, with one-click smart optimization.

### Memory Optimization
- **Standby List Cleanup** — Release physical memory used by system cache
- **Working Set Trimming** — Shrink memory footprint of background processes
- **Idle Process Paging** — Page long-inactive processes to disk
- **Virtual Memory Management** — Intelligent pagefile status detection with expansion suggestions

### CPU Smart Scheduling (ProBalance)
- EWMA trend prediction + Z-score anomaly detection algorithms
- Automatically lower priority of high-CPU background processes
- Auto-affinity adjustment for hybrid architecture CPUs (big.LITTLE)
- Whitelist protection for critical system processes and audio processes

### DPC/ISR Latency Diagnostics
- PDH system counters for real-time DPC time, interrupt time, queue depth monitoring
- ETW kernel-level event tracing for precise driver problem identification
- Built-in driver database (NVIDIA, AMD, Realtek, etc.) with fix suggestions

### Deep Disk Cleanup
- **Quick Scan** — Temp files, Electron app cache
- **Deep Scan** — MFT fast large file scan (500MB+), system component cleanup, old driver cleanup
- WinSxS component store compression
- Orphaned registry item scan
- Windows Update cache cleanup

### Network Repair Toolbox
- DNS cache flush
- Winsock catalog reset
- TCP/IP protocol stack reset

### Startup Item Management
- Registry Run key enumeration
- Task Scheduler enumeration
- One-click enable/disable startup items

## System Requirements

| Item | Requirement |
|------|-------------|
| OS | Windows 10 1903 (Build 17763) or later |
| Runtime | .NET 10 (self-contained, no separate installation needed) |
| Permissions | **Administrator** (required) |
| Architecture | x64 / x86 / ARM64 |

## Installation & Usage

### Download & Install (Recommended)

1. Go to [GitHub Releases](https://github.com/WSXYT/PrismCore/releases) and download the installer for your architecture:
   - `PrismCore-*-win-x64-Setup.exe` — 64-bit Intel/AMD (most PCs)
   - `PrismCore-*-win-arm64-Setup.exe` — ARM64 (Surface Pro X, Snapdragon laptops, etc.)
   - `PrismCore-*-win-x86-Setup.exe` — 32-bit systems
2. Double-click Setup.exe, accept UAC prompt, installation completes automatically
3. Shortcuts will be created on desktop and Start menu

> The app supports auto-update. Configure update strategy in the "Update" page after installation.

### Uninstall

Windows Settings → Apps → Installed apps → Find PrismCore → Uninstall

### Build from Source

**Prerequisites:**
- Visual Studio 2022 17.12+ or .NET 10 SDK
- Windows App SDK workload

```bash
# Clone repository
git clone <repository-url>
cd PrismCore

# Build
dotnet build PrismCore/PrismCore.csproj -c Release

# Publish MSIX (x64 example)
dotnet publish PrismCore/PrismCore.csproj -c Release -r win-x64
```

## User Guide

### First Launch

1. After launching, go to the **Dashboard** page showing system health score and real-time metrics
2. Click "Smart Optimize" button to perform one-click optimization (cleanup standby list + trim working set)
3. App continuously monitors system in background, auto-optimizes when thresholds exceeded

### Page Navigation

Left sidebar contains five pages:

- **Dashboard** — System overview and one-click optimization
- **Cleanup** — Disk space cleanup (Quick/Deep mode)
- **Optimization** — Memory optimization, startup items, and process management
- **Toolbox** — Network diagnostics and repair tools
- **Update** — Check for updates, one-click upgrade, update channel switching (Stable / Pre-release), auto-update settings
- **Settings** — All configurable parameters

### Disk Cleanup Flow

1. Go to "Cleanup" page
2. Select scan mode (Quick / Deep)
3. Click "Scan" and wait for completion
4. Check items to clean in result list
5. Click "Clean" to execute deletion

### Network Repair

Go to "Toolbox" page, select operation based on network issue:

- **DNS anomalies** → Flush DNS cache
- **Network connection issues** → Reset Winsock
- **Protocol stack corrupted** → Reset TCP/IP (requires restart)

### System Tray

After closing window, app minimizes to system tray. Right-click tray icon to:
- Show main window
- Exit app

## Settings Guide

All settings are saved in real-time and restored after restart. Settings file location:

```
%LocalAppData%\PrismCore\settings.json
```

### Background Auto Optimization

| Setting | Default | Description |
|---------|---------|-------------|
| Enable auto optimization | On | Auto cleanup when memory exceeds threshold |
| Memory threshold | 60% | Memory usage trigger (30-95%) |
| Auto optimization interval | 10 seconds | Background check interval (5-120 sec) |

### Virtual Memory

| Setting | Default | Description |
|---------|---------|-------------|
| Auto pagefile | On | Auto create temp pagefile when memory low |
| Pagefile expansion threshold | 70% | Expand pagefile when commit ratio exceeds (50-90%) |
| Smart suggestions | On | Show suggestions when pagefile needed |

### CPU Smart Scheduling

| Setting | Default | Description |
|---------|---------|-------------|
| Enable smart scheduling | On | Auto-throttle high-CPU background processes |
| System CPU threshold | 45% | Trigger scheduling when system CPU exceeds (30-95%) |
| Process CPU threshold | 8% | Throttle process when CPU exceeds (5-50%) |

### Anomaly Detection

| Setting | Default | Description |
|---------|---------|-------------|
| Enable anomaly detection | On | EWMA + Z-score based CPU spike detection |
| Z-score threshold | 3.0 | Lower = more sensitive, recommended 2.0-5.0 |
| EWMA Alpha | 0.3 | Smoothing factor, higher = more sensitive to recent data (0.05-0.95) |

### Memory Optimization Strategy

| Setting | Default | Description |
|---------|---------|-------------|
| Clean standby list | On | Release memory used by system cache |
| Trim working set | On | Trim memory working set of background processes |
| Smart page idle processes | On | Page long-idle processes to disk |

### System Monitoring

| Setting | Default | Description |
|---------|---------|-------------|
| DPC/ISR latency monitoring | On | Monitor kernel latency, detect driver issues |

### Update Channel

| Setting | Default | Description |
|---------|---------|-------------|
| Update channel | Auto (follows installed version) | Stable: receive official releases only; Pre-release: receive Beta and other pre-release updates |

> The update channel automatically aligns with the currently installed version: if a pre-release version is installed, the pre-release channel is selected by default; otherwise the stable channel is selected. After switching channels, you need to check for updates again.

### Restore Defaults

Click "Restore Default Settings" at bottom of settings page to reset all configs to factory values.

## Technical Architecture

```
PrismCore/
├── Models/          # Business logic layer (memory management, CPU scheduling, cleanup engine, etc.)
├── ViewModels/      # ViewModel layer (data adaptation, command binding)
├── Views/           # UI layer (WinUI 3 XAML pages)
├── Helpers/         # Utilities (constants, P/Invoke, permission management, tray icon)
├── Converters/      # XAML value converters
└── Assets/          # App icons and resources
```

- **Architecture Pattern:** MVVM (Model-View-ViewModel)
- **UI Framework:** WinUI 3 (Windows App SDK)
- **MVVM Framework:** CommunityToolkit.Mvvm
- **Logging:** Serilog (file + debug output)
- **Error Tracking:** Sentry
- **Distribution:** Velopack (auto-update + install/uninstall management)

## Logs

Runtime logs saved to:

```
%LocalAppData%\PrismCore\logs\prismcore-20260224.log
```

Rolled daily, useful for troubleshooting.

## Important Notes

- App requires **Administrator** privileges to run; memory cleanup, driver cleanup, etc. won't work without it
- "Old driver cleanup" and "WinSxS compression" in deep cleanup are irreversible; recommend creating system restore point first
- Registry cleanup auto-backs up to `%LocalAppData%\PrismCore\RegBackup\` before operation
- Resetting TCP/IP protocol stack requires computer restart
- App runs as single instance; multiple windows not supported

## Contributors

Thanks to the following contributors:

<table>
  <tr>
    <td align="center">
      <a href="https://github.com/MacroMeng">
        <img src="https://github.com/MacroMeng.png" width="80" height="80" style="border-radius:50%;" alt="MacroMeng"/><br/>
        <sub><b>MacroMeng</b></sub>
      </a><br/>
      <sub>🎨 Icon Design</sub>
    </td>
    <td align="center">
      <a href="https://github.com/lrsgzs">
        <img src="https://github.com/lrsgzs.png" width="80" height="80" style="border-radius:50%;" alt="lrsgzs"/><br/>
        <sub><b>lrsgzs</b></sub>
      </a><br/>
      <sub>💻 C# Tech Support</sub>
    </td>
  </tr>
</table>

## License

PrismCore - Windows System Optimization Tool
