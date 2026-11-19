"""Explicit, free local backend installation. Never reads or uploads user audio.

Run with Python; --root selects an isolated test destination. Models and runtime
stay outside the repository. No setup occurs merely by opening Voice Studio.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import urllib.request
import venv
import zipfile

from editor.voice_conversion import SOURCE_REV, MODEL_REV, runtime_root, runtime_python


def install(root):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if (root / 'installed.json').exists():
        raise ValueError('Runtime already installed. Choose a new folder to reinstall safely.')
    venv.EnvBuilder(with_pip=True).create(root / 'venv')
    python = str(runtime_python(root))
    subprocess.run([python, '-m', 'pip', 'install', 'torch==2.9.1',
                    '--index-url', 'https://download.pytorch.org/whl/cpu'], check=True)
    subprocess.run([python, '-m', 'pip', 'install', 'numpy==2.3.5'], check=True)
    url = f'https://codeload.github.com/myshell-ai/OpenVoice/zip/{SOURCE_REV}'
    archive = urllib.request.urlopen(url, timeout=120).read()
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        for name in bundle.namelist():
            parts = Path(name).parts[1:]
            if not parts or name.endswith('/') or '..' in parts:
                continue
            if parts[0] not in ('openvoice', 'LICENSE'):
                continue
            destination = root / 'source' / Path(*parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(bundle.read(name))
    names = ['converter/config.json', 'converter/checkpoint.pth']
    names += ['base_speakers/ses/'+name+'.pth' for name in
              ('en-br', 'en-us', 'en-au', 'en-india', 'en-default', 'fr', 'es', 'jp', 'kr', 'zh')]
    for name in names:
        destination = root / 'checkpoints' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        print('Downloading licensed model:', name, flush=True)
        urllib.request.urlretrieve(f'https://huggingface.co/myshell-ai/OpenVoiceV2/resolve/{MODEL_REV}/{name}', destination)
    hashes = {}
    for folder in ('source', 'checkpoints'):
        for path in (root / folder).rglob('*'):
            if path.is_file():
                with path.open('rb') as handle:
                    hashes[path.relative_to(root).as_posix()] = hashlib.file_digest(handle, 'sha256').hexdigest()
    subprocess.run([python, '-c', 'import torch,numpy; print(torch.__version__)'], check=True)
    (root / 'installed.json').write_text(json.dumps({'source_revision': SOURCE_REV,
        'model_revision': MODEL_REV, 'sha256': hashes, 'license': 'MIT'}, indent=2), encoding='utf-8')
    print('Installed local CPU conversion at', root)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=runtime_root())
    args = parser.parse_args()
    install(args.root)
