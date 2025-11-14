import ctypes

import win32api
import win32con
import win32gui


def set_windows_as_wallpaper(my_win_hwnd):
    """
    将指定窗口置于壁纸层，支持最新版的windows系统。
    旧版的只能使用分裂法，在Progman创建WorkerW并附加不会显示；新版系统不能分裂只能直接在Progman创建WorkerW并附加。
    :param my_win_hwnd: 需要放置在壁纸层的窗口句柄
    :return: None or str: 错误信息，目前None表示使用旧版的方法，str表示使用新版的方法
    """
    Progman = win32gui.FindWindow("Progman", "Program Manager")

    # 尝试使用旧版的方法让桌面窗口分裂
    win32gui.SendMessageTimeout(Progman, 0x052C, 0, None, 0, 0x03E8)
    win32gui.SendMessageTimeout(Progman, 0x052C, 0xD, None, 0, 0x03E8)
    win32gui.SendMessageTimeout(Progman, 0x052C, 0xD, 1, 0, 0x03E8)

    top_WorkerW = None # 分裂后SHELLDLL_DefView的父窗口：WorkerW
    SHELLDLL_DefView = None # SHELLDLL_DefView
    first_WorkWs = None # 第一个WorkerW窗口句柄，用于防止无限查找
    old_target_WorkerW = None # 旧版的附加目标WorkerW
    t = None # 错误信息，目前None表示使用旧版的方法，str表示使用新版的方法

    while True:
        top_WorkerW = win32gui.FindWindowEx(None, top_WorkerW, "WorkerW", None)
        if top_WorkerW == first_WorkWs:
            t = '找不到桌面图标层级的窗口！'
            # raise Exception(t)
            break
        if first_WorkWs is None:
            first_WorkWs = top_WorkerW
        if not top_WorkerW:
            continue
        SHELLDLL_DefView = win32gui.FindWindowEx(top_WorkerW, None, "SHELLDLL_DefView", None)
        if not SHELLDLL_DefView:
            continue

        old_target_WorkerW = win32gui.FindWindowEx(None, top_WorkerW, "WorkerW", None)
        print('WorkerW: ', hex(top_WorkerW))
        print('SHELLDLL_DefView: ', hex(SHELLDLL_DefView))
        print('WorkerW: ', hex(old_target_WorkerW))
        break
    if not old_target_WorkerW:
        # 新版windows的方法
        print('使用新版的方法')
        # 在Progman下查找是否已存在WorkerW，实测wallpape、live2d壁纸软件也是在这个WorkerW下附加的，防止重复创建。
        new_workerw = win32gui.FindWindowEx(Progman, None, "WorkerW", None)
        if not new_workerw:
            # 如果没有WorkerW，则创建
            new_workerw = create_workerw(Progman)
        ctypes.windll.user32.SetParent(my_win_hwnd, new_workerw)
    else:
        print('使用旧版的方法')
        # 直接附加到分裂后的WorkerW下
        ctypes.windll.user32.SetParent(my_win_hwnd, old_target_WorkerW)
        # 确保窗口在壁纸层
        ctypes.windll.user32.SetWindowPos(
            my_win_hwnd, SHELLDLL_DefView, 0, 0, 0, 0,
            0x0001 | 0x0002
        )

    return t



def create_workerw(parent_hwnd):
    # 1. 注册WorkerW类的窗口样式（需管理员权限）
    wc = win32gui.WNDCLASS()
    wc.hInstance = win32api.GetModuleHandle(None)
    wc.lpszClassName = "WorkerW"
    wc.style = win32con.CS_VREDRAW | win32con.CS_HREDRAW
    wc.lpfnWndProc = lambda hwnd, msg, wParam, lParam: win32gui.DefWindowProc(hwnd, msg, wParam, lParam)
    class_atom = win32gui.RegisterClass(wc)

    # 2. 创建WorkerW窗口（需特殊参数）
    rect = win32gui.GetClientRect(parent_hwnd)
    width = rect[2] - rect[0]
    height = rect[3] - rect[1]
    hwnd = win32gui.CreateWindowEx(
        win32con.WS_EX_LAYERED | win32con.WS_EX_TOOLWINDOW,
        class_atom,
        "",
        win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.WS_CLIPSIBLINGS,
        0, 0, width, height,
        parent_hwnd,
        None,
        wc.hInstance,
        None
    )

    return hwnd

if __name__ == '__main__':
    set_windows_as_wallpaper(0x1109E6)