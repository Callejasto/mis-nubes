<p align="center">
  <img src="icons/mis-nubes.svg" width="110" alt="Icono de Mis nubes">
</p>

<h1 align="center">Mis nubes</h1>

<p align="center">
  Tus nubes como carpetas normales de tu ordenador, en Linux y en Windows.<br>
  Google Drive, OneDrive, iCloud Drive, iCloud Fotos, Dropbox, MEGA, Nextcloud y 60 servicios más.
</p>

<p align="center">
  <b>Español</b> · <a href="README.en.md">English</a>
</p>

<p align="center">
  <img src="capturas/principal.png" width="640" alt="Ventana principal de Mis nubes">
</p>

## ¿Para quién es?

Para personas que **no saben usar la terminal**. Todo se hace con ventanas, en español y con explicaciones paso a paso: eliges tu nube, le pones un nombre, inicias sesión y listo. Tus archivos aparecen en la carpeta `Nube` y se abren solos cada vez que enciendes el ordenador, igual que en Windows o en Mac.

## Instalación

### En Windows

1. Descarga **`Mis nubes.exe`** desde la sección [**Releases**](../../releases/latest).
2. Haz **doble clic** sobre él. La primera vez descarga dos programas libres que necesita: **rclone** y **WinFsp** (unos 30 MB). Windows pedirá permiso para instalar WinFsp: pulsa **«Sí»**.
3. Pulsa **«Añadir nube»** y sigue los pasos.

Cada nube puede verse **como una unidad más en «Este equipo»** (con su letra, por ejemplo `G:`, lo recomendado) o **como una carpeta** dentro de `Nube`; se elige al añadirla y se puede cambiar después desde el botón ⋯ de su tarjeta. Después de la primera vez, **Mis nubes** aparece en el menú Inicio.

> **Requisitos:** Windows 10 u 11 (64 bits). Si Windows SmartScreen avisa de que el archivo no es conocido, pulsa «Más información» › «Ejecutar de todas formas» (el programa no está firmado con un certificado de pago).

### En Linux

1. Descarga el archivo **`Mis nubes.desktop`** desde la sección [**Releases**](../../releases/latest) (o desde la carpeta [`dist`](dist)).
2. Haz **doble clic** sobre él. La primera vez, el sistema te preguntará si confías en el archivo: elige **«Ejecutar»** o **«Continuar»**.
3. Escribe tu contraseña del ordenador cuando te la pida (solo la primera vez, para instalar lo necesario).
4. Pulsa **«Añadir nube»** y sigue los pasos.

Después de la primera vez, **Mis nubes** aparece en el menú de aplicaciones con su icono.

> **Requisitos:** CachyOS, Arch Linux o derivadas, con escritorio **KDE Plasma**. Ocupa unos 40 KB; lo demás (rclone, PyQt6, iconos Papirus) se instala solo desde los repositorios oficiales.

## Qué hace

<p align="center">
  <img src="capturas/servicios.png" width="420" alt="Elegir servicio">
  <img src="capturas/icloud-fotos.png" width="420" alt="Añadir iCloud Fotos">
</p>

- **Más de 60 servicios:** Google Drive, Google Fotos, OneDrive, iCloud Drive, iCloud Fotos, Dropbox, MEGA, Proton Drive, pCloud, Box, Nextcloud/ownCloud (WebDAV), carpetas compartidas de Windows (SMB), SFTP, FTP, Amazon S3 y compatibles, Backblaze B2 y muchos más.
- **Varias cuentas** del mismo servicio, cada una con **el nombre que tú elijas** (por ejemplo, «Drive del trabajo» y «Drive personal»).
- **Se abren solas** al encender el ordenador.
- **No ocupan espacio:** los archivos se descargan cuando los abres.
- **Espacio usado** de cada nube (en los servicios que lo permiten).
- **iCloud Fotos en línea:** tus fotos por álbumes, sin copiarlas al ordenador (solo lectura).
- **Todo en español**, con los errores explicados en palabras sencillas.
- **Diseño cuidado** inspirado en macOS, con modo claro y oscuro.
- Atajo **«Mis nubes»** en el panel lateral del explorador de archivos (Dolphin).
- **En español e inglés**, y preparado para más idiomas (ver abajo).
- **Se actualiza sola:** cuando hay una versión nueva, aparece un aviso con un botón «Actualizar». La descarga se verifica antes de instalarse y tus nubes no se tocan.

