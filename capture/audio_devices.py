"""Discover DirectShow inputs. Enumeration is not a claim that recording succeeded."""
from dataclasses import dataclass
import re
from .ffmpeg_backend import run


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
    if not backend.audio_supported:
        return AudioInventory(notice='This FFmpeg build has no DirectShow audio support. Video capture is available.')
    result = run([backend.ffmpeg, '-hide_banner', '-list_devices', 'true', '-f', 'dshow', '-i', 'dummy'])
    # Device enumeration normally exits nonzero because dummy is not an input.
    devices = parse_devices(result.stderr)
    notice = '' if devices else 'No audio inputs were reported. Check Windows microphone permissions and reconnect devices.'
    return AudioInventory(devices, notice)
