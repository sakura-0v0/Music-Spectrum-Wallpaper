import multiprocessing
import queue
import struct
import threading
import time
import traceback
from typing import Optional
from scipy.signal import resample

import numpy as np
import pyaudiowpatch as pyaudio

from check_maxsize import CheckMaxSize
from run_page import RunPage
from tools import get_default_playback_id, set_high_timer_resolution, reset_timer_resolution

from count_fps import CountFps



class SoundDriver:
    def __init__(
            self,
            config,
            pl,
            quit_driver_queue,
            data_pipe,
            count_fps_FFT_value,
            count_fps_Record_value,
            maxsize_window,
            fill_screen_window,
            wait_quit_queue,
            fft_in_left_queue,
            max_ftt_list_len = 50,
    ):
        # 设置高精度计时器
        self.high_res = set_high_timer_resolution()
        # 参数初始化
        self.config = config
        self.pl = pl
        self.check_maxsize = CheckMaxSize(self.config,maxsize_window,fill_screen_window)
        self.wait_quit_queue: multiprocessing.Queue = wait_quit_queue
        self.fft_in_left_queue: multiprocessing.Queue = fft_in_left_queue

        self.last_default_device = None

        self.fps = CountFps("FFT",count_fps_FFT_value)
        self.fps_record = CountFps("Record",count_fps_Record_value)
        # self.fps_record_fft = CountFps("Record FFT")

        self.stream : Optional[pyaudio.Stream] = None
        self.driver_chunk = None
        self.channels = None
        self.dev_info = None
        self.format = None
        self.rate = None

        self.closed = False

        self.quit_driver_queue = quit_driver_queue
        self.data_pipe = data_pipe

        self.max_ftt_list_len = max_ftt_list_len

        self.record_fft_queue = queue.Queue()

        self.left_fft_data_list = []
        self.right_fft_data_list = []
        self.middle_fft_data_list = []
        self.byte_buffer = bytearray()         # 音频缓冲区存储固定长度音频，定时采样缓冲区以达到高刷新率

        self.pa: Optional[pyaudio.PyAudio] = None

        self.target_freqs = None  # 对数坐标的目标频率列表
        self.record_fft_thread = threading.Thread(target=self.record_fft_data_loop, daemon=True)
        self.check_default = threading.Thread(target=self.check_default_device_change, daemon=True)


    def sound_loop(self):
        threading.Thread(
            target=self._sound_loop,
            daemon=True
        ).start()
        try:
            self.quit_driver_queue.get()
        except:
            traceback.print_exc()
        self.close()


    def get_input_device(self):
        """查找 WASAPI 回环设备（录制系统扬声器输出）"""
        # 如果已有流，先关闭
        if hasattr(self, 'stream') and self.stream:
            self.stream.stop_stream()
            self.stream.close()
        if self.pa is not None:
            self.pa.terminate()

        self.pa = pyaudio.PyAudio()

        # 方法1：直接获取默认扬声器的回环设备（推荐）
        loopback_info = self.pa.get_default_wasapi_loopback()
        if not loopback_info:
            raise RuntimeError("未找到任何 WASAPI 回环设备，请确保扬声器已启用并支持 WASAPI。")

        # 使用回环设备
        wasapi_device_index = loopback_info["index"]
        self.dev_info = loopback_info

        self.channels = int(self.dev_info["maxInputChannels"])
        self.rate = int(self.dev_info["defaultSampleRate"])
        self.format = pyaudio.paInt16  # 或从 config 读取

        # 从 config 读取其他参数
        self.driver_chunk = self.config.configget('driver_chunk')
        self.target_freqs = np.asarray(self.pl, dtype=np.float64)

        print(f"使用设备: {self.dev_info['name']}, 采样率: {self.rate}, 通道数: {self.channels}")

        # 打开流（只读输入，回环设备本质是输入）
        self.stream = self.pa.open(
            format=self.format,
            channels=self.channels,
            rate=self.rate,
            input_device_index=wasapi_device_index,
            frames_per_buffer=self.driver_chunk,
            input=True,
        )

        print("WASAPI 回环流已成功打开！")
        return self.stream
    def _sound_loop(self):
        """
        获取音频数据并重采样处理
        :return:
        """
        print("开始录音...")
        while True:
            try:
                self.check_maxsize.check_pause()
                if self.closed:
                    break
                data = self.stream.read(self.driver_chunk, False)
                # 执行重采样
                self.sound_record(data)

            except OSError:
                print("OSError")
                self.wait_quit_queue.put('restart')
                break
            except Exception as e:
                traceback.print_exc()
                self.wait_quit_queue.put('restart')
                break
        # if not self.closed:


    def sound_record(self, data):
        """
        音频重采样并放入音频缓冲区
        :param data:
        :return:
        """
        target_sample_width = 2  # config.configget('format_num') // 8  # 每样本字节数
        # 计算目标帧字节长度（例：1024帧*2声道*2字节=4096字节）
        target_frame_length = self.config.configget('target_fft_size') * self.channels * target_sample_width
        # === 重采样处理开始 ===#
        # 原始参数获取
        original_rate = self.rate

        original_bit_depth = pyaudio.get_sample_size(self.format) * 8

        # 将字节流转为numpy数组（处理不同位深度）
        with memoryview(data) as mv:
            raw_samples = np.frombuffer(mv, dtype=self._get_numpy_dtype(self.format))

        # 标准化为浮点数（范围[-1.0, 1.0]）
        normalized_samples = self._normalize_samples(raw_samples, original_bit_depth)

        # 采样率转换
        if original_rate != self.config.configget('target_rate'):
            ratio = self.config.configget('target_rate') / original_rate
            new_length = int(len(normalized_samples) * ratio)
            normalized_samples = self._resample(normalized_samples, new_length)

        # 转成16bit整数
        int16_samples = (normalized_samples * 32767).astype(np.int16)
        # === 重采样处理结束 ===#

        # 转换为字节流
        # 按目标帧长度分割数据并存储于缓冲区
        merged_buffer = self.byte_buffer + int16_samples.tobytes()
        # print(length ,target_frame_length)
        self.byte_buffer = merged_buffer[-target_frame_length:]
        self.fps_record.count_fps()



    def record_fft_data_loop(self):
        """
        按照目标FFT大小，目标FFT帧率，获取音频数据
        """
        next_queue = queue.Queue(maxsize=3)
        RunPage(
            get_fps_func = lambda: self.config.configget('target_fft_fps'),
            run_func = lambda: next_queue.put(None)
        )

        while True:
            try:
                if self.closed:
                    self.check_maxsize.state_lock.set()
                    break

                next_queue.get()

                chunk_data = bytes(self.byte_buffer)
                # print(len(self.byte_buffer))
                result = self.sound_to_fft(chunk_data)
                if not result:
                    continue
                self.fps.count_fps()

            except :
                time.sleep(0.005)
                traceback.print_exc()



    # 新增辅助方法 -------------------------------------------------
    def _get_numpy_dtype(self, pyaudio_format):
        """根据pyaudio格式返回对应的numpy数据类型"""
        sample_size = pyaudio.get_sample_size(pyaudio_format)
        return {
            1: np.uint8,
            2: np.int16,
            3: np.int32,  # 24bit通常存储为32bit
            4: np.float32
        }[sample_size]

    def _normalize_samples(self, samples, bit_depth):
        """将原始采样数据标准化到[-1.0, 1.0]范围"""
        if bit_depth == 8:
            return (samples.astype(np.float32) - 128) / 127.0
        elif bit_depth in [16, 24]:
            return samples.astype(np.float32) / (2 ** (bit_depth - 1))
        elif bit_depth == 32:  # 浮点数格式
            return samples.astype(np.float32)
        else:
            raise ValueError(f"Unsupported bit depth: {bit_depth}")

    def _resample(self, data, target_length):
        """执行采样率转换（使用scipy实现）"""
        return resample(data, target_length)

    def sound_to_fft(self, data):

        # print('get fft')
        # 将字节数据转换为数值数组
        # 对于立体声，数据是交错的 [左, 右, 左, 右, ...]
        self.check_maxsize.check_pause()
        try:
            data_int = struct.unpack(str(self.config.configget('target_fft_size') * self.channels) + 'h', data)
        except struct.error:
            return False
        data_np = np.array(data_int, dtype=np.float32)
        # 分离左右声道
        left_channel = data_np[0::self.channels]
        right_channel = data_np[1::self.channels]
        # FFT
        need_data = ({
            "target_freqs": self.target_freqs,  # 0
            "window_beta": self.config.configget('window_beta'),  # 1
            "target_rate": self.config.configget('target_rate'),  # 2
            "use_max_num": self.config.configget('use_max_num'),  # 3
            "fft_window_size": self.config.configget('fft_window_size'),  # 4
            "alpha": self.config.configget('alpha'),  # 5
            "max_alpha": self.config.configget('max_alpha'),  # 6
            "data_pipe": self.data_pipe,  # 7
        })

        self.fft_in_left_queue.join()
        self.fft_in_left_queue.put(((left_channel,right_channel), need_data))


        return True


    def close(self):
        print('run_close_driver')
        self.closed = True
        self.check_maxsize.quit()
        self.check_maxsize.state_lock.set()
        # try:
        #     reset_timer_resolution(self.high_res)
        # except Exception as e:
        #     traceback.print_exc()


        try:
            self.stream.stop_stream()
            self.stream.close()
            self.pa.terminate()
        except Exception as e:
            traceback.print_exc()

        print('run_close_driver_finished')




    def check_default_device_change(self):
        """
        检查默认设备是否发生变化，如果发生变化，则重启程序
        :return:
        """
        while True:
            try:
                time.sleep(2)
                if self.closed:
                    break
                now_default_device_info = get_default_playback_id()
                if self.last_default_device is not None and now_default_device_info != self.last_default_device:
                    print('change default device')
                    self.wait_quit_queue.put('restart')
                    break
                self.last_default_device = now_default_device_info
            except Exception as e:
                traceback.print_exc()
