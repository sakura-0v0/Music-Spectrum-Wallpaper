"""多进程配置 —— 主进程侧的管道口 + 子进程侧的配置实例。

子进程那一侧就是一个完整的配置对象。 ``ConfigInChildProcessPipe`` 和
:class:`~xiaoe_config_manager.config.Config` 是同一套接口（点操作、``on`` /
``value_changed``、``get('all')``），构造方式是
``ConfigInChildProcessPipe(*pipe.get_queues())``。子进程里要开 Qt 窗口，把它交给
``xiaoe_ui.config.bridge.ConfigInChildProcessPipeBridge`` 就行。

通知是自动的，不需要手工接线：

* 本进程写 → 乐观写当场派发（``set`` 返回时值已生效）；
* 别的进程写 → 广播回来时按逐键 diff 派发；自己写出去又广播回来的回声
  正好被 diff 吞掉（``before == after``），所以不会双发；
* 主进程处理子进程的写入时，走的是 ``Config.set`` —— 派发点只有那一个，
  所以也不会双发。

写入语义是乐观的（先改本地缓存、再发消息），``reset`` 是悲观的（只发消息，
本地缓存等广播回来才变）—— 这条不对称是刻意的：跨进程的写操作一律经主进程统一
处理。
"""

from __future__ import annotations

import copy
import logging
import multiprocessing
import queue
import threading
import traceback
from typing import Any

from xiaoe_config_manager.config_base import ConfigBase

__all__ = [
    "ConfigInMainProcessPipe",
    "ConfigInChildProcessPipe",
    "diff_changes",
]

log = logging.getLogger(__name__)

#: 子进程启动时等"第一份完整配置"的秒数；超时说明主进程管道没起来，
#: 直接报错比永久阻塞好（永久阻塞的表现是"子进程再也起不来"，没有任何线索）。
INIT_TIMEOUT = 30.0


def diff_changes(before: dict, after: dict) -> list:
    """逐键 diff：只报真的变了的键，返回 ``[(key, value), ...]``。

    两个用处：

    1. "整份配置替换"是广播的形式（子进程收到的是整个 dict），逐键 diff 才能
       报出"到底哪些键变了"；
    2. 子进程写入是乐观的（先改本地缓存、再发消息），主进程处理完会把整份
       配置广播回来 —— 那一发回声在这里被 ``before == after`` 自然吞掉，
       不会让写入方收到两次通知。
    """
    return [(k, v) for k, v in after.items() if before.get(k) != v]


class ConfigInMainProcessPipe:
    """主进程侧的管道口：每个子进程在主进程里对应一个实例。

    它把队列注册进 ``config.queues``（于是 ``config.set`` 会自动广播），并起一个
    线程收子进程的消息。收到之后直接调 ``config.set`` / ``config.reset`` ——
    通知由 ``config`` 自己的派发点发出，这里不另外发通知（否则就是双发）。
    """

    def __init__(self, config: ConfigBase):
        """
        Args:
            config: 主进程里的配置单例。
        """
        self.config = config
        self.config_set_queue = multiprocessing.Queue()   # 子进程 → 主进程
        self.config_get_queue = multiprocessing.Queue()   # 主进程 → 子进程
        # 注册队列：配置被修改时，通过这个队列向所有进程发送新配置
        self.config.queues.append((
            self.config_set_queue,
            self.config_get_queue,
        ))

        self._loop_thread = threading.Thread(target=self._loop, daemon=True)
        self._loop_thread.start()

    def get_queues(self):
        """把这两个队列对象传给子进程。"""
        return self.config_set_queue, self.config_get_queue

    def _loop(self):
        """收子进程消息的守护线程。

        任何一条消息出问题都不许把线程带走 —— 线程一死，之后所有子进程的写入
        都只会改各自的内存副本，主进程的文件再也不更新，而且没有任何一方收到错误。
        所以循环体整个包在 ``try`` 里，只记录不退出。
        """
        while True:
            msg = self.config_set_queue.get()
            if msg is None:
                break
            try:
                self._handle(msg)
            except Exception:                        # noqa: BLE001
                log.exception("处理子进程的配置消息失败，已跳过：%r", msg)

    def _handle(self, msg: dict):
        """处理一条子进程消息。

        Args:
            msg: ``{'call': 动作名, 'args': [...]}``；认不出来的动作只记一条
                warning（不抛、也不回错误 —— 老版本子进程的协议可能对不上）。
        """
        call = msg.get("call")
        args = msg.get("args", [])
        if call == "configset":
            self.config.set(*args)
        elif call == "configreset":
            self.config.reset(*args)
        elif call == "configgetall":
            self.config_get_queue.put(self.config.config)
        else:
            log.warning("收到无法识别的配置管道消息，已忽略：%r", msg)

    def close(self):
        """结束收消息线程（结束时必须调用）。"""
        try:
            self.config_set_queue.put(None)
            self._loop_thread.join()
        except Exception:                            # noqa: BLE001
            traceback.print_exc()
        try:
            self.config.queues.remove((self.config_set_queue, self.config_get_queue))
        except ValueError:
            pass
        for q in (self.config_set_queue, self.config_get_queue):
            try:
                q.close()
                q.join_thread()
            except Exception:
                traceback.print_exc()


