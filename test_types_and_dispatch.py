"""类型校验、派发次数、回声识别 —— 这几条是"三个后端行为一致"的护栏。

和 ``test.py`` 分开放，是因为这里的测试大多不需要起子进程：用一个进程内的
假队列就能把 ``ConfigInChildProcessPipe`` 的收发路径跑通，毫秒级。
只有最后一组是真的双子进程端到端。

运行：
    pytest test_types_and_dispatch.py -v
"""

import multiprocessing
import queue
import threading
import time

import pytest

from xiaoe_config_manager import (
    Config,
    ConfigApi,
    ConfigBase,
    ConfigInChildProcessPipe,
    ConfigInMainProcessPipe,
    ConfigKeysBase,
    ConfigMemory,
    ConfigValue,
    DATA_TYPES,
    default,
)
from xiaoe_config_manager.config_types import ConfigDict


# ===========================================================================
# 工具
# ===========================================================================

class FakeQueue:
    """进程内的假队列，顶替 ``multiprocessing.Queue``。

    只需要 ``get`` / ``put`` / ``close`` / ``join_thread`` 四个方法，
    行为是"投进去的按顺序出来"，够跑通子进程管道的收发路径。

    ``fail_after``：成功取出 N 条之后，``get`` 开始抛 ``ValueError``，
    用来模拟"队列被关闭 / 底层管道断了"。
    """

    def __init__(self, first=None, fail_after=None):
        self._q = queue.Queue()
        if first is not None:
            self._q.put(first)
        self._fail_after = fail_after
        self._gets = 0

    def get(self, timeout=None):
        if self._fail_after is not None and self._gets >= self._fail_after:
            raise ValueError("Queue is closed")
        self._gets += 1
        return self._q.get(timeout=timeout)

    def put(self, value):
        self._q.put(value)

    def close(self):
        pass

    def join_thread(self):
        pass


class BrokenQueue:
    """一上来就抛异常的队列，用于构造期的测试。"""

    def get(self, timeout=None):
        raise ValueError("Queue is closed")

    def put(self, value):
        raise ValueError("Queue is closed")

    def close(self):
        pass

    def join_thread(self):
        pass


class DemoKeys(ConfigKeysBase):
    """本文件用的最小声明。"""
    speed = default(50)
    name = default("demo")


class DemoFile(Config, DemoKeys):
    ...


class DemoMemory(ConfigMemory, DemoKeys):
    ...


class DemoChild(ConfigInChildProcessPipe, DemoKeys):
    ...


CHILD_ID = "child-99"


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def make_child(first_config=None):
    """造一个子进程侧配置 + 它的下行队列（假队列，不起进程）。

    Returns:
        ``(cfg, get_queue)``；``cfg`` 已 ``close`` 由调用方负责。
    """
    payload = {"speed": 50, "name": "demo"} if first_config is None else first_config
    get_q = FakeQueue({"call": "getall", "args": [payload, CHILD_ID]})
    cfg = DemoChild(FakeQueue(), get_q)
    return cfg, get_q


def wait_until(predicate, timeout=2.0):
    """等 predicate 成立。管道侧的派发发生在后台线程，不能假设同步。"""
    deadline = threading.Event()
    step = 0.005
    waited = 0.0
    while waited < timeout:
        if predicate():
            return True
        deadline.wait(step)
        waited += step
    return predicate()


# ===========================================================================
# 一、声明值的类型校验：不是配置值就报错，不静默跳过
# ===========================================================================

