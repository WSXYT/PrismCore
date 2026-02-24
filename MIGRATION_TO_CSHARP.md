# PrismCore 完整实现文档

> 本文档以「原理 + 实现逻辑」为核心，逐文件、逐类、逐方法地详细描述 PrismCore 的全部功能。
> 不包含任何特定语言的代码示例，仅描述算法、数据流、调用关系和实现细节，
> 使读者可以用任意语言从零复刻全部功能。

---

## 一、项目概述

### 1.1 功能定位

PrismCore 是一个 Windows 系统优化工具，需要管理员权限运行。核心功能分为六大模块：

1. **智能内存管理** — 备用列表清理、工作集修剪、动态分页文件创建与扩展、空闲进程内存页出
2. **ProBalance CPU 调度** — 基于 EWMA 趋势预测和 Z-score 异常检测的自动进程优先级与亲和性调度
3. **DPC/ISR 延迟诊断** — PDH 系统级计数器 + ETW 内核级驱动归因的双通道延迟监控
4. **深度磁盘清理** — MFT 快速大文件扫描、Electron 缓存识别、临时文件清理、系统组件清理（WinSxS/驱动商店/注册表孤立项/Windows Update 缓存）
5. **网络修复工具** — DNS 缓存刷新、Winsock 目录重置、TCP/IP 协议栈重置
6. **启动项管理** — 注册表 Run 键和任务计划程序的枚举与启用/禁用

### 1.2 架构模式：MVVM

项目严格遵循 MVVM（Model-View-ViewModel）架构：

- **Model 层**（业务逻辑）：封装所有系统操作、算法、Windows API 调用。不依赖任何 UI 框架。
- **View 层**（界面）：纯 UI 展示，不包含业务逻辑。通过信号/事件与 ViewModel 通信。
- **ViewModel 层**（适配层）：持有 Model 引用，将 Model 的数据转换为 View 可绑定的格式。所有耗时操作在后台线程执行，通过信号/事件通知 View 更新。

目录结构对应关系：
- `src/models/` → Model 层（12 个模块）
- `src/views/` → View 层（6 个页面）
- `src/viewmodels/` → ViewModel 层（4 个视图模型）
- `src/utils/` → 工具层（常量、权限、Windows API 封装）

### 1.3 UI 结构

主窗口采用左侧导航栏 + 右侧内容区的布局，共五个页面：
- **首页（Dashboard）**：系统健康评分、实时 CPU/内存/磁盘/DPC/ISR 指标、智能一键优化按钮、分页文件状态卡片、智能建议卡片
- **清理（Cleaner）**：扫描/清理按钮、快速/深度模式切换、结果表格（复选框+类别+描述+大小）
- **加速（Optimizer）**：内存状态卡片、优化按钮、启动项管理表格（带开关）、进程管理表格（提升/降低按钮）
- **工具箱（Toolbox）**：三个网络工具卡片（DNS/Winsock/TCP）
- **设置（Settings）**：所有可配置参数的开关和数值输入

### 1.4 线程模型

**核心原则：所有耗时操作必须在后台线程执行，禁止阻塞 UI 线程。**

ViewModel 中的每个耗时操作都封装为独立的工作线程类。工作线程通过信号机制将进度和结果回传给 UI 线程。UI 线程收到信号后更新界面。

定时器运行在 UI 线程，但其回调中的耗时操作会委托给后台线程或使用非阻塞 API。

### 1.5 全局设置持久化

使用操作系统原生的持久化机制（Windows 注册表或 INI 文件）存储用户配置。所有设置项通过一个单例类管理，支持实时读写，应用重启后自动恢复。

---

## 二、入口文件

### 2.1 main.py — 程序主入口

程序启动时依次执行三个检查，任一失败则终止：

#### 2.1.1 Sentry 错误上报初始化

在程序最开始初始化 Sentry SDK，配置如下：
- 启用日志集成、追踪、性能分析
- 采样率设为 100%（全量采集）
- **关键过滤逻辑**：注册一个 `before_send` 回调，检查每个即将上报的事件——如果事件没有异常对象（`exc_info` 为空）但有 `logger` 字段，说明这是一条普通日志而非真正的错误，直接丢弃（返回 None）。这样可以避免大量无意义的日志级别事件污染错误追踪。

#### 2.1.2 单实例检测

通过 Windows 命名互斥体（Named Mutex）实现：
- 调用 `kernel32.CreateMutexW`，互斥体名称为 `"Global\\PrismCoreSingleInstance"`
- `Global\\` 前缀确保跨会话（包括远程桌面）全局唯一
- 如果 `GetLastError()` 返回 `ERROR_ALREADY_EXISTS`（错误码 183），说明已有实例在运行
- 此时弹出提示对话框告知用户，然后退出程序

#### 2.1.3 UAC 管理员权限提升

- 调用 `shell32.IsUserAnAdmin()` 检测当前是否以管理员身份运行
- 如果不是管理员：
  - 获取当前 Python 解释器路径和脚本路径
  - 调用 `shell32.ShellExecuteW`，动词为 `"runas"`（触发 UAC 提权对话框）
  - 当前进程退出，等待提权后的新进程接管

三个检查全部通过后，调用应用工厂函数创建 UI 并进入事件循环。

### 2.2 app.py — 应用工厂

负责创建和配置应用实例：

#### 2.2.1 日志配置

- 默认日志级别为 INFO
- 如果命令行参数包含 `--debug`，切换为 DEBUG 级别
- 日志格式：`时间戳 [级别] 模块名: 消息`

#### 2.2.2 High DPI 策略

设置 DPI 缩放策略为 PassThrough 模式，让应用自行处理高 DPI 缩放，避免系统自动缩放导致的模糊问题。

#### 2.2.3 应用创建流程

1. 创建 QApplication 实例
2. 创建 MainWindow 实例
3. 返回 (app, window) 元组供主入口使用
4. 主入口调用 `window.show()` 显示窗口，然后 `app.exec()` 进入事件循环

---

## 三、工具层（Utils）

### 3.1 constants.py — 全局常量定义

所有阈值、列表、路径常量集中定义在此文件，便于统一调整。将常量集中管理而非散落在各模块中，是为了：(1) 调参时只需修改一处；(2) 常量之间的关系一目了然（如 RESTORE_THRESHOLD < SYSTEM_THRESHOLD）；(3) 迁移时可以一次性映射到新语言的配置系统。

#### 内存相关阈值

| 常量名 | 值 | 含义 |
|--------|-----|------|
| FREE_MEM_THRESHOLD_BYTES | 2GB (2×1024³) | 可用物理内存低于此值时触发清理判断 |
| STANDBY_RATIO_THRESHOLD | 0.25 | 备用列表占总内存比例超过此值时需要清理 |
| COMMIT_RATIO_WARNING | 0.80 | 提交费用/提交限制比率超过此值时发出警告 |

**2GB 可用内存阈值**：现代 Windows 系统在可用内存低于 1-2GB 时开始频繁换页，用户会明显感受到卡顿。2GB 是一个保守的预警值——在系统真正陷入换页风暴之前就开始干预。

**25% 备用列表阈值**：备用列表是 Windows 的文件缓存，正常情况下占总内存 20-40% 是健康的。但当可用内存不足时，过大的备用列表意味着有大量内存被缓存占用而非供应用使用。25% 阈值确保只在备用列表确实"过大"时才清理。

**80% 提交比率**：Windows 在约 90% 时弹出系统警告，选择 80% 留出 10% 的干预窗口。

#### 磁盘相关阈值

| 常量名 | 值 | 含义 |
|--------|-----|------|
| DISK_CRITICAL_BYTES | 10GB | C 盘可用空间低于此值时建议启用 CompactOS |
| LARGE_FILE_THRESHOLD_BYTES | 500MB | 大文件扫描的最小阈值 |

#### Electron 缓存识别

两个字符串列表用于识别 Electron 应用的缓存目录：
- **缓存特征目录**：`["Cache", "Code Cache", "GPUCache", "blob_storage", "Service Worker"]` — 这些子目录的存在表明父目录是 Electron 应用数据目录，其中的缓存可以安全删除
- **安全目录（不可删除）**：`["Local Storage", "Session Storage", "Cookies", "Preferences"]` — 这些目录包含用户数据，必须保留

#### 临时文件扩展名

一个集合（set），包含可安全删除的临时文件扩展名：`.tmp`, `.temp`, `.log`, `.old`, `.bak`, `.dmp`, `.etl`, `.chk`

**各扩展名含义**：
- `.tmp` / `.temp`：通用临时文件，由各种程序创建
- `.log`：日志文件，通常可安全删除（当前日志会被重新创建）
- `.old` / `.bak`：备份文件，通常是更新或配置变更前的旧版本
- `.dmp`：内存转储文件（crash dump），调试完成后可删除，单个文件可能数百 MB
- `.etl`：ETW（Event Tracing for Windows）追踪日志，性能分析完成后可删除
- `.chk`：磁盘检查（chkdsk）恢复的文件碎片

**使用 set 而非 list 的原因**：扫描大文件时需要对每个文件检查扩展名是否在集合中，set 的 `in` 操作是 O(1)，而 list 是 O(n)。

#### 受保护进程列表

一个集合，包含绝对不能被修改优先级或工作集的系统关键进程：

- `csrss.exe`：Client/Server Runtime Subsystem，负责控制台窗口管理和线程创建/销毁。降低其优先级可能导致系统挂起
- `smss.exe`：Session Manager Subsystem，系统启动时创建会话，运行时负责环境变量和子系统管理
- `wininit.exe`：Windows 初始化进程，启动 services.exe 和 lsass.exe
- `services.exe`：服务控制管理器（SCM），所有 Windows 服务的父进程
- `lsass.exe`：Local Security Authority，负责用户认证和安全策略。降低优先级会导致登录和权限检查变慢
- `svchost.exe`：服务宿主进程，托管大量系统服务（网络、更新、音频等）。由于无法区分哪个 svchost 实例托管哪些服务，统一保护
- `audiodg.exe`：Audio Device Graph Isolation，Windows 音频引擎的隔离进程
- `System`：NT 内核的用户态代理进程（PID 4）

**注意 audiodg.exe 同时出现在两个列表中**：它既是系统关键进程（不能修改工作集），也是音频进程（不能修改优先级）。两个列表有交集是有意为之——不同的保护场景检查不同的列表。

#### 音频进程列表

一个集合，包含音频相关进程（修改其优先级可能导致音频卡顿）：`audiodg.exe`, `audiosrv.exe`, `spotify.exe`, `music.ui.exe`, `foobar2000.exe`, `aimp.exe`, `vlc.exe`, `wmplayer.exe`

#### 监控与调度参数

| 常量名 | 值 | 含义 |
|--------|-----|------|
| MONITOR_INTERVAL_MS | 1500 | 首页实时监控刷新间隔（毫秒） |
| PROBALANCE_SYSTEM_THRESHOLD | 60 | 系统总 CPU 使用率超过此百分比时 ProBalance 开始扫描进程 |
| PROBALANCE_PROCESS_THRESHOLD | 10 | 单个进程 CPU 使用率超过此百分比时可能被约束 |
| PROBALANCE_SUSTAIN_SECONDS | 2 | 进程必须持续超过阈值至少 2 秒才会被约束（防止瞬时尖峰误判） |
| PROBALANCE_MIN_CONSTRAIN_SECONDS | 3 | 约束后至少保持 3 秒才能还原（防止优先级抖动） |
| PROBALANCE_RESTORE_THRESHOLD | 40 | 系统 CPU 降到此百分比以下时还原所有约束 |
| PROBALANCE_SAMPLE_INTERVAL | 1 | ProBalance 采样间隔（秒） |
| PAGE_FAULT_DELTA_THRESHOLD | 50000 | 页错误增量超过此值表示系统正在频繁换页 |

**参数之间的关系**：
- `SYSTEM_THRESHOLD(60) > RESTORE_THRESHOLD(40)`：形成 20% 的滞后区间，防止在边界值附近反复激活/还原
- `SUSTAIN_SECONDS(2) < MIN_CONSTRAIN_SECONDS(3)`：约束的最短保持时间大于触发所需的持续时间，确保约束有足够时间产生效果
- `SAMPLE_INTERVAL(1s)` 与 `SUSTAIN_SECONDS(2s)` 的关系：每秒采样一次，需要连续 2 次采样超阈值才触发约束，这意味着进程必须持续高负载至少 2 秒

**PAGE_FAULT_DELTA_THRESHOLD = 50000 的含义**：在 1.5 秒的采样间隔内，如果全系统页错误增量超过 50000 次，说明大量内存页正在被换入换出。正常系统的页错误增量通常在几千以内（大部分是软页错误——从备用列表恢复），50000 次意味着存在严重的内存压力。

#### 注册表备份目录

位于用户本地应用数据目录下的 `PrismCore/RegBackup`，用于在删除注册表项前备份。

### 3.2 privilege.py — 权限管理

提供两个功能：检测管理员身份和启用 Windows 特权令牌。

#### 3.2.1 is_admin()

直接调用 `shell32.IsUserAnAdmin()`，返回布尔值。这是最简单可靠的管理员检测方式。

#### 3.2.2 enable_privilege(privilege_name)

**用途**：某些 Windows API（如清理备用列表、创建分页文件、ETW 内核追踪）需要进程令牌中启用特定特权才能调用。即使以管理员身份运行，这些特权默认也是禁用状态，需要显式启用。

**实现步骤**：

1. **打开进程令牌**：调用 `advapi32.OpenProcessToken`，传入当前进程句柄（`kernel32.GetCurrentProcess()`）和访问权限 `TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY`（0x0020 | 0x0008）

2. **查找特权 LUID**：调用 `advapi32.LookupPrivilegeValue`，传入特权名称字符串（如 `"SeProfileSingleProcessPrivilege"`），获取该特权在本机上的 LUID（本地唯一标识符）

3. **调整令牌特权**：构造 `TOKEN_PRIVILEGES` 结构体（包含 1 个 `LUID_AND_ATTRIBUTES`，属性设为 `SE_PRIVILEGE_ENABLED = 0x00000002`），调用 `advapi32.AdjustTokenPrivileges`

4. **验证结果**：即使 `AdjustTokenPrivileges` 返回成功，也需要检查 `GetLastError()` 是否为 `ERROR_NOT_ALL_ASSIGNED`（1300），如果是则表示特权未能成功启用

5. **清理**：关闭令牌句柄

**常用特权名称**：
- `"SeProfileSingleProcessPrivilege"` — 清理内存备用列表所需
- `"SeCreatePagefilePrivilege"` — 动态创建分页文件所需
- `"SeSystemProfilePrivilege"` — ETW 内核追踪所需

### 3.3 winapi.py — Windows API 封装层

这是项目最核心的底层模块，封装了 11 个 Windows API 函数。所有系统级操作都通过此模块间接调用。

#### 3.3.1 get_memory_status() → MemoryStatus

**返回数据结构 MemoryStatus**（NamedTuple，不可变）：
- `total`：物理内存总量（字节）
- `available`：可用物理内存（字节）
- `used`：已用内存 = total - available
- `percent`：使用率百分比，保留一位小数
- `commit_total`：当前已提交的虚拟内存（字节）
- `commit_limit`：提交限制（物理内存 + 所有分页文件的总和）

**Windows 内存页面状态模型（理解本项目所有内存操作的基础）**：

Windows 内存管理器将物理内存页面分为以下状态：

1. **Active（活跃）**：正在被进程使用的页面，属于某个进程的工作集（Working Set）。这些页面有明确的所有者进程。
2. **Standby（备用）**：曾经属于某个进程但已被移出工作集的页面。页面内容仍然保留在物理内存中，如果原进程再次访问可以零成本恢复（软页错误）。备用列表按优先级 0-7 排列，优先回收低优先级页面。
3. **Modified（已修改）**：与 Standby 类似，但页面内容已被修改尚未写回磁盘。Modified Page Writer 后台线程会将这些页面写入分页文件后转为 Standby。
4. **Free（空闲）**：完全未使用的页面，可以立即分配给任何进程。
5. **Zeroed（已清零）**：Free 页面被零页线程清零后的状态，可以直接分配给用户模式进程（安全要求：防止进程读到其他进程的残留数据）。

**关键概念**：Windows 报告的 `Available`（可用内存）= Free + Zeroed + Standby。也就是说，备用列表中的页面虽然有内容，但 Windows 认为它们"可用"——因为在需要时可以立即回收。但当备用列表过大时，新的内存分配需要先回收备用页（触发软页错误），这会增加延迟。这就是本项目清理备用列表的核心动机。

**MEMORYSTATUSEX 结构体内存布局**（总大小 64 字节）：

| 偏移 | 字段名 | 类型 | 大小 | 说明 |
|------|--------|------|------|------|
| 0 | dwLength | DWORD | 4 | **必须在调用前设为 64**，否则 API 静默失败返回全零 |
| 4 | dwMemoryLoad | DWORD | 4 | 内存使用率百分比（0-100），本项目未使用此字段 |
| 8 | ullTotalPhys | ULONGLONG | 8 | 物理内存总量 |
| 16 | ullAvailPhys | ULONGLONG | 8 | 可用物理内存（Free + Zeroed + Standby） |
| 24 | ullTotalPageFile | ULONGLONG | 8 | **提交限制**（物理内存 + 所有分页文件总和）。字段名极具误导性——它不是"分页文件总大小"，而是整个系统的虚拟内存提交上限 |
| 32 | ullAvailPageFile | ULONGLONG | 8 | 提交限制中尚未使用的部分 |
| 40 | ullTotalVirtual | ULONGLONG | 8 | 用户模式虚拟地址空间总量（通常 128TB），本项目未使用 |
| 48 | ullAvailVirtual | ULONGLONG | 8 | 用户模式可用虚拟地址空间，本项目未使用 |
| 56 | ullAvailExtendedVirtual | ULONGLONG | 8 | 保留字段，始终为 0 |

**提交费用（Commit Charge）的计算**：
- `commit_total = ullTotalPageFile - ullAvailPageFile`
- 含义：所有进程已承诺使用的虚拟内存总量。当进程调用 VirtualAlloc(MEM_COMMIT) 时，系统从提交限制中扣除对应大小。即使这些页面尚未实际写入（没有物理内存支撑），提交费用也会增加。
- 当 `commit_total` 接近 `commit_limit` 时，新的内存分配会失败，应用程序会崩溃。这就是本项目动态创建分页文件的核心动机——扩大提交限制。

**used 的计算**：`used = total - available`。注意这里的 `used` 包含了 Modified 页面但不包含 Standby 页面（因为 Standby 被算在 available 里）。

**percent 的计算**：`round(used / total * 100, 1)`，保留一位小数。当 total 为 0 时返回 0.0（防除零）。

**调用约定**：使用 `ctypes.windll.kernel32`（stdcall 调用约定），传入结构体的引用（`ctypes.byref(ms)`）。

#### 3.3.2 get_disk_free(drive) → int

调用 `kernel32.GetDiskFreeSpaceExW`，返回指定驱动器的可用字节数。默认参数为 `"C:\\"`。

#### 3.3.3 purge_standby_list() → bool

**这是内存优化的核心 API**，用于清空 Windows 内存管理器的备用列表（Standby List）。

**为什么要清理备用列表**：

备用列表是 Windows 的"投机性缓存"——系统猜测这些页面可能很快被再次访问，所以保留在物理内存中。这在大多数场景下是有益的（减少磁盘 I/O）。但在以下场景中会成为问题：

- **游戏/大型应用启动时**：需要大量连续物理内存，但备用列表占据了大部分空间。虽然系统可以回收备用页，但回收过程本身有开销（需要从备用列表中摘除页面、更新 PFN 数据库、可能需要清零），导致启动卡顿。
- **内存紧张时**：当 Free+Zeroed 页面耗尽，每次新分配都需要先回收一个备用页，触发"软页错误"（Soft Page Fault）。虽然比硬页错误（从磁盘读取）快得多，但在高频分配场景下累积延迟仍然可观。
- **备用列表过大时**：备用列表可能占据 60-80% 的物理内存，导致系统报告"可用内存充足"但实际上新分配响应变慢。

**NtSetSystemInformation 调用细节**：

这是一个未文档化的 ntdll.dll 导出函数（Windows 内部 API），不在官方 SDK 头文件中声明，但其行为稳定且被广泛使用（RAMMap、Process Lasso 等工具都使用相同方法）。

函数签名：`NTSTATUS NtSetSystemInformation(ULONG SystemInformationClass, PVOID SystemInformation, ULONG SystemInformationLength)`

**参数详解**：
- `SystemInformationClass = 80`：这个值对应 `SystemMemoryListInformation` 枚举。值 80 是通过逆向工程确定的，在 Windows Vista 到 Windows 11 中保持不变。
- `SystemInformation`：指向一个 4 字节整数的指针，该整数的值决定执行什么操作：
  - `1` = MemoryEmptyWorkingSets（清空所有进程工作集）
  - `2` = MemoryFlushModifiedList（刷新已修改列表到磁盘）
  - `3` = MemoryPurgeStandbyList（清空低优先级备用页）
  - **`4` = MemoryPurgeLowPriorityStandbyList**（本项目使用此值——清空所有备用页，包括高优先级的）
- `SystemInformationLength = 4`：即 sizeof(ULONG)

**特权要求**：调用前必须在进程令牌中启用 `SeProfileSingleProcessPrivilege`（"配置文件单一进程"特权）。即使以管理员身份运行，此特权默认也是禁用状态。如果未启用，NtSetSystemInformation 返回 `STATUS_PRIVILEGE_NOT_HELD`（0xC0000061）。

**NTSTATUS 返回值**：0（STATUS_SUCCESS）表示成功。非零值表示失败，常见错误码：
- `0xC0000061`：特权未持有
- `0xC0000022`：访问被拒绝（非管理员）
- `0xC000000D`：参数无效

**实现中的结构体封装**：源码中定义了一个只有一个 `c_int` 字段的 `CMD` 结构体来传递命令值。这是因为 ctypes 需要一个可取地址的对象（`ctypes.byref()` 不能直接作用于 Python int）。也可以用 `ctypes.c_int(4)` 配合 `ctypes.byref()` 达到相同效果。

#### 3.3.4 empty_working_set(pid) → bool

**用途**：将指定进程的工作集（当前驻留在物理内存中的页面）释放回操作系统。

**工作集（Working Set）的操作系统原理**：

每个进程都有一个"工作集"——当前映射到物理内存的虚拟页面集合。工作集有最小值和最大值（由系统动态调整）。当系统内存紧张时，内存管理器的"工作集修剪器"（Working Set Trimmer）会自动缩减进程的工作集。`EmptyWorkingSet` 是手动触发这个过程的 API。

**被释放的页面去向**：
- 如果页面内容未被修改（Clean Page）→ 进入 Standby 列表（可以零成本恢复）
- 如果页面内容已被修改（Dirty Page）→ 进入 Modified 列表（等待 Modified Page Writer 写入分页文件后转为 Standby）
- 页面并未被销毁——如果进程再次访问这些页面，会触发软页错误（Soft Page Fault），系统从 Standby 列表中恢复页面，代价很低（微秒级）
- 只有当 Standby 页面被其他进程的新分配回收后，再次访问才会触发硬页错误（Hard Page Fault），需要从磁盘分页文件读取（毫秒级）

**这就是为什么 EmptyWorkingSet 对空闲进程是安全的**：空闲进程短期内不会再访问这些页面，所以页面会在 Standby 列表中逐渐被回收，物理内存被释放给活跃进程使用。

**64 位句柄截断问题**：源码中显式声明了 `OpenProcess` 和 `CloseHandle` 的参数类型（`argtypes`）和返回类型（`restype`）。这是因为 ctypes 默认将返回值视为 `c_int`（32 位），但在 64 位 Windows 上，HANDLE 是 64 位指针。如果不声明 `restype = wintypes.HANDLE`，高 32 位会被截断，导致句柄无效。这是 ctypes 调用 Windows API 时最常见的陷阱。

**实现步骤**：
1. 声明 `OpenProcess`、`CloseHandle`、`EmptyWorkingSet` 的参数和返回类型（防止 64 位截断）
2. 调用 `kernel32.OpenProcess`，传入 `PROCESS_SET_QUOTA | PROCESS_QUERY_INFORMATION`（0x0100 | 0x0400）和目标 PID
   - `PROCESS_SET_QUOTA`（0x0100）：EmptyWorkingSet 内部需要修改进程的工作集配额
   - `PROCESS_QUERY_INFORMATION`（0x0400）：需要查询进程信息以确定工作集范围
