# -*- mode: python ; coding: utf-8 -*-

import os
import sys
# 👇 新增：动态获取 xiaoe_ui 库的安装路径
import xiaoe_ui
xiaoe_ui_path = os.path.dirname(xiaoe_ui.__file__)

block_cipher = None

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[
    ('icos', 'icos'),
    (f'{xiaoe_ui_path}/static', 'xiaoe_ui/static'),
    (f'{xiaoe_ui_path}/demo_static', 'xiaoe_ui/demo_static'),
    (f'{xiaoe_ui_path}/theme/global_style.qss', 'xiaoe_ui/theme'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)


pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='小娥频谱显示',
    icon='icos/logo.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='app',
)
