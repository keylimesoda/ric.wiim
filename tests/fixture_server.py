#!/usr/bin/env python3
"""WiiM fixture server: emulates the httpapi.asp subset used by bin/wiim.

Stateful: transport/volume/mute/preset/EQ/sleep commands mutate the state
so tests can assert round-trips. Plain HTTP (tests set WIIM_BASE).
"""

import http.server
import json
import threading
import urllib.parse

HEX = lambda s: s.encode("utf-8").hex()  # noqa: E731


class FixtureState:
    def __init__(self):
        self.status = "none"
        self.mode = "-1"
        self.loop = "4"
        self.vol = 40
        self.mute = "0"
        self.curpos = 0
        self.totlen = 0
        self.plicount = 0
        self.plicurr = 0
        self.title = "Unknown"
        self.artist = "Unknown"
        self.album = "Unknown"
        self.art = ""
        self.eqstat = "Off"
        self.shutdown = 0
        self.playing_url = None
        self.playlist = None
        self.presets = [
            {"number": 1, "name": "Radio Paradise", "source": "RadioParadise",
             "url": "http://stream.radioparadise.com/flacm", "picurl": ""},
            {"number": 2, "name": "BBC Radio Norfolk", "source": "Linkplay Radio",
             "url": "http://example.org/bbc.m3u8", "picurl": ""},
            {"number": 5, "name": "My Mix", "source": "TIDAL",
             "url": "unknow", "picurl": ""},
        ]
        self.eq_list = ["Flat", "Rock", "Jazz", "Vocal Booster"]

    def player_json(self):
        return {
            "type": "0", "ch": "0", "mode": self.mode, "loop": self.loop,
            "eq": "0", "vendor": "", "status": self.status,
            "curpos": str(self.curpos), "offset_pts": str(self.curpos),
            "totlen": str(self.totlen), "alarmflag": "0",
            "plicount": str(self.plicount), "plicurr": str(self.plicurr),
            "vol": str(self.vol), "mute": self.mute,
            "Title": HEX(self.title), "Artist": HEX(self.artist),
            "Album": HEX(self.album),
        }


class FixtureHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/httpapi.asp":
            self.send_error(404)
            return
        cmd = urllib.parse.parse_qs(parsed.query).get("command", [""])[0]
        st = self.server.state
        body = self.route(st, cmd)
        data = body if isinstance(body, str) else json.dumps(body)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data.encode())

    def route(self, st, cmd):
        if cmd == "getStatusEx":
            return {"ssid": "Fixture Speakers", "DeviceName": "Fixture Speakers",
                    "GroupName": "Fixture Speakers", "project": "WiiM_Pro_Fixture",
                    "firmware": "Linkplay.fixture", "uuid": "FIXTURE0001",
                    "MAC": "AA:BB:CC:DD:EE:FF", "group": "0", "preset_key": "12",
                    "internet": "1"}
        if cmd == "getPlayerStatus":
            return st.player_json()
        if cmd == "getMetaInfo":
            if st.title == "Unknown":
                return "Failed"
            return {"metaData": {"title": st.title, "artist": st.artist,
                                 "album": st.album, "albumArtURI": st.art,
                                 "sampleRate": "44100", "bitDepth": "16"}}
        if cmd == "getPresetInfo":
            return {"preset_num": len(st.presets), "preset_list": st.presets}
        if cmd == "EQGetList":
            return st.eq_list
        if cmd == "EQGetStat":
            return {"EQStat": st.eqstat}
        if cmd == "getNewAudioOutputHardwareMode":
            return {"hardware": "3", "source": "0", "audiocast": "0"}
        if cmd == "getShutdown":
            return str(st.shutdown)
        if cmd == "getAudioInputCapbility":
            return {"ver": "1.0", "audioInput": [
                {"mode": "wifi"}, {"mode": "bluetooth"},
                {"mode": "line-in"}, {"mode": "optical"}]}
        if cmd == "getAudioInputEnable":
            return {"ver": "1.0", "audioInput": [
                {"mode": "wifi", "enable": 1}, {"mode": "bluetooth", "enable": 1},
                {"mode": "line-in", "enable": 1}, {"mode": "optical", "enable": 0}]}
        if cmd == "getModeRename":
            return "Failed"

        if cmd.startswith("setPlayerCmd:"):
            rest = cmd[len("setPlayerCmd:"):]
            parts = rest.split(":")
            action = parts[0]
            if action == "onepause":
                st.status = "pause" if st.status == "play" else "play"
                if st.status == "play" and st.mode == "-1":
                    st.mode = "10"
            elif action == "pause":
                st.status = "pause"
            elif action == "resume":
                st.status = "play"
            elif action == "stop":
                st.status = "stop"
            elif action == "play":
                st.playing_url = rest[len("play:"):]
                st.status = "play"
                st.mode = "10"
                st.title, st.artist = "Stream", "Internet"
                st.totlen = 0
            elif action == "hex_playlist":
                url = bytes.fromhex(parts[1]).decode()
                st.playlist = url
                st.status = "play"
                st.mode = "10"
                st.plicount = 3
                st.plicurr = int(parts[2]) if len(parts) > 2 else 0
                st.title, st.artist = "Track 1", "Fixture Artist"
                st.totlen = 240000
            elif action == "prev":
                st.plicurr = max(0, st.plicurr - 1)
            elif action == "next":
                st.plicurr = min(st.plicount, st.plicurr + 1)
            elif action == "seek":
                st.curpos = int(parts[1]) * 1000
            elif action == "vol":
                st.vol = max(0, min(100, int(parts[1])))
            elif action == "mute":
                st.mute = parts[1]
            elif action == "loopmode":
                code = {"-1": "0", "0": "4", "1": "1", "2": "2", "3": "3"}
                st.loop = code.get(parts[1], "4")
            elif action == "switchmode":
                st.mode = {"wifi": "10", "bluetooth": "41", "line-in": "40",
                           "optical": "43", "udisk": "11"}.get(parts[1], "10")
            else:
                return "unknown command"
            return "OK"

        if cmd.startswith("MCUKeyShortClick:"):
            n = int(cmd.split(":")[1])
            for p in st.presets:
                if p["number"] == n:
                    st.title, st.artist, st.album = p["name"], p["source"], ""
                    st.status = "play"
                    st.mode = "10"
                    st.totlen = 0
                    return "OK"
            return "Failed"

        if cmd.startswith("EQLoad:"):
            name = cmd[len("EQLoad:"):]
            if name in st.eq_list:
                st.eqstat = "On"
                return {"status": "OK"}
            return {"status": "Failed"}
        if cmd == "EQOn":
            st.eqstat = "On"
            return {"status": "OK"}
        if cmd == "EQOff":
            st.eqstat = "Off"
            return {"status": "OK"}
        if cmd.startswith("setShutdown:"):
            st.shutdown = int(cmd.split(":")[1])
            return {"status": "OK"}

        return "unknown command"


class FixtureServer:
    def __init__(self, port=0):
        self.state = FixtureState()
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port),
                                                     FixtureHandler)
        self.httpd.state = self.state
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)

    @property
    def base(self):
        host, port = self.httpd.server_address
        return "http://%s:%d" % (host, port)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8077
    srv = FixtureServer(port).start()
    print("fixture on %s" % srv.base)
    threading.Event().wait()
