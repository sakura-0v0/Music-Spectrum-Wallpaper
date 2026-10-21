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

import atexit
import copy
import json
import os
import tempfile
import threading
import time
import traceback
from typing import Callable

from xiaoe_config_manager.config_base import ConfigBase
from xiaoe_config_manager.config_types import ConfigDict, ConfigValue

__all__ = ["Config"]


class Config(ConfigBase):
    """JSON 文件配置（多进程环境下请保持单例）。

    优先级（与代码一致的说法）：``default_config_callback``（仅当
    ``init_use_callback=True``）> ``default_config`` > 类声明的 ``DEFAULTS``。
    也就是说：显式传了 ``default_config`` 时，声明里的默认值不参与
    （要合并请自己合，别指望隐式规则）。

    新版本落盘有延迟，虽然注册了atexit.register，但是强烈建议退出时执行一次 flush()
    显示将落盘。
    Args:
        file_name: 配置文件名（不带 ``.json``）。
        default_config: 静态默认配置（配置里缺的键会自动补上）。
        default_config_callback: 动态默认配置回调，参数是当前配置（仅当
            ``init_use_callback=True`` 时在初始化阶段调用；reset 时总会调用）。
        init_use_callback: 初始化阶段是否用回调拿默认配置。
        save_delay: 延迟落盘的时间（s），避免高频写入文件。设置0则退回立即落盘。
        save_on_exit: 自动在退出时执行落盘。
    """

    def __init__(
            self,
            file_name: str = 'config',
            default_config: dict | None = None,
            default_config_callback: Callable | None = None,
            init_use_callback: bool = True,
            save_delay: float = 0.5,
            save_on_exit: bool = True,
    ):
        super().__init__(default_config=default_config,
                         default_config_callback=default_config_callback)
        self.fname = file_name
        self._save_delay = save_delay
        self._save_timer: threading.Timer | None = None
        self._dirty = False
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
            self._atomic_write()

        if save_on_exit:
            atexit.register(self.flush)
    # ══════════════════════════════════════════════════════════
    # 存储原语
    # ══════════════════════════════════════════════════════════

    @property
    def path(self) -> str:
        """配置文件的完整路径（``<file_name>.json``）。"""
        return f"{self.fname}.json"

    def _read(self, key: str) -> ConfigValue:
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
        """加锁读整份配置 —— 从文件重读，并替换内存副本。"""
        with self.config_lock:
            return self._read_all_locked()

    def _read_all_locked(self) -> dict:
        """读整份配置 —— 从文件重读，并替换内存副本。

        返回的是**深拷贝**（嵌套结构也一样独立）。

        注意这条副作用：文件里的内容会覆盖 ``self.config``（本进程未落盘的中间
        状态因此丢掉），换来的是别人刚写进去的值能看到。
        """
        self._flush_locked()
        with open(self.path, 'r', encoding='UTF-8') as f:
            self.config = json.load(f)
        return copy.deepcopy(self.config)

    def _write(self, key: str, value: ConfigValue) -> None:
        """写进内存副本（真正落盘在 :meth:`_save`）。

        存的是 ``value`` 的**深拷贝**：调用方之后改自己那个对象，配置不受影响。

        用的是 copy-on-write：浅拷贝一份、改完换引用。``update_config`` 会把
        ``self.config`` 直接交给子进程队列，真正的 pickle 发生在队列的 feeder
        线程里；原地改会让那个线程读到一个边写边读的 dict。

        Args:
            key: 配置键名。
            value: 配置值。
        """
        new = dict(self.config)
        new[key] = copy.deepcopy(value)
        self.config = new

    def _apply_reset(self, key: str) -> None:
        """按 ``self.default_config`` 改回默认值。

        同样是 copy-on-write，理由见 :meth:`_write`。

        Args:
            key: 配置键名，或 ``'all'``。
        """
        default_config = copy.deepcopy(self.default_config)
        if key == "all":
            self.config = default_config
        else:
            new = dict(self.config)
            new[key] = default_config[key]
            self.config = new
        self._dirty = True

    def _save(self) -> None:
        """调度落盘（调用方已持 config_lock）。只标记 + 重置定时器，不写文件。

        ``save_delay <= 0`` 时退化成立刻落盘。
        """
        self._dirty = True
        if self._save_delay <= 0:
            self._flush_locked()
            return
        if self._save_timer is not None:
            self._save_timer.cancel()
        t = threading.Timer(self._save_delay, self.flush)
        t.daemon = True
        self._save_timer = t
        t.start()

    def _flush_locked(self) -> None:
        """调用方已持 config_lock。取消挂起的定时器并落盘。幂等。"""
        if self._save_timer is not None:
            self._save_timer.cancel()
            self._save_timer = None
        if not self._dirty:
            return
        try:
            self._atomic_write()
        except Exception:                     # noqa: BLE001
            # 写失败保持 _dirty，留给下一次 flush（含 atexit）重试
            traceback.print_exc()
            return
        self._dirty = False

    def flush(self) -> None:
        """把内存里的配置立刻写到磁盘。退出前必须调用；幂等，可重复调。"""
        with self.config_lock:
            self._flush_locked()

    def _atomic_write(self) -> None:
        """原子落盘：唯一临时名 + 写完替换（带重试）。

        - 临时名唯一（``mkstemp``）：两个写者抢同一个 ``.tmp``，一个正在写、
          另一个把它搬走，就会互相打脸。
        - 替换带重试：Windows 上 Defender / 索引服务 / 别的进程刚打开过文件，
          句柄要几十毫秒才放，不重试就是偶发 ``PermissionError``。
        """
        directory = os.path.dirname(self.path) or "."
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".cfg-", suffix=".tmp")
        try:
            with os.fdopen(fd, 'w', encoding='UTF-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
            _replace_with_retry(tmp_path, self.path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

def _replace_with_retry(src: str, dst: str, tries: int = 8) -> None:
    """``os.replace`` + 退避重试，专治 Windows 瞬时 ``PermissionError``。

    只吃 ``PermissionError``（文件被临时占用）；磁盘满、路径不存在这类
    ``OSError`` 照旧往上抛。
    """
    delay = 0.02
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.5)
