"""声明式配置 —— 键名与默认值写在类里，实例上用点操作。

三样东西，各管一段：

* :class:`ConfigKeysBase` —— 纯声明基类。子类只放「键名 = 默认值」，
  算出 ``DEFAULTS`` 供别处消费（后端、子进程、纯 Python 一侧都读同一份）。
* :class:`ConfigDeclareMixin` —— 在纯声明之上，把每个键做成实例上的 property，
  ``cfg.speed`` 返回 :class:`ConfigItemProxy`。:class:`ConfigBase` 继承本类。
* :class:`ConfigItemProxy` —— 点操作代理。它只认 owner 的
  ``get`` / ``set`` / ``reset`` / ``on`` / ``off``，所以点操作和直接调配置对象
  走的是同一条路（派发、信号、跨线程投递全都一致）。

声明来源只有一处，规则是明确的：

1. 键只认 :class:`ConfigKeysBase` 的子类（以及实现类自己的类体）；
   后端类（``Config`` / ``ConfigMemory`` / 管道）的类字典一律不扫。
2. 默认值必须是 ``str`` / ``int`` / ``float`` / ``bool`` / ``list`` / ``dict`` /
   ``None`` 之一（见 :data:`~xiaoe_config_manager.config_types.DATA_TYPES`）。
   其它东西一律在类创建时 :class:`TypeError` —— 判据是"是不是配置值"，
   不是"猜猜作者想干嘛"。类体里的方法、嵌套类、模块，以及下划线开头的名字，
   属于"本来就不是配置项"，直接跳过，不算违规。
3. 键名不许撞 :data:`RESERVED_KEYS`，也不许撞实现类上已有的任何属性
   （动态判定）—— 命中直接 :class:`TypeError`，不静默。
4. 一条继承链上不准出现同名键（``class Child(AppKeys)`` 里再写一遍 ``app_name``）；
   兄弟基类同名按 Python 的 MRO 走（左边的赢）。

用法::

    from xiaoe_config_manager import Config, ConfigKeysBase, default

    class AppKeys(ConfigKeysBase):
        app_name = default("myapp")
        timeout  = default(30)

    class AppConfig(Config, AppKeys):
        ...

    cfg = AppConfig("config_files/app")
    cfg.app_name.get()        # 'myapp'
    cfg.timeout.set(60)       # 走 AppConfig.set → 落盘 + 派发通知
"""

from __future__ import annotations

import types
from typing import Any, Callable, Generic, TypeVar, overload

from xiaoe_config_manager.config_types import DATA_TYPES, ConfigValue

__all__ = [
    "RESERVED_KEYS",
    "ConfigKeysBase",
    "ConfigDeclareMixin",
    "ConfigItemProxy",
    "collect_defaults",
    "default",
]

T = TypeVar("T")
T2 = TypeVar("T2")

#: 不许当配置键的名字。
#:
#: 这里只列动态判定看不到的那些 —— 也就是实现类在 ``__init__`` 里赋的实例属性
#: （类字典里没有它们），以及几个语义特殊的名字。方法是动态判定的，不用抄进来。
RESERVED_KEYS = frozenset({
    "DEFAULTS",
    # 声明层 / 代理层自己的
    "item",
    "keys",
    "instance",
    "memory",
    "persist",
    # 后端实现类的实例属性（ConfigBase / Config 的 __init__ 里赋的）
    "config",
    "fname",
    "queues",
    "config_lock",
    "default_config",
    "default_config_callback",
    # 子进程管道自己的实例属性
    "config_set_queue",
    "config_get_queue",
    "child_id",
    # 订阅接口名（manager 侧是方法，桥侧是 Qt 信号）
    "value_changed",
    # get / set / reset 把它当特殊键名：get('all') 读整份、reset('all') 重置整份、
    # set('all', ...) 直接报错。声明它就等于声明一个永远读不到的键（cfg.all.get()
    # 拿到的是整份配置），所以不允许。
    "all",
})


@overload
def default(value: T) -> "ConfigItemProxy[T]": ...


@overload
def default(value: None, type_: type[T2]) -> "ConfigItemProxy[T2 | None]": ...


def default(value: Any = None, type_: Any = None) -> Any:
    """声明一个配置项的默认值。

    运行时就是返回原值 —— 它只为两件事存在：给 IDE 提供类型
    （``default(30)`` 推断成 ``ConfigItemProxy[int]``、``default(None, list)``
    推断成 ``ConfigItemProxy[list | None]``），以及让声明读起来有语义。

    ::

        class AppKeys(ConfigKeysBase):
            timeout = default(30)            # -> ConfigItemProxy[int]
            id_list = default(None, list)    # -> ConfigItemProxy[list | None]

    Args:
        value: 默认值本身（运行时原样返回）。
        type_: 只在 ``value is None`` 时用来给 IDE 标类型，运行时不用。

    Returns:
        传入的 ``value``。
    """
    return value