class ConfigInChildProcessPipe(ConfigBase):
    """子进程侧的配置实例 —— 与 :class:`Config` 同一套接口。

    读一律读本地缓存（零跨进程开销），写是乐观的，``reset`` 是悲观的。
    生命周期结束时调 :meth:`close`。
    """

    def __init__(
            self,
            config_set_queue: multiprocessing.Queue,
            config_get_queue: multiprocessing.Queue,
    ):
        """
        Args:
            config_set_queue: 子进程 → 主进程（写操作发这里）。
            config_get_queue: 主进程 → 子进程（配置广播收这里）。
        """
        super().__init__()
        self.config_set_queue = config_set_queue
        self.config_get_queue = config_get_queue
        self._init_config()

        self._update_config_loop_thread = threading.Thread(
            target=self._update_config_loop, daemon=True)
        self._update_config_loop_thread.start()

    # ══════════════════════════════════════════════════════════
    # 存储原语
    # ══════════════════════════════════════════════════════════

    def _read(self, key: str) -> Any:
        """读本地缓存。

        返回的是**深拷贝**：调用方改这个值（哪怕它是嵌套的 list / dict）也不会
        动到本地缓存里那份。

        Args:
            key: 配置键名。

        Raises:
            KeyError: 键不在本地缓存里 —— 主进程与子进程表现一致，缺键一律报错，
                不静默返回 ``None``。
        """
        return copy.deepcopy(self.config[key])

    def _read_all(self) -> dict:
        """整份配置的本地快照（深拷贝）。

        子进程的本地缓存本来就是"主进程广播过来的那一整份配置"，所以这里和
        :meth:`ConfigMemory._read_all` 是同一件事，取整份并不需要走队列。

        与文件版的差别只在新鲜度：文件版会重读磁盘（拿到的一定是最新的），
        这里给的是**最近一次广播**的快照，可能比主进程晚一发；自己刚 ``set``
        的值一定在（写是乐观的）。要严格最新就回主进程读。
        """
        return copy.deepcopy(self.config)

    def _write(self, key: str, value: Any) -> None:
        """乐观写：先改本地缓存（于是 ``set`` 返回时值已生效），再发消息给主进程。

        缓存里存的是 ``value`` 的**深拷贝**：调用方之后改自己那个对象，缓存不受影响。

        Args:
            key: 配置键名。
            value: 配置值。
        """
        self.config[key] = copy.deepcopy(value)
        self.config_set_queue.put({
            'call': 'configset',
            'args': [key, value],
        })

    def _apply_reset(self, key: str) -> None:
        """悲观重置：只发消息，本地缓存要等主进程广播回来才变。

        所以 ``reset`` 返回时读到的可能还是旧值 —— 这是设计（跨进程的写一律经主进程
        统一处理），不是 bug；广播到达时会按 diff 派发正确的新值。

        Args:
            key: 配置键名，或 ``'all'``。
        """
        self.config_set_queue.put({
            'call': 'configreset',
            'args': [key],
        })

    def _save(self) -> None:
        """子进程不写文件（落盘在主进程）。"""

    def _flush_locked(self) -> None:
        """子进程不写文件（落盘在主进程）。"""

    # ══════════════════════════════════════════════════════════
    # 同步
    # ══════════════════════════════════════════════════════════

    def _init_config(self):
        """向主进程要一份完整配置，并等它回来。"""
        self.config_set_queue.put({'call': 'configgetall'})
        try:
            self.config = self.config_get_queue.get(timeout=INIT_TIMEOUT)
        except queue.Empty as exc:
            raise RuntimeError(
                f"等主进程的配置广播超时（{INIT_TIMEOUT:g}s）—— 主进程的 "
                f"ConfigInMainProcessPipe 还没起来，或者管道对象传错了。"
            ) from exc

    def _update_config_loop(self):
        """收到广播 → 替换本地缓存 → 把变化的键派发出去。

        自己写出去的那一发回声在这里被 ``diff_changes`` 吞掉（本地缓存已经是新值），
        所以不会双发。

        派发的是**深拷贝**：监听器改它不会动到本地缓存（缓存里那份就是刚收到的新值）。
        """
        while True:
            config = self.config_get_queue.get()
            if config is None:
                break
            before = self.config
            self.config = config
            if isinstance(before, dict) and isinstance(config, dict):
                for key, value in diff_changes(before, config):
                    self._dispatch(key, copy.deepcopy(value))

    def close(self):
        """结束收广播的线程（结束时必须调用）。"""
        try:
            self.config_get_queue.put(None)
            self._update_config_loop_thread.join()
        except Exception:                            # noqa: BLE001
            traceback.print_exc()
        for q in (self.config_set_queue, self.config_get_queue):
            try:
                q.close()
                q.join_thread()
            except Exception:
                traceback.print_exc()