class TestValueTypeCheck:

    def test_tuple_default_raises(self):
        """tuple 不在允许清单里：它写进 JSON 会变成 list，干脆在声明时拒绝。"""
        with pytest.raises(TypeError) as exc:
            class BadTuple(ConfigKeysBase):
                pair = (1, 2)

        message = str(exc.value)
        assert "pair" in message
        assert "tuple" in message

    def test_set_default_raises(self):
        with pytest.raises(TypeError) as exc:
            class BadSet(ConfigKeysBase):
                tags = {1, 2}

        assert "tags" in str(exc.value)
        assert "set" in str(exc.value)

    def test_callables_classes_modules_are_skipped(self):
        """方法、嵌套类、导入的模块本来就不是配置项，不该报错。"""
        import json as some_module

        class WithTools(ConfigKeysBase):
            speed = default(50)

            class Inner:
                pass

            module = some_module

            def helper(self):
                return 1

            @staticmethod
            def static_helper():
                return 2

            @property
            def prop(self):
                return 3

        assert WithTools.DEFAULTS == {"speed": 50}

    def test_underscore_names_are_skipped(self):
        """下划线开头是内部名字，既不报错也不进 DEFAULTS。"""
        class WithPrivate(ConfigKeysBase):
            speed = default(50)
            _RETRY = (1, 2, 3)

        assert WithPrivate.DEFAULTS == {"speed": 50}

    def test_child_id_is_reserved(self):
        """``child_id`` 是子进程管道的实例属性，声明它会在构造时炸。

        这条比"撞了方法名"更隐蔽：``child_id`` 是**实例**属性（``__init__`` 里赋的），
        动态检查只看类字典，所以必须显式列进 RESERVED_KEYS。以前它漏了，结果是
        声明一个叫 ``child_id`` 的键 → 类创建不报错 → 实例化时
        ``AttributeError: property has no setter``，而且只有管道后端炸，
        文件版 / 内存版正常。
        """
        with pytest.raises(TypeError) as exc:
            class BadChildId(ConfigKeysBase):
                child_id = "boom"

        assert "child_id" in str(exc.value)

    @pytest.mark.parametrize("name", [
        "broadcast",         # set() 里 self.broadcast(...) → ConfigItemProxy 不可调用
        "broadcast_all",     # reset('all') 里同样
        "update_config",     # 静默变成读一个代理，什么都不发生
        "configupdate_config",
        "flush",             # 构造期抛 "the first argument must be callable"
        "path",              # 构造期抛 "expected str, bytes or os.PathLike"
    ])
    def test_impl_class_members_are_reserved(self, name):
        """实现类自己的方法和属性也不能当键名。

        ``_check_reserved`` 的动态检查原本跳过所有 ``ConfigKeysBase`` 子类，
        而 ``ConfigBase`` / ``Config`` 正是它的子类 —— 于是整个实现类没被查过。
        ``get`` / ``set`` / ``reset`` 那批侥幸被拦住，只因为它们在 ``ConfigApi`` 上、
        而 ``ConfigApi`` 不继承 ``ConfigKeysBase``。

        这些名字放行的后果很不好查：类定义成功、实例化成功、能读能写，
        直到某次写别的键才抛出一个跟键名毫无关系的错。
        """
        with pytest.raises(TypeError) as exc:
            Keys = type("Keys", (ConfigKeysBase,), {name: 0})
            type("Cfg", (DemoFile, Keys), {})

        assert name in str(exc.value)

    def test_declaration_still_works_after_reserved_fix(self):
        """拦住实现类成员之后，正常声明不能被误伤。"""
        class FineKeys(ConfigKeysBase):
            app_name = default("myapp")
            timeout = default(30)
            _RETRY = (1, 2, 3)

            class Inner:
                pass

            def helper(self):
                return 1

        class FineConfig(Config, FineKeys):
            ...

        assert FineKeys.DEFAULTS == {"app_name": "myapp", "timeout": 30}
        cfg = FineConfig("fine")
        cfg.timeout.set(60)
        assert cfg.timeout.get() == 60
        cfg.reset("all")
        assert cfg.timeout.get() == 30


# ===========================================================================
# 二、派发次数：三个后端一致 —— 一次写就是一次通知
# ===========================================================================

