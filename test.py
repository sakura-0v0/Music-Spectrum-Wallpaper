"""
xiaoe_config_manager 完整测试套件（按 demo.py 的共享声明模式写）

模式：
    class AppConfigP:                          # 纯声明，不继承任何东西
        app_name = default("myapp")
        ...

    class AppConfig(Config, AppConfigP): ...        # 主进程用
    class AppConfigChild(ConfigInChildProcessPipe, AppConfigP): ...  # 子进程用

运行：
    pytest test.py -v
"""
import json
import multiprocessing
import time

import pytest

from xiaoe_config_manager import (
    Config,
    ConfigItemProxy,
    ConfigInMainProcessPipe,
    ConfigInChildProcessPipe,
    default,
)


# ===========================================================================
# 共享配置声明（主/子进程共用）
# ===========================================================================

class AppConfigP:
    """纯声明：只放默认值，供主进程和子进程分别继承。"""
    app_name = default("myapp")
    timeout = default(30)
    debug = default(False)
    id_list = default(None, list)


class AppConfig(Config, AppConfigP):
    """主进程配置类。"""
    ...


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    """切到临时目录，避免污染真实 config 文件。"""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def cfg(workdir):
    return AppConfig(file_name="demo_config")


# ===========================================================================
# 零、声明机制（重点验证 demo.py 模式）
# ===========================================================================

class TestSharedDeclaration:
    def test_main_collects_defaults_from_p(self):
        assert AppConfig.DEFAULTS == {
            "app_name": "myapp",
            "timeout": 30,
            "debug": False,
            "id_list": None,
        }

    def test_main_generates_property_for_each_key(self):
        for key in ("app_name", "timeout", "debug", "id_list"):
            assert isinstance(AppConfig.__dict__.get(key), property), key

    def test_main_and_child_share_identical_defaults(self):
        class AppConfigChild(ConfigInChildProcessPipe, AppConfigP):
            ...

        assert AppConfig.DEFAULTS == AppConfigChild.DEFAULTS

    def test_child_generates_property_for_each_key(self):
        class AppConfigChild2(ConfigInChildProcessPipe, AppConfigP):
            ...

        for key in ("app_name", "timeout", "debug", "id_list"):
            assert isinstance(AppConfigChild2.__dict__.get(key), property), key

    def test_p_base_itself_has_no_property(self):
        # AppConfigP 是纯声明类，不应被 Mixin 处理
        assert not isinstance(AppConfigP.__dict__.get("app_name"), property)


# ===========================================================================
# 一、点操作（重点）
# ===========================================================================

class TestDotGet:
    def test_get_default_values(self, cfg):
        assert cfg.app_name.get() == "myapp"
        assert cfg.timeout.get() == 30
        assert cfg.debug.get() is False
        assert cfg.id_list.get() is None

    def test_returns_config_item_proxy(self, cfg):
        proxy = cfg.app_name
        assert isinstance(proxy, ConfigItemProxy)
        assert repr(proxy) == "<ConfigItemProxy 'app_name'>"

    def test_proxy_is_cached_per_instance(self, cfg):
        assert cfg.app_name is cfg.app_name

    def test_class_attribute_is_property_not_value(self):
        # 类属性被替换为 property，只有实例才返回 ConfigItemProxy
        assert isinstance(AppConfig.__dict__["app_name"], property)


class TestDotSet:
    def test_set_and_get(self, cfg):
        cfg.app_name.set("renamed")
        assert cfg.app_name.get() == "renamed"

    def test_set_persists_to_file(self, cfg):
        cfg.app_name.set("persisted")
        with open("demo_config.json", encoding="utf-8") as f:
            data = json.load(f)
        assert data["app_name"] == "persisted"

    def test_set_visible_across_instances(self, workdir):
        c1 = AppConfig(file_name="shared")
        c1.timeout.set(99)
        c2 = AppConfig(file_name="shared")
        assert c2.timeout.get() == 99

    def test_set_various_value_types(self, cfg):
        cfg.id_list.set([1, 1, 1])
        assert cfg.id_list.get() == [1, 1, 1]
        cfg.debug.set(True)
        assert cfg.debug.get() is True


