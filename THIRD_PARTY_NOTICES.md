# Third-party components

The local reference-speaker extraction adapter follows the OpenVoice
ToneColorConverter.extract_se algorithm, Copyright 2024 MyShell.ai, MIT licensed.
The full notice is in `assets/licenses/LICENSE_OPENVOICE`. The pinned source is
https://github.com/myshell-ai/OpenVoice/tree/74a1d147b17a8c3092dd5430504bd83ef6c7eb23
and the separately installed OpenVoice V2 model is MIT licensed:
https://huggingface.co/myshell-ai/OpenVoiceV2.
Reference audio and generated speaker embeddings are private user assets and
are not bundled. Their permissions are separate from the software licence.

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
