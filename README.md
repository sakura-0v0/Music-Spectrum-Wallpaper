# xiaoe-config-manager

多进程安全的 JSON 配置文件管理器，纯 Python 标准库实现，零依赖。配置值常驻进程内存，读写线程安全，落盘是原子替换，子进程通过队列自动同步。

## 一套接口，三个后端

这个包里有三个类，用法几乎一样：都是先写一个声明式的配置类，再把类接上，然后 `cfg.字段.get()` / `.set()` / `.reset()`。

| 类                          | 值存在哪               | 单键读的开销  |
|----------------------------|--------------------|---------|
| `Config`                   | 进程内存，写时落盘到 JSON 文件 | 读内存     |
| `ConfigMemory`             | 进程内存里的 dict        | 读内存     |
| `ConfigInChildProcessPipe` | 子进程内存缓存，由主进程广播刷新   | 本进程内读内存 |

```python
from xiaoe_config_manager import (
    Config, ConfigMemory, ConfigInChildProcessPipe, ConfigKeysBase, default,
)

class AppKeys(ConfigKeysBase):
    """共用的Key类"""
    app_name = default("myapp")
    timeout  = default(30)

class AppConfig(Config, AppKeys): ... # 组合
class AppMemory(ConfigMemory, AppKeys): ...  # 组合

cfg = AppConfig("app")                      # 落盘到 app.json
cfg.timeout.get()       # 30

mem = AppMemory()        # 只在内存里
mem.timeout.set(60)      # 只改内存

# 子进程中，将主进程管道生成的(set_q, get_q)传入。
child = ConfigInChildProcessPipe(set_q, get_q)   # 子进程里，自动和主进程同步
child.app_name.get()    # 读本地缓存，不跨进程
child.app_name.set("app_1")  # 自动广播到全部进程，开销较大但是可以接受
```

## 读操作都在内存里

除 `get('all')` 外，所有读都直接取当前进程内存里的副本。界面刷新、事件回调这类每秒几百次的路径可以放心读。

程序跑起来之后，手动改 `<name>.json` 不会生效。文件版如果确实需要重读，调用 `cfg.get("all")` 即可从文件重读。

## 安装

```bash
pip install xiaoe-config-manager
```

要求 Python 3.10 以上。

## 快速开始

声明Keys类，与Config类组合并实例化：

```python
from xiaoe_config_manager import Config, ConfigKeysBase, default

class AppKeys(ConfigKeysBase):
    app_name = default("myapp")
    timeout  = default(30)
    debug    = default(False)
    id_list  = default(None, list)

class AppConfig(Config, AppKeys):
    ...

cfg = AppConfig(file_name="app_config")

cfg.app_name.get()      # "myapp"
cfg.timeout.set(60)     # 改内存并安排落盘
cfg.timeout.get()       # 60
cfg.timeout.reset()     # 恢复默认
cfg.flush()             # 立刻落盘，不等定时器
```

### 点键访问和直接调用

声明过的键可以直接 `cfg.字段`，也可以走 `cfg.get("字段")`。两种写法操作的是同一份数据，可以混用。

| 写法 | 读 | 写 | 重置 |
|---|---|---|---|
| 点键访问 | `cfg.timeout.get()` | `cfg.timeout.set(60)` | `cfg.timeout.reset()` |
| 传键名 | `cfg.get("timeout")` | `cfg.set("timeout", 60)` | `cfg.reset("timeout")` |
| 显式句柄 | `cfg.item("timeout").get()` | `cfg.item("timeout").set(60)` | `cfg.item("timeout").reset()` |

`get("all")` 从文件中重读整份配置，`reset("all")` 重置整份。

> 旧名字 `configget` / `configset` / `configreset` 也还能用，它们内部转给 `get` / `set` / `reset`，行为完全一样，但**不建议在新代码里使用**。实现新的后端时覆写 `get` / `set` / `reset` 即可，不要覆写旧名字。

### 命名与扫描规则

1. 只收集 `ConfigKeysBase` 的子类，以及实现类自己的类体。
2. 默认值必须是 `str`、`int`、`float`、`bool`、`list`、`dict`、`None` 之一，其它一律在类创建时抛 `TypeError`。判据是「它能不能当一个配置值」，不是猜作者想干嘛。类体里的方法、嵌套类、模块，以及下划线开头的名字，属于本来就不是配置项的东西，直接跳过，不算违规。
3. 键名撞了保留字会当场抛 `TypeError`，不会静默跳过。检查分两层：先看固定清单（`config`、`fname`、`queues`、`default_config`、`item`、`memory`、`DEFAULTS`、`all` 等），再动态查实现类 MRO 上已有的属性名，所以 `get`、`set`、`on` 这些方法名同样不能当键名。`all` 尤其特殊：它是 `get('all')` 和 `reset('all')` 专用的键名。
4. 一条继承链上重复声明同一个键会抛 `TypeError`。兄弟基类同名不拦，按 MRO 走，优先取左。

