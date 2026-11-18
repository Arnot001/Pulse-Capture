"""Local, content-addressed reaction assets. No network or executable recipes."""
from array import array
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import subprocess
import struct
import tempfile
import threading
import wave
from functools import lru_cache

from capture.ffmpeg_backend import process_options
from .sound_design import SFX as NEW_SFX, synthesize as synthesize_original

ASSETS = Path(__file__).resolve().parent.parent / 'assets'
SFX = {
    'comedy.boing': ('Boing', 'Comedy', .8),
    'comedy.pop': ('Cartoon pop', 'Comedy', .22),
    'comedy.squeak': ('Rubber squeak', 'Comedy', .6),
    'comedy.slide_whistle': ('Slide whistle', 'Comedy', 1.1),
    'reaction.record_scratch': ('Record scratch', 'Reactions', .65),
    'reaction.awkward_sting': ('Awkward sting', 'Reactions', 1.3),
    'reaction.buzzer': ('Buzzer', 'Reactions', .65),
    'cinematic.bass_impact': ('Bass impact', 'Cinematic', .9),
    'cinematic.boom': ('Dramatic boom', 'Cinematic', 1.6),
    'cinematic.riser': ('Suspense riser', 'Cinematic', 1.8),
    'transition.whoosh': ('Fast whoosh', 'Transitions', .45),
    'transition.reverse_whoosh': ('Reverse whoosh', 'Transitions', .65),
    'transition.glitch': ('Glitch zap', 'Transitions', .45),
    'reveal.ding': ('Ding', 'Reveals', .85),
    'reveal.cash': ('Cash register', 'Reveals', .9),
    'reveal.sparkle': ('Sparkle', 'Reveals', 1.2),
    'reveal.discovery': ('Discovery chime', 'Reveals', 1.4),
    'failure.trombone': ('Original sad brass sting', 'Failure', 1.6),
    'failure.descending': ('Descending tone', 'Failure', .9),
}
LEGACY_SFX = frozenset(SFX)
SFX.update(NEW_SFX)
EMOJI = {
    'emoji.skull': ('Skull', 'Reactions'), 'emoji.laugh': ('Laughing', 'Faces'),
    'emoji.cry': ('Crying', 'Faces'), 'emoji.shock': ('Shocked', 'Faces'),
    'emoji.heart': ('Heart', 'Symbols'), 'emoji.star': ('Star', 'Symbols'),
    'emoji.dog': ('Dog', 'Animals'), 'emoji.cat': ('Cat', 'Animals'),
    'emoji.bulb': ('Light bulb', 'Objects'), 'emoji.fire': ('Fire', 'Objects'),
    'emoji.alert': ('Warning', 'Alerts'), 'emoji.siren': ('Siren', 'Alerts'),
}
_LOCK = threading.RLock()
REACTION_CATEGORIES = ('WTF', 'Disbelief', 'Rage', 'Cringe', 'Laughing', 'Dramatic')
DETAIL_FIELDS = {'name': 80, 'artist': 120, 'source': 1000, 'licence': 1000,
                 'attribution': 1600, 'transcript': 500}


@lru_cache(maxsize=1)
def bundled_gifs():
    """Metadata only: never decode 64 animations merely to open a panel."""
    return {item['id']: item for item in json.loads((ASSETS/'reactions'/'catalogue.json').read_text(encoding='utf-8'))}