## Idiomas

La aplicación usa el idioma de tu sistema. También puedes cambiarlo en **ⓘ › Idioma**.
Hoy está en **español** e **inglés**. ¿Quieres traducirla a otro idioma? Es solo un archivo de
texto, sin programar: sigue la guía en [`idiomas/LEEME.md`](idiomas/LEEME.md).

## Preguntas frecuentes

**¿Borra algo de mis nubes si desconecto una?**
No. «Desconectar» solo quita la carpeta de este ordenador. Tus archivos siguen en la nube.

**¿Dónde se guardan mis contraseñas?**
En la configuración de rclone de tu propio ordenador (`~/.config/rclone/rclone.conf`), un archivo que solo tu usuario puede abrir. rclone guarda las contraseñas *ofuscadas* (no se leen a simple vista), pero no cifradas: protege tu sesión del ordenador con contraseña. Para Google, Microsoft, Dropbox y similares, la contraseña se escribe solo en la página oficial del servicio, nunca en esta aplicación.

**iCloud me pide iniciar sesión otra vez.**
Es normal: Apple lo exige cada 30 días. Pulsa **⋯ › Volver a iniciar sesión** en su tarjeta.

**¿Por qué iCloud Fotos es de solo lectura?**
Apple no permite subir ni borrar fotos desde fuera de sus aplicaciones. Para eso, usa tu iPhone.

## Para desarrolladores

- El programa completo está en [`src/mis_nubes.py`](src/mis_nubes.py) (Python 3 + PyQt6).
- [`construir.sh`](construir.sh) genera `dist/Mis nubes.desktop`: un lanzador de un solo archivo que lleva el programa dentro, comprimido.
- Es el mismo archivo para Linux y Windows: lo que cambia entre ambos está marcado con `WINDOWS`.
- Cada nube es, en Linux, un servicio de usuario de systemd (`~/.config/systemd/user/mis-nubes-*.service`) y, en Windows, una tarea del Programador de tareas (`Mis nubes\…`, definida en `%LOCALAPPDATA%\mis-nubes\tareas\*.xml`). Ambas ejecutan `rclone mount` al iniciar sesión; en Windows a través de [WinFsp](https://winfsp.dev).
- [`construir-windows.py`](construir-windows.py) genera `dist/Mis nubes.exe` con PyInstaller (en Windows: `pip install PyQt6 pyinstaller` y `python construir-windows.py`). El flujo [`.github/workflows/windows.yml`](.github/workflows/windows.yml) lo hace solo en GitHub.
- **Publicar una versión:** cambia `VERSION` en el código, ejecuta `./construir.sh` y crea una *release* con la etiqueta `vX.Y` (la misma versión) adjuntando `dist/Mis nubes.desktop`. Al subir la etiqueta, GitHub Actions compila `Mis nubes.exe` y lo adjunta a esa misma release. Las copias instaladas (Linux y Windows) la detectan, comprueban su huella SHA-256 y se actualizan.

```bash
./construir.sh                      # regenera dist/Mis nubes.desktop (Linux)
python construir-windows.py         # regenera dist/Mis nubes.exe (en Windows)
python3 src/mis_nubes.py            # o ejecuta el programa directamente (Linux o Windows)
```

## Créditos

Creado por **Jose Callejas** ([@Callejasto](https://github.com/Callejasto)) y **Claude** (Anthropic).

Funciona gracias a [rclone](https://rclone.org) (licencia MIT). Los iconos de los servicios provienen, en Linux, del tema libre [Papirus](https://github.com/PapirusDevelopmentTeam/papirus-icon-theme) (GPL-3.0), instalado desde los repositorios del sistema (en Windows, y en Linux sin Papirus, se usan las copias incluidas en [`icons/papirus`](icons/papirus), con su licencia); en Windows las nubes se muestran como carpetas gracias a [WinFsp](https://winfsp.dev) (GPLv3 con excepción para software libre); las marcas y logotipos pertenecen a sus respectivos dueños. Los iconos de Proton Drive, Koofr, Amazon S3 y Backblaze B2 de la carpeta [`icons`](icons) son diseños originales de este proyecto, no sus logotipos oficiales. Este proyecto no está afiliado a Google, Microsoft, Apple ni a ningún otro servicio.

## Licencia

[MIT](LICENSE) © 2026 Jose Callejas (Callejasto)
