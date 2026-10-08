"""Shared resource paths for source runs and PyInstaller bundles."""
from pathlib import Path
import sys


def asset_root():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))


def watermark_path():
    return asset_root() / 'assets' / 'branding' / 'pulse.png'
