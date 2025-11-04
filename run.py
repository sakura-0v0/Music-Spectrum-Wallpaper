import traceback
from threading import Thread

import numpy as np

from config import Config
from config_multiprocess import ConfigInMainProcessPipe, ConfigInChildProcessPipe
from count_fps import CountFps, CountFpsShare
from driver import SoundDriver
import multiprocessing

from fft_process import run_fft_process
from show import Show
from tools import check_restart


def run_sound(
        queues,
        *args,
        **kwargs,
):
    # 在子进程中创建管道B
    config = ConfigInChildProcessPipe(*queues)

    print("Starting sound process")
    driver = SoundDriver(
        config,
        *args,
        **kwargs,
    )
    try:
        run_fft_process() # 开启FFT处理进程

        driver.get_input_device() # 获取音频设备
        driver.record_fft_thread.start() # 开启fft窗口更新线程
        driver.check_default.start() # 开启默认音频设备变更检测线程
        driver.check_quit.start() # 开启退出检测线程
        driver.sound_loop() # 开启音频流读取 + 音频重采样循环
    finally:
        print("quit_sound_process------------------- ")

def show(data_queue,show_win):
    print('starting show thread')
    try:
        while True:
            try:
                magnitudes = data_queue.recv()
                show_win.update_data(np.arange(len(magnitudes)), magnitudes)
                data_queue.send(None)
            except ValueError:
                traceback.print_exc()
                # print("show thread ValueError")
                # 更新图形
    except EOFError:
        print("quit_update_show_thread-------------------")

def sound_main():
    """
    主函数
    :return:
    """
    config = Config()

    # 存储最大化窗口，全屏窗口
    # 被check_maxsize检测识别到的窗口，在comfig_win中列出
    manager = multiprocessing.Manager()
    maxsize_window = manager.list()
    fill_screen_window = manager.list()

    # 初始化fps管理中心，用于统一存储所有fps数值
    count_fps_share = CountFpsShare()
    count_fps_FFT_value = count_fps_share.set_fps_share("FFT")
    count_fps_Record_value = count_fps_share.set_fps_share("Record")


    # 管道初始化
    class WinAppQueues:
        def __init__(self):
            self.quit_pipe = multiprocessing.Pipe() # 在获取音频数据流中接收退出信号
            self.data_pipe = multiprocessing.Pipe() # 用于FFT后的数据传递到show进程进行显示
            self.quit_queue = multiprocessing.Queue() # 在show进程中接收退出信号
            self.restart_queue = multiprocessing.Queue()

    win_app_queues = WinAppQueues()

    # 监听子进程的重启信号，子进程通过restart_queue.put('restart')发送重启信号
    check_restart(win_app_queues.restart_queue, win_app_queues.quit_queue)

    # 主进程中创建管道A
    config_process = ConfigInMainProcessPipe(config)

    sound_p = multiprocessing.Process(
        target=run_sound,
        args=(
            config_process.get_queues(),# 队列参数
            win_app_queues.quit_pipe[0],
            win_app_queues.data_pipe[0],
            config.pl,
            count_fps_FFT_value,
            count_fps_Record_value,
            maxsize_window,
            fill_screen_window,
            win_app_queues.restart_queue,
        ),
        name = "FFT主进程",
        # daemon=True
    )
    sound_p.start()

    show_win = Show(
        config,
        maxsize_window,
        fill_screen_window,
        win_app_queues.quit_queue,
        win_app_queues.restart_queue,
    )

    show_thread = Thread(
        target=show,
        args=(
            win_app_queues.data_pipe[1],
            show_win,
        ),
        daemon=True
    )

    show_thread.start()

    CountFpsShare.start_print_fps_thread()

    show_win.app.exec_()

    # input("Press Enter to stop...")
    CountFps.print_fps_threading_quit = True
    # quit_queue.put(None)

    win_app_queues.quit_pipe[1].send(None)
    print('quit_main-------------------')



if __name__ == '__main__':
    multiprocessing.freeze_support()
    sound_main()






