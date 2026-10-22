# -*- mode: python ; coding: utf-8 -*-
# Genera «dist/Mis nubes.exe» (un solo archivo, sin consola) con PyInstaller.
# En Windows:  pip install pyinstaller PyQt6  &&  pyinstaller construir-windows.spec
# GitHub Actions lo hace solo en cada versión: ver .github/workflows/windows.yml

from PyInstaller.utils.hooks import collect_data_files

a = Analysis(
    ["src/mis_nubes.py"],
    pathex=[],
    binaries=[],
    datas=[("idiomas/*.json", "idiomas"), ("icons/papirus/*.svg", "icons/papirus"),
           ("icons/papirus/LICENSE", "icons/papirus")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    # Módulos de Qt que el programa no usa: el .exe queda más pequeño
    excludes=["PyQt6.QtQml", "PyQt6.QtQuick", "PyQt6.QtMultimedia", "PyQt6.QtWebEngineCore",
              "PyQt6.QtPdf", "PyQt6.QtSql", "PyQt6.QtTest", "tkinter", "unittest", "pydoc"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Mis nubes",
    icon="icons/mis-nubes.ico",
    console=False,          # sin ventana negra
    debug=False,
    strip=False,
    upx=False,
    bootloader_ignore_signals=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version="construir-windows-version.txt",
)
