#!/usr/bin/env python3
"""Mis nubes: conecta cualquier servicio compatible con rclone (Google Drive,
OneDrive, iCloud, Dropbox, MEGA, Nextcloud, SFTP, S3...) y lo monta solo al
iniciar sesión como carpeta en ~/Nube/<nombre que elijas>."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
from pathlib import Path

from PyQt6.QtCore import (QLibraryInfo, QLocale, QObject, QRectF, QSize, Qt, QThread, QTimer,
                          QTranslator, QUrl, pyqtSignal)
from PyQt6.QtGui import (QColor, QDesktopServices, QFont, QGuiApplication, QIcon, QPainter,
                         QPainterPath, QPixmap)
from PyQt6.QtWidgets import (
    QGraphicsDropShadowEffect, QGridLayout, QListView, QSizePolicy,
    QApplication, QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QStackedWidget,
    QToolButton, QVBoxLayout, QWidget,
)

APP = "Mis nubes"


# ================================================================ idiomas
# El programa está escrito en español y cada texto visible pasa por _().
# Cada idioma es un catálogo «texto en español» → «texto traducido».
# Para añadir un idioma: copia idiomas/en.json, traduce los valores y guárdalo
# como idiomas/<código>.json (por ejemplo fr.json). Ver idiomas/LEEME.md.
AJUSTES = Path.home() / ".config/mis-nubes/ajustes.json"
TRADUCCIONES = {}        # catálogos incluidos; se rellenan al final del archivo
CATALOGO = {}
IDIOMA = "es"


def _(texto):
    """Traduce un texto al idioma activo (si no hay traducción, se queda en español)."""
    if not isinstance(texto, str) or not texto:
        return texto
    return CATALOGO.get(texto, texto)


def leer_ajustes():
    try:
        return json.loads(AJUSTES.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def guardar_ajuste(clave, valor):
    datos = leer_ajustes()
    datos[clave] = valor
    AJUSTES.parent.mkdir(parents=True, exist_ok=True)
    AJUSTES.write_text(json.dumps(datos, ensure_ascii=False, indent=2))


def carpetas_idiomas():
    aqui = Path(__file__).resolve().parent
    return [aqui / "idiomas", aqui.parent / "idiomas",
            Path.home() / ".local/share/mis-nubes/idiomas"]


def catalogo(codigo):
    """Catálogo de un idioma: el incluido más los archivos idiomas/<código>.json."""
    cat = dict(TRADUCCIONES.get(codigo, {}))
    encontrado = codigo in TRADUCCIONES
    for carpeta in carpetas_idiomas():
        f = carpeta / f"{codigo}.json"
        try:
            datos = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        cat.update({k: v for k, v in datos.items() if not k.startswith("_") and v})
        encontrado = True
    return cat if encontrado else None


def idiomas_disponibles():
    codigos = {"es"} | set(TRADUCCIONES)
    for carpeta in carpetas_idiomas():
        if carpeta.is_dir():
            codigos |= {f.stem for f in carpeta.glob("*.json") if len(f.stem) in (2, 3, 5)}
    return sorted(codigos)


def nombre_idioma(codigo):
    nombres = {"es": "Español", "en": "English", "fr": "Français", "pt": "Português",
               "it": "Italiano", "de": "Deutsch", "ca": "Català"}
    return nombres.get(codigo, codigo)


def cargar_idioma():
    global IDIOMA, CATALOGO
    elegido = leer_ajustes().get("idioma", "auto")
    if elegido == "auto":
        entorno = (os.environ.get("LANGUAGE") or os.environ.get("LC_ALL")
                   or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or "es")
        elegido = entorno.split(":")[0].split(".")[0].split("_")[0].lower() or "es"
    if elegido == "es":
        IDIOMA, CATALOGO = "es", {}
        return
    cat = catalogo(elegido)
    if cat is None:                     # idioma sin traducción: inglés, que es el más común
        elegido, cat = "en", catalogo("en") or {}
    IDIOMA, CATALOGO = elegido, cat


def elegir_carpeta_base():
    """La carpeta de las nubes: se elige la primera vez según el idioma y no cambia después."""
    global BASE
    guardada = leer_ajustes().get("carpeta")
    if guardada:
        BASE = Path(guardada)
    elif (HOME / "Nube").exists():
        BASE = HOME / "Nube"
    else:
        BASE = HOME / _("Nube")
    guardar_ajuste("carpeta", str(BASE))
HOME = Path.home()
BASE = HOME / "Nube"
UNIT_DIR = HOME / ".config/systemd/user"
APP_DIR = HOME / ".local/share/mis-nubes"

# rclone: el del sistema o, si es antiguo (sin iCloud Fotos), uno propio descargado
RCLONE_VER = "1.75.1"
RCLONE_PROPIO = APP_DIR / "bin" / f"rclone-{RCLONE_VER}"
RCLONE_URL = (f"https://github.com/rclone/rclone/releases/download/v{RCLONE_VER}/"
              f"rclone-v{RCLONE_VER}-linux-amd64.zip")
RCLONE = "rclone"


def elegir_rclone():
    global RCLONE
    if RCLONE_PROPIO.exists():
        RCLONE = str(RCLONE_PROPIO)
    else:
        RCLONE = shutil.which("rclone") or "rclone"
    return RCLONE
VERDE, NARANJA, ROJO = "#2e9d57", "#d9822b", "#d64545"

# Servicios que no tienen sentido como "nube"
OCULTOS = {"local", "memory", "cache", "tardigrade"}

POPULARES = [
    ("drive", "Google Drive"), ("onedrive", "OneDrive"), ("iclouddrive", "iCloud Drive"),
    ("dropbox", "Dropbox"), ("mega", "MEGA"), ("protondrive", "Proton Drive"),
    ("pcloud", "pCloud"), ("box", "Box"), ("webdav", "Nextcloud / WebDAV"),
    ("gphotos", "Google Fotos"), ("koofr", "Koofr"), ("jottacloud", "Jottacloud"),
    ("yandex", "Yandex Disk"), ("mailru", "Mail.ru Cloud"), ("zoho", "Zoho WorkDrive"),
    ("smb", "Carpeta compartida de red (SMB / Windows)"), ("sftp", "Servidor SFTP / SSH"),
    ("ftp", "Servidor FTP"), ("s3", "Amazon S3 y compatibles (R2, Wasabi, MinIO…)"),
    ("b2", "Backblaze B2"),
]
NOMBRES = dict(POPULARES)
NOMBRES.update({
    "alias": "Acceso directo a otra nube que ya tengas",
    "hdfs": "Sistema de archivos Hadoop (HDFS)",
    "doi": "Conjuntos de datos científicos (DOI)",
    "http": "Página web, solo lectura (HTTP)",
    "crypt": "Carpeta cifrada con contraseña (dentro de otra nube)",
    "chunker": "Dividir archivos grandes en trozos",
    "combine": "Juntar varias nubes en una",
    "hasher": "Comprobación extra de archivos",
    "union": "Unir varias nubes en una sola carpeta",
    "compress": "Comprimir otra nube",
    "gcs": "Google Cloud Storage (no es Google Drive)",
    "koofr": "Koofr / Digi Storage",
    "storj": "Storj (nube descentralizada)",
    "sia": "Sia (nube descentralizada)",
    "swift": "OpenStack Swift",
    "oos": "Oracle Cloud Object Storage",
    "azureblob": "Microsoft Azure Blob Storage",
    "azurefiles": "Microsoft Azure Files",
    "seafile": "Seafile",
    "sharefile": "Citrix ShareFile",
    "pixeldrain": "Pixeldrain",
    "hidrive": "HiDrive (Strato)",
    "premiumizeme": "premiumize.me",
    "putio": "Put.io",
    "fichier": "1Fichier",
    "quatrix": "Quatrix",
    "filefabric": "Enterprise File Fabric",
    "qingstor": "QingCloud Object Storage",
    "netstorage": "Akamai NetStorage",
})

ICONOS_RED = {"sftp", "ftp", "smb", "webdav", "http", "hdfs", "seafile"}
ICONOS_ALMACEN = {"s3", "b2", "gcs", "azureblob", "azurefiles", "swift", "oos", "qingstor",
                  "storj", "sia", "netstorage"}

# Preguntas técnicas que se responden solas (salvo en modo experto)
AUTOMATICAS = {
    "client_id", "client_secret", "service_account_file", "tenant", "auth_url", "token_url",
    "token", "root_folder_id", "config_fs_advanced", "config_is_local", "bearer_token",
    "description", "trust_token", "cookies", "alternate_export", "box_config_file",
    "access_token", "key_pem", "key_file", "key_file_pass", "pubkey", "pubkey_file",
    "key_use_agent", "use_insecure_cipher", "disable_hashcheck", "ssh", "spn", "use_kerberos",
    "env_auth", "location_constraint", "acl", "server_side_encryption", "sse_kms_key_id",
    "storage_class", "ibm_api_key", "ibm_resource_instance_id",
}
# Respuestas automáticas solo para un servicio concreto (None = valor por defecto)
AUTO_POR_TIPO = {
    ("drive", "scope"): "drive",
    ("drive", "config_change_team_drive"): "false",
    ("onedrive", "region"): "global",
    ("onedrive", "config_type"): "onedrive",
    ("onedrive", "config_driveid"): None,
    ("onedrive", "config_drive_ok"): "true",
    ("box", "box_sub_type"): "user",
    ("mailru", "speedup_enable"): "true",
    ("iclouddrive", "service"): None,
}

# Traducciones de las preguntas más habituales: nombre -> (etiqueta, ayuda)
TRADUCCION = {
    "url": ("Dirección del servidor (URL)",
            "Es la dirección completa de tu servidor. En Nextcloud la encuentras entrando desde el "
            "navegador › «Archivos» › abajo a la izquierda «Ajustes de archivos» › «WebDAV».\n\n"
            "Se parece a esto: https://tu-servidor.com/remote.php/dav/files/USUARIO\n\n"
            "Si no la sabes, pídesela a quien administra tu servidor."),
    "user": ("Usuario", "Tu nombre de usuario o correo."),
    "pass": ("Contraseña", "Se guarda cifrada en este ordenador."),
    "password": ("Contraseña", "Se guarda cifrada en este ordenador."),
    "apple_id": ("Tu correo de Apple", "Es el correo con el que entras en tu iPhone o en "
                 "icloud.com. Lo ves en el iPhone: Ajustes › (tu nombre, arriba del todo)."),
    "username": ("Usuario", "Tu nombre de usuario o correo."),
    "host": ("Servidor", "Nombre o dirección IP del servidor, por ejemplo 192.168.1.10"),
    "port": ("Puerto", "Déjalo como está si no sabes cuál es."),
    "vendor": ("Tipo de servidor", "Elige tu servidor (Nextcloud, ownCloud…) o déjalo vacío."),
    "provider": ("Proveedor", "Elige tu proveedor de almacenamiento."),
    "access_key_id": ("Clave de acceso (Access Key ID)", "Te la da tu proveedor."),
    "secret_access_key": ("Clave secreta (Secret Access Key)", "Te la da tu proveedor."),
    "region": ("Región", "Déjalo como está si no sabes cuál es."),
    "endpoint": ("Dirección del servicio (endpoint)", "Te la da tu proveedor. Déjalo vacío si no la sabes."),
    "env_auth": ("¿Usar credenciales del sistema?", "Normalmente: No."),
    "scope": ("Permisos", "Déjalo vacío para tener acceso completo."),
    "domain": ("Dominio", "Normalmente WORKGROUP. Déjalo como está si no lo sabes."),
    "key_file": ("Archivo de clave privada", "Déjalo vacío si entras con contraseña."),
    "config_2fa": ("Escribe el código de 6 números",
                   "Mira tu iPhone, iPad o Mac: aparecerá un aviso de «Solicitud de inicio de sesión». "
                   "Pulsa «Permitir» y después escribe aquí los 6 números que te muestra.\n\n"
                   "¿No te llegó nada? Espera un minuto. Si sigue sin llegar, escribe la palabra "
                   "sms y pulsa «Siguiente»: te llegará el código por mensaje de texto."),
    "2fa": ("Código de verificación",
            "Abre la app donde recibes tus códigos (o mira tu SMS) y escribe aquí los números."),
    "config_type": ("Tipo de cuenta", "Elige qué almacenamiento quieres usar."),
    "config_driveid": ("Unidad", "Elige la unidad que quieres usar."),
    "config_drive_ok": ("¿Es correcta esta unidad?", "Elige «Sí» para usarla."),
    "config_change_team_drive": ("¿Usar una unidad compartida?",
                                 "Elige «No» para usar tu Google Drive normal."),
    "config_team_drive": ("Unidad compartida", "Elige la unidad compartida que quieres usar."),
    "account": ("ID de la cuenta (Account ID / keyID)", "Lo encuentras en la web de Backblaze, en «App Keys»."),
    "key": ("Clave de aplicación (Application Key)", "Lo encuentras en la web de Backblaze, en «App Keys»."),
    "hard_delete": ("¿Borrar definitivamente?",
                    "Elige «No» para que lo que borres vaya primero a una papelera (más seguro)."),
    "read_only": ("¿Solo ver las fotos?",
                  "Elige «Sí» si solo quieres ver y descargar tus fotos, sin poder subir ni borrar."),
    "box_sub_type": ("Tipo de cuenta", "Elige «Cuenta personal» si no sabes cuál es."),
    "tls": ("¿Conexión segura desde el inicio (FTPS implícito)?",
            "Normalmente: No. Pregúntale al dueño del servidor si no lo sabes."),
    "explicit_tls": ("¿Conexión segura (FTPS explícito)?",
                     "Elige «Sí» si tu servidor lo permite; es más seguro. Si no lo sabes, elige «No»."),
    "speedup_enable": ("¿Subidas rápidas?", "Recomendado: activado."),
    "library": ("Biblioteca", "Nombre de la biblioteca de Seafile. Déjalo vacío para ver todas."),
    "library_key": ("Contraseña de la biblioteca",
                    "Solo si esa biblioteca está cifrada. Si no, déjalo vacío."),
    "mailbox_password": ("Contraseña del buzón",
                         "Solo si en Proton usas dos contraseñas. Si no, déjalo vacío."),
}

# Textos en español para las opciones de las listas: (pregunta, valor) -> texto
EJEMPLOS_ES = {
    ("scope", "drive"): "Acceso completo (recomendado)",
    ("scope", "drive.readonly"): "Solo lectura (ver y descargar)",
    ("scope", "drive.file"): "Solo archivos creados desde este ordenador",
    ("scope", "drive.appfolder"): "Carpeta de datos de aplicaciones",
    ("scope", "drive.metadata.readonly"): "Solo ver nombres de archivos",
    ("region", "global"): "Mundial (recomendado)",
    ("region", "us"): "Gobierno de Estados Unidos",
    ("region", "de"): "Alemania (antiguo)",
    ("region", "cn"): "China",
    ("region", "com"): "Estados Unidos / Global",
    ("region", "eu"): "Europa",
    ("region", "in"): "India",
    ("region", "jp"): "Japón",
    ("region", "com.cn"): "China",
    ("region", "com.au"): "Australia",
    ("vendor", "fastmail"): "Fastmail",
    ("vendor", "nextcloud"): "Nextcloud",
    ("vendor", "owncloud"): "ownCloud 10",
    ("vendor", "infinitescale"): "ownCloud Infinite Scale",
    ("vendor", "sharepoint"): "SharePoint Online (cuenta de Microsoft)",
    ("vendor", "sharepoint-ntlm"): "SharePoint en un servidor propio",
    ("vendor", "rclone"): "Servidor WebDAV de rclone",
    ("vendor", "other"): "Otro",
    ("box_sub_type", "user"): "Cuenta personal",
    ("box_sub_type", "enterprise"): "Cuenta de servicio de empresa",
    ("provider", "koofr"): "Koofr",
    ("provider", "digistorage"): "Digi Storage",
    ("provider", "other"): "Otro compatible con Koofr",
    ("speedup_enable", "true"): "Activado",
    ("speedup_enable", "false"): "Desactivado",
    ("config_type", "onedrive"): "OneDrive personal o de empresa (recomendado)",
    ("config_type", "sharepoint"): "Sitio principal de SharePoint",
    ("config_type", "url"): "Sitio de SharePoint por nombre o dirección",
    ("config_type", "search"): "Buscar un sitio de SharePoint",
    ("config_type", "driveid"): "Escribir el ID de la unidad (avanzado)",
    ("config_type", "siteid"): "Escribir el ID del sitio (avanzado)",
    ("config_type", "path"): "Ruta del servidor de SharePoint (avanzado)",
}


def texto_ejemplo(opcion, valor, ayuda):  # noqa: C901
    """Texto en español para una opción de lista, sin mostrar inglés."""
    if (opcion, valor) in EJEMPLOS_ES:
        return _(EJEMPLOS_ES[(opcion, valor)])
    if opcion.startswith("config_") and ayuda:
        return ayuda.splitlines()[0]  # nombres de unidades, sitios, etc.
    return valor or _("(dejar vacío)")


ERRORES = [
    (("address already in use",),
     "Una ventana de inicio de sesión de un intento anterior seguía abierta. "
     "Cierra las pestañas de inicio de sesión del navegador y vuelve a intentarlo."),
    (("advanced data protection", "pcs", "adp"),
     "Apple necesita tu permiso. Mira tu iPhone y acepta el aviso que aparece. Comprueba también "
     "que en Ajustes › (tu nombre) › iCloud está ACTIVADO «Acceder a los datos de iCloud en la web»."),
    (("trust token", "trust_token", "reauth", "session expired", "missing apple id"),
     "Apple pide que vuelvas a iniciar sesión (lo hace cada 30 días). Pulsa ⋯ y elige "
     "«Volver a iniciar sesión»."),
    (("2fa", "two-factor", "two factor", "verification code", "invalid code"),
     "El código de verificación no es correcto o ha caducado. Inténtalo de nuevo con un código nuevo."),
    (("access_denied", "user denied", "consent"),
     "No se dio permiso en el navegador. Vuelve a intentarlo y pulsa «Permitir» o «Aceptar»."),
    (("invalid_grant", "token expired", "expired"),
     "El permiso ha caducado. Desconecta esta nube y vuelve a añadirla."),
    (("401", "unauthorized", "invalid credentials", "authentication failed", "login failed",
      "incorrect password", "wrong password", "bad credentials", "invalid password",
      "invalid username", "auth failed", "permission denied (publickey"),
     "El usuario o la contraseña no son correctos. Revísalos e inténtalo de nuevo."),
    (("403", "forbidden", "permission denied", "access denied"),
     "El servicio no ha dado permiso para entrar. Revisa que tu cuenta tenga acceso."),
    (("x509", "certificate", "tls:"),
     "El certificado de seguridad del servidor no es válido. Avisa al dueño del servidor."),
    (("no such host", "dial tcp", "connection refused", "network is unreachable",
      "no route to host", "lookup "),
     "No se pudo llegar al servidor. Comprueba tu conexión a internet y que la dirección "
     "esté bien escrita."),
    (("timeout", "deadline exceeded", "se agotó", "tardó demasiado"),
     "El servicio tardó demasiado en responder. Comprueba tu internet e inténtalo de nuevo."),
    (("404", "not found", "doesn't exist", "does not exist"),
     "No se encontró la carpeta o la dirección indicada. Revisa que esté bien escrita."),
    (("cancelado",), "Has cancelado la operación."),
    (("invalid email", "email/password"),
     "El correo o la contraseña de Apple no son correctos. Revísalos e inténtalo de nuevo."),
    (("cannot connect", "can't connect", "unable to connect"),
     "No se pudo conectar. Comprueba tu conexión a internet e inténtalo de nuevo."),
]


def traducir_error(msg):
    """Devuelve (explicación sencilla en español, detalle técnico original)."""
    bajo = (msg or "").lower()
    for claves, texto in ERRORES:
        if any(c in bajo for c in claves):
            return _(texto), msg
    return (_("Ha ocurrido un problema al conectar. Revisa los datos e inténtalo de nuevo."), msg)


def _caja(padre, icono, titulo, texto, botones):
    box = QMessageBox(padre)
    box.setIcon(icono)
    box.setWindowTitle(_(titulo))
    box.setText(_(texto))
    creados = [box.addButton(_(t), rol) for t, rol in botones]
    box.setDefaultButton(creados[0])
    box.exec()
    return creados.index(box.clickedButton()) if box.clickedButton() in creados else -1


def confirmar(padre, texto, si="Sí", no="No"):
    return _caja(padre, QMessageBox.Icon.Question, APP, texto,
                 [(si, QMessageBox.ButtonRole.YesRole), (no, QMessageBox.ButtonRole.NoRole)]) == 0


def avisar(padre, texto, detalles=None):
    if detalles and detalles != texto:
        if _caja(padre, QMessageBox.Icon.Warning, APP, texto,
                 [("Entendido", QMessageBox.ButtonRole.AcceptRole),
                  ("Ver detalles técnicos", QMessageBox.ButtonRole.ActionRole)]) == 1:
            _caja(padre, QMessageBox.Icon.Information, "Detalles técnicos",
                  _("Esta información sirve para quien te ayude a resolver el problema:") + "\n\n" + detalles,
                  [("Cerrar", QMessageBox.ButtonRole.AcceptRole)])
    else:
        _caja(padre, QMessageBox.Icon.Warning, APP, texto,
              [("Entendido", QMessageBox.ButtonRole.AcceptRole)])


def pedir_texto(padre, titulo, etiqueta, valor=""):
    d = QInputDialog(padre)
    d.setWindowTitle(_(titulo))
    d.setLabelText(_(etiqueta))
    d.setTextValue(valor)
    d.setOkButtonText(_("Guardar"))
    d.setCancelButtonText(_("Cancelar"))
    ok = d.exec() == QDialog.DialogCode.Accepted
    return d.textValue(), ok

UNIT = """[Unit]
Description=Mis nubes: {titulo}
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=notify
ExecStartPre=/usr/bin/mkdir -p {ruta}
ExecStart={programa} mount {remoto} {ruta} \\
    --vfs-cache-mode full \\
    --vfs-cache-max-size 20G \\
    --dir-cache-time 1h \\
    --poll-interval 1m \\
    --umask 022 \\
    --volname {titulo_q} \\
    --log-level NOTICE{extra}