```python
class ParentKeys(ConfigKeysBase):
    app_name = default("p")

class ChildKeys(ParentKeys):
    app_name = default("c")      # TypeError：继承链上已经有这个键

class Broken(ConfigKeysBase):
    pair = (1, 2)                # TypeError：tuple 不是配置值
    _RETRY = (1, 2, 3)           # 下划线开头，跳过，不报错
    def helper(self): ...        # 方法，跳过，不报错
```

> `tuple` 不在允许清单里。它写进 JSON 会退化成 `list`，读回来类型就变了，不如在声明时就拦下。

## 类型注解

`default()` 会推断类型，让 IDE 和类型检查器认得 `.get()` 的返回值和 `.set()` 的参数：

```python
class AppKeys(ConfigKeysBase):
    timeout  = default(30)          # ConfigItemProxy[int]
    app_name = default("myapp")     # ConfigItemProxy[str]
    id_list  = default(None, list)  # ConfigItemProxy[list | None]

n: int = cfg.timeout.get()          # 通过
cfg.timeout.set(60)                 # 通过
cfg.timeout.set("oops")             # 类型检查报错
```

`default(None, type)` 表示可空，第二个参数提供类型。元素类型也要精确时可以写注解：

```python
from typing import Optional

class AppKeys(ConfigKeysBase):
    ports: ConfigItemProxy[list[int]]           = default(None, list)
    tags:  ConfigItemProxy[Optional[list[str]]] = default(None, list)
```

也可以只写裸值（`timeout = 30`），运行时行为完全一样，但点键访问就没有静态检查了。

建议始终用 `default()`。

## 订阅与通知

```python
cfg.on("timeout", lambda v: print("变了", v))       # 单键
cfg.value_changed(lambda k, v: print(k, v))         # 所有键
cfg.off("timeout", 回调)                            # 取消单键，要同一个函数引用
cfg.off_value_changed(回调)                         # 取消全键
```

`off` 和 `off_value_changed` 的取向一致：注销一个没注册过的回调抛 `ValueError`。例外是键本身从未出现过，`off` 对这种情况直接返回。

通知怎么来的，分几种情况：

| 场景                     | 派发方式                                          |
|------------------------|-----------------------------------------------|
| 本进程 `set`              | 当场派发，`set` 返回时值已生效                            |
| 本进程 `reset`（文件版 / 内存版） | 当场派发新值，`reset` 返回时监听器已经跑完                      |
| 本进程 `reset`（子进程管道）     | **不**当场派发；`RESET` 广播到达时才派发一次，派发的是正确的新值         |
| `reset("all")`         | 派发一次 `("all", 整份 dict)`，三个后端一致                 |
| 别的进程改了                 | 主进程只发变了的那个键，子进程更新本地缓存后派发它                     |
| 自己写出去又广播回来的回声          | `set` 的回声不派发（缓存早已乐观写过）；`reset` 的回声要派发（见下）    |

三个后端的**派发次数和内容完全一致**：一次写就是一次通知，哪怕值没变，哪怕别人写了个和自己相同的值。子进程靠消息里的 `origin`（发起者 ID）忽略set自己的回声。

> **管道里的 `reset` 是异步的**：`cfg.reset("speed")` 返回时，监听器**还没被调用**，因为本地缓存要等主进程把新值广播回来才更新。文件版和内存版则是同步的，`reset` 返回时监听器已经跑完了。
>
> 不要写这种断言：
>
> ```python
> cfg.reset("speed") # ConfigInChildProcessPipe 实例
> assert hits == [50]        # ❌ 管道里此时 hits 还是空的，需等一小段时间。
> ```
>
> 要么等通知（在回调里继续），要么轮询到值变了为止。`set` 不受影响 —— 它是乐观写，返回时值已生效、通知也已派发。
>
> 为什么 `reset` 不干脆当场派发旧值：那会让监听器收到"旧值 → 新值"两次通知，和另两个后端的"一次重置一次通知"就对不上了。

派发点只有 `ConfigBase._dispatch` 一处。要接管通知（比如 Qt 把回调排队回自己的线程），重写这一个方法就够了，不要在别处另发通知。

