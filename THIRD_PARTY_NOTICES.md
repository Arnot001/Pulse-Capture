# Third-party components

Pulse Capture uses Python, Tcl/Tk, and (in packaged builds) PyInstaller. Their
licenses and installed distribution notices apply to those components.

FFmpeg and FFprobe are separate programs. The default source project and
default build do not bundle them. `-BundleFFmpeg` copies binaries you provide.
FFmpeg builds containing libx264 commonly use the GPL. Distribution obligations
depend on the actual build and configuration, including enabled components.
Before distributing a bundled build, include that build's notices, licenses,
and corresponding source as required. This build script does not supply them.

FFmpeg licensing: https://ffmpeg.org/legal.html
PyInstaller license: https://pyinstaller.org/en/stable/license.html
Python license: https://docs.python.org/3/license.html
