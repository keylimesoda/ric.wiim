"""Tests for local audio out: WAV framing, pactl parsing, live stream."""
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import struct
import sys
import threading
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest import mock
from types import SimpleNamespace

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


class CaptureTests(unittest.TestCase):
    def test_pulse_monitor_capture(self):
        command = wiim.localout_capture_command("fixture-sink")
        self.assertEqual(command[command.index("--device") + 1], "fixture-sink.monitor")
        self.assertEqual(command[command.index("--format") + 1], "s16le")
        self.assertEqual(command[command.index("--rate") + 1], "44100")

    def test_capture_ready_preserves_first_pcm(self):
        with tempfile.TemporaryFile() as errors:
            proc = subprocess.Popen([sys.executable, "-c",
                                     "import os; os.write(1, b'PCM!')"],
                                    stdout=subprocess.PIPE, stderr=errors)
            try:
                self.assertEqual(wiim.capture_first_pcm(proc, errors), b"PCM!")
            finally:
                proc.wait(timeout=5)
                proc.stdout.close()

    def test_capture_failure_reports_stderr(self):
        with tempfile.TemporaryFile() as errors:
            proc = subprocess.Popen([sys.executable, "-c",
                                     "import sys; sys.stderr.write('missing target')"],
                                    stdout=subprocess.PIPE, stderr=errors)
            try:
                with self.assertRaisesRegex(wiim.WiimError, "missing target"):
                    wiim.capture_first_pcm(proc, errors)
            finally:
                proc.wait(timeout=5)
                proc.stdout.close()

    def test_capture_timeout(self):
        with tempfile.TemporaryFile() as errors:
            with mock.patch.object(wiim.select, "select", return_value=([], [], [])):
                with self.assertRaisesRegex(wiim.WiimError, "produced no audio data"):
                    wiim.capture_first_pcm(mock.Mock(), errors, timeout=0)


class AudioToolsTests(unittest.TestCase):
    def test_missing_tools_offer_native_install(self):
        with mock.patch.object(wiim.shutil, "which", side_effect=lambda n:
                               None if n in ("pactl", "parec") else "found"), \
             mock.patch.object(wiim, "native_setup_available", return_value=True):
            self.assertEqual(wiim.audio_tools_status(), {
                "ready": False, "missing": ["pactl", "parec"], "canInstall": True,
                "canSetupFirewall": True})

    def test_present_tools_do_not_install(self):
        with mock.patch.object(wiim.shutil, "which", return_value="found"), \
             mock.patch.object(wiim, "run_native_admin") as run, \
             mock.patch("builtins.print"):
            self.assertEqual(wiim.install_audio_tools(), 0)
            run.assert_not_called()

    def test_install_only_escalates_system_package_manager(self):
        with mock.patch.object(wiim, "audio_tools_status", return_value={
                "ready": False, "canInstall": True}), \
             mock.patch.object(wiim, "run_native_admin", return_value=0) as run:
            self.assertEqual(wiim.install_audio_tools(), 0)
            self.assertEqual(run.call_args.args[0], [
                "/usr/bin/pacman", "-S", "--needed", "--noconfirm", "libpulse"])

    def test_unsupported_system_does_not_invoke_installer(self):
        with mock.patch.object(wiim, "audio_tools_status", return_value={
                "ready": False, "canInstall": False}), \
             mock.patch.object(wiim, "run_native_admin") as run, \
             mock.patch("builtins.print"):
            self.assertEqual(wiim.install_audio_tools(), 1)
            run.assert_not_called()


class FirewallSetupTests(unittest.TestCase):
    def invoke(self, config="ENABLED=yes", rules="", code=0):
        with mock.patch.object(wiim, "native_setup_available", return_value=True), \
             mock.patch("builtins.open", side_effect=[io.StringIO(config), io.StringIO(rules), io.StringIO('DEFAULT_INPUT_POLICY="DROP"')]), \
             mock.patch.object(wiim.subprocess, "run", return_value=SimpleNamespace(
                 returncode=code, stdout="", stderr="denied")) as run, \
             mock.patch("builtins.print") as output:
            result = wiim.setup_firewall("192.0.2.8", 17402)
            return result, run.call_args_list, output.call_args_list

    def test_native_authentication_adds_only_scoped_rule(self):
        result, calls, _ = self.invoke()
        self.assertEqual(result, 0)
        self.assertEqual(calls[0].args[0], [
            "/usr/bin/pkexec", "--disable-internal-agent", "/usr/bin/ufw",
            "allow", "from", "192.0.2.8", "to", "any", "port", "17402",
            "proto", "tcp", "comment", "ric.wiim desktop audio"])
        self.assertEqual(len(calls), 1)

    def test_cancel_reports_no_change(self):
        result, _, output = self.invoke(code=126)
        self.assertEqual(result, 1)
        self.assertIn("Authorization canceled", str(output))

    def test_missing_agent_reports_no_terminal_fallback(self):
        result, _, output = self.invoke(code=127)
        self.assertEqual(result, 1)
        self.assertIn("Polkit agent", str(output))

    def test_inactive_or_existing_rule_does_not_prompt(self):
        for config, rules in [("ENABLED=no", ""),
                              ("ENABLED=yes", "-A ufw-user-input -p tcp --dport 17402 -s 192.0.2.8 -j ACCEPT")]:
            _, calls, _ = self.invoke(config=config, rules=rules)
            self.assertEqual(calls, [])

    def test_invalid_destination_or_port_never_escalates(self):
        for ip, port in [("--help", 7402), ("192.0.2.8", 22), ("192.0.2.8", 65536)]:
            with mock.patch.object(wiim.subprocess, "run") as run:
                with self.assertRaises(wiim.WiimError):
                    wiim.setup_firewall(ip, port)
                run.assert_not_called()