单个回调抛异常不会影响别的回调，也不会冒给 `set` / `reset` 的调用方。异常会打一份堆栈后继续，走的是 `traceback.print_exc()`，所以 `sys.excepthook` 收不到这份。打包成 `console=False` 之后 stderr 是空的，想在发行版里看见，就重写 `_report_listener_error(key, callback)` 接到自己的错误上报里。

## 数据安全

**坏文件就报错，不覆盖。** `Config(...)` 只把 `FileNotFoundError` 当成"第一次运行、还没有文件"。文件损坏、编码不对、没有权限，一律原样抛出，此时文件一个字节都不会变，也不会留下临时文件：

```python
# app.json 里是 "{ 这不是 JSON "
Config("app", default_config={"a": 1})
# json.JSONDecodeError: Expecting property name enclosed in double quotes: ...
```

**落盘是延迟加原子写。** `set` 只改内存并重置一个 `save_delay` 秒（默认 0.5）的定时器，窗口内多次写只落盘一次。真正写文件时先写一个唯一命名的临时文件，再 `os.replace` 替换，替换遇到 Windows 上常见的瞬时 `PermissionError` 会退避重试。
如果直接以 `'w'` 打开原文件写，一旦序列化失败就会把文件截断成半截。

`reset`、`get('all')`、`flush()` 和进程正常退出（`atexit`）都会强制把待落盘的改动写出去。`flush()` 幂等，退出前、交给外部工具读之前、fork 之前都值得调一次。进程被强杀时 `atexit` 不跑，窗口内的改动会丢。

## 多进程

多进程场景下，主进程持有 `Config` 单例，每个子进程在主进程侧对应一个 `ConfigInMainProcessPipe`，子进程自己用 `ConfigInChildProcessPipe` 通信。

```python
import multiprocessing as mp
import threading

from xiaoe_config_manager import (
    Config, ConfigInMainProcessPipe, ConfigInChildProcessPipe,
    ConfigKeysBase, default,
)

class AppKeys(ConfigKeysBase):
    """主进程和子进程共用同一份声明。"""
    workers       = default(4)
    worker_status = default(None, str)
    master_status = default(None, str)


def worker(set_q, get_q):

    class AppConfigChild(ConfigInChildProcessPipe, AppKeys):  # 子进程中组合 Config、Keys
        ...

    # 子进程中使用传入的管道创建子进程配置实例，接口、对外行为、用法几乎与主进程的Config类一致
    cfg = AppConfigChild(set_q, get_q)
    print("子进程读到 workers =", cfg.workers.get())

    got_ok = threading.Event()

    def on_master(value):
        print("子进程收到 master_status =", value)
        got_ok.set()                      # 回调里放行主线程

    cfg.master_status.on(on_master)        # 主进程写 master_status 时回调这里

    cfg.worker_status.set("running")       # 乐观写：本地立即生效，再同步给主进程

    if not got_ok.wait(timeout=5):         # 等回调，不轮询
        print("子进程等 master_status 超时")

    cfg.close()

if __name__ == "__main__":

    class AppConfig(Config, AppKeys):... # 主进程中组合Config、Keys
    cfg = AppConfig(file_name="my_config") # 主进程中持Config单例，负责统一处理文件、广播

    got_running = threading.Event()

    def on_worker(value):
        print("主进程收到 worker_status =", value)
        got_running.set()                  # 回调里放行主线程

    cfg.worker_status.on(on_worker)        # 子进程写 worker_status 时回调这里

    main_pipe = ConfigInMainProcessPipe(cfg)    # 为每个子进程一个MainProcessPipe

    # 获取管道并传给子进程
    set_q, get_q = main_pipe.get_queues()

    p = mp.Process(target=worker, args=(set_q, get_q))
    p.start()

    if not got_running.wait(timeout=5):    # 等回调，不轮询
        print("主进程等 worker_status 超时")

    cfg.master_status.set("ok")             # 当场派发，并广播给所有子进程
    p.join()

    print("主进程最终配置 =", cfg.get("all"))
    main_pipe.close()
```

子进程中set一个配置时的数据流：

```text
子进程 set(v) ──→ 改自己的副本 ──→ set_queue ──→ 主进程 _loop() ──→ Config.set()
                                                                     │
                                                                     ▼
                                                    get_queue（只发这一个键）
                                                                     │
                                                                     ▼
                                                 子进程改本地缓存 → 派发这一个键
```

子进程的 `set` 不写文件，把请求交给主进程；`reset` 同样只发消息。主进程统一处理所有写和文件 IO，改完把**变了的那个键**发给所有子进程。子进程的 `get` 读本地缓存，没有跨进程开销。每个子进程需要独立的一对队列，也就是一个 `ConfigInMainProcessPipe` 配一个 `ConfigInChildProcessPipe`。

