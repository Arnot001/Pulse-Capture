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
