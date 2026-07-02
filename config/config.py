import copy
import json
import threading
from typing import Callable


class Config:
    """
    如果多进程环境下，请保持单例模式。
    """
    def __init__(self,file_name='config' ,default_config: dict = None,
                 default_config_callback: Callable =None, init_use_callback : bool =True,):
        """
        初始化配置
        Args:
            file_name: 配置文件名
            default_config: 默认配置(如果配置项多出，则会自动添加)
            default_config_callback: 默认配置回调函数(重置时可动态获取默认配置)
            init_use_callback: 是否在初始化时使用回调函数获取默认配置
        """
        self.fname = file_name
        self.queues = []# 当配置被修改时，向所有队列发送配置
        self.default_config = default_config
        self.default_config_callback = default_config_callback
        self.config_lock = threading.Lock() # 因为单个进程保持单例，使用多线程锁即可
        try:
            self.config = self.configget('all')
        except:
            self.config = {}
        if self.default_config_callback and init_use_callback:
            self.default_config = self.default_config_callback(self.config)
        for k, v in copy.deepcopy(self.default_config).items():
            self._config_add(k, v)



    def update_config(self):
        """
        向所有进程发送更新的配置
        """
        for _, get_queue in self.queues:
            get_queue.put(self.config)


    def _json_save(self):
        """修改设置(key,value,a)(要修改的项,值,all或1)"""
        with open(f"{self.fname}.json", 'w', encoding='UTF-8') as f:
            json.dump(self.config, f, indent=4, ensure_ascii=False)



    def configget(self, key):
        """获取设置 in:key out:value"""
        if key == 'all':
            with open(f"{self.fname}.json", 'r', encoding='UTF-8') as f:
                self.config = json.load(f)
            return self.config
        return self.config[key]



    def configset(self, key, value):
        """修改设置"""
        with self.config_lock:
            self.config[key] = value
            self._json_save()
            self.update_config()


    def configreset(self, key):
        """恢复默认设置"""
        with self.config_lock:
            print(f"reset config {key}")
            if self.default_config_callback:
                self.default_config = self.default_config_callback(
                    None if key == 'all' else self.config
                )
            default_config = copy.deepcopy(self.default_config)
            if key == 'all':
                self.config = default_config
            else:
                self.config[key] = default_config[key]
            self._json_save()
            self.update_config()

    def configupdate_config(self, key, last_value =None):
        """
        更新默认值, 如果用户的配置与旧的默认值一致，则更新为新的默认值
        Args:
            key: 需要更新的配置项
            last_value: 旧的默认值
        """
        if not self.configget(f"{key}_reseted"):
            if last_value is None or self.configget(key) == last_value:
                self.configreset(key)
            self.configset(f"{key}_reseted", True)
    def _config_add(self, key, devalue=None):
        try:
            a = self.config[key]
        except:
            self.config[key] = devalue
            self._json_save()