只有两种时候会传整份配置：子进程启动时向主进程要一份（拉取），以及 `reset("all")` 之后键集合整体变了、没法只发一个键（推送）。其余时候线上跑的都只有一个键。

子进程构造时会向主进程要一份完整配置并等它回来，等 30 秒还没到就抛 `RuntimeError`，通常意味着主进程的 `ConfigInMainProcessPipe` 还没起来，或者管道对象传错了。

用完记得调 `close()`：主进程和子进程两侧都要调，否则守护线程不会正常退出。

## 内存版

内存版（ConfigMemory）和文件版（Config类）的api、对外行为、用法几乎一致，区别就是没有文件读写。

当然，你也可以接入`ConfigInMainProcessPipe`+`ConfigInChildProcessPipe`实现内存配置的多进程同步。

```python
from xiaoe_config_manager import ConfigKeysBase, ConfigMemory, default

class AppKeys(ConfigKeysBase):
    enable = default(False)
    speed  = default(50)

class AppMemory(ConfigMemory, AppKeys):
    ...

mem = AppMemory()               # 用声明里的默认值
mem.speed.get()                 # 50
mem.speed.set(60)               # 只改内存
mem.speed.reset()               # 回到 50

mem2 = AppMemory({"speed": 99}) # 一份 dict 盖在声明默认值上面，同时是 reset 目标
```

## 动态默认值

`default_config_callback` 让你在初始化和重置时动态生成默认值：

```python
import socket
from xiaoe_config_manager import Config

def dynamic_defaults(current_config):
    return {
        "host":         "0.0.0.0",
        "port":         8080,
        "hostname":     socket.gethostname(),
        "worker_count": 4,
    }

cfg = Config(
    "dynamic_config",
    default_config={"host": "0.0.0.0", "port": 8080,
                    "hostname": "", "worker_count": 4},
    default_config_callback=dynamic_defaults,
    init_use_callback=True,
)

cfg.reset("all")    # 重置时会重新调用回调
```

初始化时默认值的优先级是：`default_config_callback`（仅当 `init_use_callback=True`）高于 `default_config`，`default_config` 高于类声明的 `DEFAULTS`。也就是说，显式传了 `default_config` 时声明里的默认值不参与，要合并请自己合。

## API 参考

### ConfigApi

三个后端的统一接口（Config、ConfigInChildProcessPipe、ConfigMemory）。

| 成员 | 说明 |
|---|---|
| `get(key)` | 读一个键，`key="all"` 返回整份 dict，缺键抛 `KeyError`，返回值是深拷贝 |
| `set(key, value)` | 写一个键，存的是深拷贝。返回时值已生效。`key="all"` 抛 `TypeError` |
| `reset(key)` | 恢复默认值，`key="all"` 恢复全部 |
| `on(key, cb)` / `off(key, cb)` | 单键订阅，回调签名 `(value)` |
| `value_changed(cb)` / `off_value_changed(cb)` | 全键订阅，回调签名 `(key, value)` |

### ConfigBase

行为层，模板方法、订阅、锁、广播、唯一派发点都在这里。`Config` 和 `ConfigMemory` 是它的平级子类，子进程管道也继承它。

子类只需要实现五个方法：`_read`、`_read_all`、`_write`、`_apply_reset`、`_save`（内存版和管道的 `_save` 是空实现）。`set` 和 `reset` 负责加锁、调这些方法、落盘广播、解锁、派发，所以"写完必须派发一次"这条纪律只有一处实现。

| 方法 | 说明 |
|---|---|
| `_dispatch(key, value)` | 唯一派发点，要接管通知就重写它 |
| `memory(defaults=None)` | 类方法，造一个内存版的自己，见「内存版」 |
| `update_config()` | 把当前配置推给所有注册过的子进程队列 |
| `configupdate_config(key, last_value=None)` | 默认值热更新，用户没改过该键时同步成新默认值。需要预置 `"{key}_reseted": False` 标记，缺了抛 `KeyError` |
| `item(key)` | 取一个显式字段句柄 |

### Config

```python
Config(
    file_name="config",
    default_config=None,
    default_config_callback=None,
    init_use_callback=True,
    save_delay=0.5,
    save_on_exit=True,
)
```

| 参数 | 说明 |
|---|---|
| `file_name` | 配置文件名，不含 `.json` |
| `default_config` | 静态默认值，缺失的键自动补齐 |
| `default_config_callback` | 动态默认值回调，参数是当前配置，重置时再次调用 |
| `init_use_callback` | 初始化时是否用回调拿默认值 |
| `save_delay` | `set` 后延迟多少秒落盘，窗口内多次写合并成一次。`<= 0` 表示每次立即写 |
| `save_on_exit` | 是否注册 `atexit`，进程正常退出时自动 flush |

