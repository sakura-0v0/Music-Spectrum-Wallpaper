import json
import math
import multiprocessing
import os

from get_res import get_res_path

with open(get_res_path('icos/app_info.json'), 'r', encoding='UTF-8') as f:
    APP_INFO = json.load(f)

APP_NAME = APP_INFO.get('app_name')
APP_VERSION = APP_INFO.get('version')

DEFAULT_CONFIG = {
    # 窗口设置(已在系统托盘提供开关)
    'is_locked':True,
    'win_top': False,
    'win_wallpaper': False,
    'win_wallpaper_full_screen': False,
    'win_wallpaper_xywh_offset': (0,0,0,0),
    'win_size': (1000, 450),
    'win_xy': (),

    # 插帧开关(现在基本上没用了)
    'hight_fps' : False,# (无需重启)
    'target_fps' : 170,# (重启)
    'jump_frame' : 5, # 超过5帧则跳帧(重启)

    # 全屏检测开关
    'full_screen_detect': True,
    'maximized_screen_detect': True,
    'exclude_window': ['Program Manager','Microsoft Text Input Application'],
    'exclude_window_maximize':[],
    'screen_detect_time': 3,
    # 音频采集参数
    'driver_chunk': 128, # 驱动数据块大小
    # fft参数
    'target_fft_size': 4096,
    'target_fft_fps': 170,
    # 重采样参数(重启)
    # 'chunk_a': 1, # FFT大小 = chunk_a * 重采样后的数据块大小(1024)
    'target_rate' : 48000, # 目标采样率
    # 'format_num' : 16, # 目标位深度


    # FFT前后处理参数(无需重启)
    'window_beta' : 8, # 0-20 FFT前处理：凯瑟窗口参数

    'use_max_num': 2,
    'fft_window_size' : 50, # FFT后处理加权平均数窗口长度
    'alpha' : 0.8, # FFT后加权平均数参数
    'max_alpha': 0.9, # 瞬态系数

    # 坐标轴参数(重启)
    'pl_start' : 50, # 坐标轴起始值
    'pl_end' : 16000, # 坐标轴终止值
    'log_points' : 130,  # 密度参数，增大值可增加数据点密度

    # 柱状图高度范围(重启)
    'gradient_max_height': 0.58,
    'gradient_min_height': 0.28,

    # 柱状图设置(重启)
    'gradient_color_top':(255, 255, 255, 190),
    'gradient_color_bottom': (255, 82, 140, 190),
    'gradient_color':[
        {"y": 0.00, "color": [255, 233, 233, 190]},
        {"y": 0.61, "color": [255, 222, 233, 190]},
        {"y": 0.82, "color": [255, 82 , 140, 190]},
        {"y": 1.00, "color": [255, 82 , 140, 190]}
    ],
    'gradient_width': 0.7,

    # 峰值条设置(重启)
    'peak_bars_show': True,
    'peak_bars_color': (255, 255, 255, 150),
    'peak_bars_width': 0.7,
    'peak_h': 0.5,  # 峰值条高度
    'peak_decay_speed_g': 60,  # 峰值条下降速度(无需重启)

    # 小球粒子设置(无需重启)
    'ball_show': False,
    'ball_speed' : 0.1,  # 上升速度（像素/帧），越大越快
    'ball_size' : 6,  # 小球直径
    'ball_color' : (255, 255, 255, 200),  # 颜色 (R,G,B,Alpha)
    'emit_threshold' : 0.3,  # 触发阈值，上升幅度高于值预发射
    'emit_threshold2' : 0.02 , # 触发阈值，上升幅度低于值即发射

}

class Config:

    lock = multiprocessing.Lock()
    format_float = False
    pl = [ ] # x坐标轴
    queues = []# 当配置被修改时，向所有队列发送配置


    def __init__(self):
        self.config = {}
        self.fname = 'config'
        for k, v in DEFAULT_CONFIG.items():
            self.config_add(k, v)
        self.config_lock = Config.lock
        self.update_pl()

    def update_config(self):
        """
        向所有进程发送更新的配置
        :return:
        """
        for _, get_queue in Config.queues:
            get_queue.put(self.config)


    def _json_save(self):
        """修改设置(key,value,a)(要修改的项,值,all或1)"""
        with open(f"{self.fname}.json", 'w', encoding='UTF-8') as f:
            json.dump(self.config, f)



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
            self.config[key] = DEFAULT_CONFIG[key]
            self._json_save()
            self.update_config()



    def config_add(self, key, devalue=None):
        try:
            a = self.config[key]
        except:
            # print(key, devalue)
            if os.path.exists(f"{self.fname}.json"):
                adict = self.configget('all')
            else:
                adict = {}
            adict[key] = devalue
            with open(f"{self.fname}.json", 'w', encoding='UTF-8') as f:
                json.dump(adict, f)
            self.config[key] = devalue

    def update_pl(self):
        def generate_log_distribution():
            """生成对数分布参考列表"""
            log_start = math.log(self.config['pl_start'])
            log_end = math.log(self.config['pl_end'])
            step = (log_end - log_start) / (self.config['log_points'] - 1)
            print(log_start, log_end, step)
            result = []
            i = 0
            while True:
                num = round(math.exp(log_start + i * step))
                if num > self.config['pl_end']:
                    break
                # print(num)
                result.append(num)
                i += 1
            print(result)
            return result
        # 生成对数参考系
        log_ref = generate_log_distribution()
        self.pl = log_ref
