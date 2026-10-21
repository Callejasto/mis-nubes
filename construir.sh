#!/usr/bin/env bash
# Genera dist/Mis nubes.desktop (el archivo de doble clic) a partir de src/mis_nubes.py
set -euo pipefail
cd "$(dirname "$0")"
B=$(gzip -9cn src/mis_nubes.py | base64 -w0)
mkdir -p dist
cat > "dist/Mis nubes.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Mis nubes
GenericName=Nubes como carpetas
Comment=Google Drive, OneDrive, iCloud, iCloud Fotos, Dropbox, MEGA y más como carpetas. Por Jose Callejas (Callejasto) y Claude.
Name[en]=My Clouds
Comment[en]=Google Drive, OneDrive, iCloud, iCloud Photos, Dropbox, MEGA and more as folders. By Jose Callejas (Callejasto) and Claude.
Icon=folder-cloud
Terminal=false
Categories=Utility;Network;
Exec=bash -c "echo $B | base64 -d | gunzip | (mkdir -p ~/.cache && cat > ~/.cache/mis-nubes-lanzador.py) && { python3 -c 'import PyQt6.QtWidgets' 2>/dev/null && command -v rclone && command -v fusermount3 && pacman -Q qt6-translations qt6-svg papirus-icon-theme || { notify-send -i folder-cloud 'Mis nubes' 'Instalando lo necesario, espera un momento...'; pkexec pacman -S --needed --noconfirm python python-pyqt6 rclone fuse3 qt6-translations qt6-svg papirus-icon-theme; }; } >/dev/null 2>&1 && python3 ~/.cache/mis-nubes-lanzador.py"
DESKTOP
echo "Listo: dist/Mis nubes.desktop"
