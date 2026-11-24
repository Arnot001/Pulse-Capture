# Third-party components

Bundled caption font: DejaVu Sans Bold. Copyright Bitstream, with DejaVu changes
in the public domain and applicable Arev notices. The complete license is included
in `assets/licenses/LICENSE_DEJAVU`. The font is distributed unmodified.

The Pulse reaction PNG artwork and synthesized sound-effect definitions are
original project assets. They contain no downloaded reaction GIFs or audio samples.
Imported user media remains subject to its owner's licence. Pillow is used only
by the optional artwork-authoring script, not by the application runtime.

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

## Optional local Voice Alternator (Commentary Studio)

The optional Voice Studio V2 conversion adapter uses MyShell OpenVoice V2,
whose published implementation and speaker assets are available under the MIT
licence. The preserved licence is `assets/licenses/LICENSE_OPENVOICE`.
OpenVoice source and checkpoints are not bundled into this repository or
installed when Pulse Capture opens. The explicit setup script retrieves
pinned revisions into a private, separately managed runtime only with user
action. PyTorch and NumPy are dependencies of that optional installed runtime,
with their own licences. The microphone-only recorder does not require them.
https://github.com/myshell-ai/OpenVoice
https://huggingface.co/myshell-ai/OpenVoiceV2