class TestDotReset:
    def test_reset_single_key(self, cfg):
        cfg.app_name.set("modified")
        cfg.app_name.reset()
        assert cfg.app_name.get() == "myapp"

    def test_reset_persists(self, cfg):
        cfg.app_name.set("modified")
        cfg.app_name.reset()
        with open("demo_config.json", encoding="utf-8") as f:
            data = json.load(f)
        assert data["app_name"] == "myapp"

    def test_reset_only_target_key(self, cfg):
        cfg.app_name.set("a")
        cfg.timeout.set(1)
        cfg.app_name.reset()
        assert cfg.app_name.get() == "myapp"
        assert cfg.timeout.get() == 1


class TestDotCombination:
    def test_full_sequence(self, cfg):
        assert cfg.timeout.get() == 30
        cfg.timeout.set(60)
        assert cfg.timeout.get() == 60
        cfg.timeout.reset()
        assert cfg.timeout.get() == 30

    def test_dot_and_legacy_share_underlying(self, cfg):
        cfg.app_name.set("x")
        assert cfg.configget("app_name") == "x"
        assert cfg.app_name.get() == "x"


# ===========================================================================
# 二、default / 回调
# ===========================================================================

class TestDefaultHelper:
    def test_default_returns_value(self):
        assert default(30) == 30
        assert default(None, list) is None

    def test_default_in_declaration_class(self):
        class P:
            a = default(1)
            b = default(None, list)

        assert P.a == 1
        assert P.b is None


class TestDefaultCallback:
    def test_callback_used_at_init(self, workdir):
        def cb(existing):
            return {"app_name": "cb", "timeout": 5}

        c = AppConfig(file_name="cb", default_config_callback=cb)
        assert c.app_name.get() == "cb"
        assert c.timeout.get() == 5

    def test_callback_disabled_by_flag(self, workdir):
        def cb(existing):
            return {"app_name": "cb"}

        c = AppConfig(
            file_name="cb2",
            default_config_callback=cb,
            init_use_callback=False,
        )
        # 走的是 AppConfigP 里的声明值
        assert c.app_name.get() == "myapp"

    def test_callback_called_on_reset(self, workdir):
        state = {"v": "first"}

        def cb(existing):
            return {"app_name": state["v"]}

        c = AppConfig(file_name="cb3", default_config_callback=cb)
        assert c.app_name.get() == "first"

        state["v"] = "second"
        c.configreset("all")
        assert c.app_name.get() == "second"


# ===========================================================================
# 三、文件交互
# ===========================================================================

class TestFileInteraction:
    def test_extra_keys_in_file_are_preserved(self, workdir):
        with open("extra.json", "w", encoding="utf-8") as f:
            json.dump({"app_name": "user-set", "extra": 1}, f)
        c = AppConfig(file_name="extra")
        assert c.app_name.get() == "user-set"
        assert c.configget("extra") == 1
        assert c.timeout.get() == 30

    def test_missing_defaults_written_back(self, workdir):
        with open("wb.json", "w", encoding="utf-8") as f:
            json.dump({"app_name": "x"}, f)
        AppConfig(file_name="wb")
        with open("wb.json", encoding="utf-8") as f:
            data = json.load(f)
        assert data["timeout"] == 30
        assert data["debug"] is False


# ===========================================================================
# 四、旧方法（少量）
# ===========================================================================

class TestLegacyGet:
    def test_get_single_key(self, cfg):
        assert cfg.configget("app_name") == "myapp"

    def test_get_all_returns_whole_dict(self, cfg):
        assert cfg.configget("all") == {
            "app_name": "myapp",
            "timeout": 30,
            "debug": False,
            "id_list": None,
        }

    def test_get_missing_key_raises(self, cfg):
        with pytest.raises(KeyError):
            cfg.configget("nope")


class TestLegacySetReset:
    def test_set_persists(self, cfg):
        cfg.configset("app_name", "1.2.3.4")
        with open("demo_config.json", encoding="utf-8") as f:
            data = json.load(f)
        assert data["app_name"] == "1.2.3.4"

    def test_reset_single(self, cfg):
        cfg.configset("app_name", "x")
        cfg.configreset("app_name")
        assert cfg.configget("app_name") == "myapp"

    def test_reset_all(self, cfg):
        cfg.configset("app_name", "x")
        cfg.configset("timeout", 1)
        cfg.configreset("all")
        assert cfg.configget("app_name") == "myapp"
        assert cfg.configget("timeout") == 30


