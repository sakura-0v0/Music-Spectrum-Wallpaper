# xiaoe-config-manager

多进程安全的 JSON 配置文件管理器，纯 Python 标准库实现，零外部依赖。

## 特性

- **线程安全** — 内置线程锁，单进程多线程环境下安全读写
- **多进程安全** — 通过 `multiprocessing.Queue` 双向管道实现主进程与子进程之间的配置自动同步
- **点操作 API** — `cfg.app_name.get() / .set(v) / .reset()`，配合 `ConfigItemProxy[T]` 提供完整静态类型检查
- **类型注解友好** — `default()` 自动推断，`ConfigItemProxy[T]` 显式声明，IDE 补全与类型检查全程可用
- **默认配置** — 支持静态默认字典和动态回调两种方式，配置项缺失时自动补齐
- **配置重置** — 支持单个 key 或全部配置一键恢复默认值
- **默认值热更新** — 当默认配置变化时，自动识别用户未修改的项并更新为新默认值
- **纯标准库** — 无任何第三方依赖，仅使用 `json`、`threading`、`multiprocessing` 等标准库

## 安装

```bash
pip install xiaoe-config-manager
```

## 快速开始

### 定义配置类

单进程场景直接继承 `Config`，在类里声明配置项即可。

```python
from xiaoe_config_manager import Config, default

class AppConfig(Config):
    app_name = default("myapp")
    timeout  = default(30)
    debug    = default(False)
    id_list  = default(None, list)
```

### 使用

```python
cfg = AppConfig(file_name="app_config")

# 点操作（推荐）
cfg.app_name.get()          # "myapp"
cfg.timeout.set(60)         # 修改并写文件
cfg.timeout.get()           # 60
cfg.timeout.reset()         # 恢复默认
cfg.timeout.get()           # 30

# 老接口（等价）
cfg.configset("timeout", 60)
cfg.configget("timeout")    # 60
cfg.configget("all")        # 返回全部配置字典
cfg.configreset("all")      # 恢复全部
```

### 三种 API 风格对照

| 风格 | 写 | 读 | 重置 |
|---|---|---|---|
| **点操作**（推荐） | `cfg.timeout.set(60)` | `cfg.timeout.get()` | `cfg.timeout.reset()` |
| 别名 | `cfg.set("timeout", 60)` | `cfg.get("timeout")` | `cfg.reset("timeout")` |
| 老接口 | `cfg.configset("timeout", 60)` | `cfg.configget("timeout")` | `cfg.configreset("timeout")` |

三者操作同一份底层数据，可以混用。`configget("all")` 是唯一只有老接口才有的能力。

## 类型注解

模块所有点操作 API 都支持静态类型检查。下面用几个例子分别说明。

### 方式一：`default()` 自动推断

`default(30)` 类型检查器会看到 `ConfigItemProxy[int]`，链式调用 `.get()` 返回 `int`。

```python
from xiaoe_config_manager import Config, default

class AppConfig(Config):
    timeout  = default(30)          # ConfigItemProxy[int]
    app_name = default("myapp")     # ConfigItemProxy[str]
    debug    = default(False)       # ConfigItemProxy[bool]

cfg = AppConfig(file_name="app")

n: int = cfg.timeout.get()          # ✅ 类型检查通过
cfg.timeout.set(60)                 # ✅ int，通过
cfg.timeout.set("oops")             # ❌ 类型检查报错：期望 int，收到 str
```

### 方式二：`default(None, type)` 声明可空类型

第一个参数为 `None` 时，第二个参数提供类型信息，推断结果为 `ConfigItemProxy[T | None]`。

```python
class AppConfig(Config):
    id_list = default(None, list)     # ConfigItemProxy[list | None]
    mapping = default(None, dict)     # ConfigItemProxy[dict | None]
    name    = default(None, str)      # ConfigItemProxy[str | None]

cfg = AppConfig(file_name="app")

# IDE 会提示 get() 可能是 None，需要判空
value = cfg.id_list.get()             # Optional[list]
if value is not None:
    value.append(1)                    # ✅ 收窄为 list

cfg.id_list.set(None)                  # ✅ None 允许
cfg.id_list.set([1, 2, 3])             # ✅ list 也允许
cfg.id_list.set("oops")                # ❌ 报错
```

