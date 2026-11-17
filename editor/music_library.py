"""User-owned music copies and explicit licence records, separate from profiles."""
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile

from capture.ffmpeg_backend import process_options
from .music import cache_folder
from .reaction_library import _atomic_json, _LOCK

YOUTUBE_LIBRARY_URL = 'https://www.youtube.com/audiolibrary'
LICENCES = ('Unspecified — verify rights', 'YouTube Audio Library licence',
            'Creative Commons Attribution', 'Personal licence', 'Pulse Original Media')


def validate_record(record):
    for key, limit in (('name',160),('artist',160),('source',500),('licence',100),('attribution',8000)):
        value=record.get(key,'')
        if not isinstance(value,str) or len(value)>limit or '\x00' in value:
            raise ValueError(f'Invalid music {key}.')
    if not record.get('name','').strip():raise ValueError('Enter a track name.')
    if record.get('licence') not in LICENCES:raise ValueError('Select a licence type.')
    if type(record.get('requires_attribution')) is not bool:raise ValueError('Choose an attribution setting.')
    if record['licence']=='Creative Commons Attribution' and not record['requires_attribution']:
        raise ValueError('Creative Commons Attribution requires a credit.')
    if record['requires_attribution'] and not record.get('attribution','').strip():
        raise ValueError('Paste the required attribution text from the track licence.')


def description_credit(record):
    validate_record(record)
    return record['attribution'].strip() if record['requires_attribution'] else ''


class MusicLibrary:
    def __init__(self, root=None):
        self.root=Path(root) if root else cache_folder()/'library'

    def items(self):
        values=[]
        for path in sorted(self.root.glob('*.json')):
            try:
                if path.stat().st_size>16000:continue
                item=json.loads(path.read_text(encoding='utf-8'))
                if item.get('id')!=path.stem or len(path.stem)!=64 or any(c not in '0123456789abcdef' for c in path.stem):continue
                validate_record(item)
                media=self.path(item)
                if media.is_file():values.append(item)
            except (ValueError,OSError,TypeError,KeyError):continue
        return values

    def path(self, item):
        key=item['id'];suffix=item['suffix']
        if len(key)!=64 or any(c not in '0123456789abcdef' for c in key) or suffix not in ('.mp3','.wav'):
            raise ValueError('Invalid saved music asset.')
        return self.root/(key+suffix)

    def find(self, path):
        path=Path(path).resolve()
        return next((r for r in self.items() if self.path(r).resolve()==path),None)

    def save(self, path, record, ffprobe):
        validate_record(record)
        path=Path(path)
        if path.suffix.lower() not in ('.mp3','.wav'):raise ValueError('Choose an MP3 or WAV.')
        if not 0<path.stat().st_size<=300*1024*1024:raise ValueError('Music files must be between 1 byte and 300 MB.')
        self.root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='music-import-',dir=self.root) as temporary:
            snapshot=Path(temporary)/('source'+path.suffix.lower())
            digest=hashlib.sha256();size=0
            with path.open('rb') as src, snapshot.open('xb') as dst:
                while block:=src.read(1024*1024):
                    size+=len(block)
                    if size>300*1024*1024:raise ValueError('Music grew beyond 300 MB during import.')
                    digest.update(block);dst.write(block)
            result=subprocess.run([str(ffprobe),'-v','error','-protocol_whitelist','file,pipe','-show_streams','-show_format',
                                   '-of','json',str(snapshot)],capture_output=True,timeout=20,**process_options())
            if result.returncode:raise ValueError('This file could not be read as audio.')
            info=json.loads(result.stdout)
            streams=[s for s in info.get('streams',[]) if s.get('codec_type')=='audio']
            if len(streams)!=1:raise ValueError('Music must contain one audio track.')
            duration=float(info.get('format',{}).get('duration') or streams[0].get('duration',0))
            if not math.isfinite(duration) or not 0<duration<=7200:raise ValueError('Music must be at most two hours long.')
            item=dict(record,id=digest.hexdigest(),suffix=path.suffix.lower(),duration=duration)
            with _LOCK:
                destination=self.path(item)
                if not destination.exists():
                    with snapshot.open('rb') as src,destination.open('xb') as dst:shutil.copyfileobj(src,dst)
                _atomic_json(self.root/(item['id']+'.json'),item)
            return item