class TestUpdateConfig:
    def test_resets_when_value_equals_last_default(self, cfg):
        cfg.configset("app_name_reseted", False)
        cfg.configset("app_name", "old-default")
        cfg.configupdate_config("app_name", last_value="old-default")
        assert cfg.configget("app_name") == "myapp"
        assert cfg.configget("app_name_reseted") is True

    def test_skips_when_user_modified(self, cfg):
        cfg.configset("app_name_reseted", False)
        cfg.configset("app_name", "user-value")
        cfg.configupdate_config("app_name", last_value="old-default")
        assert cfg.configget("app_name") == "user-value"

    def test_skips_when_already_marked_reseted(self, cfg):
        cfg.configset("app_name_reseted", True)
        cfg.configset("app_name", "whatever")
        cfg.configupdate_config("app_name", last_value="whatever")
        assert cfg.configget("app_name") == "whatever"


class TestNewApiProxyAlias:
    def test_alias_methods(self, cfg):
        cfg.set("app_name", "aliased")
        assert cfg.get("app_name") == "aliased"
        cfg.reset("app_name")
        assert cfg.get("app_name") == "myapp"


# ===========================================================================
# 五、多进程 —— 子进程 worker
# ===========================================================================

def _make_child_config(set_q, get_q):
    """按 demo.py 的写法，在子进程里动态创建配置类。"""
    class AppConfigChild(ConfigInChildProcessPipe, AppConfigP):
        ...
    return AppConfigChild(set_q, get_q)


def _child_snapshot(set_q, get_q, ready_evt, result_q):
    cfg = _make_child_config(set_q, get_q)
    ready_evt.set()
    try:
        result_q.put({
            "app_name": cfg.app_name.get(),
            "timeout": cfg.timeout.get(),
            "debug": cfg.debug.get(),
            "id_list": cfg.id_list.get(),
        })
    finally:
        cfg.close()


def _child_get_all_raw(set_q, get_q, ready_evt, result_q):
    cfg = _make_child_config(set_q, get_q)
    ready_evt.set()
    try:
        result_q.put(cfg.configget("all"))
    finally:
        cfg.close()


def _child_set_timeout_and_report(set_q, get_q, ready_evt, result_q):
    cfg = _make_child_config(set_q, get_q)
    ready_evt.set()
    try:
        cfg.timeout.set(60)
        result_q.put(cfg.timeout.get())
    finally:
        cfg.close()


def _child_mix_dot_and_raw(set_q, get_q, ready_evt, result_q):
    cfg = _make_child_config(set_q, get_q)
    ready_evt.set()
    try:
        cfg.app_name.set("from-child")
        cfg.configset("timeout", 42)
        result_q.put({
            "app_name": cfg.app_name.get(),
            "timeout": cfg.configget("timeout"),
        })
    finally:
        cfg.close()


def _child_reset_and_wait(set_q, get_q, ready_evt, result_q,
                          key, expected, timeout=10.0):
    cfg = _make_child_config(set_q, get_q)
    ready_evt.set()
    try:
        cfg.configreset(key)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if cfg.configget(key) == expected:
                break
            time.sleep(0.05)
        result_q.put(cfg.configget(key))
    finally:
        cfg.close()


def _child_wait_for(set_q, get_q, ready_evt, result_q,
                    key, expected, timeout=15.0):
    cfg = _make_child_config(set_q, get_q)
    ready_evt.set()
    try:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if cfg.configget(key) == expected:
                result_q.put(("ok", cfg.configget(key)))
                return
            time.sleep(0.05)
        result_q.put(("timeout", cfg.configget(key)))
    finally:
        cfg.close()


def _child_demo_flow(set_q, get_q, ready_evt, go_evt, result_q):
    """
    复刻 demo.py 的完整流程：
      1. 读初始值
      2. 设置 timeout=60，等主进程处理并广播回来
      3. 等主进程设置 debug=True 并广播回来
      4. 报告最终本地视图
    """
    cfg = _make_child_config(set_q, get_q)
    ready_evt.set()
    try:
        initial = {
            "app_name": cfg.app_name.get(),
            "timeout": cfg.timeout.get(),
            "debug": cfg.debug.get(),
        }

        cfg.timeout.set(60)

        # 等主进程做完它的事（设置 debug）后通知我们继续
        assert go_evt.wait(timeout=10), "主进程未就绪"

        # 等本地缓存更新到最终状态
        deadline = time.time() + 10
        while time.time() < deadline:
            if cfg.timeout.get() == 60 and cfg.debug.get() is True:
                break
            time.sleep(0.05)

        result_q.put({
            "initial": initial,
            "final": {
                "timeout": cfg.timeout.get(),
                "debug": cfg.debug.get(),
            },
        })
    finally:
        cfg.close()


