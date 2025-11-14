import queue
import struct
import threading
import time
import traceback
from typing import Optional
from scipy.signal import resample

import numpy as np
import pyaudio

from check_maxsize import CheckMaxSize
from fft_process import fft_in_left_queue
from run_page import RunPage
from tools import get_default_playback_id, set_high_timer_resolution, reset_timer_resolution

from count_fps import CountFps



class SoundDriver:
    def __init__(
            self,
            config,
            quit_pipe,
            data_pipe,
            pl,
            count_fps_FFT_value,
            count_fps_Record_value,
            maxsize_window,
            fill_screen_window,
            restart_queue,
            max_ftt_list_len = 50,


    ):
        # 设置高精度计时器
        self.high_res = set_high_timer_resolution()

        # 参数初始化
        self.pl = pl
        self.config = config
        self.check_maxsize = CheckMaxSize(self.config,maxsize_window,fill_screen_window)
        self.restart_queue = restart_queue

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

        self.quit_pipe = quit_pipe
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
        self.record_fft_data_loop_quit = False # 退出提取FFT数据的线程标志
        self.check_default = threading.Thread(target=self.check_default_device_change, daemon=True)
        self.check_quit = threading.Thread(target=self.check_quit_thread, daemon=True)

    def check_quit_thread(self):
        """
        检查退出线程
        :return:
        """
        try:
            self.quit_pipe.recv()
        except:
            traceback.print_exc()
        self.check_maxsize.state_lock.set()
        self.close()


    def get_input_device(self):
        """查找 WASAPI 设备 """
        if self.pa is not None:
            self.pa.terminate()
        self.pa = pyaudio.PyAudio()
        try:
            default_device_info = self.pa.get_default_output_device_info()
        except IOError:
            default_device_info = {}
        try:
            # 1. 将这个字符串用它被错误解码的编码（通常是'latin-1'或'iso-8859-1'）编码回字节数据
            original_bytes = default_device_info.get('name', '').encode('latin-1')
            # 2. 将得到的字节数据用正确的编码（UTF-8）解码成字符串
            good_string = original_bytes.decode('gbk')
            # print(good_string)
        except:
            traceback.print_exc()
            good_string = None
        # Select Device
        # print("设备列表:\n")
        for i in range(0, self.pa.get_device_count()):
            info = self.pa.get_device_info_by_index(i)
            if info.get('hostApi') != 1:
                continue
            # print(str(info["index"]) + ": \t %s \n \t %s \n" % (info["name"],
            #                                                     self.pa.get_host_api_info_by_index(
            #                                                         info["hostApi"])[
            #                                                         "name"]))
            device_name = info.get('name', '')
            if good_string in device_name or device_name == default_device_info['name']:
                default_device_info = info
                break


        # Handle no devices available
        if not default_device_info:
            print("No device available. Quitting.")
            exit()
        else:
            wasapi_device = default_device_info["index"]
            print(wasapi_device)


        # 设置录音参数
        self.format = pyaudio.paInt16# config.get_format()
        self.dev_info = self.pa.get_device_info_by_index(wasapi_device)
        self.channels = self.dev_info["maxInputChannels"] if (self.dev_info["maxOutputChannels"] < self.dev_info["maxInputChannels"]) else self.dev_info["maxOutputChannels"]
        print(self.dev_info)
        self.rate = self.dev_info['defaultSampleRate']

        self.driver_chunk = self.config.configget('driver_chunk')
        self.target_freqs = np.asarray(self.pl, dtype=np.float64)

        print(f"使用设备: {self.dev_info['name']}, 采样率: {self.rate}, 通道数: {self.channels}")
        # 打开流
        print(self.format, self.rate, self.channels, self.driver_chunk)
        self.stream = self.pa.open(
            format=self.format,
            channels=int(self.channels),
            rate=int(self.rate),
            input_device_index=wasapi_device,
            # output_device_index=wasapi_device,
            frames_per_buffer=self.driver_chunk,
            input=True,
            as_loopback=True,
            # input_host_api_specific_stream_info=p.get_host_api_info_by_index(0)
            # output=True,
        )

    def sound_loop(self):
        """
        获取音频数据并重采样处理
        :return:
        """
        print("开始录音...")
        while True:
            try:

                self.check_maxsize.check_pause()
                data = self.stream.read(self.driver_chunk, False)
                # 执行重采样
                self.sound_record(data)
                # self.sound_queue.put(data)


            except OSError:
                print("OSError")
                self.restart_queue.put('restart')
                break
            except Exception as e:
                traceback.print_exc()
                self.restart_queue.put('restart')
                break

        # self.sound_queue.put(None)


        self.close()

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
                if self.record_fft_data_loop_quit:
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

        fft_in_left_queue.join()
        fft_in_left_queue.put(((left_channel,right_channel), need_data))


        return True
        # fft_in_left_queue.put((left_channel, *need_data))
        # fft_in_right_queue.put((right_channel, *need_data))
        # fft_in_left_queue.send((left_channel, *need_data))
        # fft_in_right_queue.send((right_channel, *need_data))

        # left_fft = fft_out_left_queue.get()
        # right_fft = fft_out_right_queue.get()
        # # left_fft = fft_out_left_queue.recv()
        # # right_fft = fft_out_right_queue.recv()
        #
        # middle_fft = np.maximum(left_fft, right_fft)
        #
        # self.update_fft_data(
        #     middle_fft = middle_fft,
        # )

    def close(self):
        reset_timer_resolution(self.high_res)
        fft_in_left_queue.put(None)
        self.pa.terminate()
        # fft_in_right_queue.put(None)
        self.record_fft_data_loop_quit = True
        self.stream.stop_stream()
        self.stream.close()




    def check_default_device_change(self):
        """
        检查默认设备是否发生变化，如果发生变化，则重启程序
        :return:
        """
        while True:
            try:
                time.sleep(2)
                now_default_device_info = get_default_playback_id()
                if self.last_default_device is not None and now_default_device_info != self.last_default_device:
                    print('change default device')
                    self.restart_queue.put('restart')
                    break
                self.last_default_device = now_default_device_info
            except Exception as e:
                traceback.print_exc()


if __name__ == '__main__':
    sd = SoundDriver()
    sd.sound_loop()
