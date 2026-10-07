"""Pure region geometry shared by the UI and tests."""
from .models import Region


def region_from_points(start, end):
    x1, y1 = start
    x2, y2 = end
    region = Region(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))
    region.validate()
    return region