@pytest.fixture
def main_pair(workdir):
    """主进程侧的 (cfg, pipe)，测试结束自动 close。"""
    cfg = AppConfig(file_name="mp_config")
    pipe = ConfigInMainProcessPipe(cfg)
    yield cfg, pipe
    pipe.close()


# ===========================================================================
# 六、多进程 —— 子进程读
# ===========================================================================

class TestChildReads:
    def test_child_reads_initial_config(self, main_pair):
        cfg, pipe = main_pair
        set_q, get_q = pipe.get_queues()
        ready = multiprocessing.Event()
        result_q = multiprocessing.Queue()

        p = multiprocessing.Process(
            target=_child_snapshot, args=(set_q, get_q, ready, result_q)
        )
        p.start()
        try:
            assert ready.wait(timeout=10)
            result = result_q.get(timeout=10)
        finally:
            p.join(timeout=10)

        assert p.exitcode == 0
        assert result == {
            "app_name": "myapp",
            "timeout": 30,
            "debug": False,
            "id_list": None,
        }

    def test_child_get_all_is_none_known_behavior(self, main_pair):
        """子进程 configget('all') 不返回整份配置（已知行为，返回 None）。"""
        cfg, pipe = main_pair
        set_q, get_q = pipe.get_queues()
        ready = multiprocessing.Event()
        result_q = multiprocessing.Queue()

        p = multiprocessing.Process(
            target=_child_get_all_raw, args=(set_q, get_q, ready, result_q)
        )
        p.start()
        try:
            assert ready.wait(timeout=10)
            result = result_q.get(timeout=10)
        finally:
            p.join(timeout=10)

        assert result is None


# ===========================================================================
# 七、多进程 —— 子进程写
# ===========================================================================

class TestChildWrites:
    def test_child_dot_set_propagates_to_main(self, main_pair):
        cfg, pipe = main_pair
        set_q, get_q = pipe.get_queues()
        ready = multiprocessing.Event()
        result_q = multiprocessing.Queue()

        p = multiprocessing.Process(
            target=_child_set_timeout_and_report,
            args=(set_q, get_q, ready, result_q),
        )
        p.start()
        try:
            assert ready.wait(timeout=10)
            child_view = result_q.get(timeout=10)
        finally:
            p.join(timeout=10)

        assert child_view == 60
        assert cfg.timeout.get() == 60

    def test_child_mix_dot_and_raw(self, main_pair):
        cfg, pipe = main_pair
        set_q, get_q = pipe.get_queues()
        ready = multiprocessing.Event()
        result_q = multiprocessing.Queue()

        p = multiprocessing.Process(
            target=_child_mix_dot_and_raw,
            args=(set_q, get_q, ready, result_q),
        )
        p.start()
        try:
            assert ready.wait(timeout=10)
            child_view = result_q.get(timeout=10)
        finally:
            p.join(timeout=10)

        assert child_view == {"app_name": "from-child", "timeout": 42}
        assert cfg.app_name.get() == "from-child"
        assert cfg.timeout.get() == 42

    def test_child_reset_propagates_to_main(self, main_pair):
        cfg, pipe = main_pair
        cfg.configset("app_name", "modified")

        set_q, get_q = pipe.get_queues()
        ready = multiprocessing.Event()
        result_q = multiprocessing.Queue()

        p = multiprocessing.Process(
            target=_child_reset_and_wait,
            args=(set_q, get_q, ready, result_q, "app_name", "myapp"),
        )
        p.start()
        try:
            assert ready.wait(timeout=10)
            child_view = result_q.get(timeout=10)
        finally:
            p.join(timeout=10)

        assert cfg.app_name.get() == "myapp"
        assert child_view == "myapp"


# ===========================================================================
# 八、多进程 —— 主进程广播
# ===========================================================================

