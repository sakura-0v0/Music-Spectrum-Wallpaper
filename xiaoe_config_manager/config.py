"""JSON 文件配置后端 —— 只管存储：读文件、原子落盘、给默认值补缺。

行为层（加锁、默认值、订阅、广播、唯一派发点）在
:mod:`xiaoe_config_manager.config_base`，本模块只实现那几个存储原语。

    class AppKeys(ConfigKeysBase):
        speed = default(50)

    class AppConfig(Config, AppKeys):
        ...

    cfg = AppConfig("config_files/app")     # 路径不带 .json
    cfg.speed.get() / .set(60) / .reset()
"""

from __future__ import annotations

import copy
import json
import os
from typing import Any, Callable

from xiaoe_config_manager.config_base import ConfigBase

__all__ = ["Config"]


class Config(ConfigBase):
    """JSON 文件配置（多进程环境下请保持单例）。

    优先级（与代码一致的说法）：``default_config_callback``（仅当
    ``init_use_callback=True``）> ``default_config`` > 类声明的 ``DEFAULTS``。
    也就是说：显式传了 ``default_config`` 时，声明里的默认值不参与
    （要合并请自己合，别指望隐式规则）。

    Args:
        file_name: 配置文件名（不带 ``.json``）。
        default_config: 静态默认配置（配置里缺的键会自动补上）。
        default_config_callback: 动态默认配置回调，参数是当前配置（仅当
            ``init_use_callback=True`` 时在初始化阶段调用；reset 时总会调用）。
        init_use_callback: 初始化阶段是否用回调拿默认配置。
    """

    def __init__(
            self,
            file_name: str = 'config',
            default_config: dict | None = None,
            default_config_callback: Callable | None = None,
            init_use_callback: bool = True,
    ):
        super().__init__(default_config=default_config,
                         default_config_callback=default_config_callback)
        self.fname = file_name

        try:
            self.config = self._read_all()
        except FileNotFoundError:
            # 只有「第一次运行还没有文件」才兜底。
            # 文件损坏 / 没权限 / 编码错 → 原样往上抛：静默吞掉之后会被 _save()
            # 用默认值覆盖掉用户原来的配置（数据永久消失，且没有任何提示）。
            self.config = {}

        if self.default_config_callback and init_use_callback:
            self.default_config = copy.deepcopy(
                self.default_config_callback(self.config))
        elif default_config is None:
            # 深拷贝：类声明里的 list / dict 不能被实例共享，否则一个实例的
            # 改动会串到同类其它实例（甚至改掉类属性本身）
            self.default_config = copy.deepcopy(type(self).DEFAULTS or {})

        changed = False
        for key, value in copy.deepcopy(self.default_config).items():
            if key not in self.config:
                self.config[key] = value
                changed = True
        if changed:
            self._save()

    # ══════════════════════════════════════════════════════════
    # 存储原语
    # ══════════════════════════════════════════════════════════

    @property
    def path(self) -> str:
        """配置文件的完整路径（``<file_name>.json``）。"""
        return f"{self.fname}.json"

    def _read(self, key: str) -> Any:
        """读单个键。

        返回的是**深拷贝**：调用方改这个值（哪怕它是嵌套的 list / dict）也不会
        动到配置里那份。

        Args:
            key: 配置键名。

        Raises:
            KeyError: 键不存在。缺 key 必须报错，绝不静默创建（见文档 J1）。
        """
        return copy.deepcopy(self.config[key])

    def _read_all(self) -> dict:
        """读整份配置 —— 从文件重读，并替换内存副本。

        返回的是**深拷贝**（嵌套结构也一样独立）。

        注意这条副作用：文件里的内容会覆盖 ``self.config``（本进程未落盘的中间
        状态因此丢掉），换来的是别人刚写进去的值能看到。
        """
        with open(self.path, 'r', encoding='UTF-8') as f:
            self.config = json.load(f)
        return copy.deepcopy(self.config)

    def _write(self, key: str, value: Any) -> None:
        """写进内存副本（真正落盘在 :meth:`_save`）。

        存的是 ``value`` 的**深拷贝**：调用方之后改自己那个对象，配置不受影响。

        Args:
            key: 配置键名。
            value: 配置值。
        """
        self.config[key] = copy.deepcopy(value)

    def _apply_reset(self, key: str) -> None:
        """按 ``self.default_config`` 改回默认值。

        Args:
            key: 配置键名，或 ``'all'``。
        """
        default_config = copy.deepcopy(self.default_config)
        if key == "all":
            self.config = default_config
        else:
            self.config[key] = default_config[key]

    def _save(self) -> None:
        """原子落盘：先写临时文件，成功之后再替换。

        直接以 ``'w'`` 打开原文件写会在序列化失败时把文件截断成半截
        （``json.dump`` 的类型错误、磁盘写满），下次启动就是坏配置 —— 那正是
        「配置全丢」这条故障链的第一步。
        """
        tmp_path = f"{self.path}.tmp"
        with open(tmp_path, 'w', encoding='UTF-8') as f:
            json.dump(self.config, f, indent=4, ensure_ascii=False)
        os.replace(tmp_path, self.path)
