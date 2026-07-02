import json

from get_res import get_res_path

with open(get_res_path('icos/app_info.json'), 'r', encoding='UTF-8') as f:
    APP_INFO = json.load(f)

APP_NAME = APP_INFO.get('app_name')
APP_VERSION = APP_INFO.get('version')
APP_URL = "https://www.yzhxe.cn/file-downloads/2/18"
GITHUB_URL = "https://github.com/sakura-0v0/Music-Spectrum-Wallpaper"