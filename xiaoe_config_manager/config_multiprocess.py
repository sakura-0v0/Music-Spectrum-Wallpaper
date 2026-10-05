# 多进程配置模块
# 主进程中实例化ConfigProcess，子进程中实例化ConfigProcessTools。
# 通过双向管道实现子进程对主进程配置文件的读写。
import multiprocessing
import threading
import traceback
from typing import Any, Callable

from xiaoe_config_manager.config_api import ConfigApi, NewConfigApiProxy
from xiaoe_config_manager.config_dot import ConfigDeclareMixin

from .config import Config


def diff_changes(before: dict, after: dict) -> list:
    """逐键 diff：只报**真的变了**的键，返回 ``[(key, value), ...]``。

    两个用处：

    1. "整份配置替换"是广播的形式（子进程收到的是整个 dict），逐键 diff 才能
       报出"到底哪些键变了"；
    2. 子进程写入是**乐观**的（先改本地缓存、再发消息），主进程处理完会把整份
       配置广播回来 —— 那一发回声在这里被 ``before == after`` 自然吞掉，
       不会让写入方收到两次通知。
    """
    return [(k, v) for k, v in after.items() if before.get(k) != v]


class ConfigInMainProcessPipe:
    """
    config多进程的主进程管道口。
    每个进程都需要在主进程实例化一个。

    另外提供 :meth:`on_remote_change` —— "**别的进程**改了配置"的回调。
    本进程自己写的不走这里（那是调用方自己的动作，谁写谁知道）。
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
        #: 外部变更回调（签名 (key, value)）；在 `_loop` 线程里被调用
        self._remote_cbs: list = []
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

    # ══════════════════════════════════════════════════════════
    # 外部变更通知
    # ══════════════════════════════════════════════════════════

    def on_remote_change(self, callback: Callable[[str, Any], None]) -> None:
        """注册"别的进程改了配置"的回调，签名 ``(key, value)``。

        * 只在**子进程写进来**时触发；主进程自己写的（走 bridge 或直写实例）
          不触发 —— 那是调用方自己的动作，不需要别人告诉它；
        * 整份广播按**逐键 diff** 报，只报真的变了的键；
        * 回调在**管道自己的 `_loop` 线程**里执行（不是主线程！）。要把值送到
          UI，请交给 :meth:`xiaoe_ui.ConfigBridge.notify_change`，它会排队回桥
          所在线程::

              pipe = ConfigInMainProcessPipe(cfg_instance)
              pipe.on_remote_change(show_cfg.notify_change)
        """
        self._remote_cbs.append(callback)

    def off_remote_change(self, callback: Callable[[str, Any], None]) -> None:
        """取消 :meth:`on_remote_change` 注册的回调（必须传同一个函数引用）。"""
        if callback in self._remote_cbs:
            self._remote_cbs.remove(callback)

    def _fire_remote(self, key: str, value: Any) -> None:
        """把一次变更发给所有外部变更回调。

        注意：这里**不在** ``config_lock`` 里面 —— `_loop` 调完 `configset` /
        `configreset`（它们自己会加锁并释放）之后才走到这儿。回调里再写配置
        不会死锁（锁不可重入）。
        """
        for callback in tuple(self._remote_cbs):
            callback(key, value)

    def _fire_remote_diff(self, before: dict) -> None:
        for key, value in diff_changes(before, self.config.config):
            self._fire_remote(key, value)

    def _loop(self):
        while True:
            msg = self.config_set_queue.get()
            if msg is None:
                break
            args = msg.get("args", [])
            if msg['call'] == 'configset':
                before = dict(self.config.config)
                self.config.configset(*args)
                self._fire_remote_diff(before)
            # if msg['call'] == 'configget':
            #     self.config_get_queue.put(self.config.configget(*args))
            if msg['call'] == 'configreset':
                before = dict(self.config.config)
                self.config.configreset(*args)
                self._fire_remote_diff(before)
            if msg['call'] == 'configgetall':
                self.config_get_queue.put(self.config.config)
            # 当有进程修改了配置，通知所有进程更新配置

    def close(self):
        try:
            self.config_set_queue.put(None)
            self._loop_thread.join()
        except Exception:
            traceback.print_exc()


class ConfigInChildProcessPipe(NewConfigApiProxy, ConfigDeclareMixin, ConfigApi):
    """
    在子进程中实例化，与主进程中的ConfigProcess通信。
    通过传入双向管道实现子进程对配置文件的读写。

    写入是**乐观**的：先改本地缓存、再把消息发给主进程；主进程落盘后把整份配置
    广播回来。读一律读本地缓存（零跨进程开销）。

    另外提供 :meth:`on_remote_change` —— "**别的进程**改了配置"的回调。
    自己写的不走这里（乐观写当场就改了本地缓存，谁写谁知道）。
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
        #: 外部变更回调（签名 (key, value)）；在 `_update_config_loop` 线程里被调用
        self._remote_cbs: list = []
        self._init_config()
        print('success init config process tools')
        self._update_config_loop_thread = threading.Thread(target=self._update_config_loop, daemon=True)
        self._update_config_loop_thread.start()

    # ══════════════════════════════════════════════════════════
    # 外部变更通知
    # ══════════════════════════════════════════════════════════

    def on_remote_change(self, callback: Callable[[str, Any], None]) -> None:
        """注册"别的进程改了配置"的回调，签名 ``(key, value)``。

        * 只在**主进程广播下来**时触发。子进程自己 ``set`` / ``reset`` 不触发：
          乐观写已经改了本地缓存，调用方自己知道；广播回来的那一发回声会被
          逐键 diff 吞掉，所以**不会重复通知**；
        * 回调在**管道自己的 `_update_config_loop` 线程**里执行。要送到 UI，
          请交给 :meth:`xiaoe_ui.ConfigBridge.notify_change`（它排队回桥所在线程）::

              cfg = ConfigInChildProcessPipe(*queues)
              show_cfg = ShowBridge(instance=cfg)
              cfg.on_remote_change(show_cfg.notify_change)
        """
        self._remote_cbs.append(callback)

    def off_remote_change(self, callback: Callable[[str, Any], None]) -> None:
        """取消 :meth:`on_remote_change` 注册的回调（必须传同一个函数引用）。"""
        if callback in self._remote_cbs:
            self._remote_cbs.remove(callback)

    def _fire_remote(self, key: str, value: Any) -> None:
        for callback in tuple(self._remote_cbs):
            callback(key, value)

    # ══════════════════════════════════════════════════════════

    def configget(self, key):
        """获取设置 in:key out:value"""
        result = self.config.get(key)
        return result

    def configset(self, key, value):
        """修改设置（乐观：先改本地缓存，再让主进程落盘+广播）"""
        self.config[key] = value
        self.config_set_queue.put({
            'call': 'configset',
            'args': [key, value],
        })

    def configreset(self, key):
        """恢复默认设置（只发消息 —— 本地缓存要等主进程广播回来才变）"""
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
        """收到更新配置的消息，更新本地配置，并把**变化的键**报给外部变更回调"""
        while True:
            config = self.config_get_queue.get()
            if config is None:
                break
            before = self.config
            self.config = config
            if isinstance(before, dict) and isinstance(config, dict):
                for key, value in diff_changes(before, config):
                    self._fire_remote(key, value)

    def close(self):
        try:
            self.config_get_queue.put(None)
            self._update_config_loop_thread.join()
        except Exception:
            traceback.print_exc()
