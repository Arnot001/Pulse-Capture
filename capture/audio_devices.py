"""Discover DirectShow inputs. Enumeration is not a claim that recording succeeded."""
from dataclasses import dataclass
import re
from .ffmpeg_backend import run
from .wasapi_loopback import DEVICE_ID, discover_default, list_playback_devices


@dataclass(frozen=True)
class AudioDevice:
    name: str
    identifier: str
    kind: str


@dataclass(frozen=True)
class AudioInventory:
    devices: tuple[AudioDevice, ...] = ()
    notice: str = ''

    @property
    def microphones(self):
        return tuple(d for d in self.devices if d.kind == 'input')

    @property
    def loopbacks(self):
        return tuple(d for d in self.devices if d.kind == 'loopback')


def classify(name):
    # Conservative known names only. Do not label every sound input as loopback.
    loopback = ('stereo mix', 'stereomix', 'what u hear', 'what you hear',
                'wave out mix', 'waveout mix', 'virtual-audio-capturer', 'loopback')
    return 'loopback' if any(token in name.casefold() for token in loopback) else 'input'


def parse_devices(log):
    devices = []
    in_audio = False
    pending = None
    for line in log.splitlines():
        if 'DirectShow audio devices' in line:
            in_audio, pending = True, None
            continue
        if 'DirectShow video devices' in line:
            in_audio, pending = False, None
            continue
        alias = re.search(r'Alternative name "(.*)"', line)
        if alias:
            if pending is not None:
                d = devices[pending]
                devices[pending] = AudioDevice(d.name, alias[1], d.kind)
            pending = None
            continue
        match = re.search(r'\] "(.*)"(?: \((audio|video)\))?\s*$', line)
        if match:
            pending = None
            if match[2] == 'audio' or (match[2] is None and in_audio):
                devices.append(AudioDevice(match[1], match[1], classify(match[1])))
                pending = len(devices) - 1
    # Alternative identifiers keep identically named microphones distinct.
    return tuple(dict((d.identifier, d) for d in devices).values())


def discover_audio(backend):
    # The Windows playback endpoint is not a DirectShow recording input.
    # Report it separately only when a real WASAPI loopback can be opened.
    try:
        system = tuple(AudioDevice(name, identifier, 'loopback')
                       for identifier, name in list_playback_devices())
        wasapi_notice = ''
    except Exception as exc:
        system = ()
        wasapi_notice = str(exc)
    if backend.audio_supported:
        result = run([backend.ffmpeg, '-hide_banner', '-list_devices', 'true',
                      '-f', 'dshow', '-i', 'dummy'])
        devices = parse_devices(result.stderr)
    else:
        devices = ()
    if not devices and not system:
        notice = wasapi_notice or 'No audio devices found. Reconnect audio hardware.'
    elif not system:
        notice = 'Windows playback unavailable: ' + wasapi_notice
    elif not backend.audio_supported:
        notice = 'Windows playback available via WASAPI; microphone needs FFmpeg DirectShow.'
    else:
        notice = 'Windows playback uses WASAPI; microphone uses DirectShow when selected.'
    # Existing DirectShow "Stereo Mix" devices remain valid alternatives.
    return AudioInventory(system + devices, notice)