3. 如果句柄为 0 或 NULL（权限不足或进程不存在），返回 False
4. 调用 `psapi.EmptyWorkingSet(handle)`——这个函数等价于调用 `SetProcessWorkingSetSizeEx(handle, -1, -1)`，即将工作集最小值和最大值都设为 -1，告诉系统"尽可能多地释放此进程的物理页面"
5. 关闭句柄（**必须关闭**，否则句柄泄漏会导致系统资源耗尽），返回结果

#### 3.3.5 create_restore_point(description) → bool

**用途**：在执行系统级清理（驱动删除、注册表修改）前创建系统还原点，允许用户回滚。

**为什么需要还原点**：系统清理操作中有两类不可逆操作——删除旧驱动包（`pnputil /delete-driver`）和删除注册表孤立项（`reg delete`）。如果误删了仍在使用的驱动或注册表项，可能导致设备失灵或软件无法启动。系统还原点是 Windows 内置的快照机制，记录注册表、系统文件、驱动的状态，允许用户通过"系统还原"回滚到创建还原点时的状态。

**实现原理**：
调用 `srclient.dll` 的 `SRSetRestorePointW`。`srclient.dll` 是系统还原客户端库，封装了与系统还原服务（`srservice.dll`，运行在 `svchost.exe` 中）的 RPC 通信。

**RESTOREPTINFOW 结构体**：
- `dwEventType = 100`（BEGIN_SYSTEM_CHANGE）：表示"开始一次系统变更"。还有 `END_SYSTEM_CHANGE`（101）用于标记变更结束，但本项目只创建开始标记——如果后续操作失败，Windows 会自动将未关闭的还原点视为有效回滚点
- `dwRestorePtType = 0`（APPLICATION_INSTALL）：还原点类型。虽然名为"应用安装"，但这是第三方程序创建还原点时最常用的类型。其他类型如 `DEVICE_DRIVER_INSTALL`（10）、`MODIFY_SETTINGS`（12）等主要由 Windows 自身使用
- `szDescription`：还原点描述，固定 256 个 `wchar` 的数组（非指针），超长截断到 255 字符（保留终止符空间）
- `llSequenceNumber`：输入时设为 0，API 返回后填入分配的序列号

**为什么用 `WinDLL("srclient.dll")` 而非 `windll.srclient`**：使用 `use_last_error=True` 参数可以在调用失败时通过 `ctypes.get_last_error()` 获取错误码。外层用 `try/except OSError` 捕获 DLL 加载失败（某些精简版 Windows 可能移除了系统还原功能）。

返回的 `STATEMGRSTATUS` 结构体中 `nStatus` 为 0 表示成功。

#### 3.3.6 empty_recycle_bin() → bool

调用 `shell32.SHEmptyRecycleBinW(hwnd, pszRootPath, dwFlags)`。

**参数设计**：
- `hwnd = None`：父窗口句柄。传 None 表示无父窗口，任何可能的错误对话框不会附着到特定窗口
- `pszRootPath = None`：驱动器根路径。传 None 表示清空**所有驱动器**的回收站（C:\、D:\ 等全部清空）。如果只想清空特定驱动器，传入如 `"C:\\"` 即可
- `dwFlags = 0x07`：三个标志位的组合：
  - `SHERB_NOCONFIRMATION`（0x01）：不弹出"确定要清空回收站吗？"确认对话框
  - `SHERB_NOPROGRESSUI`（0x02）：不显示删除进度条窗口
  - `SHERB_NOSOUND`（0x04）：不播放清空回收站的音效
  - 三者合并为 0x07，实现完全静默清空。这对于后台自动清理至关重要——如果弹出对话框，会阻塞调用线程直到用户点击

**返回值**：`SHEmptyRecycleBinW` 返回 `HRESULT`，0（`S_OK`）表示成功。回收站已空时返回 `S_OK`（幂等操作）。

#### 3.3.7 query_recycle_bin_size() → int

调用 `shell32.SHQueryRecycleBinW(pszRootPath, pSHQueryRBInfo)`。

**SHQUERYRBINFO 结构体**：

| 偏移 | 字段 | 类型 | 说明 |
|------|------|------|------|
| 0 | cbSize | DWORD | 结构体大小，**必须在调用前设置** |
| 4 | i64Size | INT64 | 回收站中所有项目的总大小（字节） |
| 12 | i64NumItems | INT64 | 回收站中的项目数量 |

**cbSize 预设的必要性**：这是 Windows Shell API 的版本兼容模式。API 通过 `cbSize` 判断调用者使用的结构体版本——如果未来 Windows 扩展了此结构体（增加新字段），旧程序传入的 `cbSize` 较小，API 就知道不应写入新字段区域，避免缓冲区溢出。不设置 `cbSize` 会导致 API 返回错误。

**pszRootPath = None**：与 `empty_recycle_bin` 相同，None 表示查询所有驱动器回收站的总大小。

#### 3.3.8 get_foreground_window_pid() → int

两步调用：
1. `user32.GetForegroundWindow()` → 获取当前前台窗口句柄（HWND）
2. `user32.GetWindowThreadProcessId(hwnd, &pid)` → 从窗口句柄获取所属进程 PID

**窗口与进程的关系**：Windows 中每个窗口由一个线程创建和拥有（称为"窗口线程"），该线程属于某个进程。`GetWindowThreadProcessId` 同时返回线程 ID（函数返回值）和进程 ID（通过输出参数）。本项目只需要 PID，所以忽略返回值。

**"前台窗口"的定义**：前台窗口是当前接收键盘输入的窗口（拥有输入焦点的顶层窗口）。当用户切换应用（Alt+Tab、点击任务栏）时，前台窗口随之改变。如果没有窗口拥有焦点（如用户点击了桌面），`GetForegroundWindow` 返回 NULL（0），此时 `GetWindowThreadProcessId` 会将 pid 设为 0。

**使用场景**：
- ProBalance 白名单保护：前台进程不应被降低优先级或绑定到 E 核心，因为用户正在与之交互
- 内存修剪时跳过前台进程：避免修剪用户正在使用的应用导致界面卡顿（页面被换出后再访问需要从磁盘读回）

#### 3.3.9 is_foreground_fullscreen() → bool

**用途**：检测当前前台窗口是否为全屏应用（游戏、视频播放器等）。全屏时触发压力模式清理。

**实现原理**：
1. 获取前台窗口句柄。如果为 NULL（无前台窗口），直接返回 False
2. 调用 `user32.GetWindowRect(hwnd, &rect)` 获取窗口在屏幕坐标系中的矩形 (left, top, right, bottom)
3. 调用 `user32.GetSystemMetrics(SM_CXSCREEN)` 和 `GetSystemMetrics(SM_CYSCREEN)` 获取**主显示器**的分辨率
4. 判断条件：`left ≤ 0 且 top ≤ 0 且 right ≥ 屏幕宽 且 bottom ≥ 屏幕高`

**为什么用 ≤ 和 ≥ 而非 ==**：某些全屏应用（特别是独占全屏游戏）的窗口矩形可能略微超出屏幕边界（负坐标或超出分辨率），这是因为窗口边框（即使不可见）仍然占据空间。使用不等式比较可以容忍这种偏差。

**此方法的局限性**：
- **仅检测主显示器**：`GetSystemMetrics(SM_CXSCREEN/SM_CYSCREEN)` 返回的是主显示器分辨率。如果全屏应用运行在副显示器上，此方法会误判为非全屏。更精确的做法是用 `MonitorFromWindow` 获取窗口所在显示器，再用 `GetMonitorInfo` 获取该显示器的分辨率
- **无法区分"最大化"和"全屏"**：最大化窗口也覆盖整个屏幕（任务栏除外），但 `GetWindowRect` 返回的矩形可能包含任务栏区域（取决于窗口样式）。不过对于本项目的用途（判断用户是否在进行沉浸式活动），最大化窗口也应该被保护，所以这个"误判"实际上是合理的

**使用场景**：当检测到全屏应用时，自动优化器会更积极地释放内存（避免游戏/视频因内存不足而卡顿），同时 ProBalance 会确保全屏进程不被约束。

#### 3.3.10 nt_create_paging_file(path, min_size, max_size) → bool

**这是最关键的 API 之一**，可以在不重启系统的情况下立即创建或扩展分页文件。

**为什么需要这个 API**：

Windows 提供两种方式管理分页文件：
1. **wmic / 注册表方式**：修改 `HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management\PagingFiles` 注册表值。这种方式**需要重启才能生效**，因为分页文件在系统启动早期由 Session Manager（smss.exe）创建。
2. **NtCreatePagingFile 方式**：直接调用内核 API 在运行时创建分页文件，**立即生效**，无需重启。系统的提交限制（Commit Limit）会立即增加。

本项目优先使用方式 2，失败时回退到方式 1。

**NT 路径格式**：

Windows 内核使用的路径格式与用户模式不同。用户模式路径 `D:\pagefile.sys` 对应的 NT 路径是 `\??\D:\pagefile.sys`。`\??` 是 NT 对象命名空间中的符号链接目录，将盘符映射到实际的设备路径（如 `\Device\HarddiskVolume3`）。NtCreatePagingFile 要求使用 NT 路径格式。

**UNICODE_STRING 结构体**（NT 内核字符串的标准表示）：

| 偏移 | 字段 | 类型 | 说明 |
|------|------|------|------|
| 0 | Length | USHORT (2字节) | 字符串的**字节**长度（不含终止符），= 字符数 × 2 |
| 2 | MaximumLength | USHORT (2字节) | 缓冲区最大字节长度，= Length + 2（含终止符空间） |
| 4/8 | Buffer | 指针 (4/8字节) | 指向 UTF-16LE 编码的字符串缓冲区 |

**注意**：在 Python ctypes 中，`c_wchar_p` 类型会自动管理字符串内存（Python 字符串对象的生命周期内有效），所以不需要手动分配/释放非托管内存。但在 C# 中使用 P/Invoke 时，如果用 `Marshal.StringToHGlobalUni` 分配内存，则必须在调用后用 `Marshal.FreeHGlobal` 释放。

**LARGE_INTEGER 结构体**：用于传递 64 位整数的大小参数。内部只有一个 `QuadPart`（int64）字段。min_size 和 max_size 都以**字节**为单位。

**NtCreatePagingFile 函数签名**：
`NTSTATUS NtCreatePagingFile(PUNICODE_STRING PageFileName, PLARGE_INTEGER MinimumSize, PLARGE_INTEGER MaximumSize, ULONG Priority)`

- `Priority`：传 0 即可（默认优先级）
- 返回 `STATUS_SUCCESS`（0）表示成功
- 常见失败：`STATUS_PRIVILEGE_NOT_HELD`（未启用 SeCreatePagefilePrivilege）、`STATUS_OBJECT_NAME_COLLISION`（文件已存在——此时实际上是扩展操作，如果新大小 > 旧大小则扩展成功）

**运行时创建的分页文件的生命周期**：通过 NtCreatePagingFile 创建的分页文件在系统运行期间持续有效，但**无法在运行时删除**（文件被内核锁定）。系统重启后，如果注册表中没有对应的 PagingFiles 条目，该分页文件不会被重新创建，磁盘上的文件可以被删除。

#### 3.3.11 get_system_page_fault_count() → int

通过 `psutil.swap_memory()` 获取系统级换页活动指标，返回 `sin + sout`（换入字节数 + 换出字节数）的累计值。

**页错误的两种类型**：
- **软页错误（Soft Page Fault）**：访问的页面不在进程工作集中，但仍在物理内存的备用列表中。内核只需更新页表映射，不涉及磁盘 I/O，耗时约 1-10μs。软页错误是正常现象，频繁发生也不影响性能
- **硬页错误（Hard Page Fault）**：访问的页面已被换出到分页文件（或尚未从磁盘加载），需要从磁盘读取。耗时约 1-10ms（HDD）或 0.1-1ms（SSD），比软页错误慢 100-1000 倍。大量硬页错误是系统卡顿的主要原因之一

**psutil.swap_memory() 在 Windows 上的实现**：调用 `GetPerformanceInfo` API 获取系统性能信息。`sin`（swap in）和 `sout`（swap out）在 Windows 上分别对应从分页文件读入和写出的字节数，反映的是**硬页错误**活动。

**使用场景**：此值用于 auto_optimizer 的压力检测。当 `sin + sout` 的增量（两次采样的差值）超过 `PAGE_FAULT_DELTA_THRESHOLD`（50000）时，说明系统正在频繁进行磁盘换页，内存压力较大，应触发主动优化。

#### 3.3.12 measure_responsiveness(timeout_ms=5000) → float

**用途**：测量系统 UI 响应延迟，用于 ProBalance 反馈闭环。

**为什么这个方法能衡量系统卡顿程度**：

Windows 的 GUI 子系统基于消息循环（Message Loop）。每个窗口都有一个消息队列，窗口过程（WndProc）从队列中取出消息并处理。`SendMessage` 是同步调用——它将消息投递到目标窗口的队列，然后**阻塞等待**目标窗口处理完毕并返回。

如果目标窗口的 UI 线程正忙（比如在执行耗时计算、等待 I/O、或者被高优先级线程抢占 CPU），消息就会在队列中排队等待。`SendMessageTimeout` 允许设置超时，避免无限等待。

`HWND_BROADCAST`（0xFFFF）会将消息广播给所有顶层窗口。`WM_NULL`（0x0000）是一个空消息，窗口过程收到后直接返回 0，不执行任何操作。所以这个调用的总耗时 = 所有顶层窗口中**最慢的那个**处理 WM_NULL 的时间。

**这个耗时反映了什么**：
- 10-50ms：系统正常，所有窗口的 UI 线程都在及时处理消息
- 100-200ms：有窗口的 UI 线程出现短暂阻塞，用户可能感知到轻微卡顿
- 200ms+：系统明显卡顿，可能有进程霸占 CPU 导致其他窗口的 UI 线程得不到调度
- 超时（5000ms）：有窗口完全挂起（Not Responding 状态）

**SMTO_ABORTIFHUNG（0x0002）标志**：如果目标窗口被系统标记为"挂起"（5 秒未处理消息），则跳过该窗口不等待。这防止了一个挂起的窗口导致整个测量超时。

**计时方式**：使用 `time.perf_counter()`（高精度性能计数器，基于 QPC），精度通常在微秒级。返回值保留两位小数（毫秒）。

#### 3.3.13 get_cpu_topology() → CpuTopology

**返回数据结构 CpuTopology**：
- `p_cores`：P-Core（性能核心）的逻辑处理器索引列表
- `e_cores`：E-Core（能效核心）的逻辑处理器索引列表
- `is_hybrid`：是否为混合架构（同时存在 P-Core 和 E-Core）

**实现原理**：
调用 `kernel32.GetSystemCpuSetInformation`，这是 Windows 10+ 提供的 API，能精确识别 Intel 12 代及以后的混合架构。

**两次调用模式**：
1. 第一次调用传入缓冲区大小为 0，获取所需缓冲区大小
2. 分配缓冲区后第二次调用获取实际数据

**数据解析**：
缓冲区包含多个 `SYSTEM_CPU_SET_INFORMATION` 结构体，每个对应一个逻辑处理器。关键字段：
- 偏移 10 字节处：`LogicalProcessorIndex`（逻辑处理器编号，uint8）
- 偏移 14 字节处：`EfficiencyClass`（能效等级，uint8）
  - `EfficiencyClass = 0` → P-Core（性能核心）
  - `EfficiencyClass > 0` → E-Core（能效核心）

**SYSTEM_CPU_SET_INFORMATION 完整内存布局**（每个结构体 32 字节）：

| 偏移 | 字段 | 类型 | 说明 |
|------|------|------|------|
| 0 | Size | DWORD | 本结构体大小（用于遍历时步进） |
| 4 | Type | DWORD | 类型，0 = CpuSetInformation |
| 8 | Id | DWORD | CPU Set ID |
| 12 | Group | WORD | 处理器组号（多于 64 核时使用） |
| 14 | LogicalProcessorIndex | BYTE | **逻辑处理器编号**（0 起始） |
| 15 | CoreIndex | BYTE | 物理核心编号 |
| 16 | LastLevelCacheIndex | BYTE | 末级缓存编号 |
| 17 | NumaNodeIndex | BYTE | NUMA 节点编号 |
| 18 | EfficiencyClass | BYTE | **能效等级**：0=P-Core, >0=E-Core |
| 19 | AllFlags | BYTE | 标志位（Parked、Allocated 等） |
| 20 | Reserved | DWORD | 保留 |
| 24 | AllocationTag | UINT64 | 分配标签 |

**遍历方式**：从缓冲区偏移 0 开始，每次步进 `info.Size` 字节（而非固定 32 字节），因为未来 Windows 版本可能扩展此结构体。当 `info.Size == 0` 或偏移超出缓冲区长度时停止。

**Intel 混合架构背景**：Intel 第 12 代（Alder Lake）起引入了大小核混合架构。P-Core（Performance Core，Golden Cove 微架构）支持超线程，每个物理核心有 2 个逻辑处理器；E-Core（Efficiency Core，Gracemont 微架构）不支持超线程，每个物理核心只有 1 个逻辑处理器。Windows 通过 `EfficiencyClass` 字段区分两者，调度器会优先将前台任务分配到 P-Core。

**回退方案**（`_fallback_cpu_topology`）：如果 `GetSystemCpuSetInformation` 不可用（Windows 8.1 及更早版本）或调用失败：
- 获取逻辑核心数（`logical`）和物理核心数（`physical`）
- 如果 `logical > physical × 1.5`：启发式判断为混合架构，前 `physical` 个逻辑处理器视为 P-Core，其余视为 E-Core
- 否则：所有逻辑处理器视为 P-Core，E-Core 列表为空
- **这个启发式方法不完全准确**（例如纯超线程 CPU 的 logical = physical × 2 也会被误判），但在无法获取精确拓扑时是合理的降级

#### 3.3.14 enum_kernel_modules() → List[(base_address, name)]

**用途**：枚举所有已加载的内核模块（驱动程序），用于 ETW DPC/ISR 回调地址到驱动名的映射。

**内核地址空间背景**：Windows 内核模块（.sys 驱动文件）加载到内核地址空间的高地址区域（x64 上通常是 `0xFFFFF800'00000000` 以上）。每个模块占据一段连续的地址范围，起始地址就是"基地址"。DPC/ISR 的回调函数地址一定落在某个内核模块的地址范围内。

**两次调用模式**（Windows API 的常见模式）：
1. 第一次调用 `EnumDeviceDrivers(NULL, 0, &needed)`：传入空缓冲区，API 返回所需的缓冲区大小（字节数）到 `needed`
2. 计算模块数量：`count = needed / sizeof(void*)`（每个基地址是一个指针大小）
3. 分配 `void*` 数组：`arr = new void*[count]`
4. 第二次调用 `EnumDeviceDrivers(arr, needed, &needed)`：填充基地址数组

**64 位指针声明**：源码中显式声明 `GetDeviceDriverBaseNameW` 的第一个参数为 `c_void_p`（而非默认的 `c_int`），防止 64 位内核地址被截断为 32 位。

**排序的目的**：返回列表按基地址升序排序，是为了后续在 `_DriverMapper.lookup()` 中使用**二分查找**。二分查找的原理：给定一个回调地址 `addr`，使用 `bisect_right(bases, addr) - 1` 找到最后一个基地址 ≤ addr 的模块——该模块就是回调函数所属的驱动。这比线性搜索快得多（O(log n) vs O(n)），在每秒可能处理数千个 DPC/ISR 事件的场景下至关重要。

---

## 四、Model 层 — 基础模块

### 4.1 settings.py — 全局设置管理

#### 4.1.1 设计模式

采用**单例模式**，整个应用只有一个设置实例。首次创建时初始化底层持久化存储（QSettings，对应 Windows 注册表中 `HKCU\Software\PrismCore\PrismCore`）。后续所有 `AppSettings()` 调用返回同一实例。

**单例实现方式**：通过重写 `__new__` 方法，在类变量中缓存唯一实例。首次调用时创建实例并初始化 QSettings，后续调用直接返回缓存的实例。这比模块级全局变量更优雅——延迟初始化（第一次使用时才创建），且可以被子类化。

**为什么用注册表而非配置文件**：QSettings 在 Windows 上默认使用注册表（`HKCU\Software\组织名\应用名`），读写速度比文件 I/O 快（注册表常驻内存），且不存在文件锁定、编码、换行符等问题。缺点是用户不容易手动编辑，但对于 GUI 应用这不是问题。

#### 4.1.2 持久化机制

每个设置项都是一个属性（property），getter 从持久化存储读取（带默认值和类型转换），setter 立即写入持久化存储。无需手动保存，修改即生效。

**类型转换的必要性**：QSettings 从注册表读取的值都是字符串。布尔值 `True` 存储为字符串 `"true"`，读取时需要手动转换（`value.lower() in ("true", "1")`）。整数和浮点数同理需要 `int()` / `float()` 转换。每个 property 的 getter 都包含这个转换逻辑和默认值回退。

**即时写入的设计考量**：不使用"修改后统一保存"模式，因为：(1) 注册表写入是原子操作，不存在"写到一半崩溃"的风险；(2) 设置变更需要立即被其他模块感知（如 ProBalance 的 tick() 每秒读取最新设置）；(3) 避免用户忘记保存导致设置丢失。

#### 4.1.3 完整设置项清单

**后台自动优化组**（键前缀 `auto/`）：

| 属性名 | 存储键 | 类型 | 默认值 | 说明 |
|--------|--------|------|--------|------|
| auto_optimize_enabled | auto/enabled | bool | True | 后台自动优化总开关 |
| auto_optimize_interval | auto/interval | int | 15 | 自动优化检测间隔（秒） |
| memory_threshold | auto/mem_threshold | int | 70 | 内存使用率阈值（%），超过时触发自动优化 |

**虚拟内存组**（键前缀 `pagefile/`）：

| 属性名 | 存储键 | 类型 | 默认值 | 说明 |
|--------|--------|------|--------|------|
| auto_pagefile_enabled | pagefile/auto | bool | True | 内存紧张时自动创建临时分页文件 |
| pagefile_expand_threshold | pagefile/expand_threshold | int | 70 | 提交费用占比超过此值时触发动态扩展（%） |
| pagefile_info | pagefile/created_info | dict\|None | None | 当前活跃的临时分页文件信息（JSON 序列化存储） |
| pagefile_pending_reboot | pagefile/pending_reboot | bool | False | 是否处于等待重启状态 |
| suggestion_enabled | pagefile/suggestion_enabled | bool | True | 智能建议开关 |

**pagefile_info 的 JSON 结构**：`{"drive": "D:\\", "method": "dynamic"|"wmic", "size_mb": 4096, "created_at": "ISO时间戳"}`

**DPC/ISR 监控组**（键前缀 `monitor/`）：

| 属性名 | 存储键 | 类型 | 默认值 | 说明 |
|--------|--------|------|--------|------|
| dpc_monitor_enabled | monitor/dpc | bool | True | DPC/ISR 延迟监控开关 |

**ProBalance CPU 调度组**（键前缀 `cpu/`）：

| 属性名 | 存储键 | 类型 | 默认值 | 说明 |
|--------|--------|------|--------|------|
| probalance_enabled | cpu/probalance_enabled | bool | True | ProBalance 自动 CPU 调度开关 |
| probalance_system_threshold | cpu/system_threshold | int | 60 | 系统总 CPU 激活阈值（%） |
| probalance_process_threshold | cpu/process_threshold | int | 10 | 单进程 CPU 约束阈值（%） |
| anomaly_detection_enabled | cpu/anomaly_enabled | bool | True | Z-score 异常检测开关 |
| anomaly_z_threshold | cpu/z_threshold | float | 2.5 | Z-score 异常判定阈值（越小越敏感） |
| ewma_alpha | cpu/ewma_alpha | float | 0.4 | EWMA 平滑系数（越大越敏感） |

**内存优化策略组**（键前缀 `memory/`）：

| 属性名 | 存储键 | 类型 | 默认值 | 说明 |
|--------|--------|------|--------|------|
| purge_standby_enabled | memory/purge_standby | bool | True | 备用列表清理开关 |
| trim_workingset_enabled | memory/trim_workingset | bool | True | 工作集修剪开关 |
| pageout_idle_enabled | memory/pageout_idle | bool | True | 空闲进程分页开关 |

### 4.2 system_info.py — 系统信息采集

提供 CPU 快照、磁盘快照和字节格式化三个功能。

#### 4.2.1 CpuSnapshot 数据结构

| 字段 | 类型 | 来源 | 说明 |
|------|------|------|------|
| name | str | platform.processor() | CPU 型号名称 |
| cores_physical | int | psutil.cpu_count(logical=False) | 物理核心数 |
| cores_logical | int | psutil.cpu_count(logical=True) | 逻辑核心数（含超线程） |
| percent | float | psutil.cpu_percent(interval=0) | 当前 CPU 使用率百分比 |
| freq_current | float | psutil.cpu_freq().current | 当前频率（MHz） |
| freq_max | float | psutil.cpu_freq().max | 最大频率（MHz） |

