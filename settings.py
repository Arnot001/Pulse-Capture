"""Versioned settings, defensive loading, atomic writes."""
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path


def default_output():
    return Path(os.environ.get('USERPROFILE', str(Path.home()))) / 'Videos' / 'Pulse Capture'


def settings_path():
    base = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local')))
    return base / 'Pulse Capture' / 'settings.json'


@dataclass
class Settings:
    version: int = 1
    fps: int = 30
    quality: str = 'Standard'
    microphone: bool = True
    system_audio: bool = True
    mic_device: str = ''
    system_device: str = ''
    hotkey: bool = False
    output_folder: str = ''

    @property
    def output(self):
        return Path(self.output_folder) if self.output_folder else default_output()


def load(path=None):
    result = Settings()
    try:
        raw = json.loads(Path(path or settings_path()).read_text(encoding='utf-8'))
        if not isinstance(raw, dict) or raw.get('version', 1) != 1:
            return result
        for key in ('microphone', 'system_audio', 'hotkey'):
            if type(raw.get(key)) is bool:
                setattr(result, key, raw[key])
        for key in ('mic_device', 'system_device', 'output_folder'):
            if isinstance(raw.get(key), str):
                setattr(result, key, raw[key])
        if type(raw.get('fps')) is int and raw['fps'] in (30, 60):
            result.fps = raw['fps']
        if raw.get('quality') in ('Standard', 'High'):
            result.quality = raw['quality']
    except (OSError, ValueError, TypeError):
        pass
    return result


def save(settings, path=None):
    target = Path(path or settings_path())
    target.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent,
                                         prefix='.settings-', suffix='.tmp', delete=False) as handle:
            name = handle.name
            json.dump(asdict(settings), handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, target)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)