ExecStop=/usr/bin/fusermount3 -uz {ruta}
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
"""


# ================================================================ utilidades
def run(cmd, timeout=None, entrada=None):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          input=entrada, stdin=None if entrada is not None else subprocess.DEVNULL)


def error_rclone(stderr):
    lineas = [l for l in stderr.strip().splitlines() if l.strip()]
    if not lineas:
        return "Error desconocido."
    msg = re.sub(r"^\S+ \S+ (NOTICE|ERROR|CRITICAL): ", "", lineas[-1])
    return msg.replace("Fatal error: ", "")


def slug(texto):
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")
    return t or "nube"


def limpiar_nombre(nombre):
    n = re.sub(r'[\x00-\x1f/\\"$%`]', "", nombre).strip().strip(".")
    return n[:60] or "Nube"


def q(texto):
    """Cita un argumento para un archivo de systemd."""
    t = texto.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$")
    return f'"{t}"'


def config_dump():
    try:
        r = run([RCLONE, "config", "dump"])
        return json.loads(r.stdout or "{}", strict=False)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def titulo_de(remoto, datos):
    return (datos.get("description") or "").strip() or remoto


def carpeta_de(remoto, datos):
    return BASE / limpiar_nombre(titulo_de(remoto, datos))


def unidad_de(remoto):
    h = hashlib.sha1(remoto.encode()).hexdigest()[:6]
    return f"mis-nubes-{slug(remoto)}-{h}.service"


def montado(ruta):
    return run(["mountpoint", "-q", str(ruta)]).returncode == 0


def escribir_unidad(remoto, datos):
    titulo = titulo_de(remoto, datos)
    ruta = carpeta_de(remoto, datos)
    UNIT_DIR.mkdir(parents=True, exist_ok=True)
    extra = (" \\\n    --read-only --vfs-refresh --attr-timeout 1m"
             if datos.get("service") == "photos" else "")
    (UNIT_DIR / unidad_de(remoto)).write_text(UNIT.format(
        titulo=titulo.replace("\n", " "), titulo_q=q(titulo), ruta=q(str(ruta)),
        remoto=q(f"{remoto}:"), programa=q(shutil.which(RCLONE) or RCLONE), extra=extra))
    run(["systemctl", "--user", "daemon-reload"])


def montar(remoto):
    datos = config_dump().get(remoto, {})
    ruta = carpeta_de(remoto, datos)
    escribir_unidad(remoto, datos)
    unidad = unidad_de(remoto)
    run(["systemctl", "--user", "stop", unidad])
    if montado(ruta):
        run(["fusermount3", "-uz", str(ruta)])
    ruta.mkdir(parents=True, exist_ok=True)
    if any(ruta.iterdir()):
        n = 1
        while (ruta.parent / f"{ruta.name} (antiguo {n})").exists():
            n += 1
        ruta.rename(ruta.parent / f"{ruta.name} (antiguo {n})")
        ruta.mkdir()
    run(["systemctl", "--user", "enable", unidad])
    run(["systemctl", "--user", "start", unidad])
    for _ in range(20):
        if montado(ruta):
            return True
        time.sleep(1)
    return False


def quitar_unidad(remoto, datos):
    unidad = unidad_de(remoto)
    run(["systemctl", "--user", "disable", "--now", unidad])
    ruta = carpeta_de(remoto, datos)
    if montado(ruta):
        run(["fusermount3", "-uz", str(ruta)])
    (UNIT_DIR / unidad).unlink(missing_ok=True)
    run(["systemctl", "--user", "daemon-reload"])
    try:
        ruta.rmdir()
    except OSError:
        pass


def proveedores():
    try:
        r = run([RCLONE, "config", "providers"])
        return [p for p in json.loads(r.stdout, strict=False) if p["Prefix"] not in OCULTOS]
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def nombre_servicio(tipo, provs):
    if tipo in NOMBRES:
        return _(NOMBRES[tipo])
    for p in provs:
        if p["Prefix"] == tipo:
            d = p["Description"].split(",")[0].split("(")[0].strip()
            return d[:45]
    return tipo


def icono_tipo(tipo):
    if tipo in ICONOS_RED:
        nombres = ["folder-network", "network-server", "folder-remote"]
    elif tipo in ICONOS_ALMACEN:
        nombres = ["network-server-database", "drive-harddisk", "folder-cloud"]
    else:
        nombres = ["folder-cloud", "folder-remote"]
    for n in nombres + ["folder"]:
        if QIcon.hasThemeIcon(n):
            return QIcon.fromTheme(n)
    return QIcon()


def preparar_sistema():
    """Migra versiones anteriores y añade la app al menú."""
    UNIT_DIR.mkdir(parents=True, exist_ok=True)
    dump = config_dump()
    migrar = []
    for s in ("rclone-gdrive", "rclone-onedrive", "rclone-icloud"):
        f = UNIT_DIR / f"{s}.service"
        if f.exists():
            run(["systemctl", "--user", "disable", "--now", f"{s}.service"])
            f.unlink()
    plantilla = UNIT_DIR / "rclone@.service"
    if plantilla.exists():
        for remoto in dump:
            inst = f"rclone@{remoto}.service"
            if run(["systemctl", "--user", "is-enabled", inst]).stdout.strip() == "enabled":
                run(["systemctl", "--user", "disable", "--now", inst])
                migrar.append(remoto)
        plantilla.unlink()
        run(["systemctl", "--user", "daemon-reload"])
    for remoto in migrar:
        montar(remoto)

    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        destino = APP_DIR / "mis_nubes.py"
        origen = Path(__file__).resolve()
        if origen != destino:
            shutil.copyfile(origen, destino)
        menu = HOME / ".local/share/applications/mis-nubes.desktop"
        menu.parent.mkdir(parents=True, exist_ok=True)
        menu.write_text(
            "[Desktop Entry]\nType=Application\nName=Mis nubes\n"
            f"Name[en]={TRADUCCIONES.get('en', {}).get('Mis nubes', 'Mis nubes')}\n"
            f"Comment={_('Tus nubes como carpetas normales')}\n"
            f"Exec=python3 {destino}\nIcon=folder-cloud\nTerminal=false\n"
            "Categories=Utility;Network;\n")
    except OSError:
        pass


# ---------------------------------------------- pasos del asistente de rclone
PROCESO = {"p": None}


def liberar_puerto():
    """Cierra asistentes de rclone que se quedaron abiertos (ocupan el puerto 53682)."""
    try:
        run(["pkill", "-u", str(os.getuid()), "-f", "rclone[-.0-9]* config (create|update)"])
    except (FileNotFoundError, OSError):
        pass


class Eventos(QObject):
    enlace = pyqtSignal(str)
    progreso = pyqtSignal(int)


EVENTOS = Eventos()


def paso_rclone(args, timeout, reintento=True):
    """Ejecuta un paso del asistente de rclone y devuelve su JSON (o un error).
    Mientras espera, avisa del enlace de inicio de sesión si rclone lo muestra."""
    liberar_puerto()
    p = subprocess.Popen([RCLONE, *args, "--non-interactive"], stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True)
    PROCESO["p"] = p
    lineas_err = []
    agotado = {"si": False}

    def leer_errores():
        for linea in p.stderr:
            lineas_err.append(linea)
            m = re.search(r"(https?://(?:127\.0\.0\.1|localhost):\d+/auth\S*)", linea)
            if m:
                EVENTOS.enlace.emit(m.group(1))

    def cortar():
        agotado["si"] = True
        p.kill()

    lector = threading.Thread(target=leer_errores, daemon=True)
    lector.start()
    reloj = threading.Timer(timeout, cortar)
    reloj.start()
    out = p.stdout.read()
    p.wait()
    reloj.cancel()
    lector.join(2)
    PROCESO["p"] = None
    err = "".join(lineas_err)
    if agotado["si"]:
        return {"_error": "Se agotó el tiempo de espera."}
    if p.returncode != 0 or not out.strip():
        if p.returncode in (-9, -15):
            return {"_error": "Cancelado."}
        if p.returncode != 0:
            fallo = error_rclone(err)
            if reintento and "address already in use" in fallo:
                time.sleep(2)
                return paso_rclone(args, timeout, reintento=False)
            return {"_error": fallo}
        return {}
    try:
        return json.loads(out, strict=False)
    except json.JSONDecodeError:
        return {"_error": "Respuesta inesperada de rclone."}


def tarea_crear(remoto, tipo, titulo, extra=()):
    return paso_rclone(["config", "create", remoto, tipo, f"description={titulo}", *extra, "--all"],
                       120)


def tarea_continuar(remoto, estado, respuesta, espera_navegador):
    return paso_rclone(["config", "update", remoto, "--continue", "--state", estado,
                        "--result", respuesta], 900 if espera_navegador else 120)


def tarea_verificar_y_montar(remoto):
    try:
        r = run([RCLONE, "lsd", f"{remoto}:", "--max-depth", "1"], timeout=90)
        if r.returncode != 0:
            return ("verificar", error_rclone(r.stderr))
    except subprocess.TimeoutExpired:
        return ("verificar", "El servicio tardó demasiado en responder.")
    return ("ok",) if montar(remoto) else ("montar",)


def tarea_montar(remoto):
    if montar(remoto):
        return (True, "Carpeta lista.")
    if config_dump().get(remoto, {}).get("type") == "iclouddrive":
        return (False, "No se pudo abrir la carpeta. Comprueba tu internet. Si sigue sin funcionar, "
                       "pulsa el botón ⋯ y elige «Volver a iniciar sesión»: Apple lo pide cada 30 días.")
    return (False, "No se pudo abrir la carpeta. Comprueba tu conexión a internet.")


def tarea_desconectar(remoto):
    quitar_unidad(remoto, config_dump().get(remoto, {}))
    run([RCLONE, "config", "delete", remoto])
    return (True, "Desconectado. Tus archivos en la nube no se han tocado.")


def tarea_renombrar(remoto, nuevo):
    viejo = config_dump().get(remoto, {})
    unidad_existia = (UNIT_DIR / unidad_de(remoto)).exists()
    if unidad_existia:
        quitar_unidad(remoto, viejo)
    r = run([RCLONE, "config", "update", remoto, f"description={nuevo}",
             "config_refresh_token=false", "--non-interactive"])
    if r.returncode != 0:
        return (False, traducir_error(error_rclone(r.stderr))[0])
    if unidad_existia and not montar(remoto):
        return (False, "Nombre cambiado, pero no se pudo abrir la carpeta.")
    return (True, _("Ahora se llama «{nombre}».").format(nombre=nuevo))


def ofuscar(texto):
    return run([RCLONE, "obscure", "-"], entrada=texto).stdout.strip()


class Tarea(QThread):
    hecho = pyqtSignal(object)

    def __init__(self, fn, *args):
        super().__init__()
        self.fn, self.args = fn, args

    def run(self):
        try:
            res = self.fn(*self.args)
        except Exception as e:  # noqa: BLE001
            res = (False, _("Error inesperado: {error}").format(error=e))
        self.hecho.emit(res)


class Lanzador:
    """Mantiene vivas las tareas en segundo plano."""

    def __init__(self):
        self.tareas = []

    def lanzar(self, fn, args, al_terminar):
        t = Tarea(fn, *args)
        self.tareas.append(t)

        def fin(res):
            if t in self.tareas:
                self.tareas.remove(t)
            al_terminar(res)
        t.hecho.connect(fin)
        t.start()


def titulo_grande(texto, extra=6):
    l = QLabel(texto)
    f = QFont(l.font())
    f.setPointSize(f.pointSize() + extra)
    f.setBold(True)
    l.setFont(f)
    return l




# ================================================================ versión y créditos
VERSION = "1.1"
CREDITOS = "Creado por Jose Callejas (Callejasto) y Claude (Anthropic)"

# ================================================================ icono propio
ICONO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <defs>
    <linearGradient id="fondo" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#6CCBFF"/>
      <stop offset="1" stop-color="#0A6CFF"/>
    </linearGradient>
    <linearGradient id="nube" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#FFFFFF"/>
      <stop offset="1" stop-color="#E4EEFF"/>
    </linearGradient>
    <filter id="sombra" x="-20%" y="-20%" width="140%" height="160%">
      <feDropShadow dx="0" dy="10" stdDeviation="12" flood-color="#00307A" flood-opacity="0.35"/>
    </filter>
  </defs>
  <rect x="16" y="16" width="480" height="480" rx="112" fill="url(#fondo)"/>
  <path filter="url(#sombra)" fill="url(#nube)"
        d="M150 360 C98 360 70 326 70 290 C70 252 98 224 136 220 C142 168 186 130 240 130
           C284 130 320 156 336 194 C344 192 352 190 362 190 C406 190 442 226 442 272
           C442 320 406 360 358 360 Z"/>
  <path fill="#0A6CFF" d="M196 262 h40 l14 16 h66 a10 10 0 0 1 10 10 v52 a10 10 0 0 1 -10 10
        h-120 a10 10 0 0 1 -10 -10 v-68 a10 10 0 0 1 10 -10 z"/>
  <path fill="#4DA3FF" d="M186 294 h140 v46 a10 10 0 0 1 -10 10 h-120 a10 10 0 0 1 -10 -10 z"/>
</svg>
"""
ICONO_RUTA = HOME / ".local/share/icons/hicolor/scalable/apps/mis-nubes.svg"


