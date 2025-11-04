import threading

import win32gui
import win32api
import win32con
import time




def get_monitor_info(hwnd):
    monitor = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST)
    return win32api.GetMonitorInfo(monitor)

def is_maximized(hwnd):
    placement = win32gui.GetWindowPlacement(hwnd)
    return placement[1] == win32con.SW_MAXIMIZE


def is_fullscreen(config, fill_screen_window):
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return False
    title = win32gui.GetWindowText(hwnd)
    if not title:
        return False
    if any((
            i in title
            for i in config.configget('exclude_window')
            if i
    )):
        # print(title, 'no check')
        return False
    monitor = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST)
    mi = win32api.GetMonitorInfo(monitor)
    screen_rect = mi["Monitor"]
    win_rect = win32gui.GetWindowRect(hwnd)
    # 计算覆盖度需要超过99%
    # coverage = (win_rect[2] - win_rect[0]) / (screen_rect[2] - screen_rect[0]) > 0.99
    # coverage &= (win_rect[3] - win_rect[1]) / (screen_rect[3] - screen_rect[1]) > 0.99
    coverage = all((
        (win_rect[0]<= screen_rect[0]),
        (win_rect[1]<= screen_rect[1]),
        (win_rect[2]>= screen_rect[2]),
        (win_rect[3]>= screen_rect[3]),
    ))
    if coverage:
        # print(title,'fun 3')
        if title not in fill_screen_window:
            fill_screen_window.append(title)
        return True
    return False
def enum_windows_callback(hwnd, hwnd_list):
    # 过滤不可见窗口和零尺寸窗口
    if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowRect(hwnd) != (0,0,0,0):
        hwnd_list.append(hwnd)
    return True

def get_all_windows():
    hwnd_list = []
    win32gui.EnumWindows(enum_windows_callback, hwnd_list)
    return hwnd_list

def check_all_windows_state(config, maxsize_window, fill_screen_window):
    have_maximized = False
    have_fullscreen = is_fullscreen(config, fill_screen_window)
    # print('\n0000000000000000000000000000000000000000')
    for hwnd in get_all_windows():
        title = win32gui.GetWindowText(hwnd)
        maximized = is_maximized(hwnd)

        if maximized and title:
            if any((
                    i in title
                    for i in config.configget('exclude_window_maximize')
                    if i
            )):
                # print(title, 'no check')
                continue
            if title not in maxsize_window:
                maxsize_window.append(title)
            have_maximized = True

    return have_maximized, have_fullscreen

class CheckMaxSize:
    def __init__(
            self,
            config,
            maxsize_window,
            fill_screen_window
    ):
        self.config = config
        self.maxsize_window = maxsize_window
        self.fill_screen_window = fill_screen_window
        self.state = False
        self.last_state = False # False: 未检测到，继续运行
        self.condition = threading.Condition()
        self.state_lock = threading.Event()
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        try:
             while True:
                time.sleep(self.config.configget('screen_detect_time'))
                config_maximized = self.config.configget('maximized_screen_detect')
                config_fullscreen = self.config.configget('full_screen_detect')
                if not config_maximized and not config_fullscreen:
                    self.state = False
                    self.state_lock.set()
                    continue
                have_maximized, have_fullscreen = check_all_windows_state(
                    self.config,
                    self.maxsize_window,
                    self.fill_screen_window,
                )

                # 如果启用检测，且有应用全屏、最大化时：
                maximized = have_maximized and config_maximized
                fullscreen = have_fullscreen and config_fullscreen
                # print(maximized, fullscreen)
                self.state = maximized or fullscreen
                # print(self.state)
                if self.state:
                    self.state_lock.clear()
                else:
                    self.state_lock.set()
        except Exception as e:
            print(e)
        finally:
            self.state_lock.set()


    def check_pause(self):
        """
        检查是否暂停
        :return:
        """
        if self.state:
            self.state_lock.wait()
        return







if __name__ == '__main__':
    # 轮询示例
    n = 0
    check_maxsize = CheckMaxSize()
    while True:
        check_maxsize.check_pause()
        print(f"run{n}")
        n += 1
        time.sleep(0.1)