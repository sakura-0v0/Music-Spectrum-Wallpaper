# FFT处理进程
import multiprocessing
import traceback
import numpy as np
from scipy.interpolate import CubicSpline

fft_in_left_queue = multiprocessing.JoinableQueue()
# fft_out_left_queue = multiprocessing.Queue()
# fft_in_right_queue = multiprocessing.Queue()
# fft_out_right_queue = multiprocessing.Queue()
# fft_in_left_queue, fft_out_left_queue= multiprocessing.Queue()
# fft_in_right_queue, fft_out_right_queue = multiprocessing.Queue()


def run_fft_process():
    """启动FFT处理进程"""
    fft_process_left = multiprocessing.Process(
        target=fft_process_loop,
        name="FFT 左",
        args=(
            fft_in_left_queue,
            # fft_out_left_queue
        ),
        daemon=True
    )

    # fft_process_right = multiprocessing.Process(
    #     target=fft_process_loop,
    #     args=(fft_in_right_queue, fft_out_right_queue),
    #     name="FFT 右",
    #     daemon=True
    # )

    fft_process_left.start()
    # time.sleep(0.2)
    # fft_process_right.start()

def fft_process_loop(
        fft_in_queue,
        # fft_out_queue
):
    """FFT处理进程"""
    while True:
        event = fft_in_queue.get()
        try:
            if event is None:
                break
            data, event = event

            # 执行FFT
            left_fft = fft(data[0], **event)
            right_fft = fft(data[1], **event)
            # 合并左右频谱
            middle_fft = np.maximum(left_fft, right_fft)

            # 进行FFT后处理，并将结果放入显示队列
            update_fft_data(
                middle_fft,
                **event
            )

        except Exception as e:
            traceback.print_exc()
        finally:
            fft_in_queue.task_done()
        #     fft_out_queue.put(result)

    print('quit_fft_process-------------------')


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
def update_fft_data(
    middle_fft,
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
    middle_fft_data_list.append(middle_fft)
    c = len(middle_fft_data_list) - fft_window_size
    if c > 0:
        # print(len(self.middle_fft_data_list) , self.max_ftt_list_len)
        middle_fft_data_list = middle_fft_data_list[c:]

    current_data = middle_fft_data_list[-1]  # 提取最新数据
    # 计算滑动窗口均值
    window = middle_fft_data_list#[-fft_window_size:]
    weights = alpha ** np.arange(len(window))[::-1]
    a_middle = np.average(window, axis=0, weights=weights)
    # magnitude_array = 20 * np.log10(
    #     np.maximum(a_middle * 0.5, current_data) + 1e-10
    # )
    magnitude_array = 20 * np.log10(
        a_middle + 1e-10
    )
    data_array = 20 * max_alpha * np.log10(
        np.maximum(current_data, 0) + 1e-10
    )
    magnitudes = np.maximum(magnitude_array, data_array)  # 转换为列表后批量添加
    data_pipe.send(magnitudes)
    data_pipe.recv()