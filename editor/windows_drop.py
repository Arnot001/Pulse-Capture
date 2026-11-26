"""Native Windows file-drop bridge; no extra Tk extension or external dependency."""
import os
import ctypes
from ctypes import wintypes


class FileDrop:
    def __init__(self, widget, callback):
        self.widget=widget
        self.hwnd=None
        if os.name!='nt':return
        self.user=ctypes.WinDLL('user32',use_last_error=True)
        self.shell=ctypes.WinDLL('shell32',use_last_error=True)
        self.proc_type=ctypes.WINFUNCTYPE(ctypes.c_ssize_t,wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM)
        self.set_proc=self.user.SetWindowLongPtrW
        self.set_proc.argtypes=(wintypes.HWND,ctypes.c_int,ctypes.c_void_p)
        self.set_proc.restype=ctypes.c_void_p
        self.user.CallWindowProcW.argtypes=(ctypes.c_void_p,wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM)
        self.user.CallWindowProcW.restype=ctypes.c_ssize_t
        self.shell.DragAcceptFiles.argtypes=(wintypes.HWND,wintypes.BOOL)
        self.shell.DragQueryFileW.argtypes=(wintypes.HANDLE,wintypes.UINT,wintypes.LPWSTR,wintypes.UINT)
        self.shell.DragQueryFileW.restype=wintypes.UINT
        self.shell.DragFinish.argtypes=(wintypes.HANDLE,)
        self.hwnd=widget.winfo_id()
        def receive(hwnd,msg,wp,lp):
            if msg==0x233:
                try:
                    files=[]
                    count=self.shell.DragQueryFileW(wp,0xFFFFFFFF,None,0)
                    for i in range(min(count,64)):
                        length=self.shell.DragQueryFileW(wp,i,None,0)
                        buffer=ctypes.create_unicode_buffer(length+1)
                        self.shell.DragQueryFileW(wp,i,buffer,length+1)
                        files.append(buffer.value)
                    widget.after_idle(lambda:callback(tuple(files)))
                finally:self.shell.DragFinish(wp)
                return 0
            return self.user.CallWindowProcW(self.previous,hwnd,msg,wp,lp)
        self.proc=self.proc_type(receive)
        self.previous=self.set_proc(self.hwnd,-4,ctypes.cast(self.proc,ctypes.c_void_p))
        if not self.previous:
            self.hwnd=None
            raise OSError('Could not attach file drop handler.')
        self.shell.DragAcceptFiles(self.hwnd,True)

    def close(self):
        if self.hwnd:
            self.shell.DragAcceptFiles(self.hwnd,False)
            self.set_proc(self.hwnd,-4,self.previous)
            self.hwnd=None
