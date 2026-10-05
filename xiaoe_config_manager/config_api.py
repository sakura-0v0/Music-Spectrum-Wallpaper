from abc import ABC, abstractmethod
from typing import Any

class NewConfigApiProxy:
    """
    新增get、set、reset方法，转发到原版的方法。
    """
    def get(self, key):
        """获取设置 in:key out:value"""
        return self.configget(key)
    def set(self, key, value):
        """修改设置"""
        return self.configset(key, value)
    def reset(self, key):
        """恢复默认设置"""
        return self.configreset(key)


class ConfigApi(ABC):
    """配置操作抽象基类。

    定义配置读写的统一接口，由 Config（主进程直接实现）和
    ConfigInChildProcessPipe（子进程通过管道实现）分别继承实现。
    """

    @abstractmethod
    def get(self, key: str) -> Any:
        """获取配置值。

        Args:
            key: 配置键；传入 "all" 时返回全部配置字典。

        Returns:
            对应配置项的值；key 为 "all" 时返回完整配置字典。
        """
        raise NotImplementedError

    @abstractmethod
    def set(self, key: str, value: Any) -> None:
        """设置配置值。

        Args:
            key: 配置键。
            value: 配置值。
        """
        raise NotImplementedError

    @abstractmethod
    def reset(self, key: str) -> None:
        """恢复配置为默认值。

        Args:
            key: 配置键；传入 "all" 时恢复全部配置为默认值。
        """
        raise NotImplementedError

    @abstractmethod
    def configget(self, key: str) -> Any:
        """获取配置值。

        Args:
            key: 配置键；传入 "all" 时返回全部配置字典。

        Returns:
            对应配置项的值；key 为 "all" 时返回完整配置字典。
        """
        raise NotImplementedError

    @abstractmethod
    def configset(self, key: str, value: Any) -> None:
        """设置配置值。

        Args:
            key: 配置键。
            value: 配置值。
        """
        raise NotImplementedError

    @abstractmethod
    def configreset(self, key: str) -> None:
        """恢复配置为默认值。

        Args:
            key: 配置键；传入 "all" 时恢复全部配置为默认值。
        """
        raise NotImplementedError
