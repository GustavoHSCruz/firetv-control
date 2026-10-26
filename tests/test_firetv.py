"""Contract tests with a real subprocess fixture and real loopback HTTP server."""

from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from firetv_control.backend import FireTV, FireTVError, endpoint, shared_path
from firetv_control.web import make_server

FIXTURE = Path(__file__).with_name("fake_adb.py").resolve()
ROOT = Path(__file__).resolve().parents[1]


class DeviceFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name) / "config.json"
        self.log = Path(self.tmp.name) / "commands.jsonl"
        env = patch.dict(os.environ, {"FIRETV_TEST_LOG": str(self.log)})
        env.start()
        self.addCleanup(env.stop)
        self.device = FireTV(adb=str(FIXTURE), config=self.config)

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def connect(self):
        self.device.connect("192.168.1.50")


class DeviceTests(DeviceFixture):
    def test_connect_requires_ready_state_and_persists_only_success(self):
        with patch.dict(os.environ, {"FIRETV_TEST_STATE": "unauthorized"}):
            with self.assertRaisesRegex(FireTVError, "unauthorized"):
                self.connect()
        self.assertIsNone(self.device.serial)
        self.assertFalse(self.config.exists())
        self.connect()
        self.assertEqual(json.loads(self.config.read_text())["serial"], "192.168.1.50:5555")
        self.assertEqual(FireTV(config=self.config).serial, "192.168.1.50:5555")

    def test_command_failure_in_stdout_cannot_report_success(self):
        self.connect()
        apk = Path(self.tmp.name) / "example.apk"
        apk.write_bytes(b"test apk")
        with patch.dict(os.environ, {"FIRETV_TEST_INSTALL": "Failure [INSTALL_FAILED_VERSION_DOWNGRADE]"}):
            with self.assertRaisesRegex(FireTVError, "INSTALL_FAILED"):
                self.device.install(str(apk))

    def test_uninstall_requires_confirmation_and_rejects_system_apps(self):
        self.connect()
        with self.assertRaises(FireTVError):
            self.device.uninstall("org.example.player")
        with self.assertRaisesRegex(FireTVError, "terceiros"):
            self.device.uninstall("com.amazon.tv.launcher", True)
        self.assertFalse(any("uninstall" in row for row in self.commands()))
        self.device.uninstall("org.example.player", True)
        self.assertEqual(self.commands()[-1][-2:], ["uninstall", "org.example.player"])

    def test_remote_shell_quoting_blocks_command_substitution(self):
        self.connect()
        text = "hello ' $(touch owned); `id` & bye"
        self.device.text(text)
        command = self.commands()[-1]
        self.assertEqual(command[:3], ["-s", "192.168.1.50:5555", "shell"])
        self.assertEqual(shlex.split(command[3]), ["input", "text", text.replace(" ", "%s")])
        # Prove the resulting command under a real shell, with input replaced by printf.
        command_line = command[3].replace("input text ", "printf '%s' ", 1)
        output = subprocess.run(["sh", "-c", command_line], cwd=self.tmp.name, capture_output=True, check=True)
        self.assertEqual(output.stdout.decode(), text.replace(" ", "%s"))
        self.assertFalse((Path(self.tmp.name) / "owned").exists())

    def test_shared_storage_validation_and_name_framing(self):
        self.connect()
        self.assertEqual(shared_path("/sdcard/Download/../notes.txt"), "/sdcard/notes.txt")
        for path in ("/data/data/app", "/sdcard/../../data", "/sdcard2/test", "/sdcard/a\nfile"):
            with self.assertRaises(FireTVError):
                shared_path(path)
        entries = self.device.files("/sdcard")['entries']
        self.assertEqual(entries[0]['kind'], 'directory')
        self.assertTrue(any(e['name'] == "a'$(touch owned).txt" for e in entries))

    def test_upload_cannot_silently_overwrite_and_pull_requires_new_destination(self):
        self.connect()
        local = Path(self.tmp.name) / "local.txt"
        local.write_text("test")
        with patch.dict(os.environ, {"FIRETV_TEST_EXISTS": "1"}):
            with self.assertRaisesRegex(FireTVError, "já existe"):
                self.device.push(str(local), "/sdcard/local.txt")
        self.assertFalse(any("push" in row for row in self.commands()))
        with self.assertRaisesRegex(FireTVError, "já existe"):
            self.device.pull("/sdcard/local.txt", str(local))

    def test_screenshot_bytes_and_home_inspection(self):
        self.connect()
        self.assertTrue(self.device.screenshot().startswith(b"\x89PNG"))
        result = self.device.home()
        self.assertEqual(result['launchers'][0]['package'], "org.example.launcher")
        self.device.open_launcher('org.example.launcher/.MainActivity')
        self.assertEqual(shlex.split(self.commands()[-1][-1]), ['am', 'start', '-n', 'org.example.launcher/.MainActivity'])
        with self.assertRaises(FireTVError):
            self.device.open_launcher('not.installed/.MainActivity')
        self.assertFalse(any("disable-user" in str(row) for row in self.commands()))

    def test_ip_and_port_validation(self):
        self.assertEqual(endpoint("192.168.1.50"), "192.168.1.50:5555")
        for address in ("192.168.1.50;id", "-s", "127.0.0.1:0", "192.168.1.50:65536", "0.0.0.0"):
            with self.assertRaises(FireTVError):
                endpoint(address)

    def test_device_switch_waits_for_complete_workflow(self):
        started, finish, switched = threading.Event(), threading.Event(), threading.Event()
        def block(*_args):
            started.set()
            finish.wait(3)
            return []
        def switch():
            self.device.select("192.168.1.50:5555")
            switched.set()
        with patch.object(self.device, 'apps', side_effect=block), ThreadPoolExecutor(2) as pool:
            first = pool.submit(self.device.dispatch, 'apps', {})
            self.assertTrue(started.wait(2))
            second = pool.submit(switch)
            self.assertFalse(switched.wait(.1))
            finish.set()
            first.result(3)
            second.result(3)
        self.assertTrue(switched.is_set())

    def test_json_cli_works_without_device_or_python_dependencies(self):
        env = dict(os.environ, FIRETV_ADB=str(FIXTURE), FIRETV_CONFIG=str(self.config))
        result = subprocess.run(["python3", "run.py", "--json", "doctor"], cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['data']['ready'])