**注意**：`cpu_percent(interval=0)` 是非阻塞调用，返回自上次调用以来的 CPU 使用率。首次调用返回 0.0，因此需要在应用启动时预热（调用一次丢弃结果）。

#### 4.2.2 DiskSnapshot 数据结构

| 字段 | 类型 | 说明 |
|------|------|------|
| device | str | 设备名（如 `C:\`） |
| mountpoint | str | 挂载点 |
| total | int | 总容量（字节） |
| used | int | 已用空间（字节） |
| free | int | 可用空间（字节） |
| percent | float | 使用率百分比 |

**get_disk_snapshots()** 遍历 `psutil.disk_partitions(all=False)`（仅物理分区，排除网络驱动器等），对每个分区调用 `psutil.disk_usage()` 获取使用情况。忽略无法访问的分区（OSError）。

#### 4.2.3 format_bytes(n) → str

字节数格式化算法：从 B 开始，每次除以 1024，直到值小于 1024 或到达 PB 单位。保留一位小数。单位序列：B → KB → MB → GB → TB → PB。

### 4.3 anomaly.py — EWMA + Z-score 在线异常检测器

这是 ProBalance 异常检测的核心算法模块。

#### 4.3.1 算法原理

**目标**：在线检测进程 CPU 使用率的突变行为（如突然从 0% 飙升到 50%），区别于持续高负载。

**为什么不用简单的阈值判断**：简单阈值（如 CPU > 30% 就报警）无法区分"一直稳定在 35%"和"突然从 2% 跳到 35%"。前者是正常行为，后者才是异常。需要一种能感知"正常水平"并检测偏离的算法。

**为什么不用滑动窗口**：传统滑动窗口需要存储最近 N 个样本，内存开销为 O(N)。当同时监控数百个进程时，每个进程都维护一个窗口会消耗大量内存。EWMA 只需要 3 个浮点数（mean、var、last_z），内存开销为 O(1)。

**三层算法**：

1. **EWMA（指数加权移动平均）**：
   - 公式：`mean_new = α × value + (1-α) × mean_old`
   - α（alpha）是平滑系数，默认 0.3。α 越大，对新数据越敏感；α 越小，越平滑
   - 作用：跟踪数据的"正常水平"
   - **数学含义**：EWMA 本质上是对历史数据的加权求和，权重按指数衰减。展开递推式可得：`mean_n = α × x_n + α(1-α) × x_{n-1} + α(1-α)² × x_{n-2} + ...`。第 k 步之前的样本权重为 `α(1-α)^k`，随 k 增大指数衰减。当 α=0.3 时，5 步前的样本权重仅为 `0.3 × 0.7^5 ≈ 0.05`，即 5 秒前的数据只占 5% 的影响力
   - **等效窗口长度**：EWMA 的等效滑动窗口长度约为 `2/α - 1`。α=0.3 时等效窗口约 5.7 个样本，意味着算法主要关注最近 6 秒的数据
   - **首个样本特殊处理**：第一个样本直接赋值 `mean = value`，因为没有历史数据可以加权。此时方差为 0，Z-score 也为 0，不会误报

2. **Welford 在线方差（EWMA 变体）**：
   - 经典 Welford 算法用于在线计算方差，但原始版本对所有样本等权。这里使用的是 EWMA 加权变体
   - 公式推导过程：
     - 设 `δ1 = value - mean_old`（更新前的偏差）
     - 更新均值：`mean_new = mean_old + α × δ1`
     - 设 `δ2 = value - mean_new`（更新后的偏差）
     - 注意 `δ2 = value - (mean_old + α × δ1) = δ1 - α × δ1 = (1-α) × δ1`
     - 方差更新：`var_new = (1-α) × var_old + α × δ1 × δ2`
   - **为什么 δ1 × δ2 能估计方差**：`δ1 × δ2 = δ1 × (1-α) × δ1 = (1-α) × δ1²`。当 value 偏离均值越远，δ1² 越大，方差增长越快。乘以 α 做指数加权，乘以 (1-α) × var_old 保留历史方差的记忆。这个公式的巧妙之处在于：它同时利用了更新前后的偏差，自然地将新样本的贡献融入方差估计
   - **数值稳定性**：与直接计算 `E[x²] - E[x]²` 相比，Welford 方法不会因为大数相减产生精度损失。即使均值很大（如 CPU 稳定在 90%），方差计算仍然精确
   - **方差的物理含义**：方差衡量数据的"波动幅度"。一个稳定在 30% 的进程方差很小；一个在 10%-50% 之间波动的进程方差很大。方差越小，同样的偏离就越"异常"

3. **Z-score**：
   - 公式：`z = |value - mean| / sqrt(var)`
   - 含义：当前值偏离均值多少个标准差
   - **统计学背景**：在正态分布下，Z > 3 的概率仅为 0.27%（约 370 次采样才出现一次）。这意味着如果一个进程的 CPU 使用率服从正态分布，Z > 3 几乎可以确定是异常行为
   - **阈值选择**：默认 3.0。更低的阈值（如 2.0）会更敏感但误报更多；更高的阈值（如 4.0）更保守但可能漏报。3.0 是统计学中常用的"三西格玛准则"
   - **最少样本数保护**：前 min_samples（默认 10）个样本不做检测，返回 Z=0。原因是样本太少时方差估计不稳定，容易产生极端 Z 值。10 个样本（即 10 秒）足以建立一个合理的基线
   - **方差为零或负数的保护**：如果 var ≤ 0（所有样本完全相同，或浮点精度问题），返回 Z=0。避免除以零或对负数开方

#### 4.3.2 River HalfSpaceTrees 可选集成

如果安装了 `river` 库，可以使用 HalfSpaceTrees 替代 EWMA+Z-score：
- 参数：`n_trees=10, height=6, window_size=50, seed=42`
- `score_one({"x": value})` 返回 0-1 的异常分数
- 分数 > 0.5 时，将其线性映射为等效 Z-score：`z = score × z_threshold / 0.5`
- 分数 ≤ 0.5 时，Z-score 为 0

**HalfSpaceTrees 算法原理**：这是一种基于随机森林的在线异常检测算法。核心思想是在特征空间中随机划分半空间（类似随机切割），正常数据点会落在"密集"的区域（被多棵树的多个叶节点覆盖），异常数据点会落在"稀疏"的区域。`n_trees=10` 表示使用 10 棵随机树投票，`height=6` 表示每棵树最多 6 层（最多 64 个叶节点），`window_size=50` 表示使用最近 50 个样本维护参考窗口。

**为什么需要分数映射**：HalfSpaceTrees 返回 0-1 的异常分数，而 ProBalance 的约束逻辑统一使用 Z-score 阈值判断。映射公式 `z = score × z_threshold / 0.5` 将 score=0.5 映射为 z=z_threshold（刚好触发），score=1.0 映射为 z=2×z_threshold（强异常）。score ≤ 0.5 视为正常，Z=0。

**调用顺序的重要性**：必须先 `score_one` 再 `learn_one`。如果反过来，模型会先学习当前样本再评分，导致异常样本被"吸收"后评分偏低，降低检测灵敏度。

**降级策略**：使用 `try/except` 包裹 `from river.anomaly import HalfSpaceTrees`。如果 river 未安装或导入失败（任何异常），`_HAS_RIVER` 标记为 False，构造函数中 `self._hst` 保持 None，所有后续调用自动走 EWMA+Z-score 路径。这种设计使 river 成为纯可选依赖，不影响核心功能。

#### 4.3.3 AnomalyDetector 类接口

**构造参数**：
- `alpha`：EWMA 平滑系数，默认 0.3
- `z_threshold`：Z-score 异常阈值，默认 3.0
- `min_samples`：最少样本数，默认 10
- `use_river`：是否尝试使用 River，默认 True

**update(value) → float**：输入新样本，返回 Z-score。内部自动更新均值和方差。

**is_anomaly → bool**：属性，返回最近一次 update 的 Z-score 是否超过阈值。

---

## 五、Model 层 — 内存管理

### 5.1 memory.py — 智能内存管理

这是内存优化的核心模块，包含备用列表清理、工作集修剪、页面文件调整、空闲进程分页四大功能。

#### 5.1.1 模块级状态

模块维护一个全局变量 `_last_page_fault_count`（整数，初始为 0），用于追踪页错误增量。每次调用 `get_page_fault_delta()` 时更新。

#### 5.1.2 _get_total_page_faults() → int

遍历系统所有进程（通过 `psutil.process_iter`），对每个进程调用 `proc.memory_info().num_page_faults` 获取其页错误计数，累加求和。忽略权限不足或进程已退出的异常。

**页错误（Page Fault）的本质**：当进程访问一个虚拟地址，而该地址对应的物理页不在工作集中时，CPU 触发页错误异常。页错误分两种：
- **软页错误（Soft Fault）**：目标页仍在物理内存中（在备用列表或修改列表中），只需更新页表映射，不涉及磁盘 I/O，耗时约 1-10 微秒
- **硬页错误（Hard Fault）**：目标页已被换出到磁盘（页面文件），需要从磁盘读回，耗时约 1-10 毫秒（比软页错误慢 1000 倍）

`num_page_faults` 是 Windows 进程计数器 `PageFaultCount`，包含软+硬页错误的总和。当这个值的增量很大时，说明系统正在频繁地将页面从备用列表或磁盘调入工作集，是内存压力的直接指标。

#### 5.1.3 get_page_fault_delta() → int

计算自上次调用以来的页错误增量：
1. 调用 `_get_total_page_faults()` 获取当前总页错误数
2. 如果 `_last_page_fault_count` 为 0（首次调用），增量为 0
3. 否则增量 = 当前值 - 上次值，取 max(0, delta) 防止负数
4. 更新 `_last_page_fault_count` 为当前值

#### 5.1.4 should_purge_standby(pressure_mode=False) → bool

**判断是否需要清理备用列表的核心决策函数。**

**普通模式**（pressure_mode=False）判断流程：
1. 获取内存状态快照
2. 如果可用内存 ≥ 2GB（FREE_MEM_THRESHOLD_BYTES）→ 返回 False（内存充足，无需清理）
3. 估算备用列表大小：`standby_est = max(0, total - used - available)`
   - **原理**：Windows 的 MEMORYSTATUSEX 不直接暴露备用列表大小。但物理内存的分布关系为：`total = 活跃页(used) + 可用页(available) + 备用页(standby)`。其中 `available` 是 Windows 报告的"可用"内存（对应 `ullAvailPhys`），它包含空闲页（Zeroed + Free）但不包含备用页。`used` 对应 `total - ullAvailPhys` 中的活跃部分。因此 `standby ≈ total - used - available`
   - **为什么用 max(0, ...)**：由于 `used` 和 `available` 的定义在不同 Windows 版本中略有差异，计算结果可能出现小的负数，用 max(0, ...) 兜底
   - **更精确的替代方案**：如果需要精确值，可以调用 `GetPerformanceInfo()` 获取系统页面计数，或者读取 `\Memory\Standby Cache Normal Priority Bytes` 等 PDH 计数器。但估算值对于决策已经足够
4. 如果备用列表估算值 ≤ 总内存 × 25%（STANDBY_RATIO_THRESHOLD）→ 返回 False
   - **为什么是 25%**：备用列表是 Windows 的文件缓存，清理它会导致后续文件访问变慢。只有当备用列表占比过高（挤占了应用可用的内存）时才值得清理。25% 是一个保守阈值，避免过度清理
5. 以上条件都满足 → 返回 True

**压力模式**（pressure_mode=True）在普通模式基础上增加额外条件：
- 普通模式的条件 1-4 必须先满足
- 然后还需满足以下任一条件：
  - 前台窗口为全屏（调用 `is_foreground_fullscreen()`）— 表示用户在玩游戏或看视频
  - 页错误增量 > 50000（PAGE_FAULT_DELTA_THRESHOLD）— 表示系统正在频繁换页

**两种模式的使用场景**：
- 普通模式用于用户手动触发的"一键优化"，条件较宽松，只要内存不足+备用列表大就清理
- 压力模式用于后台自动优化定时器，条件更严格，需要额外证据（全屏应用或高页错误率）才触发，避免在用户正常使用时频繁清理缓存影响文件访问性能

#### 5.1.5 force_purge() → bool

直接调用 `winapi.purge_standby_list()`，不做任何条件判断。用于用户手动触发清理。

#### 5.1.6 smart_purge(pressure_mode=False) → bool

组合函数：先调用 `should_purge_standby()` 判断是否需要清理，满足条件时调用 `force_purge()` 执行清理。

#### 5.1.7 trim_background_working_sets() → int

**修剪后台进程工作集，返回成功修剪的进程数。**

遍历所有进程，对每个进程执行以下过滤：
1. 获取进程名（转小写）
2. **跳过受保护进程**（PROTECTED_PROCESSES 集合中的进程）
3. **跳过音频进程**（AUDIO_PROCESSES 集合中的进程）— 音频进程的工作集被释放后，重新加载页面会导致音频卡顿（glitch），因为音频回调有严格的实时性要求（通常 10ms 内必须返回数据）
4. **跳过前台窗口进程**（通过 `get_foreground_window_pid()` 获取）— 用户正在交互的进程，释放工作集会导致界面卡顿
5. **跳过高优先级进程**：检查 `proc.nice()`，如果优先级 < `BELOW_NORMAL_PRIORITY_CLASS` 则跳过

**Windows 进程优先级类的数值**（psutil 常量对应 Windows API 值）：

| 优先级类 | psutil 常量 | 数值 |
|----------|-------------|------|
| IDLE_PRIORITY_CLASS | 64 | 0x40 |
| BELOW_NORMAL_PRIORITY_CLASS | 16384 | 0x4000 |
| NORMAL_PRIORITY_CLASS | 32 | 0x20 |
| ABOVE_NORMAL_PRIORITY_CLASS | 32768 | 0x8000 |
| HIGH_PRIORITY_CLASS | 128 | 0x80 |
| REALTIME_PRIORITY_CLASS | 256 | 0x100 |

**注意**：这些数值不是线性递增的，不能用简单的大小比较判断优先级高低。代码中 `nice < BELOW_NORMAL_PRIORITY_CLASS` 的判断之所以有效，是因为 psutil 的 `nice()` 返回的是 Windows 原始优先级类值，而 NORMAL(32) < BELOW_NORMAL(16384)。这意味着条件 `nice < BELOW_NORMAL` 实际上匹配的是 NORMAL(32)、HIGH(128)、REALTIME(256) 这些"数值上小于 16384"的优先级类。换言之，代码的真实意图是：**只修剪 NORMAL 及以上优先级的进程，跳过已经被 ProBalance 降级到 BELOW_NORMAL 或 IDLE 的进程**（避免对已约束的进程重复操作）。

通过所有过滤的进程，调用 `winapi.empty_working_set(pid)` 释放其工作集。

#### 5.1.8 get_commit_ratio() → float

计算提交费用比率：`commit_total / commit_limit`。返回 0.0-1.0 之间的浮点数。commit_limit 为 0 时返回 0.0。

**提交费用（Commit Charge）背景**：Windows 的虚拟内存管理器为每个进程分配虚拟地址空间时，会"承诺"（commit）一定量的后备存储（物理内存 + 分页文件）。`commit_total` 是所有进程已承诺的总量，`commit_limit` 是系统能承诺的上限（= 物理内存 + 所有分页文件大小之和）。当 commit_total 接近 commit_limit 时，新的内存分配请求会失败，导致应用崩溃或系统不稳定。

**与内存使用率的区别**：内存使用率（`mem.percent`）反映的是物理 RAM 的占用情况，而提交比率反映的是虚拟内存承诺的饱和度。一个系统可能物理内存使用率只有 60%，但提交比率已经 90%——这意味着虽然还有物理 RAM 空闲，但虚拟地址空间的后备存储即将耗尽。这种情况在分页文件较小或被禁用时尤其常见。

**数据来源**：`commit_total` 和 `commit_limit` 来自 `MEMORYSTATUSEX` 结构体的 `ullTotalPageFile`（commit_limit）和 `ullTotalPageFile - ullAvailPageFile`（commit_total）。注意 Windows API 中的命名有误导性——`TotalPageFile` 实际上是 commit limit 而非分页文件大小。

#### 5.1.9 is_commit_critical() → bool

判断提交费用是否达到危险水平：`get_commit_ratio() >= 0.80`（COMMIT_RATIO_WARNING）。

**80% 阈值的选择依据**：Windows 自身在提交比率达到约 90% 时会弹出"内存不足"警告。选择 80% 作为预警阈值，留出 10% 的缓冲区间用于主动干预（创建临时分页文件），避免等到系统自身报警时已经来不及。

#### 5.1.10 adjust_pagefile_size(drive, size_mb) → bool

通过 `wmic` 命令行工具调整指定驱动器的页面文件大小。将初始大小和最大大小都设为 `size_mb`（固定大小）。

命令格式：`wmic pagefileset where name="C:\\pagefile.sys" set InitialSize=8192,MaximumSize=8192`

**InitialSize = MaximumSize 的原因**：Windows 分页文件支持动态增长（InitialSize < MaximumSize 时），但动态增长过程中会产生磁盘碎片，且增长操作本身有 I/O 开销。将两者设为相同值创建固定大小的分页文件，避免运行时的碎片和增长延迟。这是 Microsoft 官方推荐的性能优化做法。

**wmic 的局限性**：wmic 修改的是注册表中的分页文件配置（`HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management\PagingFiles`），需要重启才能生效。这是因为分页文件在系统启动早期由 Session Manager（smss.exe）创建，运行时无法通过此途径修改。运行时动态创建需要使用 `NtCreatePagingFile`（见 5.3.6）。

**shell=True 的使用**：wmic 命令包含空格和引号的复杂参数，使用 `shell=True` 让 cmd.exe 解析命令字符串比手动拆分参数列表更可靠。

#### 5.1.11 recommend_pagefile_mb() → int

推荐页面文件大小算法：`物理内存总量 × 1.5 / 1024²`，上限 32768（32GB）。

**1.5 倍的依据**：Microsoft 传统建议是物理内存的 1.5-3 倍。本项目取下限 1.5 倍，因为现代系统物理内存通常较大（16-64GB），过大的分页文件浪费磁盘空间且很少被完全使用。

**32GB 上限的原因**：对于 64GB 物理内存的系统，1.5 倍 = 96GB 分页文件显然不合理。32GB 上限确保即使在大内存系统上也不会创建过大的分页文件。实际上，分页文件主要用于内核崩溃转储和极端内存压力场景，32GB 已经足够覆盖绝大多数情况。

#### 5.1.12 page_out_idle_processes(min_mb=10.0) → List[(name, freed_mb)]

**智能识别空闲大内存进程并将其工作集页出到虚拟内存。**

遍历所有进程，过滤条件：
1. 进程 RSS（常驻内存）≥ min_mb（默认 10MB）
2. 不在受保护进程列表中
3. 不在音频进程列表中
4. 不是前台窗口进程
5. CPU 使用率 ≤ 5%（`cpu_percent(interval=0) > 5.0` 则跳过）— 表示进程近期无活动

**与 trim_background_working_sets 的区别**：`trim_background_working_sets` 修剪所有后台进程（不论是否空闲），且不检查内存大小，是"广撒网"式的。而 `page_out_idle_processes` 只针对"空闲 + 大内存"的进程，是精准打击——这些进程占着大量物理内存却什么都没做，是最理想的页出目标。

**CPU ≤ 5% 作为"空闲"判据的原因**：`cpu_percent(interval=0)` 返回的是自上次调用以来的 CPU 使用率。由于定时器每 1.5 秒调用一次，这个值反映的是最近 1.5 秒内的平均 CPU 活动。5% 的阈值允许少量后台活动（如定时器回调、GC），但排除正在积极工作的进程。

对满足条件的进程：
1. 记录修剪前的 RSS
2. 调用 `empty_working_set(pid)` 释放工作集
3. 重新读取 RSS，计算释放量 = 修剪前 RSS - 修剪后 RSS
4. 如果释放量 > 0，记录到结果列表

**释放量计算的精确性**：`empty_working_set` 调用 `SetProcessWorkingSetSizeEx(-1, -1)` 后，操作系统会将进程的工作集页面移到备用列表或写入分页文件。但这个过程不是瞬时的——操作系统可能在后台异步完成。因此紧接着读取的 `rss_after` 可能不完全反映最终释放量，但作为估算值已经足够。

返回 `[(进程名, 释放MB)]` 列表。

### 5.2 cpu_optimizer.py — ProBalance CPU 调度引擎

这是项目中最复杂的模块，参考 Process Lasso 的 ProBalance 功能，实现自动检测 CPU 霸占进程并临时约束其优先级。

#### 5.2.1 核心设计理念

**预测性干预而非反应式干预**：不是等 CPU 已经 100% 了才处理，而是通过 EWMA 趋势预测，在 CPU 即将超阈值时提前干预。反应式方案的问题是：当检测到 CPU 100% 时，用户已经感受到卡顿了——从检测到约束生效还需要至少一个采样周期（1 秒），加上操作系统调度器响应优先级变化的延迟，总延迟可达 2-3 秒。预测性方案通过线性外推提前 2 步（2 秒）预判，在 CPU 还在上升阶段就开始约束，用户几乎感受不到卡顿。

**临时约束而非永久修改**：约束是临时的，系统负载恢复后自动还原。不会永久改变任何进程的优先级。这与 Process Lasso 的 ProBalance 理念一致——工具不应该"记仇"，一个进程曾经霸占 CPU 不代表它以后也会。每次约束都是独立的决策。

**白名单绝对保护**：系统关键进程、音频进程、前台窗口进程绝对不会被约束。白名单采用集合（set）数据结构，查找时间复杂度 O(1)。前台窗口 PID 每次 tick 都重新获取（通过 `GetForegroundWindow` + `GetWindowThreadProcessId`），因为用户随时可能切换窗口。

**双重触发机制**：除了传统的"持续超阈值"触发外，还有 Z-score 异常检测触发。前者捕捉"持续高负载"（如编译任务），后者捕捉"突发行为变化"（如进程突然从 2% 跳到 40%）。两种机制互补，覆盖不同的 CPU 霸占模式。

#### 5.2.2 _TrendPredictor — EWMA 趋势预测器

**构造参数**：
- `alpha`：EWMA 平滑系数，默认 0.3
- `window`：历史窗口大小，默认 10（使用 deque 限制长度）
- `lookahead`：向前预测步数，默认 2

**update(value) → float 算法**：
1. 记录上一次的 EWMA 值 `prev_ewma`
2. 如果是首个样本，EWMA = value；否则 `ewma = α × value + (1-α) × ewma`
3. 将 value 加入历史窗口
4. 计算变化率：`rate = ewma - prev_ewma`（当前 EWMA 与上一次的差值）
5. 预测未来值：`predicted = ewma + rate × lookahead`
6. 钳位到 [0, 100] 范围
7. 返回预测值

**预测原理（线性外推）**：这是一阶线性预测。`rate` 是 EWMA 的一阶差分（即"速度"），`rate × lookahead` 是假设速度不变时的位移。例如：当前 EWMA=45%，上一次 EWMA=40%，则 rate=5，lookahead=2 时预测值=45+5×2=55%。这意味着如果 CPU 正在以每秒 5% 的速度上升，预测 2 秒后将达到 55%。

**为什么用 EWMA 的差分而非原始值的差分**：直接用 `value - prev_value` 作为变化率会受到瞬时波动的干扰。例如 CPU 从 30% 跳到 60% 再回到 35%，原始差分会给出 +30 和 -25 的剧烈波动。而 EWMA 差分天然平滑，只有持续的趋势才会产生显著的 rate 值。

**钳位的必要性**：线性外推可能产生超出 [0, 100] 的值。例如 EWMA=95%，rate=10，预测值=115%，需要钳位到 100%。同理下降趋势可能预测出负值。

**deque 窗口的作用**：虽然当前代码中 `_history` 仅用于判断是否为首个样本（`not self._history`），但保留窗口为未来扩展（如计算窗口内的统计量）提供了基础。deque 的 maxlen=10 自动丢弃旧数据，无需手动管理。

**reset()**：清空历史窗口，重置 EWMA 和变化率。在系统负载恢复（还原所有约束）时调用，确保下次高负载时从零开始预测，不受上一轮的残留状态影响。

#### 5.2.3 _ConstrainedProcess — 被约束进程记录

每当一个进程被约束时，其约束前的完整状态会被保存到此数据类中，以便后续精确还原。这是"快照-还原"模式的核心——不假设进程的"正常"状态是什么，而是记录约束前的实际状态。

| 字段 | 类型 | 说明 |
|------|------|------|
| pid | int | 进程 ID |
| name | str | 进程名（小写） |
| original_priority | int | 约束前的原始优先级 |
| original_affinity | list[int]\|None | 约束前的原始 CPU 亲和性 |
| constrained_at | float | 约束时的单调时钟时间戳 |
| reason | str | 约束原因："threshold"（阈值触发）或 "anomaly"（异常检测触发） |

**original_affinity 可能为 None 的原因**：获取进程的 CPU 亲和性需要 `PROCESS_QUERY_INFORMATION` 权限，某些受保护进程可能拒绝访问。此时记录为 None，还原时跳过亲和性恢复（只恢复优先级）。

**使用 time.monotonic() 而非 time.time()**：`time.time()` 是墙钟时间，会受 NTP 同步、用户手动调整等影响。如果在约束期间系统时钟被向前调整了 1 小时，`time.time()` 会认为已经约束了 1 小时。`time.monotonic()` 是单调递增的，不受时钟调整影响，专门用于测量时间间隔。

#### 5.2.4 ProBalanceSnapshot — 单次采样结果

| 字段 | 类型 | 说明 |
|------|------|------|
| system_cpu | float | 当前系统 CPU 使用率 |
| predicted_cpu | float | EWMA 预测的系统 CPU |
| constrained_count | int | 当前被约束的进程数 |
| restored_count | int | 本次还原的进程数 |
| actions | list[str] | 本次约束操作的描述列表 |
| anomaly_actions | list[str] | 本次异常检测触发的约束描述列表 |

#### 5.2.5 白名单定义

白名单 = 受保护进程集合 ∪ 音频进程集合 ∪ 以下额外进程：
- 系统核心：`system idle process`, `registry`, `memory compression`
- 桌面环境：`dwm.exe`, `explorer.exe`, `searchhost.exe`, `shellexperiencehost.exe`, `startmenuexperiencehost.exe`, `runtimebroker.exe`, `fontdrvhost.exe`
- 自身进程：`python.exe`, `pythonw.exe`（迁移时改为自身可执行文件名）

**白名单分层设计**：
- **PROTECTED_PROCESSES**（constants.py）：操作系统核心进程，降低优先级可能导致蓝屏或系统挂起。如 `csrss.exe`（Client/Server Runtime）负责控制台窗口和线程创建，`lsass.exe`（Local Security Authority）负责认证，`svchost.exe` 托管大量系统服务
- **AUDIO_PROCESSES**（constants.py）：音频相关进程，降低优先级会导致音频卡顿、爆音。音频处理对延迟极其敏感，通常需要在 10ms 内完成缓冲区填充
- **桌面环境进程**：`dwm.exe`（Desktop Window Manager）负责窗口合成和渲染，约束它会导致整个桌面卡顿。`explorer.exe` 是任务栏和文件管理器。其他 Shell 进程负责开始菜单、搜索等核心交互
- **自身进程**：防止工具约束自己导致 UI 无响应

**为什么前台窗口不在静态白名单中**：前台窗口是动态的（用户随时切换），所以在 tick() 中每次通过 `get_foreground_window_pid()` 实时获取，而非写入静态集合。

#### 5.2.6 ProBalanceEngine 初始化

1. **预热 psutil CPU 采样**：首次调用 `cpu_percent(interval=0)` 返回 0.0，必须丢弃。原因是 psutil 的 CPU 百分比计算需要两个时间点的采样差值：`(busy_time_2 - busy_time_1) / (total_time_2 - total_time_1) × 100`。首次调用时没有上一个时间点，所以返回 0。`interval=0` 表示非阻塞（不等待），使用上次调用的时间点作为基准。因此必须在初始化时"空调用"一次建立基线
2. 初始化约束进程字典 `_constrained`：pid → _ConstrainedProcess
3. 初始化超阈值计时字典 `_over_threshold_since`：pid → 首次超阈值的时间戳（使用 `time.monotonic()` 而非 `time.time()`，因为 monotonic 不受系统时钟调整影响，适合测量时间间隔）
4. 调用 `get_cpu_topology()` 检测 P/E 核心拓扑，记录是否为混合架构和 E-Core 列表
5. 创建系统级 EWMA 趋势预测器（alpha=0.3, window=10, lookahead=2）
6. 初始化每进程预测器字典和异常检测器字典（均为空字典，按需创建）

#### 5.2.7 tick() — 核心调度循环

由定时器每秒调用一次。接受以下可配置参数（均可从设置中读取）：
- `system_threshold`：系统 CPU 激活阈值，默认 60%
- `process_threshold`：单进程 CPU 约束阈值，默认 10%
- `sustain_seconds`：持续超阈值时间，默认 2 秒
- `restore_threshold`：还原阈值，默认 40%
- `anomaly_enabled`：是否启用异常检测，默认 True
- `z_threshold`：Z-score 阈值，默认 3.0
- `ewma_alpha`：EWMA 平滑系数，默认 0.3

**完整执行流程**：

tick() 本质上是一个三状态状态机，每秒执行一次状态转换：

```
状态 A（空闲）: 实际 CPU < restore_threshold → 还原所有约束，清空状态
状态 B（观察）: 预测 CPU < system_threshold → 维持现有约束，不扫描新进程
状态 C（干预）: 预测 CPU ≥ system_threshold → 扫描进程，约束霸占者
```

**第一步：采集系统 CPU 并预测**
- 调用 `psutil.cpu_percent(interval=0)` 获取当前系统 CPU 使用率
- 将其输入系统级 EWMA 预测器，获取预测值

**第二步：检查是否应还原所有约束（状态 A）**
- 如果实际系统 CPU < restore_threshold（默认 40%）：
  - 调用 `_restore_all()` 还原所有被约束的进程
  - 清空超阈值计时字典、每进程预测器字典、每进程异常检测器字典
  - 返回快照（不继续扫描进程）
- **为什么用实际值而非预测值**：还原判断需要保守，避免因预测误差导致过早还原。只有当系统确实已经降到低负载时才还原
- **为什么清空所有字典**：还原意味着系统回到正常状态，之前积累的每进程预测器和异常检测器的历史数据已经过时，下次高负载时需要重新建立基线

**第三步：检查是否应开始扫描（状态 B）**
- 如果预测值 < system_threshold（默认 60%）：
  - 仅清理已退出进程的记录
  - 返回快照（维持现有约束，不扫描新进程）
- **为什么用预测值而非实际值**：这是"预测性干预"的核心。如果当前 CPU 是 55% 但趋势在上升，预测值可能已经超过 60%，此时应该开始扫描。反之如果当前 58% 但趋势在下降，预测值可能低于 60%，此时不需要扫描

**第四步：高负载扫描进程（状态 C）**
- 获取前台窗口 PID
- 遍历所有进程（`psutil.process_iter`，请求 pid、name、cpu_percent 字段）
- 对每个进程执行以下判断：

  a. **白名单检查**：如果进程名在白名单中或是前台窗口进程 → 跳过，并清除该进程的计时器和预测器（防止进程从白名单移出后残留旧状态）

  b. **已约束检查**：如果进程已在约束字典中 → 跳过（不重复约束）

  c. **优先级检查**：获取进程优先级，如果不是 NORMAL_PRIORITY_CLASS → 跳过。**原因**：只约束普通优先级进程。高优先级进程（如 HIGH）通常是用户或系统有意设置的；低优先级进程（如 BELOW_NORMAL、IDLE）已经不会抢占正常进程的 CPU 时间

  d. **EWMA 预测进程 CPU**：为该进程创建或获取 TrendPredictor，输入当前 CPU 值，获取预测值。每个进程有独立的预测器实例，互不干扰

  e. **Z-score 异常检测**：如果启用异常检测，为该进程创建或获取 AnomalyDetector，输入当前 CPU 值，获取 Z-score

  f. **阈值触发判断（双通道）**：
     - **通道 1 — 持续高负载**：如果预测 CPU ≥ process_threshold（默认 10%）：
       - 如果该进程尚未开始计时 → 记录当前时间到 `_over_threshold_since[pid]`
       - 如果已计时且持续时间 ≥ sustain_seconds（默认 2 秒）→ 调用 `_constrain()` 约束该进程
       - **sustain 机制的作用**：防止瞬时 CPU 尖峰触发约束。进程必须持续超阈值 2 秒才会被约束，避免误伤编译、解压等短暂高 CPU 操作
     - **通道 2 — 行为突变**：如果 Z-score > z_threshold 且 CPU > 5% 且系统 CPU ≥ restore_threshold → 异常检测触发约束。**三个条件缺一不可**：Z-score 高说明行为突变；CPU > 5% 排除噪声（从 0.1% 到 0.5% 也是突变但无害）；系统 CPU 高说明确实有压力
     - 否则 → 清除该进程的计时器（重新开始计时）

- 清理已退出进程的记录（从所有字典中移除不存在的 PID）

#### 5.2.8 _constrain() — 约束单个进程

**执行步骤**：
1. 记录进程的原始 CPU 亲和性（`proc.cpu_affinity()`），失败则记为 None
2. 将进程优先级降为 `BELOW_NORMAL_PRIORITY_CLASS`（`proc.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)`）
3. 如果是混合架构且有 E-Core：将进程绑定到 E-Core（`proc.cpu_affinity(e_cores)`）
4. 创建 `_ConstrainedProcess` 记录，存入约束字典
5. 从超阈值计时字典中移除该进程

**为什么降到 BELOW_NORMAL 而非 IDLE**：IDLE_PRIORITY_CLASS 的线程只在系统完全空闲时才获得 CPU 时间，可能导致进程完全饿死（如数据库后台线程无法完成事务提交）。BELOW_NORMAL 仍然能获得 CPU 时间，只是比 NORMAL 少，是一个温和的惩罚。

**CPU 亲和性绑定的底层原理**：`cpu_affinity()` 最终调用 Windows API `SetProcessAffinityMask(handle, mask)`，其中 mask 是一个位掩码，每一位对应一个逻辑 CPU。例如 E-Core 列表为 [8,9,10,11]，则 mask = (1<<8)|(1<<9)|(1<<10)|(1<<11) = 0xF00。绑定后，该进程的所有线程只能在这些 CPU 上调度。

**优先级降低 + 亲和性绑定的协同效果**：单独降低优先级只能减少 CPU 时间份额，进程仍然可能在 P-Core 上运行并与前台应用竞争缓存。绑定到 E-Core 后，进程被物理隔离到效率核心上，P-Core 完全留给前台应用，减少 L2/L3 缓存争用。

#### 5.2.9 _restore_all(now) — 还原所有约束

遍历约束字典中的所有进程：
- 如果约束时间 < 3 秒（PROBALANCE_MIN_CONSTRAIN_SECONDS）→ 跳过（防止优先级抖动）
- 调用 `_restore_one()` 尝试还原
- 还原成功或进程已退出 → 从字典中移除
- 权限不足 → 保留记录，下次重试

**最短约束时间的作用**：如果没有这个限制，可能出现"约束→系统 CPU 下降→还原→CPU 再次上升→再约束"的快速振荡（抖动）。3 秒的最短约束时间确保约束至少持续一段时间，让系统有时间稳定下来。这是控制论中"死区"（deadband）的思想。

#### 5.2.10 _restore_one() — 还原单个进程

1. 通过 PID 获取进程对象
2. 恢复原始优先级（`proc.nice(info.original_priority)`）
3. 如果有原始亲和性记录，恢复原始 CPU 亲和性
4. 进程已退出（NoSuchProcess）→ 返回 True（可以清除记录）
5. 权限不足（AccessDenied）→ 返回 False（保留记录重试）

**返回值语义的精妙设计**：True 不代表"还原成功"，而是代表"可以从字典中移除"。进程已退出时虽然没有"还原"，但记录已经没有意义了，所以也返回 True。而权限不足返回 False，是因为进程还在运行但我们暂时无法操作它——下次 tick 时可能权限恢复（如用户关闭了占用句柄的调试器），所以保留记录重试。

**还原顺序**：先恢复优先级，再恢复亲和性。这个顺序很重要——如果先恢复亲和性（允许在所有核心上运行），进程可能立即在 P-Core 上以 BELOW_NORMAL 优先级运行，虽然影响很小但不够干净。先恢复优先级确保进程回到 NORMAL 后再扩展到所有核心。

#### 5.2.11 force_restore_all() — 强制还原

关闭应用时调用。不检查最短约束时间，直接还原所有被约束的进程，然后清空所有字典。

**为什么需要单独的强制还原方法**：正常的 `_restore_all()` 会跳过约束时间 < 3 秒的进程，这在运行时是合理的（防抖动）。但应用关闭时，如果不还原这些进程，它们将永久保持被降级的状态——因为没有其他机制会帮它们恢复。所以关闭时必须无条件还原所有约束，即使约束才刚刚生效。

**清空字典的顺序**：先遍历 `_constrained` 逐个还原，再 `clear()` 清空。使用 `list(self._constrained.items())` 创建副本遍历，因为 `_restore_one` 不会修改字典（修改由调用方负责），所以这里直接遍历后统一清空。

#### 5.2.12 constrained_processes 属性

返回当前被约束的进程列表：`[(pid, name, 约束秒数, reason)]`。约束秒数 = 当前时间 - constrained_at，保留一位小数。

### 5.3 auto_optimizer.py — 后台自动优化器

负责后台自动检测系统压力并执行优化，以及临时分页文件的完整生命周期管理。

#### 5.3.1 模块级状态

- `_created_pagefiles: dict[str, str]` — 本次会话中创建的临时分页文件映射，键为驱动器路径（如 `"D:\\"`），值为创建方式（`"dynamic"` 或 `"wmic"`）
- `_current_pagefile_size_mb: int` — 当前分页文件累计大小（MB），初始为 0

**为什么用模块级变量而非类实例**：auto_optimizer 的函数是无状态的工具函数，被多个 ViewModel 调用（DashboardViewModel 的定时器、SmartOptimizeWorker 等）。如果用类实例，需要确保所有调用方共享同一个实例（单例模式），增加了复杂度。模块级变量天然是"单例"的——Python 模块只会被导入一次，所有导入方共享同一份模块级变量。

**双重跟踪的原因**：`_created_pagefiles` 记录"在哪个盘、用什么方式创建的"（用于清理时选择正确的删除方法），`_current_pagefile_size_mb` 记录"当前总大小"（用于增量扩展时判断是否达到上限）。两者信息不重叠，各有用途。

**模块顶部的 psutil.cpu_percent(interval=0) 预热调用**：在模块导入时执行一次空调用，建立 CPU 采样基线。这确保后续 `calc_health_score()` 中的 `cpu_percent(interval=0)` 能返回有意义的值，而非首次调用的 0.0。

#### 5.3.2 restore_pagefile_state()

**应用启动时调用**，从持久化设置中恢复上次会话的分页文件跟踪状态。

流程：
1. 从 `AppSettings().pagefile_info` 读取上次保存的分页文件信息
2. 如果为空，直接返回
3. 检查对应路径的 `pagefile.sys` 文件是否仍然存在
4. 如果不存在（可能已被系统清理或用户手动删除），清除持久化记录
5. 如果存在，恢复到模块级状态变量中

#### 5.3.3 calc_health_score() → int

**计算系统健康评分（0-100 分）。**

评分由三个维度组成，使用阈值式线性扣分：

**内部评分函数 _score(percent, full, low, high)**：
- percent ≤ low → 满分 full
- percent ≥ high → 0 分
- low < percent < high → 线性插值：`full × (high - percent) / (high - low)`

**为什么用阈值式而非全范围线性**：如果从 0% 开始线性扣分，内存使用率 50%（完全正常）就会扣掉一半分数，给用户造成不必要的焦虑。阈值式设计确保正常使用范围内（内存 < 70%、CPU < 50%、磁盘 < 70%）始终满分，只有真正出现压力时才开始扣分。

**三个维度**：
1. **内存评分**（满分 40 分）：low=70%, high=95%
   - 内存使用率 ≤ 70% → 40 分
   - 70%-95% → 线性扣分
   - ≥ 95% → 0 分
   - **权重最高（40 分）的原因**：内存压力对用户体验影响最直接——导致页面交换、应用卡顿、甚至 OOM 崩溃

2. **CPU 评分**（满分 30 分）：low=50%, high=95%
   - CPU 使用率 ≤ 50% → 30 分
   - 50%-95% → 线性扣分
   - ≥ 95% → 0 分
   - **阈值较低（50%）的原因**：CPU 持续高于 50% 通常意味着有后台任务在大量消耗资源，用户可能感受到界面响应变慢

3. **磁盘评分**（满分 30 分）：low=70%, high=95%
   - 遍历所有磁盘分区，取最差分数（最小值）
   - 任一分区使用率 ≥ 95% → 0 分
   - **取最小值的原因**：只要有一个分区快满了（尤其是系统盘），就会影响系统稳定性（Windows 需要磁盘空间存放页面文件、临时文件、更新缓存等）

总分 = min(100, 内存分 + CPU 分 + 磁盘分)

#### 5.3.4 check_and_auto_optimize() → list[str]

**后台自动优化的核心函数**，由定时器周期性调用。返回执行的操作描述列表。

**设计哲学——压力触发式而非定时式**：不是每隔 N 分钟固定执行清理，而是只在检测到实际压力时才干预。这避免了不必要的系统操作——如果内存充足、提交费用正常，函数会立即返回空列表，开销仅为一次 `GlobalMemoryStatusEx` 调用（微秒级）。

流程：
1. 获取内存状态
2. **内存压力检测**：如果可用内存 < 2GB（FREE_MEM_THRESHOLD_BYTES）
   - 调用 `smart_purge(pressure_mode=True)` 尝试压力触发式清理备用列表
   - 调用 `trim_background_working_sets()` 修剪后台进程工作集
   - **两步操作的互补性**：purge 释放备用列表（系统级缓存），trim 释放进程工作集（进程级缓存）。前者效果立竿见影但可能影响文件缓存命中率，后者更温和但释放量取决于后台进程数量
3. **提交费用检测**：计算 commit_total / commit_limit 比率
   - 如果比率 ≥ 80%（COMMIT_RATIO_WARNING）：
     - 先尝试 `create_temp_pagefile_dynamic()`（NtCreatePagingFile，立即生效）
     - 失败则回退到 `create_temp_pagefile()`（wmic，需重启）
   - **为什么内存压力和提交费用是独立检测的**：两者可以独立出现。内存压力高但提交费用正常（物理 RAM 不够但分页文件还有余量），或者提交费用高但物理内存正常（大量虚拟内存承诺但实际使用不多）。两种情况需要不同的应对策略

#### 5.3.5 find_best_drive_for_pagefile() → str|None

**查找最适合创建临时分页文件的分区。**

选择策略：
1. 遍历所有物理分区（`psutil.disk_partitions(all=False)` 排除虚拟分区如 RAM disk）
2. 排除可用空间 < 8GB 的分区
3. 优先选择非 C 盘中可用空间最大的分区
4. 如果没有合适的非 C 盘分区，回退到 C 盘（前提是 C 盘可用空间 > 8GB）
5. 都不满足则返回 None

**优先非 C 盘的原因**：C 盘通常是系统盘，已经有系统默认的分页文件，且系统运行时会频繁读写 C 盘（临时文件、注册表、日志等）。将临时分页文件放在其他物理磁盘上可以分散 I/O 负载，减少磁盘争用。如果是同一块物理磁盘的不同分区则没有 I/O 分散效果，但至少不会与系统分页文件竞争同一文件系统的空间。

**8GB 最低空间要求**：临时分页文件默认 4GB，加上 20% 余量的增量扩展可能达到 8GB。预留 8GB 确保创建分页文件后磁盘仍有足够空间供正常使用。

#### 5.3.6 create_temp_pagefile_dynamic(size_mb=4096) → str|None

**通过 NtCreatePagingFile 动态创建分页文件（无需重启，立即生效）。**

流程：
1. 调用 `find_best_drive_for_pagefile()` 找到目标分区
2. 构造 NT 路径格式：`"\\??\X:\pagefile.sys"`
3. 启用 `SeCreatePagefilePrivilege` 特权
4. 调用 `nt_create_paging_file(nt_path, size_bytes, size_bytes)`
5. 成功后：记录到 `_created_pagefiles`，调用 `_save_pagefile_info()` 持久化
6. 失败返回 None（调用方会回退到 wmic 方案）

**NtCreatePagingFile 背景**：这是一个未文档化的 ntdll.dll 导出函数，原型为 `NtCreatePagingFile(PUNICODE_STRING PageFileName, PLARGE_INTEGER MinimumSize, PLARGE_INTEGER MaximumSize, PLARGE_INTEGER Priority)`。它直接调用内核的内存管理器创建分页文件，效果等同于系统启动时 smss.exe 创建分页文件的过程，但可以在运行时执行。

**NT 路径格式 `\\??\\`**：NT 内核使用的路径格式与 Win32 路径不同。`\\??\\` 是当前用户的 DOS 设备目录前缀（等价于旧版的 `\\DosDevices\\`），将 Win32 盘符映射到 NT 设备路径。例如 `\\??\C:\pagefile.sys` 在内核中解析为 `\Device\HarddiskVolume1\pagefile.sys`。

**SeCreatePagefilePrivilege 特权**：即使以管理员身份运行，创建分页文件也需要显式启用此特权。Windows 的特权模型是"默认禁用"——管理员令牌中包含此特权但默认未激活，需要通过 `AdjustTokenPrivileges` API 启用。

#### 5.3.7 create_temp_pagefile(size_mb=4096) → str|None

**通过 wmic 创建临时分页文件（需重启生效）。**

两步 wmic 命令：
1. `wmic pagefileset create name="X:\pagefile.sys"` — 在 WMI 中创建分页文件条目（写入注册表 `PagingFiles` 值）
2. `wmic pagefileset where name="X:\\pagefile.sys" set InitialSize=4096,MaximumSize=4096` — 设置大小

**为什么需要两步**：wmic 的 `create` 命令只能创建条目但不能同时设置大小属性，必须先创建再修改。这是 WMI `Win32_PageFileSetting` 类的接口限制。

**wmic 路径中的双反斜杠**：第二条命令的 `where` 子句中路径使用 `X:\\\\pagefile.sys`（Python 字符串中的 `\\\\` 转义为 `\\`）。这是因为 WQL（WMI Query Language）使用反斜杠作为转义字符，所以路径中的 `\` 需要写成 `\\`。

**与 NtCreatePagingFile 的关键区别**：wmic 方式修改的是注册表配置，需要重启后由 smss.exe 读取并创建实际文件。而 NtCreatePagingFile 直接在内核中创建，立即可用。因此 wmic 是 NtCreatePagingFile 失败时的降级方案——虽然不能立即缓解压力，但至少确保下次重启后有更大的分页文件。

#### 5.3.8 remove_all_temp_pagefiles() → list[str]

删除所有本次会话创建的临时分页文件：
- `dynamic` 方式创建的：无法运行时删除，重启后自动消失，直接标记为已移除
- `wmic` 方式创建的：调用 `wmic pagefileset ... delete` 删除配置
- 清空模块级状态和持久化记录

**dynamic 分页文件为什么无法运行时删除**：通过 NtCreatePagingFile 创建的分页文件被内核的内存管理器独占打开（`FILE_SHARE_NONE`），任何用户态进程都无法删除或修改它。Windows 没有提供对应的 `NtDeletePagingFile` API。但这些动态创建的分页文件不会写入注册表的 `PagingFiles` 配置，所以重启后 smss.exe 不会重新创建它们——文件会在重启过程中被自动清理。

**清理顺序的重要性**：先遍历字典逐个处理，再统一清空 `_created_pagefiles` 和重置 `_current_pagefile_size_mb`，最后清除 `AppSettings().pagefile_info`。如果先清空字典再处理，就丢失了需要删除的信息。

#### 5.3.9 expand_pagefile_incremental(threshold_pct=80) → str|None

**智能线性扩展分页文件。**

**设计思想**：不一次性创建一个巨大的分页文件，而是根据实际需求逐步扩展。这样既能及时缓解提交费用压力，又不会浪费磁盘空间。类似于动态数组的增长策略，但有上限保护。

算法：
1. 如果当前累计大小已达 8GB 上限 → 跳过
   - **为什么限制 8GB**：分页文件过大会导致磁盘空间浪费，且超过一定大小后对性能的边际收益递减。8GB 对于绝大多数场景已经足够
2. 计算提交费用比率，如果 ≤ threshold_pct → 跳过
3. 计算需要扩展的大小：
   - `threshold_bytes = commit_limit × threshold_pct / 100`
   - `need_bytes = commit_total - threshold_bytes`（超出阈值的部分）
   - `expand_mb = max(256, need_bytes × 1.2 / 1024²)`（加 20% 余量，最少 256MB）
   - **20% 余量的作用**：避免扩展后立即又触发下一次扩展。如果精确扩展到刚好够用，提交费用稍有增长就会再次超阈值，导致频繁扩展
   - **最少 256MB**：避免创建过小的分页文件，因为每次 NtCreatePagingFile 调用都有固定开销
4. 新总量 = min(当前大小 + expand_mb, 8192)
5. 优先用 NtCreatePagingFile 扩展，失败回退到 wmic
   - **NtCreatePagingFile 的特殊行为**：对同一路径多次调用时，如果新大小大于现有大小，系统会扩展现有分页文件而非报错。这使得增量扩展成为可能——每次调用传入新的总大小即可

**分页文件完整生命周期**：
```
应用启动 → restore_pagefile_state() 恢复上次状态
    ↓