class AudioPreflightTests(unittest.TestCase):
    def check(self, config="ENABLED=yes", rules="", defaults='DEFAULT_INPUT_POLICY="DROP"'):
        files = {"/etc/ufw/ufw.conf": config, "/etc/ufw/user.rules": rules,
                 "/etc/default/ufw": defaults}
        with mock.patch("builtins.open", side_effect=lambda path: io.StringIO(files[path])):
            return wiim.firewall_preflight("192.0.2.8", 7402)

    def test_missing_rule_is_detected_locally(self):
        self.assertEqual(self.check(), "needs-rule")

    def test_allowances_cover_single_player_subnet_and_port_range(self):
        for rule in ["-A ufw-user-input -p tcp --dport 7402 -s 192.0.2.8 -j ACCEPT",
                     "-A ufw-user-input -p tcp --dport 7401:7402 -s 192.0.2.0/24 -j ACCEPT",
                     "-A ufw-user-input -p tcp --dport 7402 -j ACCEPT"]:
            self.assertEqual(self.check(rules=rule), "allowed")

    def test_other_players_and_ports_do_not_count(self):
        for rule in ["-A ufw-user-input -p tcp --dport 7402 -s 192.0.2.9 -j ACCEPT",
                     "-A ufw-user-input -p tcp --dport 7401 -s 192.0.2.8 -j ACCEPT",
                     "-A ufw-user-input -p tcp -m multiport --dports 22,80,443 -j ACCEPT"]:
            self.assertEqual(self.check(rules=rule), "needs-rule")

    def test_inactive_permissive_and_unknown_configuration(self):
        self.assertEqual(self.check(config="ENABLED=no"), "inactive")
        self.assertEqual(self.check(defaults='DEFAULT_INPUT_POLICY="ACCEPT"'), "allowed")
        self.assertEqual(self.check(config="unexpected"), "unknown")
        with mock.patch("builtins.open", side_effect=PermissionError):
            self.assertEqual(wiim.firewall_preflight("192.0.2.8", 7402), "unknown")

    def test_preflight_does_not_query_player_or_request_privilege(self):
        with mock.patch.object(wiim, "audio_tools_status", return_value={"ready": True}), \
             mock.patch.object(wiim, "firewall_preflight", return_value="allowed"), \
             mock.patch.object(wiim, "Device") as device, \
             mock.patch.object(wiim.subprocess, "run") as command:
            check = wiim.audio_preflight("192.0.2.8", 7402)
            self.assertEqual(check["firewall"], "allowed")
            device.assert_not_called()
            command.assert_not_called()


class LocalAudioMetadataTests(unittest.TestCase):
    def test_live_url_normalized_in_backend(self):
        for meta, player in [({"title": "http://192.0.2.10:7402/live.wav"}, {}),
                             ({}, {"Title": "http://192.0.2.10:17402/live.wav".encode().hex()})]:
            value = wiim.normalize_meta(meta, player)
            self.assertEqual(value["title"], "Local audio")

    def test_library_file_is_still_a_normal_track(self):
        title = "http://192.0.2.10:7401/f/live.wav"
        self.assertEqual(wiim.normalize_meta({"title": title}, {})["title"], title)


