# new_config.py
import os
import threading
import traceback
from multiprocessing import Value

from PySide6.QtCore import Qt, Signal, QTimer, QUrl
from PySide6.QtGui import QIcon, QDesktopServices
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDialog, QScrollArea, QComboBox

from xiaoe_ui import (
    MainWin, MainLayout, LeftList,
    CheckItem, ComboItem, SliderItem, ColorItem, GradientItem, BottomItem,
    make_tip, make_line,
    Dialog, SingletonMixin,
    info, error, ask, ThemePage, QPushButtonHandCursor, run_in_main, ClickFrame, BigButton,
    flash_config_widget,
)

from config_objs import config, engine, theme_cfg
from app_info import APP_VERSION, APP_NAME, APP_URL, GITHUB_URL
from fast_desktop import create_lnk, get_startup_path, get_desktop_path
from multiprocess_data_manager import MultiProcessDataManager

RESTART_KEYS = {
    'jump_frame', 'chunk_a', 'driver_chunk',
    'format_num', 'pl_start', 'pl_end', 'log_points',
    'gradient_max_height', 'gradient_min_height',
}

class App(MainWin):
    restart_signal = Signal(bool)
    def __init__(
            self,
            multiprocess_datas: MultiProcessDataManager,
    ):
        super().__init__(
            win_title=f"{APP_NAME}选项",
            scroll=False,
            add_bottom_empty=False,
            add_down_block=True,
            maxsize_btn=False,
            hide_btn=True,
            show_default=False,
            min_w=800,
            min_h=500,
        )
        self.restart_signal.connect(self.set_restart_btn_status)

        self.multiprocess_datas = multiprocess_datas
        self.nees_restart_flag = False
        self.setup_ui()
        self.resize(900, 650)
        self.close_btn.hide()
        self.apply_all()
        self._bind_restart_monitor()
        threading.Thread(
            target=self.check_show_main_win,
            daemon=True,
        ).start()

        self.fps_getter = QTimer(self)
        self.fps_getter.timeout.connect(self.flash_fps)
        self.fps_getter.start(1000)  # 每秒检查一次

    def check_show_main_win(self):
        def func():
            self.show()
            self.activateWindow()
            self.raise_()
        while True:
            self.multiprocess_datas.open_main_win.get()
            run_in_main(func)


    def _bind_restart_monitor(self):
        def on_config_changed(key, value):
            if not self.nees_restart_flag:
                self.nees_restart_flag = True
                self.setWindowTitle(f"{self._win_title} (需要重启)")
                self.restart_btn.setText("需要重启")


        for key in RESTART_KEYS:
            config.on(key, lambda v, k=key: on_config_changed(k, v))

    def add_ui(self):
        layout = MainLayout(self, left_width=185)
        self.left = LeftList(callback_after_select_page=layout.scroll_to_top)

        self._build_home(self.left.add_page("home", "首页", icon="🏠"))
        self._build_quick_start()
        self._build_pause_detection()

        display_grp = self.left.add_group("display_grp", "显示设置", icon="🖥️")
        self._build_axis(display_grp.add_page("axis", "坐标轴", icon="📐"))
        self._build_bars(display_grp.add_page("bars", "柱状图", icon="📊"))
        self._build_peaks(display_grp.add_page("peaks", "峰值指示器", icon="📈"))
        self._build_particles(display_grp.add_page("particles", "粒子效果", icon="✨"))
        self._build_fps_fill(display_grp.add_page("fps_fill", "帧生成", icon="⏱"))

        audio_grp = self.left.add_group("audio_grp", "音频处理", icon="🎵")
        self._build_audio(audio_grp.add_page("audio_main", "采集设置", icon="🎤"))
        self._build_fft_pre(audio_grp.add_page("fft_pre", "FFT预处理", icon="📈"))
        self._build_fft_params(audio_grp.add_page("fft_params", "FFT参数", icon="⚙️"))
        self._build_fft_post(audio_grp.add_page("fft_post", "FFT后处理", icon="📊"))

        self._build_appearance(self.left.add_page("theme", "选项主题设置", icon="✨"))

        self._build_about()

        self._build_bottom()

        self.left.add_stretch_before_left()
        self.left.switch_to("home")

        layout.left_layout.addLayout(self.left.left_layout)
        layout.right_layout.addWidget(self.left.stack)

    # ---------- 首页 ----------
    def _build_home(self, page):
        up_layout = QVBoxLayout()
        up_layout.setAlignment(Qt.AlignCenter)
        up_layout.setSpacing(5)
        page.addLayout(up_layout, 1)

        title_frame = ClickFrame(
            tooltip="点击进入软件官网",
        )
        title_frame.on_left_click(
            lambda: QDesktopServices.openUrl(QUrl(APP_URL)))
        title_layout = QHBoxLayout(title_frame)
        logo_label = QLabel()
        icon = QIcon(self._icon_source)
        pix = icon.pixmap(100, 100)
        logo_label.setPixmap(pix)
        title_layout.addWidget(logo_label)

        title_label = QLabel(APP_NAME)
        title_label.setProperty("class", "app_title")
        title_layout.addWidget(title_label)


        up_layout.addWidget(title_frame)
        sub = QLabel(f"v{APP_VERSION}")
        sub.setProperty("class", "section_title")
        sub.setAlignment(Qt.AlignCenter)
        up_layout.addWidget(sub)


        github_frame = ClickFrame(
            tooltip="点击进入软件GitHub界面",
        )
        github_frame.on_left_click(
            lambda: QDesktopServices.openUrl(QUrl(GITHUB_URL)))
        up_layout.addWidget(github_frame)

        github_url = QLabel("GitHub: Music-Spectrum-Wallpaper")
        github_url.setProperty("class", "tip-text")
        github_url.setAlignment(Qt.AlignCenter)
        github_layout = QHBoxLayout(github_frame)
        github_layout.setContentsMargins(10, 15, 10, 15)
        github_layout.addWidget(github_url)

        # page.addStretch(1)



        #  快捷操作按钮
        down_btns_map = (
            (
                ("🔄 帧率设置", lambda :(self.left.switch_to("fft_params"),flash_config_widget("目标帧率"))),
                ("📊 渐变设置", lambda: (self.left.switch_to("bars"), flash_config_widget("渐变色"))),
            ),
        )

        down_fast_ctrl_layout = QVBoxLayout()
        page.addLayout(down_fast_ctrl_layout)
        for item in down_btns_map:
            line_layout = QHBoxLayout()
            down_fast_ctrl_layout.addLayout(line_layout)
            for btn_info in item:
                text = btn_info[0]
                callback = btn_info[1]
                btn = BigButton(
                    text = text,
                    click_cb=callback,
                )
                line_layout.addWidget(btn)

    # ---------- 快速启动 ----------
    def _build_quick_start(self):
        page = self.left.add_page("quick", "启动设置", icon="🚀")
        make_tip("创建快捷方式或设置开机自启", parent_layout=page)
        make_line(page, False)
        BottomItem("创建桌面快捷方式", text="点击创建桌面快捷方式",
                   btn_text="创建",
                   callback=self._create_desktop_lnk,
                   parent_layout=page)
        BottomItem("设置开机自启", text="开启或关闭开机自启",
                   btn_text="开启",
                   callback=self._enable_startup,
                   reset_callback=self._disable_startup,
                   parent_layout=page)
        page.addStretch(1)

    def _create_desktop_lnk(self):
        if ask("确认", "是否创建桌面快捷方式？"):
            try:
                create_lnk(APP_NAME, APP_NAME, get_desktop_path())
                info("成功", "桌面快捷方式已创建")
            except Exception as e:
                error("错误", f"创建失败：{e}")

    def _enable_startup(self):
        if ask("确认", "是否设置开机自启？"):
            try:
                create_lnk(APP_NAME, APP_NAME, get_startup_path())
                info("成功", "已设置开机自启")
            except Exception as e:
                error("错误", f"设置失败：{e}")

    def _disable_startup(self):
        if ask("确认", "是否取消开机自启？"):
            try:
                os.remove(os.path.join(get_startup_path(), f"{APP_NAME}.lnk"))
                info("成功", "已取消开机自启")
            except FileNotFoundError:
                info("提示", "未发现开机自启快捷方式")
            except Exception as e:
                error("错误", f"移除失败：{e}")

    # ---------- 暂停检测 ----------
    def _build_pause_detection(self):
        page = self.left.add_page("pause", "暂停检测", icon="⏸")
        CheckItem("最大化暂停",
                  text="前台软件最大化时暂停软件",
                  config=config,
                  config_name="maximized_screen_detect",
                  parent_layout=page)
        BottomItem("最大排除窗口", text="这里的窗口不触发暂停",
                   btn_text="设置",
                   callback=lambda: self._show_exclude_window_dialog("exclude_window_maximize", "最大化"),
                   parent_layout=page)
        make_line(page, False)
        CheckItem("全屏暂停",
                  text="存在全屏软件时暂停软件",
                  config=config, config_name="full_screen_detect",
                  parent_layout=page)
        BottomItem("全屏排除窗口", text="这里的窗口不触发暂停",
                   btn_text="设置",
                   callback=lambda: self._show_exclude_window_dialog("exclude_window", "全屏"),
                   parent_layout=page)
        make_line(page, False)
        SliderItem("轮询间隔",
                   text="暂停检测的轮询间隔",
                   config=config, config_name="screen_detect_time",
                   config_range=(0.5, 15.0), step=0.5,
                   num_type_text="s",
                   parent_layout=page)
        page.addStretch(1)

    def _show_exclude_window_dialog(self, config_key: str, win_type: str):
        key = f"exclude_dlg_{config_key}"
        existing = SingletonMixin.get_singleton(key)
        if existing:
            existing.activateWindow()
            return
        if config_key == 'exclude_window':
            checked_list = self.multiprocess_datas.fill_screen_window
        elif config_key == 'exclude_window_maximize':
            checked_list = self.multiprocess_datas.maxsize_window
        else:
            checked_list = []
        class ExcludeDialog(Dialog, SingletonMixin):
            def __init__(self, parent, cfg_key, win_type):
                Dialog.__init__(self, parent=parent, win_title=f"排除{win_type}窗口",
                                width=450, height=500, modal=False, set_fixed_size = False, )
                SingletonMixin._singleton_init(self, key, only_one=True)
                self.cfg_key = cfg_key
                self.win_type = win_type
                self._init_ui()
                self._refresh_list()

            def _init_ui(self):
                layout = self.root_layout
                layout.setSpacing(15)
                add_row = QHBoxLayout()
                self.combo = QComboBox()
                self.combo.addItems([win for win in checked_list if win.strip()])
                self.combo.setEditable(True)

                add_row.addWidget(self.combo, 1)
                add_btn = QPushButton("添加")
                add_btn.clicked.connect(self._add_window)
                add_row.addWidget(add_btn)
                layout.addLayout(add_row)

                tip = QLabel(f"可以在下拉菜单中选择后，二次编辑再添加\n\n"
                             f"窗口标题包含以下字符的窗口，在{win_type}时不会触发暂停")
                tip.setProperty("class", "tip-text")
                layout.addWidget(tip)

                self.scroll = QScrollArea()
                self.scroll.setWidgetResizable(True)
                self.list_widget = QWidget()
                self.list_widget.setProperty("class", "root-no-background")
                self.list_layout = QVBoxLayout(self.list_widget)
                self.scroll.setWidget(self.list_widget)
                layout.addWidget(self.scroll)

                close_btn = QPushButton("关闭")
                close_btn.clicked.connect(self.close)
                layout.addWidget(close_btn)

            def _refresh_list(self):
                while self.list_layout.count():
                    item = self.list_layout.takeAt(0)
                    if item.widget():
                        item.widget().deleteLater()
                current_list = config.get(self.cfg_key) or []
                for window in current_list:
                    item_widget = ClickFrame(
                        custom_class="light-line disable"
                    )
                    item_layout = QHBoxLayout(item_widget)
                    item_layout.addWidget(QLabel(window), 1)
                    del_btn = QPushButton("移除")
                    del_btn.clicked.connect(lambda _, w=window: self._remove_window(w))
                    item_layout.addWidget(del_btn)
                    self.list_layout.addWidget(item_widget)
                self.list_layout.addStretch(1)

            def _add_window(self):
                text = self.combo.currentText().strip()
                if not text:
                    return
                current = config.get(self.cfg_key) or []
                if text not in current:
                    current.append(text)
                    config.set(self.cfg_key, current)
                    self._refresh_list()
                self.combo.clearEditText()

            def _remove_window(self, window):
                current = config.get(self.cfg_key) or []
                if window in current:
                    current.remove(window)
                    config.set(self.cfg_key, current)
                    self._refresh_list()

            def closeEvent(self, e):
                SingletonMixin._singleton_close(self)
                super().closeEvent(e)

        dlg = ExcludeDialog(self, config_key, win_type)
        dlg.show()

    # ---------- 显示设置 - 坐标轴 ----------
    def _build_axis(self, page):
        SliderItem("起始频率*",
                   text="设置柱状图最左的频率值",
                   config=config, config_name="pl_start",
                   config_range=(20, 200),
                   num_type_text="Hz",
                   step=1, parent_layout=page)
        SliderItem("截止频率*",
                   text="设置柱状图最右的频率值",
                   config=config, config_name="pl_end",
                   num_type_text="Hz",
                   config_range=(8000, 20000),
                   step=1, parent_layout=page)
        make_line(page, False)
        SliderItem("柱状图数量*",
                   text="设置柱状图的总数量",
                   config=config, config_name="log_points",
                   config_range=(1, 500), step=1,
                   num_type_text="个",
                   parent_layout=page)
        page.addStretch(1)

    # ---------- 显示设置 - 柱状图 ----------
    def _build_bars(self, page):
        GradientItem("渐变色",
                     config=config, config_name="gradient_color",
                     callback=lambda v: None, parent_layout=page, tag="渐变色")
        SliderItem("宽度",
                   text="设置柱状图的相对宽度",
                   config=config, config_name="gradient_width",
                   num_type_text="x柱状图宽度",
                   config_range=(0.1, 1.0), step=0.01, parent_layout=page)
        make_line(page, False)
        SliderItem("最大高度*",
                   text="设置整个柱状图的范围顶部，数字越大条形越低",
                   config=config, config_name="gradient_max_height",
                   config_range=(0.0, 1.0),
                   num_type_text="xY坐标",
                   step=0.01, parent_layout=page)
        SliderItem("最小高度*",
                   text="设置整个柱状图的范围低部，数字越大条形越容易有值",
                   config=config, config_name="gradient_min_height",
                   config_range=(0.0, 1.0),
                   num_type_text="xY坐标",
                   step=0.01, parent_layout=page)
        page.addStretch(1)

    # ---------- 显示设置 - 峰值指示器 ----------
    def _build_peaks(self, page):
        CheckItem("开关",
                  config=config, config_name="peak_bars_show",
                  parent_layout=page)
        ColorItem(
            "颜色", config=config,
            config_name="peak_bars_color", parent_layout=page)
        SliderItem("宽度",
                   text="相对于柱状图宽度的值",
                   config=config, config_name="peak_bars_width",
                   num_type_text="x柱状图宽度",
                   config_range=(0.1, 10.0), step=0.05, parent_layout=page)
        SliderItem("高度",
                   text="相对于柱状图宽度的值",
                   config=config, config_name="peak_h",
                   num_type_text="x柱状图宽度",
                   config_range=(0.01, 5.0), step=0.01, parent_layout=page)
        SliderItem("衰减速度",
                   text="峰值的衰减速度",
                   config=config, config_name="peak_decay_speed_g",
                   config_range=(1, 2000), step=1,
                   num_type_text="px/s²",
                   parent_layout=page)
        page.addStretch(1)

    # ---------- 显示设置 - 粒子效果 ----------
    def _build_particles(self, page):
        CheckItem("显示",
                  config=config, config_name="ball_show",
                  parent_layout=page)
        ColorItem("颜色",
                  config=config, config_name="ball_color",
                  parent_layout=page)
        SliderItem("直径",
                   config=config, config_name="ball_size",
                   num_type_text="px",
                   config_range=(2, 20), step=1, parent_layout=page)
        SliderItem("速度",
                   config=config, config_name="ball_speed",
                   num_type_text="px/帧",
                   config_range=(0.01, 1.0), step=0.01, parent_layout=page)
        make_line(page, False)
        SliderItem("高触发阈值",
                   text="阈值越大，只有上升极快的“尖峰”频段才会触发粒子，粒子数量减少",
                   num_type_text="xY坐标",
                   config=config, config_name="emit_threshold",
                   config_range=(0.0, 1.0), step=0.005, parent_layout=page)
        SliderItem("低触发阈值",
                   text="阈值越小，只有接近完全停止上升或明显下降时才发射粒子，粒子数量减少",
                   num_type_text="xY坐标",
                   config=config, config_name="emit_threshold2",
                   config_range=(0.0, 1.0), step=0.005, parent_layout=page)
        page.addStretch(1)

    # ---------- 显示设置 - 帧生成 ----------
    def _build_fps_fill(self, page):
        BottomItem(
            "设置帧率上限",
            text="不建议开启帧生成，建议直接设置帧率上线",
            callback=lambda :(
                self.left.switch_to("fft_params"),
                flash_config_widget("目标帧率")
            ),
            parent_layout=page,
        )
        make_line(page, False)
        CheckItem("启用帧生成", config=config, config_name="hight_fps", parent_layout=page)
        SliderItem("目标帧率",
                   config=config, config_name="target_fps",
                   num_type_text="fps",
                   config_range=(1, 500), step=1, parent_layout=page)
        SliderItem("跳帧",
                   config=config, config_name="jump_frame",
                   num_type_text="fps",
                   config_range=(1, 30), step=1, parent_layout=page)
        page.addStretch(1)

    # ---------- 音频采集 ----------
    def _build_audio(self, page):
        ComboItem("数据块*",
                  text="设置采集音频时的每个数据块长度，数值越小采集帧率越大",
                  config=config, config_name="driver_chunk",
                  options=[2**i for i in range(4, 14)], parent_layout=page)
        ComboItem("重采样采样率",
                  text="设置重采样后的目标采样率",
                  config=config, config_name="target_rate",
                  options=[44100, 48000, 96000, 192000], parent_layout=page)
        page.addStretch(1)

    # ---------- FFT预处理 ----------
    def _build_fft_pre(self, page):
        SliderItem("凯瑟窗口参数",
                   config=config, config_name="window_beta",
                   config_range=(0, 20), step=1, parent_layout=page)
        page.addStretch(1)

    # ---------- FFT参数 ----------
    def _build_fft_params(self, page):
        SliderItem("目标帧率",
                   text="设置FFT处理目标速率，实际以选项底部显示的值为准",
                   num_type_text="fps",
                   config=config, config_name="target_fft_fps",
                   config_range=(1, 600), step=1, parent_layout=page,
                   tag="目标帧率",)
        ComboItem("FFT大小",
                  text="设置FFT算法的大小",
                  config=config, config_name="target_fft_size",
                  options=[2**i for i in range(6, 17)], parent_layout=page)

        page.addStretch(1)

    # ---------- FFT后处理 ----------
    def _build_fft_post(self, page):
        SliderItem("瞬态系数",
                   text="设置音量突变时的第一帧的值",
                   num_type_text="x原始值",
                   config=config, config_name="max_alpha",
                   config_range=(0.0, 1.5), step=0.01, parent_layout=page)
        SliderItem("切换插值法阈值",
                   text="范围内的条形个数超过阈值时，切换为取max模式",
                   num_type_text="个",
                   config=config, config_name="use_max_num",
                   config_range=(1, 1000), step=1, parent_layout=page)
        make_line(page, False)
        SliderItem("加权平滑长度",
                   text="设置加权平滑窗口的长度，长度越大，值变化越缓慢",
                   num_type_text="个",
                   config=config, config_name="fft_window_size",
                   config_range=(1, 500), step=1, parent_layout=page)
        SliderItem("加权平滑系数",
                   text="系数越大，值变化越缓慢",
                   config=config, config_name="alpha",
                   config_range=(0.0, 1.0), step=0.01, parent_layout=page)
        page.addStretch(1)

    # ---------- 外观设置（主题）----------
    def _build_appearance(self, page):
        ThemePage(page, engine=engine, config=theme_cfg,
                  on_style_changed=self.apply_all)
        page.addStretch(1)

    # ---------- 关于 ----------
    def _build_about(self):
        page = self.left.add_page("about", "关于", icon="ℹ️")
        title = QLabel(f"关于 {APP_NAME}")
        title.setProperty("class", "section_title")
        title.setAlignment(Qt.AlignCenter)
        page.addWidget(title)
        make_line(page)
        info_label = QLabel(
            f"版本 {APP_VERSION}\n"
            f"基于 xiaoe_ui 框架重构\n"
            f"by一只黄小娥 制作\n"
            f"官方网站：www.yzhxe.cn"
        )
        info_label.setProperty("class", "tip-text")
        page.addWidget(info_label)
        page.addStretch(1)

    def _build_bottom(self):
        layout = self.down_block_layout
        version_frame = ClickFrame(
            tooltip="点击进入软件官网",
        )
        version_frame.on_left_click(
            lambda: QDesktopServices.openUrl(QUrl(APP_URL)))
        version_layout = QVBoxLayout(version_frame)
        version_text = f"v{APP_VERSION}  作者:一只黄小娥"
        version_label = QLabel(version_text)
        version_label.setProperty("class", "win-title-text")
        version_layout.addWidget(version_label)
        layout.addWidget(version_frame)

        self.fps_labels = {}
        fps_layout = QHBoxLayout()
        layout.addLayout(fps_layout)

        fps_layout.setSpacing(7)
        for i, (name, fps_title) in enumerate([
                ("Record","监听"),
                ("FFT","FFT"),
                ("显示","显示"),
            ]):
            my_frame = ClickFrame(
                custom_class="light-line default-hover-line disable",
                hand_cursor=False
            )
            fps_layout.addWidget(my_frame)

            my_layout = QHBoxLayout(my_frame)
            my_layout.setSpacing(3)
            my_layout.setContentsMargins(3, 0, 3, 0)

            fps_label = QLabel(fps_title)
            fps_label.setAlignment(Qt.AlignCenter)
            fps_label.setProperty("class", "line_title")
            fps_value = QLabel("--- FPS")
            fps_value.setAlignment(Qt.AlignCenter)

            my_layout.addWidget(fps_label)
            my_layout.addWidget(fps_value)

            self.fps_labels[name] = {
                "fps_label": fps_label,
                "fps_value": fps_value,
                "fps_title": fps_title,
            }

        layout.addStretch(1)


        self.restart_btn = QPushButtonHandCursor("--")
        # self.restart_btn.setProperty("class", "small")
        self.restart_btn.clicked.connect(
            lambda :self.multiprocess_datas.wait_quit_queue.put("restart")
        )
        layout.addWidget(self.restart_btn)

    def flash_fps(self):
        try:
            if not hasattr(self.multiprocess_datas, 'count_fps_share'):
                return
            for name, fps_elems in self.fps_labels.items():
                fps_obj: Value = self.multiprocess_datas.count_fps_share.share_fps[name]
                value = fps_obj.value
                if value <= -1:
                    value = 0
                # fps_elems["fps_label"].setText(name)
                fps_elems["fps_value"].setText(f"{value:>3} FPS")
        except Exception:
            traceback.print_exc()

    def set_restart_btn_status(self, status, first = False):
        self.nees_restart_flag = False
        self.restart_btn.setEnabled(status)
        self.setWindowTitle(self._win_title)
        self.restart_btn.setText(
             f"{"" if status else "正在"}{"启动" if first else "重启"}"
        )


def main():
    import sys
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    # 可选迁移
    # migrate_gradient_data(config)
    win = App()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()