class TestDispatchCount:

    def test_set_same_value_still_dispatches(self, workdir):
        """set 一个和当前一样的值，照样派发。三个后端都不做"值没变就跳过"。"""
        for cfg in (DemoFile("f"), DemoMemory()):
            hits = []
            cfg.value_changed(lambda key, value: hits.append((key, value)))
            cfg.set("speed", 50)                 # 当前就是 50
            assert hits == [("speed", 50)], type(cfg).__name__

    def test_child_set_same_value_still_dispatches(self):
        cfg, _ = make_child()
        try:
            hits = []
            cfg.value_changed(lambda key, value: hits.append((key, value)))
            cfg.set("speed", 50)
            assert hits == [("speed", 50)]
        finally:
            cfg.close()

    def test_reset_dispatches_once_with_new_value(self, workdir):
        """reset 派发且只派发一次，值是新的。

        管道侧是异步的（当场发消息、广播回来才派发），所以单独等它；
        这里断言的是**总数**和**内容**，三个后端都一样。
        """
        for cfg in (DemoFile("r"), DemoMemory()):
            cfg.set("speed", 99)
            hits = []
            cfg.value_changed(lambda key, value: hits.append((key, value)))
            cfg.reset("speed")
            assert hits == [("speed", 50)], type(cfg).__name__

        cfg, get_q = make_child()
        try:
            cfg.set("speed", 99)
            hits = []
            cfg.value_changed(lambda key, value: hits.append((key, value)))
            cfg.reset("speed")
            # 悲观路径：当场不派发
            assert hits == []
            get_q.put({"call": "reset", "args": ["speed", 50], "origin": CHILD_ID})
            assert wait_until(lambda: hits == [("speed", 50)]), hits
        finally:
            cfg.close()

    def test_reset_all_dispatches_single_all_key(self, workdir):
        """reset('all') 派发一条 ('all', 整份)，不是逐键 N 条。"""
        for cfg in (DemoFile("ra"), DemoMemory()):
            cfg.set("speed", 99)
            cfg.set("name", "changed")
            hits = []
            cfg.value_changed(lambda key, value: hits.append((key, value)))
            cfg.reset("all")
            assert [key for key, _ in hits] == ["all"], type(cfg).__name__
            assert hits[0][1] == {"speed": 50, "name": "demo"}

        cfg, get_q = make_child()
        try:
            cfg.set("speed", 99)
            hits = []
            cfg.value_changed(lambda key, value: hits.append((key, value)))
            cfg.reset("all")
            assert hits == []
            get_q.put({"call": "getall",
                       "args": [{"speed": 50, "name": "demo"}, CHILD_ID],
                       "origin": CHILD_ID})
            assert wait_until(lambda: len(hits) == 1), hits
            assert hits == [("all", {"speed": 50, "name": "demo"})]
        finally:
            cfg.close()


# ===========================================================================
# 三、回声识别：靠 origin，不靠"值有没有变"
# ===========================================================================

class TestEchoOrigin:

    def test_child_ignores_own_set_echo(self):
        """自己 set 出去的那一发广播回来，不再派发一次。"""
        cfg, get_q = make_child()
        try:
            hits = []
            cfg.value_changed(lambda key, value: hits.append((key, value)))
            cfg.set("speed", 99)                       # 乐观写，当场派发
            assert hits == [("speed", 99)]

            get_q.put({"call": "set", "args": ["speed", 99], "origin": CHILD_ID})
            assert not wait_until(lambda: len(hits) > 1, timeout=0.3), hits
        finally:
            cfg.close()

    def test_child_dispatches_other_childs_write(self):
        """别的进程写了一个和当前相同的值，也要派发。

        旧实现靠"值没变"判断回声，这一条会失败 —— 它正是那个 bug 的回归。
        """
        cfg, get_q = make_child()
        try:
            hits = []
            cfg.value_changed(lambda key, value: hits.append((key, value)))

            # 值就是当前值，但 origin 是别人
            get_q.put({"call": "set", "args": ["speed", 50], "origin": "child-OTHER"})
            assert wait_until(lambda: hits == [("speed", 50)]), hits
        finally:
            cfg.close()

    def test_child_reset_echo_dispatches_new_value(self):
        """reset 的回声必须派发：那是子进程第一次也是唯一一次看到新值。"""
        cfg, get_q = make_child()
        try:
            cfg.set("speed", 99)
            hits = []
            cfg.value_changed(lambda key, value: hits.append((key, value)))
            cfg.reset("speed")
            assert hits == []                          # 悲观：当场不派发

            get_q.put({"call": "reset", "args": ["speed", 50], "origin": CHILD_ID})
            assert wait_until(lambda: hits == [("speed", 50)]), hits
        finally:
            cfg.close()

    def test_set_inside_callback_is_not_marked_as_child_origin(self, workdir):
        """回调里再 set 另一个键，那次广播的 origin 必须是 None（主进程发起）。

        ``ConfigInMainProcessPipe._loop`` 在下发消息期间把 ``_origin`` 设成子进程 ID。
        用户在回调里联动写别的键（"收到 A 变了，顺手改 B 通知 UI"），如果派发期间
        不把 origin 清掉，B 那次广播会带上 A 的 ID ——
        子进程 A 收到后当成自己的回声丢掉：**值写进去了，但界面不更新**。
        """
        cfg = DemoFile("cb")
        pipe = ConfigInMainProcessPipe(cfg)
        sent = []
        original = cfg.broadcast

        def spy(key, value, reset=False):
            sent.append((key, value, cfg._current_origin()))
            return original(key, value, reset)

        cfg.broadcast = spy
        cfg.on("speed", lambda value: cfg.set("name", "linked") if value == 99 else None)

        try:
            cfg._origin.value = pipe.child_id      # 模拟 _loop 正在处理 A 的消息
            try:
                cfg.set("speed", 99)
            finally:
                cfg._origin.value = None

            by_key = {key: origin for key, _, origin in sent}
            assert by_key["speed"] == pipe.child_id, "A 自己的写要保留 origin（回声该丢）"
            assert by_key["name"] is None, "回调里写的键属主进程发起，不能被当成 A 的回声"
        finally:
            pipe.close()


