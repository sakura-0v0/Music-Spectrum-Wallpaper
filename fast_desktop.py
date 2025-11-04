import ctypes,os
from ctypes import wintypes
from win32com.client import Dispatch


def get_sys_dir_path(CSIDL) -> str:
    """
    获取系统文件夹路径
    :param CSIDL: 系统文件夹ID
    :return: 路径
    """
    SHGFP_TYPE_CURRENT = 0
    buffer = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
    # 创建Unicode缓冲区
    ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL, None, SHGFP_TYPE_CURRENT, buffer)
    # 调用Windows的API来获取桌面路径
    desktop_path = buffer.value
    # 将将缓冲区的值，赋给变量desktp_path
    return desktop_path

def get_desktop_path():
    """
    获取桌面路径
    """
    desktop_path = get_sys_dir_path(0x0000)
    return desktop_path

def get_startup_path():
    """
    获取启动目录路径
    """
    startup_path = get_sys_dir_path(0x0007)
    return startup_path


def create_lnk(fast_name,exetit,target_path):
    """
    创建快捷方式
    :param fast_name: 快捷方式名字
    :param exetit: exe名字(不含.exe)
    :param target_path: 目标路径
    """
    #n1=messagebox.askokcancel('创建快捷方式','是否要在桌面创建快捷方式？')
    #if not n1:
        #return

    #创建桌面快捷方式
    def create_shortcut(path, target, work_Dir, icon=''):
        shell = Dispatch('WScript.Shell')
        shortcut = shell.CreateShortCut(path)
        shortcut.TargetPath = target
        shortcut.WorkingDirectory = work_Dir
        #shortcut.IconLocation = icos  --这是用来定义图标路径的，没有图标就不要了（icon参数：图标路径）
        shortcut.Save()
    shortcut_path = target_path+rf'\{fast_name}.lnk'
    target_path = os.getcwd()+"\\"+exetit+'.exe'#exe是因为最后这个py脚本要打包成exe
    work_dir = os.getcwd()  #工作目录，就是快捷方式属性中的起始位置
    create_shortcut(shortcut_path, target_path, work_dir)


if __name__ == '__main__':
    print(get_desktop_path())
    print(get_startup_path())
    create_lnk('测试','test',get_startup_path())