行为要点：

- 构造时只捕 `FileNotFoundError`，其余异常上抛，坏文件不被覆盖
- 缺的键自动补进文件，只补缺的，不覆盖已有的
- `set` 延迟落盘，`reset` 立即落盘（写失败会打堆栈、保留待写标记，下次 flush 重试）
- `get('all')` 先 flush 再重读文件，等于强制同步一次
- `path` 是 `"<file_name>.json"`，父目录必须已存在，这个类不建目录

### ConfigMemory

| 项 | 说明                        |
|---|---------------------------|
| `ConfigMemory(default_config=None)` | 配置初始值                     |
| `get(缺键)` / `reset(缺键)` | 抛 `KeyError`，与文件版一致       |
| `get('all')` | 返回整份配置的深拷贝                |
| `set(key, value)` | `key="all"` 抛 `TypeError` |

### ConfigKeysBase / ConfigDeclareMixin / ConfigItemProxy

| 名字 | 说明 |
|---|---|
| `ConfigKeysBase` | 纯声明基类，`DEFAULTS` 是普通 dict，任何后端都能消费 |
| `ConfigDeclareMixin` | 把声明键做成实例上的 property，`ConfigBase` 已继承 |
| `ConfigItemProxy[T]` | 字段句柄，有 `.get()` / `.set(v)` / `.reset()` / `.on(cb)` / `.off(cb)` 和 `.key` |
| `collect_defaults(cls)` | 扫出一个类认哪些键、默认值各是多少 |
| `default(value)` / `default(None, type_)` | 声明默认值，同时承担类型推断 |

`ConfigItemProxy` 由 `ConfigDeclareMixin` 自动生成，不要手动实例化。

### ConfigInMainProcessPipe

主进程侧的管道口，每个子进程创建一个。

| 成员 | 说明 |
|---|---|
| `child_id` | 分配给这个子进程的 ID（`"child-1"`、`"child-2"`……） |
| `get_queues()` | 返回 `(set_queue, get_queue)`，传给子进程 |
| `close()` | 停止监听线程并注销队列 |

它把队列注册进 `config.queues`，于是主进程每次 `set` 都会自动广播。收到子进程消息后直接调 `config.set` / `config.reset`，通知由配置对象自己发，这里不再另发。

`child_id` 不用额外传参：子进程构造时会用 `GETALL` 向主进程要一份初始配置，主进程在同一条回复里把 ID 一起给它。所以 `get_queues()` 和构造签名都没变。

### ConfigInChildProcessPipe

```python
ConfigInChildProcessPipe(config_set_queue, config_get_queue)
```

| 方法 | 说明 |
|---|---|
| `child_id` | 主进程分配的 ID，构造时领到；发消息时带上，用于识别回声 |
| `get(key)` | 读本地缓存，缺键抛 `KeyError` |
| `get("all")` | 本地整份配置的副本，是最近一次广播的快照 |
| `set(key, value)` | 乐观写，先改本地缓存再发消息 |
| `reset(key)` | 悲观重置，只发消息，本地缓存等广播回来才变；通知也在那时才发（见「订阅与通知」） |
| `on` / `off` / `value_changed` / `off_value_changed` | 订阅，跨进程变更自动派发到这里 |
| `close()` | 停止同步线程 |

`get("all")` 是快照而不是实时值：自己刚 `set` 的一定在，别的进程刚写的可能还没到。要严格最新就回主进程读。

## 注意事项

**进程模型**

- 同一个配置文件必须对应一个 `Config` 单例，多个实例同时写同一个文件会互相覆盖
- 每个子进程要独立的一对队列
- 主进程和子进程两侧的管道对象用完都要 `close()`
- 文件名不带 `.json`，父目录要先自己建

**落盘与读取**

- `set` 返回时值只在内存里，要保证已经进文件就调 `flush()`。强杀进程时 `atexit` 不跑，窗口内的改动会丢
- 程序运行期间手改配置文件不生效，记住这一条能省很多排查时间
- 子进程的 `get('all')` 是最近一次广播的快照，要实时值就回主进程读
- 子进程 `reset()` 返回时通知还没发，别在它后面立刻断言回调已经跑过

**键名**

- 声明键名别用方法名和框架内部属性名，撞了会在类创建时抛 `TypeError`
- 没声明的键走 `cfg.item("键名")`，`all` 除外

## 许可证

MIT
