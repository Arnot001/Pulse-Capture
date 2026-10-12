"""Non-destructive source-time cut ranges for Quick Edit."""
from dataclasses import dataclass
import math

from .models import TrimRange


@dataclass(frozen=True)
class CutRange:
    start: float
    end: float

    @property
    def duration(self):
        return self.end - self.start

    def validate(self, media):
        media.validate()
        if not all(isinstance(v, (int, float)) and math.isfinite(v)
                   for v in (self.start, self.end)):
            raise ValueError('Choose valid Cut Start and Cut End times.')
        if self.start < 0 or self.end > media.duration + 0.0005:
            raise ValueError('Keep cuts inside the source video.')
        if self.end <= self.start:
            raise ValueError('Cut End must be after Cut Start.')
        if self.duration < min(1 / media.fps, media.duration) - 0.0005:
            raise ValueError('Remove at least one frame.')


@dataclass(frozen=True)
class CutPlan:
    ranges: tuple[CutRange, ...] = ()

    def validate(self, media):
        previous = None
        for cut in self.ranges:
            if not isinstance(cut, CutRange):
                raise ValueError('Choose valid cut sections.')
            cut.validate(media)
            if previous is not None and cut.start < previous.end - 0.0005:
                raise ValueError('Cut sections cannot overlap.')
            previous = cut

    def add(self, cut, media):
        if not isinstance(cut, CutRange):
            raise ValueError('Choose a valid cut section.')
        cut.validate(media)
        items = list(self.ranges)
        for existing in items:
            if cut.start < existing.end - 0.0005 and cut.end > existing.start + 0.0005:
                raise ValueError('That section overlaps a cut you already removed.')
        items.append(cut)
        items.sort(key=lambda item: (item.start, item.end))
        plan = CutPlan(tuple(items))
        plan.validate(media)
        return plan

    def remove(self, cut):
        if cut not in self.ranges:
            raise ValueError('That removed section is no longer present.')
        items = list(self.ranges)
        items.remove(cut)
        return CutPlan(tuple(items))

    def visible_ranges(self, trim):
        visible = []
        for cut in self.ranges:
            start = max(trim.start, cut.start)
            end = min(trim.end, cut.end)
            if end > start:
                visible.append(CutRange(start, end))
        return tuple(visible)

    def kept_segments(self, trim):
        cursor = trim.start
        kept = []
        for cut in self.visible_ranges(trim):
            if cut.start > cursor:
                kept.append(TrimRange(cursor, cut.start))
            cursor = max(cursor, cut.end)
        if cursor < trim.end:
            kept.append(TrimRange(cursor, trim.end))
        return tuple(kept)

    def kept_duration(self, trim):
        return sum(segment.duration for segment in self.kept_segments(trim))

    def removed_duration(self, trim):
        return max(0.0, trim.duration - self.kept_duration(trim))

    def validate_selection(self, media, trim):
        self.validate(media)
        trim.validate(media)
        if self.kept_duration(trim) < min(1 / media.fps, trim.duration) - 0.0005:
            raise ValueError('Cuts would remove the entire selected video. Restore a section first.')

    def source_elapsed(self, position, trim):
        """Kept source seconds elapsed before a source-timeline position."""
        position = max(trim.start, min(position, trim.end))
        elapsed = 0.0
        for segment in self.kept_segments(trim):
            if position <= segment.start:
                break
            elapsed += min(position, segment.end) - segment.start
            if position < segment.end:
                break
        return max(0.0, min(elapsed, self.kept_duration(trim)))

    def snap_position(self, position, trim):
        """Move a source position out of a removed section onto the kept timeline."""
        return self.source_from_elapsed(self.source_elapsed(position, trim), trim)

    def source_from_elapsed(self, elapsed, trim):
        """Map kept source seconds back to source time, jumping removed ranges."""
        kept = self.kept_segments(trim)
        total = sum(segment.duration for segment in kept)
        elapsed = max(0.0, min(elapsed, total))
        remaining = elapsed
        for index, segment in enumerate(kept):
            if remaining < segment.duration - 1e-9:
                return segment.start + remaining
            remaining -= segment.duration
            if index == len(kept) - 1:
                return segment.end
        return trim.end
