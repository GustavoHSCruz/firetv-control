"""Browser video: scrcpy's raw H.264 stream -> FFmpeg -> latest JPEG frames.

One encoder/decoder session is shared by viewers. Slow viewers skip frames
instead of queuing video. Uses the documented standalone scrcpy protocol.
"""

from __future__ import annotations

import os
from pathlib import Path
import secrets
import shlex
import shutil
import socket
import subprocess
import tempfile
import threading
import time

from .backend import FireTVError, find_adb
from .mirror import TOOLS, VERSION


def find_server():
    override = os.environ.get("FIRETV_SCRCPY_SERVER")
    candidates = [override] if override else [
        str(TOOLS / f"scrcpy-linux-x86_64-v{VERSION}" / "scrcpy-server"),
        "/usr/local/share/scrcpy/scrcpy-server",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise FireTVError("Servidor de vídeo ausente. Execute python3 run.py setup-mirror ou use a imagem Docker do projeto.")


class Session:
    def __init__(self, serial, adb):
        self.serial, self.adb = serial, adb
        self.condition = threading.Condition()
        self.stopped = threading.Event()
        self.latest = None
        self.sequence = 0
        self.error = ""
        self.socket = None
        self.server = None
        self.decoder = None
        self.port = None
        self.remote = None
        self.logs = tempfile.TemporaryDirectory(prefix="firetv-live-")
        self.server_log = open(Path(self.logs.name) / "server.log", "w+b")
        self.decoder_log = open(Path(self.logs.name) / "decoder.log", "w+b")
        self.threads = []

    def fail(self, error):
        with self.condition:
            if not self.stopped.is_set():
                self.error = str(error)
            self.stopped.set()
            self.condition.notify_all()

    def feed(self, initial):
        try:
            chunk = initial
            while chunk and not self.stopped.is_set():
                remaining = memoryview(chunk)
                while remaining and not self.stopped.is_set():
                    written = self.decoder.stdin.write(remaining)
                    if not written:
                        raise OSError("O decodificador encerrou a entrada.")
                    remaining = remaining[written:]
                self.decoder.stdin.flush()
                chunk = self.socket.recv(65536)
            if not self.stopped.is_set():
                self.fail("A transmissão da TV foi encerrada.")
        except OSError as exc:
            self.fail(f"A conexão de vídeo foi interrompida: {exc}")
        finally:
            try:
                self.decoder.stdin.close()
            except OSError:
                pass

    def frames(self):
        buffer = bytearray()
        try:
            while not self.stopped.is_set():
                chunk = os.read(self.decoder.stdout.fileno(), 65536)
                if not chunk:
                    break
                buffer.extend(chunk)
                while True:
                    start = buffer.find(b"\xff\xd8")
                    end = buffer.find(b"\xff\xd9", max(0, start + 2))
                    if start < 0 or end < 0:
                        break
                    frame = bytes(buffer[start:end + 2])
                    del buffer[:end + 2]
                    with self.condition:
                        self.latest = frame
                        self.sequence += 1
                        self.condition.notify_all()
                if len(buffer) > 16 * 1024 * 1024:
                    raise ValueError("O decodificador excedeu o limite por quadro.")
            if not self.stopped.is_set():
                self.fail("O decodificador de vídeo foi encerrado.")
        except (OSError, ValueError) as exc:
            self.fail(exc)

    def frame_after(self, sequence, timeout=5):
        with self.condition:
            self.condition.wait_for(lambda: self.sequence > sequence or self.stopped.is_set(), timeout)
            if self.sequence > sequence:
                return self.sequence, self.latest
            return sequence, None

    def diagnostics(self):
        result = []
        for handle in (self.server_log, self.decoder_log):
            try:
                handle.seek(0)
                result.append(handle.read().decode("utf-8", errors="replace")[-2500:])
            except (ValueError, OSError):
                pass
        return "\n".join(result)

    def close(self):
        self.stopped.set()
        with self.condition:
            self.condition.notify_all()
        if self.socket:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.socket.close()
        for process in (self.decoder, self.server):
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
        for thread in self.threads:
            thread.join(timeout=2)
        if self.decoder:
            for handle in (self.decoder.stdin, self.decoder.stdout):
                if handle:
                    handle.close()
        for operands in ((["forward", "--remove", "tcp:" + self.port] if self.port else []),
                         (["shell", shlex.join(["rm", "-f", self.remote])] if self.remote else [])):
            if not operands:
                continue
            try:
                subprocess.run([self.adb, "-s", self.serial, *operands], capture_output=True, timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                pass
        self.server_log.close()
        self.decoder_log.close()
        self.logs.cleanup()


class LiveMirror:
    def __init__(self):
        self.lock = threading.RLock()
        self.session = None

    def status(self):
        with self.lock:
            session = self.session
            if session is None:
                return {"running": False, "serial": None, "frames": 0}
            running = (not session.stopped.is_set() and session.decoder is not None
                       and session.decoder.poll() is None and session.server.poll() is None)
            return {"running": running, "serial": session.serial if running else None,
                    "frames": session.sequence, "error": session.error if not running else ""}

    def start(self, device):
        with device.lock, self.lock:
            if not device.serial:
                raise FireTVError("Conecte o Fire TV antes de iniciar o vídeo.")
            if self.status()["running"] and self.session.serial == device.serial:
                return self.status()
            self.stop()
            server_file = find_server()
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                raise FireTVError("FFmpeg não encontrado. Instale FFmpeg ou use a imagem Docker do projeto.")
            device.run("get-state")
            session = Session(device.serial, device.adb or find_adb())
            self.session = session
            scid = f"{secrets.randbits(31):08x}"
            session.remote = f"/data/local/tmp/firetv-control-{scid}.jar"
            try:
                device.run("push", server_file, session.remote)
                session.port = device.run("forward", "tcp:0", "localabstract:scrcpy_" + scid)
                if not session.port.isdigit():
                    raise FireTVError("O ADB não retornou a porta do vídeo.")
                options = ["env", "CLASSPATH=" + session.remote, "app_process", "/", "com.genymobile.scrcpy.Server", VERSION,
                           "scid=" + scid, "tunnel_forward=true", "audio=false", "control=false", "cleanup=false",
                           "raw_stream=true", "max_size=1280", "max_fps=30", "video_bit_rate=4000000", "power_on=false"]
                session.server = subprocess.Popen([session.adb, "-s", session.serial, "shell", shlex.join(options)],
                                                   stdin=subprocess.DEVNULL, stdout=session.server_log, stderr=subprocess.STDOUT)
                first = None
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    if session.server.poll() is not None:
                        break
                    try:
                        sock = socket.create_connection(("127.0.0.1", int(session.port)), timeout=2)
                        try:
                            first = sock.recv(4096)
                        except OSError:
                            sock.close()
                            raise
                        if first:
                            sock.settimeout(None)
                            session.socket = sock
                            break
                        sock.close()
                    except OSError:
                        pass
                    time.sleep(.1)
                if not first:
                    raise FireTVError("O Fire TV não iniciou a transmissão. " + session.diagnostics())
                command = [ffmpeg, "-hide_banner", "-loglevel", "warning", "-flags", "low_delay",
                           "-probesize", "32", "-analyzeduration", "0", "-f", "h264", "-i", "pipe:0",
                           "-an", "-c:v", "mjpeg", "-q:v", "5", "-threads", "2", "-f", "image2pipe", "pipe:1"]
                session.decoder = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                                    stderr=session.decoder_log, bufsize=0)
                session.threads = [threading.Thread(target=session.feed, args=(first,), daemon=True),
                                   threading.Thread(target=session.frames, daemon=True)]
                for thread in session.threads:
                    thread.start()
                _, frame = session.frame_after(0, timeout=12)
                if not frame:
                    raise FireTVError("Nenhum quadro de vídeo recebido. " + session.diagnostics())
                return {**self.status(), "message": "Vídeo ao vivo iniciado no navegador. O áudio continua na TV."}
            except (OSError, FireTVError) as exc:
                self.stop()
                raise FireTVError(str(exc)) from exc

    def stop(self):
        with self.lock:
            if self.session is not None:
                self.session.close()
                self.session = None
            return {"running": False, "serial": None}

    def current_session(self):
        with self.lock:
            return self.session
