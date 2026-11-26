"""Discover local OpenType families and stage exact files for libass. No network."""
from functools import lru_cache
import os
from pathlib import Path
import re
import shutil
import struct

BUNDLED = Path(__file__).resolve().parent.parent/'assets/fonts'

def safe_family(value):
    return isinstance(value, str) and 0 < len(value.strip()) <= 160 and not any(
        ord(c) < 32 or c in ',{}\\' for c in value)

def font_names(path):
    data = path.read_bytes()
    offsets = [0]
    if data[:4] == b'ttcf':
        count = struct.unpack_from('>I', data, 8)[0]
        if count > 64: return []
        offsets = struct.unpack_from('>'+str(count)+'I', data, 12)
    result = []
    for base in offsets:
        count = struct.unpack_from('>H', data, base+4)[0]
        if count > 256: continue
        names = {}
        for i in range(count):
            tag, checksum, offset, size = struct.unpack_from('>4sIII', data, base+12+i*16)
            if tag != b'name': continue
            _, records, strings = struct.unpack_from('>HHH', data, offset)
            if records > 4096: continue
            for n in range(records):
                platform, encoding, language, ident, length, start = struct.unpack_from('>HHHHHH', data, offset+6+12*n)
                if ident not in (1,2,16,17) or platform not in (0,1,3): continue
                value = data[offset+strings+start:offset+strings+start+length].decode(
                    'utf-16-be' if platform in (0,3) else 'mac_roman', errors='replace').strip()
                if ident not in names or language in (0,1033): names[ident] = value
        family = names.get(16, names.get(1, ''))
        if safe_family(family): result.append((family,names.get(17,names.get(2,''))))
    return result

@lru_cache(maxsize=1)
def installed_fonts():
    result = {}
    folders = [BUNDLED, Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts',
               Path(os.environ.get('LOCALAPPDATA',Path.home()))/'Microsoft/Windows/Fonts']
    for folder in folders:
        if not folder.is_dir(): continue
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() not in ('.ttf','.otf','.ttc'): continue
            try:
                if path.stat().st_size > 50*1024*1024: continue
                for family, style in font_names(path):
                    result.setdefault(family, []).append((str(path),style))
            except (OSError, ValueError, struct.error): continue
    return result

def resolve_family(family):
    fonts = installed_fonts()
    match = next((name for name in fonts if name.casefold()==family.casefold()), None)
    if match: return match
    return next((name for name in ('DejaVu Sans','Arial','Segoe UI') if name in fonts), 'DejaVu Sans')

def stage_family(family, folder):
    resolved = resolve_family(family)
    folder = Path(folder)/'fonts'
    folder.mkdir(exist_ok=True)
    for name, _ in installed_fonts().get(resolved, ()):
        path = Path(name)
        target = folder/path.name
        if not target.exists(): shutil.copyfile(path,target)
    return resolved, folder
