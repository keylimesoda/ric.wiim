# ric.wiim — design record

Omarchy-native WiiM controller: a Quattro bar-widget plugin with a
keyboard-driven control panel, backed by a stdlib-only Python CLI/daemon.

## Decisions (settled with the user, 2026-10-16)

- Target device: **WiiM Pro Receiver "Play Room Speakers" @ 192.168.1.50 (LAN)**
  (pinned as default; `--ip` + SSDP discovery supported for the future).
- **No global keybinding** by default; README documents how to bind
  `omarchy-shell shell toggle ric.wiim`.
- **Media keys: smart route** — XF86 keys go to the WiiM only when it is
  the active/playing source, else fall through to the built-in MPRIS media
  service (`omarchy-shell media …`).
- Scope: **full kit** — transport, seek, volume/mute, 12 presets, sources,
  EQ presets, sleep timer, device info, **local library streaming** and
  **Tidal Connect / Spotify Connect control** (transport + metadata of
  streams pushed to the device). "Correct, performant, clean, gorgeous."

## Prior art (surveyed)

- Built-in `omarchy.media` service: MPRIS-only; WiiM is not MPRIS → own widget.
- `chriopter.brumm` (installed): now-playing bar widget pattern.
- `ric.daikin` (user's own plugin + CLI): the house pattern —
  `Panel` entry point, `KeyboardPanel` + `PanelKeyCatcher` cursor model,
  pure `Model.js`, external JSON CLI (`~/.local/bin/daikin`), settings
  schema in manifest. This project deliberately follows it.
- `tech.greyforge.reprieve`: `pluginDir` via `Qt.resolvedUrl(".")` for
  bundled `bin/` helpers → self-contained plugin.
- API sources: official *HTTP API for WiiM Products v1.2* PDF (downloaded,
  `docs/wiim-httpapi-v1.2.txt`), `cvdlinden/wiim-httpapi`,
  `mjcumming/pywiim` (MIT; discovered-apis doc). All commands verified
  live against the device on 2026-10-16.

## Surface & kinds

- Plugin id `ric.wiim`, kinds: `bar-widget` (single entry point
  `BarWidget.qml` deriving from `qs.Ui.Panel`, like ric.daikin).
- The bar widget is persistent → state + daemon live in the widget
  instance; its `IpcHandler` (target `ric.wiim`) works while the popout is
  closed (media router + external control). Single monitor, single device:
  no separate `service` kind needed (matches house style; revisit if a
  second monitor or device switcher appears).

## State ownership

- Widget instance owns: live snapshot, daemon process, cursor/open state.
- `bin/wiim daemon` owns: device polling (`watch`, 0.5 s diff stream),
  local file server (library playback), command execution.
- Durable config: widget settings in `shell.json` layout entry
  (`deviceIp`, `musicDir`, `volStep`, `pollMs`, `fixture`), CLI config at
  `~/.config/wiim/config.json` (CLI-only use).

## External surface (named explicitly)

- `bin/wiim` — Python 3 stdlib only. HTTPS GET to `https://<ip>/httpapi.asp`
  (self-signed cert: unverified TLS; LAN device, no credentials involved).
- Local HTTP file server (library playback): binds `0.0.0.0:7401`
  (fixed, firewall-friendly), serves only files under `musicDir`,
  Range support, no dotfiles, no listings over HTTP. Documented in README.
- Desktop audio out (`wiim localout`, experimental): creates a PipeWire
  null sink via `pactl`, captures its monitor with `pw-cat`, and serves
  an endless lossless WAV on `0.0.0.0:7402` (`/live.wav`, HTTP/1.0
  close-delimited — what the player's Lavf client accepts). Full
  teardown on exit restores the previous default sink and unloads the
  module. Needs one documented ufw rule; no sudo from the plugin.
- `omarchy-shell media status|playPause|next|previous` (media router only).
- No sudo, no credentials, no cloud APIs.

## IPC contract (target `ric.wiim`)

`open/close/show/hide/toggle`, `playPause/next/previous/stop`,
`volSet(v)/volStep(±n)/mute(on|off|toggle)`, `preset(n)`, `source(id)`,
`eq(name)/eqOn/eqOff`, `seek(sec)`, `loop(mode)`, `sleep(sec|off)`,
`playPath(rel)/playUrl(url)/playAlbum(rel)`, `library(path)`, `status()`,
`refresh()`, `discover()`. Bounded JSON results; no credentials.

## States (kept distinct)

`no-config` (no IP and discovery empty) · `discovering` · `offline`
(configured IP unreachable) · `connecting` · `ready` (idle/playing/paused
substates) · `empty-presets` · `empty-library` · `failed` (last action
error) · `fixture` (prototype/demo mode).

## Verification plan

1. `tests/fixture_server.py`: stdlib WiiM emulator (httpapi.asp subset) →
   `tests/test_cli.py` unit tests (status merge, actions, watch diff,
   library, serve Range, media routing rules).
2. `Model.js` pure helpers tested with node.
3. QML: omabox box with `--plugin`, fixture mode, screenshots per state
   (prototype loop), then live daemon against the real device (low volume,
   stop playback afterwards).
4. Live install on the user's bar + `omarchy-shell` IPC checks.

## Deferred (documented, not silently dropped)

- Multi-room grouping / stereo pair: firmware returns `unknown command`
  for zone commands (verified); revisit with more devices.
- Queue browsing: `getPlayQueueInfo` unsupported on this firmware.
- Tidal *search/login*: cloud-account APIs need credentials — out of scope.
  Tidal Connect streams are controlled (transport/metadata) once pushed.
- MPRIS bridge (expose WiiM to the built-in media widget): possible later.
- Desktop-out transport history (2026-10-17): Bluetooth A2DP rejected by
  the user (lossy; pairing dance). AirPlay considered — the Receiver
  enforces FairPlay (plain RAOP ANNOUNCE → 403; SETUP phase 2 ignored),
  and no mature open-source Linux AirPlay *sender* exists (airplay2-rs
  is alpha). The player's own HTTP client (Lavf) accepts an endless
  lossless WAV stream instead — chosen. The earlier "AP client
  isolation" diagnosis was wrong: the host's ufw (default-deny input)
  was blocking inbound fetches all along.