# ══════════════════════════════════════════════════════════════
# 扫描
# ══════════════════════════════════════════════════════════════

def _is_not_a_config_item(value: Any) -> bool:
    """判断类体里某个属性是不是"本来就不是配置项"的东西。

    这一类不需要报错，直接跳过：

    * 方法 / 函数（``def helper(self)``、``staticmethod``、``classmethod``）；
    * 嵌套类（``class Inner``）；
    * 模块（``import os`` 那种）；
    * 描述符（``property`` 已在调用处单独处理）。

    除此之外、又不是 :data:`DATA_TYPES` 的东西，就是作者真的写错了一个默认值，
    该报错（见 :func:`_check_value_type`）。
    """
    return (
        callable(value)
        or isinstance(value, (type, types.ModuleType))
    )


def _check_value_type(cls: type, attr: str, value: Any) -> None:
    """默认值不在 :data:`DATA_TYPES` 里就报错。

    Args:
        cls: 声明所在类（只用来拼报错信息）。
        attr: 属性名。
        value: 被声明的值。

    Raises:
        TypeError: 值的类型不是配置值。
    """
    raise TypeError(
        f"{cls.__name__}.{attr} 不能当配置项的默认值："
        f"它是 {type(value).__name__}，而默认值必须是 "
        f"str / int / float / bool / list / dict / None 之一。"
        f"（不想让它当配置项的话，名字以下划线开头即可。）"
    )


def _declared_in(cls: type) -> dict:
    """扫出 ``cls`` 自己类体里声明的键（不含继承来的）。

    类体里"本来就不是配置项"的东西（方法、嵌套类、模块）跳过；
    其余不是配置值的一律 :class:`TypeError`，不静默忽略。

    Args:
        cls: 要扫描的类。

    Returns:
        ``{键名: 默认值}``。

    Raises:
        TypeError: 某个属性既不是配置值，也不是方法/嵌套类/模块。
    """
    out: dict = {}
    for attr, value in list(vars(cls).items()):
        if attr.startswith("_") or attr == "DEFAULTS":
            continue
        if isinstance(value, (property, staticmethod, classmethod)):
            continue
        if _is_not_a_config_item(value):
            continue
        if not isinstance(value, DATA_TYPES):
            _check_value_type(cls, attr, value)
        out[attr] = value
    return out


def _check_inheritance_conflict(cls: type, own: dict) -> None:
    """拦「一条继承链上出现同名键」。

    只拦 :class:`ConfigKeysBase` 这条线里的重名（``class Child(AppKeys)`` 又写了一遍
    ``app_name``）—— 这正是「到底哪份默认值生效」讲不清的来源。

    兄弟基类同名不拦（保持 Python 的 MRO 行为：左边赢）。

    Args:
        cls: 要检查的类。
        own: :func:`_declared_in` 算出来的「自己类体里声明的键」。

    Raises:
        TypeError: 继承链上出现同名键。
    """
    inherited: dict = {}
    for base in cls.__mro__[1:]:
        if not isinstance(base, type) or not issubclass(base, ConfigKeysBase):
            continue
        for name in getattr(base, "_own_declared", None) or {}:
            inherited.setdefault(name, base)

    dup = sorted(set(own) & set(inherited))
    if not dup:
        return
    detail = "、".join(f"{name}（已在 {inherited[name].__name__} 里声明）" for name in dup)
    raise TypeError(
        f"{cls.__name__} 重复声明了继承链上已有的配置键：{detail}。"
        f"同一个键只能在一处声明 —— 要改默认值请改父类那一行，或者换个键名。"
    )