### 方式三：显式 `ConfigItemProxy[T]` 注解

需要更精确的类型（例如带元素类型的列表）时，直接写注解。

```python
from xiaoe_config_manager import Config, ConfigItemProxy, default
from typing import Optional

class AppConfig(Config):
    # 更精确的元素类型
    ports:  ConfigItemProxy[list[int]]           = default(None, list)
    names:  ConfigItemProxy[list[str]]           = default(None, list)
    # 可空 + 精确元素类型
    tags:   ConfigItemProxy[Optional[list[str]]] = default(None, list)
    # 字典
    routes: ConfigItemProxy[dict[str, str]]      = default(None, dict)

cfg = AppConfig(file_name="app")
ports = cfg.ports.get()                # Optional[list[int]]
```

### 方式四：省略 `default()` 直接写裸值

也可以只写裸值，运行时行为完全一样，但 IDE 只看到原始类型，点操作的 `.get()` 不会被静态检查。

```python
class AppConfig(Config):
    timeout  = 30                      # IDE 看到的是 int，而非 ConfigItemProxy[int]
    app_name = "myapp"                 # IDE 看到的是 str

cfg = AppConfig(file_name="app")
cfg.timeout.get()                      # 运行时正常，但没有类型检查与补全
cfg.timeout.set("oops")                # 运行时才报错
```

> 推荐始终使用 `default()` 或 `ConfigItemProxy[T]`，让 IDE 全程有提示。

### IDE 补全效果

```python
cfg.timeout.          # 补全：get / set / reset
cfg.app_name.s        # 补全：set
cfg.timeout.get()     # 返回类型：int
```

## 多进程使用

多进程场景下，**主进程持有 `Config` 单例**，每个子进程对应一个 `ConfigInMainProcessPipe`。子进程通过 `ConfigInChildProcessPipe` 与主进程通信。

由于 `ConfigInChildProcessPipe` 不是 `Config` 的子类，主进程和子进程无法从同一个 `Config` 子类继承。此时把**配置声明单独抽成一个纯声明类**（例如 `AppConfigP`），主进程与子进程分别继承它，两边共享同一套键名与类型信息。

### 共享声明 + 主进程 + 子进程

```python
import multiprocessing as mp
from xiaoe_config_manager import (
    Config, ConfigInMainProcessPipe, ConfigInChildProcessPipe, default,
)

# ── 1. 共享声明：只放默认值，不继承任何东西 ──
class AppConfigP:
    workers       = default(4)
    worker_status = default(None, str)
    master_status = default(None, str)

# ── 2. 主进程：Config + 声明 ──
class AppConfig(Config, AppConfigP):
    ...

# ── 3. 子进程：ConfigInChildProcessPipe + 同一份声明 ──
def worker(set_q, get_q):
    class AppConfigChild(ConfigInChildProcessPipe, AppConfigP):
        ...

    cfg = AppConfigChild(set_q, get_q)
    print(cfg.workers.get())              # 4
    cfg.worker_status.set("running")      # 发消息给主进程
    cfg.close()

if __name__ == "__main__":
    # 4. 创建主进程 Config 单例
    cfg = AppConfig(file_name="my_config")

    # 5. 为每个子进程创建主进程端管道
    main_pipe = ConfigInMainProcessPipe(cfg)

    # 6. 拿到队列，传递给子进程
    set_q, get_q = main_pipe.get_queues()

    p = mp.Process(target=worker, args=(set_q, get_q))
    p.start()
    p.join()

    # 7. 主进程可直接读写，改动会广播给所有子进程
    cfg.master_status.set("ok")

    # 8. 收尾
    main_pipe.close()
```

### 子进程

