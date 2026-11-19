"""Isolated CPU OpenVoice V2 inference. No transcription, TTS or network calls."""
import argparse
import json
from pathlib import Path
import sys
import wave


def convert(runtime, source, destination, voice, mix=1., seed=0):
    import numpy as np
    import torch
    from torch.nn import functional as F
    sys.path.insert(0, str(Path(runtime) / 'source'))
    from openvoice.models import SynthesizerTrn

    torch.set_num_threads(4)
    torch.manual_seed(seed)
    root = Path(runtime) / 'checkpoints'
    config = json.loads((root / 'converter/config.json').read_text())
    data = config['data']
    rate, hop, fft = data['sampling_rate'], data['hop_length'], data['filter_length']
    model = SynthesizerTrn(0, fft // 2 + 1, n_speakers=0, **config['model']).eval()
    state = torch.load(root / 'converter/checkpoint.pth', map_location='cpu', weights_only=True)
    model.load_state_dict(state['model'], strict=True)
    target = torch.load(voice, map_location='cpu', weights_only=True)
    if not isinstance(target, torch.Tensor) or target.shape != (1, 256, 1) or not torch.isfinite(target).all():
        raise ValueError('Expected a finite OpenVoice V2 speaker embedding shaped [1,256,1].')
    with wave.open(str(source), 'rb') as reader:
        if reader.getframerate() != rate or reader.getnchannels() != 1 or reader.getsampwidth() != 2:
            raise ValueError('Conversion input must be mono PCM16 at 22050 Hz.')
        audio = torch.from_numpy(np.frombuffer(reader.readframes(reader.getnframes()), dtype='<i2').copy()).float() / 32768
    if len(audio) < rate // 2:
        raise ValueError('Record at least half a second for conversion.')
    window = torch.hann_window(data['win_length'])

    def spectrum(samples):
        samples = F.pad(samples.reshape(1, 1, -1), ((fft-hop)//2, (fft-hop)//2), mode='reflect').squeeze(1)
        value = torch.stft(samples, fft, hop_length=hop, win_length=data['win_length'],
                           window=window, center=False, return_complex=True)
        return (value.abs().square() + 1e-6).sqrt()

    result = torch.zeros_like(audio)
    with torch.inference_mode():
        reference = spectrum(audio[:min(len(audio), 30*rate)])
        original = model.ref_enc(reference.transpose(1, 2)).unsqueeze(-1)
        # Overlapping context keeps memory bounded; retained samples stay on the source clock.
        chunk, margin = 10 * rate, 22 * hop
        for start in range(0, len(audio), chunk):
            end = min(len(audio), start + chunk)
            left = max(0, start - margin)
            right = min(len(audio), end + margin)
            samples = audio[left:right]
            padded = F.pad(samples, (0, (-len(samples)) % hop + hop))
            spec = spectrum(padded)
            converted = model.voice_conversion(spec, torch.tensor([spec.shape[-1]]),
                                                original, target, tau=.3)[0][0, 0]
            converted = converted[start-left:end-left]
            if len(converted) != end-start:
                raise ValueError('Converter returned an unexpected number of samples.')
            result[start:end] = converted * mix + audio[start:end] * (1-mix)
        # Digital silence remains silent without shifting or deleting pauses.
        result[audio == 0] = 0
    with wave.open(str(destination), 'wb') as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes((result.clamp(-.999, .999).numpy()*32767).astype('<i2').tobytes())
    print(json.dumps({'backend': 'OpenVoice V2', 'torch': torch.__version__, 'device': 'cpu',
                      'seed': seed, 'samples': len(audio), 'sample_rate': rate}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('runtime', 'source', 'destination', 'voice'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--mix', type=float, default=1.)
    args = parser.parse_args()
    if not 0 <= args.mix <= 1:
        parser.error('Mix must be between 0 and 1.')
    convert(args.runtime, args.source, args.destination, args.voice, args.mix)
