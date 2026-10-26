"""CLI-Anything-style JSON/subcommand interface without Python dependencies."""

import argparse
import json
from pathlib import Path
import sys

from .backend import FireTV, FireTVError, KEYS


def parser():
    root = argparse.ArgumentParser(description="Fire TV Control — apps, arquivos e controle remoto pelo PC.")
    root.add_argument("--json", action="store_true", help="Saída estruturada em JSON.")
    root.add_argument("--device", help="Identificador de adb devices; padrão: último dispositivo conectado.")
    commands = root.add_subparsers(dest="command")
    for name in ("doctor", "devices", "disconnect", "info", "home"):
        commands.add_parser(name)
    commands.add_parser("connect").add_argument("address", help="IP[:porta] do Fire TV.")
    commands.add_parser("select").add_argument("serial")
    apps = commands.add_parser("apps")
    apps.add_argument("--all", action="store_true", help="Incluir apps do sistema para consulta.")
    commands.add_parser("install").add_argument("apk")
    remove = commands.add_parser("uninstall")
    remove.add_argument("package")
    remove.add_argument("--yes", action="store_true", help="Confirmar remoção do app e dos seus dados locais.")
    commands.add_parser("launch").add_argument("package")
    commands.add_parser("key").add_argument("key", choices=KEYS)
    commands.add_parser("text").add_argument("text")
    commands.add_parser("files").add_argument("path", nargs="?", default="/sdcard")
    push = commands.add_parser("push")
    push.add_argument("local")
    push.add_argument("remote", help="Caminho completo do arquivo de destino, em /sdcard.")
    push.add_argument("--overwrite", action="store_true")
    pull = commands.add_parser("pull")
    pull.add_argument("remote")
    pull.add_argument("local", help="Caminho novo no PC (arquivo ou pasta).")
    commands.add_parser("screenshot").add_argument("output")
    commands.add_parser("mirror", help="Abrir vídeo ao vivo em uma janela do PC (scrcpy).")
    web = commands.add_parser("web")
    web.add_argument("--port", type=int, default=8765)
    web.add_argument("--no-browser", action="store_true")
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    device = FireTV(serial=args.device)
    try:
        if args.command in (None, "web"):
            from .web import serve
            serve(device, getattr(args, "port", 8765), not getattr(args, "no_browser", False))
            return 0
        command = args.command
        if command == "mirror":
            from .mirror import run_mirror
            if args.json:
                raise FireTVError("O comando mirror abre uma janela interativa. Execute sem --json.")
            run_mirror(device)
            return 0
        elif command == "install":
            result = device.install(args.apk)
        elif command == "uninstall":
            result = device.uninstall(args.package, args.yes)
        elif command == "push":
            result = device.push(args.local, args.remote, args.overwrite)
        elif command == "pull":
            result = device.pull(args.remote, args.local)
        elif command == "screenshot":
            path = Path(args.output).expanduser().resolve()
            png = device.screenshot()
            with path.open("xb") as handle:
                handle.write(png)
            result = {"path": str(path)}
        else:
            data = vars(args).copy()
            result = device.dispatch(command, data)
        print(json.dumps({"ok": True, "data": result}, ensure_ascii=False, indent=2) if args.json else
              json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if command == "doctor" and not result["ready"] else 0
    except (FireTVError, OSError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        else:
            print(f"Erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