def _check_reserved(cls: type, keys: dict) -> None:
    """拦「键名砸掉框架自己的属性」：先查显式清单，再动态查实现类。

    动态部分的判据是「这个名字在 MRO 上有没有被赋过值」，但要跳过**纯声明类** ——
    那些类的类体里本来就只有 ``键 = 默认值``，是配置数据的来源，不算"撞"。

    跳过条件必须收窄到「纯声明」：``ConfigDeclareMixin`` 及其子类（``ConfigBase`` /
    ``Config`` / ``ConfigMemory`` / 两个管道类）是**实现类**，它们的类字典里是真正的
    方法和属性，必须查。

    以前这里只判 ``issubclass(base, ConfigKeysBase)``，而实现类全是它的子类，
    于是一路 ``continue`` 过去，``broadcast`` / ``broadcast_all`` / ``flush`` /
    ``path`` / ``update_config`` / ``configupdate_config`` 都能被声明成键。
    后果分三种：``set`` 里 ``self.broadcast(...)`` 抛 ``'ConfigItemProxy' object is
    not callable``、构造期抛 ``expected str, bytes or os.PathLike``、或者
    ``update_config()`` 静默变成读一个代理什么都不做。

    只有 ``get`` / ``set`` / ``reset`` 那一批当时被拦住了 —— 因为它们在 ``ConfigApi``
    上，而 ``ConfigApi`` 不继承 ``ConfigKeysBase``，歪打正着进了检查范围。

    Args:
        cls: 要检查的类。
        keys: 待检查的 ``{键名: 默认值}``。

    Raises:
        TypeError: 命中保留字，或撞上实现类已有的属性名。
    """
    bad = set(keys) & RESERVED_KEYS

    for name in keys:
        if name in bad:
            continue
        for base in cls.__mro__[1:]:
            if base is object:
                continue
            if (
                isinstance(base, type)
                and issubclass(base, ConfigKeysBase)
                and not issubclass(base, ConfigDeclareMixin)
            ):
                continue                     # 纯声明类自己的键，不算撞
            if name in vars(base):
                bad.add(name)
                break

    if bad:
        raise TypeError(
            f"{cls.__name__} 里这些名字不能当配置键（会砸掉配置对象自己的属性，"
            f"或者是 get / set / reset 的特殊键名）：{sorted(bad)}。"
            f"改个名字；没声明的普通键可以走 cfg.item('键名')，特殊键名（如 'all'）不行。"
        )


def collect_defaults(cls: type) -> dict:
    """扫出 ``cls`` 认哪些配置键、默认值各是多少。

    扫描来源（后面的覆盖前面的）：

    1. MRO 上各基类的 ``DEFAULTS``（MRO 正序，所以近的 / 左边的先占位）；
    2. ``cls`` 自己类体里声明的；
    3. MRO 上的纯声明基类（:class:`ConfigKeysBase` 的子类，且不在
       :class:`ConfigDeclareMixin` 那条线上）里声明的。

    实现类（``Config`` / ``ConfigMemory`` / 管道 / Qt 桥）以及 ``object`` 的类字典
    不扫 —— 换句话说，"哪里能写默认值"是明确的。

    Args:
        cls: 要扫描的类。

    Returns:
        ``{键名: 默认值}``；没有声明就是空 dict。

    Raises:
        TypeError: 声明了保留字，或继承链上出现同名键。
    """
    out: dict = {}

    # ① 继承来的 DEFAULTS
    for base in cls.__mro__[1:]:
        if base is object:
            continue
        for key, value in (base.__dict__.get("DEFAULTS") or {}).items():
            out.setdefault(key, value)

    # ② + ③ 扫声明来源
    for base in reversed(cls.__mro__):
        if base is object or base is ConfigKeysBase:
            continue
        if base is not cls:
            if not (isinstance(base, type) and issubclass(base, ConfigKeysBase)):
                continue
            if issubclass(base, ConfigDeclareMixin):
                continue                     # 实现类的类字典不扫
        for attr, value in list(vars(base).items()):
            if attr.startswith("_") or attr == "DEFAULTS":
                continue
            if isinstance(value, (property, staticmethod, classmethod)):
                continue
            if _is_not_a_config_item(value):
                continue
            if not isinstance(value, DATA_TYPES):
                _check_value_type(cls, attr, value)
            out[attr] = value

    _check_reserved(cls, out)
    return out


# ══════════════════════════════════════════════════════════════
# 声明 / 点操作
# ══════════════════════════════════════════════════════════════

