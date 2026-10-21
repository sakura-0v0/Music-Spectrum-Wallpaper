"""多进程配置 —— 主进程侧的管道口 + 子进程侧的配置实例。

子进程那一侧是一个完整的配置对象，和 :class:`~xiaoe_config_manager.config.Config`
是同一套接口（点操作、``on`` / ``value_changed``、``get('all')``）。

**它必须和声明类一起组成子类**，不能直接实例化：默认值与点操作都来自声明，
裸的 ``ConfigInChildProcessPipe`` 的 ``DEFAULTS`` 是空的、也没有任何点操作属性::

    # 主进程
    pipe = ConfigInMainProcessPipe(main_cfg)

    # 子进程
    class Child(ConfigInChildProcessPipe, AppKeys):   # AppKeys 是 ConfigKeysBase 子类
        ...

    cfg = Child(*pipe.get_queues())

（和 ``class AppConfig(Config, AppKeys)`` 的写法对称 —— 后端在前、声明在后。）
子进程里要开 Qt 窗口，把它交给 ``xiaoe_ui.config.bridge.ConfigInChildProcessPipeBridge``
就行。

通知是自动的，不需要手工接线：

* 本进程写 → 乐观写当场派发（``set`` 返回时值已生效）；
* 别的进程写 → 广播回来时派发被改的那个键；
* 自己写出去又广播回来的**回声** → 广播里带着 origin，认出来是自己发的就跳过，
  所以不会双发。

写入语义是乐观的（先改本地缓存、再发消息），``reset`` 是悲观的（只发消息，
本地缓存等广播回来才变）—— 这条不对称是刻意的：跨进程的写操作一律经主进程统一
处理。
"""

from __future__ import annotations

import copy
import itertools
import logging
import multiprocessing
import queue
import threading
import time
import traceback

from xiaoe_config_manager.config_base import ConfigBase
from xiaoe_config_manager.config_pipe_protocol import GETALL, ORIGIN, RESET, SET
from xiaoe_config_manager.config_types import ConfigDict, ConfigValue

__all__ = [
    "ConfigInMainProcessPipe",
    "ConfigInChildProcessPipe",
]

log = logging.getLogger(__name__)

#: 子进程启动时等"第一份完整配置"的秒数；超时说明主进程管道没起来，
#: 直接报错比永久阻塞好（永久阻塞的表现是"子进程再也起不来"，没有任何线索）。
INIT_TIMEOUT = 30.0

#: 主进程侧给每个子进程分配 ID 用的计数器。
#:
#: ``ConfigInMainProcessPipe`` 只会在主进程里被创建（它持有主进程的配置对象和
#: 两条队列），所以这个计数器天然只在一个进程内自增，不需要加锁也不会撞号。
_next_child_id = itertools.count(1)

#: 收消息线程连续读失败多少次就判定管道已死。
#:
#: 队列被关闭后每次 ``get`` 都会立刻抛，重试没有意义；但要给"瞬时故障"留余地，
#: 所以不是一次就放弃。
_MAX_READ_FAILURES = 3


