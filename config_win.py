import os
import threading
import time
from multiprocessing import Process, Queue
from typing import Optional

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QCheckBox, QSlider,
                             QSpinBox, QDoubleSpinBox, QPushButton, QLabel, QColorDialog,
                             QSizePolicy, QFrame, QApplication, QScrollArea, QComboBox, QDialog, QInputDialog,
                             QMessageBox)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QColor, QIcon

from config import APP_NAME
# from qt_material import apply_stylesheet, list_themes
from config_multiprocess import ConfigInChildProcessPipe, ConfigInMainProcessPipe
from count_fps import CountFps, CountFpsShare
from fast_desktop import create_lnk, get_startup_path, get_desktop_path
from get_res import get_res_path
import tools
import config as old_config
from style import style

RESTART_KEYS = {
    'jump_frame', 'chunk_a','driver_chunk',
    'format_num', 'pl_start', 'pl_end', 'log_points', 'gradient_max_height',
    'gradient_min_height',
}



class ConfigWindow(QWidget):
    restart_required = pyqtSignal()
    window_activate = pyqtSignal()

    def __init__(
            self,
            config,
            fps_dict,
            top_win_queue,
            maxsize_window,
            fill_screen_window
    ):
        super().__init__()
        self.fps_dict = fps_dict
        self.config = config
        self.top_win_queue = top_win_queue
        self.maxsize_window = maxsize_window
        self.fill_screen_window = fill_screen_window
        self.widget_map = {}
        self.fps_info = []

        self.init_ui()
        self.setWindowIcon(QIcon(get_res_path("icos/logo.ico")))
        self.setWindowTitle(f"{old_config.APP_NAME}选项 - v{old_config.APP_VERSION}")
        self.restart_flag = False
        self.setMinimumSize(600, 400)
        # apply_stylesheet(self, theme='light_pink.xml', extra=style)

        self.setStyleSheet(style)
        self.top_win_thread = threading.Thread(target=self.top_win, daemon=True)
        self.top_win_thread.start()
        self.window_activate.connect(self.do_activate)

    def top_win(self):
        # print('in_process')
        while True:
            m = self.top_win_queue.get()
            # print(m)
            if m is None:
                break
            self.window_activate.emit()

    def do_activate(self):
        self.activateWindow()
        self.raise_()

        # print('`b`reak_process')

    def init_ui(self):
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.scroll_layout = QVBoxLayout(content)

        # 手动排列配置项
        self.setup_ui()



        scroll.setWidget(content)
        main_layout.addWidget(scroll)

        bottom_container = QWidget()
        h_layout = QHBoxLayout(bottom_container)
        h_layout.setContentsMargins(0, 0, 0, 0)
        # 添加重置按钮
        reset_btn = QPushButton("恢复默认")
        reset_btn.setFixedWidth(150)
        # reset_btn.setFixedSize(200, 22)
        reset_btn.clicked.connect(self.reset_defaults)
        h_layout.addWidget(reset_btn)

        self.yzhxe_label = QLabel(f'版本:{old_config.APP_VERSION} by.一只黄小娥 qq wx:1206985031')
        # self.yzhxe_label.setProperty("class","fps_label")
        h_layout.addWidget(self.yzhxe_label)

        bottom_fps_container = QWidget()
        fps_layout = QHBoxLayout(bottom_fps_container)

        fps_layout.addStretch(1)
        self.create_fps_widget(fps_layout, "Record", "音频采集")
        self.create_fps_widget(fps_layout, "FFT", "FFT")
        self.create_fps_widget(fps_layout, "显示", "显示")

        main_layout.addWidget(bottom_container)
        main_layout.addWidget(bottom_fps_container)

        # 添加定时器
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_fps_labels)
        self.timer.start(1000)  # 每秒更新

    def setup_ui(self):
        space = 10*' '
        # 全屏检测
        self.add_section_title("快速启动")
        self.create_btn("快捷方式", text = "创建桌面快捷方式",func_ = self.create_desktop_lnk, reset_func_ = None)
        self.create_btn("开机自启", text = "设置软件开机自启",func_ = self.create_startup_lnk, reset_func_ = self.clear_startup)

        self.add_divider()

        self.add_section_title("暂停检测 - 其他软件全屏、最大化时暂停")
        self.create_checkbox('maximized_screen_detect', "最大化暂停")
        self.create_btn_picker('exclude_window_maximize', "最大化排除",text = '设置不检测最大化的窗口' ,func_ = lambda :self.set_exclude_window('exclude_window_maximize'))
        self.create_checkbox('full_screen_detect', "全屏暂停")
        self.create_btn_picker('exclude_window', "全屏排除",text = '设置不检测全屏的窗口' ,func_ = lambda :self.set_exclude_window('exclude_window'))
        self.create_slider_input('screen_detect_time', "轮询间隔(s)", 0.5, 30.0, 0.5)
        self.add_divider()

        self.add_section_title(f"{space}显示设置")

        self.add_divider()
        # 坐标轴设置
        self.add_section_title("坐标轴 - 设置x轴的刻度 (需重启)")
        self.create_slider_input('pl_start', "起始频率(Hz)",  20, 200, 1)
        self.create_slider_input('pl_end', "截止频率(Hz)",  8000, 20000, 1)
        self.create_slider_input('log_points', "标尺密度", 1, 500, 1)
        self.add_divider()

        # 柱状图设置
        self.add_section_title("柱状图 - 设置柱状图样式")
        # self.create_color_picker('gradient_color_top', "渐变颜色顶部")
        # self.create_color_picker('gradient_color_bottom', "渐变颜色底部")
        self.create_btn_picker('gradient_color', "渐变色",text = '设置柱状图的渐变色' ,func_ = self.set_gradient_color_window)

        self.create_slider_input('gradient_width', "宽度", 0.1, 1.0, 0.01)
        self.create_slider_input('gradient_max_height', "最大高度(需重启)", 0.0, 1.0, 0.01)
        self.create_slider_input('gradient_min_height', "最小高度(需重启)", 0.0, 1.0, 0.01)
        self.add_divider()

        # 峰值条设置
        self.add_section_title("峰值指示器")
        self.create_checkbox('peak_bars_show', "显示")
        self.create_color_picker('peak_bars_color', "颜色")
        self.create_slider_input('peak_bars_width', "宽度", 0.1, 10.0, 0.05)
        self.create_slider_input('peak_h', "高度", 0.01, 5, 0.01)
        self.create_slider_input('peak_decay_speed_g', "衰减速度", 1, 2000, 1)
        self.add_divider()

        # 粒子效果
        self.add_section_title("粒子效果")
        self.create_checkbox('ball_show', "显示")
        self.create_color_picker('ball_color', "颜色")
        self.create_slider_input('ball_size', "直径(px)", 2, 20, 1)
        self.create_slider_input('ball_speed', "速度(像素/帧)", 0.01, 1.0, 0.01)
        self.create_slider_input('emit_threshold', "高触发阈值", 0.0, 1.0, 0.005)
        self.create_slider_input('emit_threshold2', "低触发阈值", 0.0, 1.0, 0.005)
        self.add_divider()
        # 插帧设置
        self.add_section_title("帧生成 (FFT帧数较低时可选启用) - 请参考实际帧率适当提升该项")
        self.create_checkbox('hight_fps', "启用帧生成")
        self.create_slider_input('target_fps', "目标帧率", 1, 300, 1)
        self.create_slider_input('jump_frame', "跳帧(需重启)",  1, 30, 1)
        self.add_divider()

        self.add_section_title(f"{space}音频处理")

        self.add_divider()
        # 音频处理
        self.add_section_title("音频采集 - 数据块越小帧数上限越高")
        # self.create_slider_input('chunk_a', "FFT倍数(x1024)", 1, 8, 1)
        self.create_combobox('driver_chunk', "数据块(需重启)",
                             [2**i for i in range(4, 14)])
        self.create_combobox('target_rate', "重采样采样率",
                             [44100, 48000, 96000, 192000])
        # self.create_combobox('format_num', "位深度", [8, 16, 24, 32], )
        self.add_divider()

        # FFT参数
        self.add_section_title("FFT预处理 - 设置FFT预处理参数")
        self.create_slider_input('window_beta', "凯瑟窗口参数", 0, 20, 1)
        self.add_divider()

        # fft参数
        self.add_section_title("FFT参数 - 设置FFT参数")
        self.create_slider_input('target_fft_fps', "目标帧率",1, 600, 1)
        self.create_combobox(
            "target_fft_size", "FFT大小",
            [2**i for i in range(6, 17)])
        self.create_slider_input('max_alpha',"瞬态系数",0.0,1.5,0.01)

        self.add_divider()

        self.add_section_title("FFT后处理 - 设置FFT后处理参数")
        self.create_slider_input('use_max_num', "切换插值法阈值", 1, 1000, 1)
        self.create_slider_input('fft_window_size', "加权平滑长度", 1, 500, 1)
        self.create_slider_input('alpha', "加权平滑系数", 0.0, 1.0, 0.01)
        self.add_divider()

        self.scroll_layout.addStretch()

    def add_section_title(self, text):
        """添加分组标题"""
        label = QLabel(text)
        label.setProperty("class","section_title")
        self.scroll_layout.addWidget(label)

    def add_divider(self):
        """添加分割线"""
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet("color: #ddd;")
        self.scroll_layout.addWidget(line)

    def create_combobox(self, key, name, options):
        """创建下拉选择框"""
        container = QWidget()
        layout = QHBoxLayout(container)

        label = QLabel(self._format_name(key, name))
        label.setProperty("class", "item")

        combo = NoWheelComboBox()
        combo.addItems(map(str, options))
        combo.setCurrentText(str(self.config.configget(key)))
        combo.currentTextChanged.connect(
            lambda v: self.update_config(key, int(v)))

        # 重置按钮
        reset_btn = QPushButton("重置")
        reset_btn.setFixedWidth(60)
        reset_btn.clicked.connect(lambda: self.reset_single_item(key, combo))

        layout.addWidget(label)
        layout.addWidget(combo)
        layout.addWidget(reset_btn)
        self.scroll_layout.addWidget(container)
        self.widget_map[key] = combo
        return container
    def create_checkbox(self, key, name):
        """创建复选框"""
        value = self.config.configget(key)
        container = QWidget()
        layout = QHBoxLayout(container)

        label = QLabel(self._format_name(key, name))
        label.setProperty("class", "item")
        checkbox = QCheckBox()
        checkbox.setChecked(value)

        # 添加重置按钮
        reset_btn = QPushButton("重置")
        reset_btn.setFixedWidth(60)
        reset_btn.clicked.connect(lambda: self.reset_single_item(key, checkbox))

        checkbox.stateChanged.connect(
            lambda state: self.update_config(key, bool(state)))

        layout.addWidget(label)
        layout.addWidget(checkbox)
        layout.addWidget(reset_btn)  # 添加重置按钮到布局
        self.scroll_layout.addWidget(container)
        self.widget_map[key] = checkbox
        return container

    def create_slider_input(self, key, name, min_val, max_val, step):
        """创建滑块+输入框组合"""

        value = self.config.configget(key)
        container = QWidget()
        layout = QHBoxLayout(container)

        # 标签
        label = QLabel(self._format_name(key, name))
        label.setProperty("class", "item")
        layout.addWidget(label)

        # 输入框
        if isinstance(min_val, int) and isinstance(max_val, int) and isinstance(step, int):
            input_box = NoWheelSpinBox()
        else:
            input_box = NoWheelDoubleSpinBox()
            input_box.setDecimals(2)

        input_box.setRange(min_val, max_val)
        input_box.setSingleStep(step)
        input_box.setValue(value)

        # 滑块
        slider = NoWheelSlider(Qt.Horizontal)
        slider.setRange(0, int((max_val - min_val) / step))
        slider.setValue(int((value - min_val) / step))

        # 重置按钮
        reset_btn = QPushButton("重置")
        reset_btn.setFixedWidth(60)

        # reset_btn.setFixedSize(60, 22)
        reset_btn.clicked.connect(lambda: self.reset_single_item(key, input_box))

        # 信号连接
        input_box.valueChanged.connect(
            lambda v: slider.setValue(int((v - min_val) / step))
        )
        input_box.valueChanged.connect(
            lambda v: self.update_config(key, v))
        slider.valueChanged.connect(
            lambda v: input_box.setValue(min_val + v * step))

        layout.addWidget(input_box)
        layout.addWidget(slider)
        layout.addWidget(reset_btn)  # 添加重置按钮到布局
        self.scroll_layout.addWidget(container)
        self.widget_map[key] = container
        return container

    def create_color_picker(self, key, name):
        """创建颜色选择器(标签左对齐、颜色按钮居中、重置右对齐)"""
        value = self.config.configget(key)
        container = QWidget()
        layout = QHBoxLayout(container)

        # 左侧标签 (左对齐)
        label = QLabel(self._format_name(key, name))
        label.setProperty("class", "item")
        label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(label)

        color_value_label = QLabel()
        self.update_color_label(color_value_label, value)
        color_value_label.setProperty("class", "color")

        layout.addWidget(color_value_label)

        # 中间弹性空间 + 颜色按钮
        layout.addStretch(1)  # 左侧弹性推挤


        btn_back = QWidget()
        self.set_color_btn_back(btn_back)

        btn_back_layout = QHBoxLayout(btn_back)

        btn = QPushButton()
        self.update_button_color(btn, value)
        btn.clicked.connect(lambda: self.choose_color(key, btn, color_value_label))
        btn_back_layout.addWidget(btn)
        layout.addWidget(btn_back, alignment=Qt.AlignCenter)

        # 右侧重置按钮 (右对齐)
        layout.addStretch(1)  # 右侧弹性推挤
        reset_btn = QPushButton("重置")
        reset_btn.setFixedWidth(60)

        def func():
            self.reset_single_item(key, btn)
            self.update_color_label(color_value_label, self.config.configget(key))
        reset_btn.clicked.connect(func)
        layout.addWidget(reset_btn)

        self.scroll_layout.addWidget(container)
        self.widget_map[key] = btn
        return container

    def create_btn_picker(self, key, name, text = None,func_ = None):
        """创建带配置的按钮"""
        value = self.config.configget(key)
        container = QWidget()
        layout = QHBoxLayout(container)

        # 左侧标签 (左对齐)
        label = QLabel(name)
        label.setProperty("class", "item")
        label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(label)

        if not text:
            text = value
        color_value_label = QLabel(text)
        color_value_label.setProperty("class", "color")
        layout.addWidget(color_value_label)

        # 中间弹性空间 + 颜色按钮
        layout.addStretch(1)  # 左侧弹性推挤



        btn = QPushButton('设置')
        # btn.setFixedWidth(60)

        btn.clicked.connect(func_)
        layout.addWidget(btn, alignment=Qt.AlignCenter)

        # 右侧重置按钮 (右对齐)
        layout.addStretch(1)  # 右侧弹性推挤
        reset_btn = QPushButton("重置")
        reset_btn.setFixedWidth(60)
        def func():
            self.reset_single_item(key, btn, no_change_elm = True)
        reset_btn.clicked.connect(func)
        layout.addWidget(reset_btn)

        self.scroll_layout.addWidget(container)
        self.widget_map[key] = btn
        return container

    def create_btn(self,name, text = None,func_ = None, reset_func_ = None):
        """
        创建按钮
        :param name: 显示名称
        :param text: 描述文字
        :param func_: 按钮点击事件
        :param reset_func_: 重置按钮事件
        """
        container = QWidget()
        layout = QHBoxLayout(container)

        # 左侧标签 (左对齐)
        label = QLabel(name)
        label.setProperty("class", "item")
        label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(label)

        color_value_label = QLabel(text)
        color_value_label.setProperty("class", "color")
        layout.addWidget(color_value_label)

        # 中间弹性空间 + 颜色按钮
        layout.addStretch(1)  # 左侧弹性推挤



        btn = QPushButton('设置')
        # btn.setFixedWidth(60)

        btn.clicked.connect(func_)
        layout.addWidget(btn, alignment=Qt.AlignCenter)

        # 右侧重置按钮 (右对齐)
        layout.addStretch(1)  # 右侧弹性推挤
        reset_btn = QPushButton("重置")
        reset_btn.setFixedWidth(60)

        if reset_func_:
            reset_btn.clicked.connect(reset_func_)
        else:
            reset_btn.setDisabled(True)

        layout.addWidget(reset_btn)

        self.scroll_layout.addWidget(container)

        return container

    def create_fps_widget(self, parent, key, name):
        fps_label = QLabel()
        fps_label.setProperty("class","fps_label")
        parent.addWidget(fps_label)
        self.fps_info.append({
            'key' : key,
            'name' : name,
            'label' : fps_label,
        })
    def reset_single_item(self, key, widget, no_change_elm = False):
        """重置单个配置项"""

        self.config.configreset(key)
        default = old_config.DEFAULT_CONFIG[key]
        # default = self.config.configget(key)
        if no_change_elm:
            return
        # 更新控件显示
        if isinstance(widget, QCheckBox):
            widget.setChecked(default)
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            widget.setValue(default)
        elif isinstance(widget, QPushButton):
            self.update_button_color(widget, default)
        elif isinstance(widget, QComboBox):
            widget.setCurrentText(str(default))
        # 如果是滑块组合需要特殊处理
        container = self.widget_map.get(key)
        if container:
            slider= container.findChild(QSlider)
            if slider:
                min_val = widget.minimum()
                max_val = widget.maximum()
                if isinstance(widget, QDoubleSpinBox):
                    step = widget.singleStep()
                    slider.setValue(int((default - min_val) / step))

        if key in RESTART_KEYS and not self.restart_flag:
            self.setWindowTitle(f"{self.windowTitle()} (需要重启)")
            self.restart_flag = True

    def set_color_btn_back(self, elem):
        elem.setStyleSheet('''
            background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0.333 #000000,        /* 左黑截止点 */
                stop:0.334 #808080,
                stop:0.665 #808080,
                stop:0.666 #FFFFFF);       /* 右白起始点 */
            border-radius: 3px;
            border: 1px solid #888;
        ''')

    def _format_name(self, key, name):
        """格式化显示名称"""
        if key in RESTART_KEYS:
            return f"{name}*"
        return name

    def update_config(self, key, value):
        self.config.configset(key, value)
        if key in RESTART_KEYS and not self.restart_flag:
            self.setWindowTitle(f"{self.windowTitle()} (需要重启)")
            self.restart_flag = True

    def choose_color(self, key, btn, lab):
        color = QColorDialog.getColor(initial=QColor(*self.config.configget(key)),
                                     options=QColorDialog.ShowAlphaChannel)
        if color.isValid():
            rgba = (color.red(), color.green(), color.blue(), color.alpha())
            self.update_config(key, rgba)
            self.update_button_color(btn, rgba)
            self.update_color_label(lab, rgba)

    def update_color_label(self, lab, rgba):
        lab.setText(f"RGBA({','.join((str(i) for i in rgba))})")

    def update_button_color(self, btn, rgba):
        btn.setStyleSheet(
            f"background-color: rgba({','.join((str(i) for i in rgba))});"
            "border: 1px solid #888;"
            "border-radius: 3px;"
            "margin: 0"
        )
    def reset_defaults(self):
        for key in old_config.DEFAULT_CONFIG:
            if key in [
                'is_locked',
                'win_top',
                'win_size',
                'win_xy',
                'win_wallpaper',
                'win_wallpaper_full_screen',
                'win_wallpaper_xywh_offset',
            ]:
                continue
            self.config.configreset(key)
            default = old_config.DEFAULT_CONFIG[key]
            # 更新控件显示
            widget = self.widget_map.get(key)
            if widget:
                if isinstance(widget, QCheckBox):
                    widget.setChecked(default)
                elif isinstance(widget, QWidget):  # 滑块输入组合
                    input_box = widget.findChild((QSpinBox, QDoubleSpinBox))
                    if input_box:
                        input_box.setValue(default)
        self.restart_flag = True
        self.setWindowTitle(f"{self.windowTitle()} (需要重启)")

    def closeEvent(self, event):
        if self.restart_flag:
            self.restart_required.emit()
        super().closeEvent(event)

    def update_fps_labels(self):
        # 获取实时数据（这里需要替换为实际获取方法）
        for item in self.fps_info:
            key = item["key"]
            name = item["name"]
            label = item["label"]
            # print(name, key)
            fps = self.fps_dict.get(key).value
            label.setText(f"{name}:{fps: >3}FPS")

    def create_desktop_lnk(self):
        if CustomMessageBox.confirm(
                self,
                "创建桌面快捷方式",
                "是否要创建桌面快捷方式？"
        ):
            try:
                create_lnk(APP_NAME, APP_NAME, get_desktop_path())
            except Exception as e:
                QMessageBox.critical(
                    self,
                    '错误',
                    f"{e}"
                )

    def create_startup_lnk(self):
        if CustomMessageBox.confirm(
                self,
                "设置开机自启",
                "是否要设置开机自启？"
        ):
            try:
                create_lnk(APP_NAME, APP_NAME, get_startup_path())
            except Exception as e:
                QMessageBox.critical(
                    self,
                    '错误',
                    f"{e}"
                )

    def clear_startup(self):
        if CustomMessageBox.confirm(
                self,
                "取消设置开机自启",
                "是否要撤销设置开机自启？"
        ):
            try:
                os.remove(os.path.join(get_startup_path(),f"{APP_NAME}.lnk"))
            except Exception as e:
                QMessageBox.critical(
                    self,
                    '错误',
                    f"如果遇到的是“系统找不到指定的文件”，说明你并没有设置过开机自启。\n\n{e}"
                )

    def set_exclude_window(self, config_key):
        # 创建对话框
        win_text = ''
        if config_key == 'exclude_window':
            win_text = '全屏'
            checked_list = self.fill_screen_window
        elif config_key == 'exclude_window_maximize':
            win_text = '最大化'
            checked_list = self.maxsize_window


        dialog = QDialog(self)
        dialog.setWindowTitle(f"添加{win_text}检测的排除窗口")
        dialog.setMinimumSize(400, 600)
        main_layout = QVBoxLayout(dialog)
        add_lab = QLabel(f'导致程序暂停的{win_text}窗口：')
        main_layout.addWidget(add_lab)
        # 第一行：下拉框和加号按钮
        top_layout = QHBoxLayout()
        self.exclude_combo = QComboBox()
        self.exclude_combo.addItems([win for win in checked_list if win.strip()])
        add_btn = QPushButton("←不检测该窗口")
        add_btn.setStyleSheet(
            "min-width: 120px;"
            "max-width: 120px;"
        )

        top_layout.addWidget(self.exclude_combo, 1)
        top_layout.addWidget(add_btn)
        main_layout.addLayout(top_layout)

        add_lab = QLabel(
            f'已排除检测的{win_text}窗口：\n\n'
            f'   - 当程序莫名其妙被暂停时，可尝试添加排除窗口。\n'
            f'   - 作用：即使检测到下面的窗口{win_text}，也不会暂停运行。'
        )
        main_layout.addWidget(add_lab)
        # 第二行：滚动区域显示已排除窗口
        scroll = QScrollArea()
        content = QWidget()
        self.list_layout = QVBoxLayout(content)
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        main_layout.addWidget(scroll)

        # 刷新列表函数
        def refresh_list():
            # 清空现有列表
            while self.list_layout.count():
                item = self.list_layout.takeAt(0)
                widget = item.widget()
                if widget:
                    widget.deleteLater()
                elif item.spacerItem():
                    self.list_layout.removeItem(item)
            def create_line():
                divider = QFrame()
                divider.setFrameShape(QFrame.HLine)
                divider.setFrameShadow(QFrame.Sunken)
                divider.setStyleSheet("color: #eeeeee; margin: 2px 10px;")
                self.list_layout.addWidget(divider)

            # 从配置获取当前排除列表
            current_list = self.config.configget(config_key)
            create_line()
            # 添加每个列表项
            for window in current_list:
                item_widget = QWidget()
                item_layout = QHBoxLayout(item_widget)
                item_layout.addWidget(QLabel(window), 1)

                # 删除按钮
                del_btn = QPushButton("移除")
                del_btn.setStyleSheet("color: red; font-size: 18px;")
                del_btn.clicked.connect(lambda _, w=window: remove_window(w))

                item_layout.addWidget(del_btn)
                self.list_layout.addWidget(item_widget)
                # 添加分割线
                create_line()
            self.list_layout.addStretch(1)

        # 添加窗口逻辑
        def add_window():
            selected = self.exclude_combo.currentText()
            dialog = QInputDialog(self)
            dialog.setInputMode(QInputDialog.TextInput)
            dialog.setWindowTitle(f"添加{win_text}排除窗口",)
            dialog.setLabelText(
                "支持部分匹配，如：\n"
                "排除项：“Google Chrome” 匹配-> “一只黄小娥的小屋 - Google Chrome”\n\n"
                "请确认需要排除的窗口名称:"
            )
            dialog.setTextValue(selected)
            dialog.setOkButtonText("确定")  # ✅ 正确生效位置
            dialog.setCancelButtonText("取消")  # ✅ 正确生效位置

            if dialog.exec_() != QInputDialog.Accepted:
                return

            selected = dialog.textValue()

            current = self.config.configget(config_key) or []
            if selected not in current:
                current.append(selected)
                self.config.configset(config_key, current)
                QTimer.singleShot(50, refresh_list)

        # 删除窗口逻辑
        def remove_window(window):
            current = self.config.configget(config_key) or []
            if window in current:
                current.remove(window)
                self.config.configset(config_key, current)
                QTimer.singleShot(50, refresh_list)


        # 连接信号
        add_btn.clicked.connect(add_window)
        refresh_list()  # 初始刷新
        dialog.exec_()

    def set_gradient_color_window(self):
        # 创建对话框窗口
        dialog = QDialog(self)
        dialog.setWindowTitle("设置渐变色")
        dialog.setMinimumSize(700, 600)
        main_layout = QVBoxLayout(dialog)

        # 当前渐变色数据
        gradient_data = self.config.configget('gradient_color').copy()
        def print_gradient_data():
            print([i['y'] for i in gradient_data])
        # 存储控件引用
        point_widgets = []

        # 创建分隔线
        def create_line():
            divider = QFrame()
            divider.setFrameShape(QFrame.HLine)
            divider.setFrameShadow(QFrame.Sunken)
            divider.setStyleSheet("color: #eeeeee; margin: 2px 10px;")
            return divider

        # 更新单个项目的范围和值
        def update_item_range(index):
            if index >= len(point_widgets):
                return

            widgets = point_widgets[index]
            point = gradient_data[index]

            # 计算当前点的Y值范围
            min_val = 0.0
            max_val = 1.0

            # 如果有前一个点，则上限为前一个点的Y值
            if index > 0:

                min_val = gradient_data[index - 1]["y"]+0.01

            # 如果有后一个点，则下限为后一个点的Y值
            if index < len(gradient_data) - 1:

                max_val = gradient_data[index + 1]["y"]-0.01

            # 暂时断开信号避免循环触发
            widgets['y_spin'].valueChanged.disconnect()
            widgets['y_slider'].valueChanged.disconnect()

            # 设置范围
            widgets['y_spin'].setRange(min_val, max_val)
            # widgets['y_slider'].setRange(int(min_val * 100), int(max_val * 100))

            # 更新控件值
            widgets['y_spin'].setValue(point["y"])
            widgets['y_slider'].setValue(int(point["y"] * 100))

            # 重新连接信号
            widgets['y_spin'].valueChanged.connect(lambda v, idx=index: update_y_value(idx, v))
            widgets['y_slider'].valueChanged.connect(lambda v, idx=index: update_y_value(idx, v / 100.0))

        # 更新Y值
        def update_y_value(index, value):
            # 确保值在范围内
            min_val = point_widgets[index]['y_spin'].minimum()
            max_val = point_widgets[index]['y_spin'].maximum()
            clamped_value = max(min_val, min(value, max_val))

            gradient_data[index]["y"] = clamped_value

            # 更新当前项
            update_item_range(index)

            # 更新相邻点的范围
            if index > 0:
                update_item_range(index - 1)
            if index < len(gradient_data) - 1:
                update_item_range(index + 1)

            # 更新配置
            self.config.configset('gradient_color', gradient_data)

        # 刷新列表函数
        def refresh_list():
            # 清空现有列表
            for i in reversed(range(list_layout.count())):
                item = list_layout.itemAt(i)
                if item.widget():
                    item.widget().deleteLater()
                elif item.spacerItem():
                    list_layout.removeItem(item)

            point_widgets.clear()
            list_layout.addWidget(create_line())

            # 添加每个渐变色关键点
            for i, point in enumerate(gradient_data):
                item_widget = QWidget()
                item_layout = QHBoxLayout(item_widget)

                # Y值输入框
                y_spin = NoWheelDoubleSpinBox()
                y_spin.setSingleStep(0.01)

                # 滑动条
                y_slider = NoWheelSlider(Qt.Horizontal)
                y_slider.setRange(0, 100)

                # 颜色按钮
                btn_back = QWidget()
                self.set_color_btn_back(btn_back)

                btn_back_layout = QHBoxLayout(btn_back)
                color_btn = QPushButton()
                color_btn.setFixedSize(60, 24)
                update_btn_color(color_btn, point["color"])
                # 添加按钮
                add_btn = QPushButton("添加↑")
                # del_btn.setStyleSheet("color: red;")
                add_btn.clicked.connect(lambda _, idx=i: add_new_point(idx))

                # 删除按钮
                del_btn = QPushButton("删除")
                del_btn.setStyleSheet("color: red;")
                del_btn.clicked.connect(lambda _, idx=i: delete_point(idx))

                # 添加控件到布局
                item_layout.addWidget(QLabel("位置(y):"))
                item_layout.addWidget(y_spin)
                item_layout.addWidget(y_slider)
                item_layout.addWidget(QLabel("颜色:"))
                btn_back_layout.addWidget(color_btn)
                item_layout.addWidget(btn_back)
                item_layout.addWidget(add_btn)
                item_layout.addWidget(del_btn)

                if i in (0, len(gradient_data) - 1):
                    disable_elems = [
                        y_spin,
                        y_slider,
                        del_btn,
                    ]
                    if i == 0:
                        disable_elems.append(add_btn)

                    for it in disable_elems:
                        it.setStyleSheet(
                            "color: gray;"
                            "cursor: not-allowed;"
                        )
                        it.setToolTip("不允许进行此操作")
                        it.setDisabled(True)


                # 添加到列表布局
                list_layout.addWidget(item_widget)
                list_layout.addWidget(create_line())

                # 存储控件引用
                widgets = {
                    'y_spin': y_spin,
                    'y_slider': y_slider,
                    'color_btn': color_btn,
                    'del_btn': del_btn
                }
                point_widgets.append(widgets)

                # 连接信号
                y_spin.valueChanged.connect(lambda v, idx=i: update_y_value(idx, v))
                y_slider.valueChanged.connect(lambda v, idx=i: update_y_value(idx, v / 100.0))
                color_btn.clicked.connect(lambda _, idx=i: choose_color(idx))

            # 设置每个点的范围
            for i in range(len(gradient_data)):
                update_item_range(i)

            list_layout.addStretch(1)

        # 更新按钮颜色
        def update_btn_color(btn, color):
            btn.setStyleSheet(
                f"background-color: rgba{tuple(color)};"
                "border: 1px solid #888;"
                "border-radius: 3px;"
            )

        # 选择颜色
        def choose_color(index):
            old_color = gradient_data[index]["color"]
            color = QColorDialog.getColor(
                initial=QColor(*old_color),
                options=QColorDialog.ShowAlphaChannel
            )
            if color.isValid():
                new_color = [color.red(), color.green(), color.blue(), color.alpha()]
                gradient_data[index]["color"] = new_color
                # 只更新颜色按钮，不刷新整个列表
                update_btn_color(point_widgets[index]['color_btn'], new_color)
                # 更新配置
                self.config.configset('gradient_color', gradient_data)

        # 删除关键点
        def delete_point(index):
            if len(gradient_data) > 1:
                del gradient_data[index]
                self.config.configset('gradient_color', gradient_data)
                refresh_list()  # 需要刷新列表因为结构变化

        # 顶部按钮布局
        btn_layout = QHBoxLayout()
        head = QLabel(f"{' '*42}上↑{' '*35}↓下")
        btn_layout.addWidget(head)
        # add_btn = QPushButton("添加关键点")
        # add_btn.clicked.connect(lambda: add_new_point())
        # btn_layout.addWidget(add_btn)
        # refresh_btn = QPushButton("刷新")
        # refresh_btn.clicked.connect(lambda: refresh_list())
        # btn_layout.addWidget(refresh_btn)

        # 新建关键点
        def add_new_point(index):
            # 查找可用的中间位置
            print_gradient_data()
            now_y = gradient_data[index]["y"]
            up_y = gradient_data[index-1]["y"]

            now_color = gradient_data[index]["color"]
            up_color = gradient_data[index-1]["color"]
            new_y = (up_y+now_y)/2
            new_color = [(i[0]+i[1])//2 for i in zip(now_color, up_color)]

            gradient_data.insert(index, {
                "y": new_y,
                "color": new_color
            })

            self.config.configset('gradient_color', gradient_data)
            refresh_list()  # 需要刷新列表因为结构变化

            print_gradient_data()

        # 列表容器
        list_container = QWidget()
        list_layout = QVBoxLayout(list_container)

        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(list_container)

        # 组装界面
        main_layout.addLayout(btn_layout)
        main_layout.addWidget(scroll)
        refresh_list()  # 初始加载列表
        dialog.exec_()

class CustomInputDialog(QInputDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOkButtonText("确定")  # 自定义确认按钮
        self.setCancelButtonText("关闭")  # 自定义取消按钮

class CustomMessageBox(QMessageBox):
    """自定义确认对话框（Yes/No 语义 + 中文按钮）"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStandardButtons(QMessageBox.Yes | QMessageBox.No)  # 保留原逻辑
        self.button(QMessageBox.Yes).setText("确定")
        self.button(QMessageBox.No).setText("关闭")

    @classmethod
    def confirm(cls, parent, title, text):
        """快速创建确认对话框的类方法"""
        dialog = cls(parent)
        dialog.setWindowTitle(title)
        dialog.setText(text)
        dialog.setIcon(QMessageBox.Question)
        return dialog.exec_() == QMessageBox.Yes  # 直接返回布尔值

class NoWheelComboBox(QComboBox):
    def wheelEvent(self, event):
        event.ignore()

class NoWheelSpinBox(QSpinBox):
    def wheelEvent(self, event):
        event.ignore()

class NoWheelDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event):
        event.ignore()

class NoWheelSlider(QSlider):
    def wheelEvent(self, event):
        event.ignore()
# 供其他模块调用的函数
_config_window = None

def show_config_window():
    global _config_window
    if not _config_window:
        _config_window = ConfigWindow()
        _config_window.restart_required.connect(
            lambda: print("请重启应用以应用配置更改"))
    _config_window.show()




show_config_process: Process = None

def _show_config_process(
    config_get_queue,
    config_set_queue,
    restart_queue,
    fps_dict,
    top_win_queue,
    maxsize_window,
    fill_screen_window,
):
    import sys
    print('started process')
    config = ConfigInChildProcessPipe(config_set_queue, config_get_queue)
    print('inited config')
    app = QApplication(sys.argv)
    print('start')
    win = ConfigWindow(
        config,
        fps_dict,
        top_win_queue,
        maxsize_window,
        fill_screen_window
    )
    print('showing')
    win.show()
    print('showed')
    app.exec_()
    top_win_queue.put(None)
    win.top_win_thread.join()
    if win.restart_flag:
        restart_queue.put('restart')
    # del app, win, config
    print('quit_config_win_process-------------------')


config_process: Optional[ConfigInMainProcessPipe] = None

def show_config(
        config,
        maxsize_window,
        fill_screen_window,
        restart_queue,
):
    global show_config_process, config_process
    if show_config_process and show_config_process.is_alive():
        config_process.top_win_queue.put(1)
        return
    config_process = ConfigInMainProcessPipe(config)
    top_win_queue = Queue()

    show_config_process = Process(
        target=_show_config_process,
        args=(
            config_process.config_get_queue,
            config_process.config_set_queue,
            restart_queue,
            CountFpsShare.share_fps,
            top_win_queue,
            maxsize_window,
            fill_screen_window,
        ),
        name = f"{old_config.APP_NAME}配置",
        daemon=True
    )

    show_config_process.start()
    print('start process')


# 测试代码
if __name__ == "__main__":
    show_config()

