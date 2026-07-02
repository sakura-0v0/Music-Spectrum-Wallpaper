"""
多进程安全配置管理模块

包含：
- Config 类：配置文件核心操作（可以单独使用，也可以配合 ConfigInMainProcessPipe 和 ConfigInChildProcessPipe 使用）
- ConfigInMainProcessPipe 类：主进程管道接口(使用with或结束时调用close())
- ConfigInChildProcessPipe 类：子进程操作工具(使用with或结束时调用close())
"""
from .config import Config
from .config_multiprocess import ConfigInMainProcessPipe, ConfigInChildProcessPipe