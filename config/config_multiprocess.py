# 多进程配置模块
# 主进程中实例化ConfigProcess，子进程中实例化ConfigProcessTools。
# 通过双向管道实现子进程对主进程配置文件的读写。
import multiprocessing
import threading
import traceback

from .config import Config


class ConfigInMainProcessPipe:
    """
    config多进程的主进程管道口。
    每个进程都需要在主进程实例化一个。
    """
    def __init__(self, config: Config):
        """
        初始化
        Args:
            config: 主进程中的配置单例
        """
        self.config = config
        self.config_set_queue = multiprocessing.Queue()# 子进程-》主进程
        self.config_get_queue = multiprocessing.Queue()# 主进程-》子进程
        # 注册队列
        #   当config被修改时，通过这个队列向所有进程发送新配置
        self.config.queues.append((
            self.config_set_queue,
            self.config_get_queue
        ))

        self._loop_thread = threading.Thread(target=self._loop, daemon=True)
        self._loop_thread.start()

    def get_queues(self):
        """将这两个对象传递给子进程"""
        return self.config_set_queue, self.config_get_queue

    def _loop(self):
        while True:
            msg = self.config_set_queue.get()
            if msg is None:
                break
            args = msg.get("args", [])
            if msg['call'] == 'configset':
                self.config.configset(*args)
            # if msg['call'] == 'configget':
            #     self.config_get_queue.put(self.config.configget(*args))
            if msg['call'] == 'configreset':
                self.config.configreset(*args)
            if msg['call'] == 'configgetall':
                self.config_get_queue.put(self.config.config)
            # 当有进程修改了配置，通知所有进程更新配置

    def close(self):
        try:
            self.config_set_queue.put(None)
            self._loop_thread.join()
        except:
            traceback.print_exc()


class ConfigInChildProcessPipe:
    """
    在子进程中实例化，与主进程中的ConfigProcess通信。
    通过传入双向管道实现子进程对配置文件的读写。
    """
    def __init__(
            self,
            config_set_queue: multiprocessing.Queue,
            config_get_queue: multiprocessing.Queue,
    ):
        """
        初始化
        Args:
            config_set_queue: 主进程-》子进程(当config被修改时，接收修改消息)
            config_get_queue: 子进程-》主进程
        """

        self.config_set_queue = config_set_queue
        self.config_get_queue = config_get_queue
        self.config = {}
        self._init_config()
        print('success init config process tools')
        self._update_config_loop_thread = threading.Thread(target=self._update_config_loop, daemon=True)
        self._update_config_loop_thread.start()

    def configget(self, key):
        """获取设置 in:key out:value"""
        result = self.config.get(key)
        return result

    def configset(self, key, value):
        """修改设置"""
        self.config[key] = value
        self.config_set_queue.put({
            'call': 'configset',
            'args': [key, value],
        })

    def configreset(self, key):
        '''恢复默认设置'''
        self.config_set_queue.put({
            'call': 'configreset',
            'args': [key],
        })

    def _init_config(self):
        self.config_set_queue.put({
            'call': 'configgetall',
        })
        self.config = self.config_get_queue.get()

    def _update_config_loop(self):
        """收到更新配置的消息，更新本地配置"""
        while True:
            config = self.config_get_queue.get()
            if config is None:
                break
            self.config = config

    def close(self):
        try:
            self.config_get_queue.put(None)
            self._update_config_loop_thread.join()
        except:
            traceback.print_exc()
