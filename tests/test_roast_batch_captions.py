"""Prevent future generated comedy captions from spilling onto gameplay.

These are text-only examples from the first GTA roast batch. No user video,
private recording, screenshots or fingerprint is committed.
"""
from dataclasses import asdict
import unittest

from editor.comedy_layout import fit_caption, regions
from editor.typography import CaptionStyle, theme_style


EXAMPLES = {
    "elevator": [
        ("top", "ROCKSTAR, EXPLAIN THIS.", 90),
        ("bottom", "SHE'S STRIKING A POSE.", 88),
        ("top", "IN A FUCKING LIFT.", 92),
        ("bottom", "THIS IS NOT VOGUE.", 90),
        ("top", "SUNGLASSES. INDOORS.", 88),
        ("bottom", "LEG UP. FULL COMMITMENT.", 84),
        ("top", "MAN JUST WANTS TO GO UPSTAIRS.", 78),
        ("bottom", "NPC HAS A MODEL DEAL. 💀", 82),
    ],
    "burger": [
        ("top", "ROCKSTAR, WHAT IS THAT?", 84),
        ("bottom", "A BUN. FINE.", 88),
        ("top", "THAT IS SIX FEET OF HAM.", 84),
        ("bottom", "IS IT LOAD-BEARING?", 82),
        ("top", "IT NEEDS PLANNING PERMISSION.", 80),
        ("bottom", "GET AN ENGINEER.", 78),
        ("top", "DO NOT SHAKE THE TABLE.", 84),
    ],
    "robbers": [
        ("top", "ARREST THESE OUTFITS.", 88),
        ("bottom", "HE'S ROBBING A SHOP.", 86),
        ("top", "DRESSED FOR TENERIFE.", 88),
        ("bottom", "SUNGLASSES. BANDANA.", 84),
        ("top", "ALL-INCLUSIVE HEIST.", 88),
        ("bottom", "WHO'S THE TOUR REP?", 88),
        ("top", "SOUVENIR T-SHIRT.", 88),
        ("bottom", "FIVE STARS. ZERO TASTE.", 83),
        ("top", "WANTED: HOLIDAY STYLIST.", 80),
    ],
}


class BatchRoastBandTests(unittest.TestCase):
    def test_every_caption_fits_1600x900_source_to_mobile_safe_bands(self):
        safe_bands = regions((1600, 900))
        self.assertGreater(safe_bands["top"].height, 0)
        self.assertGreater(safe_bands["bottom"].height, 0)
        for episode, cues in EXAMPLES.items():
            for zone, label, font_size in cues:
                with self.subTest(episode=episode, text=label):
                    props = asdict(theme_style("Comedy Bold"))
                    props["font_size"] = font_size
                    style = CaptionStyle(**props)
                    font, lines, height, padding = fit_caption(
                        label, style, safe_bands[zone])
                    self.assertGreaterEqual(font, 64)
                    self.assertLessEqual(len(lines), 3)
                    self.assertLessEqual(height+padding*2, safe_bands[zone].height)


if __name__ == "__main__":
    unittest.main()
