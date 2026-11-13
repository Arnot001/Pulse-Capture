# Third-party components

Pulse Capture uses Python, Tcl/Tk, and (in packaged builds) PyInstaller. Their
licenses and installed distribution notices apply to those components.

FFmpeg and FFprobe are separate programs. The default source project and
default build do not bundle them. `-BundleFFmpeg` copies binaries you provide.
FFmpeg builds containing libx264 commonly use the GPL. Distribution obligations
depend on the actual build and configuration, including enabled components.
Before distributing a bundled build, include that build's notices, licenses,
and corresponding source as required. This build script does not supply them.

Optional system-audio support: PyAudioWPatch (Apache-2.0), a PyAudio/PortAudio
fork that exposes Windows WASAPI loopback capture. Installing it for source use
does not add a bundled dependency to the base project. When building an EXE
with the package installed, the build includes PyAudioWPatch; include its
license, bundled PortAudio notices and distribution obligations.
https://pypi.org/project/PyAudioWPatch/
https://github.com/s0d3s/PyAudioWPatch

FFmpeg licensing: https://ffmpeg.org/legal.html
PyInstaller license: https://pyinstaller.org/en/stable/license.html
Python license: https://docs.python.org/3/license.html
