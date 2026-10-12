"""配置对象的行为层 —— 加锁、默认值、订阅、广播，以及唯一派发点。

文件版（:class:`~xiaoe_config_manager.config.Config`）、内存版
（:class:`~xiaoe_config_manager.config_memory.ConfigMemory`）、子进程管道
（``ConfigInChildProcessPipe``）都继承 :class:`ConfigBase`，只实现几个存储原语：

    _read        读单个键（缺键必须抛 KeyError）
    _read_all    读整份
    _write       写一个键（只改存储，调用方已持锁）
    _apply_reset 按键回默认值（调用方已持锁）
    _save        持久化（内存版是空实现；调用方已持锁）

其余全在这一层，所以"每次写完都要派发一次"这条纪律只有一处实现：

    set(key, value)  → 加锁 → _write() → _save() → 广播 → 解锁 → _dispatch()
    reset(key)       → 加锁 → 重算默认值 → _apply_reset() → _save() → 广播 → 读回 → 解锁 → _dispatch()

:meth:`ConfigBase._dispatch` 是**唯一的派发点** —— 谁要接管通知（比如 Qt 桥），
重写它就行，不要另外找地方发通知。
"""

from __future__ import annotations

import copy
import sys
import threading
import traceback
from typing import Any, Callable

from xiaoe_config_manager.config_api import ConfigApi
from xiaoe_config_manager.config_dot import ConfigDeclareMixin, ConfigKeysBase

__all__ = ["ConfigBase"]