# ===========================================================================
# 四、类型定义本身：ConfigValue 与 DATA_TYPES 不能漂移
# ===========================================================================

class TestTypeDefinitions:

    def test_data_types_derived_from_config_value(self):
        """DATA_TYPES 由 ConfigValue 推导，tuple 自然不在里面。"""
        from typing import get_args

        assert len(get_args(ConfigValue)) == 7
        assert tuple not in DATA_TYPES
        assert set(DATA_TYPES) == {str, int, float, bool, type(None), list, dict}

    def test_get_has_overloads(self):
        """get 的两个 overload 是 ``cfg.get("all")["k"]`` 能过类型检查的前提。

        类型提示本身测不了行为，但能锁住"别把它删了"——
        用 ``typing.get_overloads`` 直接读注册表。
        """
        from typing import get_overloads

        assert len(get_overloads(ConfigApi.get)) == 2
        assert len(get_overloads(ConfigBase.get)) == 2


# ===========================================================================
# 五、广播发出去的是副本，不是调用方那个对象
# ===========================================================================

def _child_read_rows(set_q, get_q, report_q, delay):
    """子进程：等一会儿再把收到的 rows 报回去。"""
    class Child(ConfigInChildProcessPipe, DemoKeys):
        ...

    get_q_owner = None
    cfg = Child(set_q, get_q)
    try:
        time.sleep(delay)
        report_q.put(cfg.get("rows"))
    finally:
        cfg.close()


class TestBroadcastIsolation:

    def test_broadcast_sends_deep_copy(self):
        """``set`` 返回后立刻改原对象，广播出去的不能跟着变。

        ``Queue.put`` 立即返回、真正 pickle 在 feeder 线程 —— 传引用的话，
        调用方在 ``set`` 返回后改自己那个 list（很常见），子进程会收到改过的内容，
        而主进程内存和文件里还是旧值。用假队列时 pickle 不会发生，所以这里
        直接检查 put 进去的那个对象和原对象是否共享嵌套结构。
        """
        cfg, _ = make_child()
        try:
            src = [{"n": [1]}]
            cfg.set("rows", src)
            sent = cfg.config_set_queue._q.queue[-1]     # 最后一条消息
            assert sent["args"][1] == [{"n": [1]}]

            src[0]["n"].append(999)                      # 改原对象
            assert sent["args"][1] == [{"n": [1]}], "广播消息和调用方共享了嵌套对象"
            assert cfg.get("rows") == [{"n": [1]}]
        finally:
            cfg.close()

    def test_child_write_sends_deep_copy(self):
        """子进程 ``_write`` 发出去的值同样是副本。"""
        cfg, _ = make_child()
        try:
            src = [{"n": [1]}]
            cfg.set("rows", src)
            sent = cfg.config_set_queue._q.queue[-1]
            src[0]["n"].append(999)
            assert sent["args"][1] == [{"n": [1]}]
            assert cfg.get("rows") == [{"n": [1]}]
        finally:
            cfg.close()


# ===========================================================================
# 六、收消息线程：队列坏了不能静默死掉
# ===========================================================================

