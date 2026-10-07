"""Reserve unique sessions atomically; publish only validated recordings."""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import os


@dataclass
class Reservation:
    final: Path
    partial: Path
    lock: Path

    def release(self):
        self.lock.unlink(missing_ok=True)

    def publish(self):
        # Windows rename fails if the destination exists. No replace/overwrite.
        if os.name == 'nt':
            os.rename(self.partial, self.final)
        else:
            os.link(self.partial, self.final)
            self.partial.unlink()


def reserve(folder, now=None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stem = (now or datetime.now()).strftime('PulseCapture_%Y-%m-%d_%H%M%S')
    for index in range(10000):
        suffix = f'_{index:03d}' if index else ''
        final = folder / f'{stem}{suffix}.mp4'
        partial = folder / f'{stem}{suffix}.partial.mp4'
        lock = folder / f'{stem}{suffix}.lock'
        try:
            with lock.open('x'):
                pass
        except FileExistsError:
            continue
        if final.exists() or partial.exists():
            lock.unlink()
            continue
        return Reservation(final, partial, lock)
    raise OSError('Too many recordings share this timestamp.')
