import threading
from typing import Callable
import ctypes
import time


class RunPage:
    def __init__(
            self,
            get_fps_func: Callable,
            run_func: Callable ,
            run = True
    ):
        """

        :param get_fps_func: 获取fps的方法
        :param run_func: 需要按fps为上限运行的方法
        """
        self.get_fps_func = get_fps_func
        self.run_func = run_func

        self.time_index = 0
        self.fps = 0
        self.a_page_time = 0.0
        self.times = []
        self.running = threading.Thread(target=self._run_loop, daemon=True)
        self.stop_flag = False
        if run:
            self.run()

    def run(self):
        self.running.start()

    def stop(self):
        self.stop_flag = True
        self.running.join()

    def _run_loop(self):
        """
        按设定fps速率为上限，运行函数。
        """
        # 设置高精度定时器分辨率
        winmm = ctypes.WinDLL('winmm')
        winmm.timeBeginPeriod(ctypes.c_uint(1))

        last_int_time = 0 # 记录上一次的秒数
        try:
            while not self.stop_flag:
                now = time.perf_counter()
                int_time = int(now)
                # 检查更新fps
                new_fps = self.get_fps_func()
                if new_fps != self.fps:
                    self.update_fps(new_fps)
                if int_time != last_int_time:
                    # 重置index
                    self.time_index = 0
                    last_int_time = int_time
                point = now - int_time
                page_point = self.times[self.time_index]
                cut = point - page_point
                if cut >= 0:
                    # 当前时间点已超过当前页面应该运行的时间，运行函数
                    self.run_func()
                    self.time_index += 1
                    if self.time_index >= len(self.times):
                        # 索引达到上限时重置
                        self.time_index = 0
                    if cut < self.a_page_time:
                        # 当前时间点如果已超过预定时间点1ms，则不执行sleep
                        time.sleep(0.001)

                else:
                    # 未到达预定时间点，则sleep
                    time.sleep(0.001)
        finally:
            # 恢复默认定时器分辨率
            winmm.timeEndPeriod(ctypes.c_uint(1))


    def update_fps(self, fps):
        """
        更新fps
        :param fps: fps值
        :return:
        """
        self.fps = fps
        self.a_page_time = 1 / self.fps
        # 生成每秒的时间序列
        self.times = [self.a_page_time * i for i in range(self.fps)]
        self.time_index = 0

if __name__ == '__main__':
    config = {
        'fps': 2670
    }

    # fps计数器
    n = 0
    def count_fps():
        global n
        while True:
            print(n)
            n = 0
            time.sleep(1)

    fps_counter = threading.Thread(target=count_fps, daemon=True)
    fps_counter.start()

    # 需要按设置的频率为上限运行的函数
    def func():
        global n
        n += 1 # 运行次数+1，用于计算fps

    # 可随时改变fps，会自动同步fps
    RunPage(
        lambda: config.get('fps'), # 获取fps的方法，可即时更新
        func # 需要按fps为上限运行的方法
    )

    input()
