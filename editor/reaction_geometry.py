"""Output-pixel geometry matching reactions.add_visuals, independent of Tk."""
from dataclasses import dataclass, replace
import math


def clamp(value, low, high):
    return max(low, min(high, value))


@dataclass(frozen=True)
class VisualBounds:
    x: float
    y: float
    side: int
    dx: float = 0
    dy: float = 0


def visual_bounds(cue, width, height, at, item):
    """Include rotate's transparent square, GIF lifetime and animation offsets.

    FFmpeg scales to an integer box, rounds the fitted aspect ratio, then rounds
    hypot(iw,ih) for the rotation canvas. X/Y normalize the remaining travel,
    not the full output dimensions. Keep these semantics for existing v2 plans.
    """
    end = min(cue.end, cue.start+item['duration']) if cue.kind == 'gif' and not cue.loop else cue.end
    if not cue.start <= at < end or cue.opacity == 0:
        return None
    elapsed = at-cue.start
    size = max(16, round(min(width, height)*cue.scale))
    ramp = min(.15, (end-cue.start)/3)
    factor = .65+.35*min(1, elapsed/ramp) if cue.animation == 'pop' else 1
    target = max(1, int(size*factor))
    ratio = min(target/item['width'], target/item['height'])
    sw, sh = (max(1, math.floor(item[key]*ratio+.5)) for key in ('width', 'height'))
    side = math.floor(math.hypot(sw, sh)+.5)
    x = (cue.x*(width-side) if cue.x is not None else width-side-width*.1
         if 'right' in cue.position else width*.1 if 'left' in cue.position else (width-side)/2)
    y = (cue.y*(height-side) if cue.y is not None else height*.12
         if 'top' in cue.position else height*.78-side if 'bottom' in cue.position else (height-side)/2)
    dx = size*.04*math.sin(elapsed*70) if cue.animation == 'shake' else 0
    dy = -size*.12*abs(math.sin(elapsed*14))*math.exp(-elapsed*4) if cue.animation == 'bounce' else 0
    return VisualBounds(clamp(x+dx, 0, width-side), clamp(y+dy, 0, height-side), side, dx, dy)


def positioned(cue, x, y, width, height, at, item):
    """Inverse of the compositor's normalized position and animation offsets."""
    bounds = visual_bounds(cue, width, height, at, item)
    if bounds is None:
        return cue
    return replace(cue, x=clamp((x-bounds.dx)/max(1, width-bounds.side), 0, 1),
                   y=clamp((y-bounds.dy)/max(1, height-bounds.side), 0, 1))
