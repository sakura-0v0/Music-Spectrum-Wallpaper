import ctypes
import threading
import time
from collections import deque
from ctypes import wintypes
from typing import Callable

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import QTimer, pyqtSignal
from PyQt5.QtWidgets import QMessageBox
from pyqtgraph.Qt import QtCore, QtGui

from config import APP_NAME
from config_multiprocess import ConfigInMainProcessPipe
from config_win import show_config
from count_fps import CountFps
from pyqtgraph.Qt import QtWidgets

from get_res import get_res_path
from style import style
from tools import restart

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
                y = item['y']
                color = item['color']
                gradient.setColorAt(y, self.run_func2(*color))
            return self.run_func3(gradient)


            return

        if self.last_color_config != self.get_color_config():
            self.last_color_config = self.get_color_config()
            self.color = _get_color()
        return self.color





class Show(QtCore.QObject):
    quit_signal = pyqtSignal()
    def __init__(
            self,
            config,
            maxsize_window,
            fill_screen_window,
            win_quit_queue,
            restart_queue,
    ):
        super().__init__()
        # 初始化图形界面
        self.config = config
        self.maxsize_window = maxsize_window
        self.fill_screen_window = fill_screen_window
        self.win_quit_queue = win_quit_queue
        self.restart_queue = restart_queue

        self.app = pg.mkQApp(APP_NAME)
        self.fps = CountFps("显示")
        fmt = QtGui.QSurfaceFormat()
        fmt.setSwapInterval(0)  # 关键参数：0=禁用VSync, 1=启用VSync
        fmt.setRenderableType(QtGui.QSurfaceFormat.OpenGL)
        QtGui.QSurfaceFormat.setDefaultFormat(fmt)
        pg.setConfigOptions(
            useOpenGL=True,
            # enableExperimental=True
            background=None
        )

        self.win = pg.GraphicsLayoutWidget(
            # show=True,
        )
        self.win.setWindowIcon(QtGui.QIcon(get_res_path("icos/logo.ico")))

        self.min_width = 80
        self.min_height = 50


        self.win.setAttribute(QtCore.Qt.WA_TranslucentBackground)


        palette = self.win.palette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor(0, 0, 0, 0))
        self.win.setPalette(palette)

        self.win.setWindowFlags(
            QtCore.Qt.FramelessWindowHint |
            # QtCore.Qt.WindowStaysOnTopHint |  # 确保窗口在最前
            QtCore.Qt.Tool  # 添加Tool标志，这有助于无边框窗口显示
        )
        self.mouse_state = None
        self.win.resize(*config.configget('win_size'))
        if config.configget('win_xy'):
            self.win.move(*config.configget('win_xy'))
        self.win.show()
        self.win.raise_()
        self.win.activateWindow()
        self.init_ui()
        self.init_tray()

        self.win.changeEvent = self.window_change_event

    def init_ui(self):

        self.max_db = 20 * np.log10((2 ** 16-1) * 1024 / 2)
        self.y_t= self.max_db * self.config.configget('gradient_max_height')
        self.y_b = self.max_db * self.config.configget('gradient_min_height')
        # 创建全局渐变
        # self.gradient = QtGui.QLinearGradient(0, self.y_t, 0, self.y_b)  # 从y_max到y_min渐变
        # self.gradient.setColorAt(0, QtGui.QColor(*config.configget('gradient_color_top')))  # 蓝
        # self.gradient.setColorAt(1, QtGui.QColor(*config.configget('gradient_color_bottom')))  # 红

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
        self.axis.setTicks([[(i, str(f)) for i, f in enumerate(self.config.pl)]])
        self.axis.setTicks([])  # 禁用刻度线
        self.axis.setPen(pg.mkPen(width=0))  # 设置轴线为透明

        self.plot = self.win.addPlot(axisItems={'bottom': self.axis})

        self.plot.addItem(self.bars)

        self.plot.setYRange(self.y_b, self.y_t)
        self.plot.setXRange(1, len(self.config.pl) - 2)
        self.plot.setMouseEnabled(x=False, y=False)
        # self.plot.getViewBox().setBackgroundColor(None)

        self.plot.hideAxis('left')  # 隐藏坐标轴


        # 峰值
        # 初始化峰值数组
        self.peak_heights = np.zeros_like(self.config.pl)
        self.peak_velocities = np.zeros(len(self.config.pl))
        # 创建峰值保持条
        self.peak_bars = pg.BarGraphItem(
            x=[],
            height=np.full(len(self.config.pl), 0.01),  # 横条高度固定3像素
            width=self.config.configget('peak_bars_width'),  # 比主柱子略宽
            brush=self.peak_color.get_color(),  # QtGui.QBrush(QtGui.QColor(*config.configget('peak_bars_color'))),  # 半透明白色
            pen=None,
            useOpenGL=True
        )
        self.plot.addItem(self.peak_bars)
        self.peak_heights = np.zeros(len(self.config.pl))  # 新增峰值高度数组
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
        self.quit_signal.connect(self.quit_show, QtCore.Qt.ConnectionType.QueuedConnection | QtCore.Qt.ConnectionType.UniqueConnection)
        threading.Thread(target= self.check_quit).start()

    def check_quit(self):
        self.win_quit_queue.get()
        self.quit_signal.emit()

    def quit_show(self):
        self.app.quit()
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
            # 计算逻辑帧率
            this_fft_fps = 1 / this_fft_page_timestamp
            # 计算显示帧数量
            show_page_num = self.config.configget('target_fps')/this_fft_fps

            # 计算显示帧间隔(s)
            show_page_timestamp = 1 / self.config.configget('target_fps')
            # print(show_page_timestamp)
            self._interpolate(data,self.last_data,show_page_num,show_page_timestamp)

        self.last_data = data

    def _interpolate(self,data,last_data, show_page_num , show_page_timestamp):
        """线性插值计算当前帧数据"""
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
        """处理缓冲区数据"""
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
        """更新峰值横条位置"""
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
        """向量化优化的粒子系统"""
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


    def init_tray(self):
        # 创建系统托盘图标
        self.tray = QtWidgets.QSystemTrayIcon(self.win)
        # 如果没有图标文件，可以使用默认图标
        self.tray.setIcon(QtGui.QIcon(get_res_path("icos/logo.ico")))

        # 创建右键菜单
        tray_menu = QtWidgets.QMenu()
        # 移动窗口菜单项
        self.was_locked = self.config.configget('is_locked')
        self.move_action = QtWidgets.QAction("移动窗口", self.win)
        self.move_action.setCheckable(True)
        self.move_action.triggered.connect(self.enable_move)
        tray_menu.addAction(self.move_action)

        move_reset = tray_menu.addAction("重置位置")
        move_reset.triggered.connect(self.move_reset)

        tray_menu.addSeparator()

        # 锁定窗口菜单项
        self.lock_action = QtWidgets.QAction("锁定窗口", self.win)
        self.lock_action.setCheckable(True)
        self.lock_action.triggered.connect(self.toggle_lock)
        tray_menu.addAction(self.lock_action)
        self.lock_action.setChecked(self.config.configget('is_locked'))
        self.toggle_lock(self.config.configget('is_locked'))

        tray_menu.addSeparator()
        # 置顶窗口菜单项
        self.topmost_action = QtWidgets.QAction("置顶窗口", self.win)
        self.topmost_action.setCheckable(True)
        self.topmost_action.triggered.connect(self.toggle_topmost)
        tray_menu.addAction(self.topmost_action)
        self.topmost_action.setChecked(self.config.configget('win_top'))
        self.toggle_topmost(self.config.configget('win_top'))


        self.wallpaper_action = QtWidgets.QAction("壁纸模式", self.win)
        self.wallpaper_action.setCheckable(True)
        self.wallpaper_action.triggered.connect(self.set_as_wallpaper)
        tray_menu.addAction(self.wallpaper_action)
        self.wallpaper_action.setChecked(self.config.configget('win_wallpaper'))
        QTimer.singleShot(50, lambda :self.set_as_wallpaper(first = True))

        tray_menu.addSeparator()

        self.wallpaper_action_fill_screen = QtWidgets.QAction("壁纸全屏", self.win)
        self.wallpaper_action_fill_screen.setCheckable(True)
        self.wallpaper_action_fill_screen.triggered.connect(self.set_wallpaper_full_screen)
        tray_menu.addAction(self.wallpaper_action_fill_screen)
        self.wallpaper_action_fill_screen.setChecked(self.config.configget('win_wallpaper_full_screen'))

        quit_action = tray_menu.addAction("壁纸偏移")
        quit_action.triggered.connect(self.set_wallpaper_offset)

        tray_menu.addSeparator()
        quit_action = tray_menu.addAction("选项")

        quit_action.triggered.connect(lambda :show_config(
            self.config,
            self.maxsize_window,
            self.fill_screen_window,
            self.restart_queue,
        ))

        # 分隔线
        tray_menu.addSeparator()

        # 重启
        quit_action = tray_menu.addAction("重启")
        quit_action.triggered.connect(lambda :self.restart_queue.put("restart"))
        # 退出菜单项


        quit_action = tray_menu.addAction("退出")
        def quit_func():
            self.win_quit_queue.put(None)
        quit_action.triggered.connect(quit_func)

        self.tray.setContextMenu(tray_menu)
        self.tray.show()

        # 托盘图标点击事件
        self.tray.activated.connect(self.tray_activated)
    def toggle_lock(self, checked = None):
        """切换窗口锁定状态"""
        if checked is not None:
            self.config.configset('is_locked', checked)
        # 获取当前窗口标志（包含已有的置顶设置）
        current_flags = self.win.windowFlags()

        # 核心修改：通过窗口标记控制输入接收
        if self.config.configget('is_locked'):
            new_flags = (current_flags |  # 保留原有设置
                         QtCore.Qt.WindowTransparentForInput |  # 透明化输入
                         QtCore.Qt.WindowDoesNotAcceptFocus)  # 禁止获取焦点
        else:
            new_flags = (current_flags &
                         ~QtCore.Qt.WindowTransparentForInput &  # 恢复输入
                         ~QtCore.Qt.WindowDoesNotAcceptFocus)  # 允许焦点

        self.win.setWindowFlags(new_flags)
        # 重新显示窗口以应用新的窗口标志
        self.win.show()
        self.toggle_topmost(self.config.configget('win_top'))

    def move_reset(self):
        def handle_result(button):
            if button == QMessageBox.Yes:
                self.config.configreset('win_xy')
                restart(self.win_quit_queue)
        msg_box = QMessageBox()
        msg_box.setWindowIcon(QtGui.QIcon(get_res_path("icos/logo.ico")))
        msg_box.setWindowTitle("重置提示")  # 标题
        msg_box.setText("确定要重置窗口位置吗？")  # 提示内容
        msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        self.app.setQuitOnLastWindowClosed(False)
        # 独立事件循环管理
        loop = QtCore.QEventLoop()
        msg_box.finished.connect(loop.quit)
        msg_box.buttonClicked.connect(lambda btn: handle_result(msg_box.standardButton(btn)))
        msg_box.show()
        loop.exec_()  # 局部事件循环
        self.app.setQuitOnLastWindowClosed(True)  # 恢复默认设置

    def enable_move(self,checked):
        """启用窗口移动功能"""
        # 暂时解锁窗口以便移动
        if checked:
            if self.config.configget('win_wallpaper'):
                self.set_as_wallpaper(move_open=True)
            self.was_locked = self.config.configget('is_locked')
            if self.config.configget('is_locked'):
                self.toggle_lock(False)

            # 显示提示信息
            self.tray.showMessage("窗口移动", "现在可以拖动窗口移动位置，点击完成移动",
                                  QtWidgets.QSystemTrayIcon.Information, 2000)

            # 启用鼠标事件跟踪
            self.win.setMouseTracking(True)
            self.margin = 8  # 边缘检测范围
            self.mouse_state = 'normal'  # 新增状态标识：normal/moving/resizing

            self.win.mousePressEvent = self.mouse_press_event
            self.win.mouseMoveEvent = self.mouse_move_event
            self.win.mouseReleaseEvent = self.mouse_release_event

            palette = self.win.palette()
            palette.setColor(QtGui.QPalette.Window, QtGui.QColor(0, 0, 0, 100))  # 半透明黑色
            self.win.setPalette(palette)
            self.win.update()  # 立即刷新界面
        else:

            self.dragging = False
            self.finish_move(self.was_locked)
            if self.was_locked:
                self.toggle_lock(True)
            if self.config.configget('win_wallpaper'):
                self.set_as_wallpaper()
    def get_resize_edge(self, pos):
        """根据鼠标位置判断是否在边缘区域"""
        rect = self.win.rect()
        edge = []
        if pos.x() < self.margin: edge.append('left')
        elif pos.x() > rect.width()-self.margin: edge.append('right')
        if pos.y() < self.margin: edge.append('top')
        elif pos.y() > rect.height()-self.margin: edge.append('bottom')
        return edge
    def finish_move(self, was_locked):
        """完成窗口移动"""
        # 恢复鼠标事件
        self.win.mousePressEvent = None
        self.win.mouseMoveEvent = None
        self.win.mouseReleaseEvent = None
        self.mouse_state = None
        # 恢复透明背景
        palette = self.win.palette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor(0, 0, 0, 0))  # 完全透明
        self.win.setPalette(palette)
        self.win.update()
        # 返回窗口的几何信息（包含位置和大小）: QRect(x, y, width, height)
        geometry = self.win.geometry()

        # 提取位置和大小
        x = geometry.x()
        y = geometry.y()
        width = geometry.width()
        height = geometry.height()
        self.config.configset(
            'win_size',
            (width, height)
        )
        self.config.configset(
            'win_xy',
            (x, y)
        )

        # 如果之前是锁定状态，恢复锁定
        if was_locked:
            self.toggle_lock(True)


    def mouse_press_event(self, event):
        """鼠标按下事件 - 用于窗口移动"""
        if not (event.button() == QtCore.Qt.LeftButton):
            return
        resize_edge = self.get_resize_edge(event.pos())
        if resize_edge:
            self.mouse_state = 'resizing'
            self.resize_edge = resize_edge
            self.start_geometry = self.win.geometry()
            self.start_pos = event.pos()  # 改用窗口相对坐标
            self.start_global_pos = event.globalPos()  # 保留全局坐标
        else:
            self.mouse_state = 'moving'
            self.dragging = True
            self.drag_position = event.globalPos() - self.win.frameGeometry().topLeft()

        event.accept()

    def mouse_move_event(self, event):
        """鼠标移动事件 - 用于窗口移动"""
        if self.mouse_state == 'moving':
            if self.dragging and event.buttons() & QtCore.Qt.LeftButton:
                self.win.move(event.globalPos() - self.drag_position)
                event.accept()

        elif self.mouse_state == 'resizing':
            # 新增缩放逻辑
            pos = event.pos()
            global_pos = event.globalPos()

            # 计算相对移动量（基于窗口坐标系）
            delta = pos - self.start_pos

            # 计算基于全局坐标的增量
            global_delta = global_pos - self.start_global_pos

            new_geo = self.start_geometry

            if 'left' in self.resize_edge:
                new_geo.setLeft(new_geo.left() + global_delta.x())
            if 'right' in self.resize_edge:
                new_geo.setRight(new_geo.right() + global_delta.x())
            if 'top' in self.resize_edge:
                new_geo.setTop(new_geo.top() + global_delta.y())
            if 'bottom' in self.resize_edge:
                new_geo.setBottom(new_geo.bottom() + global_delta.y())
            # 限制最小尺寸（可选）
            if new_geo.width() < self.min_width:
                if 'left' in self.resize_edge:
                    new_geo.setLeft(new_geo.right() - 100)
                else:
                    new_geo.setRight(new_geo.left() + 100)
            if new_geo.height() < self.min_height:
                if 'top' in self.resize_edge:
                    new_geo.setTop(new_geo.bottom() - 50)
                else:
                    new_geo.setBottom(new_geo.top() + 50)
            self.win.setGeometry(new_geo)
            self.start_global_pos = global_pos
            event.accept()

        elif self.mouse_state:
            # 更新鼠标形状
            edge = self.get_resize_edge(event.pos())
            cursor = QtCore.Qt.ArrowCursor
            if edge:
                if {'left', 'top'} <= set(edge):
                    cursor = QtCore.Qt.SizeFDiagCursor  # 左上-右下
                elif {'right', 'bottom'} <= set(edge):
                    cursor = QtCore.Qt.SizeFDiagCursor  # 右下-左上
                elif {'right', 'top'} <= set(edge):
                    cursor = QtCore.Qt.SizeBDiagCursor  # 右上-左下
                elif {'left', 'bottom'} <= set(edge):
                    cursor = QtCore.Qt.SizeBDiagCursor  # 左下-右上
                elif 'left' in edge or 'right' in edge:
                    cursor = QtCore.Qt.SizeHorCursor
                elif 'top' in edge or 'bottom' in edge:
                    cursor = QtCore.Qt.SizeVerCursor
            else:
                cursor = QtCore.Qt.SizeAllCursor

            self.win.setCursor(cursor)

    def mouse_release_event(self, event):
        """鼠标释放事件 - 用于窗口移动"""
        if event.button() == QtCore.Qt.LeftButton:
            self.mouse_state = 'normal'
            event.accept()
        # if event.button() == QtCore.Qt.LeftButton:
        #     self.dragging = False
        #     event.accept()
        #     # 调用完成移动的回调
        #     if hasattr(self, 'move_callback'):
        #         self.move_callback()

    def window_change_event(self, event):
        print('window_change_event')

    def toggle_topmost(self, checked = None):
        """切换窗口置顶状态"""
        if checked is not None:
            self.config.configset('win_top', checked)
        if self.config.configget('win_top'):
            # 置顶窗口
            self.win.setWindowFlags(self.win.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)
            # self.topmost_action.setText("取消置顶")
        else:
            # 取消置顶
            # self.win.setWindowFlags(self.win.windowFlags() & ~QtCore.Qt.WindowStaysOnTopHint)
            # self.topmost_action.setText("置顶窗口")
            flags = self.win.windowFlags()
            flags &= ~QtCore.Qt.WindowStaysOnTopHint  # 移除置顶标志
            # flags |= QtCore.Qt.Tool  # 确保工具窗口标志存在
            self.win.setWindowFlags(flags)

        # 重新显示窗口以应用新的窗口标志
        self.win.show()


        if not self.config.configget('win_top'):
            self.set_windows_bottom()


    def set_as_wallpaper(
            self,
            checked = None,
            reset = False,
            first = False,
            move_open = False,
    ):
        """将窗口设置为壁纸（位于桌面图标下方）"""
        # 获取窗口句柄
        if checked is not None:
            if self.mouse_state:
                # 禁止在移动模式下更改壁纸模式
                QMessageBox.warning(self.win, "警告", "请先完成窗口移动，再切换壁纸模式。")
                self.wallpaper_action.setChecked(self.config.configget('win_wallpaper'))
                return
            self.config.configset('win_wallpaper', checked)
        hwnd = int(self.win.winId())
        if not self.config.configget('win_wallpaper') or move_open:
            if not hasattr(self,'original_parent'):
                return
            # 恢复父窗口关系
            ctypes.windll.user32.SetParent(hwnd, self.original_parent)

            # 还原窗口样式
            ctypes.windll.user32.SetWindowLongW(hwnd, -20, self.original_exstyle)
            self.win.setAttribute(QtCore.Qt.WA_TranslucentBackground)

            palette = self.win.palette()
            palette.setColor(QtGui.QPalette.Window, QtGui.QColor(0, 0, 0, 0))
            self.win.setPalette(palette)
            self.win.setWindowFlags(
                QtCore.Qt.FramelessWindowHint |
                # QtCore.Qt.WindowStaysOnTopHint |  # 确保窗口在最前
                QtCore.Qt.Tool  # 添加Tool标志，这有助于无边框窗口显示
            )
            self.win.resize(*self.config.configget('win_size'))
            if self.config.configget('win_xy'):
                self.win.move(*self.config.configget('win_xy'))
            self.toggle_lock()
            self.toggle_topmost()
            self.win.show()
            self.win.raise_()
            self.win.activateWindow()
            return
        self.original_exstyle = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
        self.original_parent = ctypes.windll.user32.GetParent(hwnd)
        # 定义Windows API常量
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_NOACTIVATE = 0x08000000

        # 设置窗口扩展样式
        ctypes.windll.user32.SetWindowLongW(
            hwnd,
            GWL_EXSTYLE,
            WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        )

        # 获取桌面窗口句柄
        progman = ctypes.windll.user32.FindWindowW("Progman", "Program Manager")

        # 发送特殊消息创建WorkerW窗口
        ctypes.windll.user32.SendMessageTimeoutW(
            progman,
            0x052C,  # 特殊消息ID
            0,
            0,
            0,
            1000,
            ctypes.byref(ctypes.c_ulong())
        )

        # 查找WorkerW窗口
        def enum_windows(hwnd, param):
            # 查找包含"SHELLDLL_DefView"的窗口
            if ctypes.windll.user32.FindWindowExW(hwnd, 0, "SHELLDLL_DefView", None):
                # 找到WorkerW窗口
                workerw = ctypes.windll.user32.FindWindowExW(0, hwnd, "WorkerW", None)
                # 将我们的窗口设置为WorkerW的子窗口
                ctypes.windll.user32.SetParent(param, workerw)

                ctypes.windll.user32.SetWindowPos(
                    hwnd,
                    workerw,  # 放在workerw后面
                    0, 0, 0, 0,
                    0x0001 | 0x0002  # SWP_NOSIZE | SWP_NOMOVE
                )
                return False
            return True

        # 定义回调函数类型
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        enum_windows_proc = WNDENUMPROC(enum_windows)

        # 枚举窗口
        ctypes.windll.user32.EnumWindows(enum_windows_proc, hwnd)
        # 关键修改：确保窗口背景透明
        # 1. 设置窗口背景为透明
        palette = self.win.palette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor(0, 0, 0, 0))  # 完全透明
        self.win.setPalette(palette)
        #
        # 获取窗口当前所在屏幕的物理参数
        if self.config.configget('win_wallpaper_full_screen') or first or not reset:
            current_screen = self.win.screen()  # 获取显示器物理坐标系
            screen_geo = [
                current_screen.geometry().x(),
                current_screen.geometry().y(),
                current_screen.geometry().width(),
                current_screen.geometry().height(),
            ]
        else:
            xy = self.config.configget('win_xy')
            if not xy:
                xy = (0,0)
            screen_geo = [
                *xy,
                *self.config.configget('win_size'),
            ]
        print(screen_geo)
        config_geometry = self.config.configget('win_wallpaper_xywh_offset')
        new_geometry = []
        for index, value in enumerate(config_geometry):
            new_geometry.append(screen_geo[index] + value)
        self.win.setGeometry(*new_geometry)  # 精准对齐物理屏幕边界

        # 更新窗口位置和大小
        self.win.show()
        self.win.raise_()
        self.win.activateWindow()

        if not self.config.configget('win_wallpaper_full_screen') and not reset:
            self.set_as_wallpaper(reset=True)



    def set_wallpaper_full_screen(self, checked = None):
        if checked is not None:
            if self.mouse_state:
                # 禁止在移动模式下更改壁纸模式
                QMessageBox.warning(self.win, "警告", "请先完成窗口移动，再切换壁纸全屏模式。")
                self.wallpaper_action_fill_screen.setChecked(self.config.configget('win_wallpaper_full_screen'))
                return
            self.config.configset('win_wallpaper_full_screen', checked)
        if self.config.configget('win_wallpaper'):
            self.set_as_wallpaper()

    def set_wallpaper_offset(self):
        """壁纸偏移设置窗口"""
        # 创建配置对话框
        dialog = QtWidgets.QDialog()
        dialog.setWindowIcon(QtGui.QIcon(get_res_path("icos/logo.ico")))
        dialog.setWindowTitle("壁纸模式坐标偏移设置 - 将频谱移到目标显示器后再开壁纸模式，即可指定显示器显示")
        dialog.setFixedSize(620, 400)
        dialog.setStyleSheet(style)


        # 创建预览画布
        class PreviewCanvas(QtWidgets.QWidget):
            def __init__(self, config, parent=None):
                super().__init__(parent)
                self.config = config
                self.setMouseTracking(True)

                # 添加刷新定时器（关键代码）
                self.refresh_timer = QtCore.QTimer(self)
                self.refresh_timer.timeout.connect(self._refresh_animation)
                self.refresh_timer.start(10)  # 30帧/秒

            def paintEvent(self, event):
                painter = QtGui.QPainter(self)
                painter.setRenderHint(QtGui.QPainter.Antialiasing)

                # 计算中心矩形区域（占画布60%空间）
                canvas_size = self.size()
                rect_width = canvas_size.width() * 0.6 - 20
                rect_height = canvas_size.height() * 0.6
                rect_x = (canvas_size.width() - rect_width) / 2
                rect_y = (canvas_size.height() - rect_height) / 2
                main_rect = QtCore.QRectF(rect_x, rect_y, rect_width, rect_height)

                # 绘制主矩形
                painter.setPen(QtGui.QPen(QtGui.QColor(200, 200, 200), 2))
                painter.drawRect(main_rect)

                # 绘制频谱条形图
                num_bars = 50  # 条形数量
                bar_spacing = 2  # 条形间距
                bar_width = (rect_width - (num_bars - 1) * bar_spacing) / num_bars

                # 生成模拟频谱数据（正弦波叠加）
                heights = self.generate_spectrum_heights(num_bars, rect_height)

                # 创建渐变效果
                gradient = QtGui.QLinearGradient(0, main_rect.top(), 0, main_rect.bottom())
                gradient_color = self.config.configget('gradient_color')
                if gradient_color:
                    for item in gradient_color:
                        gradient.setColorAt(item['y'], QtGui.QColor(*item['color']))
                else:
                    top = [255, 233, 233, 190]
                    btn = [255, 82 , 140, 190]
                    gradient.setColorAt(0, QtGui.QColor(*top))  # 顶部蓝色
                    gradient.setColorAt(1, QtGui.QColor(*btn))  # 底部绿色

                # 绘制每个条形
                for i in range(num_bars):
                    # 计算条形位置
                    x = main_rect.left() + i * (bar_width + bar_spacing)
                    current_height = heights[i] * rect_height * 0.8  # 高度缩放

                    # 创建条形路径
                    bar_rect = QtCore.QRectF(
                        x,
                        main_rect.bottom() - current_height,
                        bar_width,
                        current_height
                    )

                    # 绘制渐变填充条形
                    painter.fillRect(bar_rect, gradient)

                    # 绘制条形边框
                    painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 50), 0.5))
                    painter.drawRect(bar_rect)

                # 左上角十字准星
                cross_size = 20
                painter.setPen(QtGui.QPen(QtGui.QColor(255, 120, 180), 2))
                painter.drawLine(
                    main_rect.left() - cross_size, main_rect.top(),
                    main_rect.left() + cross_size, main_rect.top()
                )
                painter.drawLine(
                    main_rect.left(), main_rect.top() - cross_size,
                    main_rect.left(), main_rect.top() + cross_size
                )

                # 右下角双向箭头
                arrow_size = 15
                # 横向箭头
                h_arrow = QtCore.QPointF(main_rect.right(), main_rect.bottom() + 30)
                painter.drawLine(h_arrow.x() - arrow_size, h_arrow.y(),
                               h_arrow.x() + arrow_size, h_arrow.y())
                painter.drawPolygon(
                    QtGui.QPolygonF([
                        h_arrow + QtCore.QPointF(arrow_size, 0),
                        h_arrow + QtCore.QPointF(arrow_size/2, -arrow_size/2),
                        h_arrow + QtCore.QPointF(arrow_size/2, arrow_size/2)
                    ])
                )
                painter.drawPolygon(
                    QtGui.QPolygonF([
                        h_arrow + QtCore.QPointF(-arrow_size, 0),  # X轴镜像
                        h_arrow + QtCore.QPointF(-arrow_size / 2, arrow_size / 2),  # Y轴镜像
                        h_arrow + QtCore.QPointF(-arrow_size / 2, -arrow_size / 2)  # Y轴镜像
                    ])
                )

                # 纵向箭头
                v_arrow = QtCore.QPointF(main_rect.right() + 30, main_rect.bottom())
                painter.drawLine(v_arrow.x(), v_arrow.y() - arrow_size,
                               v_arrow.x(), v_arrow.y() + arrow_size)
                painter.drawPolygon(
                    QtGui.QPolygonF([
                        v_arrow + QtCore.QPointF(0, arrow_size),
                        v_arrow + QtCore.QPointF(-arrow_size/2, arrow_size/2),
                        v_arrow + QtCore.QPointF(arrow_size/2, arrow_size/2)
                    ])
                )
                painter.drawPolygon(
                    QtGui.QPolygonF([
                        v_arrow + QtCore.QPointF(0, -arrow_size),
                        v_arrow + QtCore.QPointF(arrow_size/2, -arrow_size/2),
                        v_arrow + QtCore.QPointF(-arrow_size/2, -arrow_size/2)
                    ])
                )

            def generate_spectrum_heights(self, num_bars, max_height):
                """生成动态频谱高度数据"""
                import math
                heights = []
                timestamp = time.time() * 5  # 时间因子产生动画效果

                # 正弦波叠加算法
                for i in range(num_bars):
                    # 基频
                    base = math.sin(i * 0.3 + timestamp) * 0.5 + 0.5

                    # 高频分量
                    high_freq = math.sin(i * 2 + timestamp * 2) * 0.2

                    # 低频分量
                    low_freq = math.sin(i * 0.1 + timestamp * 0.5) * 0.3



                    # 合成高度值
                    height = (base * 0.5 + high_freq + low_freq)
                    height = max(0, min(1.0, height))  # 限制在0-1范围

                    heights.append(height)

                return heights
            def _refresh_animation(self):
                """触发界面刷新"""
                self.update()

        # 创建控件
        preview = PreviewCanvas(self.config, dialog)
        preview.setFixedSize(600, 350)

        # 创建输入框
        input_style = """
            QSpinBox {
                min-width: 80px;
                max-width: 100px;
                border: 1px solid #00FF00;
                background: rgba(0,0,0,150);
                color: #00FF00;
            }
        """

        x_input = QtWidgets.QSpinBox(dialog)  # 关键修改：显式设置父对象
        y_input = QtWidgets.QSpinBox(dialog)
        w_input = QtWidgets.QSpinBox(dialog)
        h_input = QtWidgets.QSpinBox(dialog)

        for box in [x_input, y_input, w_input, h_input]:
            # box.setStyleSheet(input_style)
            box.setRange(-9999, 9999)
            box.setSingleStep(1)

        # 初始化数值
        current_offset = self.config.configget('win_wallpaper_xywh_offset')
        x_input.setValue(current_offset[0])
        y_input.setValue(current_offset[1])
        w_input.setValue(current_offset[2])
        h_input.setValue(current_offset[3])

        # 布局控件
        def reposition_inputs():
            preview_geo = preview.geometry()
            center = preview_geo.center()

            # X输入框：主矩形上方偏移
            x_input.move(center.x() - 130, preview_geo.top() + 20)
            # Y输入框：主矩形左侧偏移
            y_input.move(preview_geo.left(), center.y() - 60)
            # W输入框：主矩形下方偏移
            w_input.move(center.x() + 20, preview_geo.bottom() - 50)
            # H输入框：主矩形右侧偏移
            h_input.move(preview_geo.right() - 115, center.y() + 40)



        # 值变更处理
        def update_offset():
            if self.mouse_state:
                # 禁止在移动模式下更改壁纸模式
                QMessageBox.warning(self.win, "警告", "请先完成窗口移动，再应用壁纸偏移。")
                return
            new_offset = [
                x_input.value(),
                y_input.value(),
                w_input.value(),
                h_input.value()
            ]
            self.config.configset('win_wallpaper_xywh_offset', new_offset)
            if self.config.configget('win_wallpaper'):
                self.set_as_wallpaper()

        # 创建确认按钮
        btn_confirm = QtWidgets.QPushButton("应用")
        btn_confirm.clicked.connect(update_offset)

        # 窗口显示时重新定位输入框
        dialog.showEvent = lambda e: reposition_inputs()

        # 主布局
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.addWidget(preview)
        layout.addWidget(btn_confirm)


        self.app.setQuitOnLastWindowClosed(False)
        # 独立事件循环管理
        loop = QtCore.QEventLoop()
        dialog.finished.connect(loop.quit)
        dialog.show()
        loop.exec_()  # 局部事件循环
        self.app.setQuitOnLastWindowClosed(True)  # 恢复默认设置

    def set_windows_bottom(self):
        """置窗口在屏幕底部"""
        window = self.win.windowHandle()
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
        if reason == QtWidgets.QSystemTrayIcon.DoubleClick:
            # 双击托盘图标显示/隐藏窗口
            if self.win.isVisible():
                self.win.hide()
            else:
                self.win.show()
                self.win.raise_()
                self.win.activateWindow()