class ConfigInMainProcessPipe:
    """主进程侧的管道口：每个子进程在主进程里对应一个实例。

    每个实例有一个进程内唯一的 ``child_id``（``"child-1"``、``"child-2"``……），
    子进程启动时会拿到它。之后子进程发来的写请求都带着这个 ID，主进程把它原样
    放进广播消息里带回去 —— 子进程据此认出"这是我自己的回声"。

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
        #: 这个管道口对应的子进程 ID（``"child-1"`` 这种）。
        #: 子进程启动时通过 ``GETALL`` 拿到它，自己发消息时带上。
        self.child_id = f"child-{next(_next_child_id)}"
        #: 收消息线程是否已经因为管道故障退出。
        #: 置上之后 ``set`` 会直接报错 —— 静默不同步比抛异常难查得多。
        self.dead = False
        self._closed = False
        #: 子进程 → 主进程。
        self.config_set_queue: multiprocessing.Queue = multiprocessing.Queue()
        #: 主进程 → 子进程。
        self.config_get_queue: multiprocessing.Queue = multiprocessing.Queue()
        # 注册队列：配置被修改时，通过这个队列向所有进程发送新配置
        self.config.queues.append((
            self.config_set_queue,
            self.config_get_queue,
        ))

        self._loop_thread = threading.Thread(target=self._loop, daemon=True)
        self._loop_thread.start()

    def get_queues(self):
        """把这两个队列对象传给子进程。

        ID 不走这里 —— 子进程构造时用 ``GETALL`` 问一次，主进程在同一条回复里
        把 ID 和整份配置一起给它。这样连接方式不用改。
        """
        return self.config_set_queue, self.config_get_queue

    def _loop(self):
        """收子进程消息的守护线程。

        任何一条消息出问题都不许把线程带走 —— 线程一死，之后所有子进程的写入
        都只会改各自的内存副本，主进程的文件再也不更新，而且没有任何一方收到错误。

        所以 ``get()`` 本身也在 ``try`` 里：队列被关闭、底层管道断了（子进程异常
        退出、句柄失效）都会从 ``get`` 抛出 ``ValueError`` / ``EOFError`` /
        ``OSError``。只包 ``_handle`` 是不够的 —— 那样第一条异常就把整个循环带走，
        而失败是静默的，调用方只会觉得"配置突然不同步了"。

        队列真的坏了时重试没有意义（每次都会立刻抛），所以连续失败到上限就
        打一条错误日志、把 :attr:`dead` 置上，然后退出。之后 ``set`` 会因此
        直接报错，而不是悄悄失效。
        """
        consecutive_failures = 0
        while True:
            try:
                msg = self.config_set_queue.get()
            except Exception:                        # noqa: BLE001
                if self._closed:
                    break
                consecutive_failures += 1
                log.exception("读取子进程的配置消息失败（第 %d 次）",
                              consecutive_failures)
                if consecutive_failures >= _MAX_READ_FAILURES:
                    self.dead = True
                    log.error("配置管道已不可用，停止监听：%r", self)
                    break
                continue
            consecutive_failures = 0
            if msg is None:
                break
            # 这一发写由哪个子进程发起：子进程自己填 origin，没填就当是本管道的。
            origin = msg.get(ORIGIN) or self.child_id
            self.config._origin.value = origin
            try:
                self._handle(msg)
            except Exception:                        # noqa: BLE001
                log.exception("处理子进程的配置消息失败，已跳过：%r", msg)
            finally:
                self.config._origin.value = None

    def _handle(self, msg: dict):
        """处理一条子进程消息。

        Args:
            msg: ``{'call': 动作名, 'args': [...], 'origin': ID}``；认不出来的动作
                只记一条 warning（不抛、也不回错误 —— 老版本子进程的协议可能对不上）。
        """
        call = msg.get("call")
        args = msg.get("args", [])
        if call == SET:
            self.config.set(*args)
        elif call == RESET:
            self.config.reset(*args)
        elif call == GETALL:
            # 子进程启动时要一份整份配置，顺便领自己的 ID。
            # 只回给发问的这个子进程，不能 broadcast_all —— 那会把整份配置推给
            # 所有已经就绪的子进程，让它们无谓地重派发一遍。
            with self.config.config_lock:
                # 深拷贝：Queue.put 是异步 pickle，构造期别人也可能在写
                snapshot = copy.deepcopy(self.config.config)
            self.config_get_queue.put({
                'call': GETALL,
                'args': [snapshot, self.child_id],
            })
        else:
            log.warning("收到无法识别的配置管道消息，已忽略：%r", msg)

    def close(self):
        """结束收消息线程（结束时必须调用）。"""
        self._closed = True
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

    **必须和声明类组成子类再用**，不要直接实例化它：键、默认值和点操作全部来自
    声明，裸 ``ConfigInChildProcessPipe`` 的 ``DEFAULTS`` 是空的、也没有点操作属性::

        class Child(ConfigInChildProcessPipe, AppKeys): ...
        cfg = Child(*pipe.get_queues())

    读一律读本地缓存（零跨进程开销），写是乐观的，``reset`` 是悲观的。
    生命周期结束时调 :meth:`close`。

    构造时会向主进程要一份完整配置，同一份回复里还带着主进程分配给自己的
    ``child_id``。之后每次写都把这个 ID 附在消息上，主进程原样放进广播带回来；
    收到广播时看到 origin 是自己，就知道那是回声，不再派发第二次。
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
        #: 主进程分配的 ID（``"child-1"`` 这种）。:meth:`_init_config` 里领到。
        self.child_id: str | None = None
        #: 收广播的线程是否已经因为管道故障退出。
        self.dead = False
        self._closed = False
        self._init_config()

        self._update_config_loop_thread = threading.Thread(
            target=self._update_config_loop, daemon=True)
        self._update_config_loop_thread.start()

    def _current_origin(self) -> str | None:
        """子进程发出的每一条写都是"自己"发起的，所以 origin 恒为本进程 ID。

        覆写基类实现：基类读的是"收消息的线程"标记的那个值，子进程没有那个线程，
        它的写永远来自自己的用户代码。
        """
        return self.child_id

    # ══════════════════════════════════════════════════════════
    # 存储原语
    # ══════════════════════════════════════════════════════════

    def _read(self, key: str) -> ConfigValue:
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

        ``self.config`` 是 copy-on-write 的：写入换新 dict、广播换新 dict，
        已经发布出去的旧 dict 不会再被改。所以这里不需要持锁。

        与文件版的差别只在新鲜度：文件版会重读磁盘（拿到的一定是最新的），
        这里给的是**最近一次广播**的快照，可能比主进程晚一发；自己刚 ``set``
        的值一定在（写是乐观的）。要严格最新就回主进程读。
        """
        return copy.deepcopy(self.config)

    def _write(self, key: str, value: ConfigValue) -> None:
        """乐观写：先改本地缓存（于是 ``set`` 返回时值已生效），再发消息给主进程。

        缓存里存的是 ``value`` 的**深拷贝**：调用方之后改自己那个对象，缓存不受影响。

        用 copy-on-write（换引用而不是原地改），理由同 :meth:`Config._write`：
        本地缓存会被别的线程读到，换引用能保证读到的一致。

        消息里的值也是深拷贝：``Queue.put`` 立即返回，真正 pickle 在 feeder 线程，
        调用方 ``set`` 返回后立刻改原对象的话，主进程会收到改过的内容。

        Args:
            key: 配置键名。
            value: 配置值。
        """
        copied = copy.deepcopy(value)
        new = dict(self.config)
        new[key] = copied
        self.config = new
        self.config_set_queue.put({
            'call': SET,
            'args': [key, copied],
            ORIGIN: self.child_id,
        })

    def _apply_reset(self, key: str) -> None:
        """悲观重置：只发消息，本地缓存要等主进程把新值带回来才变。

        Args:
            key: 配置键名，或 ``'all'``。
        """
        self.config_set_queue.put({
            'call': RESET,
            'args': [key],
            ORIGIN: self.child_id,
        })

    def _dispatch_on_reset(self) -> bool:
        """子进程**不在** ``reset`` 返回前当场派发。

        此时本地缓存还是旧值（:meth:`_apply_reset` 只发了消息），派发出去的是
        错的。正确的新值要等主进程广播回来，由 :meth:`_handle_remote` 派发一次。
        这样三个后端的 ``reset`` 都是"一次重置一次通知"。
        """
        return False

    def _save(self) -> None:
        """子进程不写文件（落盘在主进程）。"""

    def _flush_locked(self) -> None:
        """子进程不写文件（落盘在主进程）。"""

    # ══════════════════════════════════════════════════════════
    # 同步
    # ══════════════════════════════════════════════════════════

    def _init_config(self):
        """向主进程要一份完整配置，并等它回来；同一条回复里还领到自己的 ID。

        等的时候可能先收到几条 ``SET`` / ``RESET``（别的进程恰好在写），
        先按顺序落到本地缓存，再等 ``GETALL`` 那份整份配置盖上来 ——
        整份里已经包含前面那些键的最新值，所以先应用一遍只是为了让"没收到
        ``GETALL`` 之前也不至于丢消息"，顺序不会错。

        这时候还没有监听器（构造还没返回），所以不派发。
        """
        try:
            self.config_set_queue.put({'call': GETALL})
        except Exception as exc:                     # noqa: BLE001
            raise RuntimeError(
                "子进程配置管道不可用：发不出第一条同步请求。"
                "通常是队列对象已经关闭，或者传进来的不是 "
                "ConfigInMainProcessPipe.get_queues() 的返回值。"
            ) from exc
        deadline = time.monotonic() + INIT_TIMEOUT
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(
                    f"等主进程的配置广播超时（{INIT_TIMEOUT:g}s）—— 主进程的 "
                    f"ConfigInMainProcessPipe 还没起来，或者管道对象传错了。"
                )
            try:
                msg = self.config_get_queue.get(timeout=remaining)
            except queue.Empty:
                continue
            except Exception as exc:                 # noqa: BLE001
                raise RuntimeError(
                    "子进程配置管道不可用：读不到主进程的初始配置。"
                ) from exc
            if msg is None:
                raise RuntimeError("主进程的配置管道已关闭，子进程拿不到初始配置。")
            call = msg.get("call")
            args = msg.get("args", [])
            if call == GETALL:
                self.config = args[0]
                # 主进程在同一份回复里带上分配好的 ID（老版本没有这个字段，留空）
                self.child_id = args[1] if len(args) > 1 else None
                return
            self._handle_remote(msg)

    def _update_config_loop(self):
        """收主进程广播 → 更新本地缓存 → 派发通知。

        消息只有三种（见 :mod:`config_pipe_protocol`）：

        * ``SET``：某个键被写了。更新本地缓存，然后派发这一个键。
        * ``RESET``：某个键被重置。更新本地缓存（用消息里带来的值），
          然后派发这一个键。
        * ``GETALL``：整份配置。只在 ``reset('all')`` 和启动同步时出现，
          整份替换后逐键派发。

        主进程发什么键，子进程就派发什么键，不需要拿两份配置反推变了什么。

        ``get()`` 包在 ``try`` 里，理由同 ``ConfigInMainProcessPipe._loop``：
        主进程退出、管道断开会从 ``get`` 抛 ``ValueError`` / ``EOFError`` /
        ``OSError``，不接住的话这个守护线程会静默死掉，之后子进程再也收不到
        任何更新，而调用方完全不知道。
        """
        consecutive_failures = 0
        while True:
            try:
                msg = self.config_get_queue.get()
            except Exception:                        # noqa: BLE001
                if self._closed:
                    break
                consecutive_failures += 1
                log.exception("读取主进程的配置广播失败（第 %d 次）",
                              consecutive_failures)
                if consecutive_failures >= _MAX_READ_FAILURES:
                    self.dead = True
                    log.error("配置管道已不可用，停止同步：%r", self)
                    break
                continue
            consecutive_failures = 0
            if msg is None:
                break
            self._handle_remote(msg)

    def _handle_remote(self, msg: dict) -> None:
        """应用一条主进程发来的广播。

        回声只对 **``SET``** 跳过派发。``RESET`` / ``GETALL`` 不管是不是自己的
        回声都要派发 —— 因为这两条路径在子进程侧是悲观的：

        * ``SET`` 是乐观写：发消息前本地缓存已经改成新值了，监听器当时就收到过
          一次通知。回声回来时值和缓存都一样，再派发就是重复。
        * ``RESET`` 是悲观重置：发消息时只入队、不动缓存，所以 ``reset`` 返回前
          不会派发（见 ``ConfigInChildProcessPipe._dispatch_on_reset``）。缓存要
          到这条回声回来才变成新值，"新值到了"这个通知只有这里能发。

        跳过 ``SET`` 回声用的是 ``origin`` 而不是"值有没有变"：后者会把"别的进程
        恰好写了同一个值"也误判成回声，让监听器漏掉别人的变更。

        Args:
            msg: 主进程发来的消息。
        """
        call = msg.get("call")
        args = msg.get("args", [])
        echo = self.child_id is not None and msg.get(ORIGIN) == self.child_id

        if call == GETALL:
            # 整份：可能是 reset('all') 的广播，也可能只是启动同步。
            # 两种情况都要让缓存变成这份内容；派发与否只看有没有监听器，
            # 不看 origin —— reset('all') 同样是悲观路径。
            self._replace_all(args[0], dispatch=True)
        elif call == SET:
            self._apply_remote_set(args[0], args[1], dispatch=not echo)
        elif call == RESET:
            # 悲观路径：回声正是"新值终于到了"的那一刻，必须派发。
            self._apply_remote_set(args[0], args[1], dispatch=True)
        else:
            log.warning("收到无法识别的配置广播，已忽略：%r", msg)

    def _apply_remote_set(self, key: str, value: ConfigValue,
                          dispatch: bool = True) -> None:
        """把一个键的远程变更落到本地缓存，需要时派发一次。

        不是回声时无条件派发 —— 和 ``Config`` / ``ConfigMemory`` 的"一次写一次
        派发"对齐，不再依赖"值有没有变"。

        Args:
            key: 变了的键。
            value: 主进程发来的新值。
            dispatch: 是否派发通知（``False`` 表示这是 ``SET`` 自己的回声）。
        """
        with self.config_lock:
            new = dict(self.config)
            new[key] = copy.deepcopy(value)
            self.config = new
        if dispatch:
            self._dispatch(key, copy.deepcopy(value))

    def _replace_all(self, config: dict, dispatch: bool = True) -> None:
        """整份替换本地缓存，按需派发一次 ``key='all'`` 的通知。

        ``reset('all')`` 之后键集合和每个键的值都可能变，没有比"整份"更小的
        消息可发。派发的形式要和 ``Config`` / ``ConfigMemory`` 对齐 —— 它们
        走 ``ConfigBase.reset('all')``，派发的是 ``('all', 整份 dict)`` 一条，
        而不是逐键发 N 条。

        Args:
            config: 主进程发来的整份配置。
            dispatch: 是否派发。启动同步时为 ``False``（那时构造函数还没返回，
                用户还没机会注册监听器）。
        """
        with self.config_lock:
            self.config = config
        if dispatch:
            self._dispatch("all", copy.deepcopy(config))

    def close(self):
        """结束收广播的线程（结束时必须调用）。"""
        self._closed = True
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
