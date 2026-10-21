"""内存版配置后端 —— 接口与 :class:`~xiaoe_config_manager.config.Config` 一致，只是不落盘。

标准做法和文件版**一模一样**：定义一个类，然后实例化。

    class AppKeys(ConfigKeysBase):
        speed = default(50)

    class AppMemory(ConfigMemory, AppKeys):      # 内存版：基类换成 ConfigMemory
        ...

    mem = AppMemory()                            # 用声明的默认值
    mem = AppMemory({"speed": 99})               # 再盖一份 dict 上去
    mem.speed.get()                              # 点操作照旧

想省掉"写一个类"这一步时，也可以用便捷路径 ``Config.memory({...})`` /
``XxxConfig.memory()`` —— 它按类的声明合成一份内存配置（点操作也在），适合临时配置与
老代码兼容。正经当配置用（多个键、要 reset 语义、要 IDE 补全）还是定义类。
"""

from __future__ import annotations

import copy

from xiaoe_config_manager.config_base import ConfigBase
from xiaoe_config_manager.config_types import ConfigDict, ConfigValue

__all__ = ["ConfigMemory"]


class ConfigMemory(ConfigBase):
    """内存版配置：一个 dict + 一份重置目标，没有文件、不落盘。

    用法与 :class:`~xiaoe_config_manager.config.Config` 对称：继承它、把声明类接上，
    实例化时给不给 dict 都行（不传就用类声明的默认值）。

        class AppMemory(ConfigMemory, AppKeys):
            ...

        mem = AppMemory()

    和文件版的语义**完全一致**（没有任何"内存版例外"）：

    * ``get(缺键)`` 抛 ``KeyError`` —— 与文件版一样，缺 key 就该报错；
    * ``set`` / ``reset`` / ``on`` / ``off`` / ``value_changed`` / ``off_value_changed``
      也全都一样；``reset(缺键)`` 同样抛 ``KeyError``。
    * ``get('all')`` 返回整份 dict。
    * 读出来的是**深拷贝**，写进去的也是**深拷贝** —— 嵌套的 list / dict 与
      调用方、与 ``self.default_config`` 都不共享，改哪边都不会串。

    唯一的差别是**存储位置**：一个 dict，没有文件。

    ``fname`` 是 ``None``（没有文件）—— 调试时 ``cfg.fname is None`` 就说明这是内存版。
    """

    def __init__(self, default_config: dict | None = None):
        """建一份内存配置。

        Args:
            default_config: 初始值，**盖在**类声明的默认值上面；同时也是 reset 的目标。
                不传就直接用 ``type(self).DEFAULTS``（与文件版
                ``Config(路径)`` 退回声明默认值是同一个规则）。
        """
        merged = {**(type(self).DEFAULTS or {}), **(default_config or {})}
        super().__init__(default_config=merged)
        #: 没有文件（保留这个名字是为了和 Config 对称，也方便调试时一眼看出）
        self.fname = None
        # 深拷贝：类声明的默认值、调用方传进来的 default_config 都不能与该实例共享嵌套对象
        self.config = copy.deepcopy(merged)

    # ══════════════════════════════════════════════════════════
    # 存储原语
    # ══════════════════════════════════════════════════════════

    def _read(self, key: str) -> ConfigValue:
        """读一个键。

        返回的是**深拷贝**：调用方改这个值（哪怕它是嵌套的 list / dict）也不会
        动到配置里那份。

        Args:
            key: 配置键名。

        Raises:
            KeyError: 键不存在 —— 与文件版**完全一致**，不搞特殊。
                读"可能没有的键"是调用方的事（宽容留在读的一侧），
                配置对象本身一律严格。
        """
        return copy.deepcopy(self.config[key])

    def _read_all(self) -> dict:
        """读整份配置（深拷贝，改它——包括改嵌套的值——都不会影响配置本身）。

        ``self.config`` 是 copy-on-write 的：每次写入都换一个新的 dict，旧对象
        发布出去之后永远不会再被改。所以这里读到的引用是一致的快照，不需要持锁
        也不会撞上 "dictionary changed size during iteration"。
        """
        return copy.deepcopy(self.config)

    def _write(self, key: str, value: ConfigValue) -> None:
        """写进内存 dict（copy-on-write：浅拷贝一份、改完换引用）。

        存的是 ``value`` 的**深拷贝**：调用方之后改自己那个对象，配置不受影响。

        为什么不用 ``self.config[key] = ...`` 原地改：``update_config`` 会把
        ``self.config`` 直接交给子进程队列，而真正的 pickle 发生在队列的 feeder
        线程里。原地改会让那个线程读到一个边写边读的 dict；换成"改新的、换引用"
        之后，已经发布出去的那个 dict 就固定下来了。

        Args:
            key: 配置键名。
            value: 配置值。
        """
        new = dict(self.config)
        new[key] = copy.deepcopy(value)
        self.config = new

    def _apply_reset(self, key: str) -> None:
        """按 ``self.default_config`` 改回默认值（深拷贝，不与默认值共享嵌套对象）。

        同样是 copy-on-write，理由见 :meth:`_write`。

        Args:
            key: 配置键名，或 ``'all'``。
        """
        if key == "all":
            self.config = copy.deepcopy(self.default_config)
        else:
            new = dict(self.config)
            new[key] = copy.deepcopy(self.default_config[key])
            self.config = new

    def _save(self) -> None:
        """内存版没有落盘这一步。"""

    def _flush_locked(self) -> None:
        """内存版没有落盘这一步。"""
