"""主进程 ⇄ 子进程的管道消息协议。

只有三个动作：

    子进程 → 主进程（config_set_queue）
        SET     写一个键          {'call': SET, 'args': [key, value], ORIGIN: id}
        RESET   把一个键恢复默认  {'call': RESET, 'args': [key], ORIGIN: id}
        GETALL  要一份完整配置    {'call': GETALL}

    主进程 → 子进程（config_get_queue）
        SET     某个键变了        {'call': SET, 'args': [key, value], ORIGIN: id}
        RESET   某个键被重置      {'call': RESET, 'args': [key, value], ORIGIN: id}
        GETALL  整份配置在这里    {'call': GETALL, 'args': [整份 dict, 收件人 id]}

同一个 ``call`` 名在两个方向上是对称的：子进程收到 ``SET`` 就乐观写本地缓存，
收到 ``RESET`` 就按消息里的值更新缓存并派发。

``SET`` / ``RESET`` 只带一个键。整份配置只在两种时候过线：子进程启动时拉一次
（``GETALL`` 上行），以及 ``reset('all')`` 让键集合整体变化时推一次
（``GETALL`` 下行）。

关于 ``ORIGIN``（键名 ``"origin"``）
-----------------------------------
值是"这条变更由哪个子进程发起"的 ID，主进程自己发起的写是 ``None``。
子进程靠它区分两件本来长得一样的事：

* ``origin == 自己的 ID``：这是我自己那次 ``set`` 的回声。本地缓存当时已经
  乐观写过了，所以整条消息可以直接忽略。
* 其他任何情况：别人的写入，照常更新缓存并派发。

没有这个字段时只能拿"值有没有变"去猜回声，那样会把"别的进程恰好写了同一个
值"也误判成回声，导致那个进程的监听器收不到通知 —— 和 ``Config`` /
``ConfigMemory`` 的行为就对不上了。

``None`` 沿用 multiprocessing 的惯例：往队列里放 ``None`` 表示"收工"，
两个方向的循环都用它退出。

这个模块只放常量，不 import 任何东西 —— ``config_base`` 和
``config_multiprocess`` 都要用它，放一边会循环导入。
"""

from __future__ import annotations

__all__ = ["SET", "RESET", "GETALL", "ORIGIN"]

#: 写一个键。两个方向都用。
SET = "set"
#: 把一个键恢复默认。两个方向都用。
RESET = "reset"
#: 整份配置。上行是"给我一份"，下行是"给你一份"。
GETALL = "getall"
#: 消息里表示"谁发起的"的键名。
ORIGIN = "origin"
