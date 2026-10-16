#!/usr/bin/env python3
"""Unit tests for bin/wiim against the fixture WiiM server.

Run:  python3 -m unittest discover -s tests -v
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "bin"))

os.environ.setdefault("WIIM_BASE", "")  # ensure not inherited weirdly

import fixture_server  # noqa: E402

# bin/wiim has no .py extension: load it as a module explicitly.
import importlib.machinery  # noqa: E402
import importlib.util  # noqa: E402

_loader = importlib.machinery.SourceFileLoader(
    "wiim", os.path.join(ROOT, "bin", "wiim"))
_spec = importlib.util.spec_from_loader("wiim", _loader)
wiim = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wiim)


class CliTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = fixture_server.FixtureServer().start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()

    def setUp(self):
        # fresh state per test + point the client at the fixture
        self.srv.state = fixture_server.FixtureState()
        self.srv.httpd.state = self.srv.state
        os.environ["WIIM_BASE"] = self.srv.base
        self.dev = wiim.Device("127.0.0.1", timeout=2.0)


class TestStatus(CliTestCase):
    def test_full_snapshot_shape(self):
        snap = wiim.snapshot(self.dev, full=True)
        self.assertTrue(snap["online"])
        self.assertEqual(snap["device"]["name"], "Fixture Speakers")
        self.assertEqual(snap["device"]["presetKeys"], 12)
        self.assertEqual(len(snap["presets"]), 3)
        self.assertEqual(snap["eq"]["stat"], "Off")
        self.assertIn("wifi", [s["id"] for s in snap["sources"]])
        # optical disabled by getAudioInputEnable and not active -> hidden
        self.assertNotIn("optical", [s["id"] for s in snap["sources"]])

    def test_hex_meta_fallback(self):
        self.srv.state.title = "Old Dirt Roads"
        self.srv.state.artist = "Owen Riegling"
        snap = wiim.snapshot(self.dev, full=False)
        self.assertEqual(snap["meta"]["title"], "Old Dirt Roads")
        self.assertEqual(snap["meta"]["artist"], "Owen Riegling")

    def test_metainfo_preferred(self):
        self.srv.state.title = "Real Title"
        self.srv.state.artist = "Real Artist"
        self.srv.state.art = "https://art.example/a.jpg"
        snap = wiim.snapshot(self.dev, full=False)
        self.assertEqual(snap["meta"]["artUrl"], "https://art.example/a.jpg")

    def test_fast_snapshot_omits_heavy_sections(self):
        snap = wiim.snapshot(self.dev, full=False)
        self.assertNotIn("presets", snap)
        self.assertNotIn("device", snap)


class TestActions(CliTestCase):
    def test_toggle_roundtrip(self):
        self.dev.transport("onepause")
        self.assertEqual(self.srv.state.status, "play")
        self.dev.transport("onepause")
        self.assertEqual(self.srv.state.status, "pause")

    def test_volume(self):
        self.dev.set_volume(55)
        self.assertEqual(self.srv.state.vol, 55)
        self.dev.set_volume(999)
        self.assertEqual(self.srv.state.vol, 100)

    def test_mute(self):
        self.dev.set_mute(True)
        self.assertEqual(self.srv.state.mute, "1")

    def test_loop_modes(self):
        self.dev.set_loop("shuffle")
        self.assertEqual(wiim.snapshot(self.dev, False)["player"]["loop"],
                         "shuffle")
        self.dev.set_loop("sequence")
        self.assertEqual(wiim.snapshot(self.dev, False)["player"]["loop"],
                         "sequence")

    def test_preset(self):
        self.dev.preset(1)
        st = self.srv.state
        self.assertEqual(st.title, "Radio Paradise")
        self.assertEqual(st.status, "play")
        with self.assertRaises(wiim.WiimError):
            self.dev.preset(13)

    def test_sleep_timer(self):
        self.dev.sleep_timer(1800)
        self.assertEqual(self.srv.state.shutdown, 1800)
        self.dev.sleep_timer(None)
        self.assertEqual(self.srv.state.shutdown, -1)
        with self.assertRaises(wiim.WiimError):
            self.dev.sleep_timer(0)  # 0 would power off the device

    def test_source_switch(self):
        self.dev.set_source("bluetooth")
        snap = wiim.snapshot(self.dev, full=True)
        self.assertEqual(snap["player"]["source"], "bluetooth")

    def test_seek(self):
        self.dev.seek(90)
        self.assertEqual(self.srv.state.curpos, 90000)

    def test_eq(self):
        self.dev.eq_load("Rock")
        self.assertEqual(self.srv.state.eqstat, "On")
        self.dev.eq_off()
        self.assertEqual(self.srv.state.eqstat, "Off")


class TestPlayUrl(CliTestCase):
    def test_play_url(self):
        self.dev.play_url("http://127.0.0.1:9/f/Artist/Album/01.mp3")
        self.assertEqual(self.srv.state.status, "play")
        self.assertIn("/f/", self.srv.state.playing_url)

    def test_play_playlist_hex(self):
        self.dev.play_playlist("http://127.0.0.1:9/pl/abc.m3u", 0)
        self.assertEqual(self.srv.state.status, "play")
        self.assertEqual(self.srv.state.plicount, 3)


class TestWatch(CliTestCase):
    def test_watch_emits_diffs(self):
        env = dict(os.environ, WIIM_BASE=self.srv.base)
        proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "bin", "wiim"),
             "--ip", "127.0.0.1", "watch", "--interval", "0.1"],
            stdout=subprocess.PIPE, text=True, env=env)
        try:
            line1 = json.loads(proc.stdout.readline())
            self.assertTrue(line1["online"])
            self.assertEqual(line1["player"]["status"], "none")
            # mutate device state behind the watcher
            self.srv.state.status = "play"
            self.srv.state.title = "Changed"
            line2 = json.loads(proc.stdout.readline())
            self.assertEqual(line2["player"]["status"], "play")
            self.assertEqual(line2["meta"]["title"], "Changed")
        finally:
            proc.terminate()
            proc.wait(timeout=5)


class TestDaemon(CliTestCase):
    def test_daemon_commands_and_events(self):
        env = dict(os.environ, WIIM_BASE=self.srv.base)
        proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "bin", "wiim"),
             "--ip", "127.0.0.1", "daemon", "--interval", "0.1"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env)

        def read_event():
            return json.loads(proc.stdout.readline())

        def send(obj):
            proc.stdin.write(json.dumps(obj) + "\n")
            proc.stdin.flush()

        try:
            hello = read_event()
            self.assertEqual(hello["event"], "hello")
            self.assertTrue(hello["serve"]["port"] > 0)
            state = read_event()
            self.assertEqual(state["event"], "state")

            send({"id": 7, "cmd": "toggle"})
            # command reply may interleave with state events
            for _ in range(10):
                msg = read_event()
                if msg.get("id") == 7:
                    break
            else:
                self.fail("no reply to daemon command")
            self.assertTrue(msg["ok"])
            self.assertEqual(self.srv.state.status, "play")

            send({"id": 8, "cmd": "bogus"})
            for _ in range(10):
                msg = read_event()
                if msg.get("id") == 8:
                    break
            self.assertFalse(msg["ok"])
            self.assertIn("unknown cmd", msg["error"])

            send({"id": 9, "cmd": "__shutdown__"})
            proc.wait(timeout=5)
            self.assertEqual(proc.returncode, 0)
        finally:
            if proc.poll() is None:
                proc.kill()


class TestLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "Artist", "Album A"))
        os.makedirs(os.path.join(self.tmp, "Artist", "Empty"))
        for name in ("02 second.flac", "01 first.mp3"):
            open(os.path.join(self.tmp, "Artist", "Album A", name),
                 "w").close()
        open(os.path.join(self.tmp, "Artist", ".hidden.mp3"), "w").close()
        open(os.path.join(self.tmp, "loose.ogg"), "w").close()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_scan_root(self):
        out = wiim.library_scan(self.tmp)
        self.assertEqual([d["name"] for d in out["dirs"]], ["Artist"])
        self.assertEqual([t["name"] for t in out["tracks"]], ["loose"])
        self.assertEqual(out["dirs"][0]["tracks"], 2)

    def test_scan_nested_sorted(self):
        out = wiim.library_scan(self.tmp, "Artist/Album A")
        self.assertEqual([t["name"] for t in out["tracks"]],
                         ["01 first", "02 second"])

    def test_traversal_guard(self):
        with self.assertRaises(wiim.WiimError):
            wiim.library_scan(self.tmp, "../etc")

    def test_album_tracks(self):
        tracks = wiim.album_tracks(self.tmp, "Artist/Album A")
        self.assertEqual(len(tracks), 2)
        self.assertTrue(tracks[0].startswith("Artist/Album A/01"))


class TestServe(CliTestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.payload = b"RIFF" + b"x" * 1000
        with open(os.path.join(self.tmp, "song.mp3"), "wb") as f:
            f.write(self.payload)
        self.srv_http = wiim.start_server(0, self.tmp)
        self.base = "http://127.0.0.1:%d" % self.srv_http.server_address[1]

    def tearDown(self):
        self.srv_http.shutdown()
        self.srv_http.server_close()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _get(self, path, headers=None):
        req = urllib.request.Request(self.base + path, headers=headers or {})
        with urllib.request.urlopen(req, timeout=2) as r:
            return r.status, r.read()

    def test_file_served(self):
        status, body = self._get("/f/song.mp3")
        self.assertEqual(status, 200)
        self.assertEqual(body, self.payload)

    def test_range(self):
        req = urllib.request.Request(self.base + "/f/song.mp3",
                                     headers={"Range": "bytes=4-8"})
        with urllib.request.urlopen(req, timeout=2) as r:
            self.assertEqual(r.status, 206)
            self.assertEqual(r.read(), b"xxxxx")

    def test_traversal_404(self):
        try:
            self._get("/f/../../etc/passwd")
            self.fail("expected 404")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)

    def test_no_listings(self):
        try:
            self._get("/")
            self.fail("expected 404")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)

    def test_playlist(self):
        token = self.srv_http.make_playlist(["song.mp3"])
        status, body = self._get("/pl/%s.m3u" % token)
        self.assertEqual(status, 200)
        self.assertIn(b"#EXTM3U", body)
        self.assertIn(b"/f/song.mp3", body)


class TestMediaRouter(CliTestCase):
    def test_routes_to_wiim_when_playing(self):
        self.srv.state.status = "play"
        self.srv.state.mode = "32"  # TIDAL Connect
        result = wiim.media_route("playPause", self.dev, "auto")
        self.assertEqual(result["target"], "wiim")
        self.assertEqual(self.srv.state.status, "pause")

    def test_falls_through_to_mpris(self):
        orig = wiim.mpris_status
        orig_run = wiim.subprocess_run
        wiim.mpris_status = lambda: {"playing": True, "identity": "brumm"}
        calls = []
        wiim.subprocess_run = lambda argv: calls.append(argv) or ""
        try:
            result = wiim.media_route("next", self.dev, "auto")
            self.assertEqual(result["target"], "mpris")
            self.assertEqual(calls, [["omarchy-shell", "media", "next"]])
        finally:
            wiim.mpris_status = orig
            wiim.subprocess_run = orig_run

    def test_idle_no_mpris_goes_to_wiim(self):
        orig = wiim.mpris_status
        wiim.mpris_status = lambda: {"playing": False}
        try:
            result = wiim.media_route("playPause", self.dev, "auto")
            self.assertEqual(result["target"], "wiim")
        finally:
            wiim.mpris_status = orig


class TestSignature(CliTestCase):
    def test_signature_ignores_position_drift(self):
        a = wiim.snapshot(self.dev, full=False)
        self.srv.state.curpos = 12345
        b = wiim.snapshot(self.dev, full=False)
        self.assertEqual(wiim.snapshot_signature(a),
                         wiim.snapshot_signature(b))

    def test_signature_tracks_status(self):
        a = wiim.snapshot(self.dev, full=False)
        self.srv.state.status = "play"
        b = wiim.snapshot(self.dev, full=False)
        self.assertNotEqual(wiim.snapshot_signature(a),
                            wiim.snapshot_signature(b))


if __name__ == "__main__":
    unittest.main()
