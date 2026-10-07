"""PULSE // CAPTURE desktop entry point."""
import sys


def main():
    if sys.platform != 'win32':
        raise SystemExit('Pulse Capture requires Windows 10 or 11.')
    from capture.window_picker import enable_dpi_awareness
    enable_dpi_awareness()
    from ui.app import CaptureApp
    CaptureApp().mainloop()


if __name__ == '__main__':
    main()
