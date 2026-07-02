import os

from xiaoe_ui import StyleEngine, ConfigBridge

from xiaoe_config_manager import Config

CONFIG_ROOT = "config_file"
os.makedirs(CONFIG_ROOT, exist_ok=True)
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
        {"pos": 0.00, "color": [255, 233, 233, 190]},
        {"pos": 0.61, "color": [255, 222, 233, 190]},
        {"pos": 0.82, "color": [255, 82 , 140, 190]},
        {"pos": 1.00, "color": [255, 82 , 140, 190]}
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

def migrate_gradient_data(config):
    """
    将旧版渐变色数据格式 {y, color} 迁移为 xiaoe_ui 框架所需的 {pos, color} 格式。
    如果数据已经是新格式或不存在，则不做任何修改。
    调用后如果 config 有持久化方法（如 save），需手动调用保存。
    """
    data = config.get('gradient_color')
    # 如果数据不存在或不是列表，直接返回
    if not data or not isinstance(data, list):
        return
    # 如果列表为空，无需处理
    if len(data) == 0:
        return
    # 检查第一个元素，如果包含 'y' 且不包含 'pos'，则为旧格式
    if 'y' in data[0] and 'pos' not in data[0]:
        new_data = [{"pos": item["y"], "color": item["color"]} for item in data]
        config.set('gradient_color', new_data)
        # 提示：如果 config 有 save 方法，可在此调用 config.save()
        # 例如：if hasattr(config, 'save'): config.save()
        print("渐变颜色配置已自动从旧格式 (y) 迁移到新格式 (pos)")
config_manager = Config(
    file_name=f"{CONFIG_ROOT}/config",
    default_config=DEFAULT_CONFIG
)
config = ConfigBridge(instance=config_manager)
migrate_gradient_data(config)


engine = StyleEngine()
engine.add_qss(
    """
QPushButton:disabled {
    background-color: #d3d3d3; /* 背景变浅灰 */
}
    """
)
theme_cfg = ConfigBridge(instance=Config(
    file_name=f"{CONFIG_ROOT}/theme",
    default_config=engine.get_defaults())
)


