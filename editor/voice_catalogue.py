"""Honest local speaker catalogue with private favourites and user provenance."""
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import shutil
import subprocess
import threading
import time
import uuid

from capture.ffmpeg_backend import process_options
from .ai_voiceover import library_root
from .voice_conversion import MODEL_URL, available, runtime_python, runtime_root
from .voice_reference import check_cancel, extract_reference, reference_labels, validate_embedding
from .voice_assets import digest

CATEGORIES = ('All', 'Male', 'Female', 'Androgynous', 'Characters', 'Documentary', 'Comedy', 'Gaming', 'Dramatic')


@dataclass(frozen=True)
class Voice:
    id: str
    name: str
    model: str
    language: str = 'Multilingual'
    accent: str = 'Preserves source accent'
    presentation: str = 'Unspecified'
    age: str = 'Unspecified'
    tone: str = 'Natural'
    style: str = 'Performance preserving'
    categories: tuple = ()
    provider: str = 'MyShell / OpenVoice V2'
    provenance: str = MODEL_URL + ' · MIT licensed stock speaker embedding'
    mode: str = 'Local CPU'
    cost: str = 'No API charge'
    metadata_origin: str = 'Provider stock label; not an accent-conversion promise'
    permission: str = 'MIT stock embedding'
    reference_sha256: str = ''
    reference_file: str = ''

    @property
    def installed(self):
        return available() and Path(self.model).is_file()


