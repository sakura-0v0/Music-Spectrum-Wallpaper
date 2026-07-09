import multiprocessing
import os
os.environ["QT_FONT_DPI"] = "96"
import sys
import traceback
from threading import Thread

import numpy as np
from PySide6.QtWidgets import QApplication
from xiaoe_ui import resolve_static, WinManager
from xiaoe_ui.utils.to_china_text import to_china_text

from xiaoe_config_manager import ConfigInChildProcessPipe
from config_objs import engine, theme_cfg, config_manager
from config_ui.main_win import App
from driver import SoundDriver
from fft_process import run_fft_process
from multiprocess_data_manager import MultiProcessDataManager, kill_process
from pl_manager import PlManager
from show import Show
from xiaoe_ui import run_in_main_block

class Main:
    def __init__(self):

        self.app = QApplication(sys.argv)
        to_china_text(self.app, "translations")
        load_app_skin()
        self.multiprocess_datas = MultiProcessDataManager(
            start_processes = self.start_processes,
            main_quit_func = self.main_quit_func,
            restart_status_signal = self.set_restart_btn_status,

        )

        self.config_win = App(
            self.multiprocess_datas
        )

        with self.multiprocess_datas.loading_lock:
            if self.multiprocess_datas.processes_is_loading:
                self.config_win.set_restart_btn_status(
                    False, first=True
                )

        s = self.app.exec()
        self.multiprocess_datas.wait_quit_thread.join(20)
        print('quit_process_main_win')
        sys.exit(s)

    def set_restart_btn_status(self, status: bool):
        if not hasattr(self, "config_win"):
            print('no has')
            return
        self.config_win.restart_signal.emit(status)

    def main_quit_func(self):
        def func():
            self.config_win.show()
            self.app.quit()
        run_in_main_block(func)

    def start_processes(self):
        self.pl_manager = PlManager(config_manager)
        self.sound_p = multiprocessing.Process(
            target=run_sound,
            args=(
                self.multiprocess_datas.main_config_process_sound.get_queues(),  # 队列参数
                self.pl_manager.pl,
                self.multiprocess_datas.quit_driver_queue,
                self.multiprocess_datas.data_pipe[0],
                self.multiprocess_datas.count_fps_FFT_value,
                self.multiprocess_datas.count_fps_Record_value,
                self.multiprocess_datas.maxsize_window,
                self.multiprocess_datas.fill_screen_window,
                self.multiprocess_datas.wait_quit_queue,
                self.multiprocess_datas.fft_in_left_queue,
            ),
            kwargs={
                "fft_in_left_queue": self.multiprocess_datas.fft_in_left_queue,
                "left_volume_value": self.multiprocess_datas.left_volume_value,
                "right_volume_value": self.multiprocess_datas.right_volume_value,
            },
            name="FFT主进程",
        )
        self.multiprocess_datas.sound_p = self.sound_p
        self.sound_p.start()

        self.show_win_process = multiprocessing.Process(
            target=run_show,
            args=(
                self.multiprocess_datas.main_config_process_show.get_queues(),
                self.pl_manager.pl,
                self.multiprocess_datas.maxsize_window,
                self.multiprocess_datas.fill_screen_window,
                self.multiprocess_datas.wait_quit_queue,
                self.multiprocess_datas.quit_show_queue,
                self.multiprocess_datas.left_volume_value,
                self.multiprocess_datas.right_volume_value,
                self.multiprocess_datas.count_fps_Show_value,
                self.multiprocess_datas.open_main_win,
            ),
            kwargs={
                "data_pipe": self.multiprocess_datas.data_pipe,
            }
        )

        self.show_win_process.start()

        self.multiprocess_datas.processes.append(self.sound_p)
        self.multiprocess_datas.processes.append(self.show_win_process)

def load_app_skin():
    _default_ico = resolve_static("icos/logo.ico")
    # with resources.path('xiaoe_ui', 'demo_static/background.png') as path:
    background_path = resolve_static("icos/background.png")
    engine.set_internal_default("bg_image", background_path)
    WinManager.set_icon_source(_default_ico)                                # 全局图标
    WinManager.set_style_source(lambda: engine.make_style(theme_cfg))        # QSS 生成函数
    WinManager.set_bg_source(lambda: engine.resolve_value(theme_cfg, "bg_image"))


def run_sound(
        config_queues,
        *args,
        fft_in_left_queue,
        left_volume_value,
        right_volume_value,
):
    # 在子进程中创建管道B
    config = ConfigInChildProcessPipe(*config_queues)

    print("Starting sound process")
    driver = SoundDriver(
        config,
        *args,
    )
    fft_process = run_fft_process(
        fft_in_left_queue = fft_in_left_queue,
        left_volume_value=left_volume_value,
        right_volume_value=right_volume_value
    )  # 开启FFT处理进程
    # try:
    driver.get_input_device() # 获取音频设备
    driver.record_fft_thread.start() # 开启fft窗口更新线程
    driver.check_default.start() # 开启默认音频设备变更检测线程
    driver.sound_loop() # 开启音频流读取 + 音频重采样循环
    config.close()
    try:
        fft_process.join(1)
        kill_process(fft_process)
    except KeyboardInterrupt:
        pass

    print("quit_process_sound------------------- ")
    sys.exit(0)

def run_show(
    config_queues,
    *args,
    data_pipe,
):
    # 在子进程中创建管道B
    config = ConfigInChildProcessPipe(*config_queues)
    load_app_skin()
    app = QApplication(sys.argv)
    show_win = Show(
        config,
        app,
        *args,
    )
    show_thread = Thread(
        target=show_updater,
        args=(
            data_pipe[1],
            show_win,
        ),
        daemon=True
    )

    show_thread.start()
    s = app.exec()
    config.close()
    print("quit_process_show------------------")
    # sys.exit(s)


def show_updater(data_pipe, show_win):
    print('starting show thread')
    try:
        while True:
            try:
                magnitudes = data_pipe.recv()
                if magnitudes is None:
                    break
                show_win.update_data(np.arange(len(magnitudes)), magnitudes)
                data_pipe.send(None)
            except ValueError:
                traceback.print_exc()
                # print("show thread ValueError")
                # 更新图形
    except EOFError:
        ...
    print("quit_thread_update_show-------------------")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main = Main()

