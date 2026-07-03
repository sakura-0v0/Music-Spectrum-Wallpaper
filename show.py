import ctypes
import traceback

import threading
import time
from collections import deque
from ctypes import wintypes
from typing import Callable

import numpy as np
import pyqtgraph as pg
from PySide6 import QtWidgets, QtGui, QtCore
from PySide6.QtCore import QTimer, Signal, QRect
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import QMessageBox, QVBoxLayout
from xiaoe_ui import FramelessWin, WallpaperWinMixin

from app_info import APP_NAME
from count_fps import CountFps

from get_res import get_res_path
from wallpaper_tools import set_windows_as_wallpaper


class GetColor:
    def __init__(
            self,
            config_key,
            run_func: Callable,
            run_func2: Callable = None,
            run_func3: Callable = None,
            run_func4: Callable = None,
            config = None,
    ):
        self.config = config
        self.config_key = config_key
        self.run_func = run_func
        self.run_func2 = run_func2
        self.run_func3 = run_func3
        self.run_func4 = run_func4

        self.color = None
        self.last_color_config = None
    def get_color_config(self):
        return self.config.configget(self.config_key)
    def _get_color(self):
        # return QtGui.QBrush(QtGui.QColor(*get_color_config()))
        return self.run_func(*self.get_color_config())

    def get_color(self):
        if self.last_color_config != self.get_color_config():
            self.last_color_config = self.get_color_config()
            self.color = self._get_color()
        return self.color

    def get_more_color(self):
        def _get_color():
            color_config = self.get_color_config()
            gradient = self.run_func()
            for item in color_config:
                y = item['pos']
                color = item['color']
                gradient.setColorAt(y, self.run_func2(*color))
            return self.run_func3(gradient)

        if self.last_color_config != self.get_color_config():
            self.last_color_config = self.get_color_config()
            self.color = _get_color()
        return self.color





