import multiprocessing
import subprocess
import threading
from typing import TYPE_CHECKING, Callable

from xiaoe_ui import run_in_main_block

from config import ConfigInMainProcessPipe
from config_objs import config_manager
from count_fps import CountFpsShare
from pl_manager import PlManager

if TYPE_CHECKING:
    from run import Main

class MultiProcessDataManager:
    """进程管理中心，必须在主进程中实例化"""
    def __init__(
            self,
            start_processes: Callable[[], None],
            main_quit_func: Callable[[], None],
            restart_status_signal: Callable[[bool], None],
    ):
        self.open_main_win = multiprocessing.Queue()
        self.loading_lock = threading.Lock()
        self.processes_is_loading = True
        self.wait_quit_queue: multiprocessing.Queue|None = None
        self.start_processes = start_processes
        self.main_quit_func = main_quit_func
        self.restart_status_signal = restart_status_signal
        self.processes = []
        self.wait_quit()

    def init_obj(self):
        self.main_config_process_sound = ConfigInMainProcessPipe(config_manager)
        self.main_config_process_show = ConfigInMainProcessPipe(config_manager)

        self.manager = multiprocessing.Manager()
        self.maxsize_window = self.manager.list()
        self.fill_screen_window = self.manager.list()

        # 初始化fps管理中心，用于统一存储所有fps数值
        self.count_fps_share = CountFpsShare()
        self.count_fps_FFT_value = self.count_fps_share.set_fps_share("FFT")
        self.count_fps_Record_value = self.count_fps_share.set_fps_share("Record")
        self.count_fps_Show_value = self.count_fps_share.set_fps_share("显示")

        self.wait_quit_queue = multiprocessing.Queue()  # 等等退出或重启信号

        self.quit_driver_queue = multiprocessing.Queue()  # 在获取音频数据流中接收退出信号
        self.quit_show_queue = multiprocessing.Queue()  # 在显示频谱窗口中接收退出信号
        self.quit_fft_queue = multiprocessing.Queue()  # 在FFT中接收退出信号

        self.data_pipe = multiprocessing.Pipe()  # 用于FFT后的数据传递到show进程进行显示

        self.fft_in_left_queue = multiprocessing.JoinableQueue()
        self.left_volume_value = multiprocessing.Value('f', 0.0)
        self.right_volume_value = multiprocessing.Value('f', 0.0)


    def wait_quit(self):
        self.wait_quit_thread = threading.Thread(
            target=self._wait_quit,
            daemon=True
        )
        self.wait_quit_thread.start()

    def _wait_quit(self):
        while True:
            self.init_obj()
            self.start_processes()

            with self.loading_lock:
                self.processes_is_loading = False
                self.restart_status_signal(True)

            info = self.wait_quit_queue.get(block=True)

            with self.loading_lock:
                self.processes_is_loading = True
                self.restart_status_signal(False)

            print(info)
            CountFpsShare.quit_all_fps()
            self.quit_processes()
            if info == "quit":
                self.main_quit_func()
                break
            if info == "restart":
                print("restart----ing")

    def quit_processes(self):
        self.quit_driver_queue.put(None)
        self.quit_show_queue.put(None)
        self.quit_fft_queue.put(None)

        self.fft_in_left_queue.put(None)

        self.data_pipe[0].send(None) # 不用于退出，仅激活
        self.data_pipe[1].send(None) # 退出

        self.main_config_process_sound.close()
        self.main_config_process_show.close()

        for process in self.processes:
            process.join(3)
            kill_process(process)


def kill_process(process: multiprocessing.Process):
    process.kill()
    process.join(1)
    if process.is_alive():
        print(f"{process.pid} process killed")
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(process.pid)],
                       capture_output=True)