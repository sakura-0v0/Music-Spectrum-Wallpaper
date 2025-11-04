import subprocess
import sys
import threading
import time
import win_precise_time as wps
from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
import pythoncom
import ctypes


def get_default_playback_id():
    """精准获取系统当前默认播放设备ID"""
    pythoncom.CoInitialize()  # 初始化COM库
    try:
        # 获取默认音频端点
        devices = AudioUtilities.GetSpeakers()
        return devices.GetId()
    except Exception as e:
        print(f"音频API访问失败: {str(e)}")
        return None
    finally:
        pythoncom.CoUninitialize()


def restart(quit_queue):
    """重启"""
    print(f"{[sys.executable] + sys.argv}")
    subprocess.Popen([sys.executable] + sys.argv)

    quit_queue.put(None) # 通知show窗口退出，完成整个进程的退出
    print("重启成功" ,"xxxxxxxxxxxx"*100)
    time.sleep(1)
    # os._exit(0)
    # sys.exit(0)


def check_restart(restart_queue, quit_queue):
    """检测子进程的重启请求"""
    def func():
        msg = restart_queue.get()
        # if msg == 'restart':
        restart(quit_queue)
    threading.Thread(target=func, daemon=True).start()


def truncate_fast(value: float, decimals=3):
    """
    截断小数
    """
    n = 10 ** decimals
    value *= n
    return int(value) / n

def sleep_plus(seconds):
    """睡眠"""
    start = time.perf_counter()
    wps.sleep(seconds)
    elapsed = time.perf_counter() - start

    print(f"目标: {seconds:.6f}s, 实际: {elapsed:.6f}s, 误差: {(elapsed - seconds) * 1000:.3f}ms")



# 加载 Windows 多媒体库
winmm = ctypes.WinDLL('winmm')


# 定义结构体
class TIMECAPS(ctypes.Structure):
    _fields_ = [('wPeriodMin', ctypes.c_uint),
                ('wPeriodMax', ctypes.c_uint)]


def set_high_timer_resolution():
    """设置高精度计时器分辨率"""
    caps = TIMECAPS()
    winmm.timeGetDevCaps(ctypes.byref(caps), ctypes.sizeof(caps))

    # 设置最高可用分辨率（通常为1ms）
    resolution = caps.wPeriodMin
    winmm.timeBeginPeriod(resolution)
    return resolution


def reset_timer_resolution(resolution):
    """恢复默认计时器分辨率"""
    winmm.timeEndPeriod(resolution)
