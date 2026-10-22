#!/usr/bin/env python3
"""Genera «dist/Mis nubes.exe» en Windows (equivale a construir.sh en Linux).

    pip install pyinstaller PyQt6
    python construir-windows.py

Lee la versión de src/mis_nubes.py y la graba dentro del .exe (Propiedades › Detalles)."""
import re
import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
VERSION = re.search(r'^VERSION = "([^"]+)"', (AQUI / "src/mis_nubes.py").read_text("utf-8"),
                    re.M).group(1)
numeros = [int(n) for n in re.findall(r"\d+", VERSION)][:4]
numeros += [0] * (4 - len(numeros))
tupla = ", ".join(map(str, numeros))

(AQUI / "construir-windows-version.txt").write_text(f"""# Generado por construir-windows.py (no editar)
VSVersionInfo(
  ffi=FixedFileInfo(filevers=({tupla}), prodvers=({tupla}), mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040A04B0', [
      StringStruct('CompanyName', 'Jose Callejas (Callejasto)'),
      StringStruct('FileDescription', 'Mis nubes: tus nubes como carpetas normales'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('InternalName', 'mis-nubes'),
      StringStruct('LegalCopyright', 'MIT License'),
      StringStruct('OriginalFilename', 'Mis nubes.exe'),
      StringStruct('ProductName', 'Mis nubes'),
      StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1034, 1200])])
  ]
)
""", encoding="utf-8")

print(f"Mis nubes {VERSION}: generando dist/Mis nubes.exe …")
sys.exit(subprocess.call([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                          str(AQUI / "construir-windows.spec")], cwd=AQUI))