class ConfigKeysBase:
    """纯声明基类：子类只放「键名 = 默认值」，算出 ``DEFAULTS``，不生成点操作。

    "一份声明、多处消费"就靠它 —— 后端、子进程、纯 Python 一侧读的都是
    :attr:`DEFAULTS` 这个普通 dict::

        class AppKeys(ConfigKeysBase):
            app_name = default("myapp")

        AppKeys.DEFAULTS                                # {'app_name': 'myapp'}
        Config(path, default_config=AppKeys.DEFAULTS)   # 非声明式消费
        class AppConfig(Config, AppKeys): ...           # 声明式消费（顺带有点操作）

    规则见模块 docstring。
    """

    #: 本类认得的键与默认值（由 ``__init_subclass__`` 算好）
    DEFAULTS: dict = {}

    #: 本类自己类体里声明的键（不含继承来的）—— 重名检查要用
    _own_declared: dict = {}

    def __init_subclass__(cls, **kwargs):
        """子类创建时算出 ``DEFAULTS``（顺带做重名与保留字检查）。

        Args:
            **kwargs: 类关键字参数，原样转给父类。
        """
        super().__init_subclass__(**kwargs)
        own = _declared_in(cls)
        _check_inheritance_conflict(cls, own)
        cls._own_declared = own
        cls.DEFAULTS = collect_defaults(cls)


def _proxy_property(key: str) -> property:
    """把声明键变成类上的 property，实例访问得到 :class:`ConfigItemProxy`。"""
    return property(
        lambda self: self._item(key),
        doc=f"配置项 {key!r} —— .get() / .set(v) / .reset() / .on(cb)",
    )


class ConfigDeclareMixin(ConfigKeysBase):
    """在 :class:`ConfigKeysBase` 之上，把每个声明键做成实例上的点操作属性。

    :class:`ConfigBase` 继承本类，于是 ``Config`` / ``ConfigMemory`` / 管道以及
    用户的 ``AppConfig(Config, AppKeys)`` 全都有点操作。
    """

    def __init_subclass__(cls, **kwargs):
        """子类创建时把声明的键装成实例上的 property。

        Args:
            **kwargs: 类关键字参数，原样转给父类。
        """
        super().__init_subclass__(**kwargs)          # → 先把 DEFAULTS 算好
        for key in cls.DEFAULTS:
            setattr(cls, key, _proxy_property(key))

    def _item(self, key: str) -> "ConfigItemProxy":
        """按 key 取（并缓存）配置项代理。声明键的 property 走这里。

        Args:
            key: 配置键名。

        Returns:
            该键的 :class:`ConfigItemProxy`（同一个键永远返回同一个对象）。
        """
        cache = self.__dict__.setdefault("_config_proxies", {})
        if key not in cache:
            cache[key] = ConfigItemProxy(self, key)
        return cache[key]

    def item(self, key: str) -> "ConfigItemProxy":
        """显式取一个配置项代理：``cfg.item("speed").set(60)``。

        声明的键可以直接 ``cfg.speed``；没声明的键（以及撞了保留字的键）
        走这条。

        Args:
            key: 配置键名。

        Returns:
            该键的 :class:`ConfigItemProxy`。
        """
        return self._item(key)


class ConfigItemProxy(Generic[T]):
    """一个配置项：``cfg.speed.get() / .set(60) / .reset() / .on(cb)``。

    不能手工 new —— 从 ``cfg.键名`` 或 ``cfg.item("键名")`` 拿。

    它只转发给 owner 的 ``get`` / ``set`` / ``reset`` / ``on`` / ``off``，
    所以「点操作」和「直接调配置对象」是同一条路：落盘、广播、派发、Qt 信号
    全都照常。
    """

    __slots__ = ("_owner", "_key")

    def __init__(self, owner: Any, key: str):
        """不要自己 new —— 从 ``cfg.键名`` 或 ``cfg.item("键名")`` 拿。

        Args:
            owner: 配置对象（点操作全部转发给它）。
            key: 配置键名。
        """
        self._owner = owner
        self._key = key

    def get(self) -> T:
        """读这个配置项当前的值。"""
        return self._owner.get(self._key)

    def set(self, value: T) -> None:
        """写这个配置项（落盘 / 广播 / 派发通知都由 owner 负责）。"""
        self._owner.set(self._key, value)

    def reset(self) -> None:
        """把这个配置项恢复成默认值。"""
        self._owner.reset(self._key)

    def on(self, callback: Callable[[T], None]) -> None:
        """监听这个配置项的变化，等价于 ``owner.on(键名, callback)``。

        Args:
            callback: ``(new_value) -> None``。
        """
        self._owner.on(self._key, callback)

    def off(self, callback: Callable[[T], None]) -> None:
        """取消监听（必须是 :meth:`on` 传进去的同一个函数引用）。

        Args:
            callback: 之前注册的那个函数引用。
        """
        self._owner.off(self._key, callback)

    @property
    def key(self) -> str:
        """配置键名（``"speed"`` 这种字符串）。"""
        return self._key

    def __repr__(self) -> str:
        return f"<ConfigItemProxy {self._key!r}>"
