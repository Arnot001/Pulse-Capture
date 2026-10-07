from dataclasses import dataclass


@dataclass(frozen=True)
class Region:
    x: int
    y: int
    width: int
    height: int

    def validate(self):
        if self.width < 2 or self.height < 2:
            raise ValueError('Select an area at least 2 × 2 pixels.')


@dataclass(frozen=True)
class CaptureOptions:
    mode: str = 'screen'
    fps: int = 30
    quality: str = 'Standard'
    region: Region | None = None
    hwnd: int | None = None
    audio: tuple[str, ...] = ()

    def validate(self):
        if self.mode not in ('screen', 'window', 'region'):
            raise ValueError('Unknown capture mode.')
        if self.fps not in (30, 60) or self.quality not in ('Standard', 'High'):
            raise ValueError('Invalid recording quality or frame rate.')
        if self.mode == 'window' and (not self.hwnd or self.hwnd < 0):
            raise ValueError('Select a window first.')
        if self.mode == 'region' and self.region is None:
            raise ValueError('Select an area first.')
        if self.region:
            self.region.validate()
        if len(self.audio) > 2 or len(set(self.audio)) != len(self.audio):
            raise ValueError('Choose up to two different audio sources.')
        if any(not name.strip() or '\x00' in name for name in self.audio):
            raise ValueError('Invalid audio device.')
