# -*- mode: python ; coding: utf-8 -*-

import os
import sys
# 👇 新增：动态获取 xiaoe_ui 库的安装路径
import xiaoe_ui
xiaoe_ui_datas = xiaoe_ui.get_static_files_to_spec()
trans_datas = xiaoe_ui.get_china_qm_file_list_map_to_spec()

block_cipher = None

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('icos', 'icos'),
        *xiaoe_ui_datas,
        *trans_datas,
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