def icono_app():
    if ICONO_RUTA.exists():
        return QIcon(str(ICONO_RUTA))
    return QIcon.fromTheme("folder-cloud")


def instalar_extras():
    """Icono propio, acceso en el menú, lanzador descargado con icono y atajo en Dolphin."""
    try:
        ICONO_RUTA.parent.mkdir(parents=True, exist_ok=True)
        if not ICONO_RUTA.exists() or ICONO_RUTA.read_text() != ICONO_SVG:
            ICONO_RUTA.write_text(ICONO_SVG)
            run(["gtk-update-icon-cache", "-q", str(HOME / ".local/share/icons/hicolor")])
        menu = HOME / ".local/share/applications/mis-nubes.desktop"
        if menu.exists():
            texto = menu.read_text().replace("Icon=folder-cloud", "Icon=mis-nubes")
            menu.write_text(texto)
    except OSError:
        pass
    # El archivo «Mis nubes.desktop» descargado: ponerle también el icono propio
    for carpeta in ("Descargas", "Downloads", "Escritorio", "Desktop"):
        try:
            for f in (HOME / carpeta).glob("*.desktop"):
                t = f.read_text(errors="ignore")
                if "Name=Mis nubes" in t and "Icon=folder-cloud" in t:
                    f.write_text(t.replace("Icon=folder-cloud", f"Icon={ICONO_RUTA}"))
        except OSError:
            pass
    # Atajo «Mis nubes» en el panel lateral del explorador de archivos (Dolphin)
    try:
        xbel = HOME / ".local/share/user-places.xbel"
        destino = f"file://{BASE}"
        if xbel.exists():
            t = xbel.read_text()
            if destino not in t and "</xbel>" in t:
                shutil.copyfile(xbel, xbel.with_suffix(".xbel.copia-mis-nubes"))
                icono = ('<info><metadata owner="http://freedesktop.org">'
                         '<bookmark:icon name="mis-nubes"/></metadata></info>'
                         if "xmlns:bookmark" in t else "")
                entrada = (f' <bookmark href="{destino}">\n  <title>{_(APP)}</title>\n'
                           f'  {icono}\n </bookmark>\n')
                i = t.rindex("</xbel>")
                xbel.write_text(t[:i] + entrada + t[i:])
                BASE.mkdir(parents=True, exist_ok=True)
    except (OSError, ValueError):
        pass


# ================================================================ iCloud Fotos (en línea)
TIPO_FOTOS = "icloudfotos"
FOTOS_CFG = HOME / ".config/mis-nubes/fotos.json"      # versión anterior (copia con icloudpd)
FOTOS_SESION = APP_DIR / "icloud-sesion"