class Show(WallpaperWinMixin, FramelessWin):
    quit_signal = Signal()
    def __init__(
            self,
            config,
            qt_app,
            pl,
            maxsize_window,
            fill_screen_window,
            wait_quit_queue,
            quit_show_queue,
            left_volume_value,
            right_volume_value,
            fps,
            open_main_win,
    ):
        self.open_main_win = open_main_win
        self.config = config
        self.qt_app = qt_app
        self.lock_status = True
        self.true_xy = (0, 0)
        super().__init__(
            min_w=80, min_h=50,
            on_top_with_global = False,
            cuantou=True,
        )
        # 初始化图形界面

        self.pl = pl
        self.maxsize_window = maxsize_window
        self.fill_screen_window = fill_screen_window
        self.win_quit_queue = wait_quit_queue
        self.quit_show_queue = quit_show_queue
        self.left_volume_value = left_volume_value
        self.right_volume_value = right_volume_value
        self.fps = CountFps("显示",fps)
        fmt = QtGui.QSurfaceFormat()
        fmt.setSwapInterval(0)  # 关键参数：0=禁用VSync, 1=启用VSync
        fmt.setRenderableType(QtGui.QSurfaceFormat.OpenGL)
        QtGui.QSurfaceFormat.setDefaultFormat(fmt)
        pg.setConfigOptions(
            useOpenGL=True,
            background=None
        )

        self.win = pg.GraphicsLayoutWidget()

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

        self.layout.addWidget(self.win)



        palette = self.palette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor(0, 0, 0, 0))
        self.setPalette(palette)
        self.show()
        self.raise_()
        self.activateWindow()
        self.init_ui()
        self.init_tray()
        self._load_config()
        self._edit_label.setText("拖动调整窗口大小 · 位置\n点击小键盘可微调位置")
        if self.config.configget("win_wallpaper"):
            self.init_wallpaper(default_show=True)


    def init_ui(self):

        self.max_db = 20 * np.log10((2 ** 16-1) * 1024 / 2)
        self.y_t= self.max_db * self.config.configget('gradient_max_height')
        self.y_b = self.max_db * self.config.configget('gradient_min_height')
        # 创建全局渐变

        self.bars_color = GetColor(
            "gradient_color",
            lambda: QtGui.QLinearGradient(0, self.y_t, 0, self.y_b) ,
            # self.gradient.setColorAt,
            QtGui.QColor,
            QtGui.QBrush,
            config = self.config
        )
        self.peak_color = GetColor(
            "peak_bars_color",
            lambda *a: QtGui.QBrush(QtGui.QColor(*a)),
            config=self.config
        )
        self.balls_color = GetColor("ball_color", pg.mkBrush, config=self.config)

        # 创建柱状图项
        self.bars = pg.BarGraphItem(
            x=[],
            height=[],
            width=self.config.configget('gradient_width'),
            brush=self.bars_color.get_more_color(),#QtGui.QBrush(self.gradient),  # 关键：使用mkBrush包装渐变
            # pen=None,
            useOpenGL=True,
            config=self.config

        )

        self.axis = pg.AxisItem(orientation='bottom')
        self.axis.setTicks([[(i, str(f)) for i, f in enumerate(self.pl)]])
        self.axis.setTicks([])  # 禁用刻度线
        self.axis.setPen(pg.mkPen(width=0))  # 设置轴线为透明

        self.plot = self.win.addPlot(axisItems={'bottom': self.axis})

        self.plot.addItem(self.bars)

        self.plot.setYRange(self.y_b, self.y_t)
        self.plot.setXRange(1, len(self.pl) - 2)
        self.plot.setMouseEnabled(x=False, y=False)
        # self.plot.getViewBox().setBackgroundColor(None)

        self.plot.hideAxis('left')  # 隐藏坐标轴


        # 峰值
        # 初始化峰值数组
        self.peak_heights = np.zeros_like(self.pl)
        self.peak_velocities = np.zeros(len(self.pl))
        # 创建峰值保持条
        self.peak_bars = pg.BarGraphItem(
            x=[],
            height=np.full(len(self.pl), 0.01),  # 横条高度固定3像素
            width=self.config.configget('peak_bars_width'),  # 比主柱子略宽
            brush=self.peak_color.get_color(),  # QtGui.QBrush(QtGui.QColor(*config.configget('peak_bars_color'))),  # 半透明白色
            pen=None,
            useOpenGL=True
        )
        self.plot.addItem(self.peak_bars)
        self.peak_heights = np.zeros(len(self.pl))  # 新增峰值高度数组
        self.last_peak_update = time.time()

        # 粒子效果
        self.balls = []  # 存储小球信息（字典格式）

        self.last_update = time.time()
        self.data_buffer = deque(maxlen=self.config.configget('target_fps')+self.config.configget('target_fps')//6)
        self.last_data : tuple[float, any, any] = (None, None, None)

        self.skip_page_time = self.config.configget('jump_frame') / self.config.configget('target_fps')

        self.timer = QtCore.QTimer()
        self.timer.setTimerType(QtCore.Qt.PreciseTimer)
        self.timer.timeout.connect(self._process_buffer)
        self.timer.start(1)
        self.quit_signal.connect(self.quit_show, QtCore.Qt.QueuedConnection)
        threading.Thread(target= self.check_quit, daemon=True).start()

    def check_quit(self):
        self.quit_show_queue.get(block=True)
        self.quit_signal.emit()


    def quit_show(self):
        self.close()
        self.qt_app.quit()
        print('quit_show_win-------------------')




    def update_bars(self, x, y):
        self.bars.setOpts(
            x=x,
            height=y,
            width=self.config.configget('gradient_width'),
            brush=self.bars_color.get_more_color(),
        )

        self._update_peaks(x, y)
        self._update_balls(x, y)
        # self._update_volume()
        self.fps.count_fps()



    def update_data(self, x, y):
        timestamp = time.time()
        data = (timestamp, x, y)
        if not self.config.configget('hight_fps') or self.last_data[0] is None:
            # self.update_bars(x, y)
            self.data_buffer.append(
                data
            )
        else:
            # 计算逻辑帧间隔(s)
            this_fft_page_timestamp = timestamp - self.last_data[0]
            if this_fft_page_timestamp <= 0:
                this_fft_page_timestamp = 1e-6
            # # 计算逻辑帧率
            # this_fft_fps = 1 / this_fft_page_timestamp
            # # 计算显示帧数量
            # show_page_num = self.config.configget('target_fps')/this_fft_fps
            show_page_num = self.config.configget('target_fps') * this_fft_page_timestamp
            # 计算显示帧间隔(s)
            show_page_timestamp = 1 / self.config.configget('target_fps')
            # print(show_page_timestamp)
            self._interpolate(data,self.last_data,show_page_num,show_page_timestamp)

        self.last_data = data

    def _interpolate(self,data,last_data, show_page_num , show_page_timestamp):
        """
        线性插值计算当前帧数据
        """
        last_timestamp, last_x, last_y = last_data
        now_timestamp, now_x, now_y = data

        # 预转换numpy数组（保持float32精度提升性能）
        last_y = np.asarray(last_y, dtype=np.float32)
        now_y = np.asarray(now_y, dtype=np.float32)

        # 生成标准化时间轴（避免切片操作）
        num_points = int(show_page_num)
        ratios = np.linspace(0, 1, num_points + 2, dtype=np.float32)[1:-1]

        # 向量化计算（核心优化）
        time_stamps = now_timestamp + np.arange(num_points) * show_page_timestamp
        interpolated = last_y * (1 - ratios[:, None]) + now_y * ratios[:, None]

        # 批量提交到缓冲区
        self.data_buffer.extend(
            (ts, now_x, y)
            for ts, y in zip(time_stamps, interpolated)
        )



    def _process_buffer(self):
        """
        处理缓冲区数据
        """
        if not self.data_buffer:  # <-- 关键！防止空缓冲区访问

            return
        page_timestamp, x, y = self.data_buffer[0]
        now_timestamp_c = page_timestamp - time.time()

        # 等待帧
        if now_timestamp_c > 0:
            return
        # 帧超时则不渲染
        if now_timestamp_c >= -self.skip_page_time:
            self.update_bars(x, y)

        self.data_buffer.popleft()

    def _update_peaks(self, x, current_heights):
        """
        更新峰值横条位置
        """
        if not self.config.configget('peak_bars_show'):
            if self.peak_bars.isVisible():
                self.peak_bars.hide()
            return
        if not self.peak_bars.isVisible():
            self.peak_bars.show()
        # 计算时间差
        now = time.time()
        dt = now - self.last_peak_update
        self.last_peak_update = now
        # 将当前高度数组转换为numpy
        # print(type(current_heights))
        # current = np.asarray(current_heights, dtype=np.float32)


        # 两种更新逻辑：
        # 1. 当前高度超过峰值时：直接设置为当前高度
        # 2. 当前低于峰值时：按时间匀速下降
        mask = current_heights > self.peak_heights
        self.peak_heights[mask] = current_heights[mask]  # 当前值超过峰值时顶起
        self.peak_velocities[mask] = 0

        # 修改以下部分实现自由落体物理
        _mask = ~mask
        speed = self.config.configget('peak_decay_speed_g') * dt # 下落的加速度值（像素/秒²）
        # 应用重力加速度
        self.peak_velocities[_mask] +=  speed

        # 根据速度更新位置（使用位移公式 Δy = v * dt）
        self.peak_heights[_mask] -= self.peak_velocities[_mask] * dt

        # 防止下溢
        np.clip(self.peak_heights, self.y_b - 5, self.y_t + 5, out=self.peak_heights)


        # 更新峰值条位置（x与主柱子一致）
        if self.peak_bars:
            height = self.config.configget('peak_h')
            self.peak_bars.setOpts(

                x=x,  # 使用与主柱子相同的x坐标
                height = height,  # 横条固定高度
                y=self.peak_heights + height,  # y位置为中心对齐（高度3）
                width = self.config.configget('peak_bars_width'),
                brush=self.peak_color.get_color(),
            )

    def _update_balls(self, x, y):
        """
        向量化优化的粒子系统
        """
        if not self.config.configget('ball_show'):
            if hasattr(self, 'scatter') and hasattr(self, 'balls'):
                # 重置粒子系统为向量化结构
                self.balls = {
                    'channel_index': np.array([], dtype=np.int32),
                    'x_pos': np.array([], dtype=np.float32),
                    'y_pos': np.array([], dtype=np.float32),
                    'speed': np.array([], dtype=np.float32),
                    'life': np.array([], dtype=np.int32)
                }
                self.scatter.clear()
            return

        # 初始化历史数据
        if not hasattr(self, 'prev_y'):
            self.prev_y = np.zeros_like(y)
            self.active_channels = np.zeros(len(y), dtype=bool)
            # 确保粒子系统是向量化结构
            if not hasattr(self, 'balls') or not isinstance(self.balls, dict):
                self.balls = {
                    'channel_index': np.array([], dtype=np.int32),
                    'x_pos': np.array([], dtype=np.float32),
                    'y_pos': np.array([], dtype=np.float32),
                    'speed': np.array([], dtype=np.float32),
                    'life': np.array([], dtype=np.int32)
                }

        # 转换为numpy数组
        current_y = np.asarray(y, dtype=np.float32)
        delta_y = current_y - self.prev_y

        # 触发粒子发射的条件 - 向量化计算
        trigger_mask = (
                self.active_channels &
                ((delta_y < self.config.configget('emit_threshold2')) | (delta_y < 0)) &
                (current_y > self.y_b)
        )
        trigger_indices = np.where(trigger_mask)[0]

        # 向量化添加新粒子
        if trigger_indices.size > 0:
            new_particles = {
                'channel_index': trigger_indices,
                'x_pos': x[trigger_indices],
                'y_pos': current_y[trigger_indices] + 1,
                'speed': np.full(trigger_indices.size, self.config.configget('ball_speed'), dtype=np.float32),
                'life': np.zeros(trigger_indices.size, dtype=np.int32)
            }

            # 合并新粒子到现有粒子系统
            for key in self.balls:
                self.balls[key] = np.concatenate([self.balls[key], new_particles[key]])

        # 更新激活状态
        np.greater_equal(delta_y, self.config.configget('emit_threshold'), out=self.active_channels)

        # 向量化更新粒子位置
        if self.balls['channel_index'].size > 0:
            # 更新位置和生命值
            self.balls['y_pos'] += self.balls['speed']
            self.balls['life'] += 1

            # 更新x坐标（根据当前柱子位置）
            self.balls['x_pos'] = x[self.balls['channel_index']]

            # 过滤超出视野的粒子
            view_range = self.plot.getViewBox().viewRange()
            y_max = view_range[1][1] + 50
            valid_mask = self.balls['y_pos'] < y_max

            # 应用过滤
            for key in self.balls:
                self.balls[key] = self.balls[key][valid_mask]

        # 创建散点图（如果不存在）
        if not hasattr(self, 'scatter'):
            self.scatter = pg.ScatterPlotItem(
                size=self.config.configget('ball_size'),
                brush=self.balls_color.get_color(),
                pen=None,
                useCache=True,
                pxMode=True
            )
            self.plot.addItem(self.scatter)

        # 批量更新散点数据
        if self.balls['channel_index'].size > 0:
            self.scatter.setData(
                self.balls['x_pos'],
                self.balls['y_pos'],
                size=self.config.configget('ball_size'),
                brush=self.balls_color.get_color(),
            )
        else:
            self.scatter.clear()

        # 保存当前y值
        np.copyto(self.prev_y, current_y)
    def _update_volume(self,):
        print(f"当前音量(L): {self.left_volume_value.value:.1f}% | (R): {self.right_volume_value.value:.1f}%")

    def init_tray(self):
        # 创建系统托盘图标
        self.tray = QtWidgets.QSystemTrayIcon(self)
        self.tray.setIcon(QtGui.QIcon(get_res_path("icos/logo.ico")))
        self.tray.setToolTip(APP_NAME)


        # 创建右键菜单
        tray_menu = QtWidgets.QMenu()

        tray_menu.addSeparator()

        quit_action = tray_menu.addAction("选项")

        quit_action.triggered.connect(
            lambda :self.open_main_win.put(None)
        )

        # 分隔线
        tray_menu.addSeparator()
        # 锁定窗口菜单项
        self.lock_action = QAction("锁定窗口", self)
        self.lock_action.setCheckable(True)
        self.lock_action.triggered.connect(self.toggle_lock)
        tray_menu.addAction(self.lock_action)
        self.lock_action.setChecked(True)
        self.toggle_lock(True)

        tray_menu.addSeparator()
        # 置顶窗口菜单项
        self.topmost_action = QAction("置顶窗口", self)
        self.topmost_action.setCheckable(True)
        self.topmost_action.triggered.connect(self.toggle_topmost)
        tray_menu.addAction(self.topmost_action)
        self.topmost_action.setChecked(self.config.configget('win_top'))
        self.toggle_topmost(self.config.configget('win_top'))


        self.wallpaper_action = QAction("壁纸模式", self)
        self.wallpaper_action.setCheckable(True)
        self.wallpaper_action.triggered.connect(
            self.set_wallpaper_checked
        )
        tray_menu.addAction(self.wallpaper_action)
        self.wallpaper_action.setChecked(self.config.configget('win_wallpaper'))
        QTimer.singleShot(50, lambda :self.set_as_wallpaper(first = True))

        tray_menu.addSeparator()

        self.wallpaper_action_fill_screen = QAction("壁纸全屏", self)
        self.wallpaper_action_fill_screen.setCheckable(True)
        self.wallpaper_action_fill_screen.triggered.connect(self.set_wallpaper_full_screen)
        tray_menu.addAction(self.wallpaper_action_fill_screen)
        self.wallpaper_action_fill_screen.setChecked(self.config.configget('win_wallpaper_full_screen'))

        # quit_action = tray_menu.addAction("壁纸偏移")
        # quit_action.triggered.connect(self.set_wallpaper_offset)
        tray_menu.addSeparator()
        # 重启
        quit_action = tray_menu.addAction("重启")
        quit_action.triggered.connect(lambda :self.win_quit_queue.put("restart"))
        # 退出菜单项


        quit_action = tray_menu.addAction("退出")
        def quit_func():
            self.win_quit_queue.put("quit")
        quit_action.triggered.connect(quit_func)

        self.tray.setContextMenu(tray_menu)
        self.tray.show()
        # 托盘图标点击事件
        self.tray.activated.connect(self.tray_activated)

    def enter_edit_mode(self):
        super().enter_edit_mode()

    def set_config_into_wallpaper_func(self,value):
        self.config.configset('win_wallpaper', value)

    def toggle_lock(self, checked = None):
        """切换窗口锁定状态"""

        if checked:
            # 锁定状态
            self.exit_edit_mode()

        else:
            self.enter_edit_mode()

        self.toggle_topmost(self.config.configget('win_top'))

    def keyPressEvent(self, event):
        """小键盘方向键微调窗口位置（新增功能）"""
        # print(event.key(),)
        x, y = self.x(), self.y()
        step = 1  # 微调步长

        if event.key() == QtCore.Qt.Key_Left:
            self.move(x - step, y)
        elif event.key() == QtCore.Qt.Key_Right:
            self.move(x + step, y)
        elif event.key() == QtCore.Qt.Key_Up:
            self.move(x, y - step)
        elif event.key() == QtCore.Qt.Key_Down:
            self.move(x, y + step)

        event.accept()

    def changeEvent(self, event):
        super().changeEvent(event)
        print('window_change_event')

    def toggle_topmost(self, checked = None):
        """切换窗口置顶状态"""
        if checked is not None:
            self.config.configset('win_top', checked)
        else:
            checked = self.config.configget('win_top')
        self.on_top(checked)
        if not checked:
            self.set_windows_bottom()

    def _load_config(self):
        self.resize(*self.config.configget('win_size'))
        win_xy = self.config.configget('win_xy')
        self.true_xy = win_xy
        if win_xy:
            win_xy = self.apply_wallpaper_xy_offset(win_xy)
            self.move(*win_xy)

    def _save_config(self):
        if not self.lock_status:
            self.true_xy = self.x(), self.y()
        self.config.configset('win_xy', self.true_xy)
        self.config.configset('win_size', (self.width(), self.height()))

    def set_wallpaper_checked(self, checked = None):
        self.config.configset("win_wallpaper", checked)
        self.set_as_wallpaper(checked)

    def set_wallpaper_full_screen(self, checked = None):
        if checked is not None:
            if self.is_edit_mode:
                # 禁止在移动模式下更改壁纸模式
                QMessageBox.warning(self, "警告", "请先完成窗口移动，再切换壁纸全屏模式。")
                self.wallpaper_action_fill_screen.setChecked(self.config.configget('win_wallpaper_full_screen'))
                return
            self.config.configset('win_wallpaper_full_screen', checked)
        if self.config.configget('win_wallpaper'):
            self.set_as_wallpaper(False)
            self.set_as_wallpaper(True)


    def set_as_wallpaper(self,*args, **kwargs):
        super().set_as_wallpaper(
            *args,
            full_screen=self.config.configget('win_wallpaper_full_screen'),
            **kwargs
        )
        self.on_top(self.config.configget('win_top'))


    def set_windows_bottom(self):
        """置窗口在屏幕底部"""
        window = self.windowHandle()
        if window:
            # 定义Windows API常量
            HWND_BOTTOM = wintypes.HWND(1)  # 关键修正：正确类型转换
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOACTIVATE = 0x0010

            # 获取有效窗口句柄
            hwnd = wintypes.HWND(int(window.winId()))  # 类型安全转换

            # 调用系统API
            ctypes.windll.user32.SetWindowPos(
                hwnd,
                HWND_BOTTOM,
                0, 0, 0, 0,
                SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
            )
    def tray_activated(self, reason):
        """托盘图标激活事件"""
        if reason != QtWidgets.QSystemTrayIcon.ActivationReason.Trigger:
            return
        self.open_main_win.put(None)