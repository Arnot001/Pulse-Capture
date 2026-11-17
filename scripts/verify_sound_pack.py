"""Render every sound and report PCM health; make a representative audition WAV."""
from array import array
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
import wave

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from editor.reaction_library import ReactionLibrary, SFX


def verify(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    records=[];hashes=set();montage=array('h');cues=[]
    chosen={'original.rimshot','original.balloon_escape','original.applause','original.gasp',
            'original.system_panic','original.receipt','original.glass_shatter','original.thunder',
            'original.falling_stairs','original.deflate','original.dog_bark','original.bird_chirp',
            'original.page_flip','original.bubble_wipe','original.door_creak','original.heartbeat_rise'}
    with tempfile.TemporaryDirectory(prefix='pulse-sound-audit-') as folder:
        library=ReactionLibrary(folder)
        for key in SFX:
            path=library.resolve(key)
            with wave.open(str(path),'rb') as wav:
                assert wav.getparams()[:3]==(2,2,48000),key
                pcm=array('h');pcm.frombytes(wav.readframes(wav.getnframes()))
            digest=hashlib.sha256(pcm.tobytes()).hexdigest()
            assert digest not in hashes, f'Duplicate waveform: {key}'
            hashes.add(digest)
            peak=max(abs(v) for v in pcm)/32768
            rms=math.sqrt(sum(v*v for v in pcm)/len(pcm))/32768
            duration=len(pcm)/96000
            assert .005<rms and peak<.99,(key,rms,peak)
            assert abs(duration-SFX[key][2])<1/48000,key
            records.append(dict(id=key,duration=duration,peak=round(peak,5),rms=round(rms,5),pcm_sha256=digest))
            if key in chosen:
                cues.append(dict(id=key,start=len(montage)/96000,end=(len(montage)+len(pcm))/96000))
                montage.extend(pcm);montage.extend(array('h',[0])*15360)
    with wave.open(str(output/'sound-pack-audition.wav'),'wb') as wav:
        wav.setparams((2,2,48000,0,'NONE','not compressed'));wav.writeframes(montage.tobytes())
    (output/'sound-pack-audit.json').write_text(json.dumps(dict(count=len(records),sounds=records,audition_cues=cues),indent=2)+'\n',encoding='utf-8')
    print(f'{len(records)} unique, non-silent stereo WAVs; no clipping. Audition: {len(cues)} representative arrangements.')


if __name__=='__main__':verify(sys.argv[1])
