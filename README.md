# Fire TV Control

A standalone Fire OS manager with a local browser panel, live video, CLI and Docker Compose.
No Android Studio, cloud account, root access or Python runtime dependencies.
The current interface is in Brazilian Portuguese; the CLI emits structured JSON.

[Português](README.pt-BR.md) · [Agent skill](skills/firetv-control/SKILL.md)

## Run with Docker

```sh
git clone https://github.com/GustavoHSCruz/firetv-control.git
cd firetv-control
cp .env.example .env
# Edit FIRETV_DEVICE in .env with your Fire TV's IP (optional).
docker compose up -d --build
```

For the first browser authorization, get the complete session URL:

```sh
docker compose logs firetv
```

Open the printed `http://127.0.0.1:8765/#...` URL on the same PC. After that,
bookmark **http://127.0.0.1:8765/**: an HttpOnly, SameSite=Strict cookie remembers
this browser, and the panel key persists across container restarts.
The fragment is removed from the address bar after opening the panel.

Enable **Settings → My Fire TV → Developer options → ADB debugging** and accept
the debugging-key prompt on the TV. If Developer options is hidden, select the
device name in **About** seven times. Find its address in **About → Network**.
The computer and TV must be on the same network.

The container has its own persistent ADB identity. Authorize that identity once;
it is preserved with your selected device and panel key in `firetv-state`.
The optional `FIRETV_DEVICE` target is reconnected automatically. The volume does
not back up the TV's apps or files.

`restart: unless-stopped` brings the service back when Docker starts. The Docker
service or Docker Desktop must itself start at login/boot. Close the terminal;
the container keeps running. Use `docker compose stop` to stop intentionally,
`docker compose up -d` to resume and `docker compose down` to remove the container
while retaining state. Adding `--volumes` deletes the saved keys and state.

Docker publishes only on **127.0.0.1:8765**. It needs neither privileged mode,
USB passthrough, host networking nor access to the host Docker socket. Shared
storage uploads/downloads use temporary files in the data volume.

## Features

- **Apps:** inspect package IDs, install/update single APKs, launch apps and
  uninstall third-party apps with confirmation.
- **Files:** browse shared storage, upload with progress and download files.
  CLI pull also supports directories; overwrites are opt-in.
- **Remote:** D-pad, OK, Back, Home, Menu and playback buttons; plain ASCII text
  input and keyboard shortcuts in the remote tab.
- **Live video:** click **Ver ao vivo** in the remote tab. H.264 is captured on
  the TV, decoded by FFmpeg and delivered as an MJPEG stream to the browser.
  Slow viewers skip frames instead of building a playback backlog. The default
  source is capped at 720p/30 FPS; actual frame rate and latency vary with the TV
  and network. No desktop display server is needed inside Docker.
- **Screenshots:** capture/download PNG separately while live video is running.
- **Home inspection:** see the current launcher, inspect alternative HOME
  activities and open a launcher without changing the default Home binding.

**Limitations:** Fire OS only, not Vega OS. Android 9 does not provide scrcpy
system-audio capture, so sound stays on the TV. DRM-protected surfaces may be
black. APK architecture, API and service requirements still apply. Split APK
formats (XAPK/APKM/APKS) are not supported by the single-APK installer. The file
browser is for `/sdcard` and `/storage/emulated/0`, not private app data,
credentials, DRM downloads or a complete device backup. Text input supports
ASCII, excluding `%`, due to Android `input text` limitations.

An alternative Android TV launcher such as [Luncher](https://github.com/CVasilakis/luncher)
may provide its own wallpaper, app layout and colors. Install a compatible APK
from the project's official source and configure it on the TV. **Opening a
launcher does not replace the Home button.** Permanent replacement depends on
model and firmware. The panel does not disable the stock launcher or updates.

## Run without Docker

Python 3.10+ and ADB are required. Browser video also needs FFmpeg and the
matching scrcpy server. On Linux x86_64, the helper downloads an official
scrcpy bundle and verifies the published SHA-256:

```sh
python3 run.py setup
python3 run.py setup-mirror
# Install FFmpeg using your system package manager.
python3 run.py
```

`python3 run.py web --port 8766 --no-browser` changes the local port and avoids
opening a browser. `./iniciar.sh` checks ADB and starts the panel. Close the panel
server with Ctrl+C. `FIRETV_ADB`, `FIRETV_SCRCPY_SERVER` and `FIRETV_CONFIG` select
custom tool paths and state location. `FIRETV_SCRCPY` selects the optional native
client used by `python3 run.py mirror`; this native-window command is for hosts
with a desktop, not the headless Docker path.

Install the CLI separately, with ADB in PATH:

```sh
pip install git+https://github.com/GustavoHSCruz/firetv-control.git
firetv-control --json doctor
firetv-control connect 192.168.1.50
firetv-control --json apps
firetv-control install ./example.apk
firetv-control launch org.example.app
firetv-control uninstall org.example.app --yes
firetv-control files /sdcard/Download
firetv-control push ./video.mp4 /sdcard/Download/video.mp4
firetv-control pull /sdcard/Download ./new-backup-directory
firetv-control screenshot ./new-screenshot.png
firetv-control key home
firetv-control text 'plain ASCII text'
firetv-control home
```

Global `--json` and `--device SERIAL` precede the subcommand. Uninstall deletes
local app data. Only third-party packages can be removed. `push --overwrite`
allows replacing a remote file; `pull` and `screenshot` require new local paths.
After a timeout, check device state before repeating a mutation.

## Development and verification

```sh
python3 -m unittest discover -s tests -v
node --check firetv_control/static/app.js
# Optional browser integration test, using an existing Playwright installation:
FIRETV_PLAYWRIGHT=/path/to/node_modules/playwright node tests/test_browser.cjs
```

Tests use an explicit fake-ADB executable; it is never selected by the normal
launcher. Browser tests exercise the actual HTTP server and subprocess adapter.
See [hardware verification](VERIFICACAO.md) for physical-device evidence and
which operations were simulated. Tests and recordings never ship device keys,
APK files, panel secrets, personal files or screenshots in the repository.

## Origins and upstream documentation

This project was developed using the local **CLI-Anything** adapter/JSON patterns
and **REA** ADB shell-boundary and file-listing references. It has no runtime or
source-tree dependency on either project. The backend uses fixed ADB operations,
quotes values at the remote shell boundary and exposes no arbitrary shell API.

- [CLI-Anything contribution format for standalone CLIs](https://github.com/HKUDS/CLI-Anything/blob/main/CONTRIBUTING.md)
- [REA](https://github.com/morluto/rea)
- [Amazon: connect to Fire TV through ADB](https://developer.amazon.com/docs/fire-tv/connecting-adb-to-device.html)
- [Android ADB reference](https://developer.android.com/tools/adb)
- [scrcpy standalone streaming protocol](https://github.com/Genymobile/scrcpy/blob/master/doc/develop.md)
- [scrcpy audio requirements](https://github.com/Genymobile/scrcpy/blob/master/doc/audio.md)

MIT licensed. scrcpy is Apache-2.0 licensed, and the Docker image downloads its
server from the official release with a pinned SHA-256. ADB and FFmpeg are
installed from Debian packages. Application code and the interface were developed
with AI assistance and checked with local tests and physical hardware.