class ConfigBase(ConfigDeclareMixin, ConfigApi):
    """配置对象的行为层。

    模板方法把「改值」和「通知」钉在一起::

        set(key, value)  → 加锁 → 子类的 _write() → 落盘/广播 → 解锁 → _dispatch()
        reset(key)       → 加锁 → 重算默认值 → 子类的 _apply_reset() → 落盘/广播 → 读回 → 解锁 → _dispatch()

    ``_dispatch`` 是唯一的派发点 —— 谁要接管通知（比如 Qt 桥），重写它就行，
    不要另外找地方发通知。

    线程语义：``set`` / ``reset`` 返回时值已经生效，与监听器跑没跑完无关。
    """

    def __init__(
            self,
            default_config: dict | None = None,
            default_config_callback: Callable | None = None,
    ):
        """行为层初始化（子类的 ``__init__`` 记得调它）。

        Args:
            default_config: 静态默认值（reset 的目标）。
            default_config_callback: 动态默认值回调，参数是当前配置；
                ``reset`` 时总会调用它。
        """
        #: 向子进程广播用的队列注册表：``[(set_queue, get_queue), ...]``
        self.queues: list = []
        #: 单进程内保单例，多线程用锁即可
        self.config_lock = threading.Lock()
        #: 默认值（reset 的目标）。深拷贝：类声明 / 调用方传进来的对象不与本实例共享
        self.default_config: dict = copy.deepcopy(default_config or {})
        #: 动态默认值回调（优先于上面的静态默认值）
        self.default_config_callback: Callable | None = default_config_callback
        #: 当前值
        self.config: dict = {}

        self._listeners: dict[str, list[Callable]] = {}
        self._value_listeners: list[Callable] = []

    # ══════════════════════════════════════════════════════════
    # 存储原语（子类实现）
    # ══════════════════════════════════════════════════════════

    def _read(self, key: str) -> Any:
        """读单个键（子类实现）。

        Args:
            key: 配置键名。

        Raises:
            KeyError: 键不存在 —— 缺键必须报错，不要静默返回 None。
        """
        raise NotImplementedError

    def _read_all(self) -> Any:
        """读整份配置（子类实现）。"""
        raise NotImplementedError

    def _read_all_locked(self) -> Any:
        """读整份配置调用方已持 config_lock。与锁无关则直接路由_read_all。"""
        return self._read_all()

    def _write(self, key: str, value: Any) -> None:
        """写一个键（子类实现）。只改存储，不负责派发；调用方已持锁。

        Args:
            key: 配置键名。
            value: 配置值。
        """
        raise NotImplementedError

    def _apply_reset(self, key: str) -> None:
        """把一个键（或 ``'all'``）改回 ``self.default_config``（子类实现）。

        Args:
            key: 配置键名，或 ``'all'``。调用方已持锁。
        """
        raise NotImplementedError

    def _save(self) -> None:
        """延迟持久化（子类实现）。内存版是空实现；调用方已持锁。"""
        raise NotImplementedError

    def _flush_locked(self) -> None:
        """持久化（子类实现）。内存版是空实现；调用方已持锁。"""
        raise NotImplementedError

    # ══════════════════════════════════════════════════════════
    # 标准三件套
    # ══════════════════════════════════════════════════════════

    def get(self, key: str) -> Any:
        """读配置。

        返回值是**深拷贝**：改它（哪怕改里面的嵌套 list / dict）不会动到配置里那份。

        Args:
            key: 配置键；``'all'`` 时返回整份配置。

        Raises:
            KeyError: 键不存在。
        """
        if key == "all":
            return self._read_all()
        return self._read(key)

    def set(self, key: str, value: Any) -> None:
        """写配置 → 落盘/广播 → 派发一次通知。

        存进去的是 ``value`` 的**深拷贝**：调用方之后改自己那个对象，配置不受影响。

        Args:
            key: 配置键名。``'all'`` 是保留键名（只给 ``get('all')`` / ``reset('all')``
                用），写它没有任何意义，所以这里直接报错。
            value: 配置值。

        Raises:
            TypeError: ``key == 'all'`` —— 它是"整份配置"的特殊键名，不指向任何一个
                配置项。要一次改多个键就逐个 ``set``。
        """
        if key == "all":
            raise TypeError(
                "'all' 是保留键名：get('all') 读整份配置、reset('all') 重置整份，"
                "它不对应任何单个配置项，不能用来写。要改多个键请逐个 set(key, value)。"
            )
        with self.config_lock:
            self._write(key, value)
            self._save()
            self.update_config()
        self._dispatch(key, value)

    def reset(self, key: str) -> None:
        """把配置恢复成默认值 → 落盘/广播 → 派发一次通知。

        Args:
            key: 配置键名，或 ``'all'``（重置全部）。

        注意：子进程管道（``ConfigInChildProcessPipe``）的 reset 是异步的 ——
        它只发消息，本地缓存要等主进程广播回来才变，所以这里派发的可能是旧值。
        这是设计（跨进程写一律经主进程统一处理），不是 bug。
        """
        with self.config_lock:
            if self.default_config_callback:
                # 回调返回的 dict 由本实例接管，深拷贝一份存着
                self.default_config = copy.deepcopy(self.default_config_callback(
                    None if key == "all" else self.config
                ))
            self._apply_reset(key)
            self._flush_locked()
            self.update_config()
            new_value = self._read_all_locked() if key == "all" else self._read(key)
        self._dispatch(key, new_value)

    def update_config(self):
        """把当前配置推给所有注册过的子进程队列（没有队列就是空操作）。"""
        for _, get_queue in self.queues:
            get_queue.put(self.config)

    def configupdate_config(self, key: str, last_value: Any = None):
        """更新默认值：用户值还停在旧默认值上时，跟着换成新默认值。

        Args:
            key: 要更新的配置项。
            last_value: 旧的默认值。

        Raises:
            KeyError: 配置里没有 ``<key>_reseted`` 标记 —— 这是硬前提，
                缺了就是没按规矩预置（见 README）。
        """
        if not self.get(f"{key}_reseted"):
            if last_value is None or self.get(key) == last_value:
                self.reset(key)
            self.set(f"{key}_reseted", True)

    # ══════════════════════════════════════════════════════════
    # 订阅 + 派发
    # ══════════════════════════════════════════════════════════

    def on(self, key: str, callback: Callable[[Any], None]) -> None:
        """订阅单个键的变化，``callback(value)``。

        回调是普通 Python 引用：不随接收者销毁自动断开。长生命周期配置上注册的
        短命对象要自己 :meth:`off`，或者改用 :meth:`value_changed`。

        Args:
            key: 配置键名。
            callback: ``(new_value) -> None``。
        """
        self._listeners.setdefault(key, []).append(callback)

    def off(self, key: str, callback: Callable[[Any], None]) -> None:
        """取消 :meth:`on` 注册的回调（必须是同一个函数引用）。

        Args:
            key: 配置键名。
            callback: 之前注册的函数引用。

        Raises:
            ValueError: 键在、但回调不在它的列表里。键本身没出现过则静默返回
                （这一条是历史行为，改它会砸掉调用方的收尾逻辑）。
        """
        if key in self._listeners:
            self._listeners[key].remove(callback)

    def value_changed(self, callback: Callable[[str, Any], None]) -> None:
        """订阅所有键的变化，``callback(key, value)``。

        Args:
            callback: ``(key, new_value) -> None``。

        桥（``xiaoe_ui``）把同一个名字实现成 Qt 信号：那边是
        ``cfg.value_changed.connect(slot)``，这边是方法调用；取消订阅这边用
        :meth:`off_value_changed`，桥侧用 ``.disconnect(slot)``。
        """
        self._value_listeners.append(callback)

    def off_value_changed(self, callback: Callable[[str, Any], None]) -> None:
        """取消 :meth:`value_changed` 注册的回调（必须是同一个函数引用）。

        Args:
            callback: 之前注册的函数引用。

        Raises:
            ValueError: 回调不在订阅列表里（与 :meth:`off` 的取向一致：
                注销一个没注册过的回调属非预期行为，不静默吞掉）。
        """
        self._value_listeners.remove(callback)

    @classmethod
    def memory(cls, defaults: dict | None = None) -> "ConfigBase":
        """便捷路径：不写类，直接照当前类造一份内存版（``Config.memory({...})``）。

        **标准做法是定义类**（和文件版一样）::

            class AppMemory(ConfigMemory, AppKeys): ...
            mem = AppMemory()

        这条便捷路径存在的意义：临时配置、老代码兼容、以及 ``AppConfig.memory()``
        这种"照本类的声明再造一份内存版"的用法 —— 它内部就是按 ``cls.DEFAULTS``
        合成一个临时声明类，所以点操作、订阅、``get('all')`` 一样都不少。

        Args:
            defaults: 额外默认值，盖在同名声明值上面 —— 最终默认值是
                ``{**cls.DEFAULTS, **defaults}``，同时也是 reset 的目标。

        Returns:
            :class:`~xiaoe_config_manager.config_memory.ConfigMemory` 实例
            （有声明键时是它的一个子类，好把点操作也带上）。
        """
        from xiaoe_config_manager.config_memory import ConfigMemory

        data = {**(getattr(cls, "DEFAULTS", None) or {}), **(defaults or {})}
        if not getattr(cls, "DEFAULTS", None):
            # 没有声明键 → 不用合成类，直接给内存后端
            return ConfigMemory(data)

        # 有声明键：把键合成一个临时声明类挂上去，这样 cfg.键名 的点操作也在
        keys_cls = type(f"_{cls.__name__}MemoryKeys", (ConfigKeysBase,), dict(data))
        memory_cls = type(f"{cls.__name__}Memory", (ConfigMemory, keys_cls), {})
        return memory_cls(data)

    def _dispatch(self, key: str, value: Any) -> None:
        """唯一派发点：把一次变更发给所有订阅者。

        Args:
            key: 变了的配置键。
            value: 新值（事件发生那一刻的快照）。

        两条纪律：

        * 遍历的是快照 —— 回调里再注册的监听器不会在当轮被调用（与 Qt 信号一致）；
        * **逐个隔离**：某个回调抛异常只打一份堆栈（见
          :meth:`_report_listener_error`），其余回调照常跑，也不会冒给
          ``set`` / ``reset`` 的调用方 —— 一个订阅出问题不该把整轮通知带走。
        """
        for callback in tuple(self._listeners.get(key, ())):
            try:
                callback(value)
            except Exception:                    # noqa: BLE001
                self._report_listener_error(key, callback)
        for callback in tuple(self._value_listeners):
            try:
                callback(key, value)
            except Exception:                    # noqa: BLE001
                self._report_listener_error(key, callback)

    def _report_listener_error(self, key: str, callback: Callable) -> None:
        """回调抛异常时的出口：打一份堆栈，然后继续跑别的回调。

        两点要知道：

        * 这是 ``traceback.print_exc()`` 直接打，**框架的异常钩子收不到它** ——
          ``sys.excepthook`` / ``threading.excepthook`` 只接"没人接的异常"，
          而这里已经被吃掉了。想让发行版也看得见（``console=False`` 时 stderr
          是 None），要么重写本方法把它接到自己的错误上报里（Qt 桥可以这么做），
          要么在应用侧接管 stderr。
        * ``sys.stderr is None`` 时先返回：Python 3.11+ 的 ``print_exc`` 遇到
          None 会安静地什么都不做，但 3.10 会抛 ``AttributeError`` —— 那会把
          "隔离"变成"整个派发炸掉"。

        Args:
            key: 出问题的配置键。
            callback: 抛异常的那个回调（只用来打出它的名字）。
        """
        if sys.stderr is None:
            return
        name = getattr(callback, "__qualname__", None) or repr(callback)
        print(f"配置回调抛异常（已隔离，其余回调照常）：键={key!r} 回调={name}",
              file=sys.stderr)
        traceback.print_exc()
