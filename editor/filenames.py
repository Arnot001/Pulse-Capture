"""Reserve a new edit without touching the original or any previous export."""
from pathlib import Path
import re
from capture.filenames import Reservation


def reserve_export(source, folder=None):
    source = Path(source).resolve()
    folder = Path(folder).resolve() if folder else source.parent
    folder.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', source.stem)[:120].rstrip(' .') or 'Video'
    for number in range(10000):
        suffix = f'_{number:03d}' if number else ''
        final = folder / f'{stem}_trimmed{suffix}.mp4'
        partial = final.with_suffix('.partial.mp4')
        lock = final.with_suffix('.lock')
        try:
            with lock.open('x'):
                pass
        except FileExistsError:
            continue
        if final.exists() or partial.exists() or final == source:
            lock.unlink()
            continue
        return Reservation(final, partial, lock)
    raise OSError('There are too many exports with this filename. Choose another folder.')