class LocaloutLifecycleTests(unittest.TestCase):
    def run_localout(self, capture_script, connect=True, cancel_before_route=False):
        calls = []
        signal_handlers = {}
        clients = []
        current_sink = "10"
        dev = mock.Mock()
        dev.player_status.return_value = {"status": "play"}
        playing = threading.Event()
        self.progress = []

        def progress(state):
            self.progress.append(state)
            if state == "streaming": playing.set()

        def pactl(args):
            nonlocal current_sink
            calls.append(args)
            if args == ["set-default-sink", "fixture-out"]:
                current_sink = "20"  # WirePlumber may move streams automatically.
            if args == ["info"]:
                return "Default Sink: original-output\n"
            if args == ["load-module", "module-null-sink", "sink_name=fixture-out",
                        "sink_properties=device.description=WiiM_Out"]:
                return "123\n"
            if args == ["list", "short", "sinks"]:
                return "10\toriginal-output\n20\tfixture-out\n"
            if args == ["list", "short", "sink-inputs"]:
                return "30\t%s\tclient\n" % current_sink
            return ""

        def register(sig, handler):
            previous = signal_handlers.get(sig)
            signal_handlers[sig] = handler
            return previous

        def play_url(url):
            if not connect:
                return
            def pull():
                with urllib.request.urlopen(url, timeout=5) as response:
                    self.body = response.read(48)
                if not cancel_before_route: playing.wait(timeout=5)
                signal_handlers[wiim.signal.SIGTERM]()
            t = threading.Thread(target=pull)
            clients.append(t)
            t.start()
            if cancel_before_route: t.join(timeout=5)

        dev.play_url.side_effect = play_url
        dev.meta.return_value = {"url": "/live.wav"}
        args = SimpleNamespace(sink="fixture-out", port=0, timeout=1)
        # The URL must use the ephemeral port selected by the real HTTP server.
        real_server = wiim.LiveServer
        def server(address, handler):
            srv = real_server(address, handler)
            args.port = srv.server_address[1]
            return srv

        def play_actual_url(url):
            play_url(url.replace(":0/", ":%d/" % args.port))
        dev.play_url.side_effect = play_actual_url
        try:
            with mock.patch.object(wiim, "pactl", side_effect=pactl), \
                 mock.patch.object(wiim.shutil, "which", return_value="parec"), \
                 mock.patch.object(wiim, "resolve_ip", return_value="127.0.0.1"), \
                 mock.patch.object(wiim, "local_ip_for", return_value="127.0.0.1"), \
                 mock.patch.object(wiim, "Device", return_value=dev), \
                 mock.patch.object(wiim, "LiveServer", side_effect=server), \
                 mock.patch.object(wiim.signal, "signal", side_effect=register), \
                 mock.patch.object(wiim, "out_json"), \
                 mock.patch.object(wiim, "local_audio_event", side_effect=progress), \
                 mock.patch.object(wiim, "localout_capture_command", return_value=[
                     sys.executable, "-c", capture_script]):
                try:
                    wiim.cmd_localout(args)
                except wiim.WiimError as error:
                    return calls, dev, error
                return calls, dev, None
        finally:
            for client in clients:
                client.join(timeout=5)

    def test_routes_after_pull_and_restores_inputs(self):
        calls, dev, error = self.run_localout(
            "import os,time; os.write(1,b'PCM!'); time.sleep(30)")
        self.assertIsNone(error)
        self.assertEqual(self.progress, ["connecting", "buffering", "streaming"])
        self.assertEqual(self.body, wiim.build_wav_header() + b"PCM!")
        self.assertIn(["set-default-sink", "fixture-out"], calls)
        self.assertIn(["move-sink-input", "30", "20"], calls)
        self.assertIn(["move-sink-input", "30", "10"], calls)
        self.assertIn(["set-default-sink", "original-output"], calls)
        self.assertEqual(calls[-1], ["unload-module", "123"])
        dev.stop.assert_called_once()

    def test_cancel_after_http_connection_never_redirects_apps(self):
        calls, dev, error = self.run_localout(
            "import os,time; os.write(1,b'PCM!'); time.sleep(30)", cancel_before_route=True)
        self.assertIsNone(error)
        self.assertNotIn(["set-default-sink", "fixture-out"], calls)
        self.assertFalse(any(call[0] == "move-sink-input" for call in calls))
        self.assertEqual(calls[-1], ["unload-module", "123"])

    def test_capture_failure_never_redirects_apps(self):
        calls, dev, error = self.run_localout(
            "import sys; sys.stderr.write('capture failed')")
        self.assertIn("capture failed", str(error))
        self.assertNotIn(["set-default-sink", "fixture-out"], calls)
        self.assertFalse(any(call[0] == "move-sink-input" for call in calls))
        self.assertEqual(calls[-1], ["unload-module", "123"])
        dev.play_url.assert_not_called()

    def test_unreachable_player_never_redirects_apps(self):
        with mock.patch.object(wiim, "LOCALOUT_CONNECT_TIMEOUT", 0):
            calls, dev, error = self.run_localout(
                "import os,time; os.write(1,b'PCM!'); time.sleep(30)", connect=False)
        self.assertIn("WiiM did not connect", str(error))
        self.assertNotIn(["set-default-sink", "fixture-out"], calls)
        self.assertFalse(any(call[0] == "move-sink-input" for call in calls))
        self.assertEqual(calls[-1], ["unload-module", "123"])


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