class HttpTests(DeviceFixture):
    def setUp(self):
        super().setUp()
        self.server, self.url = make_server(self.device, 0)
        self.token = self.url.split('#')[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def http(self, path, data=None, headers=None, raw=None):
        client = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        supplied = {"Authorization": "Bearer " + self.token}
        supplied.update(headers or {})
        body = raw if raw is not None else json.dumps(data).encode() if data is not None else None
        client.request("POST" if body is not None else "GET", path, body, supplied)
        result = client.getresponse()
        status, response, response_headers = result.status, result.read(), result.headers
        client.close()
        return status, response, response_headers

    def test_api_rejects_missing_token_cross_origin_and_dns_rebinding(self):
        for headers in ({"Authorization": ""}, {"Origin": "https://example.com"}, {"Host": "attacker.invalid"}):
            status, _, _ = self.http('/api/action', {"action": "devices"}, headers)
            self.assertIn(status, (401, 403))
        self.assertFalse(self.log.exists())

    def test_static_page_and_security_headers(self):
        status, body, headers = self.http('/')
        self.assertEqual(status, 200)
        self.assertIn(b'Fire TV Control', body)
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertEqual(headers['Cache-Control'], 'no-store')

    def test_bad_json_unknown_action_and_wrong_confirmation_type_are_rejected(self):
        for raw in (b'{', b'[]', b'{"action": "shell"}'):
            status, _, _ = self.http('/api/action', raw=raw)
            self.assertEqual(status, 400)
        self.connect()
        status, body, _ = self.http('/api/action', {"action": "uninstall", "package": "org.example.player", "confirmed": "true"})
        self.assertEqual(status, 400)
        self.assertIn('Confirme', body.decode())

    def test_http_install_and_file_download(self):
        self.connect()
        status, body, _ = self.http('/api/upload?mode=install', raw=b'test APK')
        self.assertEqual(status, 200, body)
        self.assertTrue(json.loads(body)['ok'])
        status, body, headers = self.http('/api/download', {"path": "/sdcard/notes.txt"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body, b'file from test fixture\n')
        self.assertIn('notes.txt', headers['Content-Disposition'])


if __name__ == '__main__':
    unittest.main()
