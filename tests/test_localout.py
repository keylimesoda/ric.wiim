"""Tests for local audio out: WAV framing, pactl parsing, live stream."""
import importlib.machinery
import importlib.util
import io
import json
import os
import struct
import sys
import threading
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "bin"))

_loader = importlib.machinery.SourceFileLoader(
    "wiim", os.path.join(ROOT, "bin", "wiim"))
_spec = importlib.util.spec_from_loader("wiim", _loader)
wiim = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wiim)


class WavHeaderTests(unittest.TestCase):
    def test_structure(self):
        h = wiim.build_wav_header()
        self.assertEqual(len(h), 44)
        self.assertEqual(h[0:4], b"RIFF")
        self.assertEqual(h[8:12], b"WAVE")
        data_size = 0x7FF00000
        self.assertEqual(struct.unpack("<I", h[4:8])[0], data_size + 36)
        self.assertEqual(struct.unpack("<I", h[40:44])[0], data_size)
        self.assertEqual(h[12:16], b"fmt ")
        self.assertEqual(struct.unpack("<I", h[16:20])[0], 16)
        self.assertEqual(struct.unpack("<H", h[20:22])[0], 1)      # PCM
        self.assertEqual(struct.unpack("<H", h[22:24])[0], 2)      # channels
        self.assertEqual(struct.unpack("<I", h[24:28])[0], 44100)  # rate
        self.assertEqual(struct.unpack("<I", h[28:32])[0], 176400)  # byterate
        self.assertEqual(struct.unpack("<H", h[32:34])[0], 4)      # block align
        self.assertEqual(struct.unpack("<H", h[34:36])[0], 16)     # bits
        self.assertEqual(h[36:40], b"data")

    def test_custom_params(self):
        h = wiim.build_wav_header(rate=48000, channels=1, bits=16)
        self.assertEqual(struct.unpack("<I", h[24:28])[0], 48000)
        self.assertEqual(struct.unpack("<I", h[28:32])[0], 96000)
        self.assertEqual(struct.unpack("<H", h[22:24])[0], 1)


class PactlParsingTests(unittest.TestCase):
    def test_index_ok(self):
        self.assertEqual(wiim.parse_pactl_index("536870916\n"), 536870916)

    def test_index_bad(self):
        for bad in ("", "nope\n", "  \n"):
            with self.assertRaises(wiim.WiimError):
                wiim.parse_pactl_index(bad)

    def test_sink_index(self):
        text = ("71\talsa_output.x\tPipeWire\ts32le 2ch 48000Hz\tRUNNING\n"
                "5511\twiim-out\tPipeWire\tfloat32le 2ch 48000Hz\tIDLE\n")
        self.assertEqual(wiim.parse_sink_index(text, "wiim-out"), 5511)
        self.assertIsNone(wiim.parse_sink_index(text, "missing"))

    def test_sink_input_ids(self):
        text = "12\t4\t0\n13\t5\t0\ngarbage line\n"
        self.assertEqual(wiim.parse_sink_input_ids(text), [12, 13])
        self.assertEqual(wiim.parse_sink_input_ids(""), [])

    def test_default_sink(self):
        text = ("Default Sample Specification: s16le 2ch 44100Hz\n"
                "Default Sink: alsa_output.pci.hdmi\n"
                "Default Source: alsa_input.x\n")
        self.assertEqual(wiim.parse_default_sink(text), "alsa_output.pci.hdmi")
        self.assertEqual(wiim.parse_default_sink("nope"), "")

    def test_null_module_indices(self):
        text = ("42\tmodule-null-sink\tsink_name=wiim-out sink_properties=x\t\n"
                "43\tmodule-null-sink\tsink_name=other-out\t\n"
                "44\tmodule-loopback\t\t\n")
        self.assertEqual(wiim.parse_null_module_indices(text, "wiim-out"), [42])
        self.assertEqual(wiim.parse_null_module_indices("", "wiim-out"), [])


class _SlowPipe:
    """File-like: yields one chunk, then blocks until released."""

    def __init__(self, first_chunk, release_event):
        self.first = first_chunk
        self.release = release_event
        self.sent = threading.Event()

    def read(self, n):
        if not self.sent.is_set():
            self.sent.set()
            return self.first[:n]
        self.release.wait(timeout=5)
        return b""


class LiveStreamTests(unittest.TestCase):
    def setUp(self):
        self.srv = wiim.LiveServer(("127.0.0.1", 0), wiim.LiveHandler)
        self.srv.pcm = io.BytesIO(b"A" * wiim.LIVE_WAV_CHUNK * 3)
        self.srv.stream_lock = threading.Lock()
        self.thread = threading.Thread(target=self.srv.serve_forever,
                                       daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:%d" % self.srv.server_address[1]

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.thread.join(timeout=5)

    def test_live_wav_body(self):
        with urllib.request.urlopen(self.base + "/live.wav", timeout=5) as r:
            self.assertEqual(r.status, 200)
            self.assertEqual(r.headers["Content-Type"], "audio/wav")
            body = r.read()
        self.assertEqual(body, wiim.build_wav_header()
                         + b"A" * wiim.LIVE_WAV_CHUNK * 3)

    def test_other_paths_404(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(self.base + "/f/x.mp3", timeout=5)
        self.assertEqual(cm.exception.code, 404)

    def test_second_client_gets_503(self):
        ev = threading.Event()
        self.srv.pcm = _SlowPipe(b"B" * wiim.LIVE_WAV_CHUNK, ev)
        results = {}

        def first():
            try:
                with urllib.request.urlopen(self.base + "/live.wav",
                                            timeout=5) as r:
                    results["a"] = r.read()
            except Exception as e:  # noqa: BLE001
                results["a"] = repr(e)

        t = threading.Thread(target=first, daemon=True)
        t.start()
        # wait until the first stream is mid-flight
        for _ in range(50):
            if self.srv.stream_lock.locked():
                break
            threading.Event().wait(0.05)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(self.base + "/live.wav", timeout=5)
        self.assertEqual(cm.exception.code, 503)
        ev.set()
        t.join(timeout=5)


class FirewallHelperTests(unittest.TestCase):
    def test_ports_ordered(self):
        self.assertLess(wiim.SERVE_PORT_DEFAULT, wiim.LOCALOUT_PORT_DEFAULT)


if __name__ == "__main__":
    unittest.main()
