"""Low-latency native video window using the official scrcpy client."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

from .backend import FireTVError, find_adb, validate_serial

VERSION = "5.0.1"
LINUX_SHA256 = "9f969d30cc574816077edecda65719c1c70b0aee1df1ba5fa00779ac07b8fd6e"
TOOLS = Path(__file__).resolve().parents[1] / ".tools"


def find_scrcpy() -> str:
    override = os.environ.get("FIRETV_SCRCPY")
    local = TOOLS / f"scrcpy-linux-x86_64-v{VERSION}" / "scrcpy"
    candidates = [override] if override else [shutil.which("scrcpy"), str(local)]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise FireTVError(
        "scrcpy não encontrado. Execute python3 run.py setup-mirror, "
        "instale scrcpy no PC ou defina FIRETV_SCRCPY com o caminho do executável."
    )


def install_scrcpy():
    """Install a pinned official Linux bundle and verify its published SHA-256."""
    try:
        existing = find_scrcpy()
    except FireTVError:
        existing = None
    if existing:
        print(f"scrcpy disponível: {existing}")
        return
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "AMD64"):
        raise FireTVError(
            "Instale scrcpy pela fonte oficial: https://github.com/Genymobile/scrcpy . "
            "No Windows: winget install --exact Genymobile.scrcpy . No macOS: brew install scrcpy ."
        )
    name = f"scrcpy-linux-x86_64-v{VERSION}"
    url = f"https://github.com/Genymobile/scrcpy/releases/download/v{VERSION}/{name}.tar.gz"
    TOOLS.mkdir(exist_ok=True)
    print(f"Baixando scrcpy oficial {VERSION}:\n{url}", flush=True)
    with tempfile.TemporaryDirectory(prefix="firetv-scrcpy-", dir=TOOLS) as directory:
        archive = Path(directory) / "scrcpy.tar.gz"
        digest = hashlib.sha256()
        with urllib.request.urlopen(url, timeout=60) as response, archive.open("wb") as handle:
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                handle.write(chunk)
        if digest.hexdigest() != LINUX_SHA256:
            raise FireTVError("O SHA-256 do scrcpy não corresponde ao publicado. Download descartado.")
        stage = Path(directory) / "extract"
        with tarfile.open(archive, "r:gz") as package:
            for member in package.getmembers():
                path = Path(member.name)
                if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != name or not (member.isfile() or member.isdir()):
                    raise FireTVError("Estrutura inesperada no pacote scrcpy.")
            package.extractall(stage, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))
        unpacked = stage / name
        if not (unpacked / "scrcpy").is_file() or not (unpacked / "scrcpy-server").is_file():
            raise FireTVError("O pacote não contém cliente e servidor scrcpy.")
        (unpacked / "scrcpy").chmod(0o755)
        shutil.move(str(unpacked), str(TOOLS / name))
    print(f"scrcpy instalado localmente; SHA-256 verificado: {LINUX_SHA256}")


def mirror_command(serial: str, adb: str | None = None):
    binary = find_scrcpy()
    env = os.environ.copy()
    env["ADB"] = adb or find_adb()
    # Local official bundles ship a matching server next to the binary.
    server = Path(binary).with_name("scrcpy-server")
    if server.is_file():
        env["SCRCPY_SERVER_PATH"] = str(server)
    command = [
        binary, "--serial", validate_serial(serial), "--no-audio", "--no-control",
        "--max-size=1280", "--max-fps=30", "--video-bit-rate=4M",
        "--window-title=Fire TV Control - Ao vivo", "--window-width=960",
    ]
    return command, env


def run_mirror(device):
    """Foreground CLI entry point; closing the window or Ctrl+C stops mirroring."""
    with device.lock:
        if not device.serial:
            raise FireTVError("Conecte o Fire TV primeiro: python3 run.py connect IP")
        device.run("get-state")
        command, env = mirror_command(device.serial, device.adb)
    process = subprocess.Popen(command, env=env)
    try:
        code = process.wait()
        if code:
            raise FireTVError(f"scrcpy encerrou com código {code}. Confira as mensagens acima.")
    except KeyboardInterrupt:
        process.terminate()
        try:
            process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
