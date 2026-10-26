"""Streaming invariants without a device, display server or FFmpeg installation."""

from io import BytesIO
import json
import threading
import unittest
from types import SimpleNamespace

from firetv_control.live import Session
from firetv_control.web import make_server
import test_firetv as fixtures


class FakeSession:
    def __init__(self):
        self.stopped = threading.Event()
        self.sequence = 1

    def frame_after(self, _sequence, timeout=5):
        self.stopped.set()
        return 1, b"\xff\xd8test-frame\xff\xd9"


class FakeMirror:
    def __init__(self):
        self.running = False
        self.stops = 0
        self.session = None

    def start(self, _device):
        self.session = FakeSession()
        self.running = True
        return self.status()

    def stop(self):
        self.running = False
        self.stops += 1
        if self.session:
            self.session.stopped.set()
        return self.status()

    def status(self):
        return {"running": self.running, "serial": "192.168.1.50:5555" if self.running else None}

    def current_session(self):
        return self.session


class LiveHttpTests(fixtures.DeviceFixture):
    http = fixtures.HttpTests.http
    stop = fixtures.HttpTests.stop

    def setUp(self):
        super().setUp()
        self.mirror = FakeMirror()
        self.server, self.url = make_server(self.device, 0, mirror=self.mirror)
        self.token = self.url.split('#')[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def test_cookie_bootstrap_is_httponly_and_authorizes_api_without_header(self):
        status, _, headers = self.http('/api/action', {'action': 'doctor'})
        self.assertEqual(status, 200)
        cookie = headers['Set-Cookie']
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=Strict', cookie)
        status, _, _ = self.http('/api/action', {'action': 'devices'},
                                 {'Authorization': '', 'Cookie': cookie.split(';')[0]})
        self.assertEqual(status, 200)
        status, _, _ = self.http('/api/action', {'action': 'devices'},
                                 {'Authorization': '', 'Cookie': cookie.split(';')[0], 'Origin': 'https://attacker.invalid'})
        self.assertEqual(status, 403)

    def test_live_stream_requires_auth_and_has_jpeg_framing(self):
        status, _, _ = self.http('/api/live', headers={'Authorization': ''})
        self.assertEqual(status, 401)
        status, _, _ = self.http('/api/live')
        self.assertEqual(status, 409)
        status, _, _ = self.http('/api/action', {'action': 'mirror_start'})
        self.assertEqual(status, 200)
        status, data, headers = self.http('/api/live')
        self.assertEqual(status, 200)
        self.assertIn('multipart/x-mixed-replace', headers['Content-Type'])
        self.assertIn(b'--firetv-frame\r\n', data)
        self.assertIn(b'\xff\xd8test-frame\xff\xd9', data)

    def test_changing_devices_stops_previous_video_and_server_close_cleans_up(self):
        self.http('/api/action', {'action': 'mirror_start'})
        self.assertTrue(self.mirror.running)
        self.http('/api/action', {'action': 'connect', 'address': '192.168.1.50'})
        self.assertFalse(self.mirror.running)
        self.http('/api/action', {'action': 'mirror_start'})
        self.server.server_close()
        self.assertFalse(self.mirror.running)

    def test_panel_key_survives_server_recreation(self):
        server, url = make_server(self.device, 0)
        try:
            self.assertEqual(url.split('#')[1], self.token)
        finally:
            server.server_close()


class FrameTests(unittest.TestCase):
    def test_latest_frame_replaces_previous_frame_without_a_viewer_queue(self):
        import os
        session = Session('test-device', 'not-used')
        self.addCleanup(session.close)
        read_fd, write_fd = os.pipe()
        reader = os.fdopen(read_fd, 'rb', buffering=0)
        writer = os.fdopen(write_fd, 'wb', buffering=0)
        self.addCleanup(reader.close)
        session.decoder = SimpleNamespace(stdout=reader, stdin=BytesIO(), poll=lambda: 0)
        thread = threading.Thread(target=session.frames)
        thread.start()
        writer.write(b'\xff\xd8first\xff\xd9\xff\xd8second\xff\xd9\xff\xd8latest\xff\xd9')
        writer.close()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        sequence, frame = session.frame_after(0)
        self.assertEqual(sequence, 3)
        self.assertEqual(frame, b'\xff\xd8latest\xff\xd9')


if __name__ == '__main__':
    unittest.main()
