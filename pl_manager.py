import math


class PlManager:
    def __init__(self, config):
        self.config = config
        """生成对数分布参考列表"""
        log_start = math.log(self.config.configget('pl_start'))
        log_end = math.log(self.config.configget('pl_end'))
        step = (log_end - log_start) / (self.config.configget('log_points') - 1)
        print(log_start, log_end, step)
        self.pl  = []
        i = 0
        while True:
            num = round(math.exp(log_start + i * step))
            if num >self.config.configget('pl_end'):
                break
            # print(num)
            self.pl.append(num)
            i += 1