定时器检测 → check_and_auto_optimize() 检测提交费用压力
    ↓
首次创建 → create_temp_pagefile_dynamic() (4GB)
    ↓
持续监控 → expand_pagefile_incremental() 按需扩展（最大 8GB）
    ↓
用户关闭 → remove_all_temp_pagefiles() 清理
    ↓
持久化 → _save_pagefile_info() 保存状态供下次恢复
```

---

## 六、Model 层 — 延迟监控

### 6.1 latency_monitor.py — DPC/ISR 延迟诊断

采用 PDH + ETW 双通道混合方案：PDH 提供可靠的总体百分比，ETW 提供精确到单个驱动的归因。

#### 6.1.1 数据结构

**DriverLatencyInfo**：单个驱动的统计
- `name`：驱动文件名（小写）
- `dpc_count`：DPC 事件计数
- `isr_count`：ISR 事件计数

**LatencySnapshot**：一次采样的完整快照
- `dpc_time_percent`：DPC 占用 CPU 时间百分比（来自 PDH）
- `isr_time_percent`：ISR 占用 CPU 时间百分比（来自 PDH）
- `dpc_queue_length`：DPC 队列速率（每秒排队数，来自 PDH）
- `has_issue`：是否存在延迟问题
- `warnings`：警告消息列表（中文）
- `top_drivers`：按 DPC+ISR 总数降序排列的 top 驱动列表（来自 ETW）
- `etw_available`：ETW 会话是否可用

#### 6.1.2 PDH 通道

**PDH（Performance Data Helper）** 是 Windows 性能计数器的高级 API。它封装了底层的注册表性能数据访问，提供统一的计数器路径语法和格式化输出。

**DPC 和 ISR 的背景知识**：
- **ISR（Interrupt Service Routine，中断服务例程）**：硬件设备（网卡、显卡、USB 控制器等）通过中断通知 CPU 有事件需要处理。ISR 在最高优先级（DIRQL）运行，会抢占所有用户态代码和大部分内核代码。ISR 必须尽快完成（通常 < 100μs），否则会导致其他中断丢失
- **DPC（Deferred Procedure Call，延迟过程调用）**：ISR 中不适合做的耗时工作（如数据包处理、缓冲区拷贝）会被排入 DPC 队列，在稍低的优先级（DISPATCH_LEVEL）执行。DPC 仍然高于所有用户态线程，如果 DPC 执行时间过长，用户会感受到音频卡顿、鼠标不流畅、视频掉帧
- **为什么监控 DPC/ISR**：DPC/ISR 时间过长是 Windows 系统卡顿的常见原因，通常由有问题的驱动程序导致。用户感知到的"系统卡"很多时候不是 CPU 不够用，而是 DPC/ISR 霸占了 CPU 时间

**使用的三个计数器**：
- `\Processor(_Total)\% DPC Time` — 所有处理器花在 DPC 上的时间百分比
- `\Processor(_Total)\% Interrupt Time` — 所有处理器花在 ISR 上的时间百分比
- `\Processor(_Total)\DPCs Queued/sec` — 每秒排队的 DPC 数量

**初始化流程**（_open_pdh）：
1. `PdhOpenQueryW(None, 0, &query)` 创建查询句柄。第一个参数 None 表示从本机实时数据源读取（而非日志文件）
2. 对每个计数器路径调用 `PdhAddCounterW(query, path, 0, &counter)` 添加到查询。返回的 counter 句柄用于后续取值
3. 调用一次 `PdhCollectQueryData(query)` 预热。**预热的必要性**：PDH 的百分比计数器需要两次采集的差值才能计算。首次采集建立基线，第二次采集才能返回有意义的值（与 psutil 的 cpu_percent 预热原理相同）

**采样流程**（_sample_pdh）：
1. `PdhCollectQueryData(query)` 采集新数据
2. 对每个计数器调用 `PdhGetFormattedCounterValue(handle, PDH_FMT_DOUBLE, None, &fmt_value)` 获取双精度浮点值
3. `PDH_FMT_DOUBLE = 0x200` 指定输出格式为 double。`_PDH_FMT_COUNTERVALUE` 结构体包含 `CStatus`（状态码）和 `doubleValue`（值）两个字段

**警告阈值**：
- DPC 时间 > 3.0% → 警告。正常系统 DPC 时间通常 < 1%，超过 3% 说明有驱动在 DPC 中做了过多工作
- ISR 时间 > 2.0% → 警告。正常系统 ISR 时间通常 < 0.5%，超过 2% 说明有硬件中断处理异常

#### 6.1.3 ETW 通道

**ETW（Event Tracing for Windows）** 是 Windows 内核级事件追踪框架，可以捕获每个 DPC/ISR 事件的回调地址。

**ETW 架构概述**：ETW 由三个角色组成：
- **Provider（提供者）**：产生事件的组件。内核本身是最重要的 Provider，通过 SystemTraceControlGuid 标识
- **Session（会话）**：内核中的事件缓冲区管理器。Provider 将事件写入 Session 的缓冲区
- **Consumer（消费者）**：读取事件的应用程序。通过 `OpenTraceW` + `ProcessTrace` 实时消费事件

本模块的角色是 Consumer：启动一个内核追踪 Session，让内核 Provider 产生 DPC/ISR 事件，然后实时消费这些事件。

**核心原理**：
1. 启动一个内核追踪会话，启用 DPC 和中断事件标志
2. 每个 DPC/ISR 事件的 UserData 首 8 字节包含回调函数的内核地址
3. 通过二分查找将地址映射到具体的内核驱动模块
4. 统计每个驱动的 DPC/ISR 事件数量

**_DriverMapper — 地址到驱动名映射器**：
- 初始化时调用 `enum_kernel_modules()` 获取所有内核模块的基地址和名称
- `lookup(addr)` 方法：使用二分查找（`bisect_right`）找到地址所属的模块
  - 原理：模块按基地址升序排列，`bisect_right(bases, addr) - 1` 得到最后一个基地址 ≤ addr 的模块

**_EtwDpcSession — ETW 实时会话**：

**启动流程**：
1. 启用 `SeSystemProfilePrivilege` 特权。这是内核追踪所需的特权，普通管理员令牌中存在但默认禁用，需要通过 `AdjustTokenPrivileges` 显式启用
2. 尝试两种会话模式：
   - 首选：自定义会话名 `"PrismCore_DpcIsr"` + `EVENT_TRACE_SYSTEM_LOGGER_MODE` 标志
   - 回退：`"NT Kernel Logger"` 经典会话名（不使用 SYSTEM_LOGGER_MODE）
   - **为什么需要两种模式**：Windows Vista+ 引入了 `SYSTEM_LOGGER_MODE`，允许多个会话同时追踪内核事件（每个会话用自定义名称）。但某些旧版 Windows 或特殊配置下此模式不可用。经典的 `"NT Kernel Logger"` 是系统保留的唯一内核追踪会话名，全局只能有一个，但兼容性最好
3. 对每种模式：先停止同名旧会话（`ControlTraceW` + `EVENT_TRACE_CONTROL_STOP`），再启动新会话。**先停后启的原因**：如果上次应用崩溃未正常关闭，旧会话可能仍在运行，同名会话无法重复启动
4. 构造 `EVENT_TRACE_PROPERTIES` 变长结构体：
   - `Wnode.Guid` = SystemTraceControlGuid `{9e814aad-3204-11d2-9a82-006008a86939}`。这个 GUID 标识内核追踪 Provider
   - `Wnode.ClientContext = 1`（QPC 高精度时钟）。值 1 表示使用 QueryPerformanceCounter 作为时间戳源，精度约 100ns。值 2 表示系统时间（精度约 10ms），值 3 表示 CPU 周期计数器
   - `Wnode.Flags = WNODE_FLAG_TRACED_GUID`（0x20000）。标识这是一个追踪 GUID 而非 WMI GUID
   - `EnableFlags = EVENT_TRACE_FLAG_DPC | EVENT_TRACE_FLAG_INTERRUPT`（0x20 | 0x40 = 0x60）。位掩码，告诉内核只产生 DPC 和中断相关事件，不产生进程/线程/磁盘等其他事件，减少开销
   - `LogFileMode = EVENT_TRACE_REAL_TIME_MODE`（0x100）。实时模式，事件直接传递给消费者回调，不写入日志文件
   - `BufferSize = 64`（KB）。每个事件缓冲区的大小。内核在内存中维护多个缓冲区轮转使用
   - `LoggerNameOffset = sizeof(EVENT_TRACE_PROPERTIES)`。会话名存储在结构体末尾的变长缓冲区中，这个偏移量指向会话名的起始位置
   - **变长结构体的内存布局**：`[EVENT_TRACE_PROPERTIES 固定部分][会话名 wchar 缓冲区 256×2 字节]`。总大小 = sizeof(props) + 512 字节。必须用 `(c_ubyte * total)()` 分配连续内存，再用 `from_buffer` 将结构体映射到缓冲区头部
5. `StartTraceW(&handle, session_name, &props)` 启动会话。成功返回 0，handle 用于后续控制
6. `OpenTraceW(&logfile)` 打开实时消费句柄，注册事件回调
7. 启动后台守护线程运行 `ProcessTrace`（阻塞调用，直到会话停止）

**事件回调**（_on_event）：

回调函数签名为 `void callback(EVENT_RECORD*)` ，由 ProcessTrace 在后台线程中调用。

1. 检查事件 Opcode（位于 `EventHeader.EventDescriptor.Opcode`）：
   - 66 = DPC（普通 DPC，由驱动调用 `KeInsertQueueDpc` 排入）
   - 67 = Timer DPC（定时器到期触发的 DPC，由 `KeSetTimer` 注册）
   - 50 = ISR（硬件中断服务例程）
   - 其他 → 忽略（如线程调度、上下文切换等事件）
2. 从 UserData 首 8 字节读取回调地址（uint64）。**这个地址是 DPC/ISR 回调函数在内核地址空间中的虚拟地址**。例如 NVIDIA 驱动的 DPC 回调地址会落在 `nvlddmkm.sys` 的加载范围内。读取方式：`ctypes.c_uint64.from_address(rec.UserData).value`
3. 调用 `_mapper.lookup(addr)` 获取驱动名
4. 在线程安全的统计字典中累加计数。使用 `threading.Lock` 保护，因为回调在 ETW 后台线程中执行，而 `flush_top()` 在主线程中调用

**GC 防护的关键细节**：回调函数对象 `self._callback = _EVENT_RECORD_CALLBACK(self._on_event)` 必须保存为实例属性。如果只作为局部变量传给 `OpenTraceW`，Python 的垃圾回收器可能在 ProcessTrace 运行期间回收这个 ctypes 回调对象，导致回调地址变成野指针，引发段错误（SIGSEGV）。

**ProcessTrace 的阻塞特性**：`ProcessTrace` 是一个阻塞调用，它会持续从内核缓冲区读取事件并调用回调函数，直到会话被停止（`CloseTrace` 关闭消费句柄）。因此必须在独立的守护线程（`daemon=True`）中运行，否则会阻塞主线程。守护线程在主进程退出时自动终止，无需显式 join。

**停止流程**：先调用 `CloseTrace(trace_handle)` 关闭消费句柄（使 ProcessTrace 返回），再调用 `ControlTraceW(0, name, &props, STOP)` 停止内核会话。顺序不能反——如果先停止会话，ProcessTrace 可能因为缓冲区中还有未消费的事件而挂起。

**flush_top(n=5)**：获取 top-N 驱动统计并重置计数器。在锁保护下拷贝统计字典并清空，然后按 DPC+ISR 总数降序排列。**清空的原因**：每次采样周期（通常 2 秒）获取一次统计，清空后下次采样反映的是最新周期的数据，而非累计值。

**LatencyMonitor 类 — PDH+ETW 的统一门面**：

LatencyMonitor 是对外暴露的公共接口，封装了 PDH 和 ETW 两个通道的生命周期管理和数据聚合。ViewModel 只需调用 `open()`、`sample()`、`close()` 三个方法，无需了解底层的 PDH 计数器操作和 ETW 会话管理。

**open() → bool**：
1. 调用 `_open_pdh()` 初始化 PDH 查询和计数器。返回值决定 `_pdh_ok` 标志
2. 创建 `_EtwDpcSession` 实例并调用 `start()`。ETW 启动失败不影响 PDH——`_etw` 设为 None，`_etw_available` 设为 False
3. 返回 PDH 是否成功。**PDH 优先级高于 ETW 的原因**：PDH 提供的是总体百分比（用于判断是否有问题），ETW 提供的是驱动归因（用于定位问题来源）。没有 ETW 仍然可以告诉用户"DPC 延迟偏高"，只是无法告诉"是哪个驱动导致的"

**sample() → LatencySnapshot**：
1. 创建空的 LatencySnapshot
2. 如果 PDH 可用 → 调用 `_sample_pdh(snap)` 填充百分比数据
3. 如果 ETW 可用 → 调用 `_etw.flush_top(5)` 获取 top-5 驱动统计
4. 调用 `_evaluate(snap)` 生成警告消息
5. 返回完整快照

**_evaluate(snap) — 警告生成逻辑**：
- 如果 DPC 时间 > 3.0%：设置 `has_issue=True`，调用 `_format_top_drivers` 获取 DPC 类型的 top 驱动。如果有驱动信息则生成"DPC 延迟偏高 (X.X%)，主要来自: 驱动名"；否则生成通用警告
- 如果 ISR 时间 > 2.0%：同理，但针对 ISR 类型
- **PDH 判定 + ETW 归因的协作模式**：PDH 负责"是否有问题"的判定（阈值比较），ETW 负责"问题在哪"的归因（驱动名称）。两者独立工作——即使 ETW 不可用，PDH 仍然可以发出警告

**_format_top_drivers(drivers, kind) → str**：
- 按 kind（"dpc" 或 "isr"）过滤出对应计数 > 0 的驱动
- 对每个驱动，查找 `_KNOWN_DPC_DRIVERS` 映射表。如果驱动名（去掉 .sys 后缀）在映射表中，使用中文建议文字；否则直接显示驱动文件名
- 最多取前 3 个，用中文顿号"、"连接

**diagnose_dpc_drivers() → str**：
兼容旧接口的独立函数。不依赖 ETW 实时会话，而是通过 `enum_kernel_modules()` 获取当前加载的内核模块列表，与 `_KNOWN_DPC_DRIVERS` 映射表做模式匹配。如果某个已加载的驱动名包含映射表中的关键字，就将其建议文字加入结果。用 `seen` 集合去重（同一驱动可能有多个模块），最多返回 3 条建议。这个函数的局限性在于它只能告诉"系统中存在哪些已知的高延迟驱动"，而不能告诉"当前哪个驱动正在产生高延迟"——后者需要 ETW 实时监控。

**已知高延迟驱动映射表**（_KNOWN_DPC_DRIVERS）：
将驱动文件名（去掉 .sys 后缀）映射为中文建议，例如：
- `nvlddmkm` → "NVIDIA 显卡驱动（建议更新或关闭后台录制）"
- `rtwlane` → "Realtek 无线网卡驱动（建议更新或禁用节能）"
- `tcpip` → "TCP/IP 协议栈（建议检查网络负载）"
等共 13 个已知驱动模式。

---

## 七、Model 层 — 清理引擎

### 7.1 cleaner.py — 智能清理引擎

#### 7.1.1 数据结构

**CleanItem**：单个可清理项
- `path`：文件或目录路径
- `size`：大小（字节）
- `category`：类别字符串，取值 `"electron"` | `"temp"` | `"large_file"` | `"recycle_bin"` | `"update_cache"` | `"old_driver"` | `"orphan_reg"` | `"compact_os"`
- `description`：人类可读描述
- `selected`：是否默认选中（大文件中只有临时扩展名的默认选中）

**ScanResult**：扫描结果汇总
- `items`：CleanItem 列表
- `total_size`（计算属性）：所有已选中项的总大小
- `count`（计算属性）：已选中项的数量

#### 7.1.2 Electron 缓存识别算法

**背景知识 — 为什么专门识别 Electron 应用**：Electron 是基于 Chromium 的桌面应用框架（VS Code、Discord、Slack、Teams 等都是 Electron 应用）。每个 Electron 应用都内嵌一个完整的 Chromium 浏览器引擎，会在 `%APPDATA%` 或 `%LOCALAPPDATA%` 下创建大量缓存目录。单个应用的缓存可达数百 MB 到数 GB，且这些缓存是可安全删除的（应用会自动重建）。

**_has_electron_signature(directory) → bool**

判断一个目录是否为 Electron 应用数据目录的两阶段算法：

1. **快速特征检测**：列出目录的所有子目录名，检查是否同时包含 `"Cache"` 和 `"GPUCache"` 两个子目录。这是 Chromium 内核的标志性目录结构——所有基于 Chromium 的应用（Chrome、Edge、Electron 应用）都会创建这两个缓存目录。但仅凭此特征无法区分 Electron 应用和 Chrome 浏览器本身。

2. **精确确认**：在前两级子目录中搜索 `.asar` 文件。`.asar` 是 Electron 特有的应用打包格式（类似 tar，将应用的 JS/HTML/CSS 打包为单个文件）。Chrome/Edge 不会有 `.asar` 文件，因此这是 Electron 应用的确定性标志。限制搜索深度为两级是为了避免在大型目录树中浪费时间。

**scan_electron_caches() → list[CleanItem]**

扫描流程：
1. 确定搜索根目录：`%APPDATA%` 和 `%LOCALAPPDATA%`
2. 对每个根目录，遍历其直接子目录
3. 对每个子目录，检查它本身及其下一级子目录是否具有 Electron 签名
4. 对确认的 Electron 应用目录，遍历 ELECTRON_CACHE_DIRS 列表中的缓存子目录名
5. 如果缓存子目录存在且大小 > 0，创建 CleanItem

#### 7.1.3 临时文件扫描

**scan_temp_files() → list[CleanItem]**

1. 收集临时目录：`%TEMP%`、`%TMP%`、`%SYSTEMROOT%\Temp`
2. 对每个临时目录，遍历其直接子项（文件和目录）
3. 文件直接记录大小，目录使用 `_dir_size()` 计算总大小
4. 所有临时文件/目录默认选中

**三个临时目录的区别**：
- `%TEMP%` / `%TMP%`：通常指向 `C:\Users\<用户名>\AppData\Local\Temp`，是当前用户的临时目录。两个环境变量通常指向同一路径，但代码用 `set()` 去重避免重复扫描
- `%SYSTEMROOT%\Temp`：即 `C:\Windows\Temp`，是系统级临时目录，服务进程和 SYSTEM 账户使用。清理此目录需要管理员权限

**只遍历直接子项而非递归的原因**：临时目录的直接子项通常是独立的临时文件或临时子目录（如安装程序解压的临时文件夹）。递归遍历每个文件会产生大量 CleanItem，UI 表格难以展示。将子目录作为整体呈现（显示总大小），用户可以一次性选择删除整个临时子目录。

**_dir_size(path) → int**：使用栈模拟（非递归）遍历目录树，累加所有文件大小。避免深层递归导致栈溢出。与 system_cleaner.py 中的同名函数实现相同（见 7.3.6）。

#### 7.1.4 大文件扫描（MFT 优先 + os.walk 回退）

**scan_large_files(root, threshold, max_results) → list[CleanItem]**

**双策略扫描设计**：这是一个典型的"优雅降级"模式——优先使用高性能方案，失败时自动回退到通用方案。

1. **优先尝试 MFT 快速扫描**（`_scan_large_files_mft`）：
   - 调用 `mft_scanner.scan_mft_large_files()` 直接读取 NTFS 主文件表
   - 速度比传统遍历快几个数量级（全盘扫描从分钟级降到秒级）
   - 需要管理员权限且仅支持 NTFS 文件系统，失败时返回 None

2. **回退到 os.walk 遍历**（`_scan_large_files_walk`）：
   - **跳过系统目录**：`Windows`、`Program Files`、`Program Files (x86)`、`$` 开头的目录（如 `$Recycle.Bin`、`$WinREAgent`）。这些目录包含系统文件，不应被用户删除，且遍历它们会浪费大量时间
   - 对每个文件用 `os.path.getsize()` 检查大小是否 ≥ threshold（默认 500MB）
   - `os.walk` 的 `onerror` 参数设为忽略，跳过无权限的目录

**大文件的默认选中逻辑**：只有扩展名在 TEMP_EXTENSIONS 集合中的大文件默认选中，其他大文件默认不选中（需用户手动确认）。

#### 7.1.5 清理执行

**execute_clean(items) → (cleaned_bytes, failed_count)**

对每个已选中的 CleanItem 执行删除。返回二元组：实际释放的字节数和失败的项目数。

**分类处理策略**：
- `recycle_bin` 类别：调用 `empty_recycle_bin()`（Shell API 一次性清空，比逐文件删除高效）
- 目录：调用 `_safe_remove_tree()`（自底向上删除，跳过被占用的文件）
- 文件：调用 `_safe_remove_file()`
- 路径已不存在：视为已清理（可能被其他程序或用户手动删除），计入 cleaned_bytes

**_safe_remove_tree(path) → int**：

**为什么不直接用 `shutil.rmtree()`**：`rmtree` 遇到任何一个无法删除的文件就会抛出异常并中止整个操作。而实际场景中，一个缓存目录里可能有几百个文件，其中只有一两个被进程锁定。`_safe_remove_tree` 采用"尽力而为"策略——自底向上遍历（`os.walk(topdown=False)`），逐个删除文件，失败的跳过继续处理下一个。最后尝试删除空目录（如果所有文件都删除成功，目录就是空的）。返回实际释放的字节数。

**_is_path_locked(path) → bool**：通过 `psutil.process_iter(['open_files'])` 遍历所有进程的打开文件列表，检查是否有进程持有目标路径的文件句柄。这是一个开销较大的操作（需要遍历所有进程），因此只在需要时调用（如判断删除失败的原因）。

### 7.2 mft_scanner.py — MFT 快速文件扫描

通过直接读取 NTFS 主文件表（Master File Table）实现毫秒级大文件检索，速度比 os.walk 快几个数量级。需要管理员权限。

#### 7.2.1 背景知识

NTFS 文件系统将所有文件和目录的元数据存储在 MFT 中。每个文件对应一条 MFT 记录，包含文件名、父目录引用号、属性等。通过 `DeviceIoControl` 的 `FSCTL_ENUM_USN_DATA` 控制码可以直接枚举所有 MFT 记录，无需逐目录遍历。

**为什么 MFT 扫描比 os.walk 快几个数量级**：
- `os.walk` 的工作方式是：打开目录 → 读取目录项 → 对每个子目录递归。每次打开目录都是一次文件系统操作，涉及路径解析、权限检查、目录索引查找。一个有 100 万文件的磁盘可能有 10 万个目录，需要 10 万次目录打开操作
- MFT 扫描直接通过 `DeviceIoControl` 顺序读取 MFT 表，MFT 在磁盘上是连续存储的（或接近连续），一次 64KB 的读取可以获取数百条记录。整个扫描只需要几百次 I/O 操作，而非几十万次
- 实测对比：100 万文件的 C 盘，os.walk 需要 30-60 秒，MFT 扫描只需要 1-3 秒

**USN Journal（更新序列号日志）**：NTFS 维护一个变更日志，记录文件系统的每次修改（创建、删除、重命名等）。`FSCTL_ENUM_USN_DATA` 实际上是枚举 MFT 中所有活跃记录的 USN 信息，而非读取 USN 日志本身。这个控制码的名字容易误导——它枚举的是 MFT 记录，只是返回格式是 USN_RECORD。

**文件引用号（File Reference Number）**：每个 MFT 记录有一个 64 位的文件引用号。低 48 位是 MFT 记录索引（即该文件在 MFT 表中的位置），高 16 位是序列号（每次该 MFT 槽位被复用时递增，用于检测过期引用）。代码中用 `& 0x0000FFFFFFFFFFFF` 提取低 48 位作为唯一标识。

#### 7.2.2 Windows API 常量

- `GENERIC_READ = 0x80000000`
- `FILE_SHARE_READ = 0x01`, `FILE_SHARE_WRITE = 0x02`
- `OPEN_EXISTING = 3`
- `FSCTL_ENUM_USN_DATA = 0x000900B3` — 枚举 MFT 记录
- `FSCTL_QUERY_USN_JOURNAL = 0x000900F4` — 查询 USN 日志信息
- `FILE_ATTRIBUTE_DIRECTORY = 0x10`

#### 7.2.3 数据结构

**USN_JOURNAL_DATA**：USN 日志元数据
- `UsnJournalID`（uint64）、`FirstUsn`（int64）、`NextUsn`（int64）等

**MFT_ENUM_DATA_V0**：枚举请求参数
- `StartFileReferenceNumber`（uint64）：起始文件引用号
- `LowUsn`（int64）：USN 下界（设为 0）
- `HighUsn`（int64）：USN 上界（设为 journal.NextUsn）

**USN_RECORD_V2**：单条 USN 记录
- `RecordLength`（DWORD）：记录总长度
- `FileReferenceNumber`（uint64）：文件引用号
- `ParentFileReferenceNumber`（uint64）：父目录引用号
- `FileAttributes`（DWORD）：文件属性
- `FileNameLength`（WORD）：文件名字节长度
- `FileNameOffset`（WORD）：文件名在记录中的偏移
- 文件名以 UTF-16LE 编码存储在记录末尾

**MftFileEntry**：扫描结果条目
- `path`：完整文件路径
- `size`：文件大小（字节）
- `is_directory`：是否为目录

#### 7.2.4 扫描流程

**第一步：打开卷句柄**
- 调用 `CreateFileW` 打开 `\\.\X:`（X 为盘符），需要 `GENERIC_READ` 权限
- **路径格式说明**：`\\.\` 是 Win32 设备命名空间前缀，`C:` 是卷的符号链接名。合起来 `\\.\C:` 表示"直接访问 C 盘卷设备"，绕过文件系统层。这与打开普通文件（如 `C:\file.txt`）不同——后者经过文件系统驱动，前者直接与卷管理器通信
- `FILE_SHARE_READ | FILE_SHARE_WRITE` 允许其他进程同时读写该卷（否则会独占卷导致系统无法正常运行）

**第二步：查询 USN 日志**
- 调用 `DeviceIoControl`（控制码 `FSCTL_QUERY_USN_JOURNAL`）获取日志元数据
- 主要需要 `NextUsn` 值作为枚举的上界。`NextUsn` 是下一个将被分配的 USN 值，所有现有记录的 USN 都小于它

**第三步：枚举所有 MFT 记录**
- 构造 `MFT_ENUM_DATA_V0`：`StartFileReferenceNumber=0, LowUsn=0, HighUsn=journal.NextUsn`
- 循环调用 `DeviceIoControl`（控制码 `FSCTL_ENUM_USN_DATA`），每次读取 64KB 缓冲区
- **缓冲区内存布局**：
  ```
  [8 字节: 下一次枚举的起始引用号(uint64)]
  [USN_RECORD_V2 #1: 变长记录]
  [USN_RECORD_V2 #2: 变长记录]
  ...（直到 bytes_returned 边界）
  ```
- 每条 USN_RECORD_V2 是变长的：固定头部 + 变长文件名。`RecordLength` 字段指示整条记录的总字节数，用于跳到下一条记录
- **文件名提取**：文件名从记录起始偏移 `FileNameOffset` 处开始，长度为 `FileNameLength` 字节，编码为 UTF-16LE。注意 `FileNameOffset` 是相对于记录起始的偏移，而非缓冲区起始。因此在缓冲区中的绝对偏移 = 记录在缓冲区中的偏移 + FileNameOffset
- 对每条记录提取：文件引用号（低 48 位）、父目录引用号（低 48 位）、文件名、是否为目录
- 存入内存映射表：`file_ref → (name, parent_ref, is_dir, 0)`
- 更新 `StartFileReferenceNumber` 为缓冲区前 8 字节的值，继续下一轮
- **终止条件**：`DeviceIoControl` 返回 False 或 `bytes_returned ≤ 8`（只有下一个引用号，没有实际记录）

**第四步：构建完整路径**
- 递归函数 `_build_path(ref)`：通过父目录引用号链式拼接路径
- **算法本质**：MFT 记录只存储文件名和父目录引用号，不存储完整路径。要得到完整路径，必须从文件沿父目录链向上回溯到根目录。例如：文件 `report.docx`（父=目录A）→ 目录A `Documents`（父=目录B）→ 目录B `Users`（父=根）→ 拼接为 `Users\Documents\report.docx`
- 使用路径缓存（`path_cache: dict[int, str]`）避免重复计算。同一目录下的多个文件共享父路径，缓存命中率很高
- 递归深度限制 64 层防止循环引用（损坏的 MFT 可能出现 A→B→A 的循环）
- **两遍扫描的原因**：第一遍枚举 MFT 构建 file_map，第二遍构建路径。不能在第一遍中构建路径，因为父目录的记录可能还没被枚举到（MFT 记录不保证按目录层级顺序排列）

**第五步：获取文件大小并过滤**
- 对每个非目录文件，调用 `GetCompressedFileSizeW(path, &high)` 获取实际占用大小
- **为什么用 GetCompressedFileSizeW 而非 GetFileSize**：`GetFileSize` 返回文件的逻辑大小（即应用程序看到的大小），而 `GetCompressedFileSizeW` 返回文件在磁盘上的实际占用大小。对于 NTFS 压缩文件或稀疏文件，实际占用可能远小于逻辑大小。用实际占用大小更能反映磁盘空间消耗
- **64 位大小的拼接**：`GetCompressedFileSizeW` 返回低 32 位（返回值）和高 32 位（通过指针参数）。完整大小 = `(high << 32) | low`。注意每次调用后必须重置 `high.value = 0`，否则上次的高位会残留
- **错误处理**：如果返回值为 `0xFFFFFFFF` 且 `GetLastError() != 0`，说明文件不可访问（已删除、权限不足等），跳过
- 过滤出大小 ≥ min_size_bytes 的文件
- 按大小降序排列，限制最大返回数量（默认 500）

### 7.3 system_cleaner.py — 系统级清理

处理 WinSxS 组件存储、驱动商店、CompactOS、注册表孤立项、Windows Update 缓存五类系统级清理。

#### 7.3.1 SystemCleanResult 数据结构

- `action`：操作名称
- `success`：是否成功
- `message`：结果描述
- `freed_bytes`：释放的字节数（默认 0）

#### 7.3.2 cleanup_winsxs(aggressive=False) → SystemCleanResult

调用 `Dism.exe /Online /Cleanup-Image /StartComponentCleanup` 清理 WinSxS 组件存储。`aggressive=True` 时追加 `/ResetBase` 参数（不可逆，删除所有旧版本组件）。超时 600 秒。

**WinSxS 组件存储的背景**：`C:\Windows\WinSxS` 是 Windows 的组件存储（Side-by-Side Assembly Store），存放系统组件的所有版本。每次 Windows Update 安装补丁时，旧版本组件会保留在 WinSxS 中以支持回滚。随着时间推移，WinSxS 可能膨胀到 10GB 以上。

**两种清理模式的区别**：
- `/StartComponentCleanup`（普通模式）：删除已被取代且超过 30 天的旧版本组件。安全，不影响回滚能力
- `/StartComponentCleanup /ResetBase`（激进模式）：删除所有旧版本组件，包括最近安装的补丁的旧版本。**不可逆**——执行后无法卸载任何已安装的 Windows Update。释放空间更多但牺牲了回滚能力

#### 7.3.3 驱动商店清理

**背景知识 — Windows 驱动商店（Driver Store）：**

Windows 驱动商店位于 `%SYSTEMROOT%\System32\DriverStore\FileRepository`，是所有已安装驱动包的本地缓存。每次安装或更新驱动时，Windows 会将完整的驱动包（.inf + .sys + .cat 等）复制到此目录，并以 `oem<N>.inf` 的形式注册到 PnP 管理器。问题在于：驱动更新后旧版本不会自动删除，长期积累可能占用数 GB 空间。例如显卡驱动每次更新都会留下旧版本，一个 NVIDIA 驱动包可能就有 500MB+。

**list_old_drivers() → list[dict]**

枚举驱动商店中的旧版本驱动：

1. 调用 `pnputil /enum-drivers` 获取所有已注册的第三方驱动信息

2. **位置解析策略（locale 无关）：** 这是本函数最关键的设计决策。`pnputil` 的输出格式因 Windows 语言而异——英文系统输出 `Published Name:`，中文系统输出 `发布名称:`，日文系统又不同。如果按字段名匹配（如搜索 "Published Name"），代码只能在特定语言的 Windows 上工作。

   解决方案：**完全忽略字段名，只依赖字段的位置顺序。** pnputil 的输出有一个跨语言不变量：每条驱动记录由空行分隔，且字段顺序固定为：
   - 字段 0：发布名称（如 `oem12.inf`）
   - 字段 1：原始名称
   - 字段 2：提供程序名称
   - 字段 3：类名（如 `Display adapters`）
   - 字段 4：类 GUID
   - 字段 5：驱动版本
   - 字段 6：签名者名称

   解析算法：对每个文本块，逐行查找包含 `:` 的行，取 `:` 右侧的值，按出现顺序存入数组。这样无论字段名是什么语言，`fields[0]` 始终是 inf 名称，`fields[3]` 始终是类名。

3. **过滤条件**：字段数 < 4 的块被跳过（可能是标题行或空块）

4. **分组淘汰算法**：按 `class`（设备类别）排序后用 `itertools.groupby` 分组。同一类别内如果有多个驱动包，保留列表中最后一个（假设为最新），其余标记为可删除。注意：这里的"最新"判断是基于排序后的自然顺序，而非严格的版本号比较——这是一个简化假设，对大多数场景足够准确，因为 oem 编号通常随安装时间递增。

5. **安全性**：`pnputil /delete-driver` 默认只删除未被任何设备使用的驱动包（不带 `/force` 标志），因此不会影响当前正在使用的驱动。

**delete_driver(inf_name) → bool**：调用 `pnputil /delete-driver <inf_name>` 删除指定驱动包。不使用 `/force` 标志，如果驱动正在被设备使用，删除会失败（安全保护）。

#### 7.3.4 CompactOS

**背景知识 — CompactOS 压缩机制：**

CompactOS 是 Windows 10 引入的系统文件透明压缩功能。它使用 XPRESS Huffman 算法（LZX 的轻量变体）对 `%SYSTEMROOT%` 下的系统二进制文件（.exe、.dll 等）进行压缩存储。与传统 NTFS 压缩不同，CompactOS 压缩是在文件系统层之上、由 Windows 引导加载器和内核特殊处理的——压缩后的文件在磁盘上占用更少空间，但读取时由内核透明解压，对应用程序完全不可见。

典型压缩效果：可节省 1.5~2.5GB 磁盘空间。代价是轻微的 CPU 开销（解压），但在现代 CPU 上几乎不可感知，且由于减少了磁盘 I/O，在 HDD 上甚至可能提升启动速度。

**should_compact_os() → bool**：检查 C 盘可用空间是否 < `DISK_CRITICAL_BYTES`（10GB）。只在磁盘空间真正紧张时才建议启用，因为压缩过程本身需要临时空间且耗时较长。

**enable_compact_os() → SystemCleanResult**：调用 `compact.exe /CompactOS:always` 启用压缩。超时设为 600 秒（10 分钟），因为需要逐个压缩数千个系统文件。`/CompactOS:always` 表示强制启用，即使系统认为不需要。

**query_compact_os_status() → bool**：调用 `compact.exe /CompactOS:query` 查询当前状态。输出文本因语言而异——中文系统包含"未"字表示未压缩，英文系统包含 "not" 表示未压缩。返回 True 表示"未压缩，可以压缩"。这里的双语言检测（"未" 和 "not"）是为了兼容中英文 Windows。

#### 7.3.5 注册表孤立项清理

**scan_orphan_registry() → list[dict]**

扫描三类注册表孤立项。核心思路：注册表中存储了大量指向文件系统的引用（DLL 路径、EXE 路径、安装目录），当对应的文件被删除（如卸载软件不干净）但注册表项残留时，就产生了"孤立项"。这些孤立项不仅浪费注册表空间，还可能导致系统在查找 COM 组件或应用路径时产生不必要的文件系统探测，影响性能。

1. **CLSID 孤立项**（_scan_clsid_orphans）：

   **COM 背景知识**：CLSID（Class Identifier）是 Windows COM（组件对象模型）的核心概念。每个 COM 组件都有一个全局唯一的 GUID 作为 CLSID，注册在 `HKCR\CLSID\{GUID}` 下。当应用程序需要创建 COM 对象时，系统通过 CLSID 查找注册表，找到 `InProcServer32` 子键中记录的 DLL 路径，加载该 DLL 并调用其 `DllGetClassObject` 导出函数。

   **InProcServer32 的含义**：`InProcServer32` 表示"进程内服务器，32/64位"，即该 COM 组件以 DLL 形式加载到调用者进程空间内（与之对应的 `LocalServer32` 表示独立 EXE 进程）。默认值（空字符串键名）存储的就是 DLL 的完整路径。

   **扫描逻辑**：
   - 用 `winreg.EnumKey` 逐个枚举 `HKCR\CLSID` 下的子键（每个子键名是一个 GUID）
   - 对每个 GUID，尝试打开 `{GUID}\InProcServer32` 子键
   - 读取默认值（`winreg.QueryValueEx(key, "")`，空字符串表示默认值）
   - 用 `os.path.expandvars()` 展开路径中的环境变量（如 `%SystemRoot%`）
   - 检查展开后的路径是否存在于文件系统
   - 不存在 → 该 CLSID 的 COM 组件已失效，记录为孤立项

   **为什么只检查 InProcServer32**：这是最常见的 COM 注册形式，覆盖了绝大多数第三方 COM 组件。`LocalServer32`（独立进程 COM）相对少见且通常由系统组件使用，误删风险更高。

2. **App Paths 孤立项**（_scan_app_paths_orphans）：

   **App Paths 的作用**：`HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths` 是 Windows Shell 的应用程序路径注册表。当用户在"运行"对话框或开始菜单中输入程序名（如 `chrome.exe`）时，Shell 会先查找此注册表来定位完整路径，而不仅仅依赖 PATH 环境变量。每个子键名是程序文件名，默认值是完整路径。

   **扫描逻辑**：枚举所有子键，读取默认值（EXE 路径），展开环境变量后检查文件是否存在。程序已卸载但 App Paths 残留的情况很常见。

3. **卸载信息孤立项**（_scan_uninstall_orphans）：

   **Uninstall 键的作用**：`HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall` 是"控制面板 → 程序和功能"列表的数据源。每个子键代表一个已安装的程序，`InstallLocation` 值记录安装目录。当程序被手动删除（直接删文件夹而非通过卸载程序）时，这些注册表项会残留。

   **扫描逻辑**：枚举所有子键，读取 `InstallLocation` 值（注意：不是所有程序都设置了此值，`QueryValueEx` 可能抛出 `OSError`，需要捕获）。对非空值展开环境变量后检查目录是否存在。额外检查 `loc.strip()` 非空，因为有些程序会写入空字符串。

每个孤立项返回：`{"key": 注册表路径, "type": 类型, "ref": 引用的文件/目录路径}`

**遍历模式说明**：三个扫描函数都使用相同的 `while True` + `EnumKey` + 递增索引 + `OSError` 终止的模式。这是 Windows 注册表 API 的标准枚举方式——`EnumKey(key, i)` 在索引超出范围时抛出 `OSError`，以此作为循环终止条件。

**backup_and_delete_key(key_path) → bool**：

安全删除策略——先备份再删除：
1. 在 `%LOCALAPPDATA%\PrismCore\RegBackup\` 目录下创建备份文件。文件名由注册表路径转换而来（`\` 和 `/` 替换为 `_`），扩展名为 `.reg`
2. 调用 `reg export <key_path> <backup_file> /y` 导出为标准 .reg 格式（可双击导入恢复）
3. 导出成功后，调用 `reg delete <key_path> /f` 强制删除（`/f` 跳过确认提示）
4. 如果导出或删除任一步骤失败，返回 False，不会出现"删了但没备份"的情况（导出失败时不会执行删除）

#### 7.3.6 Windows Update 缓存

**背景知识 — SoftwareDistribution 目录：**

`%SYSTEMROOT%\SoftwareDistribution` 是 Windows Update 服务（wuauserv）的工作目录。其中 `Download` 子目录存储已下载但尚未安装（或已安装但未清理）的更新包。Windows Update 不会自动清理已安装更新的下载缓存，长期积累可达数 GB。此目录的内容是纯缓存性质——删除后 Windows Update 会在下次检查更新时重新下载所需文件，不会影响已安装的更新。

**cleanup_windows_update() → SystemCleanResult**：

删除 `%SYSTEMROOT%\SoftwareDistribution\Download` 目录下的所有内容：
- 使用 `os.scandir()` 遍历顶层条目（比 `os.listdir` 更高效，因为 `scandir` 在遍历时就能获取文件类型信息，避免额外的 `stat` 调用）
- 对目录条目：先用 `_dir_size()` 计算大小，再用 `shutil.rmtree()` 递归删除
- 对文件条目：用 `stat().st_size` 获取大小，再用 `os.remove()` 删除
- 每个条目独立 try/except，被 Windows Update 服务锁定的文件会抛出 `OSError`，跳过继续处理下一个
- 累计释放的字节数记录在返回结果的 `freed_bytes` 字段中

**_dir_size(path) → int**：使用栈模拟（而非递归）计算目录总大小，避免深层目录结构导致的栈溢出。用 `os.scandir` 遍历，对文件累加 `st_size`，对子目录压入栈中继续处理。`follow_symlinks=False` 避免符号链接导致的循环遍历。

**scan_update_cache_size() → int**：复用 `_dir_size()` 估算缓存大小，用于扫描阶段向用户展示可清理空间。

### 7.4 network.py — 网络修复工具

三个独立的网络修复函数，均通过 `subprocess.run` 调用系统命令，超时 15 秒，静默执行（`CREATE_NO_WINDOW`）。

#### 7.4.1 flush_dns() → bool

执行 `ipconfig /flushdns`，刷新 DNS 解析器缓存。用于解决域名解析异常（如网页打不开但 IP 可达）。立即生效，无需重启。

#### 7.4.2 reset_winsock() → bool

执行 `netsh winsock reset`，重置 Winsock 目录到默认状态。Winsock 是 Windows 网络编程接口的核心组件，某些恶意软件或异常的 LSP（分层服务提供程序）会污染 Winsock 目录导致网络异常。**需要重启才能生效。**

#### 7.4.3 reset_tcp_ip() → bool

执行 `netsh int ip reset`，重置 TCP/IP 协议栈的所有参数到默认值。这会清除所有手动配置的 IP 地址、子网掩码、默认网关、DNS 服务器等设置。**需要重启才能生效。**

### 7.5 process_manager.py — 进程与 CPU 亲和性管理

#### 7.5.1 ProcessInfo 数据结构

| 字段 | 类型 | 说明 |
|------|------|------|
| pid | int | 进程 ID |
| name | str | 进程名 |
| cpu_percent | float | CPU 使用率 |
| memory_mb | float | 常驻内存（MB） |
| priority | int | 优先级类 |
| status | str | 进程状态 |

#### 7.5.2 list_top_processes(count=30) → list[ProcessInfo]

遍历所有进程，收集 PID、名称、内存信息、状态。

**cpu_percent(interval=0) 的含义**：`interval=0` 表示非阻塞模式——返回自上次调用以来的 CPU 使用率。首次调用时返回 0.0（因为没有上一次的基准），这是 psutil 的已知行为。在本场景中这是可接受的，因为此函数主要用于 UI 展示进程列表，用户会看到实时刷新的数据。如果需要精确的瞬时 CPU 使用率，需要传入 `interval=1`（阻塞 1 秒），但这会导致遍历数百个进程时总耗时过长。

**RSS（Resident Set Size）**：`memory_info().rss` 返回进程的常驻内存集大小——即当前实际占用物理内存的字节数。除以 `1024²` 转换为 MB。注意 RSS 包含与其他进程共享的内存页（如共享 DLL），因此所有进程的 RSS 之和会大于实际物理内存使用量。

**nice() 在 Windows 上的行为**：psutil 的 `nice()` 在 Windows 上映射到进程优先级类（Priority Class），返回值是 Windows 定义的优先级常量（如 `NORMAL_PRIORITY_CLASS = 32`、`HIGH_PRIORITY_CLASS = 128` 等）。

按内存降序排列，返回前 count 个。捕获 `AccessDenied`（系统进程）和 `NoSuchProcess`（进程已退出）两种异常。

#### 7.5.3 set_process_priority(pid, priority) → bool

设置指定进程的优先级类。

**受保护进程检查**：先通过 `p.name().lower()` 获取进程名（转小写），与 `PROTECTED_PROCESSES` 集合比对。受保护列表包含 Windows 关键系统进程：`csrss.exe`（客户端/服务器运行时子系统）、`lsass.exe`（本地安全认证）、`smss.exe`（会话管理器）、`services.exe`（服务控制管理器）、`svchost.exe`（服务宿主）、`wininit.exe`（Windows 初始化）、`audiodg.exe`（音频设备图隔离）、`System`（内核伪进程）。修改这些进程的优先级可能导致系统不稳定甚至蓝屏。

**底层机制**：psutil 的 `nice(priority)` 在 Windows 上调用 `SetPriorityClass(hProcess, priority)`。传入的 `priority` 值必须是 Windows 定义的优先级类常量（如 `IDLE_PRIORITY_CLASS=64`、`BELOW_NORMAL_PRIORITY_CLASS=16384`、`NORMAL_PRIORITY_CLASS=32`、`ABOVE_NORMAL_PRIORITY_CLASS=32768`、`HIGH_PRIORITY_CLASS=128`、`REALTIME_PRIORITY_CLASS=256`）。

#### 7.5.4 set_process_affinity(pid, cpus) → bool

将进程绑定到指定的 CPU 核心列表。同样先检查受保护列表。

**底层机制**：psutil 的 `cpu_affinity(cpus)` 在 Windows 上调用 `SetProcessAffinityMask(hProcess, mask)`。传入的 `cpus` 列表（如 `[0, 1, 2, 3]`）会被转换为位掩码（如 `0b00001111 = 0xF`）。每个位对应一个逻辑 CPU，置 1 表示允许该进程在该 CPU 上运行。Windows 调度器只会将进程的线程分配到掩码中允许的 CPU 上。

#### 7.5.5 boost_foreground(pid) → bool

**提升进程优先级并绑定到 P 核心。**

**P 核心（Performance Core）启发式识别：**

Intel 12 代及以后的混合架构 CPU 有两种核心：P 核心（高性能，支持超线程）和 E 核心（高能效，不支持超线程）。Windows 通过 `cpu_count(logical=True)` 返回逻辑 CPU 总数，`cpu_count(logical=False)` 返回物理核心数。

本函数的启发式假设：**逻辑 CPU 编号的前 `physical` 个对应 P 核心。** 即 `range(min(physical, logical))`。这个假设在大多数 Intel 混合架构 CPU 上成立，因为 Windows 的 CPU 编号通常先排列 P 核心（含超线程），再排列 E 核心。但这不是一个保证——AMD 处理器、某些 BIOS 配置、或未来的架构可能不遵循此规则。更精确的方法是使用 `GetSystemCpuSetInformation` API 查询每个核心的 `EfficiencyClass` 属性（0=E 核心，1=P 核心），但这会增加实现复杂度。

**操作流程：**
1. 设置进程优先级为 `HIGH_PRIORITY_CLASS`（128）
2. 绑定 CPU 亲和性到 P 核心列表
3. 两个操作独立执行，任一成功即返回 True（`ok1 or ok2`）。这样即使亲和性设置失败（如进程已退出），优先级提升仍然生效。

#### 7.5.6 throttle_background(pid) → bool

**降低进程优先级并绑定到 E 核心。**

**E 核心（Efficiency Core）识别：** 逻辑 CPU 编号中从 `physical` 到 `logical-1` 的部分（`range(physical, logical)`）。这是 boost_foreground 的镜像逻辑——P 核心占据前 `physical` 个编号，剩余的就是 E 核心（或超线程逻辑核心）。

**非混合架构的降级处理：** 如果 `logical ≤ physical`（即没有超线程，也不是混合架构），说明不存在可区分的 E 核心，此时 `range(physical, logical)` 为空列表。函数退化为仅降低优先级到 `IDLE_PRIORITY_CLASS`（64），不设置亲和性。这是合理的——在同构 CPU 上，优先级降低已经足够让调度器将该进程排在其他进程之后。

**IDLE_PRIORITY_CLASS 的效果：** 优先级为 IDLE 的进程只在系统完全空闲时才获得 CPU 时间片。Windows 调度器使用 32 级优先级（0-31），IDLE 优先级类的线程基础优先级为 4，而 NORMAL 为 8。当有任何 NORMAL 或更高优先级的线程就绪时，IDLE 线程不会被调度。

### 7.6 startup.py — 启动项管理

#### 7.6.1 StartupItem 数据结构

| 字段 | 类型 | 说明 |
|------|------|------|
| name | str | 启动项名称 |
| command | str | 启动命令 |
| source | str | 来源：`"registry"` 或 `"task"` |
| location | str | 注册表路径或任务计划路径 |
| enabled | bool | 是否启用 |

#### 7.6.2 list_startup_items() → list[StartupItem]

汇总两个来源的启动项：注册表 Run 键 + 任务计划程序。

**注册表扫描**（_scan_registry_run）：

Windows 启动项的注册表机制：当用户登录时，`explorer.exe`（Shell）会读取 Run 键下的所有值，并逐个启动对应的程序。HKCU 下的 Run 键只对当前用户生效，HKLM 下的对所有用户生效。

- 扫描两个 Run 键：
  - `HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Run`（当前用户）
  - `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run`（所有用户）
- 对每个键，用 `winreg.EnumValue(key, i)` 逐个枚举值。`EnumValue` 返回三元组 `(name, value, type)`：`name` 是值名称（通常是程序名），`value` 是启动命令行，`type` 是注册表值类型（通常是 `REG_SZ`）
- 注册表中存在的项视为已启用（被禁用的项会被移到 `AutorunsDisabled` 子键，见 7.6.3）
- `location` 字段记录为 `"HKCU\..."` 或 `"HKLM\..."`，后续 toggle 操作需要据此判断使用哪个注册表根键

**任务计划扫描**（_scan_task_scheduler）：

Windows 任务计划程序（Task Scheduler）是另一个常见的自启动机制，许多软件（如 Adobe、Google Update）通过创建"登录时触发"的计划任务来实现开机自启。

- 执行 `schtasks /Query /FO CSV /NH`：`/FO CSV` 指定 CSV 格式输出（便于解析），`/NH` 去掉表头行
- CSV 解析策略：每行格式为 `"任务名","下次运行时间","状态"`。代码先 `strip()` 去除首尾空白，再 `strip('"')` 去除首尾引号，最后按 `'","'` 分割。这种解析方式比标准 CSV 解析器简单，但对 schtasks 的输出格式足够可靠
- **过滤系统任务**：以 `\Microsoft` 开头的任务是 Windows 内置的系统任务（如 Windows Update、Defender 扫描等），数量众多且不应被用户禁用，因此过滤掉
- **状态判断**：同时检查英文和中文状态字符串（`"Ready"`/`"就绪"`、`"Running"`/`"正在运行"`），兼容中英文 Windows
- 任务名使用 `rsplit("\\", 1)[-1]` 提取最后一段作为显示名称（去掉路径前缀如 `\MyApp\UpdateTask` → `UpdateTask`）

#### 7.6.3 toggle_startup_registry(item, enable) → bool

**启用/禁用注册表启动项的实现原理：**

采用与 Microsoft Sysinternals Autoruns 相同的策略——在 Run 键旁边使用一个 `AutorunsDisabled` 子键作为"回收站"：

- **禁用流程**：
  1. 根据 `item.location` 前缀判断根键（`"HKCU"` → `HKEY_CURRENT_USER`，否则 → `HKEY_LOCAL_MACHINE`）
  2. 用 `split("\\", 1)[1]` 提取去掉前缀后的路径（如 `SOFTWARE\Microsoft\...\Run`）
  3. 以 `KEY_READ` 权限打开源键（Run），读取 `item.name` 对应的值和类型
  4. 以 `KEY_SET_VALUE` 权限打开目标键（`Run\AutorunsDisabled`），写入同名同类型的值
  5. 以 `KEY_SET_VALUE` 权限重新打开源键，删除原值

- **启用流程**：方向相反——从 `AutorunsDisabled` 读取 → 写入 `Run` → 从 `AutorunsDisabled` 删除

**为什么不直接删除**：直接删除注册表值会永久丢失启动命令信息，用户无法恢复。移动到 `AutorunsDisabled` 子键后，Windows Shell 不会读取该子键（它只读 Run 键本身），但数据仍然保留在注册表中。这也是 Autoruns 工具的标准做法，因此与 Autoruns 互操作——用 PrismCore 禁用的项在 Autoruns 中也会显示为已禁用，反之亦然。

**注意三次打开键的原因**：代码分三次打开注册表键（读源、写目标、删源），而不是一次打开后复用，是因为每次打开使用不同的访问权限（`KEY_READ` vs `KEY_SET_VALUE`）。遵循最小权限原则，避免以写权限打开只需要读的键。

#### 7.6.4 toggle_startup_task(item, enable) → bool

执行 `schtasks /Change /TN <任务路径> /ENABLE` 或 `/DISABLE` 切换计划任务状态。`/TN` 参数使用 `item.location`（完整任务路径，如 `\MyApp\UpdateTask`）。与注册表方式不同，任务计划程序原生支持启用/禁用状态，不需要移动数据。

---

## 八、View 层 — 界面

### 8.1 main_window.py — 主窗口

#### 8.1.1 窗口基类与导航结构

主窗口继承自 QFluentWidgets 的 `FluentWindow`，这是一个预置了左侧导航栏 + 右侧堆叠页面的窗口框架。

**初始化参数**：
- 窗口标题：`"{APP_NAME} v{APP_VERSION}"`
- 默认尺寸：1100×720，最小尺寸：860×560
- 主题：自动跟随系统（`Theme.AUTO`）
- 启动时居中显示（计算屏幕可用区域中心坐标）

#### 8.1.2 导航项注册

按顺序注册五个页面到导航栏：

| 位置 | 图标 | 标签 | 视图类 |
|------|------|------|--------|
| 顶部 | HOME | 首页 | DashboardView |
| 顶部 | DELETE | 清理 | CleanerView |
| 顶部 | SPEED_HIGH | 加速 | OptimizerView |
| 顶部 | DEVELOPER_TOOLS | 工具箱 | ToolboxView |
| 底部 | SETTING | 设置 | SettingsView |

底部还有一个 `NavigationAvatarWidget`（显示应用名首字母 "P"）。

#### 8.1.3 视图模型创建与信号连接

主窗口同时创建四个 ViewModel 实例，并在 `_connect_signals()` 中建立所有信号-槽连接。这是 MVVM 的核心胶水代码——**主窗口是唯一知道 View 和 ViewModel 同时存在的地方**，View 和 ViewModel 彼此不持有引用。

**为什么信号连接集中在主窗口**：这是 MVVM 模式的关键设计——View 不知道 ViewModel 的存在，ViewModel 不知道 View 的存在，它们通过信号/槽（观察者模式）解耦。主窗口作为"组装者"（Composition Root），负责将两者的信号和槽对接。这样 View 和 ViewModel 都可以独立测试。

**信号连接总览**：

**首页信号链**：
- `dashboard_vm.status_updated` → `dashboard_view.update_status`（实时数据刷新）
- `btn_optimize.clicked` → `_on_smart_optimize` → `dashboard_vm.start_smart_optimize()`
- `dashboard_vm.optimize_progress` → `dashboard_view.set_progress_text`
- `dashboard_vm.optimize_done` → `_on_smart_optimize_done`（隐藏进度、显示结果通知）
- `dashboard_vm.auto_action` → `dashboard_view.show_auto_action`（后台自动优化通知）
- `dashboard_vm.pagefile_status_changed` → `_on_pagefile_status`（更新分页文件卡片）
- `dashboard_vm.pagefile_suggest` → `_on_pagefile_suggest`（更新智能建议卡片）
- 分页文件卡片的 `reboot_clicked` → `dashboard_vm.request_reboot_clear`
- 建议卡片的 `accept/dismiss/cancel/reboot` → 对应 ViewModel 方法

**清理信号链**：
- `btn_scan.clicked` → `_on_scan` → `cleaner_vm.start_scan(deep)`
- `cleaner_vm.scan_progress` → `cleaner_view.set_status`
- `cleaner_vm.scan_done` → `_on_scan_done`（填充表格）
- `btn_clean.clicked` → `_on_clean` → `cleaner_vm.start_clean(items)`
- `cleaner_vm.clean_done` → `_on_clean_done`（显示结果）

**加速信号链**：
- `btn_optimize.clicked` → `optimizer_vm.start_optimize()`
- `optimizer_vm.optimize_progress/done` → 视图更新
- `optimizer_vm.memory_updated` → `mem_card.set_data`
- `optimizer_vm.processes_updated` → `populate_processes`（带 boost/throttle 回调）
- `btn_startup_refresh.clicked` → `optimizer_vm.refresh_startup()`
- `optimizer_vm.startup_loaded` → `populate_startup`（带 toggle 回调）

**工具箱信号链**：
- 三个工具卡片的按钮 → `_on_run_tool(action)` → `toolbox_vm.run_tool(action)`
- `toolbox_vm.tool_done` → `toolbox_view.show_result`

**设置信号链**：
- `settings_view.settings_changed` → `dashboard_vm.reload_settings()`

#### 8.1.4 页面切换懒加载

监听 `stackedWidget.view.aniFinished` 信号（页面切换动画完成后触发）。当切换到加速页时，延迟 200ms 后刷新启动项列表和进程列表。

**为什么延迟 200ms**：QFluentWidgets 的页面切换有滑动动画，如果在动画进行中立即发起数据加载（遍历进程、查询注册表），可能导致动画卡顿。200ms 的延迟确保动画完全结束后再开始数据加载。使用 `QTimer.singleShot(200, callback)` 实现一次性延迟调用。

**为什么只对加速页做懒加载**：首页的数据由定时器持续推送，不需要手动触发；清理页在用户点击扫描按钮时才加载；工具箱页是静态卡片。只有加速页需要在切换时主动刷新进程列表和启动项列表，因为这些数据会随时间变化。

#### 8.1.5 关闭事件

重写 `closeEvent`：先调用 `dashboard_vm.stop()` 停止所有定时器并还原 ProBalance 约束，再调用父类关闭。

**为什么必须在关闭时还原 ProBalance 约束**：ProBalance 引擎可能已经将某些进程的优先级降低并绑定到 E 核心。如果程序直接退出而不还原，这些进程会永久保持被约束的状态（低优先级 + E 核心绑定），直到进程重启或用户手动修改。`stop()` 方法会调用 `force_restore_all()` 将所有被约束进程的优先级和亲和性恢复到原始值。

### 8.2 dashboard_view.py — 首页视图

整个页面使用 `ScrollArea` 作为基类，内部放置一个垂直布局容器。边距 28/20/28/20，间距 16。

#### 8.2.1 _ScoreCard — 健康评分卡片

固定高度 220px 的卡片，包含三个元素：
- **ProgressRing**（圆环进度条）：120×120，描边宽度 10，范围 0-100
- **评分文字**：SubtitleLabel，显示 "XX 分"
- **状态描述**：CaptionLabel，根据分数显示不同文字：
  - ≥ 80 → "系统状态良好"
  - ≥ 60 → "系统状态一般，建议优化"
  - < 60 → "系统状态较差，请立即优化"

#### 8.2.2 _MiniIndicator — 迷你指标卡片

固定高度 100px 的通用指标卡片，用于 CPU、内存、DPC、ISR、磁盘等指标。包含：
- 标题行：图标（16×16）+ 标题文字 + 右侧数值百分比
- ProgressBar：范围 0-100
- 详情文字：CaptionLabel

`set_data(percent, detail)` 方法更新进度条值（钳位到 100）和详情文字。

#### 8.2.3 _PagefileStatusCard — 分页文件状态卡片

固定高度 56px，始终可见。水平布局：左侧状态文字 + 右侧"立即重启清除"按钮。

两种状态：
- **空闲**：显示"还没有创建临时分页文件哦~再用用吧"，重启按钮隐藏
- **活跃**：显示"已创建 XX MB 临时分页文件 (D:\)"，重启按钮可见

`reboot_clicked` 信号在用户点击重启按钮时发出。

#### 8.2.4 _PagefileSuggestionCard — 智能建议卡片

固定高度 56px，始终可见。水平布局：左侧建议文字 + 右侧按钮组。

三种模式（通过 `set_mode` 切换按钮可见性）：
- **idle**：显示"暂无智能建议"，所有按钮隐藏
- **suggest**：显示建议文字，显示"接受建议"和"忽略"按钮
- **accepted**：显示"已调整虚拟内存，需重启生效"，显示"撤销"和"立即重启"按钮

四个信号：`accept_clicked`、`dismiss_clicked`、`cancel_clicked`、`reboot_clicked`。

#### 8.2.5 DashboardView 主布局

从上到下依次排列：
1. 标题 "系统概览"
2. 顶部行（水平布局）：左侧评分卡片 + 右侧面板（优化按钮 48px 高 + 功能说明 + 不确定进度条 + 状态文字 + 问题提示）
3. 分页文件状态卡片
4. 智能建议卡片
5. 标题 "实时监控"
6. 指标网格（2×2 + 动态磁盘行）：CPU、内存、DPC 延迟、ISR 延迟，磁盘指标动态创建

#### 8.2.6 update_status(data) — 核心数据更新方法

接收一个字典，包含所有首页需要的数据：

**数据字典结构**：
```
{
    "score": int,           # 健康评分
    "cpu_pct": float,       # CPU 使用率
    "mem_pct": float,       # 内存使用率
    "mem_used": str,        # 已用内存（格式化）
    "mem_total": str,       # 总内存（格式化）
    "dpc_pct": float,       # DPC 时间百分比
    "isr_pct": float,       # ISR 时间百分比
    "probalance_count": int,    # 被约束进程数
    "probalance_threshold": int, # 阈值触发数
    "probalance_anomaly": int,   # 异常检测触发数
    "disks": [{             # 磁盘列表
        "mount": str,
        "percent": float,
        "free": str,
    }],
    "issues": [str],        # 问题提示列表
}
```

**DPC/ISR 显示逻辑**：百分比值放大 10 倍映射到进度条（`min(value * 10, 100)`）。原因：正常系统的 DPC/ISR 时间占比通常 < 3%，如果直接映射到 0-100 的进度条，3% 只会显示为一条几乎不可见的细线。放大 10 倍后，3% 显示为 30%，视觉上更直观。超过 10% 的 DPC/ISR 时间已经是严重问题，映射为 100%（满条）是合理的。

**磁盘指标动态创建**：每次 `update_status` 调用时，比较当前磁盘数量与已创建的指标卡片数量。如果不一致（如 U 盘插拔导致磁盘数变化），先销毁所有旧的磁盘指标卡片（`deleteLater()`），再根据新的磁盘列表重新创建。每行放 2 个磁盘指标（使用 `QHBoxLayout`），奇数个磁盘时最后一行只放一个。

**ProBalance 状态显示**：如果有被约束的进程，在 CPU 指标详情中显示约束数量和触发原因分类。

**问题提示**：如果有问题列表则显示 "⚠" + 问题描述；评分 ≥ 80 且无问题则显示 "✓ 系统状态良好"。

#### 8.2.7 其他公共方法

- `set_optimizing(active)`：显示/隐藏不确定进度条，禁用/启用优化按钮
- `set_progress_text(text)`：更新状态文字
- `show_result(message, score_before, score_after)`：弹出 InfoBar 成功通知，标题包含评分变化（如 "优化完成 · 评分 65 → 82 (+17)"），持续 8 秒
- `show_auto_action(message)`：弹出 InfoBar 信息通知（右下角），持续 3 秒，用于后台自动优化提示

### 8.3 cleaner_view.py — 清理页视图

基类 `ScrollArea`，边距 28/20/28/20，间距 12。

#### 8.3.1 类别中文映射表

将内部类别标识符映射为用户可读的中文标签：

| 内部标识 | 显示标签 |
|----------|----------|
| electron | 应用缓存 |
| temp | 临时文件 |
| large_file | 大文件 |
| recycle_bin | 回收站 |
| winsxs | 组件存储 |
| old_drivers | 旧驱动 |
| orphan_registry | 注册表 |
| win_update | 更新缓存 |
| compact_os | 系统压缩 |

#### 8.3.2 页面布局

从上到下：
1. 标题 "垃圾清理" + 说明文字
2. 操作栏（水平）：扫描按钮 + 模式切换（SwitchButton，Off="快速"/On="深度"）+ 弹性空间 + "清理已选"按钮（初始禁用）
3. 不确定进度条（初始隐藏）
4. 状态文字（初始 "点击'扫描'开始检测垃圾文件"）
5. 结果表格（4 列）
6. 摘要标签

#### 8.3.3 结果表格

4 列配置：
- 列 0：复选框，固定宽 40px
- 列 1：类别，自适应内容宽度
- 列 2：描述，拉伸填充
- 列 3：大小，自适应内容宽度

表格禁止选择行（NoSelection）、禁止编辑（NoEditTriggers）。最小高度 160px。

#### 8.3.4 populate(result) — 填充扫描结果

接收 `ScanResult` 对象，遍历其 `items` 列表：
- 每行第 0 列放置 CheckBox 控件，初始选中状态取自 `item.selected`
- CheckBox 的 `stateChanged` 信号连接到 `_on_check`，更新对应 item 的 selected 属性
- 第 1-3 列分别填入类别标签、描述、格式化大小
- 填充完成后更新摘要（已选数量和总大小）

#### 8.3.5 get_selected_items() → list[CleanItem]

返回所有 `selected=True` 的项目列表，供清理操作使用。

### 8.4 optimizer_view.py — 加速页视图

基类 `ScrollArea`，边距 28/20/28/20，间距 12。

#### 8.4.1 _MemoryCard — 内存状态卡片

固定高度 130px 的卡片，包含：
- 标题行：IOT 图标 + "内存状态"
- 内存文字：`"已用: X.X GB / X.X GB  (可用: X.X GB)"`
- ProgressBar：范围 0-100，显示内存使用率
- 提交费用文字：`"提交费用: XX.X%"`，如果 `commit_critical=True` 则追加 " ⚠ 危险"

`set_data(data)` 接收字典：`{total, used, available, percent, commit_ratio, commit_critical, recommended_pf}`

#### 8.4.2 页面布局

从上到下：
1. 标题 "性能加速"
2. 内存状态卡片
3. 操作行：智能优化按钮 + 刷新按钮
4. 功能说明文字
5. 不确定进度条 + 状态文字
6. 启动项管理区：标题行（"启动项管理" + 刷新按钮）+ 启动项表格
7. 进程管理区：标题 "进程管理（按内存排序）" + 进程表格

#### 8.4.3 启动项表格

4 列：名称（拉伸）、来源（自适应）、状态（自适应）、开关（固定 100px）。

`populate_startup(items, on_toggle)` 方法：
- 遍历启动项列表，每行填入名称、来源（"注册表"/"计划任务"）、状态（"已启用"/"已禁用"）
- 第 3 列放置 SwitchButton 控件，初始状态取自 `item.enabled`
- SwitchButton 的 `checkedChanged` 信号连接到 `on_toggle(item, checked)` 回调

#### 8.4.4 进程表格

5 列：PID、名称（拉伸）、内存、CPU%、操作（自适应）。最小高度 400px。

`populate_processes(procs, on_boost, on_throttle)` 方法：
- 遍历进程列表，填入 PID、名称、内存（"XX.X MB"）、CPU%
- 第 4 列放置一个 QFrame 容器，内含两个按钮："优先级↑"（80px）和 "优先级↓"（80px）
- 按钮点击分别触发 `on_boost(pid)` 和 `on_throttle(pid)` 回调

### 8.5 toolbox_view.py — 工具箱页视图

基类 `ScrollArea`，边距 28/20/28/20，间距 12。

#### 8.5.1 _ToolCard — 工具卡片

水平布局的通用工具卡片：图标（24×24）+ 文字列（标题 + 灰色描述）+ "执行"按钮（固定 80px）。

#### 8.5.2 页面布局

从上到下：
1. 标题 "工具箱" + 说明 "网络修复工具，按需使用。"
2. 不确定进度条（初始隐藏）+ 状态文字
3. 三个工具卡片：
   - DNS 刷新：图标 GLOBE，描述 "网页打不开时尝试"
   - Winsock 重置：图标 GLOBE，描述 "修复网络异常（需重启）"
   - TCP/IP 重置：图标 GLOBE，描述 "彻底重置网络协议（需重启）"

每个卡片的 `btn` 属性暴露给外部连接信号。

### 8.6 settings_view.py — 设置页视图

基类 `ScrollArea`，边距 28/20/28/20，间距 12。发出 `settings_changed` 信号通知 ViewModel 重新加载配置。

#### 8.6.1 _SettingRow — 设置行卡片

通用的单行设置控件容器。水平布局：左侧文字列（标题 BodyLabel + 灰色描述 BodyLabel）+ 右侧控件槽（通过 `add_widget` 添加）。

#### 8.6.2 设置分组与控件

**后台自动优化组**：
- 启用开关（SwitchButton）→ 写入 `auto_optimize_enabled`，触发 `settings_changed`
- 检测间隔（SpinBox，15-120）→ 写入 `auto_optimize_interval`，触发 `settings_changed`
- 内存阈值（SpinBox，50-95）→ 写入 `memory_threshold`，触发 `settings_changed`

**虚拟内存组**：
- 自动创建临时分页文件开关 → 写入 `auto_pagefile_enabled`
- 分页文件扩展阈值（SpinBox，50-95）→ 写入 `pagefile_expand_threshold`
- 智能建议开关 → 写入 `suggestion_enabled`

**ProBalance CPU 调度组**：
- 启用 ProBalance 开关 → 写入 `probalance_enabled`，触发 `settings_changed`
- 系统 CPU 激活阈值（SpinBox，30-95）→ 写入 `probalance_system_threshold`
- 单进程 CPU 约束阈值（SpinBox，5-50）→ 写入 `probalance_process_threshold`

**高级设置（异常检测）组**：
- Z-score 异常检测开关 → 写入 `anomaly_detection_enabled`，触发 `settings_changed`
- Z-score 阈值（DoubleSpinBox，1.0-10.0，步长 0.5）→ 写入 `anomaly_z_threshold`，触发 `settings_changed`
- EWMA 平滑系数（DoubleSpinBox，0.05-0.95，步长 0.05）→ 写入 `ewma_alpha`，触发 `settings_changed`

**内存优化策略组**：
- 备用列表清理开关 → 写入 `purge_standby_enabled`
- 工作集修剪开关 → 写入 `trim_workingset_enabled`
- 空闲进程分页开关 → 写入 `pageout_idle_enabled`

**系统监控组**：
- DPC/ISR 延迟监控开关 → 写入 `dpc_monitor_enabled`，触发 `settings_changed`

#### 8.6.3 settings_changed 信号触发规则

并非所有设置变更都触发此信号——这是一个重要的性能优化设计。只有需要 ViewModel **立即响应**的设置才触发：
- 自动优化开关/间隔/阈值 → 需要重新配置定时器间隔或启停定时器
- ProBalance 开关 → 需要启停 ProBalance 采样定时器，关闭时还需还原所有约束
- 异常检测参数（Z-score 阈值、EWMA alpha）→ 需要更新 AnomalyDetector 实例的参数
- DPC 监控开关 → 需要启停 ETW 内核会话（ETW 会话是系统级资源，不用时应释放）

**为什么不是所有设置都触发信号**：其他设置（分页文件策略、内存优化策略开关）属于"惰性生效"——它们在下次执行对应操作时才被读取。例如 `purge_standby_enabled` 只在 `check_and_auto_optimize()` 执行时才被检查，而该函数由定时器周期性调用，因此设置变更会在下一个周期自动生效，无需立即通知。这种设计减少了不必要的信号传播和对象重建。

---

## 九、ViewModel 层 — 信号适配与后台线程

### 9.1 dashboard_vm.py — 首页视图模型

这是最复杂的 ViewModel，承担实时监控、智能优化、后台自动优化、ProBalance 调度、分页文件生命周期管理五大职责。

#### 9.1.1 信号定义

| 信号名 | 参数 | 用途 |
|--------|------|------|
| status_updated | dict | 实时状态数据（每 1.5 秒发射一次） |
| optimize_progress | str | 智能优化进度文字 |
| optimize_done | str, int, int | 优化完成（摘要、优化前评分、优化后评分） |
| auto_action | str | 后台自动优化动作通知 |
| pagefile_status_changed | dict | 分页文件状态变更 |
| pagefile_suggest | int | 智能建议（推荐 MB 数，-1=已接受，0=取消） |

#### 9.1.2 三个定时器

**定时器架构设计原理**：DashboardViewModel 使用四个独立定时器而非一个统一定时器，原因是各任务的执行频率和生命周期不同。统一定时器需要在每次触发时判断"该执行哪些任务"，增加复杂度；独立定时器可以各自启停，互不影响。

**实时监控定时器**（`_timer`）：
- 间隔：MONITOR_INTERVAL_MS（1500ms）
- 回调：`_tick()` — 采集系统状态并发射 `status_updated`
- 运行在 UI 线程，但内部调用的 API 都是非阻塞的（`psutil.cpu_percent(interval=0)`、`GlobalMemoryStatusEx`、`PdhGetFormattedCounterValue` 等都是瞬时返回）
- **为什么是 1500ms**：这是 UI 刷新率和系统开销的平衡点。更快（如 500ms）会增加 CPU 开销且人眼难以感知差异；更慢（如 3s）会让用户觉得数据不够实时

**后台自动优化定时器**（`_auto_timer`）：
- 间隔：`auto_optimize_interval × 1000` ms（默认 15 秒，用户可配置 15-120 秒）
- 回调：`_auto_check()` — 检测内存压力并执行自动优化
- 仅在 `auto_optimize_enabled=True` 时启动

**ProBalance 采样定时器**（`_pb_timer`）：
- 间隔：PROBALANCE_SAMPLE_INTERVAL × 1000 ms（1 秒）
- 回调：`_probalance_tick()` — 调用 ProBalanceEngine.tick()
- 仅在 `probalance_enabled=True` 时启动

**30 分钟建议定时器**（`_suggest_timer`）：
- 单次触发（SingleShot）
- 在临时分页文件创建后启动，30 分钟后触发建议
- 如果应用重启，从持久化的 `created_at` 时间戳计算剩余时间

#### 9.1.3 start() — 启动入口

按顺序执行：
1. 如果 DPC 监控开关打开 → 调用 `_latency.open()` 初始化 PDH+ETW
2. 立即执行一次 `_tick()` 采集初始数据
3. 启动实时监控定时器
4. 如果自动优化开关打开 → 启动自动优化定时器
5. 如果 ProBalance 开关打开 → 启动 ProBalance 定时器
6. 调用 `restore_pagefile_state()` 恢复分页文件跟踪状态
7. 调用 `_restore_pagefile_ui()` 恢复分页文件卡片 UI 状态

**步骤 2 的必要性**：定时器启动后要等一个完整周期（1.5 秒）才会首次触发。如果不立即执行一次 `_tick()`，用户打开应用后会看到 1.5 秒的空白仪表盘。立即采集一次确保 UI 在启动瞬间就有数据显示。

**条件启动的设计**：三个定时器根据各自的开关独立启动。用户可以只开启监控而关闭自动优化和 ProBalance，此时只有监控定时器运行，CPU 开销最小。

#### 9.1.4 stop() — 关闭入口

停止所有三个定时器，调用 `_probalance.force_restore_all()` 还原所有被约束的进程，关闭延迟监控。

**关闭顺序的重要性**：必须先停止定时器再还原进程。如果先还原进程但定时器还在运行，下一次 tick 可能又会约束刚还原的进程。停止定时器确保不会有新的约束操作发生。

**延迟监控关闭**：`_latency.close()` 会释放 PDH 查询句柄和停止 ETW 会话。ETW 会话是系统级资源（内核对象），不关闭会导致资源泄漏，且 Windows 限制同时活跃的 ETW 会话数量（通常 64 个）。

#### 9.1.5 _tick() — 实时监控采集

每 1.5 秒执行一次，采集并组装完整的状态字典。这是整个仪表盘的数据泵——所有实时指标都由此函数驱动更新。

**在 UI 线程执行的安全性**：虽然此函数在 UI 线程运行，但其中的每个调用都是非阻塞的：`get_cpu_snapshot()` 和 `get_memory_status()` 底层是 `GlobalMemoryStatusEx` / `GetSystemTimes` 等微秒级系统调用；`get_disk_snapshots()` 使用 `psutil.disk_usage()` 也是快速的；`calc_health_score()` 只做简单算术。整个 _tick 通常 < 5ms，不会造成 UI 卡顿。

采集步骤：
1. 调用 `get_cpu_snapshot()` 获取 CPU 数据
2. 调用 `get_memory_status()` 获取内存数据
3. 调用 `get_disk_snapshots()` 获取磁盘数据
4. 调用 `calc_health_score()` 计算健康评分
5. 调用 `_latency.sample()` 采集 DPC/ISR 延迟
6. 调用 `_update_responsiveness_feedback()` 执行响应延迟反馈闭环

**问题提示生成逻辑**（与评分阈值对齐）：
- 内存使用率 > 70% → 添加警告
- CPU 使用率 > 50% → 添加警告
- 任一磁盘使用率 > 70% → 添加警告
- 延迟监控的 warnings 列表直接追加
- ETW 不可用时首次添加降级提示
- ProBalance 有约束进程时添加提示

#### 9.1.6 _update_responsiveness_feedback() — 响应延迟反馈闭环

**这是 ProBalance 的自适应调节机制**，根据系统 UI 实际响应延迟动态调整 ProBalance 的激活阈值。这实现了一个经典的**反馈控制回路**：感知（测量延迟）→ 判断（是否超标）→ 执行（调整阈值）→ 效果（ProBalance 更积极/保守）→ 再感知。

**为什么需要反馈闭环**：ProBalance 的系统 CPU 阈值（默认 60%）是一个静态值，但不同系统的"卡顿点"不同——8 核 CPU 在 60% 时可能完全流畅，而 4 核 CPU 在 50% 时就开始卡顿。通过测量实际 UI 响应延迟，可以动态调整阈值使 ProBalance 在真正需要时才介入。

**冷却期**：两次调整之间至少间隔 30 秒（使用 `time.monotonic()` 计时），避免在延迟波动时频繁切换阈值（类似控制理论中的死区/滞后设计）。

**调节逻辑**：
1. 调用 `measure_responsiveness()` 测量 UI 线程响应延迟（通过 `SendMessageTimeoutW` 向前台窗口发送 `WM_NULL`）
2. 如果延迟 > 200ms 且当前未加速 → 将系统阈值降低 15%（`threshold *= 0.85`，下限 50%），使 ProBalance 更容易被触发
3. 如果延迟 ≤ 100ms 且当前已加速 → 恢复原始阈值，让 ProBalance 回到正常灵敏度

**200ms/100ms 双阈值设计**：上升阈值（200ms）高于下降阈值（100ms），形成滞后区间，防止在边界值附近反复切换。这是控制工程中常见的"施密特触发器"思想。

#### 9.1.7 _SmartOptimizeWorker — 智能一键优化线程

继承 QThread，在后台执行完整的智能优化流程。通过 `progress` 信号报告进度，`finished` 信号返回结果。

**为什么用独立 QThread 而非线程池**：智能优化是一个长时间运行的顺序流程（可能持续数十秒），且同一时间只允许一个实例运行。QThread 提供了明确的生命周期管理（start/wait/finished 信号），比线程池更适合这种"单次长任务"场景。

**执行步骤**（每步都尊重对应的设置开关）：

1. **记录优化前状态**：调用 `calc_health_score()` 和 `get_memory_status()` 保存基线
2. **清理备用列表**（`purge_standby_enabled`）：调用 `force_purge()`
3. **修剪后台工作集**（`trim_workingset_enabled`）：调用 `trim_background_working_sets()`
4. **智能进程分页**（`pageout_idle_enabled`）：调用 `page_out_idle_processes()`，统计释放的进程数和总 MB
5. **快速垃圾清理**：扫描临时文件 + Electron 缓存，然后执行清理
6. **智能线性扩展分页文件**（`auto_pagefile_enabled`）：如果提交比超过扩展阈值，调用 `expand_pagefile_incremental()`
7. **危急提交费用处理**：如果 `is_commit_critical()` 为真，调用 `adjust_pagefile_size()` 调整虚拟内存
8. **计算释放量**：对比优化前后的可用内存差值
9. **生成摘要**：拼接所有操作描述，附加内存使用率变化（如 "内存: 85% → 72% (↓13%)"）
10. **发射完成信号**：包含摘要文字、优化前评分、优化后评分

**步骤顺序的设计逻辑**：先释放内存（步骤 2-4），再清理磁盘（步骤 5），最后处理分页文件（步骤 6-7）。这个顺序确保内存释放后重新计算提交比率更准确——如果先扩展分页文件再释放内存，可能会创建不必要的分页文件。

#### 9.1.8 _auto_check() — 后台自动优化

由自动优化定时器周期性调用，静默执行。与 SmartOptimizeWorker 不同，此函数直接在定时器回调中运行（UI 线程），因为其中的操作都是快速的系统调用（< 100ms）。

**自动撤回机制**：如果提交比已降至 `阈值 - 15%` 以下且存在临时分页文件 → 自动清理临时分页文件配置，发射 `pagefile_status_changed({"mode": "idle"})` 更新卡片。这个 15% 的滞后区间防止在阈值附近反复创建/删除分页文件。

**触发条件**：内存使用率 ≥ `memory_threshold` 设置值时才执行优化。

**执行内容**：
1. 调用 `check_and_auto_optimize()`（内存清理 + 分页文件创建）
2. 如果 `pageout_idle_enabled` → 调用 `page_out_idle_processes()`
3. 每个操作结果通过 `auto_action` 信号通知 UI

#### 9.1.9 分页文件生命周期管理

ViewModel 层负责协调分页文件从创建到清理的完整生命周期，是 Model 层分页文件操作与 View 层卡片 UI 之间的桥梁。

**创建后回调**（`_on_pagefile_created`）：
- Worker 线程创建分页文件后发射 `pagefile_created` 信号
- ViewModel 从 `AppSettings().pagefile_info` 读取信息，发射 `pagefile_status_changed` 更新卡片
- 启动 30 分钟建议计时器

**建议计时器启动**（`_start_suggest_timer`）：
- 从持久化的 `created_at` ISO 时间戳计算已过去的秒数
- 剩余时间 = max(0, 30×60 - elapsed) × 1000 ms
- 如果剩余为 0 → 立即触发建议
- 否则启动单次定时器

**30 分钟延迟的设计意图**：临时分页文件创建后不立即建议用户调整系统虚拟内存，而是等待 30 分钟观察。如果 30 分钟后临时分页文件仍然存在（说明系统确实需要更多虚拟内存），才建议用户永久调整。这避免了因短暂的内存峰值（如大型编译任务）而做出不必要的永久配置变更。

**建议超时**（`_on_suggest_timeout`）：
- 检查建议开关和临时分页文件是否仍存在
- 发射 `pagefile_suggest(recommend_pagefile_mb())` 通知 UI 显示建议

**用户操作**：
- `accept_suggestion(rec_mb)` → 调用 `adjust_pagefile_size()` 调整系统虚拟内存，发射 `-1` 表示已接受
- `dismiss_suggestion()` → 停止计时器，发射 `0` 取消建议
- `cancel_suggestion()` → 发射 `0`（wmic 修改需重启才生效，不重启即不生效）
- `request_reboot_clear()` → 清理所有临时分页文件 → 清除持久化记录 → 执行 `shutdown /r /t 3` 重启

#### 9.1.10 _probalance_tick() — ProBalance 定时采样

每秒调用一次，将设置页的所有 ProBalance 参数传入 `ProBalanceEngine.tick()`：
- `system_threshold`、`process_threshold`：从 AppSettings 实时读取
- `anomaly_enabled`、`z_threshold`、`ewma_alpha`：从 AppSettings 实时读取

将返回的 `ProBalanceSnapshot` 中的 `actions` 和 `anomaly_actions` 列表逐条通过 `auto_action` 信号通知 UI。如果有还原操作（`restored_count > 0`），也发送通知。

#### 9.1.11 reload_settings() — 设置变更响应

设置页发出 `settings_changed` 信号后调用：
1. 更新自动优化定时器间隔，根据开关启停
2. 根据 DPC 监控开关启停延迟监控
3. 根据 ProBalance 开关启停 ProBalance 定时器（关闭时还原所有约束）

**"热重载"设计**：设置变更不需要重启应用。每个定时器都可以在运行时动态启停和调整间隔。这是通过 QTimer 的 `setInterval()` 和 `start()`/`stop()` 方法实现的。

**ProBalance 关闭时的清理**：关闭 ProBalance 开关时不仅停止定时器，还必须调用 `force_restore_all()` 还原所有被约束的进程。否则这些进程会永久保持被降级的状态。这是"关闭功能 = 撤销所有副作用"的原则。

**DPC 监控的启停开销**：开启 DPC 监控需要初始化 PDH 查询和 ETW 会话（约 100ms），关闭需要释放这些资源。频繁开关会有性能开销，但用户通常不会频繁切换此设置。

### 9.2 cleaner_vm.py — 清理器视图模型

#### 9.2.1 信号定义

| 信号名 | 参数 | 用途 |
|--------|------|------|
| scan_progress | str | 扫描进度文字 |
| scan_done | object (ScanResult) | 扫描完成 |
| clean_progress | str | 清理进度文字 |
| clean_done | str | 清理完成摘要 |

#### 9.2.2 系统级清理类别常量

`SYSTEM_CATEGORIES = {"winsxs", "old_drivers", "orphan_registry", "win_update", "compact_os"}`

这些类别不走通用的 `execute_clean()` 文件删除流程，需要特殊处理。

#### 9.2.3 _ScanWorker — 统一扫描线程

接收 `deep` 参数控制扫描深度。继承 QThread，在后台执行全部扫描操作，避免阻塞 UI。

**扫描顺序的设计考量**：先扫描快速项目（临时文件、Electron 缓存、回收站），再扫描慢速项目（大文件、系统级项目）。这样用户可以尽早看到部分结果。每个扫描步骤之间通过 `progress` 信号报告当前阶段。

执行流程：

1. 扫描临时文件（`scan_temp_files()`）— 遍历 TEMP 目录，按扩展名匹配
2. 搜索 Electron 应用缓存（`scan_electron_caches()`）— 遍历 AppData 目录树
3. 检查回收站大小（`query_recycle_bin_size()`），大于 0 则添加为 CleanItem（类别 `recycle_bin`，默认选中）
4. **深度模式额外**：扫描 C 盘大文件（`scan_large_files("C:\\")`）— 优先使用 MFT 扫描，失败则回退到 os.walk
5. 分析 Windows Update 缓存大小，大于 0 则添加（类别 `win_update`，**默认不选中**）
6. 扫描旧驱动（`scan_old_drivers_info()`），有结果则添加（类别 `old_drivers`，size 字段存储驱动数量，**默认不选中**）
7. 扫描孤立注册表项（`scan_orphan_registry_info()`），有结果则添加（类别 `orphan_registry`，size 字段存储条目数量，**默认不选中**）
8. 查询 CompactOS 状态，如果未启用则添加建议项（类别 `compact_os`，size=0，**默认不选中**）
9. 按大小降序排列所有结果

**默认选中策略**：临时文件、Electron 缓存、回收站默认选中（安全性高，误删风险低）；系统级项目（驱动、注册表、WinSxS、CompactOS）默认不选中（需要用户明确确认，因为操作不可逆或影响较大）。大文件也默认不选中（用户需要自行判断是否需要）。

#### 9.2.4 _CleanWorker — 统一清理线程

将待清理项分为两组：文件级项目和系统级项目。分组依据是 `SYSTEM_CATEGORIES` 集合。

**文件级清理**：直接调用 `execute_clean(file_items)`，返回 (cleaned_bytes, failed_count)。这包括临时文件、Electron 缓存、回收站、大文件等——本质上都是删除文件/目录。

**系统级清理**（需要特殊处理的项目）：
1. **先创建系统还原点**：调用 `create_restore_point("PrismCore 系统清理前备份")`。这是安全网——如果系统级清理导致问题，用户可以通过 Windows 系统还原回退。还原点创建失败不会阻止后续清理（仅记录警告）
2. 逐项处理（按类别分发到不同的清理函数）：
   - `win_update` → `cleanup_windows_update()`，累加释放字节数
   - `old_drivers` → `list_old_drivers()` 重新获取最新列表，逐个 `delete_driver()`（重新扫描而非使用缓存，因为扫描和清理之间可能有时间差）
   - `orphan_registry` → `scan_orphan_registry()` 重新扫描，逐个 `backup_and_delete_key()`（同理，重新扫描确保数据新鲜）
   - `winsxs` → `cleanup_winsxs()`
   - `compact_os` → `enable_compact_os()`

**为什么系统级项目要重新扫描**：扫描阶段和清理阶段之间可能间隔数分钟（用户在查看结果、勾选项目），期间系统状态可能已变化。重新扫描确保操作的是最新数据，避免删除已不存在的项目。

最终生成摘要：`"已清理 X.X MB"` + 失败数（如有）。

#### 9.2.5 CleanerViewModel 公共方法

- `start_scan(deep)` → 创建 _ScanWorker 并启动，防止重复启动（检查 isRunning）
- `start_clean(items)` → 创建 _CleanWorker 并启动

### 9.3 optimizer_vm.py — 加速页视图模型

#### 9.3.1 信号定义

| 信号名 | 参数 | 用途 |
|--------|------|------|
| optimize_progress | str | 内存优化进度文字 |
| optimize_done | str | 内存优化完成摘要 |
| memory_updated | dict | 内存状态数据 |
| processes_updated | list | 进程列表 |
| startup_loaded | list | 启动项列表 |
| startup_toggled | str | 启动项切换结果消息 |

#### 9.3.2 四个工作线程

**线程设计原则**：加速页的每个耗时操作都封装为独立的 QThread 子类。这样做的原因是 Qt 的信号槽机制要求信号发射者是 QObject，而 QThread 本身就是 QObject，可以直接定义和发射信号。每个 Worker 都是"用完即弃"的——创建、启动、完成后由 Qt 的父对象机制自动回收。

**_OptimizeWorker**：与首页的 _SmartOptimizeWorker 逻辑类似，但有两个关键区别：(1) 不包含垃圾清理步骤（清理是清理页的职责，加速页只做内存优化）；(2) `finished` 信号只返回摘要字符串，不含评分变化（加速页没有评分卡片）。执行步骤：清理备用列表 → 修剪工作集 → 智能进程分页 → 智能扩展分页文件 → 危急提交费用处理 → 计算释放量。

**_RefreshMemoryWorker**：在后台线程中采集内存状态，返回字典：
```
{total, used, available, percent, commit_ratio, commit_critical, recommended_pf}
```

**_RefreshProcessesWorker**：调用 `list_top_processes()` 返回进程列表。

**_LoadStartupWorker**：调用 `list_startup_items()` 返回启动项列表。

#### 9.3.3 OptimizerViewModel 公共方法

**内存优化**：
- `start_optimize()` → 创建 _OptimizeWorker 并启动（防重复）
- `refresh_memory()` → 创建 _RefreshMemoryWorker 异步刷新内存状态
- `refresh_processes()` → 创建 _RefreshProcessesWorker 异步刷新进程列表

**进程管理**（同步调用，不需要 Worker 线程）：
- `boost_process(pid)` → 调用 `boost_foreground(pid)`，提升优先级+绑定 P 核心
- `throttle_process(pid)` → 调用 `throttle_background(pid)`，降低优先级+绑定 E 核心
- **为什么同步调用**：`SetPriorityClass` 和 `SetProcessAffinityMask` 都是瞬时返回的 Windows API（微秒级），不会阻塞 UI 线程，因此不需要放到后台线程。

**启动项管理**：
- `refresh_startup()` → 创建 _LoadStartupWorker 异步加载启动项列表
- `toggle_startup(item, enable)` → 根据 `item.source` 调用对应的 toggle 函数（registry 或 task），发射结果消息（如 "启用 XXX: 成功"）

### 9.4 toolbox_vm.py — 工具箱视图模型

最简单的 ViewModel，仅封装网络工具的后台执行。

#### 9.4.1 信号定义

| 信号名 | 参数 | 用途 |
|--------|------|------|
| tool_progress | str | 工具执行进度文字 |
| tool_done | str | 工具执行完成结果消息 |

#### 9.4.2 _ToolWorker — 通用工具执行线程

接收 `action` 字符串参数，通过字典映射到对应的处理函数。这是一个**策略模式**的简化实现——用字典代替 if/elif 链，将 action 字符串映射到 `(函数, 成功消息, 失败消息)` 三元组：

| action | 调用函数 | 成功消息 | 失败消息 |
|--------|----------|----------|----------|
| `"dns"` | `flush_dns()` | "DNS 缓存已刷新" | "DNS 刷新失败" |
| `"winsock"` | `reset_winsock()` | "Winsock 已重置（需重启生效）" | "Winsock 重置失败" |
| `"tcp"` | `reset_tcp_ip()` | "TCP/IP 已重置（需重启生效）" | "TCP/IP 重置失败" |

#### 9.4.3 ToolboxViewModel 公共方法

- `run_tool(action)` → 创建 _ToolWorker 并启动（防重复），连接 progress 和 finished 信号

---

## 十、数据流总览

本节以端到端视角描述数据如何在 MVVM 三层之间流动。理解这些数据流是复刻整个系统的关键——它们定义了各模块之间的协作契约。

### 10.1 实时监控数据流

**触发频率**：每 1.5 秒一次，是整个应用的"心跳"。

**线程模型**：全部在 UI 线程执行。这看似违反"耗时操作不阻塞 UI"的原则，但实际上每个 API 调用都是微秒级返回的（读取内核计数器或缓存值），整个 `_tick()` 的执行时间通常 < 5ms，不会造成可感知的卡顿。

```
QTimer (1.5s) → DashboardViewModel._tick()
  ├→ get_cpu_snapshot()        → CPU 数据
  ├→ get_memory_status()       → 内存数据
  ├→ get_disk_snapshots()      → 磁盘数据
  ├→ calc_health_score()       → 健康评分
  ├→ LatencyMonitor.sample()   → DPC/ISR 延迟
  ├→ measure_responsiveness()  → UI 响应延迟（反馈闭环）
  └→ status_updated.emit(dict) → DashboardView.update_status()
```

### 10.2 智能优化数据流

**线程模型**：用户点击按钮在 UI 线程，实际优化在后台 QThread，完成后通过信号回到 UI 线程更新界面。这是典型的"请求-异步执行-回调"模式。

**关键设计**：优化按钮在 Worker 运行期间被禁用（`set_optimizing(True)` 会 disable 按钮），防止用户重复点击导致并发优化。

```
用户点击"智能优化"
  → MainWindow._on_smart_optimize()
    → DashboardView.set_optimizing(True)
    → DashboardViewModel.start_smart_optimize()
      → _SmartOptimizeWorker.start() [后台线程]
        ├→ force_purge()
        ├→ trim_background_working_sets()
        ├→ page_out_idle_processes()
        ├→ scan_temp_files() + scan_electron_caches() → execute_clean()
        ├→ expand_pagefile_incremental()
        └→ finished.emit(summary, score_before, score_after)
          → MainWindow._on_smart_optimize_done()
            → DashboardView.set_optimizing(False)
            → DashboardView.show_result()
```

### 10.3 ProBalance 调度数据流

**触发频率**：每 1 秒一次，比监控定时器更频繁，因为 CPU 负载变化很快，需要更及时的响应。

**线程模型**：在 UI 线程执行。`psutil.cpu_percent(interval=0)` 和进程遍历都是非阻塞的，整个 tick 通常 < 10ms。

**数据流向**：设置页的参数通过 `AppSettings` 单例实时传入 `tick()`，不需要信号通知——每次 tick 都重新读取最新设置值。这是"拉取"模式而非"推送"模式，简化了设置变更的传播逻辑。

```
QTimer (1s) → DashboardViewModel._probalance_tick()
  → ProBalanceEngine.tick(settings...)
    ├→ psutil.cpu_percent() → 系统 CPU
    ├→ _TrendPredictor.update() → 预测值
    ├→ 如果 CPU < restore_threshold → _restore_all()
    ├→ 如果预测值 < system_threshold → 维持现状
    └→ 高负载扫描：
        ├→ 白名单过滤
        ├→ 每进程 EWMA 预测
        ├→ Z-score 异常检测
        ├→ 持续超阈值计时
        └→ _constrain() → 降优先级 + 绑 E 核心
  → auto_action.emit() → DashboardView.show_auto_action()
```