class TestPipeFailureIsLoud:
    """收消息线程：队列坏了必须显式失败，不能静默死掉。

    直接驱动 ``_loop`` / ``_update_config_loop``，不靠换队列属性 ——
    线程一旦阻塞在 ``get()`` 上，换属性也救不回来（那正是这些测试第一版卡死的原因）。
    """

    def test_main_loop_marks_dead_when_queue_broken(self):
        pipe = object.__new__(ConfigInMainProcessPipe)
        pipe.config = DemoFile
        pipe.child_id = "child-x"
        pipe.config_set_queue = BrokenQueue()
        pipe._closed = False
        pipe.dead = False

        pipe._loop()                              # 直接在当前线程跑，必然返回

        assert pipe.dead is True, "队列坏了却没标记 dead"

    def test_main_loop_retries_then_gives_up(self):
        """连续失败到上限才放弃，不是一次就死 —— 给瞬时故障留余地。"""
        class FlakyThenBroken(BrokenQueue):
            pass

        pipe = object.__new__(ConfigInMainProcessPipe)
        pipe.config = DemoFile
        pipe.child_id = "child-x"
        pipe.config_set_queue = FlakyThenBroken()
        pipe._closed = False
        pipe.dead = False

        pipe._loop()
        assert pipe.dead is True

    def test_child_loop_marks_dead_when_queue_broken(self):
        cfg = object.__new__(DemoChild)
        cfg.config = {}
        cfg.child_id = "child-x"
        cfg.config_get_queue = BrokenQueue()
        cfg._closed = False
        cfg.dead = False

        cfg._update_config_loop()

        assert cfg.dead is True, "队列坏了却没标记 dead"

    def test_broken_queue_does_not_crash_constructor(self):
        """构造期队列就是坏的：报错，而不是留个半死的对象。"""
        with pytest.raises(RuntimeError):
            DemoChild(BrokenQueue(), BrokenQueue())


# ===========================================================================
# 七、双子进程端到端：A 写、B 收到、A 不重复
# ===========================================================================

def _child_echo_probe(tag, set_q, get_q, report_q, ready_q, go_evt):
    """子进程：只让 tag == "A" 的那个写，两边都记录派发到的键。"""
    class Child(ConfigInChildProcessPipe, DemoKeys):
        ...

    cfg = Child(set_q, get_q)
    hits = []
    cfg.value_changed(lambda key, value: hits.append((key, value)))
    ready_q.put(tag)
    go_evt.wait(10)

    if tag == "A":
        cfg.speed.set(99)

    # 等主进程把这一发广播完
    end = threading.Event()
    end.wait(1.5)
    report_q.put((tag, cfg.child_id, list(hits), cfg.speed.get()))
    cfg.close()


class TestTwoChildrenEndToEnd:

    def test_origin_isolation_between_two_children(self, workdir):
        """A 写一次 → A 只收到 1 次（自己的，回声被丢），B 收到 1 次（别人的）。"""
        cfg = DemoFile("e2e")
        pipes, procs = [], []
        report_q = multiprocessing.Queue()
        ready_q = multiprocessing.Queue()
        go_evt = multiprocessing.Event()

        for tag in ("A", "B"):
            pipe = ConfigInMainProcessPipe(cfg)
            pipes.append(pipe)
            p = multiprocessing.Process(
                target=_child_echo_probe,
                args=(tag, *pipe.get_queues(), report_q, ready_q, go_evt),
            )
            procs.append(p)
            p.start()

        results = {}
        try:
            for _ in range(2):
                ready_q.get(timeout=15)
            go_evt.set()
            for _ in range(2):
                tag, child_id, hits, value = report_q.get(timeout=20)
                results[tag] = (child_id, hits, value)
        finally:
            for p in procs:
                p.join(timeout=15)
            for pipe in pipes:
                pipe.close()

        assert cfg.speed.get() == 99

        id_a, hits_a, value_a = results["A"]
        id_b, hits_b, value_b = results["B"]

        # 两个子进程拿到的是不同的 ID
        assert id_a != id_b

        # A：自己那次乐观写派发了一次；主进程广播回来的回声被丢掉了
        assert hits_a == [("speed", 99)], hits_a
        # B：收到了 A 的写入，一次
        assert hits_b == [("speed", 99)], hits_b

        assert value_a == 99 and value_b == 99
