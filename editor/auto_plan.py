"""Deterministic source-time Shorts recommendations from local video/audio cues.

Suggestions are candidates for review, not guarantees of interesting content.
No cloud calls, telemetry, or account data.
"""
from dataclasses import dataclass
import math

STYLES = ('Gaming', 'News/Preview', 'Funny Moments')
DEFAULT_SECONDS = 28.0


@dataclass(frozen=True)
class AutoSuggestion:
    start: float
    end: float
    score: float
    reason: str

    @property
    def duration(self):
        return self.end - self.start


def choose_highlights(duration, scenes=(), energy=(), *, style='Gaming', count=1,
                      target_seconds=DEFAULT_SECONDS):
    """Rank up to three non-destructive clips; times refer to original source.

    scenes: source seconds where FFmpeg detected visual changes.
    energy: (second, RMS dBFS) samples. Higher dBFS means louder.
    """
    if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        raise ValueError('Choose a recording with a valid duration.')
    if style not in STYLES:
        raise ValueError('Choose Gaming, News/Preview, or Funny Moments.')
    if type(count) is not int or count not in (1, 2, 3):
        raise ValueError('Choose one, two, or three Shorts.')
    if not math.isfinite(target_seconds) or target_seconds <= 0:
        raise ValueError('Choose a positive Short duration.')

    length = min(duration, max(20.0, min(35.0, float(target_seconds))))
    scenes = tuple(sorted(t for t in scenes if isinstance(t, (int, float))
                          and math.isfinite(t) and 0 <= t <= duration))
    energy = tuple(sorted((float(t), max(-90.0, min(0.0, float(db))))
                          for t, db in energy
                          if isinstance(t, (int, float)) and isinstance(db, (int, float))
                          and math.isfinite(t) and math.isfinite(db)
                          and 0 <= t <= duration))

    if duration <= length + .001:
        return (AutoSuggestion(0.0, duration, 0.0, 'Entire recording fits one Short'),)

    points = set((0.0, max(0.0, duration-length), max(0.0, duration/2-length/2)))
    for t in scenes:
        points.add(max(0.0, min(duration-length, t-length*.35)))
    for t, level in energy:
        if level >= -29.0:
            points.add(max(0.0, min(duration-length, t-length*.25)))
    step = max(4.0, length*.48)
    for j in range(1, int((duration-length)/step) + 1):
        points.add(min(duration-length, j*step))

    if style == 'Gaming':
        scene_weight, audio_weight = .6, .4
    elif style == 'News/Preview':
        scene_weight, audio_weight = .3, .7
    else:
        scene_weight, audio_weight = .45, .55

    ranked = []
    for start in points:
        end = start + length
        scene_hits = sum(start <= t < end for t in scenes)
        audio = [db for t, db in energy if start <= t < end]
        loud = sum(db > -28 for db in audio)
        shifts = sum(max(0.0, audio[i]-audio[i-1]) >= 8 for i in range(1, len(audio)))
        scene_signal = min(1.0, scene_hits / max(2.0, length/9))
        sound_signal = min(1.0, (loud*.35 + shifts*2.0) / max(1.0, length/4))
        score = scene_weight*scene_signal + audio_weight*sound_signal
        if scene_signal > sound_signal * 1.25:
            reason = 'Frequent visual changes'
        elif sound_signal > scene_signal * 1.25:
            reason = 'Audio activity / emphasis'
        elif score > .1:
            reason = 'Scene and audio activity'
        else:
            reason = 'Evenly spaced fallback (review manually)'
        ranked.append(AutoSuggestion(round(start, 3), round(end, 3),
                                     round(score, 4), reason))
    ranked.sort(key=lambda s: (-s.score, s.start))

    selected = []
    for candidate in ranked:
        if any(max(0.0, min(s.end, candidate.end)-max(s.start, candidate.start))
               > .30 * length for s in selected):
            continue
        selected.append(candidate)
        if len(selected) == count:
            break
    # Return fewer than requested when footage cannot fit distinct clips.
    return tuple(selected)
