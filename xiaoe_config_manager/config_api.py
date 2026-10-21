"""配置接口层 —— 本包对外的标准接口。

三个约定：

1. 标准三件套是 ``get`` / ``set`` / ``reset`` —— 子类只需要实现这三个。
2. 老名字 ``configget`` / ``configset`` / ``configreset`` 保留可用，但方向是单向的：
   它们是本模块里写一次的转发壳，转给 ``get`` / ``set`` / ``reset``。
   覆写点只有新名字那三个，不要去覆写老名字。
3. 订阅也是接口成员：``on(key, cb)`` / ``off(key, cb)`` /
   ``value_changed(cb)`` / ``off_value_changed(cb)``。
   ``value_changed(cb)`` 订阅的是所有键，回调签名 ``(key, value)``；
   ``on`` 按单个键订阅，回调签名 ``(value)``。两对都是"谁注册谁注销"。

线程语义（所有实现共同承诺）：

* ``set`` / ``reset`` 返回时值已生效 —— 与"监听器跑没跑完"无关；
* 回调在哪个线程跑，由实现决定（``ConfigBase`` 系列是调用方线程；Qt 桥会把
  回调排队回桥所在线程，见 ``xiaoe_ui.config.bridge``）；
* 派发是隔离的：单个回调抛异常只打一份堆栈，不影响同一轮里其它回调，也不会让
  ``set`` / ``reset`` 的调用方拿到异常。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Literal, overload

from xiaoe_config_manager.config_types import ConfigDict, ConfigValue

__all__ = ["ConfigApi"]


class ConfigApi(ABC):
    """配置对象的统一接口。

    ``get`` / ``set`` / ``reset`` / ``on`` / ``off`` / ``value_changed`` 是抽象成员，
    由具体实现提供；``configget`` / ``configset`` / ``configreset`` 是本层提供的兼容壳。

    和 Python 的常见风格一致：``get('all')`` 返回整份配置的 ``dict``。三个内置实现
    都如此，差别只在数据来源与新鲜度 —— 文件版重读磁盘、内存版返回内存快照、
    子进程管道返回最近一次广播的快照（见各自的 docstring）。

    值一律是 :data:`~xiaoe_config_manager.config_types.ConfigValue`：标量、``list``、
    ``dict``、``None`` 及其嵌套组合。要精确到"这个键是 ``int``"请用点键访问
    （``cfg.timeout.get()`` 的返回类型由 ``default(30)`` 推断），本接口是类型擦除的。
    """

    # ══════════════════════════════════════════════════════════
    # 标准三件套（子类实现）
    # ══════════════════════════════════════════════════════════

    @overload
    def get(self, key: Literal["all"]) -> ConfigDict: ...

    @overload
    def get(self, key: str) -> ConfigValue: ...

    @abstractmethod
    def get(self, key: str) -> ConfigValue | ConfigDict:
        """读一个键；``key='all'`` 时返回整份配置。

        两个 overload 是为了让 ``cfg.get("all")["键"]`` 能过类型检查：返回值的
        联合类型里虽然含 ``dict``，但类型检查器不会替你从联合里挑出它 ——
        它要求联合的每个成员都支持 ``str`` 下标。传字面量 ``"all"`` 时命中第一个
        重载拿到 ``dict``，其它键命中第二个拿到 ``ConfigValue``。

        Args:
            key: 配置键名，或 ``'all'``。

        Returns:
            该键的值；``'all'`` 时是整份配置 ``dict``。

        Raises:
            KeyError: 键不存在（不静默返回 None —— 见 README「静默返回」一节）。
        """
        raise NotImplementedError

    @abstractmethod
    def set(self, key: str, value: ConfigValue) -> None:
        """写一个键（落盘 / 广播 / 派发通知都由实现负责）。

        返回时值已经生效。

        Args:
            key: 配置键名。
            value: 配置值。
        """
        raise NotImplementedError

    @abstractmethod
    def reset(self, key: str) -> None:
        """把一个键恢复成默认值；``key='all'`` 时重置全部。

        Args:
            key: 配置键名，或 ``'all'``。
        """
        raise NotImplementedError

    # ══════════════════════════════════════════════════════════
    # 订阅（子类实现）
    # ══════════════════════════════════════════════════════════

    @abstractmethod
    def on(self, key: str, callback: Callable[[ConfigValue], None]) -> None:
        """订阅单个键的变化。

        Args:
            key: 配置键名。
            callback: ``(new_value) -> None``。
        """
        raise NotImplementedError

    @abstractmethod
    def off(self, key: str, callback: Callable[[ConfigValue], None]) -> None:
        """取消 :meth:`on` 注册的回调（必须是同一个函数引用）。

        Args:
            key: 配置键名。
            callback: 之前注册的函数引用。

        Raises:
            ValueError: 键在，但回调不在它的列表里（键本身没出现过则静默返回）。
        """
        raise NotImplementedError

    @abstractmethod
    def value_changed(self, callback: Callable[[str, ConfigValue], None]) -> None:
        """订阅所有键的变化。

        桥（``xiaoe_ui``）把这个名字实现成 Qt 信号，所以那边是
        ``cfg.value_changed.connect(slot)``；纯 Python 侧是本方法，
        取消订阅用 :meth:`off_value_changed`（桥侧是 ``.disconnect(slot)``）。

        Args:
            callback: ``(key, new_value) -> None``。
        """
        raise NotImplementedError

    @abstractmethod
    def off_value_changed(self, callback: Callable[[str, ConfigValue], None]) -> None:
        """取消 :meth:`value_changed` 注册的回调（必须是同一个函数引用）。

        Args:
            callback: 之前注册的函数引用。

        Raises:
            ValueError: 回调不在订阅列表里（与 :meth:`off` 的取向一致：
                注销一个没注册过的回调属非预期行为，不静默吞掉）。
        """
        raise NotImplementedError

    # ══════════════════════════════════════════════════════════
    # 老名字：兼容转发（不覆写，全部转给上面三个）
    # ══════════════════════════════════════════════════════════

    @overload
    def configget(self, key: Literal["all"]) -> ConfigDict: ...

    @overload
    def configget(self, key: str) -> ConfigValue: ...

    def configget(self, key: str) -> ConfigValue | ConfigDict:
        """``get`` 的老名字。

        Args:
            key: 配置键名，或 ``'all'``（语义与 :meth:`get` 完全一致）。
        """
        return self.get(key)

    def configset(self, key: str, value: ConfigValue) -> None:
        """``set`` 的老名字。

        Args:
            key: 配置键名。
            value: 配置值。
        """
        return self.set(key, value)

    def configreset(self, key: str) -> None:
        """``reset`` 的老名字。

        Args:
            key: 配置键名，或 ``'all'``。
        """
        return self.reset(key)
