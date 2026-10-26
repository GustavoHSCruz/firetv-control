"""Fixed ADB operations, shared by the CLI and the local control panel.

Follows CLI-Anything's backend adapter pattern. Like REA's AdbCommand.ts,
quotes arguments at the remote shell boundary (ADB joins shell operands).
No host shell, arbitrary shell endpoint, root or system-package disabling.
"""

from __future__ import annotations

import base64
import ipaddress
import json
import os
from pathlib import Path
import posixpath
import re
import shlex
import shutil
import subprocess
import tempfile
import threading


class FireTVError(RuntimeError):
    pass


KEYS = {
    "up": 19, "down": 20, "left": 21, "right": 22, "ok": 23,
    "back": 4, "home": 3, "menu": 82, "play": 85,
    "rewind": 89, "forward": 90, "volume_up": 24, "volume_down": 25,
    "mute": 164, "delete": 67,
}


def find_adb() -> str:
    override = os.environ.get("FIRETV_ADB")
    local = Path(__file__).resolve().parents[1] / ".tools" / "platform-tools"
    candidates = [override] if override else [
        shutil.which("adb"), str(local / ("adb.exe" if os.name == "nt" else "adb")),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise FireTVError(
        "ADB não encontrado. Execute python3 run.py setup, instale Android SDK "
        "Platform-Tools ou defina FIRETV_ADB com o caminho do adb."
    )


def validate_serial(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:\[\]-]{1,200}", value) or value.startswith("-"):
        raise FireTVError("Identificador ADB inválido.")
    return value


def endpoint(address: str) -> str:
    if not isinstance(address, str):
        raise FireTVError("Informe o IPv4 do Fire TV, por exemplo 192.168.1.50.")
    host, sep, port = address.strip().partition(":")
    try:
        ip = ipaddress.IPv4Address(host)
        number = int(port) if sep else 5555
        if not 1 <= number <= 65535 or ip.is_unspecified or ip.is_multicast:
            raise ValueError()
    except ValueError as exc:
        raise FireTVError("IP ou porta inválidos. Exemplo: 192.168.1.50:5555.") from exc
    return f"{ip}:{number}"


def package_name(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+", value):
        raise FireTVError("Nome de pacote inválido. Exemplo: org.videolan.vlc.")
    return value


def components(output: str) -> list[str]:
    # query-activities indents component lines; resolve-activity usually does not.
    return [line.strip() for line in output.splitlines()
            if re.fullmatch(r"[A-Za-z0-9_.$]+/[A-Za-z0-9_.$]+", line.strip())]


def shared_path(value: str) -> str:
    if not isinstance(value, str) or any(ord(c) < 32 for c in value):
        raise FireTVError("Caminho inválido.")
    path = posixpath.normpath(value)
    if not any(path == root or path.startswith(root + "/") for root in ("/sdcard", "/storage/emulated/0")):
        raise FireTVError("Use o armazenamento compartilhado: /sdcard ou /storage/emulated/0.")
    return path


class FireTV:
    def __init__(self, serial: str | None = None, adb: str | None = None, config: Path | None = None):
        self.adb = adb
        self.config = config or Path(os.environ.get(
            "FIRETV_CONFIG", str(Path.home() / ".config" / "firetv-control" / "device.json")
        ))
        self.lock = threading.RLock()
        if serial:
            self.serial = validate_serial(serial)
        else:
            try:
                saved = json.loads(self.config.read_text(encoding="utf-8"))
                self.serial = validate_serial(saved["serial"])
            except (OSError, ValueError, KeyError, TypeError, FireTVError):
                self.serial = None

    def run(self, *args: str, device: bool = True, timeout: int = 30, binary: bool = False):
        with self.lock:
            command = [self.adb or find_adb()]
            if device:
                if not self.serial:
                    raise FireTVError("Conecte o Fire TV pelo IP ou selecione um dispositivo primeiro.")
                command += ["-s", validate_serial(self.serial)]
            command += list(args)
            try:
                result = subprocess.run(command, capture_output=True, timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                raise FireTVError(
                    f"O Fire TV não respondeu em {timeout}s. Verifique a rede e a autorização na TV. "
                    "A operação pode ter sido concluída; confira antes de tentar novamente."
                ) from exc
            except OSError as exc:
                raise FireTVError(f"Não foi possível executar o ADB: {exc}") from exc
            message = (result.stdout + result.stderr).decode("utf-8", errors="replace").strip()
            if result.returncode or (not binary and (
                "Failure [" in message or re.search(r"(?im)^(?:error:|error type |exception occurred|securityexception:|java\.lang\.securityexception:)", message)
            )):
                if "unauthorized" in message.lower():
                    message = "Autorize este PC no aviso de depuração exibido no Fire TV."
                elif "offline" in message.lower():
                    message = "Dispositivo offline. Verifique o Fire TV e conecte novamente."
                raise FireTVError(message or "O ADB não concluiu a operação.")
            return result.stdout if binary else result.stdout.decode("utf-8", errors="replace").strip()

    def shell(self, *args: str, **kwargs):
        return self.run("shell", shlex.join(args), **kwargs)

    def remember(self):
        self.config.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=self.config.parent, prefix=".device-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"serial": self.serial}, handle)
            os.replace(name, self.config)
        finally:
            Path(name).unlink(missing_ok=True)

    def doctor(self):
        try:
            version = self.run("version", device=False)
            return {"ready": True, "adb": self.adb or find_adb(), "version": version, "selected": self.serial}
        except FireTVError as exc:
            return {"ready": False, "error": str(exc), "selected": self.serial}

    def devices(self):
        rows = []
        for line in self.run("devices", "-l", device=False).splitlines():
            fields = line.split()
            if len(fields) < 2 or fields[0] == "List" or line.startswith("*"):
                continue
            metadata = dict(p.split(":", 1) for p in fields[2:] if ":" in p)
            rows.append({"serial": fields[0], "state": fields[1], **metadata})
        return rows

    def select(self, serial: str):
        with self.lock:
            serial = validate_serial(serial)
            device = next((d for d in self.devices() if d["serial"] == serial), None)
            if not device or device["state"] != "device":
                state = device["state"] if device else "não encontrado"
                raise FireTVError(f"Dispositivo {state}. Autorize a depuração na TV e tente novamente.")
            previous = self.serial
            self.serial = serial
            try:
                self.run("get-state")
                self.remember()
            except Exception:
                self.serial = previous
                raise
            return {"serial": serial, "message": "Fire TV conectado."}

    def connect(self, address: str):
        with self.lock:
            target = endpoint(address)
            message = self.run("connect", target, device=False)
            if re.search(r"failed|cannot|unable|refused", message, re.I):
                if "refused" in message.lower():
                    raise FireTVError(
                        f"{target} recusou a conexão. Ative Depuração ADB em Meu Fire TV → "
                        "Opções do desenvolvedor e confirme o IP em Sobre → Rede."
                    )
                raise FireTVError(message)
            return self.select(target)

    def disconnect(self):
        with self.lock:
            if not self.serial:
                return {"message": "Nenhum dispositivo selecionado."}
            if ":" in self.serial:
                self.run("disconnect", self.serial, device=False)
            self.serial = None
            self.remember()
            return {"message": "Desconectado."}

    def info(self):
        props = dict(re.findall(r"^\[([^\]]+)\]: \[([^\]]*)\]$", self.shell("getprop"), re.M))
        return {
            "serial": self.serial, "model": props.get("ro.product.model", "Desconhecido"),
            "manufacturer": props.get("ro.product.manufacturer", ""),
            "android": props.get("ro.build.version.release", ""),
            "sdk": props.get("ro.build.version.sdk", ""),
            "software": props.get("ro.build.version.name") or props.get("ro.build.display.id", ""),
            "fire_os": props.get("ro.build.version.fireos", ""),
            "storage": self.shell("df", "-h", "/sdcard"),
        }

    def apps(self, all_apps=False):
        args = ("pm", "list", "packages") + (() if all_apps else ("-3",))
        packages = sorted(line[8:] for line in self.shell(*args).splitlines() if line.startswith("package:"))
        return [{"package": p} for p in packages]

    def install(self, local: str):
        path = Path(local).expanduser().resolve()
        if not path.is_file() or path.suffix.lower() != ".apk":
            raise FireTVError("Selecione um arquivo .apk existente. XAPK/APKM e pacotes Vega não são APKs.")
        output = self.run("install", "-r", str(path), timeout=300)
        if "Success" not in output:
            raise FireTVError(output or "O ADB não confirmou a instalação.")
        return {"message": "APK instalado.", "output": output}

    def uninstall(self, package: str, confirmed=False):
        package = package_name(package)
        if not confirmed:
            raise FireTVError("Confirme a desinstalação: ela apaga os dados locais do aplicativo.")
        if package not in {p["package"] for p in self.apps()}:
            raise FireTVError("Apenas apps de terceiros podem ser desinstalados por esta ferramenta.")
        output = self.run("uninstall", package, timeout=120)
        if "Success" not in output:
            raise FireTVError(output or "O ADB não confirmou a desinstalação.")
        return {"message": f"{package} desinstalado.", "output": output}

    def launch(self, package: str):
        package = package_name(package)
        for category in ("LEANBACK_LAUNCHER", "LAUNCHER", "HOME"):
            intent = ("-a", "android.intent.action.MAIN", "-c", f"android.intent.category.{category}", "-p", package)
            try:
                resolved = self.shell("cmd", "package", "resolve-activity", "--brief", *intent)
            except FireTVError as exc:
                if "not found" not in str(exc) and "Unknown command" not in str(exc):
                    raise
                break  # Old Fire OS builds do not expose cmd package.
            matches = components(resolved)
            if matches:
                output = self.shell("am", "start", "-n", matches[-1])
                return {"message": f"Abrindo {package}.", "output": output}
        # One launch event; no random input events are generated.
        output = self.shell("monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1")
        if "Events injected: 1" not in output:
            raise FireTVError("O app não tem uma atividade de abertura acessível. Verifique se está habilitado.")
        return {"message": f"Abrindo {package}.", "output": output}

    def key(self, key: str):
        if key not in KEYS:
            raise FireTVError("Botão de controle inválido.")
        self.shell("input", "keyevent", str(KEYS[key]))
        return {"message": f"Comando enviado: {key}."}

    def text(self, text: str):
        if not isinstance(text, str) or not text or len(text) > 500 or any(ord(c) < 32 or ord(c) > 126 for c in text) or "%" in text:
            raise FireTVError("Digite de 1 a 500 caracteres sem acentos, quebras de linha ou %. Limitação do input text do Android.")
        self.shell("input", "text", text.replace(" ", "%s"))
        return {"message": "Texto enviado ao campo em foco na TV."}

    def files(self, remote="/sdcard"):
        remote = shared_path(remote)
        script = '''test -d "$1" && test -r "$1" || exit 1
for p in "$1"/* "$1"/.[!.]* "$1"/..?*; do
  test -e "$p" || test -L "$p" || continue
  if test -L "$p"; then kind=link; elif test -d "$p"; then kind=directory; else kind=file; fi
  printf '%s\\000%s\\000' "$kind" "${p##*/}"
done'''
        raw = self.shell("sh", "-c", script, "firetv-list", remote, binary=True)
        fields = raw.split(b"\0")
        if fields[-1] != b"" or (len(fields) - 1) % 2:
            raise FireTVError("Resposta de diretório inválida.")
        entries = []
        for index in range(0, len(fields) - 1, 2):
            kind, name = fields[index].decode(), fields[index + 1].decode("utf-8", errors="replace")
            entries.append({"name": name, "kind": kind, "path": posixpath.join(remote, name)})
        return {"path": remote, "entries": sorted(entries, key=lambda e: (e["kind"] != "directory", e["name"].lower()))}

    def push(self, local: str, remote: str, overwrite=False):
        path = Path(local).expanduser().resolve()
        remote = shared_path(remote)
        if not path.is_file():
            raise FireTVError("O arquivo local não existe.")
        if not overwrite:
            exists = self.shell("sh", "-c", 'if test -e "$1" || test -L "$1"; then printf exists; fi', "firetv-exists", remote)
            if exists:
                raise FireTVError("O destino já existe. Escolha outro nome ou autorize a substituição.")
        output = self.run("push", str(path), remote, timeout=300)
        return {"message": "Arquivo enviado.", "path": remote, "output": output}

    def pull(self, remote: str, local: str):
        remote = shared_path(remote)
        local = Path(local).expanduser().resolve()
        if local.exists():
            raise FireTVError("O destino local já existe. Escolha um novo caminho para evitar sobrescrita.")
        local.parent.mkdir(parents=True, exist_ok=True)
        output = self.run("pull", remote, str(local), timeout=300)
        return {"message": "Dados copiados para o PC.", "path": str(local), "output": output}

    def screenshot(self):
        png = self.run("exec-out", "screencap", "-p", binary=True, timeout=30)
        if not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise FireTVError("O dispositivo não retornou uma captura PNG válida.")
        return png

    def home(self):
        output = self.shell("cmd", "package", "query-activities", "--brief", "-a", "android.intent.action.MAIN", "-c", "android.intent.category.HOME")
        matches = sorted(set(components(output)))
        current = self.shell("cmd", "package", "resolve-activity", "--brief", "-a", "android.intent.action.MAIN", "-c", "android.intent.category.HOME")
        current_matches = components(current)
        return {"current": current_matches[-1] if current_matches else current,
                "launchers": [{"component": c, "package": c.split("/")[0],
                               "helper": c.startswith("com.amazon.firehomestarter/") or c.endswith(".FallbackHome")}
                              for c in matches],
                "message": "Você pode instalar e abrir um launcher alternativo. A substituição do botão Home depende do modelo e do firmware."}

    def open_launcher(self, component: str):
        candidates = self.home()["launchers"]
        candidate = next((item for item in candidates if item["component"] == component), None)
        if not candidate or candidate["helper"]:
            raise FireTVError("Selecione um launcher instalado. Componentes auxiliares do sistema não podem ser abertos aqui.")
        output = self.shell("am", "start", "-n", candidate["component"])
        return {"message": "Launcher aberto na TV.", "output": output}

    def dispatch(self, action: str, data: dict):
        # Serialize whole workflows: switching devices cannot redirect an in-flight operation.
        with self.lock:
            operations = {
                "doctor": lambda: self.doctor(), "devices": lambda: self.devices(),
                "connect": lambda: self.connect(data.get("address", "")),
                "select": lambda: self.select(data.get("serial", "")),
                "disconnect": lambda: self.disconnect(), "info": lambda: self.info(),
                "apps": lambda: self.apps(data.get("all", False)),
                "launch": lambda: self.launch(data.get("package", "")),
                "uninstall": lambda: self.uninstall(data.get("package", ""), data.get("confirmed") is True),
                "key": lambda: self.key(data.get("key", "")),
                "text": lambda: self.text(data.get("text", "")),
                "files": lambda: self.files(data.get("path", "/sdcard")),
                "home": lambda: self.home(),
                "open_launcher": lambda: self.open_launcher(data.get("component", "")),
                "screenshot": lambda: {"image": "data:image/png;base64," + base64.b64encode(self.screenshot()).decode()},
            }
            if action not in operations:
                raise FireTVError("Operação desconhecida.")
            return operations[action]()
