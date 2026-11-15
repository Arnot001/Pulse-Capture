"""Download the public English speech model on explicit local setup only.

Never replaces an existing model.bin and never uploads recordings.
"""
from pathlib import Path
from faster_whisper.utils import download_model


def main():
    root = Path(__file__).resolve().parents[1]
    model = root / '.auto-models' / 'base.en'
    if (model / 'model.bin').is_file():
        print('Existing local English speech model retained.')
        return
    model.mkdir(parents=True, exist_ok=True)
    download_model('base.en', output_dir=str(model))
    if not (model / 'model.bin').is_file():
        raise RuntimeError('Speech model download did not create model.bin.')
    print('Local English speech model ready.')


if __name__ == '__main__':
    main()
