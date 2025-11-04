import sys
import os


def get_res_path(relative_path):
    """获取适配打包环境和开发环境的资源绝对路径"""
    if getattr(sys, 'frozen', False):
        # 打包后sys._MEIPASS指向临时解压目录
        base_path = sys._MEIPASS
    else:
        # 开发环境取项目根目录（假设本文件在项目根目录的utils目录）
        base_path = os.path.dirname(os.path.abspath(__file__))

    # 拼接规范化的完整路径
    full_path = os.path.normpath(os.path.join(base_path, relative_path))
    # 可选验证路径是否存在
    if not os.path.exists(full_path):
        raise FileNotFoundError(f"资源路径不存在：{full_path}")
    print(f"资源路径：{full_path}")
    return full_path