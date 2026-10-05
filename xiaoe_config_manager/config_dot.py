from typing import Generic, TypeVar, overload, Any, Optional

T = TypeVar("T")

def _make_proxy_property(key: str) -> property:
    def getter(self) -> "ConfigItemProxy":
        return self._get_config_proxy(key)
    return property(getter, doc=f"配置项 {key!r}")



class ConfigDeclareMixin:
    """让子类通过类属性声明配置键。

        class AppConfig(Config):
            app_name = "aaaaa"              # 运行时可用
            # 或
            app_name: ConfigItemProxy = "aaaaa"   # IDE 有提示

        cfg = AppConfig(file_name='aaaa')
        cfg.app_name.get()   # "aaaaa"
    """
    DEFAULTS: dict = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        defaults = {}
        seen = set()

        # 先收集继承来的 DEFAULTS（父类已经处理成 property 的）
        for base in reversed(cls.__mro__[1:]):
            if base is object:
                continue
            for k, v in (base.__dict__.get("DEFAULTS") or {}).items():
                defaults.setdefault(k, v)

        # 再扫 MRO 上每个类自己的 __dict__
        for base in cls.__mro__:
            if base is object or base is ConfigDeclareMixin:
                continue
            for attr, default in list(vars(base).items()):
                if attr.startswith("_") or attr == "DEFAULTS" or attr in seen:
                    continue
                if callable(default) or isinstance(
                        default, (property, staticmethod, classmethod)
                ):
                    continue
                seen.add(attr)
                defaults[attr] = default

        # 只把 property 设在当前 cls 上，不动父类
        for k in seen:
            setattr(cls, k, _make_proxy_property(k))

        cls.DEFAULTS = defaults

    def _get_config_proxy(self, key: str) -> "ConfigItemProxy":
        cache = self.__dict__.setdefault("_config_proxies", {})
        if key not in cache:
            cache[key] = ConfigItemProxy(self, key)
        return cache[key]

class ConfigItemProxy(Generic[T]):
    """配置项代理：`config.xxx.get/set/reset()`。"""

    __slots__ = ("_config", "_key")

    def __init__(self, config: "ConfigApi", key: str):
        self._config = config
        self._key = key

    def get(self) -> T:
        """
        获取该配置的值
        """
        return self._config.configget(self._key)

    def set(self, value: T) -> None:
        """
        更改该配置的值
        """
        self._config.configset(self._key, value)

    def reset(self) -> None:
        """
        重置该配置的值
        """
        self._config.configreset(self._key)

    def __repr__(self) -> str:
        return f"<ConfigItemProxy {self._key!r}>"


@overload
def default(value: T) -> "ConfigItemProxy[T]": ...
@overload
def default(value: None, type_: "type[T] | T") -> "ConfigItemProxy[T | None]": ...


def default(value: Any = None, type_: Any = None) -> Any:
    """声明配置项的默认值。

    两种写法：
        timeout = default(30)            # 自动推断 ConfigItemProxy[int]
        id_list = default(None, list)    # 显式: ConfigItemProxy[list | None]
    """
    return value