class Catalogue:
    def __init__(self, root=None):
        self.root = Path(root) if root else library_root()
        self.path = self.root / 'catalogue.json'
        self.lock = threading.RLock()
        self.state = {'favourites': [], 'recent': [], 'custom': []}
        if self.path.is_file():
            value = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(value, dict):
                raise ValueError('Voice catalogue is not a JSON object.')
            self.state.update(value)

    def save(self):
        with self.lock:
            self.root.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name('catalogue-' + uuid.uuid4().hex + '.tmp')
            temporary.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(self.path)

    def voices(self):
        entries = [('en-br', 'English · British', 'British', 'English'),
                   ('en-us', 'English · American', 'American', 'English'),
                   ('en-au', 'English · Australian', 'Australian', 'English'),
                   ('en-india', 'English · Indian', 'Indian', 'English'),
                   ('en-default', 'English · Default', 'Unspecified', 'English'),
                   ('fr', 'French', 'French', 'French'), ('es', 'Spanish', 'Spanish', 'Spanish'),
                   ('jp', 'Japanese', 'Japanese', 'Japanese'), ('kr', 'Korean', 'Korean', 'Korean'),
                   ('zh', 'Chinese', 'Chinese', 'Chinese')]
        result = [Voice(key, label, str(runtime_root() / 'checkpoints/base_speakers/ses' / (key+'.pth')),
                        language=language, accent='Preserves source pronunciation') for key, label, accent, language in entries]
        result += [Voice(**value) for value in self.state['custom']]
        return result

    def search(self, query='', category='All', favourites=False, sort='Name', **filters):
        query = query.casefold().strip()
        result = []
        for voice in self.voices():
            if query and query not in ' '.join(str(x) for x in asdict(voice).values()).casefold():
                continue
            if category != 'All' and category not in voice.categories and category != voice.presentation:
                continue
            if favourites and voice.id not in self.state['favourites']:
                continue
            if any(value not in ('', 'All') and value != getattr(voice, key) for key, value in filters.items()):
                continue
            result.append(voice)
        if sort == 'Recently used':
            recent = self.state['recent']
            return sorted(result, key=lambda v: (recent.index(v.id) if v.id in recent else 999, v.name))
        return sorted(result, key=lambda v: v.name.casefold())

    def favourite(self, ident):
        values = self.state['favourites']
        values.remove(ident) if ident in values else values.append(ident)
        self.save()

    def used(self, ident):
        self.state['recent'] = [ident] + [x for x in self.state['recent'] if x != ident][:19]
        self.save()

    def add_reference(self, reference, labels, cancel=None):
        """Publish only a validated embedding and its immutable authorised source."""
        labels = reference_labels(labels)
        check_cancel(cancel)
        with self.lock:
            for value in self.state['custom']:
                if value.get('reference_sha256') == reference.source_sha256 and Path(value['model']).is_file():
                    return Voice(**value)
        # Keep all intermediate output in the prepared reference's temporary folder.
        embedding = reference.wav.with_suffix('.pth')
        backend = extract_reference(reference, embedding, cancel)
        validate_embedding(embedding, cancel)
        check_cancel(cancel)
        with self.lock:
            # Another import may have completed while extraction was running.
            for value in self.state['custom']:
                if value.get('reference_sha256') == reference.source_sha256 and Path(value['model']).is_file():
                    return Voice(**value)
            ident = 'reference-' + uuid.uuid4().hex
            self.root.mkdir(parents=True, exist_ok=True)
            folder = self.root/ident
            folder.mkdir()
            model, original = folder/'speaker.pth', folder/reference.original.name
            voice = Voice(ident, labels['name'], str(model),
                          language=labels.get('language', 'Unspecified'),
                          accent=labels.get('accent', 'Unspecified'),
                          presentation=labels.get('presentation', 'Unspecified'),
                          style=labels.get('style', 'Natural'), provider='Authorised reference',
                          provenance=labels['provenance'], permission=labels['permission'],
                          metadata_origin='User-provided labels; not provider-verified',
                          reference_sha256=reference.source_sha256, reference_file=str(original))
            appended = False
            try:
                shutil.copyfile(embedding, model)
                shutil.copyfile(reference.original, original)
                if digest(original) != reference.source_sha256:
                    raise ValueError('Reference changed during import; nothing was added.')
                details = dict(reference.info, source_name=reference.source_name,
                               source_sha256=reference.source_sha256, embedding_sha256=digest(model),
                               labels=labels, backend=backend, created_at=time.time(), schema=1)
                (folder/'reference.json').write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding='utf-8')
                check_cancel(cancel)
                self.state['custom'].append(asdict(voice))
                appended = True
                self.save()
            except BaseException:
                if appended:
                    self.state['custom'].pop()
                shutil.rmtree(folder)
                raise
            return voice

    def import_voice(self, manifest_path):
        """Import an embedding with explicit rights metadata, never arbitrary model code."""
        manifest_path = Path(manifest_path)
        data = json.loads(manifest_path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('Voice manifest must be a JSON object.')
        for key in ('name', 'model', 'provenance', 'permission'):
            if not isinstance(data.get(key), str) or not data[key].strip():
                raise ValueError('Voice manifest requires name, model, provenance and permission.')
        if data['permission'] not in ('licensed', 'own voice', 'speaker consent'):
            raise ValueError('Declare licensed, own voice or speaker consent permission.')
        for key in ('language', 'accent', 'presentation', 'age', 'tone', 'style'):
            if key in data and (not isinstance(data[key], str) or not 1 <= len(data[key]) <= 160):
                raise ValueError(f'Voice {key} must be a short text label.')
        categories = data.get('categories', [])
        if not isinstance(categories, list) or any(not isinstance(v, str) or v not in CATEGORIES[1:] for v in categories):
            raise ValueError('Use supported voice categories in a JSON list.')
        if data.get('presentation', 'Unspecified') not in ('Unspecified', 'Male', 'Female', 'Androgynous'):
            raise ValueError('Choose Male, Female, Androgynous or Unspecified voice presentation.')
        model = (manifest_path.parent / data['model']).resolve()
        if model.suffix.lower() != '.pth' or not model.is_file() or model.stat().st_size > 1024*1024:
            raise ValueError('Import an OpenVoice V2 .pth speaker embedding under 1 MB, not an RVC checkpoint.')
        if not available():
            raise ValueError('Install local conversion before validating an embedding.')
        check = "import sys,torch; x=torch.load(sys.argv[1],map_location='cpu',weights_only=True); assert isinstance(x,torch.Tensor) and x.shape==(1,256,1) and torch.isfinite(x).all(), 'Invalid embedding'"
        result = subprocess.run([str(runtime_python()), '-c', check, str(model)], capture_output=True,
                                timeout=45, **process_options())
        if result.returncode:
            raise ValueError('Not a valid, safe OpenVoice V2 speaker embedding.')
        ident = 'custom-' + uuid.uuid4().hex
        self.root.mkdir(parents=True, exist_ok=True)
        destination = self.root / (ident + '.pth')
        with model.open('rb') as source, destination.open('xb') as target:
            shutil.copyfileobj(source, target)
        permitted = {key: data[key] for key in ('language', 'accent', 'presentation', 'age', 'tone', 'style', 'categories') if key in data}
        voice = Voice(ident, data['name'], str(destination), provider='User supplied',
                      provenance=data['permission'] + ': ' + data['provenance'],
                      permission=data['permission'], metadata_origin='User-provided labels; not provider-verified', **permitted)
        self.state['custom'].append(asdict(voice))
        self.save()
        return voice