```python
from xiaoe_config_manager import ConfigInChildProcessPipe, default

# 复用同一份共享声明
class AppConfigP:
    workers       = default(4)
    worker_status = default(None, str)

def worker(set_q, get_q):
    class AppConfigChild(ConfigInChildProcessPipe, AppConfigP):
        ...

    cfg = AppConfigChild(set_q, get_q)

    # 读：从本地缓存读，无跨进程开销
    print(cfg.workers.get())              # 4

    # 写：发消息给主进程，由主进程落盘并广播
    cfg.worker_status.set("done")

    # 主进程的修改会自动同步到本地缓存
    # ...

    cfg.close()
```

### 为什么需要 `AppConfigP`

- `ConfigDeclareMixin` 在**每一个继承它的子类**上单独生成点操作属性
- 主进程的 `AppConfig` 与子进程的 `AppConfigChild` 是**两个不同的子类**，各自需要一份声明
- 把声明抽到 `AppConfigP`，一次编写两处继承，键名、默认值、类型注解三方面都不会漂移
- 单进程场景只有一个类，直接 `class AppConfig(Config)` 就够了，不必拆出 `P` 类

### 架构说明

```text
子进程 cfg.set(v) ──→ set_queue ──→ 主进程 _loop() ──→ Config.configset()
                                                          │
                                                          ▼
                                                   config_get_queue
                                                          │
                                                          ▼
                                          子进程 _update_config_loop() 更新本地缓存
```

- 子进程的 `set()` / `reset()` 不直接写文件，通过队列把请求交给主进程
- 主进程统一处理所有写操作和文件 I/O，修改后通过广播队列通知所有子进程
- 子进程的 `get()` 从本地缓存读取，零跨进程开销
- 每个子进程需要**独立的**一对队列（一个 `ConfigInMainProcessPipe` + 一个 `ConfigInChildProcessPipe`）

## 动态默认值

`default_config_callback` 允许在初始化时和重置时动态生成默认值。

```python
from xiaoe_config_manager import Config, default

class AppConfig(Config):
    host         = default("0.0.0.0")
    port         = default(8080)
    hostname     = default(None, str)
    worker_count = default(4)

def dynamic_defaults(current_config):
    """根据当前环境动态生成默认值。"""
    import socket
    return {
        "host":         "0.0.0.0",
        "port":         8080,
        "hostname":     socket.gethostname(),
        "worker_count": 4,
    }

cfg = Config(
    "dynamic_config",
    default_config=AppConfig.DEFAULTS,
    default_config_callback=dynamic_defaults,
    init_use_callback=True,     # 初始化时调用回调
)

# 重置时会再次调用回调，获取最新的默认值
cfg.configreset("all")
```

## API 参考

### Config

核心配置类，管理 JSON 文件的读写。

