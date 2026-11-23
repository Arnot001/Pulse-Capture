"""Launch the proven Pulse Privacy Screen as a separate, recoverable process.

This module intentionally does not touch recording, editor, or Windows shell state.
The bundled PowerShell utility owns its desktop settings and recovery controls.
"""
from pathlib import Path
import os
import subprocess
import sys

from branding import asset_root


def privacy_script_path():
    return asset_root() / 'assets' / 'privacy' / 'Pulse-Privacy-Screen.ps1'


def find_powershell():
    system_root = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    executable = system_root / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
    if not executable.is_file():
        raise FileNotFoundError('Windows PowerShell 5.1 was not found.')
    return executable


def launch_privacy_screen(existing=None):
    """Return (process, newly_started). Repeated clicks cannot open duplicates."""
    if sys.platform != 'win32':
        raise RuntimeError('Privacy Desktop requires Windows 10 or 11.')
    if existing is not None and existing.poll() is None:
        return existing, False
    script = privacy_script_path()
    if not script.is_file():
        raise FileNotFoundError(f'Privacy Screen script was not bundled: {script}')
    executable = find_powershell()
    command = [str(executable), '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass',
               '-File', str(script)]
    process = subprocess.Popen(command, cwd=str(script.parent),
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return process, True