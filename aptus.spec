# -*- mode: python ; coding: utf-8 -*-
# PyInstaller — APTUS (UM ÚNICO .exe em dist\ — sem pasta _internal)
# OBRIGATÓRIO: pasta assets\ com logo_aptus.png (ou .jpg) — embutida no .exe se existir aqui.
# Uso: python -m PyInstaller aptus.spec --noconfirm --clean
# Requer: pip install pyinstaller customtkinter openpyxl psycopg2-binary

import os

from PyInstaller.utils.hooks import collect_all

block_cipher = None

datas, binaries, hiddenimports = collect_all("customtkinter")

# Embute a logo (obrigatória para documentos) se a pasta assets existir junto ao .spec
try:
    _spec_dir = os.path.dirname(os.path.abspath(SPEC))
except NameError:
    _spec_dir = os.getcwd()
_assets = os.path.join(_spec_dir, "assets")
if os.path.isdir(_assets):
    datas = list(datas) + [(_assets, "assets")]

_icon = os.path.join(_spec_dir, "assets", "logo_aptus.ico")
if not os.path.isfile(_icon):
    _icon = None

a = Analysis(
    ["OFAT_PAYOFICIAL.PY"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports
    + [
        "db_config",
        "psycopg2",
        "psycopg2.pool",
        "psycopg2.extensions",
        "psycopg2._psycopg",
        "reportlab",
        "reportlab.pdfgen",
        "reportlab.pdfgen.canvas",
        "reportlab.platypus",
        "reportlab.lib.utils",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "scipy",
        "pandas",
        "pytest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="APTUS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon,
    uac_admin=True,
)
