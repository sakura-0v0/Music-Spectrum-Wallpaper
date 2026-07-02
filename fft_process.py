# FFT处理进程
import multiprocessing
import sys
import traceback
import numpy as np
from scipy.interpolate import CubicSpline




def run_fft_process(
        fft_in_left_queue,
        left_volume_value,
        right_volume_value,
):
    """启动FFT处理进程"""
    fft_process_left = multiprocessing.Process(
        target=fft_process_loop,
        name="FFT 左",
        args=(
            fft_in_left_queue,
            left_volume_value,
            right_volume_value,
        ),
    )


    fft_process_left.start()
    return fft_process_left

def fft_process_loop(
        fft_in_queue,
        left_volume_value,
        right_volume_value,
):
    """FFT处理进程"""
    while True:
        event = fft_in_queue.get()
        try:
            if event is None:
                break
            data, event = event
            # 新增音量计算代码（在FFT处理前）
            max_amplitude = 32767.0  # 16bit有符号整型最大值
            left_rms = np.sqrt(np.mean(data[0] ** 2))
            left_percent = left_rms / max_amplitude * 143.88

            right_rms = np.sqrt(np.mean(data[1] ** 2))
            right_percent = right_rms / max_amplitude * 143.88

            # print(f"当前音量(L): {left_percent:.1f}% | (R): {right_percent:.1f}%")
            # 执行FFT
            left_fft = fft(data[0], **event)
            right_fft = fft(data[1], **event)
            # 合并左右频谱
            middle_fft = np.maximum(left_fft, right_fft)

            # 进行FFT后处理，并将结果放入显示队列
            update_fft_data(
                middle_fft,
                left_percent,
                right_percent,
                left_volume_value,
                right_volume_value,
                **event
            )
        except Exception as e:
            traceback.print_exc()
        finally:
            fft_in_queue.task_done()
        #     fft_out_queue.put(result)

    print('quit_process_fft-------------------')
    # sys.exit(0)


def fft(
        data,
        target_freqs,
        window_beta,
        target_rate,
        use_max_num,
        *args, **kwargs
):
    """向量化改进版FFT能量密度计算"""
    # 时域加窗处理
    window = np.kaiser(len(data), window_beta)
    compensation = 1.0 / np.mean(window)
    fft_data = np.fft.fft(data * window * compensation)
    a = np.fft.fftfreq(len(data), 1 / target_rate)
    pos_mask = a >= 0


    # 频率参数预处理
    pos_freqs = a[pos_mask]
    pos_mag = np.abs(fft_data[pos_mask]) / len(data) * 2

    # 创建频率仓
    log_freqs = np.log(target_freqs + 1e-10)
    freq_bins = np.exp(np.convolve(log_freqs, [0.5, 0.5], mode='valid'))

    freq_bins = np.insert(freq_bins, 0, 0)
    freq_bins = np.append(freq_bins, np.inf)
    lefts, rights = freq_bins[:-1], freq_bins[1:]

    # 预处理插值对象
    cs = CubicSpline(pos_freqs, pos_mag, bc_type='not-a-knot')
    start_idx = np.searchsorted(pos_freqs, lefts, side='left')
    end_idx = np.searchsorted(pos_freqs, rights, side='left')
    # 计算每个频带的能量
    # use_max_num = 2  # 频带内点的数量阈值
    target_energy = np.zeros(len(target_freqs))
    use_max = False
    for i, target_freq in enumerate(target_freqs):
        n_in_band = end_idx[i] - start_idx[i]
        # print(f"目标频率: {target_freqs[i]} Hz")
        # if n_in_band > 0:
        #     # 获取频带内的所有频率点
        #     band_freqs = pos_freqs[start_idx[i]:end_idx[i]]
        #     band_mags = pos_mag[start_idx[i]:end_idx[i]]
        #
        #     # 打印频率点详细信息
        #     print("包含的频率点:")
        #     for j, (freq, mag) in enumerate(zip(band_freqs, band_mags)):
        #         print(f"  #{j + 1}: {freq} Hz, 幅值: {mag:.4f}")

        # 根据频带内点数选择计算方法
        if not use_max and (n_in_band <= use_max_num or i == 0):
            # 使用三次样条插值计算频带中点能量
            target_energy[i] = cs(target_freq)
        else:
            # if not use_max:
            #     print(target_freq)
            use_max = True
            # 取频带内所有点的最大值

            target_energy[i] = np.max(pos_mag[start_idx[i]:end_idx[i]]) #*weights)

    return target_energy

middle_fft_data_list = [] # 用于存放滑动窗口的FFT数据
left_volume_history = []
right_volume_history = []
def update_fft_data(
    middle_fft,
    left_percent,
    right_percent,
    left_volume_value,
    right_volume_value,
    target_freqs,
    window_beta,
    target_rate,
    use_max_num,
    fft_window_size,
    alpha,
    max_alpha,
    data_pipe,

):
    global middle_fft_data_list
    # 新增：音量历史数据存储
    global left_volume_history, right_volume_history  # 新增全局变量

    # 抽象核心算法为局部函数
    def process_smoothing(history_list, new_value, window_size, alpha, axis=None):
        """统一处理滑动窗口维护和平滑值计算"""
        # 1. 添加新值
        history_list.append(new_value)

        # 2. 维护窗口长度
        if len(history_list) > window_size:
            history_list = history_list[-window_size:]

        # 3. 计算加权平均
        weights = alpha ** np.arange(len(history_list))[::-1]
        smoothed = np.average(history_list, axis=axis, weights=weights)

        return history_list, smoothed

    # ==== 音量处理 ====

    # 左声道处理
    left_volume_history, smooth_left = process_smoothing(
        left_volume_history, left_percent, fft_window_size, alpha
    )

    # 右声道处理
    right_volume_history, smooth_right = process_smoothing(
        right_volume_history, right_percent, fft_window_size, alpha
    )

    # 更新共享变量
    left_volume_value.value = max(smooth_left, left_percent * max_alpha)
    right_volume_value.value = max(smooth_right, right_percent * max_alpha)

    # ==== FFT数据处理 ====
    # 中间频谱处理（复用相同算法）
    middle_fft_data_list, a_middle = process_smoothing(
        middle_fft_data_list, middle_fft, fft_window_size, alpha, axis=0
    )

    # ==== 后续处理保持原样 ====
    current_data = middle_fft_data_list[-1]
    magnitude_array = 20 * np.log10(a_middle + 1e-10)
    data_array = 20 * max_alpha * np.log10(np.maximum(current_data, 0) + 1e-10)
    magnitudes = np.maximum(magnitude_array, data_array)
    data_pipe.send(magnitudes)
    data_pipe.recv()
