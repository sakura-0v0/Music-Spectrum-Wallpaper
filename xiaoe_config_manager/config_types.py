"""配置值的类型定义，以及由它推导出的运行时校验元组。

全项目对"一个配置值能是什么"只在这里说一次：

* :data:`ConfigValue` —— 给类型检查器看的类型；
* :data:`DATA_TYPES` —— 给 ``isinstance`` 用的运行时元组，由前者推导，
  所以两者不会漂移。

这个模块不 import 包里任何其它模块：``config_dot``、``config_api``、
``config_base``、三个后端都要用它，往任何一边放都会循环导入。
"""

from __future__ import annotations

from typing import TypeAlias, get_args, get_origin

__all__ = ["ConfigValue", "ConfigDict", "DATA_TYPES"]

# 一个配置值。递归：``list`` / ``dict`` 里面装的还是配置值。
#
# 两处写法都是必须的：
# * 标 ``TypeAlias``：否则 IDE / mypy 会把它当成普通模块级变量，
#   在参数注解里用它就报"类型提示无效"。
# * 右侧写真实表达式、不是字符串：否则 ``get_args`` 拿不到成员，
#   ``DATA_TYPES`` 就没法从它推导。
ConfigValue: TypeAlias = (
    str | int | float | bool | None
    | list["ConfigValue"] | dict[str, "ConfigValue"]
)

#: ``get('all')`` / ``reset('all')`` 用的整份配置。
ConfigDict: TypeAlias = dict[str, ConfigValue]

#: 运行时校验用的类型元组，供 ``isinstance(value, DATA_TYPES)`` 使用。
#:
#: 从 :data:`ConfigValue` 拆出来，而不是另外手写一份 —— 手写的那份迟早会和
#: 类型注解对不上。``get_origin`` 把 ``list[...]`` / ``dict[...]`` 还原成
#: ``list`` / ``dict``，``None`` 那一支还原成 ``NoneType``。
DATA_TYPES: tuple[type, ...] = tuple(
    get_origin(arg) or arg for arg in get_args(ConfigValue)
)