class TestMainBroadcast:
    def test_main_change_is_seen_by_child(self, main_pair):
        cfg, pipe = main_pair
        set_q, get_q = pipe.get_queues()
        ready = multiprocessing.Event()
        result_q = multiprocessing.Queue()

        p = multiprocessing.Process(
            target=_child_wait_for,
            args=(set_q, get_q, ready, result_q, "app_name", "broadcast-value"),
        )
        p.start()
        try:
            assert ready.wait(timeout=10)
            cfg.configset("app_name", "broadcast-value")
            status, value = result_q.get(timeout=15)
        finally:
            p.join(timeout=10)

        assert status == "ok"
        assert value == "broadcast-value"

    def test_multiple_children_each_with_own_pipe(self, workdir):
        cfg = AppConfig(file_name="mp_multi")
        result_q = multiprocessing.Queue()

        pipes = []
        processes = []
        ready_events = []
        try:
            for _ in range(2):
                pipe = ConfigInMainProcessPipe(cfg)
                pipes.append(pipe)
                set_q, get_q = pipe.get_queues()
                ready = multiprocessing.Event()
                ready_events.append(ready)
                p = multiprocessing.Process(
                    target=_child_wait_for,
                    args=(set_q, get_q, ready, result_q,
                          "app_name", "broadcast-multi"),
                )
                p.start()
                processes.append(p)

            for ready in ready_events:
                assert ready.wait(timeout=10)

            cfg.configset("app_name", "broadcast-multi")

            results = [result_q.get(timeout=15) for _ in processes]
            for status, value in results:
                assert status == "ok"
                assert value == "broadcast-multi"
        finally:
            for p in processes:
                p.join(timeout=10)
            for pipe in pipes:
                pipe.close()


# ===========================================================================
# 九、多进程 —— 复刻 demo.py 完整流程
# ===========================================================================

class TestDemoFlow:
    def test_full_demo_flow(self, workdir):
        cfg = AppConfig(file_name="demo_config")
        pipe = ConfigInMainProcessPipe(cfg)
        try:
            set_q, get_q = pipe.get_queues()
            ready = multiprocessing.Event()
            go = multiprocessing.Event()
            result_q = multiprocessing.Queue()

            p = multiprocessing.Process(
                target=_child_demo_flow,
                args=(set_q, get_q, ready, go, result_q),
            )
            p.start()

            try:
                # 1) 等子进程就绪
                assert ready.wait(timeout=10)

                # 2) 等主进程侧看到子进程设置的 timeout=60
                deadline = time.time() + 10
                while time.time() < deadline and cfg.timeout.get() != 60:
                    time.sleep(0.05)
                assert cfg.timeout.get() == 60, "子进程的 set 未到达主进程"

                # 3) 主进程改 debug，会广播给所有子进程
                cfg.debug.set(True)

                # 4) 放行子进程，让它读回本地缓存
                go.set()

                result = result_q.get(timeout=15)
            finally:
                p.join(timeout=10)

            assert result["initial"] == {
                "app_name": "myapp",
                "timeout": 30,
                "debug": False,
            }
            assert result["final"]["timeout"] == 60
            assert result["final"]["debug"] is True

            # 主进程侧也确认
            assert cfg.timeout.get() == 60
            assert cfg.debug.get() is True

            # 收尾时主进程可以继续读写
            cfg.id_list.set([1, 1, 1])
            assert cfg.id_list.get() == [1, 1, 1]
        finally:
            pipe.close()


# ===========================================================================
# 十、生命周期
# ===========================================================================

class TestLifecycle:
    def test_main_pipe_close_stops_loop_thread(self, workdir):
        cfg = AppConfig(file_name="mp_life")
        pipe = ConfigInMainProcessPipe(cfg)
        assert pipe._loop_thread.is_alive()
        pipe.close()
        assert not pipe._loop_thread.is_alive()

    def test_child_close_exits_cleanly(self, workdir):
        cfg = AppConfig(file_name="mp_child_life")
        pipe = ConfigInMainProcessPipe(cfg)
        try:
            set_q, get_q = pipe.get_queues()
            ready = multiprocessing.Event()
            result_q = multiprocessing.Queue()
            p = multiprocessing.Process(
                target=_child_snapshot,
                args=(set_q, get_q, ready, result_q),
            )
            p.start()
            assert ready.wait(timeout=10)
            result_q.get(timeout=10)
            p.join(timeout=10)
            assert p.exitcode == 0
        finally:
            pipe.close()