```python
Config(
    file_name="config",
    default_config=None,
    default_config_callback=None,
    init_use_callback=True,
)
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `file_name` | `str` | `"config"` | 配置文件名，不含 `.json` |
| `default_config` | `dict` | `None` | 默认配置字典，缺失的 key 自动补齐 |
| `default_config_callback` | `Callable` | `None` | 默认配置回调，接受当前 config 字典作为参数，重置时再次调用 |
| `init_use_callback` | `bool` | `True` | 初始化时是否调用回调 |

**方法：**

| 方法 | 说明 |
|------|------|
| `configget(key)` | 获取配置值。`key="all"` 返回全部配置字典 |
| `configset(key, value)` | 设置配置值，自动写文件并广播 |
| `configreset(key)` | 恢复默认值。`key="all"` 恢复全部 |
| `configupdate_config(key, last_value=None)` | 默认值热更新。用户未修改过该 key 时同步为新默认值。需预置 `"{key}_reseted": False` 标记 |
| `update_config()` | 向所有注册的子进程广播当前配置 |

### ConfigItemProxy[T]

配置项代理，点操作 API 的核心类型。

| 方法 | 说明 |
|------|------|
| `get() -> T` | 获取该配置项的值 |
| `set(value: T) -> None` | 修改该配置项 |
| `reset() -> None` | 恢复该配置项为默认值 |

由 `ConfigDeclareMixin` 通过类属性自动生成，不能在代码里手动实例化。

### default

声明默认值的辅助函数，也承担类型推断的职责。

```python
default(30)              # 推断为 ConfigItemProxy[int]
default("myapp")         # 推断为 ConfigItemProxy[str]
default(None, list)      # 推断为 ConfigItemProxy[list | None]
default(None, dict)      # 推断为 ConfigItemProxy[dict | None]
```

运行时行为：直接返回传入的 `value`（`type_` 参数仅用于类型推断）。

### ConfigInMainProcessPipe

主进程管道接口，每个子进程对应创建一个实例。

```python
ConfigInMainProcessPipe(config: Config)
```

| 方法 | 说明 |
|------|------|
| `get_queues()` | 返回 `(set_queue, get_queue)` 元组，传递给子进程 |
| `on_remote_change(cb)` | 注册"**别的进程**改了配置"的回调，`cb(key, value)`。只在子进程写进来时触发 |
| `off_remote_change(cb)` | 取消注册（同一个函数引用） |
| `close()` | 关闭管道，停止监听线程 |

### ConfigInChildProcessPipe

子进程配置工具，通过队列与主进程通信。

```python
ConfigInChildProcessPipe(config_set_queue, config_get_queue)
```

| 方法 | 说明 |
|------|------|
| `configget(key)` | 从本地缓存读取配置值 |
| `configset(key, value)` | 修改配置（乐观：先改本地缓存，消息发给主进程落盘+广播） |
| `configreset(key)` | 恢复默认值（只发消息 —— 本地缓存要等广播回来才变） |
| `on_remote_change(cb)` | 注册"**别的进程**改了配置"的回调，`cb(key, value)`。只在主进程广播下来时触发 |
| `off_remote_change(cb)` | 取消注册（同一个函数引用） |
| `close()` | 关闭管道，停止同步线程 |

继承 `ConfigDeclareMixin`，所以配合声明类使用后自动获得点操作 API（`cfg.xxx.get()` 等）。

### 变更通知：`on_remote_change`（2.0.1 起）

管道搬数据是**静默**的（子进程收到广播时是整份替换本地缓存），谁也不知道"配置变了"。
`on_remote_change` 就是那个通知点：

```python
# 主进程
pipe = ConfigInMainProcessPipe(cfg)
pipe.on_remote_change(lambda key, value: print("子进程改了", key, "=", value))

# 子进程
cfg = ConfigInChildProcessPipe(set_q, get_q)
cfg.on_remote_change(lambda key, value: print("主进程改了", key, "=", value))
```

契约（三条，都和"直觉"不太一样，所以写清楚）：

1. **只报"别的进程改的"**。自己写的那一发不报 —— 谁写谁知道。主进程本地写不走这里，
   子进程乐观写也不走这里。
2. **整份广播按逐键 diff 报**，只报真的变了的键。子进程写出去又广播回来的那发**回声**
   正好被 diff 吞掉，所以**不会双发**。
3. **回调跑在管道自己的线程上**（主进程是 `_loop` 线程，子进程是 `_update_config_loop` 线程）。
   要在 Qt 里更新界面，请把它接到
   `xiaoe_ui.ConfigBridge.notify_change` —— 桥会把回调排队回桥所在线程：

   ```python
   pipe.on_remote_change(show_cfg.notify_change)
   ```

   （同样地，**接收端必须跑事件循环**，否则排队的通知送不到。）

## 注意事项

1. **多进程环境下请保持 `Config` 单例** — 多个 `Config` 实例同时操作同一文件会导致数据不一致
2. **子进程的 `ConfigInChildProcessPipe` 不直接写文件** — 所有写操作会发送请求，由主进程统一处理
3. **多进程场景推荐使用共享声明类模式** — 把配置声明抽到 `AppConfigP`，主进程与子进程各自继承，避免两边维护两份键名
4. **单进程场景直接继承 `Config`** — 无需拆分 `AppConfigP`，一个类即可
5. **使用完毕后调用 `close()`** — 避免守护线程未正常退出
6. **文件名不含 `.json` 后缀** — 传入 `"myconfig"` 对应 `myconfig.json`
7. **子进程的 `configget('all')` 当前不返回整份配置** — 需要整份配置时请通过具体的 key 逐个读取，或改用主进程侧读取

## 许可证

MIT