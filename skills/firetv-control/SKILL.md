---
name: firetv-control
description: Manage a user's Fire TV running Fire OS through the Fire TV Control CLI or local Docker panel. Use for APK installation, app management, shared files, remote keys, screenshots, or live viewing; does not support Vega OS devices.
---

# Fire TV Control

Use the installed `firetv-control` command or `python3 run.py` from the checkout.
The application is standalone; CLI-Anything is a design reference, not a dependency.

Start with `firetv-control --json doctor` and `firetv-control --json devices`.
The global flags `--json` and `--device SERIAL` precede subcommands. Connect with
`firetv-control connect IP[:PORT]`. The user must enable ADB debugging and accept
the computer's key on the TV. ADB support does not establish APK compatibility.

Useful operations:

```sh
firetv-control --json info
firetv-control --json apps
firetv-control install /absolute/path/app.apk
firetv-control launch org.example.app
firetv-control uninstall org.example.app --yes
firetv-control files /sdcard/Download
firetv-control push ./video.mp4 /sdcard/Download/video.mp4
firetv-control pull /sdcard/Download ./new-backup-directory
firetv-control screenshot ./new-capture.png
firetv-control key home
firetv-control text 'plain ASCII text'
firetv-control home
```

Uninstall deletes the app's local data and requires `--yes`; only third-party
packages may be removed. `push` refuses existing destinations unless
`--overwrite` is explicitly supplied; `pull` and `screenshot` require new local
destinations. Transfer paths are confined to shared storage, not private app
data, credentials or DRM downloads. After a timeout, inspect the result before
repeating a mutation. There is no generic remote shell endpoint.

For browser viewing use `docker compose up -d --build` or
`firetv-control web --no-browser`. Open the complete session URL printed by the
service once; its HttpOnly cookie remembers the browser. The panel has
**Ver ao vivo** and **Encerrar vídeo** controls. Browser video uses scrcpy's
temporary server, H.264 and FFmpeg, with latest-frame MJPEG delivery. Android 9
does not forward audio. Protected video may appear black. `mirror` is an optional
native scrcpy window command, not a JSON operation or the Docker video path.

`home` only inspects launchers. Installing or opening an alternative launcher
does not replace the Home button. Do not infer launcher replacement support
from the Fire OS major version; it depends on device and firmware.

Docker persists ADB keys, selected device and panel key in the named volume.
Keep the published port on loopback. See [the README](../../README.md) for
Docker setup, prerequisites and the tested hardware/limitations.
