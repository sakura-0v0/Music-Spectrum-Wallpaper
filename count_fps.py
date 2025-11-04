import threading
import time
from multiprocessing import Value

class CountFpsShare:
    """
    FPS计数器的管理中心，
    用于统一管理FPS计数器的共享变量
    """
    share_fps = {}
    @classmethod
    def print_fps(cls):
        print('===================== FPS =========')
        for name, value in cls.share_fps.items():
            print(f"{name}: {value.value}FPS")
        print('===================================')

    print_fps_threading_quit: bool = False

    @classmethod
    def set_fps_share(cls, name: str) -> Value:
        """
        将FPS的共享变量加入字典
        :param name:
        :return: Value
        """
        cls.share_fps[name] = Value('i', 0)
        return cls.share_fps[name]
    @classmethod
    def start_print_fps_thread(cls):
        threading.Thread(target=cls.print_fps_thread, daemon=True).start()

    @classmethod
    def print_fps_thread(cls):
        """
        控制台打印FPS线程
        """
        while not cls.print_fps_threading_quit:
            # cls.print_fps()
            time.sleep(1)

        print('Quit print_fps_thread')

class CountFps:

    def __init__(self, name, share_fps = None):
        """
        初始化FPS计数器
        :param name:
        :param share_fps: 当需要在子进程中使用FPS计数器时，需要在主进程中定义并传入传入共享变量
        """
        self.last_fps_time = None
        self.fps = 0

        self.update_count = 0
        self.name = name
        if share_fps is None:
            self.share_fps = CountFpsShare.set_fps_share(name)
        else:
            # 子进程中使用FPS计数器时，使用传入的共享变量
            self.share_fps = share_fps

        self.my_loop = threading.Thread(target=self._loop, daemon=True)
        self.my_loop.start()


    def count_fps(self):
        """
        在需要计数的地方调用
        :return:
        """
        self.update_count += 1

    def _loop(self):
        while True:
            self.fps = self.update_count
            self.share_fps.value = self.fps
            self.update_count = 0
            # print(f"{self.name}: {self.fps}FPS")
            time.sleep(1)