"""Small, deterministic FFmpeg voice effects for Commentary Studio.

Every preset uses bundled FFmpeg audio filters, so there are no downloads,
third-party VSTs, cloud services or modifications to microphone WAV files.
Effects are kept inside the edited commentary clip's interval.
"""
import math

EFFECTS = ('None', 'Echo', 'Reverb', 'Chorus')


def validate_effect(effect, strength):
    if effect not in EFFECTS or type(effect) is not str:
        raise ValueError('Choose a supported commentary effect.')
    if type(strength) not in (int, float) or not math.isfinite(strength):
        raise ValueError('Effect intensity must be a finite number.')
    if not 0 <= strength <= 1:
        raise ValueError('Effect intensity must be between 0% and 100%.')


def voice_effect_filters(effect, strength):
    """Return a small auditable FFmpeg audio filter list; 0% bypasses entirely."""
    validate_effect(effect, strength)
    strength = float(strength)
    if effect == 'None' or strength <= 0:
        return []
    if effect == 'Echo':
        # Separated repeats; preserve most of the dry speech for intelligibility.
        a = .08 + .34 * strength
        b = .04 + .22 * strength
        return [f'aecho=0.9:0.9:210|390:{a:.3f}|{b:.3f}']
    if effect == 'Reverb':
        # Dense reflections approximate a small-to-large room, rather than a
        # separate convolution impulse-response asset. Short CPU-friendly taps.
        decays = (.05 + .14*strength, .04 + .12*strength,
                  .03 + .11*strength, .02 + .10*strength,
                  .015 + .08*strength)
        taps = '|'.join(f'{decay:.3f}' for decay in decays)
        return [f'aecho=0.85:0.86:33|65|103|168|249:{taps}']
    # Modulated delays make an ensemble/doubled-voice sound, not pitch cloning.
    left = .09 + .31*strength
    right = .08 + .27*strength
    return [f'chorus=0.7:0.9:50|60:{left:.3f}|{right:.3f}:0.25|0.4:2|1.3']

def render_effect_audition(ffmpeg, path, source_in, duration,
                           effect, strength, cancel=None):
    """Render a disposable 30-second-or-shorter WAV for accurate studio audition.

    This never writes to the original recording/library or touches the timeline.
    Each finished result is a temporary PCM file owned by the dialog for cleanup.
    """
    import os
    import subprocess
    import tempfile
    import time
    from pathlib import Path

    filters = voice_effect_filters(effect, strength)
    if not filters:
        return Path(path), source_in, duration, False
    duration = min(float(duration), 30.)
    if duration <= 0 or source_in < 0:
        raise ValueError('Choose a valid recording interval.')
    handle, name = tempfile.mkstemp(prefix='pulse-commentary-preview-',
                                   suffix='.wav')
    os.close(handle)
    output = Path(name)
    cmd = [str(ffmpeg), '-hide_banner', '-loglevel', 'error',
           '-nostdin', '-y', '-ss', f'{source_in:.6f}',
           '-t', f'{duration:.6f}', '-i', str(Path(path).resolve()),
           '-af', ','.join(filters + [f'atrim=duration={duration:.6f}']),
           '-c:a', 'pcm_s16le', '-ar', '48000', '-ac', '2', str(output)]
    proc = None
    try:
        if cancel is not None and cancel.is_set():
            raise ValueError('Effects preview cancelled.')
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        deadline = time.monotonic()+45
        while True:
            try:
                _, error = proc.communicate(timeout=.15)
                break
            except subprocess.TimeoutExpired:
                if cancel is not None and cancel.is_set():
                    raise ValueError('Effects preview cancelled.')
                if time.monotonic() > deadline:
                    raise ValueError('Effects preview exceeded 45 seconds.')
        if proc.returncode != 0:
            raise ValueError('FFmpeg could not render this effect: ' +
                             error.decode('utf-8', errors='replace')[-500:])
        if cancel is not None and cancel.is_set():
            raise ValueError('Effects preview cancelled.')
        return output, 0., duration, True
    except BaseException:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try: proc.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
        try: output.unlink(missing_ok=True)
        except OSError: pass
        raise
