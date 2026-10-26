#!/usr/bin/env python3
"""Run in-place, or install Google's official platform-tools locally."""

from pathlib import Path
import os
import platform
import shutil
import sys
import tempfile
import urllib.request
import zipfile


def setup():
    target = Path(__file__).resolve().parent / ".tools"
    system = {"Linux": "linux", "Darwin": "darwin", "Windows": "windows"}.get(platform.system())
    if not system or (system == "linux" and platform.machine() not in ("x86_64", "AMD64")):
        raise RuntimeError("Instale o ADB pelo gerenciador de pacotes da sua plataforma e defina FIRETV_ADB.")
    binary = target / "platform-tools" / ("adb.exe" if system == "windows" else "adb")
    if binary.exists():
        print(f"ADB local já instalado: {binary}")
        return
    url = f"https://dl.google.com/android/repository/platform-tools-latest-{system}.zip"
    print(f"Baixando Android SDK Platform-Tools oficial:\n{url}", flush=True)
    target.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="firetv-platform-tools-") as directory:
        archive = Path(directory) / "tools.zip"
        with urllib.request.urlopen(url, timeout=60) as response, archive.open("wb") as handle:
            shutil.copyfileobj(response, handle)
        stage = Path(directory) / "extract"
        with zipfile.ZipFile(archive) as package:
            # Only accept ordinary files below the expected root.
            for item in package.infolist():
                name = Path(item.filename)
                if name.is_absolute() or ".." in name.parts or not name.parts or name.parts[0] != "platform-tools":
                    raise RuntimeError("Estrutura inesperada no pacote Platform-Tools.")
            package.extractall(stage)
        unpacked = stage / "platform-tools"
        adb = unpacked / binary.name
        if not adb.is_file():
            raise RuntimeError("O pacote não contém o executável ADB.")
        if os.name != "nt":
            for path in unpacked.iterdir():
                if path.is_file() and (path.name in ("adb", "fastboot", "sqlite3") or path.name.startswith("make_f2fs")):
                    path.chmod(0o755)
        shutil.move(str(unpacked), str(target / "platform-tools"))
    print(f"Instalado apenas neste projeto: {binary}")


if __name__ == "__main__":
    if sys.argv[1:] == ["setup-mirror"]:
        from firetv_control.backend import FireTVError
        from firetv_control.mirror import install_scrcpy
        try:
            install_scrcpy()
        except (FireTVError, OSError) as exc:
            print(f"Erro: {exc}", file=sys.stderr)
            raise SystemExit(1)
        raise SystemExit(0)
    if sys.argv[1:] == ["setup"]:
        try:
            setup()
        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
            print(f"Erro: {exc}", file=sys.stderr)
            raise SystemExit(1)
    else:
        from firetv_control.cli import main
        raise SystemExit(main())
