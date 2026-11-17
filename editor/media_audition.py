"""Cancelable, serial FFmpeg auditions; no decoding or synthesis on Tk's thread."""
from pathlib import Path
from queue import Queue, Empty
import subprocess
import tempfile
import threading

from capture.ffmpeg_backend import process_options


class Audition:
    def __init__(self, owner, notify):
        self.owner, self.notify = owner, notify
        self.events = Queue()
        self.lock = threading.Condition()
        self.pending = self.process = None
        self.closed = False
        self.token = 0
        self.temp = tempfile.TemporaryDirectory(prefix='pulse-media-preview-')
        self.worker = threading.Thread(target=self.run, daemon=True, name='Pulse media audition')
        self.worker.start()
        self.timer = owner.after(60, self.poll)

    def stop(self):
        with self.lock:
            self.token += 1
            self.pending = None
            if self.process and self.process.poll() is None:
                try: self.process.terminate()
                except OSError: pass
        try:
            import winsound
            winsound.PlaySound(None, 0)
        except (ImportError, RuntimeError): pass

    def play(self, command_factory):
        self.stop()
        with self.lock:
            self.pending = (self.token, command_factory)
            self.lock.notify()
        self.notify('Preparing preview…', False)

    def run(self):
        try:
            while True:
                with self.lock:
                    self.lock.wait_for(lambda:self.closed or self.pending is not None)
                    if self.closed: return
                    token, factory = self.pending
                    self.pending = None
                destination = Path(self.temp.name)/f'{token}.wav'
                try:
                    command = factory(destination)
                    with self.lock:
                        if self.closed or token != self.token: continue
                        self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **process_options())
                        process = self.process
                    try:
                        _, error = process.communicate(timeout=45)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.communicate()
                        raise ValueError('Audio preview timed out.')
                    if process.returncode: raise ValueError('Could not preview this audio: '+error.decode(errors='replace')[-300:])
                    self.events.put((token, destination, None))
                except Exception as exc:
                    self.events.put((token, None, str(exc)))
                finally:
                    with self.lock: self.process = None
        finally:
            self.temp.cleanup()

    def poll(self):
        if self.closed: return
        try:
            while True:
                token, path, error = self.events.get_nowait()
                if token != self.token: continue
                if error: self.notify(error, True)
                else:
                    try:
                        import winsound
                        winsound.PlaySound(str(path), winsound.SND_FILENAME|winsound.SND_ASYNC)
                        self.notify('Playing preview. Stop ends playback.', False)
                    except (ImportError, RuntimeError) as exc: self.notify(str(exc), True)
        except Empty: pass
        self.timer = self.owner.after(60, self.poll)

    def close(self):
        if self.closed: return
        self.stop()
        self.owner.after_cancel(self.timer)
        # The worker can finish a long synthesis after the window closes. It
        # must not become the last owner of Tk objects on a background thread.
        self.owner = self.notify = None
        with self.lock:
            self.closed = True
            self.lock.notify()
