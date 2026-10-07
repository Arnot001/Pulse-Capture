import unittest
from capture.region_picker import region_from_points
from capture.models import Region


class RegionTests(unittest.TestCase):
    def test_reverse_drag_across_negative_coordinates(self):
        self.assertEqual(region_from_points((200, 300), (-100, -200)), Region(-100, -200, 300, 500))

    def test_click_is_not_a_region(self):
        with self.assertRaises(ValueError):
            region_from_points((1, 1), (1, 1))