def migrar_fotos_copia():
    """La versión anterior copiaba las fotos al PC. Se detiene; las fotos copiadas se conservan."""
    try:
        lista = json.loads(FOTOS_CFG.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    carpetas = []
    for f in lista:
        unidad = f"mis-nubes-fotos-{f['id']}.service"
        run(["systemctl", "--user", "disable", "--now", unidad])
        (UNIT_DIR / unidad).unlink(missing_ok=True)
        carpetas.append(limpiar_nombre(f["nombre"]))
    run(["systemctl", "--user", "daemon-reload"])
    FOTOS_CFG.unlink(missing_ok=True)
    shutil.rmtree(FOTOS_SESION, ignore_errors=True)
    for viejo in (APP_DIR / "bin").glob("icloudpd-*"):
        viejo.unlink(missing_ok=True)
    # Que la carpeta con las fotos copiadas no choque con la nueva carpeta en línea
    for i, nombre in enumerate(carpetas):
        ruta = BASE / nombre
        if ruta.exists() and any(ruta.iterdir()):
            nueva = BASE / f"{nombre} (copia antigua)"
            if not nueva.exists():
                ruta.rename(nueva)
                carpetas[i] = nueva.name
    return carpetas


def soporta_fotos():
    try:
        provs = json.loads(run([RCLONE, "config", "providers"]).stdout, strict=False)
    except (OSError, json.JSONDecodeError):
        return False
    return any(p["Prefix"] == "iclouddrive" and any(o["Name"] == "service" for o in p["Options"])
               for p in provs)


def descargar_rclone(aviso_progreso):
    """Descarga la versión oficial de rclone (para equipos con una versión antigua)."""
    import io
    import urllib.request
    import zipfile
    RCLONE_PROPIO.parent.mkdir(parents=True, exist_ok=True)
    try:
        datos = io.BytesIO()
        with urllib.request.urlopen(RCLONE_URL, timeout=60) as r:
            total = int(r.headers.get("Content-Length") or 0)
            while True:
                bloque = r.read(256 * 1024)
                if not bloque:
                    break
                datos.write(bloque)
                if total:
                    aviso_progreso(int(datos.tell() * 100 / total))
        with zipfile.ZipFile(datos) as z:
            miembro = next(n for n in z.namelist() if n.endswith("/rclone"))
            tmp = RCLONE_PROPIO.with_suffix(".tmp")
            tmp.write_bytes(z.read(miembro))
        tmp.chmod(0o755)
        tmp.rename(RCLONE_PROPIO)
        elegir_rclone()
        return (True, "")
    except Exception as e:  # noqa: BLE001
        return (False, str(e))


ESPACIO_CACHE = HOME / ".cache/mis-nubes/espacio.json"


def espacio_guardado():
    try:
        return json.loads(ESPACIO_CACHE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def tarea_espacio(remoto, datos):
    usado = total = None
    try:
        if datos.get("type") == "iclouddrive":
            if datos.get("service") != "photos":
                # Apple no da el total del plan: se suma lo que ocupan los archivos
                r = run([RCLONE, "size", f"{remoto}:", "--json"], timeout=1800)
                usado = json.loads(r.stdout or "{}").get("bytes")
        else:
            r = run([RCLONE, "about", f"{remoto}:", "--json"], timeout=60)
            d = json.loads(r.stdout or "{}")
            usado, total = d.get("used"), d.get("total")
    except Exception:  # noqa: BLE001
        pass
    if usado is not None:
        try:
            cache = espacio_guardado()
            cache[remoto] = [usado, total, time.time()]
            ESPACIO_CACHE.parent.mkdir(parents=True, exist_ok=True)
            ESPACIO_CACHE.write_text(json.dumps(cache))
        except OSError:
            pass
    return (remoto, usado, total)


# ================================================================ iconos de los servicios
# Iconos del tema libre Papirus (si está instalado); si no, un icono de color con la inicial.
OFICIALES = {
    "drive": ["google-drive", "googledrive"], "gphotos": ["google-photos"],
    "onedrive": ["ms-onedrive", "skydrive"], "dropbox": ["dropbox"], "mega": ["mega"],
    "webdav": ["nextcloud", "owncloud"], "iclouddrive": ["icloud"], TIPO_FOTOS: ["icloud"],
    "pcloud": ["pcloud"], "yandex": ["yandex-disk"], "box": ["box"], "seafile": ["seafile"],
    "smb": ["folder-network"], "sftp": ["folder-remote"], "ftp": ["folder-remote"],
}
PAPIRUS = [Path("/usr/share/icons/Papirus"), HOME / ".local/share/icons/Papirus"]

# Iconos propios (diseños originales de Mis nubes) para servicios que Papirus no trae.
# No son los logotipos oficiales de esas marcas.
ICONOS_PROPIOS = {
    "protondrive": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <defs>
    <linearGradient id="fondo" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#A88EFF"/>
      <stop offset="1" stop-color="#5E3CF0"/>
    </linearGradient>
    <linearGradient id="carpeta" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#FFFFFF"/>
      <stop offset="1" stop-color="#EAE4FF"/>
    </linearGradient>
  </defs>
  <rect x="16" y="16" width="480" height="480" rx="112" fill="url(#fondo)"/>
  <path fill="#3F22B8" opacity="0.25" d="M110 182 a24 24 0 0 1 24 -24 h86 l32 32 h132 a24 24 0 0 1 24 24 v168 a24 24 0 0 1 -24 24 h-250 a24 24 0 0 1 -24 -24 z"/>
  <path fill="url(#carpeta)" d="M104 168 a24 24 0 0 1 24 -24 h88 l32 32 h136 a24 24 0 0 1 24 24 v168 a24 24 0 0 1 -24 24 h-256 a24 24 0 0 1 -24 -24 z"/>
  <path d="M226 270 v-22 a30 30 0 0 1 60 0 v22" fill="none" stroke="#6A48F5" stroke-width="16" stroke-linecap="round"/>
  <rect x="208" y="266" width="96" height="76" rx="16" fill="#6A48F5"/>
  <circle cx="256" cy="296" r="11" fill="#FFFFFF"/>
  <rect x="250.5" y="298" width="11" height="24" rx="5.5" fill="#FFFFFF"/>
</svg>
""",
    "koofr": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <defs>
    <linearGradient id="fondo" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#4FE0C4"/>
      <stop offset="1" stop-color="#0B8F84"/>
    </linearGradient>
    <linearGradient id="nube" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#FFFFFF"/>
      <stop offset="1" stop-color="#E2F7F3"/>
    </linearGradient>
  </defs>
  <rect x="16" y="16" width="480" height="480" rx="112" fill="url(#fondo)"/>
  <path fill="#05564F" opacity="0.22" transform="translate(0,34)"
        d="M150 360 C98 360 70 326 70 290 C70 252 98 224 136 220 C142 168 186 130 240 130
           C284 130 320 156 336 194 C344 192 352 190 362 190 C406 190 442 226 442 272
           C442 320 406 360 358 360 Z"/>
  <path fill="url(#nube)" transform="translate(0,22)"
        d="M150 360 C98 360 70 326 70 290 C70 252 98 224 136 220 C142 168 186 130 240 130
           C284 130 320 156 336 194 C344 192 352 190 362 190 C406 190 442 226 442 272
           C442 320 406 360 358 360 Z"/>
  <g fill="none" stroke="#0E9C8F" stroke-width="15" stroke-linecap="round">
    <path d="M209 290 A52 52 0 0 1 303 274"/>
    <path d="M303 322 A52 52 0 0 1 209 338"/>
  </g>
  <g fill="#0E9C8F">
    <polygon points="290,262 322,262 310,292"/>
    <polygon points="222,350 190,350 202,320"/>
  </g>
</svg>
""",
}
ICONOS_CACHE = HOME / ".cache/mis-nubes/iconos"
_ICONOS = {}


def _icono_oficial(clave):
    if clave in _ICONOS:
        return _ICONOS[clave]
    encontrado = None
    for nombre in OFICIALES.get(clave, []) if clave not in ICONOS_PROPIOS else []:
        for base in PAPIRUS:
            for sub in ("64x64/apps", "48x48/apps", "64x64/places", "48x48/places"):
                f = base / sub / f"{nombre}.svg"
                if f.exists():
                    encontrado = QIcon(str(f))
                    break
            if encontrado:
                break
        if encontrado:
            break
    if not encontrado and clave in ICONOS_PROPIOS:
        try:
            ICONOS_CACHE.mkdir(parents=True, exist_ok=True)
            f = ICONOS_CACHE / f"{clave}.svg"
            if not f.exists() or f.read_text() != ICONOS_PROPIOS[clave]:
                f.write_text(ICONOS_PROPIOS[clave])
            encontrado = QIcon(str(f))
        except OSError:
            pass
    _ICONOS[clave] = encontrado
    return encontrado


def icono_servicio(clave, nombre, tam=48):
    ic = _icono_oficial(clave)
    if not ic or ic.isNull():
        return tile(clave, nombre, tam)
    pm = ic.pixmap(tam, tam)
    if clave == TIPO_FOTOS:  # distintivo de «fotos» sobre el icono de iCloud
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        d = tam * 0.46
        x = y = tam - d
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("white"))
        p.drawEllipse(QRectF(x - 1, y - 1, d + 2, d + 2))
        p.setBrush(QColor("#FF9500"))
        p.drawEllipse(QRectF(x, y, d, d))
        p.setBrush(QColor("white"))
        m = QPainterPath()
        m.moveTo(x + d * 0.2, y + d * 0.72)
        m.lineTo(x + d * 0.42, y + d * 0.42)
        m.lineTo(x + d * 0.58, y + d * 0.6)
        m.lineTo(x + d * 0.68, y + d * 0.5)
        m.lineTo(x + d * 0.82, y + d * 0.72)
        m.closeSubpath()
        p.drawPath(m)
        p.drawEllipse(QRectF(x + d * 0.6, y + d * 0.24, d * 0.15, d * 0.15))
        p.end()
    return pm


def servicio_de(datos, provs):
    """(clave para el icono, nombre visible) de una conexión de rclone."""
    tipo = datos.get("type", "")
    if tipo == "iclouddrive" and datos.get("service") == "photos":
        return TIPO_FOTOS, _("iCloud Fotos")
    return tipo, nombre_servicio(tipo, provs)


def tamano(n):
    for unidad in ("B", "KB", "MB", "GB", "TB", "PB"):
        if n < 1024 or unidad == "PB":
            t = f"{n:.1f} {unidad}".replace(".0 ", " ")
            return t if IDIOMA == "en" else t.replace(".", ",")
        n /= 1024


# ================================================================ estilo macOS
CLARO = dict(fondo="#F5F5F7", tarjeta="#FFFFFF", borde="#E3E3E8", texto="#1D1D1F",
             gris="#6E6E73", acento="#007AFF", acento_h="#1A85FF", acento_p="#0062CC",
             verde="#28A745", naranja="#E67E00", rojo="#FF3B30", campo="#FFFFFF",
             campo_borde="#D2D2D7", boton2="#E8E8ED", boton2_h="#DCDCE1", sel="#E5F0FF",
             sombra=28)
OSCURO = dict(fondo="#1E1E1E", tarjeta="#2C2C2E", borde="#3A3A3C", texto="#F5F5F7",
              gris="#98989D", acento="#0A84FF", acento_h="#339CFF", acento_p="#0071E3",
              verde="#30D158", naranja="#FF9F0A", rojo="#FF453A", campo="#1C1C1E",
              campo_borde="#48484A", boton2="#3A3A3C", boton2_h="#48484A", sel="#16365C",
              sombra=110)
T = dict(CLARO)


def aplicar_tema(app):
    oscuro = app.palette().window().color().lightness() < 128
    T.clear()
    T.update(OSCURO if oscuro else CLARO)
    app.setStyleSheet(f"""
    QWidget {{ color: {T['texto']}; font-size: 10.5pt; }}
    QWidget#raiz, QDialog, QMessageBox, QInputDialog {{ background: {T['fondo']}; }}
    QLabel {{ background: transparent; }}
    QFrame#tarjeta {{ background: {T['tarjeta']}; border: 1px solid {T['borde']}; border-radius: 14px; }}
    QFrame#caja {{ background: {T['tarjeta']}; border: 1px solid {T['borde']}; border-radius: 12px; }}
    QLabel#gris {{ color: {T['gris']}; }}
    QLabel#pequeno {{ color: {T['gris']}; font-size: 9pt; }}
    QLabel#titulo {{ font-size: 21pt; font-weight: 700; }}
    QLabel#subtitulo {{ font-size: 15pt; font-weight: 650; }}
    QLabel#nombre {{ font-size: 12.5pt; font-weight: 650; }}
    QLabel#error {{ color: {T['rojo']}; font-weight: 600; }}
    QLabel#numero {{ background: {T['acento']}; color: white; border-radius: 12px;
                     min-width: 24px; max-width: 24px; min-height: 24px; max-height: 24px;
                     font-weight: 700; font-size: 10pt; }}
    QPushButton {{ background: {T['boton2']}; border: none; border-radius: 8px;
                   padding: 8px 16px; color: {T['texto']}; }}
    QPushButton:hover {{ background: {T['boton2_h']}; }}
    QPushButton:disabled {{ color: {T['gris']}; }}
    QPushButton#primario {{ background: {T['acento']}; color: white; font-weight: 600; }}
    QPushButton#primario:hover {{ background: {T['acento_h']}; }}
    QPushButton#primario:pressed {{ background: {T['acento_p']}; }}
    QPushButton#primario:disabled {{ background: {T['boton2']}; color: {T['gris']}; }}
    QPushButton#grande {{ background: {T['acento']}; color: white; font-weight: 700;
                          font-size: 12pt; padding: 12px 22px; border-radius: 10px; }}
    QPushButton#grande:hover {{ background: {T['acento_h']}; }}
    QPushButton#grande:disabled {{ background: {T['boton2']}; color: {T['gris']}; }}
    QPushButton#enlace {{ background: transparent; color: {T['acento']}; padding: 2px 0; text-align: left; }}
    QPushButton#enlace:hover {{ text-decoration: underline; }}
    QPushButton#redondo {{ border-radius: 16px; padding: 0; min-width: 32px; max-width: 32px;
                           min-height: 32px; max-height: 32px; font-size: 13pt; font-weight: 700; }}
    QPushButton#redondo::menu-indicator {{ image: none; width: 0; }}
    QLineEdit, QComboBox {{ background: {T['campo']}; border: 1px solid {T['campo_borde']};
                            border-radius: 9px; padding: 9px 11px; font-size: 11.5pt;
                            selection-background-color: {T['acento']}; }}
    QLineEdit:focus, QComboBox:focus {{ border: 2px solid {T['acento']}; padding: 8px 10px; }}
    QComboBox::drop-down {{ border: none; width: 28px; }}
    QComboBox QAbstractItemView {{ background: {T['tarjeta']}; border: 1px solid {T['borde']};
                                   selection-background-color: {T['acento']};
                                   selection-color: white; padding: 4px; }}
    QListWidget {{ background: transparent; border: none; outline: none; }}
    QListWidget::item {{ border-radius: 12px; padding: 6px; color: {T['texto']}; }}
    QListWidget::item:hover {{ background: {T['boton2']}; }}
    QListWidget::item:selected {{ background: {T['sel']}; color: {T['texto']}; }}
    QCheckBox {{ color: {T['gris']}; spacing: 6px; }}
    QProgressBar {{ background: {T['boton2']}; border: none; border-radius: 3px;
                    max-height: 6px; min-height: 6px; }}
    QProgressBar::chunk {{ background: {T['acento']}; border-radius: 3px; }}
    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QMenu {{ background: {T['tarjeta']}; border: 1px solid {T['borde']}; border-radius: 10px; padding: 6px; }}
    QMenu::item {{ padding: 8px 20px; border-radius: 6px; }}
    QMenu::item:selected {{ background: {T['acento']}; color: white; }}
    QMenu::separator {{ height: 1px; background: {T['borde']}; margin: 4px 8px; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; }}
    QScrollBar::handle:vertical {{ background: {T['campo_borde']}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    """)


COLORES_TILE = ["#007AFF", "#34C759", "#FF9500", "#AF52DE", "#FF2D55", "#32ADE6",
                "#5856D6", "#FF3B30", "#30B0C7", "#A2845E", "#00C7BE", "#FFCC00"]


def tile(clave, texto, tam=48):
    """Icono cuadrado redondeado de colores con la inicial (estilo app de Mac)."""
    from PyQt6.QtGui import QLinearGradient
    color = QColor(COLORES_TILE[int(hashlib.md5(clave.encode()).hexdigest(), 16) % len(COLORES_TILE)])
    pantalla = QGuiApplication.primaryScreen()
    dpr = pantalla.devicePixelRatio() if pantalla else 1
    pm = QPixmap(int(tam * dpr), int(tam * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    ruta = QPainterPath()
    ruta.addRoundedRect(QRectF(0, 0, tam, tam), tam * 0.25, tam * 0.25)
    g = QLinearGradient(0, 0, 0, tam)
    g.setColorAt(0, color.lighter(118))
    g.setColorAt(1, color.darker(108))
    p.fillPath(ruta, g)
    p.setPen(QColor("white"))
    f = QFont()
    f.setPixelSize(int(tam * 0.46))
    f.setBold(True)
    p.setFont(f)
    letra = next((c for c in texto if c.isalnum()), "?").upper()
    p.drawText(QRectF(0, 0, tam, tam), Qt.AlignmentFlag.AlignCenter, letra)
    p.end()
    return pm


def circulo(ok, tam=72):
    """Círculo grande con ✓ (verde) o ! (naranja)."""
    pantalla = QGuiApplication.primaryScreen()
    dpr = pantalla.devicePixelRatio() if pantalla else 1
    pm = QPixmap(int(tam * dpr), int(tam * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(T["verde"] if ok else T["naranja"]))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QRectF(0, 0, tam, tam))
    p.setPen(QColor("white"))
    f = QFont()
    f.setPixelSize(int(tam * 0.55))
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRectF(0, 0, tam, tam), Qt.AlignmentFlag.AlignCenter, "✓" if ok else "!")
    p.end()
    return pm


def etiqueta(texto, nombre=None, ajuste=True):
    l = QLabel(_(texto))
    if nombre:
        l.setObjectName(nombre)
    l.setWordWrap(ajuste)
    return l


def boton(texto, nombre=None, accion=None):
    b = QPushButton(_(texto))
    if nombre:
        b.setObjectName(nombre)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if accion:
        b.clicked.connect(accion)
    return b


def sombra(w):
    ef = QGraphicsDropShadowEffect(w)
    ef.setBlurRadius(26)
    ef.setOffset(0, 3)
    ef.setColor(QColor(0, 0, 0, T["sombra"]))
    w.setGraphicsEffect(ef)


def pastilla(lbl, texto, color):
    c = QColor(color)
    lbl.setText(_(texto))
    lbl.setStyleSheet(f"color: {color}; background: rgba({c.red()},{c.green()},{c.blue()},40);"
                      "border-radius: 9px; padding: 2px 10px; font-size: 9pt; font-weight: 600;")


def caja_pasos(pasos):
    """Lista numerada con círculos azules, como las guías de Apple."""
    caja = QFrame()
    caja.setObjectName("caja")
    lay = QVBoxLayout(caja)
    lay.setContentsMargins(18, 14, 18, 14)
    lay.setSpacing(12)
    for i, texto in enumerate(pasos, 1):
        fila = QHBoxLayout()
        fila.setSpacing(12)
        n = QLabel(str(i))
        n.setObjectName("numero")
        n.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fila.addWidget(n, 0, Qt.AlignmentFlag.AlignTop)
        t = etiqueta(_(texto))
        t.setTextFormat(Qt.TextFormat.RichText)
        fila.addWidget(t, 1)
        lay.addLayout(fila)
    return caja


# ================================================================ textos de ayuda
NAVEGADOR = ("Tu navegador de internet (Firefox, Chrome…). Allí iniciarás sesión de forma "
             "segura: <b>tu contraseña nunca se escribe en esta aplicación</b>.")

NECESITAS = {
    "drive": ["Tu correo y contraseña de Google (los mismos de Gmail).", NAVEGADOR],
    "gphotos": ["Tu correo y contraseña de Google (los mismos de Gmail).", NAVEGADOR],
    "onedrive": ["Tu correo y contraseña de Microsoft (Outlook, Hotmail, Office o el del trabajo).",
                 NAVEGADOR],
    "dropbox": ["Tu correo y contraseña de Dropbox.", NAVEGADOR],
    "iclouddrive": [
        "Tu correo y contraseña de Apple (con los que entras en tu iPhone).",
        "Tu iPhone, iPad o Mac a mano: te llegará un código de 6 números.",
        "En el iPhone, abre <b>Ajustes › (tu nombre) › iCloud</b> y comprueba que «Acceder a los "
        "datos de iCloud en la web» está <b>activado</b>.",
        "Por seguridad, <b>Apple pide volver a iniciar sesión cada 30 días</b>. Cuando pase, verás "
        "un aviso en la tarjeta y lo harás en un minuto.",
    ],
    TIPO_FOTOS: [
        "Tu correo y contraseña de Apple (con los que entras en tu iPhone).",
        "Tu iPhone, iPad o Mac a mano: te llegará un código de 6 números.",
        "En el iPhone, abre <b>Ajustes › (tu nombre) › iCloud</b> y comprueba que «Acceder a los "
        "datos de iCloud en la web» está <b>activado</b>.",
        "Por seguridad, <b>Apple pide volver a iniciar sesión cada 30 días</b>.",
    ],
    "mega": ["Tu correo y contraseña de MEGA."],
    "protondrive": ["Tu correo y contraseña de Proton.",
                    "Si usas verificación en dos pasos, tu app de códigos a mano."],
    "webdav": [
        "La <b>dirección de tu servidor</b>. En Nextcloud la encuentras así: entra en tu Nextcloud "
        "desde el navegador › «Archivos» › abajo a la izquierda «Ajustes de archivos» › copia la "
        "dirección que aparece en «WebDAV».",
        "Tu usuario y contraseña. Si tu cuenta tiene verificación en dos pasos, crea una "
        "«contraseña de aplicación» en Ajustes › Seguridad y usa esa.",
    ],
    "smb": [
        "El <b>nombre o la dirección IP</b> del ordenador que comparte la carpeta "
        "(por ejemplo 192.168.1.10). En Windows lo ves en Configuración › Sistema › Información.",
        "El usuario y la contraseña de ese ordenador.",
    ],
    "sftp": ["La dirección del servidor (nombre o IP).", "Tu usuario y contraseña del servidor."],
    "ftp": ["La dirección del servidor (nombre o IP).", "Tu usuario y contraseña del servidor."],
    "s3": ["El nombre de tu proveedor (Amazon, Cloudflare R2, Wasabi…).",
           "Tus claves «Access Key» y «Secret Key». Se crean en el panel web de tu proveedor."],
    "b2": ["Tu «keyID» y tu «applicationKey». Están en la web de Backblaze › «App Keys» › "
           "«Add a New Application Key»."],
}

PLACEHOLDER = {
    "url": "https://mi-nube.com/remote.php/dav/files/USUARIO",
    "host": "192.168.1.10   o   servidor.com",
    "user": "tu usuario o correo",
    "username": "tu@correo.com",
    "apple_id": "tunombre@icloud.com",
    "pass": "tu contraseña",
    "password": "tu contraseña",
    "port": "déjalo como está",
    "config_2fa": "123456",
    "2fa": "123456",
    "endpoint": "https://…",
}


def es_oauth(tipo, provs):
    for p in provs:
        if p["Prefix"] == tipo:
            return any(o["Name"] == "client_id" for o in p["Options"])
    return False


def necesitas(tipo, provs, servicio):
    if tipo in NECESITAS:
        return NECESITAS[tipo]
    if es_oauth(tipo, provs):
        return [_("Tu correo y contraseña de {servicio}.").format(servicio=servicio), NAVEGADOR]
    return [_("Tu usuario y contraseña de {servicio}.").format(servicio=servicio),
            "Si te pide algún dato que no conoces, deja lo que venga escrito: casi siempre es lo correcto."]


def nombre_servicio2(tipo, provs):  # noqa: D103
    if tipo == TIPO_FOTOS:
        return _("iCloud Fotos")
    return nombre_servicio(tipo, provs)


# ================================================================ asistente
P_SERVICIO, P_NOMBRE, P_PREGUNTA, P_NAVEGADOR, P_ESPERA, P_FIN = range(6)
ETAPAS = ["Servicio", "Nombre", "Conectar", "Listo"]
ETAPA_DE = {P_SERVICIO: 0, P_NOMBRE: 1, P_PREGUNTA: 2, P_NAVEGADOR: 2, P_ESPERA: 2, P_FIN: 3}


class Asistente(QDialog):
    def __init__(self, padre, provs, existentes, tipo_inicial=None, nombre_inicial="",
                 reconectar=None):
        super().__init__(padre)
        self.setWindowTitle(_("Añadir nube"))
        self.setWindowIcon(icono_app())
        self.setMinimumSize(640, 600)
        self.provs = provs
        self.existentes = existentes
        self.lz = Lanzador()
        self.remoto = None
        self.estado = None
        self.opcion = None
        self.esperando_navegador = False
        self.resultado = None
        self.reintentar = False
        self.tipo = tipo_inicial
        self.tipo_rclone = tipo_inicial
        self.extra = []
        self.titulo = nombre_inicial
        self.ruta_final = None
        self.reconectar = reconectar

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(28, 20, 28, 20)
        raiz.setSpacing(14)
        self.etapas = QLabel()
        self.etapas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        raiz.addWidget(self.etapas)
        self.pilas = QStackedWidget()
        raiz.addWidget(self.pilas, 1)

        pie = QHBoxLayout()
        self.experto = QCheckBox(_("Modo experto"))
        self.experto.setToolTip(_("Muestra también las preguntas técnicas. No hace falta para casi nadie."))
        pie.addWidget(self.experto)
        pie.addStretch()
        self.btn_cancelar = boton("Cancelar", None, self.cancelar)
        self.btn_otro = boton("Abrir la carpeta", None, self._abrir_final)
        self.btn_otro.hide()
        self.btn_sig = boton("Continuar", "primario", self.siguiente)
        self.btn_sig.setDefault(True)
        for b in (self.btn_cancelar, self.btn_otro, self.btn_sig):
            pie.addWidget(b)
        raiz.addLayout(pie)

        for crear in (self._pagina_servicio, self._pagina_nombre, self._pagina_pregunta,
                      self._pagina_navegador, self._pagina_espera, self._pagina_fin):
            crear()
        self.pilas.currentChanged.connect(self._al_cambiar)
        EVENTOS.enlace.connect(self._enlace)
        EVENTOS.progreso.connect(self.e_barra.setValue)

        if reconectar:
            datos = existentes.get(reconectar, {})
            self.setWindowTitle(_("Volver a iniciar sesión"))
            self.remoto = reconectar
            self.tipo = servicio_de(datos, provs)[0]
            self.titulo = titulo_de(reconectar, datos)
            QTimer.singleShot(0, self._crear)
        elif tipo_inicial:
            self._seleccionar(tipo_inicial)
            self.ir(P_NOMBRE)
        else:
            self.ir(P_SERVICIO)

    # ---------- utilidades
    def ir(self, pagina):
        self.pilas.setCurrentIndex(pagina)
        self._al_cambiar(pagina)

    def _al_cambiar(self, pagina):
        actual = ETAPA_DE.get(pagina, 0)
        partes = []
        for i, e in enumerate(ETAPAS):
            if i == actual:
                partes.append(f"<b style='color:{T['acento']}'>● {_(e)}</b>")
            elif i < actual:
                partes.append(f"<span style='color:{T['verde']}'>✓ {_(e)}</span>")
            else:
                partes.append(f"<span style='color:{T['gris']}'>○ {_(e)}</span>")
        self.etapas.setText("&nbsp;&nbsp;&nbsp;›&nbsp;&nbsp;&nbsp;".join(partes))
        self.experto.setVisible(pagina in (P_SERVICIO, P_NOMBRE) and not self.reconectar)
        self.btn_sig.setVisible(pagina in (P_SERVICIO, P_NOMBRE, P_PREGUNTA, P_FIN))
        self.btn_sig.setEnabled(True)
        self.btn_cancelar.setVisible(pagina != P_FIN)
        if pagina != P_FIN:
            self.btn_otro.hide()
        textos = {P_SERVICIO: "Continuar", P_NOMBRE: "Empezar", P_PREGUNTA: "Siguiente"}
        if pagina in textos:
            self.btn_sig.setText(_(textos[pagina]))

    def _servicio(self):
        return nombre_servicio2(self.tipo, self.provs) if self.tipo else ""

    # ---------- página: servicio
    def _pagina_servicio(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(10)
        l.addWidget(etiqueta("¿Qué nube quieres añadir?", "titulo"))
        l.addWidget(etiqueta("Haz clic en una. Si no la ves, escríbela en el buscador.", "gris"))
        self.buscar = QLineEdit()
        self.buscar.setPlaceholderText(_("Buscar un servicio…  (por ejemplo: dropbox, nextcloud, mega)"))
        self.buscar.setClearButtonEnabled(True)
        self.buscar.textChanged.connect(self._filtrar)
        l.addWidget(self.buscar)
        self.lista = QListWidget()
        self.lista.setViewMode(QListView.ViewMode.IconMode)
        self.lista.setIconSize(QSize(52, 52))
        self.lista.setGridSize(QSize(136, 112))
        self.lista.setResizeMode(QListView.ResizeMode.Adjust)
        self.lista.setMovement(QListView.Movement.Static)
        self.lista.setWordWrap(True)
        self.lista.setUniformItemSizes(False)
        self.lista.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.lista.setSpacing(4)
        self.lista.itemDoubleClicked.connect(lambda _: self.siguiente())
        l.addWidget(self.lista, 1)
        self.ver_todos = boton("Ver todos los servicios", "enlace", self._alternar_todos)
        l.addWidget(self.ver_todos, 0, Qt.AlignmentFlag.AlignLeft)
        self.todos = False

        prefijos = {p["Prefix"] for p in self.provs}
        populares = []
        for tipo, texto in POPULARES:
            if tipo in prefijos:
                populares.append((tipo, texto))
            if tipo == "iclouddrive":
                populares.append((TIPO_FOTOS, "iCloud Fotos"))
        for tipo, texto in populares:
            self._item(tipo, texto, True)
        resto = [p["Prefix"] for p in self.provs if p["Prefix"] not in dict(POPULARES)]
        for tipo in sorted(resto, key=lambda t: nombre_servicio(t, self.provs).lower()):
            self._item(tipo, nombre_servicio(tipo, self.provs), False)
        self.ver_todos.setText(_("Ver los {n} servicios disponibles").format(n=self.lista.count()))
        self._filtrar("")
        self.pilas.addWidget(w)

    def _item(self, tipo, texto, popular):
        texto = _(texto)
        corto = texto.split(" (")[0]
        it = QListWidgetItem(QIcon(icono_servicio(tipo, texto, 52)), corto)
        it.setData(Qt.ItemDataRole.UserRole, tipo)
        it.setData(Qt.ItemDataRole.UserRole + 1, popular)
        it.setToolTip(texto)
        it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        it.setSizeHint(QSize(128, 106))
        self.lista.addItem(it)

    def _alternar_todos(self):
        self.todos = not self.todos
        self.ver_todos.setText(_("Ver solo los más usados") if self.todos
                               else _("Ver los {n} servicios disponibles").format(n=self.lista.count()))
        self._filtrar(self.buscar.text())

    def _filtrar(self, texto):
        t = texto.lower().strip()
        for i in range(self.lista.count()):
            it = self.lista.item(i)
            tipo = it.data(Qt.ItemDataRole.UserRole)
            if t:
                ocultar = t not in it.toolTip().lower() and t not in tipo
            else:
                ocultar = not self.todos and not it.data(Qt.ItemDataRole.UserRole + 1)
            it.setHidden(ocultar)

    def _seleccionar(self, tipo):
        for i in range(self.lista.count()):
            if self.lista.item(i).data(Qt.ItemDataRole.UserRole) == tipo:
                self.lista.setCurrentRow(i)
                return

    # ---------- página: nombre
    def _pagina_nombre(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(12)
        cab = QHBoxLayout()
        self.n_tile = QLabel()
        cab.addWidget(self.n_tile)
        col = QVBoxLayout()
        self.n_servicio = etiqueta("", "subtitulo")
        self.n_explica = etiqueta("", "gris")
        col.addWidget(self.n_servicio)
        col.addWidget(self.n_explica)
        cab.addLayout(col, 1)
        l.addLayout(cab)
        l.addSpacing(4)
        l.addWidget(etiqueta("<b>Ponle un nombre</b>"))
        self.nombre = QLineEdit()
        self.nombre.setPlaceholderText(_("Por ejemplo: Drive del trabajo, Fotos de casa…"))
        self.nombre.textChanged.connect(self._vista_carpeta)
        self.nombre.returnPressed.connect(self.siguiente)
        l.addWidget(self.nombre)
        self.n_carpeta = etiqueta("", "pequeno")
        l.addWidget(self.n_carpeta)
        l.addSpacing(6)
        l.addWidget(etiqueta("<b>Antes de empezar, ten a mano:</b>"))
        self.n_necesitas = QVBoxLayout()
        l.addLayout(self.n_necesitas)
        l.addStretch(1)
        self.pilas.addWidget(w)

    def _preparar_nombre(self):
        servicio = self._servicio()
        self.n_tile.setPixmap(icono_servicio(self.tipo, servicio, 56))
        self.n_servicio.setText(servicio)
        if self.tipo == TIPO_FOTOS:
            self.n_explica.setText(
                _("Tus fotos aparecerán como una carpeta, ordenadas por álbumes. <b>Se ven en línea: no "
                "se copian a tu ordenador</b> (solo se guardan un rato las que abres, para que vayan "
                "rápido).<br>Es de <b>solo lectura</b>: puedes ver y copiar fotos, pero no borrar ni "
                "subir desde aquí. Para eso, usa tu iPhone."))
        else:
            self.n_explica.setText(_("Tus archivos aparecerán como una carpeta normal de tu ordenador."))
        if not self.nombre.text():
            self.nombre.setText(self._nombre_libre(servicio.split(" (")[0].split(" / ")[0]))
        while self.n_necesitas.count():
            item = self.n_necesitas.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.n_necesitas.addWidget(caja_pasos(necesitas(self.tipo, self.provs, servicio)))
        self._vista_carpeta(self.nombre.text())
        self.nombre.setFocus()
        self.nombre.selectAll()

    def _vista_carpeta(self, texto):
        self.n_carpeta.setText("📁  " + _("Se creará la carpeta:  Carpeta personal › {base} › <b>{nombre}</b>")
                               .format(base=BASE.name, nombre=limpiar_nombre(texto or BASE.name)))

    def _usados(self):
        return {limpiar_nombre(titulo_de(r, d)).lower() for r, d in self.existentes.items()}

    def _nombre_libre(self, base):
        nombre, n = base, 2
        while limpiar_nombre(nombre).lower() in self._usados():
            nombre = f"{base} {n}"
            n += 1
        return nombre

    # ---------- página: pregunta
    def _pagina_pregunta(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(10)
        cab = QHBoxLayout()
        self.p_tile = QLabel()
        cab.addWidget(self.p_tile)
        self.p_servicio = etiqueta("", "gris")
        cab.addWidget(self.p_servicio, 1)
        l.addLayout(cab)
        l.addSpacing(6)
        self.p_titulo = etiqueta("", "subtitulo")
        l.addWidget(self.p_titulo)
        self.p_texto = QLineEdit()
        self.p_texto.returnPressed.connect(self.siguiente)
        self.p_combo = QComboBox()
        self.p_mostrar = QCheckBox(_("Mostrar lo que escribo"))
        self.p_mostrar.toggled.connect(lambda v: self.p_texto.setEchoMode(
            QLineEdit.EchoMode.Normal if v else QLineEdit.EchoMode.Password))
        self.p_error = etiqueta("", "error")
        self.p_ayuda = etiqueta("")
        self.p_ayuda.setTextFormat(Qt.TextFormat.RichText)
        for x in (self.p_texto, self.p_combo, self.p_mostrar, self.p_error):
            l.addWidget(x)
        caja = QFrame()
        caja.setObjectName("caja")
        cl = QVBoxLayout(caja)
        cl.setContentsMargins(16, 12, 16, 12)
        cl.addWidget(self.p_ayuda)
        self.p_caja = caja
        l.addWidget(caja)
        self.p_ver_original = boton("Ver la explicación técnica del servicio (en inglés)", "enlace")
        self.p_ver_original.setCheckable(True)
        self.p_original = etiqueta("", "pequeno")
        self.p_original.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.p_original.hide()
        self.p_ver_original.toggled.connect(self.p_original.setVisible)
        l.addWidget(self.p_ver_original, 0, Qt.AlignmentFlag.AlignLeft)
        l.addWidget(self.p_original)
        l.addStretch(1)
        self.pilas.addWidget(w)

    # ---------- página: navegador
    def _pagina_navegador(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(12)
        self.b_titulo = etiqueta("", "titulo")
        l.addWidget(self.b_titulo)
        self.b_sub = etiqueta("Sigue estos pasos. Esta ventana continuará sola cuando termines.", "gris")
        l.addWidget(self.b_sub)
        self.b_pasos = QVBoxLayout()
        l.addLayout(self.b_pasos)
        l.addSpacing(4)
        l.addWidget(etiqueta("<b>¿No se abrió ninguna página en tu navegador?</b>  "
                             "Pulsa este botón:"))
        fila = QHBoxLayout()
        self.b_abrir = boton("Preparando el enlace…", "grande", self._abrir_enlace)
        self.b_abrir.setEnabled(False)
        self.b_copiar = boton("Copiar enlace", None, self._copiar_enlace)
        self.b_copiar.setEnabled(False)
        fila.addWidget(self.b_abrir)
        fila.addWidget(self.b_copiar)
        fila.addStretch()
        l.addLayout(fila)
        self.b_copiado = etiqueta("", "pequeno")
        l.addWidget(self.b_copiado)
        l.addStretch(1)
        espera = QHBoxLayout()
        barra = QProgressBar()
        barra.setRange(0, 0)
        barra.setTextVisible(False)
        barra.setFixedWidth(120)
        espera.addWidget(barra)
        espera.addWidget(etiqueta("Esperando a que termines en el navegador…", "pequeno"), 1)
        l.addLayout(espera)
        self.pilas.addWidget(w)
        self.enlace_auth = None

    def _mostrar_navegador(self):
        servicio = self._servicio()
        self.b_titulo.setText(_("Inicia sesión en {servicio}").format(servicio=servicio))
        while self.b_pasos.count():
            it = self.b_pasos.takeAt(0)
            if it.widget():
                it.widget().hide()
                it.widget().deleteLater()
        self.b_pasos.addWidget(caja_pasos([
            _("Mira tu navegador (Firefox, Chrome…): se ha abierto una página de <b>{servicio}</b>. "
              "Si no la ves, búscala en la barra de tareas, abajo.").format(servicio=servicio),
            "Elige tu cuenta, o escribe tu correo y tu contraseña.",
            "Te preguntará si das permiso a <b>«rclone»</b> (es el programa que conecta tu nube; "
            "es seguro). Pulsa <b>«Permitir»</b> o <b>«Aceptar»</b>.",
            "Cuando veas la palabra <b>«Success!»</b> (significa «¡Listo!»), cierra esa pestaña "
            "y vuelve a esta ventana.",
        ]))
        self.enlace_auth = None
        self.b_abrir.setEnabled(False)
        self.b_copiar.setEnabled(False)
        self.b_abrir.setText(_("Preparando el enlace…"))
        self.b_copiado.setText("")
        self.ir(P_NAVEGADOR)

    def _enlace(self, url):
        self.enlace_auth = url
        self.b_abrir.setText(_("Abrir la página de inicio de sesión"))
        self.b_abrir.setEnabled(True)
        self.b_copiar.setEnabled(True)

    def _abrir_enlace(self):
        if self.enlace_auth:
            QDesktopServices.openUrl(QUrl(self.enlace_auth))

    def _copiar_enlace(self):
        if self.enlace_auth:
            QGuiApplication.clipboard().setText(self.enlace_auth)
            self.b_copiado.setText(_("✓ Copiado. Ahora abre tu navegador, haz clic en la barra de "
                                   "direcciones (arriba), pega con Ctrl+V y pulsa Intro."))

    # ---------- página: espera
    def _pagina_espera(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.addStretch()
        self.e_icono = QLabel()
        self.e_icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.e_titulo = etiqueta("", "subtitulo")
        self.e_titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.e_texto = etiqueta("", "gris")
        self.e_texto.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.e_barra = QProgressBar()
        self.e_barra.setRange(0, 0)
        self.e_barra.setTextVisible(False)
        self.e_barra.setFixedWidth(260)
        for x in (self.e_icono, self.e_titulo, self.e_texto):
            l.addWidget(x)
        l.addSpacing(8)
        l.addWidget(self.e_barra, 0, Qt.AlignmentFlag.AlignCenter)
        l.addStretch()
        self.pilas.addWidget(w)

    def _esperar(self, titulo, texto, progreso=None):
        if self.tipo:
            self.e_icono.setPixmap(icono_servicio(self.tipo, self._servicio(), 64))
        self.e_titulo.setText(_(titulo))
        self.e_texto.setText(_(texto))
        if progreso is None:
            self.e_barra.setRange(0, 0)
        else:
            self.e_barra.setRange(0, 100)
            self.e_barra.setValue(progreso)
        self.ir(P_ESPERA)

    # ---------- página: final
    def _pagina_fin(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.addStretch()
        self.f_icono = QLabel()
        self.f_icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.f_titulo = etiqueta("", "titulo")
        self.f_titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.f_texto = etiqueta("")
        self.f_texto.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.f_detalle = etiqueta("", "pequeno")
        self.f_detalle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.f_detalle.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        for x in (self.f_icono, self.f_titulo, self.f_texto, self.f_detalle):
            l.addWidget(x)
        l.addStretch()
        self.pilas.addWidget(w)

    def _final(self, ok, titulo, texto, detalle=None):
        self.ok_final = ok
        self.f_icono.setPixmap(circulo(ok))
        self.f_titulo.setText(_(titulo))
        self.f_texto.setText(_(texto))
        self.f_detalle.setText(_("Detalle técnico (para quien te ayude): {detalle}").format(
            detalle=detalle) if detalle and detalle != texto else "")
        self.f_detalle.setVisible(bool(self.f_detalle.text()))
        self.ir(P_FIN)
        if ok:
            self.btn_sig.setText(_("Listo"))
            self.btn_otro.setText(_("Abrir la carpeta"))
            self.btn_otro.setVisible(bool(self.ruta_final))
        else:
            self.btn_sig.setText(_("Intentar de nuevo"))
            self.btn_otro.setText(_("Cerrar"))
            self.btn_otro.show()
        self.raise_()
        self.activateWindow()

    def _abrir_final(self):
        if getattr(self, "ok_final", False) and self.ruta_final:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.ruta_final)))
            self.accept()
        else:
            self.reject()

    # ---------- flujo
    def siguiente(self):
        i = self.pilas.currentIndex()
        if i == P_SERVICIO:
            it = self.lista.currentItem()
            if not it or it.isHidden():
                avisar(self, "Primero haz clic en el servicio que quieres añadir.")
                return
            nuevo = it.data(Qt.ItemDataRole.UserRole)
            if nuevo != self.tipo:
                self.nombre.clear()
            self.tipo = nuevo
            self._preparar_nombre()
            self.ir(P_NOMBRE)
        elif i == P_NOMBRE:
            self._empezar()
        elif i == P_PREGUNTA:
            self._responder()
        elif i == P_FIN:
            if getattr(self, "ok_final", False):
                self.accept()
            else:
                self.reintentar = True
                self.reject()

    def _empezar(self):
        titulo = self.nombre.text().strip()
        if not titulo:
            avisar(self, "Escribe un nombre para esta nube, por ejemplo «Mis fotos».")
            return
        if limpiar_nombre(titulo).lower() in self._usados():
            avisar(self, "Ya tienes una nube con ese nombre. Escribe otro distinto.")
            return
        self.titulo = titulo
        base, n = slug(titulo), 2
        self.remoto = base
        while self.remoto in self.existentes:
            self.remoto = f"{base}-{n}"
            n += 1
        self._crear()

    def _crear(self):
        if self.tipo == TIPO_FOTOS:
            self.tipo_rclone, self.extra = "iclouddrive", ["service=photos"]
            if not soporta_fotos():
                self._esperar("Preparando iCloud Fotos…",
                              "Descargando una versión más nueva de rclone (unos 25 MB). "
                              "Solo pasa una vez.", 0)
                self.lz.lanzar(descargar_rclone, [EVENTOS.progreso.emit], self._rclone_listo)
                return
        else:
            self.tipo_rclone = self.tipo
            self.extra = ["service=drive"] if self.tipo == "iclouddrive" and soporta_fotos() else []
        self._esperar("Preparando…", "Un momento.")
        self.lz.lanzar(tarea_crear, [self.remoto, self.tipo_rclone, self.titulo, self.extra],
                       self._respuesta)

    def _rclone_listo(self, res):
        if not res[0] or not soporta_fotos():
            self._final(False, "No se pudo preparar iCloud Fotos",
                        "No se pudo descargar lo necesario. Comprueba tu internet e inténtalo "
                        "de nuevo.", res[1] if len(res) > 1 else None)
            return
        self._crear()

    def _respuesta(self, d):
        self.esperando_navegador = False
        if isinstance(d, tuple):
            d = {"_error": d[1]}
        if d.get("_error"):
            self._fallo(d["_error"])
            return
        estado = d.get("State") or ""
        if not estado:
            if d.get("Error"):
                self._fallo(d["Error"])
                return
            self.raise_()
            self.activateWindow()
            self._esperar("Comprobando la conexión…", "Estamos mirando que todo funcione. Un momento.")
            self.lz.lanzar(tarea_verificar_y_montar, [self.remoto], self._verificado)
            return
        opt = d.get("Option") or {}
        nombre = opt.get("Name", "")
        auto_tipo = (self.tipo_rclone, nombre) in AUTO_POR_TIPO
        if not self.experto.isChecked() and (nombre in AUTOMATICAS or auto_tipo) \
                and not d.get("Error"):
            if nombre == "config_is_local":
                resp = "true"
                self.esperando_navegador = True
                self._mostrar_navegador()
            elif auto_tipo and AUTO_POR_TIPO[(self.tipo_rclone, nombre)] is not None:
                resp = AUTO_POR_TIPO[(self.tipo_rclone, nombre)]
                self._esperar("Preparando…", "Un momento.")
            else:
                resp = "false" if nombre == "config_fs_advanced" else opt.get("DefaultStr", "")
                self._esperar("Preparando…", "Un momento.")
            self.lz.lanzar(tarea_continuar, [self.remoto, estado, resp, self.esperando_navegador],
                           self._respuesta)
            return
        self.estado, self.opcion = estado, opt
        self._mostrar_pregunta(opt, d.get("Error", ""))

    def _mostrar_pregunta(self, opt, error):
        nombre = opt.get("Name", "")
        etiqueta_t, ayuda = TRADUCCION.get(nombre, (None, None))
        if nombre == "2fa" and opt.get("Type") == "bool":
            etiqueta_t, ayuda = ("¿Tu cuenta usa verificación en dos pasos?",
                                 "Elige «Sí» si al entrar te piden un código además de la contraseña.")
        if self.tipo_rclone == "iclouddrive" and nombre == "password":
            etiqueta_t, ayuda = ("Tu contraseña de Apple",
                                 "La misma que usas en tu iPhone para la App Store o iCloud. "
                                 "Se guarda cifrada en este ordenador.")
        ayuda_original = (opt.get("Help") or "").strip()
        legible = nombre.replace("config_", "").replace("_", " ")
        if not etiqueta_t:
            etiqueta_t = (_("¿Activar la opción «{opcion}»?") if opt.get("Type") == "bool"
                          else _("Dato solicitado: «{opcion}»")).format(opcion=legible)
            ayuda = ("Si no sabes qué poner, <b>deja lo que viene escrito y pulsa «Siguiente»</b>. "
                     "Casi siempre es lo correcto.")
        original = ayuda_original if nombre not in TRADUCCION else ""
        ayuda = _(ayuda or "").replace("\n", "<br>")
        if not opt.get("Required"):
            ayuda += _("<br><br><span style='color:%s'>Este dato es opcional.</span>") % T["gris"]
        if error:
            error = "⚠  " + traducir_error(error)[0]
        self._pregunta(_(etiqueta_t), ayuda, error, opt, original)

    def _pregunta(self, titulo, ayuda, error, opt, original=""):
        """Muestra una pregunta (de rclone o de iCloud Fotos)."""
        servicio = self._servicio()
        self.p_tile.setPixmap(icono_servicio(self.tipo, servicio, 36))
        self.p_servicio.setText(f"<b>{self.titulo}</b>" if self.titulo == servicio
                                else f"<b>{self.titulo}</b> · {servicio}")
        self.p_original.setText(original)
        self.p_ver_original.setChecked(False)
        self.p_ver_original.setVisible(bool(original))
        self.p_titulo.setText(_(titulo))
        self.p_ayuda.setText(_(ayuda))
        self.p_caja.setVisible(bool(ayuda))
        self.p_error.setText(_(error) or "")
        self.p_error.setVisible(bool(error))
        nombre = opt.get("Name", "")
        ejemplos = opt.get("Examples") or []
        defecto = opt.get("DefaultStr") or ""
        es_bool = opt.get("Type") == "bool"
        self.p_mostrar.setChecked(False)
        self.p_mostrar.setVisible(bool(opt.get("IsPassword")))
        if es_bool or ejemplos:
            self.p_combo.clear()
            self.p_combo.setEditable(not es_bool and not opt.get("Exclusive"))
            if es_bool:
                self.p_combo.addItem(_("Sí"), "true")
                self.p_combo.addItem(_("No"), "false")
            else:
                if not opt.get("Exclusive") and defecto == "" and not opt.get("Required"):
                    self.p_combo.addItem(_("(dejar vacío)"), "")
                for e in ejemplos:
                    v = e.get("Value", "")
                    self.p_combo.addItem(texto_ejemplo(nombre, v, e.get("Help") or ""), v)
            idx = self.p_combo.findData(defecto)
            self.p_combo.setCurrentIndex(max(idx, 0))
            self.p_combo.show()
            self.p_texto.hide()
            self.p_combo.setFocus()
        else:
            self.p_texto.setEchoMode(QLineEdit.EchoMode.Password if opt.get("IsPassword")
                                     else QLineEdit.EchoMode.Normal)
            self.p_texto.setText("" if opt.get("IsPassword") else defecto)
            self.p_texto.setPlaceholderText(_(PLACEHOLDER.get(nombre, "")))
            self.p_texto.show()
            self.p_combo.hide()
            self.p_texto.setFocus()
        self.ir(P_PREGUNTA)
        self.raise_()
        self.activateWindow()

    def _leer_respuesta(self):
        opt = self.opcion
        if self.p_combo.isVisible():
            i = self.p_combo.currentIndex()
            texto = self.p_combo.currentText()
            if self.p_combo.isEditable() and (i < 0 or texto != self.p_combo.itemText(i)):
                return texto.strip()
            return self.p_combo.itemData(i) if i >= 0 else ""
        resp = self.p_texto.text()
        return resp if opt.get("IsPassword") else resp.strip()

    def _responder(self):
        opt = self.opcion
        resp = self._leer_respuesta()
        if opt.get("Required") and not resp:
            avisar(self, "Este dato es obligatorio. Escríbelo para poder continuar.")
            return
        if opt.get("IsPassword") and resp:
            resp = ofuscar(resp)
        self._esperar("Comprobando…", "Un momento.")
        self.lz.lanzar(tarea_continuar, [self.remoto, self.estado, resp, False], self._respuesta)

    def _verificado(self, res):
        if res[0] == "ok":
            self._exito()
        elif res[0] == "montar":
            self._final(False, "Casi listo",
                        "Tu cuenta quedó guardada, pero no se pudo abrir la carpeta. Cierra esta "
                        "ventana y pulsa «Reintentar» en la tarjeta de esta nube.")
            self.resultado = self.remoto
            self.btn_sig.setText(_("Cerrar"))
            self.ok_final = True
        else:
            explicacion = traducir_error(res[1])[0]
            if confirmar(self, _("Los datos se guardaron, pero no pudimos comprobar que funcionen:"
                                 "\n\n{explicacion}\n\n¿Quieres guardarla de todas formas?")
                         .format(explicacion=explicacion),
                         si="Guardar igualmente", no="No guardar"):
                self._esperar("Abriendo la carpeta…", "Un momento.")
                self.lz.lanzar(tarea_montar, [self.remoto],
                               lambda r2: self._exito() if r2[0] else self._verificado(("montar",)))
            else:
                run([RCLONE, "config", "delete", self.remoto])
                self._final(False, "No se añadió", "Puedes intentarlo de nuevo cuando quieras.")

    def _exito(self):
        self.resultado = self.remoto
        self.ruta_final = carpeta_de(self.remoto, config_dump().get(self.remoto, {}))
        if self.reconectar:
            self._final(True, "¡Sesión iniciada!", _("«{nombre}» vuelve a funcionar. "
                        "Dentro de 30 días Apple te lo volverá a pedir.").format(nombre=self.titulo))
            return
        if self.tipo == TIPO_FOTOS:
            self._final(True, "¡iCloud Fotos está listo!",
                        _("Tus fotos están en la carpeta <b>{base} › {carpeta}</b>, "
                          "ordenadas por álbumes (todas juntas están en «All Photos»)."
                          "<br><br>La primera vez puede tardar unos minutos en mostrar todas las "
                          "fotos si tienes muchas. Las siguientes veces irá rápido.")
                        .format(base=BASE.name, carpeta=self.ruta_final.name))
            return
        self._final(True, _("¡«{nombre}» está lista!").format(nombre=self.titulo),
                    _("Tus archivos ya aparecen en la carpeta <b>{base} › {carpeta}</b>."
                      "<br>Se abrirá sola cada vez que enciendas el ordenador."
                      "<br><br>Consejo: también la tienes en el panel izquierdo del explorador de "
                      "archivos, en «Mis nubes».").format(base=BASE.name, carpeta=self.ruta_final.name))

    def _fallo(self, msg):
        if self.remoto and not self.reconectar:
            run([RCLONE, "config", "delete", self.remoto])
        explicacion, detalle = traducir_error(msg)
        self._final(False, "No se pudo conectar", explicacion, detalle)

    # ---------- cancelar / cerrar
    def cancelar(self):
        p = PROCESO["p"]
        if p:
            p.kill()
        if self.remoto and self.pilas.currentIndex() != P_FIN and not self.reconectar:
            run([RCLONE, "config", "delete", self.remoto])
        self.reject()

    def done(self, r):
        for senal, f in ((EVENTOS.enlace, self._enlace), (EVENTOS.progreso, self.e_barra.setValue)):
            try:
                senal.disconnect(f)
            except TypeError:
                pass
        super().done(r)

    def closeEvent(self, ev):
        if self.pilas.currentIndex() != P_FIN:
            self.cancelar()
        ev.accept()


# ================================================================ acerca de
class AcercaDe(QDialog):
    def __init__(self, padre):
        super().__init__(padre)
        self.setWindowTitle(_("Acerca de Mis nubes"))
        self.setFixedWidth(420)
        l = QVBoxLayout(self)
        l.setContentsMargins(30, 26, 30, 22)
        l.setSpacing(8)
        ico = QLabel()
        ico.setPixmap(icono_app().pixmap(96, 96))
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l.addWidget(ico)
        for texto, nombre in (("Mis nubes", "titulo"), (_("Versión {v}").format(v=VERSION), "gris"),
                              (CREDITOS, None),
                              ("Tus nubes como carpetas normales en Linux: Google Drive, OneDrive, "
                               "iCloud, Dropbox, MEGA y muchas más.", "gris"),
                              ("Funciona gracias a <b>rclone</b> (rclone.org), un programa libre. "
                               "Iconos de los servicios: tema libre <b>Papirus</b>.", "pequeno")):
            e = etiqueta(texto, nombre)
            e.setAlignment(Qt.AlignmentFlag.AlignCenter)
            l.addWidget(e)
        l.addSpacing(10)
        # Idioma (Language): se guarda y se aplica al volver a abrir la aplicación
        fila = QHBoxLayout()
        fila.addStretch()
        fila.addWidget(etiqueta("Idioma:", "gris", False))
        self.idioma = QComboBox()
        self.idioma.addItem(_("Automático (el del sistema)"), "auto")
        for codigo in idiomas_disponibles():
            self.idioma.addItem(nombre_idioma(codigo), codigo)
        actual = leer_ajustes().get("idioma", "auto")
        self.idioma.setCurrentIndex(max(self.idioma.findData(actual), 0))
        self.idioma.currentIndexChanged.connect(self._cambiar_idioma)
        fila.addWidget(self.idioma)
        fila.addStretch()
        l.addLayout(fila)
        l.addSpacing(6)
        l.addWidget(boton("Cerrar", "primario", self.accept), 0, Qt.AlignmentFlag.AlignCenter)

    def _cambiar_idioma(self):
        guardar_ajuste("idioma", self.idioma.currentData())
        if confirmar(self, "El idioma cambiará al volver a abrir Mis nubes. ¿Reiniciar ahora?",
                     si="Reiniciar ahora", no="Más tarde"):
            os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve())])


# ================================================================ tarjetas
class Tarjeta(QFrame):
    def __init__(self, ventana, remoto):
        super().__init__()
        self.v, self.remoto = ventana, remoto
        self.ocupada = False
        self.modo = None
        self.datos = {}
        self.setObjectName("tarjeta")
        sombra(self)
        fila = QHBoxLayout(self)
        fila.setContentsMargins(16, 14, 14, 14)
        fila.setSpacing(14)
        self.ico = QLabel()
        fila.addWidget(self.ico, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(3)
        arriba = QHBoxLayout()
        self.titulo = etiqueta("", "nombre", True)
        self.estado = QLabel()
        arriba.addWidget(self.titulo)
        arriba.addWidget(self.estado)
        arriba.addStretch()
        col.addLayout(arriba)
        self.sub = etiqueta("", "gris")
        col.addWidget(self.sub)
        self.barra_espacio = QProgressBar()
        self.barra_espacio.setTextVisible(False)
        self.barra_espacio.setMaximumWidth(260)
        self.barra_espacio.hide()
        self.espacio = etiqueta("", "pequeno")
        self.espacio.hide()
        col.addWidget(self.barra_espacio)
        col.addWidget(self.espacio)
        self.barra = QProgressBar()
        self.barra.setRange(0, 0)
        self.barra.setTextVisible(False)
        self.barra.setMaximumWidth(260)
        self.barra.hide()
        col.addWidget(self.barra)
        fila.addLayout(col, 1)
        self.btn = boton("", "primario", lambda: self.v.accion(self))
        self.btn.setMinimumWidth(140)
        fila.addWidget(self.btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self.mas = boton("⋯", "redondo")
        self.mas.setToolTip(_("Más opciones"))
        menu = QMenu(self)
        menu.addAction(_("Abrir la carpeta"), lambda: self.v.abrir(self.ruta))
        self.accion_sesion = menu.addAction(_("Volver a iniciar sesión…"), lambda: self.v.reconectar(self))
        menu.addAction(_("Cambiar nombre…"), lambda: self.v.renombrar(self))
        menu.addSeparator()
        menu.addAction(_("Desconectar…"), lambda: self.v.quitar(self))
        self.mas.setMenu(menu)
        fila.addWidget(self.mas, 0, Qt.AlignmentFlag.AlignVCenter)

    def ocupado(self, texto):
        self.ocupada = True
        pastilla(self.estado, texto, T["acento"])
        self.barra.show()
        self.btn.setEnabled(False)
        self.mas.setEnabled(False)

    def libre(self):
        self.ocupada = False
        self.barra.hide()
        self.btn.setEnabled(True)
        self.mas.setEnabled(True)

    def mostrar_espacio(self, usado, total):
        if usado is None:
            return
        if total:
            self.barra_espacio.setRange(0, 1000)
            self.barra_espacio.setValue(int(usado * 1000 / total))
            self.barra_espacio.show()
            self.espacio.setText(_("{usado} usados de {total}").format(usado=tamano(usado), total=tamano(total)))
        elif self.datos.get("type") == "iclouddrive":
            self.espacio.setText(_("Tus archivos ocupan {usado} en iCloud Drive").format(usado=tamano(usado)))
            self.espacio.setToolTip(_("Apple no permite consultar el total de tu plan desde aquí. "
                                    "Las fotos no se cuentan: ocupan aparte."))
        else:
            self.espacio.setText(_("{usado} usados").format(usado=tamano(usado)))
        self.espacio.show()

    def actualizar(self, datos, provs):
        self.datos = datos
        clave, servicio = servicio_de(datos, provs)
        self.es_icloud = datos.get("type") == "iclouddrive"
        self.nombre = titulo_de(self.remoto, datos)
        self.ruta = carpeta_de(self.remoto, datos)
        self.ico.setPixmap(icono_servicio(clave, servicio, 48))
        self.titulo.setText(self.nombre)
        extra = " · " + _("solo lectura") if clave == TIPO_FOTOS else ""
        self.sub.setText(f"{servicio}{extra} · {BASE.name} › {self.ruta.name}")
        self.accion_sesion.setVisible(self.es_icloud)
        if self.ocupada:
            return
        tiene_unidad = (UNIT_DIR / unidad_de(self.remoto)).exists()
        if tiene_unidad and montado(self.ruta):
            self._estado("Conectada", T["verde"], "Abrir", "abrir", True)
        elif tiene_unidad:
            self._estado("Sin conexión", T["naranja"], "Reintentar", "montar", False)
        else:
            self._estado("No aparece como carpeta", T["gris"], "Mostrar carpeta", "montar", False)

    def _estado(self, texto, color, boton_txt, modo, principal):
        pastilla(self.estado, texto, color)
        self.btn.setText(_(boton_txt))
        self.btn.setObjectName("primario" if principal else "")
        self.btn.style().unpolish(self.btn)
        self.btn.style().polish(self.btn)
        self.modo = modo


# ================================================================ ventana
class Ventana(QWidget):
    def __init__(self, aviso_inicial=None):
        super().__init__()
        self.setObjectName("raiz")
        self.setWindowTitle(_(APP))
        self.setWindowIcon(icono_app())
        self.resize(780, 640)
        self.lz = Lanzador()
        self.provs = proveedores()
        self.tarjetas = {}
        self.espacio_pedido = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 18)
        lay.setSpacing(14)

        cab = QHBoxLayout()
        cab.setSpacing(14)
        logo = QLabel()
        logo.setPixmap(icono_app().pixmap(60, 60))
        cab.addWidget(logo)
        tit = QVBoxLayout()
        tit.setSpacing(2)
        tit.addWidget(etiqueta("Mis nubes", "titulo"))
        tit.addWidget(etiqueta("Tus nubes, como carpetas normales de tu ordenador.", "gris"))
        cab.addLayout(tit, 1)
        cab.addWidget(boton("＋  Añadir nube", "primario", lambda: self.anadir()), 0,
                      Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(cab)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        cont = QWidget()
        self.lista = QVBoxLayout(cont)
        self.lista.setContentsMargins(4, 6, 4, 6)
        self.lista.setSpacing(12)

        self.vacio = QWidget()
        lv = QVBoxLayout(self.vacio)
        lv.addStretch()
        ico = QLabel()
        ico.setPixmap(icono_app().pixmap(110, 110))
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lv.addWidget(ico)
        t1 = etiqueta("Todavía no tienes ninguna nube", "subtitulo")
        t1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t2 = etiqueta("Añade Google Drive, OneDrive, iCloud, Dropbox y muchas más.\n"
                      "Aparecerán como carpetas y se abrirán solas al encender el ordenador.", "gris")
        t2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lv.addWidget(t1)
        lv.addWidget(t2)
        lv.addSpacing(10)
        lv.addWidget(boton("Añadir mi primera nube", "grande", lambda: self.anadir()), 0,
                     Qt.AlignmentFlag.AlignCenter)
        lv.addStretch()
        self.lista.addWidget(self.vacio)
        self.lista.addStretch()
        self.scroll.setWidget(cont)
        lay.addWidget(self.scroll, 1)

        pie = QHBoxLayout()
        self.aviso = etiqueta("", None)
        pie.addWidget(self.aviso, 1)
        pie.addWidget(boton(_("Abrir carpeta {base}").format(base=BASE.name), None,
                            lambda: self.abrir(BASE)))
        pie.addWidget(boton("ⓘ", "redondo", lambda: AcercaDe(self).exec()))
        lay.addLayout(pie)
        creditos = etiqueta(CREDITOS, "pequeno")
        creditos.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(creditos)

        self.cache_espacio = espacio_guardado()
        self.refrescar()
        self.reloj = QTimer(self)
        self.reloj.timeout.connect(self.refrescar)
        self.reloj.start(6000)
        if aviso_inicial:
            QTimer.singleShot(600, lambda: avisar(self, aviso_inicial))

    def refrescar(self):
        dump = config_dump()
        for r in list(self.tarjetas):
            if r not in dump:
                self.tarjetas.pop(r).deleteLater()
        for i, r in enumerate(sorted(dump, key=lambda r: titulo_de(r, dump[r]).lower())):
            nueva = r not in self.tarjetas
            if nueva:
                self.tarjetas[r] = Tarjeta(self, r)
            tj = self.tarjetas[r]
            self.lista.insertWidget(i, tj)
            tj.actualizar(dump[r], self.provs)
            if nueva and r in self.cache_espacio:
                usado, total, _ = self.cache_espacio[r]
                tj.mostrar_espacio(usado, total)
            # OneDrive, Google… cada 10 min; iCloud Drive (hay que sumar archivos) cada 6 h
            cada = 6 * 3600 if dump[r].get("type") == "iclouddrive" else 600
            ultimo = self.espacio_pedido.get(r, 0)
            if dump[r].get("type") == "iclouddrive":
                ultimo = max(ultimo, self.cache_espacio.get(r, [0, 0, 0])[2])
            if time.time() - ultimo > cada and montado(tj.ruta):
                self.espacio_pedido[r] = time.time()
                self.lz.lanzar(tarea_espacio, [r, dump[r]], self._espacio)
        self.vacio.setVisible(not dump)

    def _espacio(self, res):
        remoto, usado, total = res
        if remoto in self.tarjetas:
            self.tarjetas[remoto].mostrar_espacio(usado, total)

    def abrir(self, ruta):
        BASE.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(ruta)))

    def mensaje(self, ok, texto):
        if ok:
            self.aviso.setText(f"<span style='color:{T['verde']}'>✓ {_(texto)}</span>")
            QTimer.singleShot(8000, lambda: self.aviso.setText(""))
        else:
            self.aviso.setText("")
            avisar(self, texto)

    def tras_tarea(self, tj, res):
        tj.libre()
        self.refrescar()
        self.mensaje(*res)

    # ---------- acciones
    def anadir(self, tipo=None, nombre=""):
        while True:
            a = Asistente(self, self.provs, config_dump(), tipo, nombre)
            a.exec()
            self.refrescar()
            if a.resultado:
                self.mensaje(True, "Nube añadida.")
            if not a.reintentar:
                break
            tipo, nombre = a.tipo, a.titulo

    def reconectar(self, tj):
        while True:
            a = Asistente(self, self.provs, config_dump(), reconectar=tj.remoto)
            a.exec()
            self.refrescar()
            if not a.reintentar:
                break

    def accion(self, tj):
        if tj.modo == "abrir":
            self.abrir(tj.ruta)
        elif tj.modo == "montar":
            tj.ocupado("Conectando…")
            self.lz.lanzar(tarea_montar, [tj.remoto], lambda r: self.tras_tarea(tj, r))

    def renombrar(self, tj):
        nuevo, ok = pedir_texto(self, "Cambiar nombre",
                                "Escribe el nuevo nombre (su carpeta también cambiará de nombre):",
                                tj.nombre)
        nuevo = nuevo.strip()
        if not ok or not nuevo or nuevo == tj.nombre:
            return
        usados = {limpiar_nombre(titulo_de(r, d)).lower() for r, d in config_dump().items()
                  if r != tj.remoto}
        if limpiar_nombre(nuevo).lower() in usados:
            avisar(self, "Ya tienes una nube con ese nombre. Escribe otro distinto.")
            return
        tj.ocupado("Cambiando el nombre…")
        self.lz.lanzar(tarea_renombrar, [tj.remoto, nuevo], lambda r: self.tras_tarea(tj, r))

    def quitar(self, tj):
        if not confirmar(self, _("¿Desconectar «{nombre}»?\n\nTranquilo: tus archivos en la nube "
                                 "NO se borran. Solo deja de aparecer la carpeta en este ordenador.")
                         .format(nombre=tj.nombre),
                         si="Desconectar", no="Cancelar"):
            return
        tj.ocupado("Desconectando…")
        self.lz.lanzar(tarea_desconectar, [tj.remoto], lambda res: self.tras_tarea(tj, res))

    def closeEvent(self, ev):
        if any(t.fn is not tarea_espacio for t in self.lz.tareas):
            if not confirmar(self, "Todavía se está haciendo algo. ¿Cerrar de todas formas?",
                             si="Cerrar", no="Esperar"):
                ev.ignore()
                return
            if PROCESO["p"]:
                PROCESO["p"].kill()
        os._exit(0)


def main():
    cargar_idioma()
    elegir_carpeta_base()
    app = QApplication(sys.argv)
    app.setApplicationName(_(APP))
    app.setDesktopFileName("mis-nubes")
    traductor = QTranslator(app)
    if traductor.load(QLocale(IDIOMA), "qtbase", "_",
                      QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(traductor)
    aplicar_tema(app)
    elegir_rclone()
    if not (shutil.which("rclone") or RCLONE_PROPIO.exists()) or not shutil.which("fusermount3"):
        avisar(None, "Faltan algunos programas necesarios. Cierra esta ventana y vuelve a abrir "
                     "el archivo «Mis nubes» para instalarlos.")
        return 1
    preparar_sistema()
    instalar_extras()
    aviso = None
    copiadas = migrar_fotos_copia()
    if copiadas:
        aviso = _("Novedad: iCloud Fotos ahora funciona en línea, sin copiar las fotos a tu "
                  "ordenador. Para usarlo, pulsa «Añadir nube» y elige «iCloud Fotos».\n\n"
                  "Las fotos que ya se habían copiado siguen en la carpeta «{carpetas}». "
                  "Si no las necesitas, puedes borrar esa carpeta para liberar espacio.").format(
            carpetas="», «".join(f"{BASE.name} › {c}" for c in copiadas))
    app.setWindowIcon(icono_app())
    v = Ventana(aviso)
    v.show()
    return app.exec()


# ================================================================ catálogos de idiomas
# Inglés (incluido en el programa). Otros idiomas: archivos idiomas/<código>.json
TRADUCCIONES["en"] = {
    "_idioma": "English",
    "Mis nubes": "My Clouds",
    "Creado por Jose Callejas (Callejasto) y Claude (Anthropic)": "Created by Jose Callejas (Callejasto) and Claude (Anthropic)",
    "Nube": "Clouds",
    "Tu navegador de internet (Firefox, Chrome…). Allí iniciarás sesión de forma segura: <b>tu contraseña nunca se escribe en esta aplicación</b>.": "Your web browser (Firefox, Chrome…). You will sign in there securely: <b>your password is never typed into this app</b>.",
    "Acceso completo (recomendado)": "Full access (recommended)",
    "Solo lectura (ver y descargar)": "Read only (view and download)",
    "Solo archivos creados desde este ordenador": "Only files created from this computer",
    "Carpeta de datos de aplicaciones": "Application data folder",
    "Solo ver nombres de archivos": "Only see file names",
    "Mundial (recomendado)": "Worldwide (recommended)",
    "Gobierno de Estados Unidos": "US Government",
    "Alemania (antiguo)": "Germany (legacy)",
    "Estados Unidos / Global": "United States / Global",
    "Europa": "Europe",
    "Japón": "Japan",
    "SharePoint Online (cuenta de Microsoft)": "SharePoint Online (Microsoft account)",
    "SharePoint en un servidor propio": "SharePoint on your own server",
    "Servidor WebDAV de rclone": "rclone WebDAV server",
    "Otro": "Other",
    "Cuenta personal": "Personal account",
    "Cuenta de servicio de empresa": "Business service account",
    "Otro compatible con Koofr": "Other Koofr-compatible service",
    "Activado": "On",
    "Desactivado": "Off",
    "OneDrive personal o de empresa (recomendado)": "OneDrive personal or business (recommended)",
    "Sitio principal de SharePoint": "Main SharePoint site",
    "Sitio de SharePoint por nombre o dirección": "SharePoint site by name or address",
    "Buscar un sitio de SharePoint": "Search for a SharePoint site",
    "Escribir el ID de la unidad (avanzado)": "Type the drive ID (advanced)",
    "Escribir el ID del sitio (avanzado)": "Type the site ID (advanced)",
    "Ruta del servidor de SharePoint (avanzado)": "SharePoint server path (advanced)",
    "(dejar vacío)": "(leave empty)",
    "Sí": "Yes",
    "No": "No",
    "tu usuario o correo": "your username or email",
    "tu contraseña": "your password",
    "déjalo como está": "leave it as it is",
    "tunombre@icloud.com": "yourname@icloud.com",
    "192.168.1.10   o   servidor.com": "192.168.1.10   or   server.com",
    "tu@correo.com": "you@email.com",
    "https://mi-nube.com/remote.php/dav/files/USUARIO": "https://my-cloud.com/remote.php/dav/files/USERNAME",
    "Servicio": "Service",
    "Nombre": "Name",
    "Conectar": "Connect",
    "Listo": "Done",
    "Google Fotos": "Google Photos",
    "iCloud Fotos": "iCloud Photos",
    "Nextcloud / WebDAV": "Nextcloud / WebDAV",
    "Carpeta compartida de red (SMB / Windows)": "Shared network folder (SMB / Windows)",
    "Servidor SFTP / SSH": "SFTP / SSH server",
    "Servidor FTP": "FTP server",
    "Amazon S3 y compatibles (R2, Wasabi, MinIO…)": "Amazon S3 and compatible (R2, Wasabi, MinIO…)",
    "Acceso directo a otra nube que ya tengas": "Shortcut to another cloud you already have",
    "Sistema de archivos Hadoop (HDFS)": "Hadoop file system (HDFS)",
    "Conjuntos de datos científicos (DOI)": "Scientific datasets (DOI)",
    "Página web, solo lectura (HTTP)": "Web page, read only (HTTP)",
    "Carpeta cifrada con contraseña (dentro de otra nube)": "Password-encrypted folder (inside another cloud)",
    "Dividir archivos grandes en trozos": "Split large files into chunks",
    "Juntar varias nubes en una": "Combine several clouds into one",
    "Comprobación extra de archivos": "Extra file checking",
    "Unir varias nubes en una sola carpeta": "Merge several clouds into a single folder",
    "Comprimir otra nube": "Compress another cloud",
    "Google Cloud Storage (no es Google Drive)": "Google Cloud Storage (not Google Drive)",
    "Storj (nube descentralizada)": "Storj (decentralized cloud)",
    "Sia (nube descentralizada)": "Sia (decentralized cloud)",
    "Dirección del servidor (URL)": "Server address (URL)",
    "Es la dirección completa de tu servidor. En Nextcloud la encuentras entrando desde el navegador › «Archivos» › abajo a la izquierda «Ajustes de archivos» › «WebDAV».\n\nSe parece a esto: https://tu-servidor.com/remote.php/dav/files/USUARIO\n\nSi no la sabes, pídesela a quien administra tu servidor.": "It is the full address of your server. In Nextcloud, open it in your browser › “Files” › bottom left “Files settings” › “WebDAV”.\n\nIt looks like this: https://your-server.com/remote.php/dav/files/USERNAME\n\nIf you don't know it, ask whoever runs your server.",
    "Usuario": "Username",
    "Tu nombre de usuario o correo.": "Your username or email.",
    "Contraseña": "Password",
    "Se guarda cifrada en este ordenador.": "It is stored encrypted on this computer.",
    "Tu correo de Apple": "Your Apple email",
    "Es el correo con el que entras en tu iPhone o en icloud.com. Lo ves en el iPhone: Ajustes › (tu nombre, arriba del todo).": "It is the email you use on your iPhone or at icloud.com. You can see it on your iPhone: Settings › (your name, at the very top).",
    "Servidor": "Server",
    "Nombre o dirección IP del servidor, por ejemplo 192.168.1.10": "Server name or IP address, for example 192.168.1.10",
    "Puerto": "Port",
    "Déjalo como está si no sabes cuál es.": "Leave it as it is if you don't know.",
    "Tipo de servidor": "Server type",
    "Elige tu servidor (Nextcloud, ownCloud…) o déjalo vacío.": "Choose your server (Nextcloud, ownCloud…) or leave it empty.",
    "Proveedor": "Provider",
    "Elige tu proveedor de almacenamiento.": "Choose your storage provider.",
    "Clave de acceso (Access Key ID)": "Access Key ID",
    "Te la da tu proveedor.": "Your provider gives it to you.",
    "Clave secreta (Secret Access Key)": "Secret Access Key",
    "Región": "Region",
    "Dirección del servicio (endpoint)": "Service address (endpoint)",
    "Te la da tu proveedor. Déjalo vacío si no la sabes.": "Your provider gives it to you. Leave it empty if you don't know it.",
    "¿Usar credenciales del sistema?": "Use system credentials?",
    "Normalmente: No.": "Usually: No.",
    "Permisos": "Permissions",
    "Déjalo vacío para tener acceso completo.": "Leave it empty for full access.",
    "Dominio": "Domain",
    "Normalmente WORKGROUP. Déjalo como está si no lo sabes.": "Usually WORKGROUP. Leave it as it is if you don't know.",
    "Archivo de clave privada": "Private key file",
    "Déjalo vacío si entras con contraseña.": "Leave it empty if you sign in with a password.",
    "Escribe el código de 6 números": "Type the 6-digit code",
    "Mira tu iPhone, iPad o Mac: aparecerá un aviso de «Solicitud de inicio de sesión». Pulsa «Permitir» y después escribe aquí los 6 números que te muestra.\n\n¿No te llegó nada? Espera un minuto. Si sigue sin llegar, escribe la palabra sms y pulsa «Siguiente»: te llegará el código por mensaje de texto.": "Look at your iPhone, iPad or Mac: a “Sign-in request” notice will appear. Tap “Allow” and then type here the 6 digits it shows you.\n\nNothing arrived? Wait a minute. If it still doesn't arrive, type the word sms and press “Next”: you will get the code by text message.",
    "Código de verificación": "Verification code",
    "Abre la app donde recibes tus códigos (o mira tu SMS) y escribe aquí los números.": "Open the app where you get your codes (or check your SMS) and type the digits here.",
    "Tipo de cuenta": "Account type",
    "Elige qué almacenamiento quieres usar.": "Choose which storage you want to use.",
    "Unidad": "Drive",
    "Elige la unidad que quieres usar.": "Choose the drive you want to use.",
    "¿Es correcta esta unidad?": "Is this the right drive?",
    "Elige «Sí» para usarla.": "Choose “Yes” to use it.",
    "¿Usar una unidad compartida?": "Use a shared drive?",
    "Elige «No» para usar tu Google Drive normal.": "Choose “No” to use your regular Google Drive.",
    "Unidad compartida": "Shared drive",
    "Elige la unidad compartida que quieres usar.": "Choose the shared drive you want to use.",
    "ID de la cuenta (Account ID / keyID)": "Account ID / keyID",
    "Lo encuentras en la web de Backblaze, en «App Keys».": "You can find it on the Backblaze website, under “App Keys”.",
    "Clave de aplicación (Application Key)": "Application Key",
    "¿Borrar definitivamente?": "Delete permanently?",
    "Elige «No» para que lo que borres vaya primero a una papelera (más seguro).": "Choose “No” so deleted files go to a trash first (safer).",
    "¿Solo ver las fotos?": "Only view the photos?",
    "Elige «Sí» si solo quieres ver y descargar tus fotos, sin poder subir ni borrar.": "Choose “Yes” if you only want to view and download your photos, without uploading or deleting.",
    "Elige «Cuenta personal» si no sabes cuál es.": "Choose “Personal account” if you don't know.",
    "¿Conexión segura desde el inicio (FTPS implícito)?": "Secure connection from the start (implicit FTPS)?",
    "Normalmente: No. Pregúntale al dueño del servidor si no lo sabes.": "Usually: No. Ask the server owner if you don't know.",
    "¿Conexión segura (FTPS explícito)?": "Secure connection (explicit FTPS)?",
    "Elige «Sí» si tu servidor lo permite; es más seguro. Si no lo sabes, elige «No».": "Choose “Yes” if your server supports it; it is safer. If you don't know, choose “No”.",
    "¿Subidas rápidas?": "Fast uploads?",
    "Recomendado: activado.": "Recommended: on.",
    "Biblioteca": "Library",
    "Nombre de la biblioteca de Seafile. Déjalo vacío para ver todas.": "Seafile library name. Leave it empty to see all of them.",
    "Contraseña de la biblioteca": "Library password",
    "Solo si esa biblioteca está cifrada. Si no, déjalo vacío.": "Only if that library is encrypted. Otherwise, leave it empty.",
    "Contraseña del buzón": "Mailbox password",
    "Solo si en Proton usas dos contraseñas. Si no, déjalo vacío.": "Only if you use two passwords in Proton. Otherwise, leave it empty.",
    "¿Tu cuenta usa verificación en dos pasos?": "Does your account use two-step verification?",
    "Elige «Sí» si al entrar te piden un código además de la contraseña.": "Choose “Yes” if you are asked for a code as well as your password when you sign in.",
    "Tu contraseña de Apple": "Your Apple password",
    "La misma que usas en tu iPhone para la App Store o iCloud. Se guarda cifrada en este ordenador.": "The same one you use on your iPhone for the App Store or iCloud. It is stored encrypted on this computer.",
    "¿Activar la opción «{opcion}»?": "Turn on the “{opcion}” option?",
    "Dato solicitado: «{opcion}»": "Requested setting: “{opcion}”",
    "Si no sabes qué poner, <b>deja lo que viene escrito y pulsa «Siguiente»</b>. Casi siempre es lo correcto.": "If you don't know what to enter, <b>leave what is already there and press “Next”</b>. It is almost always right.",
    "<br><br><span style='color:%s'>Este dato es opcional.</span>": "<br><br><span style='color:%s'>This setting is optional.</span>",
    "Una ventana de inicio de sesión de un intento anterior seguía abierta. Cierra las pestañas de inicio de sesión del navegador y vuelve a intentarlo.": "A sign-in window from a previous attempt was still open. Close the sign-in tabs in your browser and try again.",
    "Apple necesita tu permiso. Mira tu iPhone y acepta el aviso que aparece. Comprueba también que en Ajustes › (tu nombre) › iCloud está ACTIVADO «Acceder a los datos de iCloud en la web».": "Apple needs your permission. Look at your iPhone and accept the notice that appears. Also check that in Settings › (your name) › iCloud, “Access iCloud Data on the Web” is ON.",
    "Apple pide que vuelvas a iniciar sesión (lo hace cada 30 días). Pulsa ⋯ y elige «Volver a iniciar sesión».": "Apple asks you to sign in again (it does so every 30 days). Press ⋯ and choose “Sign in again”.",
    "El código de verificación no es correcto o ha caducado. Inténtalo de nuevo con un código nuevo.": "The verification code is wrong or has expired. Try again with a new code.",
    "No se dio permiso en el navegador. Vuelve a intentarlo y pulsa «Permitir» o «Aceptar».": "Permission was not given in the browser. Try again and press “Allow” or “Accept”.",
    "El permiso ha caducado. Desconecta esta nube y vuelve a añadirla.": "The permission has expired. Disconnect this cloud and add it again.",
    "El usuario o la contraseña no son correctos. Revísalos e inténtalo de nuevo.": "The username or password is wrong. Check them and try again.",
    "El servicio no ha dado permiso para entrar. Revisa que tu cuenta tenga acceso.": "The service did not allow access. Check that your account has access.",
    "El certificado de seguridad del servidor no es válido. Avisa al dueño del servidor.": "The server's security certificate is not valid. Let the server owner know.",
    "No se pudo llegar al servidor. Comprueba tu conexión a internet y que la dirección esté bien escrita.": "Could not reach the server. Check your internet connection and that the address is spelled correctly.",
    "El servicio tardó demasiado en responder. Comprueba tu internet e inténtalo de nuevo.": "The service took too long to respond. Check your internet and try again.",
    "No se encontró la carpeta o la dirección indicada. Revisa que esté bien escrita.": "The folder or address was not found. Check that it is spelled correctly.",
    "Has cancelado la operación.": "You cancelled the operation.",
    "El correo o la contraseña de Apple no son correctos. Revísalos e inténtalo de nuevo.": "The Apple email or password is wrong. Check them and try again.",
    "No se pudo conectar. Comprueba tu conexión a internet e inténtalo de nuevo.": "Could not connect. Check your internet connection and try again.",
    "Ha ocurrido un problema al conectar. Revisa los datos e inténtalo de nuevo.": "There was a problem connecting. Check your details and try again.",
    "Error desconocido.": "Unknown error.",
    "Error inesperado: {error}": "Unexpected error: {error}",
    "Se agotó el tiempo de espera.": "The wait timed out.",
    "Respuesta inesperada de rclone.": "Unexpected response from rclone.",
    "El servicio tardó demasiado en responder.": "The service took too long to respond.",
    "Carpeta lista.": "Folder ready.",
    "No se pudo abrir la carpeta. Comprueba tu conexión a internet.": "Could not open the folder. Check your internet connection.",
    "No se pudo abrir la carpeta. Comprueba tu internet. Si sigue sin funcionar, pulsa el botón ⋯ y elige «Volver a iniciar sesión»: Apple lo pide cada 30 días.": "Could not open the folder. Check your internet. If it still doesn't work, press the ⋯ button and choose “Sign in again”: Apple asks for it every 30 days.",
    "Desconectado. Tus archivos en la nube no se han tocado.": "Disconnected. Your files in the cloud were not touched.",
    "Nombre cambiado, pero no se pudo abrir la carpeta.": "Name changed, but the folder could not be opened.",
    "Ahora se llama «{nombre}».": "It is now called “{nombre}”.",
    "Tu correo y contraseña de Google (los mismos de Gmail).": "Your Google email and password (the same as for Gmail).",
    "Tu correo y contraseña de Microsoft (Outlook, Hotmail, Office o el del trabajo).": "Your Microsoft email and password (Outlook, Hotmail, Office or your work account).",
    "Tu correo y contraseña de Dropbox.": "Your Dropbox email and password.",
    "Tu correo y contraseña de Apple (con los que entras en tu iPhone).": "Your Apple email and password (the ones you use on your iPhone).",
    "Tu iPhone, iPad o Mac a mano: te llegará un código de 6 números.": "Your iPhone, iPad or Mac nearby: you will get a 6-digit code.",
    "En el iPhone, abre <b>Ajustes › (tu nombre) › iCloud</b> y comprueba que «Acceder a los datos de iCloud en la web» está <b>activado</b>.": "On your iPhone, open <b>Settings › (your name) › iCloud</b> and check that “Access iCloud Data on the Web” is <b>on</b>.",
    "Por seguridad, <b>Apple pide volver a iniciar sesión cada 30 días</b>. Cuando pase, verás un aviso en la tarjeta y lo harás en un minuto.": "For security, <b>Apple asks you to sign in again every 30 days</b>. When that happens, you will see a notice on the card and it takes a minute.",
    "Por seguridad, <b>Apple pide volver a iniciar sesión cada 30 días</b>.": "For security, <b>Apple asks you to sign in again every 30 days</b>.",
    "Tu correo y contraseña de MEGA.": "Your MEGA email and password.",
    "Tu correo y contraseña de Proton.": "Your Proton email and password.",
    "Si usas verificación en dos pasos, tu app de códigos a mano.": "If you use two-step verification, your code app nearby.",
    "La <b>dirección de tu servidor</b>. En Nextcloud la encuentras así: entra en tu Nextcloud desde el navegador › «Archivos» › abajo a la izquierda «Ajustes de archivos» › copia la dirección que aparece en «WebDAV».": "Your <b>server address</b>. In Nextcloud you find it like this: open your Nextcloud in the browser › “Files” › bottom left “Files settings” › copy the address shown under “WebDAV”.",
    "Tu usuario y contraseña. Si tu cuenta tiene verificación en dos pasos, crea una «contraseña de aplicación» en Ajustes › Seguridad y usa esa.": "Your username and password. If your account has two-step verification, create an “app password” in Settings › Security and use that.",
    "El <b>nombre o la dirección IP</b> del ordenador que comparte la carpeta (por ejemplo 192.168.1.10). En Windows lo ves en Configuración › Sistema › Información.": "The <b>name or IP address</b> of the computer sharing the folder (for example 192.168.1.10). On Windows you can see it in Settings › System › About.",
    "El usuario y la contraseña de ese ordenador.": "The username and password of that computer.",
    "La dirección del servidor (nombre o IP).": "The server address (name or IP).",
    "Tu usuario y contraseña del servidor.": "Your username and password for the server.",
    "El nombre de tu proveedor (Amazon, Cloudflare R2, Wasabi…).": "The name of your provider (Amazon, Cloudflare R2, Wasabi…).",
    "Tus claves «Access Key» y «Secret Key». Se crean en el panel web de tu proveedor.": "Your “Access Key” and “Secret Key”. They are created in your provider's web dashboard.",
    "Tu «keyID» y tu «applicationKey». Están en la web de Backblaze › «App Keys» › «Add a New Application Key».": "Your “keyID” and “applicationKey”. They are on the Backblaze website › “App Keys” › “Add a New Application Key”.",
    "Si te pide algún dato que no conoces, deja lo que venga escrito: casi siempre es lo correcto.": "If it asks for something you don't know, leave what is already there: it is almost always right.",
    "Tu usuario y contraseña de {servicio}.": "Your {servicio} username and password.",
    "Tu correo y contraseña de {servicio}.": "Your {servicio} email and password.",
    "Esta información sirve para quien te ayude a resolver el problema:": "This information is for whoever helps you solve the problem:",
    "Guardar": "Save",
    "Cancelar": "Cancel",
    "Entendido": "OK",
    "Ver detalles técnicos": "Show technical details",
    "Detalles técnicos": "Technical details",
    "Añadir nube": "Add cloud",
    "Modo experto": "Expert mode",
    "Muestra también las preguntas técnicas. No hace falta para casi nadie.": "Also shows the technical questions. Almost nobody needs this.",
    "Abrir la carpeta": "Open folder",
    "Continuar": "Continue",
    "Empezar": "Start",
    "Siguiente": "Next",
    "¿Qué nube quieres añadir?": "Which cloud do you want to add?",
    "Haz clic en una. Si no la ves, escríbela en el buscador.": "Click one. If you don't see it, type it in the search box.",
    "Buscar un servicio…  (por ejemplo: dropbox, nextcloud, mega)": "Search for a service…  (for example: dropbox, nextcloud, mega)",
    "Ver todos los servicios": "See all services",
    "Ver los {n} servicios disponibles": "See all {n} available services",
    "Ver solo los más usados": "See only the most popular",
    "<b>Ponle un nombre</b>": "<b>Give it a name</b>",
    "Por ejemplo: Drive del trabajo, Fotos de casa…": "For example: Work Drive, Home Photos…",
    "<b>Antes de empezar, ten a mano:</b>": "<b>Before you start, have ready:</b>",
    "Se creará la carpeta:  Carpeta personal › {base} › <b>{nombre}</b>": "This folder will be created:  Home › {base} › <b>{nombre}</b>",
    "Tus fotos aparecerán como una carpeta, ordenadas por álbumes. <b>Se ven en línea: no se copian a tu ordenador</b> (solo se guardan un rato las que abres, para que vayan rápido).<br>Es de <b>solo lectura</b>: puedes ver y copiar fotos, pero no borrar ni subir desde aquí. Para eso, usa tu iPhone.": "Your photos will appear as a folder, organized by albums. <b>They are viewed online: they are not copied to your computer</b> (only the ones you open are kept for a while, so they load fast).<br>It is <b>read only</b>: you can view and copy photos, but not delete or upload from here. Use your iPhone for that.",
    "Tus archivos aparecerán como una carpeta normal de tu ordenador.": "Your files will appear as a regular folder on your computer.",
    "Mostrar lo que escribo": "Show what I type",
    "Ver la explicación técnica del servicio (en inglés)": "See the service's technical explanation",
    "Sigue estos pasos. Esta ventana continuará sola cuando termines.": "Follow these steps. This window will continue on its own when you finish.",
    "<b>¿No se abrió ninguna página en tu navegador?</b>  Pulsa este botón:": "<b>No page opened in your browser?</b>  Press this button:",
    "Preparando el enlace…": "Preparing the link…",
    "Copiar enlace": "Copy link",
    "Esperando a que termines en el navegador…": "Waiting for you to finish in the browser…",
    "Inicia sesión en {servicio}": "Sign in to {servicio}",
    "Mira tu navegador (Firefox, Chrome…): se ha abierto una página de <b>{servicio}</b>. Si no la ves, búscala en la barra de tareas, abajo.": "Look at your browser (Firefox, Chrome…): a <b>{servicio}</b> page has opened. If you don't see it, look for it in the taskbar at the bottom.",
    "Elige tu cuenta, o escribe tu correo y tu contraseña.": "Choose your account, or type your email and password.",
    "Te preguntará si das permiso a <b>«rclone»</b> (es el programa que conecta tu nube; es seguro). Pulsa <b>«Permitir»</b> o <b>«Aceptar»</b>.": "It will ask if you give permission to <b>“rclone”</b> (the program that connects your cloud; it is safe). Press <b>“Allow”</b> or <b>“Accept”</b>.",
    "Cuando veas la palabra <b>«Success!»</b> (significa «¡Listo!»), cierra esa pestaña y vuelve a esta ventana.": "When you see the word <b>“Success!”</b>, close that tab and come back to this window.",
    "Abrir la página de inicio de sesión": "Open the sign-in page",
    "✓ Copiado. Ahora abre tu navegador, haz clic en la barra de direcciones (arriba), pega con Ctrl+V y pulsa Intro.": "✓ Copied. Now open your browser, click the address bar (at the top), paste with Ctrl+V and press Enter.",
    "Preparando…": "Preparing…",
    "Un momento.": "Just a moment.",
    "Comprobando…": "Checking…",
    "Comprobando la conexión…": "Checking the connection…",
    "Estamos mirando que todo funcione. Un momento.": "We are checking that everything works. Just a moment.",
    "Preparando iCloud Fotos…": "Preparing iCloud Photos…",
    "Descargando una versión más nueva de rclone (unos 25 MB). Solo pasa una vez.": "Downloading a newer version of rclone (about 25 MB). This only happens once.",
    "Abriendo la carpeta…": "Opening the folder…",
    "Primero haz clic en el servicio que quieres añadir.": "First click the service you want to add.",
    "Escribe un nombre para esta nube, por ejemplo «Mis fotos».": "Type a name for this cloud, for example “My photos”.",
    "Ya tienes una nube con ese nombre. Escribe otro distinto.": "You already have a cloud with that name. Type a different one.",
    "Este dato es obligatorio. Escríbelo para poder continuar.": "This setting is required. Type it to continue.",
    "No se pudo preparar iCloud Fotos": "Could not prepare iCloud Photos",
    "No se pudo descargar lo necesario. Comprueba tu internet e inténtalo de nuevo.": "Could not download what is needed. Check your internet and try again.",
    "No se pudo conectar": "Could not connect",
    "Intentar de nuevo": "Try again",
    "Detalle técnico (para quien te ayude): {detalle}": "Technical detail (for whoever helps you): {detalle}",
    "Los datos se guardaron, pero no pudimos comprobar que funcionen:\n\n{explicacion}\n\n¿Quieres guardarla de todas formas?": "Your details were saved, but we could not check that they work:\n\n{explicacion}\n\nDo you want to keep it anyway?",
    "Guardar igualmente": "Keep anyway",
    "No guardar": "Don't keep",
    "No se añadió": "Not added",
    "Puedes intentarlo de nuevo cuando quieras.": "You can try again whenever you want.",
    "Casi listo": "Almost done",
    "Tu cuenta quedó guardada, pero no se pudo abrir la carpeta. Cierra esta ventana y pulsa «Reintentar» en la tarjeta de esta nube.": "Your account was saved, but the folder could not be opened. Close this window and press “Retry” on this cloud's card.",
    "¡Sesión iniciada!": "Signed in!",
    "«{nombre}» vuelve a funcionar. Dentro de 30 días Apple te lo volverá a pedir.": "“{nombre}” works again. Apple will ask again in 30 days.",
    "¡iCloud Fotos está listo!": "iCloud Photos is ready!",
    "Tus fotos están en la carpeta <b>{base} › {carpeta}</b>, ordenadas por álbumes (todas juntas están en «All Photos»).<br><br>La primera vez puede tardar unos minutos en mostrar todas las fotos si tienes muchas. Las siguientes veces irá rápido.": "Your photos are in the <b>{base} › {carpeta}</b> folder, organized by albums (all of them together are in “All Photos”).<br><br>The first time it may take a few minutes to show all your photos if you have many. After that it will be fast.",
    "¡«{nombre}» está lista!": "“{nombre}” is ready!",
    "Tus archivos ya aparecen en la carpeta <b>{base} › {carpeta}</b>.<br>Se abrirá sola cada vez que enciendas el ordenador.<br><br>Consejo: también la tienes en el panel izquierdo del explorador de archivos, en «Mis nubes».": "Your files now appear in the <b>{base} › {carpeta}</b> folder.<br>It will open on its own every time you turn on your computer.<br><br>Tip: you also have it in the left panel of the file manager, under “My Clouds”.",
    "Volver a iniciar sesión": "Sign in again",
    "Acerca de Mis nubes": "About My Clouds",
    "Versión {v}": "Version {v}",
    "Tus nubes como carpetas normales en Linux: Google Drive, OneDrive, iCloud, Dropbox, MEGA y muchas más.": "Your clouds as regular folders on Linux: Google Drive, OneDrive, iCloud, Dropbox, MEGA and many more.",
    "Funciona gracias a <b>rclone</b> (rclone.org), un programa libre. Iconos de los servicios: tema libre <b>Papirus</b>.": "Powered by <b>rclone</b> (rclone.org), a free program. Service icons: the free <b>Papirus</b> theme.",
    "Idioma:": "Language:",
    "Automático (el del sistema)": "Automatic (system language)",
    "Cerrar": "Close",
    "El idioma cambiará al volver a abrir Mis nubes. ¿Reiniciar ahora?": "The language will change when My Clouds is reopened. Restart now?",
    "Reiniciar ahora": "Restart now",
    "Más tarde": "Later",
    "Más opciones": "More options",
    "Volver a iniciar sesión…": "Sign in again…",
    "Cambiar nombre…": "Rename…",
    "Desconectar…": "Disconnect…",
    "Conectada": "Connected",
    "Sin conexión": "Offline",
    "No aparece como carpeta": "Not shown as a folder",
    "Abrir": "Open",
    "Reintentar": "Retry",
    "Mostrar carpeta": "Show folder",
    "solo lectura": "read only",
    "{usado} usados de {total}": "{usado} used of {total}",
    "{usado} usados": "{usado} used",
    "Tus archivos ocupan {usado} en iCloud Drive": "Your files take up {usado} in iCloud Drive",
    "Apple no permite consultar el total de tu plan desde aquí. Las fotos no se cuentan: ocupan aparte.": "Apple doesn't allow checking your plan's total from here. Photos are not counted: they take up space separately.",
    "Tus nubes, como carpetas normales de tu ordenador.": "Your clouds, as regular folders on your computer.",
    "＋  Añadir nube": "＋  Add cloud",
    "Todavía no tienes ninguna nube": "You don't have any clouds yet",
    "Añade Google Drive, OneDrive, iCloud, Dropbox y muchas más.\nAparecerán como carpetas y se abrirán solas al encender el ordenador.": "Add Google Drive, OneDrive, iCloud, Dropbox and many more.\nThey will appear as folders and open on their own when you turn on your computer.",
    "Añadir mi primera nube": "Add my first cloud",
    "Abrir carpeta {base}": "Open {base} folder",
    "Nube añadida.": "Cloud added.",
    "Conectando…": "Connecting…",
    "Cambiar nombre": "Rename",
    "Escribe el nuevo nombre (su carpeta también cambiará de nombre):": "Type the new name (its folder will be renamed too):",
    "Cambiando el nombre…": "Renaming…",
    "Desconectar": "Disconnect",
    "Desconectando…": "Disconnecting…",
    "¿Desconectar «{nombre}»?\n\nTranquilo: tus archivos en la nube NO se borran. Solo deja de aparecer la carpeta en este ordenador.": "Disconnect “{nombre}”?\n\nDon't worry: your files in the cloud are NOT deleted. The folder just stops appearing on this computer.",
    "Todavía se está haciendo algo. ¿Cerrar de todas formas?": "Something is still in progress. Close anyway?",
    "Faltan algunos programas necesarios. Cierra esta ventana y vuelve a abrir el archivo «Mis nubes» para instalarlos.": "Some required programs are missing. Close this window and open the “Mis nubes” file again to install them.",
    "Novedad: iCloud Fotos ahora funciona en línea, sin copiar las fotos a tu ordenador. Para usarlo, pulsa «Añadir nube» y elige «iCloud Fotos».\n\nLas fotos que ya se habían copiado siguen en la carpeta «{carpetas}». Si no las necesitas, puedes borrar esa carpeta para liberar espacio.": "New: iCloud Photos now works online, without copying photos to your computer. To use it, press “Add cloud” and choose “iCloud Photos”.\n\nThe photos that were already copied are still in the “{carpetas}” folder. If you don't need them, you can delete that folder to free up space.",
    "Tus nubes como carpetas normales": "Your clouds as regular folders"
}


def exportar_idioma(codigo):
    """Imprime un catálogo para traducir: python3 mis_nubes.py --exportar-idioma fr > fr.json"""
    base = TRADUCCIONES.get("en", {})
    existente = catalogo(codigo) or {}
    plantilla = {"_idioma": nombre_idioma(codigo),
                 "_instrucciones": "Traduce cada valor. Las claves (a la izquierda) están en "
                                   "español y no se tocan. Respeta {variables} y etiquetas <b>.",
                 **{k: existente.get(k, "" if codigo != "en" else v)
                    for k, v in base.items() if not k.startswith("_")}}
    print(json.dumps(plantilla, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--exportar-idioma":
        exportar_idioma(sys.argv[2])
        sys.exit(0)
    sys.exit(main())
