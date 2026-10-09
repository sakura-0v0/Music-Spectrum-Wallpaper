"""多进程安全配置管理模块。

标准用法是 ``get`` / ``set`` / ``reset``，老名字
``configget`` / ``configset`` / ``configreset`` 仍然可用（转发到新的三个）。

- :class:`Config` 类：JSON 文件配置
- :class:`ConfigMemory` 类：内存配置（同一个形状：定义类 + 实例化，只是不落盘）
- :class:`ConfigInMainProcessPipe` 类：主进程管道口（结束时调用 ``close()``）
- :class:`ConfigInChildProcessPipe` 类：子进程配置实例（结束时调用 ``close()``）
- :class:`ConfigApi` 类：统一接口（get/set/reset + on/off/value_changed）
- :class:`ConfigBase` 类：行为层（加锁、默认值、订阅、广播、唯一派发点）
- :class:`ConfigKeysBase` 类：声明式配置的纯声明基类
- :class:`ConfigDeclareMixin` 类：把声明键变成点操作属性（Config 系列已继承）
- :class:`ConfigItemProxy` 类：点操作代理（``cfg.键名.get()/.set(v)/.reset()``）
- :func:`default`：声明默认值
"""

from .config import Config
from .config_api import ConfigApi
from .config_base import ConfigBase
from .config_dot import (
    ConfigDeclareMixin,
    ConfigItemProxy,
    ConfigKeysBase,
    collect_defaults,
    default,
)
from .config_memory import ConfigMemory
from .config_multiprocess import (
    ConfigInChildProcessPipe,
    ConfigInMainProcessPipe,
    diff_changes,
)

__all__ = [
    "Config",
    "ConfigApi",
    "ConfigBase",
    "ConfigDeclareMixin",
    "ConfigInChildProcessPipe",
    "ConfigInMainProcessPipe",
    "ConfigItemProxy",
    "ConfigKeysBase",
    "ConfigMemory",
    "collect_defaults",
    "default",
    "diff_changes",
]
