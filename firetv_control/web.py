"""Loopback-only panel with a per-launch capability token and fixed operations."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
import json
import mimetypes
import os
from pathlib import Path
import secrets
import shutil
import tempfile
from urllib.parse import parse_qs, quote, urlsplit
import webbrowser
import threading
import signal

from .backend import FireTV, FireTVError, shared_path
from .live import LiveMirror

MAX_UPLOAD = 2 * 1024 * 1024 * 1024


def make_server(device: FireTV, port=8765, mirror=None):
    token_path = device.config.with_name("panel-token")
    token_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with token_path.open("x", encoding="utf-8") as handle:
            token_path.chmod(0o600)
            handle.write(secrets.token_urlsafe(32))
    except FileExistsError:
        pass
    token = token_path.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise FireTVError("Chave do painel inválida. Remova o arquivo panel-token para gerar outra.")
    mirror = mirror or LiveMirror()
    static = Path(__file__).parent / "static"

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):
            pass  # Do not log the session URL or file names.

        def send(self, status, body, content_type="application/json; charset=utf-8", extra=None):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.headers_out(content_type, len(body), extra)
            self.end_headers()
            self.wfile.write(body)

        def headers_out(self, content_type, length, extra=None):
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            for key, value in (extra or {}).items():
                self.send_header(key, value)

        def allowed_host(self):
            # Reject DNS rebinding, cross-site origins and connections via other names.
            expected = f"127.0.0.1:{self.server.server_port}"
            origin = self.headers.get("Origin")
            if self.headers.get("Host") != expected or (origin and origin != f"http://{expected}"):
                self.close_connection = True
                self.send(403, {"ok": False, "error": "Origem não autorizada."})
                return False
            return True

        def authorized(self):
            if not self.allowed_host():
                return False
            supplied = self.headers.get("Authorization", "")
            cookies = SimpleCookie()
            try:
                cookies.load(self.headers.get("Cookie", ""))
            except Exception:
                pass
            cookie = cookies.get("firetv-session")
            from_cookie = cookie.value if cookie else ""
            valid_header = secrets.compare_digest(supplied.encode("utf-8"), ("Bearer " + token).encode("utf-8"))
            valid_cookie = secrets.compare_digest(from_cookie.encode("utf-8"), token.encode("utf-8"))
            if not valid_header and not valid_cookie:
                self.close_connection = True
                self.send(401, {"ok": False, "error": "Sessão inválida. Abra o endereço completo impresso no terminal."})
                return False
            return True

        def length(self, limit):
            try:
                length = int(self.headers.get("Content-Length", "-1"))
            except ValueError as exc:
                raise FireTVError("Tamanho da requisição inválido.") from exc
            if length < 0 or length > limit or self.headers.get("Transfer-Encoding"):
                raise FireTVError("Arquivo ou requisição grande demais, ou tamanho não informado.")
            return length

        def do_GET(self):
            if not self.allowed_host():
                return
            route = urlsplit(self.path).path
            if route == "/healthz":
                self.send(200, {"ok": True})
                return
            if route == "/api/live":
                if not self.authorized():
                    return
                self.live_video()
                return
            files = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}
            if route in files:
                path = static / files[route]
                self.send(200, path.read_bytes(), mimetypes.guess_type(str(path))[0] or "application/octet-stream")
            else:
                self.send(404, {"ok": False, "error": "Não encontrado."})

        def do_POST(self):
            if not self.authorized():
                return
            try:
                self.connection.settimeout(300)
                parsed = urlsplit(self.path)
                if parsed.path == "/api/upload":
                    # Keep the selected target fixed while receiving a large file.
                    with device.lock:
                        self.upload(parse_qs(parsed.query))
                    return
                length = self.length(64 * 1024)
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise FireTVError("Requisição interrompida.")
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise FireTVError("Envie um objeto JSON.")
                if parsed.path == "/api/download":
                    self.download(data)
                    return
                if parsed.path != "/api/action":
                    self.send(404, {"ok": False, "error": "Operação não encontrada."})
                    return
                action = data.pop("action", "")
                if not isinstance(action, str):
                    raise FireTVError("Operação inválida.")
                with device.lock:
                    if action == "mirror_start":
                        result = mirror.start(device)
                    elif action == "mirror_stop":
                        result = mirror.stop()
                    elif action == "mirror_status":
                        result = mirror.status()
                    else:
                        # Close the old device's video before connecting/selecting another one.
                        if action in ("connect", "select", "disconnect"):
                            mirror.stop()
                        result = device.dispatch(action, data)
                self.send(200, {"ok": True, "data": result}, extra={
                    "Set-Cookie": f"firetv-session={token}; HttpOnly; SameSite=Strict; Path=/api/; Max-Age=31536000"
                })
            except (FireTVError, ValueError, TypeError, KeyError) as exc:
                self.close_connection = True
                self.send(400, {"ok": False, "error": str(exc)})
            except OSError as exc:
                self.close_connection = True
                try:
                    self.send(500, {"ok": False, "error": f"Falha de leitura ou gravação: {exc}"})
                except OSError:
                    pass

        def live_video(self):
            session = mirror.current_session()
            if session is None or not mirror.status()["running"]:
                self.send(409, {"ok": False, "error": "Inicie o vídeo ao vivo primeiro."})
                return
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=firetv-frame")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            self.connection.settimeout(10)
            sequence = -1
            try:
                while not session.stopped.is_set():
                    sequence, frame = session.frame_after(sequence, timeout=5)
                    if frame is None:
                        continue
                    self.wfile.write(b"--firetv-frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                     + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n")
                    self.wfile.flush()
            except (OSError, TimeoutError):
                pass  # A closed/slow browser must not stop the shared video encoder.

        def upload(self, query):
            length = self.length(MAX_UPLOAD)
            mode = query.get("mode", [""])[0]
            if mode not in ("install", "push"):
                raise FireTVError("Tipo de envio inválido.")
            with tempfile.TemporaryDirectory(prefix="firetv-upload-") as directory:
                path = Path(directory) / ("upload.apk" if mode == "install" else "upload.bin")
                remaining = length
                with path.open("wb") as handle:
                    while remaining:
                        chunk = self.rfile.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise FireTVError("Envio interrompido.")
                        handle.write(chunk)
                        remaining -= len(chunk)
                with device.lock:
                    result = device.install(str(path)) if mode == "install" else device.push(
                        str(path), query.get("path", [""])[0], query.get("overwrite", ["false"])[0] == "true"
                    )
                self.send(200, {"ok": True, "data": result})

        def download(self, data):
            remote = shared_path(data.get("path", ""))
            with tempfile.TemporaryDirectory(prefix="firetv-download-") as directory:
                local = Path(directory) / "download"
                with device.lock:
                    # Browser transfers are files; CLI pull also supports directory trees.
                    device.shell("test", "-f", remote)
                    device.pull(remote, str(local))
                if not local.is_file():
                    raise FireTVError("Selecione um arquivo para baixar.")
                name = remote.rsplit("/", 1)[-1]
                self.send_response(200)
                self.headers_out("application/octet-stream", local.stat().st_size, {
                    "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name, safe='')}"
                })
                self.end_headers()
                with local.open("rb") as handle:
                    shutil.copyfileobj(handle, self.wfile, 1024 * 1024)

    server = ThreadingHTTPServer((os.environ.get("FIRETV_BIND", "127.0.0.1"), port), Handler)
    server.daemon_threads = True
    server.mirror = mirror
    original_close = server.server_close
    def close():
        mirror.stop()
        original_close()
    server.server_close = close
    return server, f"http://127.0.0.1:{server.server_port}/#{token}"


def serve(device: FireTV, port=8765, open_browser=True):
    server, url = make_server(device, port)
    print(f"Fire TV Control — painel local\n{url}\nCtrl+C para encerrar.", flush=True)
    if open_browser:
        webbrowser.open(url)
    stopped = threading.Event()
    if threading.current_thread() is threading.main_thread():
        def terminate(_signum, _frame):
            raise KeyboardInterrupt()
        signal.signal(signal.SIGTERM, terminate)
    def reconnect():
        while not stopped.is_set():
            with device.lock:
                # An explicit saved disconnect suppresses the initial env target.
                target = device.serial or (os.environ.get("FIRETV_DEVICE") if not device.config.exists() else None)
                if target and (":" in target or target.count(".") == 3):
                    try:
                        state = next((item for item in device.devices() if item["serial"] == device.serial), {})
                        if state.get("state") != "device":
                            device.connect(target)
                    except (FireTVError, OSError):
                        pass  # User may still need to authorize this PC on the TV.
            stopped.wait(15)
    if os.environ.get("FIRETV_RECONNECT") == "1":
        threading.Thread(target=reconnect, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stopped.set()
        server.server_close()