def library_root():
    return Path(os.environ.get('PULSE_REACTION_LIBRARY') or
                str(Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Pulse Capture' / 'reactions'))


def safe_id(value):
    if type(value) is not str or not re.fullmatch(r'[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+', value) or len(value) > 90:
        raise ValueError('Use a local library asset ID, not a path or URL.')
    return value


def inspect_gif(data):
    """Bound dimensions/frame work before handing compressed pixels to a decoder."""
    try:
        if data[:6] not in (b'GIF87a', b'GIF89a'):
            raise ValueError('Not a GIF file.')
        width, height, packed = struct.unpack_from('<HHB', data, 6)
        if not (1 <= width <= 1024 and 1 <= height <= 1024):
            raise ValueError('GIF dimensions must be at most 1024 pixels.')
        offset = 13 + (3*(2**((packed&7)+1)) if packed&128 else 0)
        delays, delay = [], .1
        def blocks(at):
            while True:
                size = data[at]
                at += 1
                if not size:
                    return at
                at += size
                if at > len(data):
                    raise ValueError('Truncated GIF data.')
        while offset < len(data):
            marker = data[offset]; offset += 1
            if marker == 0x3b:
                break
            if marker == 0x21:
                extension = data[offset]; offset += 1
                if extension == 0xf9:
                    if data[offset] != 4:
                        raise ValueError('Invalid GIF control block.')
                    delay = max(.02, struct.unpack_from('<H', data, offset+2)[0]/100)
                offset = blocks(offset)
            elif marker == 0x2c:
                x,y,w,h,flags = struct.unpack_from('<HHHHB',data,offset)
                if not (w and h and x+w<=width and y+h<=height):
                    raise ValueError('GIF frame extends beyond its canvas.')
                delays.append(delay); delay=.1
                if len(delays)>300 or width*height*len(delays)>64000000 or sum(delays)>15:
                    raise ValueError('GIF limit: 300 frames, 15 seconds, 64 million pixels.')
                offset += 9+(3*(2**((flags&7)+1)) if flags&128 else 0)
                if not 2<=data[offset]<=8:
                    raise ValueError('Invalid GIF compression size.')
                offset = blocks(offset+1)
            else:
                raise ValueError('Invalid GIF block.')
        if not delays or marker != 0x3b:
            raise ValueError('Incomplete GIF file.')
        return width,height,delays
    except (IndexError,struct.error) as exc:
        raise ValueError('Truncated GIF file.') from exc


def _atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def synthesize(asset_id, path):
    """Original layered oscillators, filtered noise and envelopes; deterministic PCM."""
    if asset_id in NEW_SFX:
        return synthesize_original(asset_id, path)
    duration = SFX[asset_id][2]
    rate = 48000
    rng = random.Random(asset_id)
    data = array('h')
    phase = noise = 0.
    for i in range(round(duration*rate)):
        t = i/rate
        u = t/duration
        white = rng.uniform(-1, 1)
        noise += .12*(white-noise)
        env = min(1, t/.006, (duration-t)/.025)
        freq, tone = 440., 0.
        if asset_id == 'comedy.boing':
            freq = 150 + 600*math.exp(-5*u) + 65*math.sin(50*t)*math.exp(-3*u)
        elif asset_id == 'comedy.pop':
            freq = 180 + 1600*math.exp(-18*u)
        elif asset_id == 'comedy.squeak':
            freq = 1200 + 600*math.sin(u*math.pi) + 180*math.sin(t*120)
        elif asset_id == 'comedy.slide_whistle':
            freq = 1800 - 1500*u
        elif asset_id == 'reaction.record_scratch':
            freq = 150+1600*abs(math.sin(t*18))*(1-u)
            tone = .65*white*math.sin(t*240)
        elif asset_id == 'reaction.awkward_sting':
            freq = 185
            tone = .4*math.sin(2*math.pi*196*t)+.25*math.sin(2*math.pi*277*t)
        elif asset_id == 'reaction.buzzer':
            freq = 95
            tone = .6*(1 if math.sin(2*math.pi*freq*t)>0 else -1)
        elif asset_id.startswith('cinematic.'):
            freq = 38+100*math.exp(-15*u) if 'riser' not in asset_id else 80+1300*u*u
            tone = (1-u)*noise*1.4 if 'riser' not in asset_id else noise*u*2
        elif asset_id.startswith('transition.'):
            freq = 150+2200*(1-u)
            tone = noise*3*math.sin(math.pi*u)**2
            if 'reverse' in asset_id:
                tone = noise*4*u*u
            if 'glitch' in asset_id:
                freq = (230, 890, 140, 1800)[int(t*32)%4]
                tone = white*.2 if int(t*90)%3 else 0
        elif asset_id.startswith('reveal.'):
            notes = (1046.5, 1318.5, 1568, 2093)
            index = min(3, int(u*4))
            freq = 1568 if 'ding' in asset_id else notes[index]
            tone = .35*math.sin(2*math.pi*freq*2.756*t)*math.exp(-7*(u% .25))
            if 'cash' in asset_id:
                tone += noise*1.5*math.exp(-30*u)
        elif 'trombone' in asset_id:
            freq = (233.08, 220, 207.65, 155.56)[min(3, int(u*4))]*(1-.025*math.sin(t*28))
        else:
            freq = 900-750*u
        phase += 2*math.pi*freq/rate
        harmonic = .15*math.sin(phase*2)+.08*math.sin(phase*3)
        decay = math.exp(-3*u) if any(s in asset_id for s in ('boing','pop','impact','boom','ding')) else 1
        wave_value = (.5*math.sin(phase)+harmonic+tone)*env*decay
        if 'whoosh' in asset_id:
            wave_value = tone*env
        sample = round(math.tanh(wave_value)*23500)
        data.extend((sample, sample))
    with wave.open(str(path), 'wb') as stream:
        stream.setparams((2, 2, rate, 0, 'NONE', 'not compressed'))
        stream.writeframes(data.tobytes())


class ReactionLibrary:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else library_root()

    def metadata(self, asset_id, kind=None):
        safe_id(asset_id)
        if asset_id in SFX:
            name, category, duration = SFX[asset_id]
            category = 'Failures' if category == 'Failure' else 'Reactions' if category == 'Reveals' else category
            if asset_id == 'cinematic.riser': category = 'Suspense'
            item = dict(id=asset_id, name=name, category=category, duration=duration, kind='sfx', suffix='.wav')
            item.update(artist='Pulse Capture', source='Original procedural sound design', licence='Pulse Original Media',
                        attribution='', licence_record='assets/licenses/PULSE_ORIGINAL_MEDIA.md')
        elif asset_id in EMOJI:
            name, category = EMOJI[asset_id]
            item = dict(id=asset_id, name=name, category=category, duration=0, kind='emoji', suffix='.png', width=256, height=256)
        elif asset_id in bundled_gifs():
            item = dict(bundled_gifs()[asset_id])
        else:
            try:
                path = self.root/(asset_id+'.json')
                if path.stat().st_size > 65536:
                    raise ValueError('Invalid library metadata.')
                item = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError) as exc:
                raise ValueError(f'Missing local asset: {asset_id}. Import it in the reaction library first.') from exc
            if type(item) is not dict or item.get('id') != asset_id or item.get('kind') not in ('gif', 'sfx') or item.get('suffix') not in ('.gif', '.wav'):
                raise ValueError('Invalid library metadata.')
        if kind and item['kind'] != kind:
            raise ValueError(f'{asset_id} is not a {kind} asset.')
        return item

    def resolve(self, asset_id, kind=None):
        item = self.metadata(asset_id, kind)
        if item['kind'] == 'emoji':
            path = ASSETS/'emoji'/(asset_id+'.png')
        elif asset_id in bundled_gifs():
            path = ASSETS/'reactions'/(asset_id+'.gif')
        else:
            path = self.root/(asset_id+item['suffix'])
            if path.resolve().parent != self.root.resolve():
                raise ValueError('Asset must remain inside the local library.')
            if asset_id in SFX and not path.exists():
                with _LOCK:
                    if not path.exists():
                        self.root.mkdir(parents=True, exist_ok=True)
                        fd, name = tempfile.mkstemp(dir=self.root, suffix='.wav')
                        os.close(fd)
                        try:
                            synthesize(asset_id, name)
                            os.replace(name, path)
                        finally:
                            Path(name).unlink(missing_ok=True)
        if not path.is_file():
            raise ValueError(f'Missing library file: {asset_id}. Reimport this asset.')
        return path

    def items(self, kind):
        values = [self.metadata(key) for key in (SFX if kind == 'sfx' else EMOJI if kind == 'emoji' else bundled_gifs() if kind == 'gif' else ())]
        for path in sorted(self.root.glob('import.*.json')):
            try:
                item = self.metadata(path.stem)
                if item['kind'] == kind:
                    values.append(item)
            except ValueError:
                continue
        categories = self.preferences().get('categories', {})
        for item in values:
            item['category'] = categories.get(item['id'], item['category'])
        return values

    def thumbnail(self, asset_id):
        if asset_id in bundled_gifs():
            return ASSETS/'reactions'/(asset_id+'.png')
        return self.resolve(asset_id)

    def categorize(self, asset_ids, category):
        category = str(category).strip()
        if not category or len(category)>48 or any(ord(c)<32 for c in category):
            raise ValueError('Use a category name of 1–48 characters.')
        if category in ('All', 'Favourites', 'Recent'):
            raise ValueError('That name is reserved for a library filter.')
        for key in asset_ids: self.metadata(key)
        with _LOCK:
            prefs = self.preferences()
            prefs.setdefault('categories', {}).update({key:category for key in asset_ids})
            _atomic_json(self.root/'preferences.json', prefs)

    def update_details(self, asset_id, values):
        """Edit imported descriptive data, retaining identity and all decoder metadata."""
        item = self.metadata(asset_id)
        if not asset_id.startswith('import.'):
            raise ValueError('Bundled media credits are read-only. Import your own recording to edit its details.')
        if type(values) is not dict or set(values) - DETAIL_FIELDS.keys():
            raise ValueError('Unsupported reaction detail fields.')
        for key, value in values.items():
            if type(value) is not str or len(value) > DETAIL_FIELDS[key] or any(ord(c) < 32 and c != '\n' for c in value):
                raise ValueError(f'{key}: enter plain text up to {DETAIL_FIELDS[key]} characters.')
        if 'name' in values and not values['name'].strip():
            raise ValueError('Give this reaction a searchable name.')
        with _LOCK:
            item = self.metadata(asset_id)
            item.update(values)
            _atomic_json(self.root/(asset_id+'.json'), item)
        return item

    def import_many(self, paths, kind, ffmpeg, ffprobe, progress=None, cancel=None):
        if len(paths)>200: raise ValueError('Import up to 200 files in one batch.')
        existing = {item['id'] for item in self.items(kind)}
        added, duplicates, errors = [], [], []
        for i, path in enumerate(paths):
            if cancel is not None and cancel.is_set():break
            try:
                key = self.import_file(path, kind, ffmpeg, ffprobe)
                (duplicates if key in existing else added).append(key)
                existing.add(key)
            except (ValueError, OSError, subprocess.SubprocessError) as exc:
                errors.append(f'{Path(path).name}: {exc}')
            if progress: progress(i+1, len(paths))
        return dict(added=added, duplicates=duplicates, errors=errors)

    def preferences(self):
        try:
            return json.loads((self.root/'preferences.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {'favourites': [], 'recent': [], 'freeze_duration': 1.8}

    def remember(self, asset_id, favourite=False):
        self.metadata(asset_id)
        with _LOCK:
            prefs = self.preferences()
            if favourite:
                values = prefs.setdefault('favourites', [])
                values.remove(asset_id) if asset_id in values else values.append(asset_id)
            else:
                prefs['recent'] = [asset_id]+[x for x in prefs.get('recent', []) if x != asset_id][:15]
            _atomic_json(self.root/'preferences.json', prefs)

    def import_file(self, path, kind, ffmpeg, ffprobe):
        path = Path(path).resolve()
        allowed = ('.wav', '.mp3') if kind == 'sfx' else ('.gif',)
        if kind not in ('sfx', 'gif') or path.suffix.lower() not in allowed:
            raise ValueError('Import WAV/MP3 sound or an animated GIF.')
        if not 0 < path.stat().st_size <= 20*1024*1024:
            raise ValueError('Imports must be at most 20 MB.')
        self.root.mkdir(parents=True, exist_ok=True)
        # Probe and decode an owned snapshot: the selected source may change during import.
        with tempfile.TemporaryDirectory(prefix='import-', dir=self.root) as temporary:
            source = Path(temporary)/('source'+path.suffix.lower())
            with path.open('rb') as stream:
                data = stream.read(20*1024*1024+1)
            if len(data) > 20*1024*1024:
                raise ValueError('Import grew beyond 20 MB.')
            source.write_bytes(data)
            gif_info = inspect_gif(data) if kind == 'gif' else None
            asset_id = 'import.'+hashlib.sha256(data).hexdigest()[:32]
            digest = hashlib.sha256(data).hexdigest()
            if kind == 'gif':
                match = next((key for key,item in bundled_gifs().items() if item['sha256']==digest),None)
                if match: return match
            # Importing the same file again must not overwrite its name, category
            # or licence metadata. Different filenames with identical bytes dedupe.
            try:
                self.resolve(asset_id, kind)
                return asset_id
            except ValueError:
                pass
            base = ['-v', 'error', '-protocol_whitelist', 'file,pipe', '-max_alloc', '67108864']
            result = subprocess.run([str(ffprobe), *base, '-count_frames', '-show_streams', '-show_format',
                                     '-of', 'json', str(source)], capture_output=True, timeout=15, **process_options())
            if result.returncode:
                raise ValueError('This media could not be validated.')
            info = json.loads(result.stdout)
            streams = info.get('streams', [])
            if len(streams) != 1:
                raise ValueError('Imports must contain exactly one audio or GIF stream.')
            stream = streams[0]
            duration = float(info.get('format', {}).get('duration') or stream.get('duration', 0))
            if not math.isfinite(duration) or not 0 < duration <= (15 if kind == 'gif' else 20):
                raise ValueError('Use GIFs up to 15 seconds or sound effects up to 20 seconds.')
            if kind == 'gif':
                w, h, frames = int(stream.get('width', 0)), int(stream.get('height', 0)), int(stream.get('nb_read_frames', 0))
                if stream.get('codec_name') != 'gif' or not (1 <= w <= 1024 and 1 <= h <= 1024 and 1 <= frames <= 300 and w*h*frames <= 64000000):
                    raise ValueError('GIF limit: 1024 px, 300 frames, 64 million total pixels.')
                subprocess.run([str(ffmpeg), *base, '-nostdin', '-xerror', '-i', str(source), '-t', '15', '-f', 'null', '-'],
                               check=True, capture_output=True, timeout=20, **process_options())
                content, suffix = data, '.gif'
            else:
                if stream.get('codec_type') != 'audio' or int(stream.get('channels', 0)) > 8:
                    raise ValueError('Choose a supported audio file with at most 8 channels.')
                normalized = Path(temporary)/'normalized.wav'
                subprocess.run([str(ffmpeg), *base, '-nostdin', '-n', '-i', str(source), '-t', '20',
                                '-ac', '2', '-ar', '48000', '-c:a', 'pcm_s16le', str(normalized)],
                               check=True, capture_output=True, timeout=20, **process_options())
                content, suffix = normalized.read_bytes(), '.wav'
            with _LOCK:
                destination = self.root/(asset_id+suffix)
                if not destination.exists():
                    with destination.open('xb') as output:
                        output.write(content)
                item = dict(id=asset_id, name=path.stem[:80], category='Imported', kind=kind,
                            suffix=suffix, duration=duration, sha256=digest,
                            source='Local import', licence='User supplied — verify rights', attribution='')
                # Tags are descriptive data only. Preserve supplied credits without
                # treating a copyright tag as permission to use the recording.
                tags = {str(k).lower(): str(v) for k,v in
                        {**info.get('format', {}).get('tags', {}), **stream.get('tags', {})}.items()}
                for field, keys in (('name', ('title',)), ('artist', ('artist', 'author')),
                                    ('licence', ('license', 'licence')), ('attribution', ('copyright',))):
                    value = next((tags[key] for key in keys if tags.get(key)), None)
                    if value:
                        item[field] = ''.join(c for c in value if ord(c) >= 32 or c == '\n')[:DETAIL_FIELDS[field]]
                if sum(len(k)+len(v) for k,v in tags.items()) <= 4000:
                    item['embedded_tags'] = tags
                if kind == 'gif':
                    item.update(width=w, height=h, frames=frames, delays=gif_info[2])
                # Restoring a missing media file must retain the user's credits.
                try:
                    previous = self.metadata(asset_id, kind)
                except ValueError:
                    previous = {}
                item.update({key: previous[key] for key in DETAIL_FIELDS if key in previous})
                _atomic_json(self.root/(asset_id+'.json'), item)
            return asset_id
