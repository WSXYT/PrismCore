using System.Runtime.InteropServices;
using static PrismCore.Helpers.NativeApi;

namespace PrismCore.Helpers;

/// <summary>系统托盘图标管理，纯 Win32 实现。</summary>
public sealed class TrayIcon : IDisposable
{
    public event Action? ShowRequested;
    public event Action? OptimizeRequested;
    public event Action? ExitRequested;

    private const uint IDM_SHOW = 1001;
    private const uint IDM_OPTIMIZE = 1002;
    private const uint IDM_EXIT = 1003;

    private nint _hWnd;
    private nint _hIcon;
    private NOTIFYICONDATAW _nid;
    private WNDPROC _wndProc = null!; // prevent GC

    public void Create()
    {
        var hInstance = GetModuleHandleW(null);

        // 从 exe 提取嵌入图标（由 csproj ApplicationIcon 编译嵌入）
        var exePath = Environment.ProcessPath;
        if (!string.IsNullOrEmpty(exePath))
            _hIcon = LoadTrayIcon(exePath);

        // 注册窗口类
        _wndProc = WndProc;
        var wc = new WNDCLASSEXW
        {
            cbSize = (uint)Marshal.SizeOf<WNDCLASSEXW>(),
            lpfnWndProc = Marshal.GetFunctionPointerForDelegate(_wndProc),
            hInstance = hInstance,
            lpszClassName = "PrismCoreTrayWnd"
        };
        RegisterClassExW(ref wc);

        // 创建消息窗口
        _hWnd = CreateWindowExW(0, "PrismCoreTrayWnd", "", 0, 0, 0, 0, 0, HWND_MESSAGE, 0, hInstance, 0);
        if (_hWnd == 0) return;

        // 添加托盘图标
        _nid = new NOTIFYICONDATAW
        {
            cbSize = (uint)Marshal.SizeOf<NOTIFYICONDATAW>(),
            hWnd = _hWnd,
            uID = 1,
            uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP,
            uCallbackMessage = WM_APP_TRAY,
            hIcon = _hIcon,
            szTip = "PrismCore"
        };
        Shell_NotifyIconW(NIM_ADD, ref _nid);
    }

    public void Dispose()
    {
        Shell_NotifyIconW(NIM_DELETE, ref _nid);
        if (_hWnd != 0) { DestroyWindow(_hWnd); _hWnd = 0; }
        if (_hIcon != 0) { DestroyIcon(_hIcon); _hIcon = 0; }
    }

    private nint WndProc(nint hWnd, uint msg, nint wParam, nint lParam)
    {
        if (msg == WM_APP_TRAY)
        {
            var mouseMsg = (uint)(lParam & 0xFFFF);
            if (mouseMsg == WM_LBUTTONUP)
                ShowRequested?.Invoke();
            else if (mouseMsg == WM_RBUTTONUP)
                ShowContextMenu();
            return 0;
        }

        if (msg == WM_COMMAND)
        {
            var id = (uint)(wParam & 0xFFFF);
            if (id == IDM_SHOW) ShowRequested?.Invoke();
            else if (id == IDM_OPTIMIZE) OptimizeRequested?.Invoke();
            else if (id == IDM_EXIT) ExitRequested?.Invoke();
            return 0;
        }

        return DefWindowProcW(hWnd, msg, wParam, lParam);
    }

    private void ShowContextMenu()
    {
        var hMenu = CreatePopupMenu();
        InsertMenuW(hMenu, 0, MF_STRING, IDM_SHOW, "打开主界面");
        InsertMenuW(hMenu, 1, MF_STRING, IDM_OPTIMIZE, "智能优化");
        InsertMenuW(hMenu, 2, MF_STRING, IDM_EXIT, "退出");

        GetCursorPos(out var pt);
        SetForegroundWindow(_hWnd);
        TrackPopupMenu(hMenu, TPM_RIGHTBUTTON | TPM_BOTTOMALIGN, pt.X, pt.Y, 0, _hWnd, 0);
        DestroyMenu(hMenu);
    }

    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    private static extern nint ExtractIconW(nint hInst, string lpszExeFileName, uint nIconIndex);

    /// <summary>从 exe 嵌入资源提取图标（由 csproj ApplicationIcon 编译嵌入，Windows 自动缩放尺寸）。</summary>
    private static nint LoadTrayIcon(string exePath)
    {
        var icon = ExtractIconW(0, exePath, 0);
        return (icon != 0 && icon != 1) ? icon : 0;
    }
}
