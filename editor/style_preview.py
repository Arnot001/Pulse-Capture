"""A draft style preview through Quick Edit's actual asynchronous FFmpeg renderer."""
from queue import Empty
import tkinter as tk
from ui import theme as t
from .preview import Preview


class StylePreview(tk.Canvas):
    def __init__(self,parent,window,draft):
        super().__init__(parent,bg='#080e14',height=270,highlightthickness=1,highlightbackground=t.LINE,cursor='fleur')
        self.window,self.draft=window,draft
        self.worker=Preview(window.backend.ffmpeg,window.media)
        self.token=0;self.photo=None;self.pending=None;self.closed=False
        self.timer=self.after(60,self.poll)
        self.bind('<Configure>',lambda _:self.refresh())
        self.bind('<Destroy>',lambda e:self.close() if e.widget is self else None)

    def refresh(self):
        if self.closed:return
        self.token+=1
        if self.pending:self.after_cancel(self.pending)
        self.pending=self.after(160,self.request)

    def request(self):
        self.pending=None
        try:
            edits,position=self.draft()
            edits.validate(self.window.media)
            if self.worker.media!=self.window.media:
                self.worker.close()
                self.worker=Preview(self.window.backend.ffmpeg,self.window.media)
            self.worker.request(self.token,position,max(2,self.winfo_width()-4),max(2,self.winfo_height()-4),
                                edits,False,self.window.trim,self.window.cuts)
        except (ValueError,tk.TclError) as exc:self.error(str(exc))

    def error(self,message):
        self.photo=None;self.delete('all')
        self.create_text(self.winfo_width()/2,self.winfo_height()/2,text=message,fill=t.MUTED,
                         width=max(120,self.winfo_width()-24),font=(t.FONT,-12))

    def poll(self):
        self.timer=None
        if self.closed:return
        try:
            frame=self.worker.frames.get_nowait()
            if frame.token==self.token:
                if frame.error:self.error(frame.error)
                else:
                    self.photo=tk.PhotoImage(master=self,data=frame.ppm,format='PPM')
                    self.delete('all');self.create_image(self.winfo_width()/2,self.winfo_height()/2,image=self.photo)
        except Empty:pass
        self.timer=self.after(60,self.poll)

    def point(self,event):
        if self.photo is None:return None
        width,height=self.photo.width(),self.photo.height()
        left,top=(self.winfo_width()-width)/2,(self.winfo_height()-height)/2
        if left<=event.x<=left+width and top<=event.y<=top+height:
            return (event.x-left)/width,(event.y-top)/height

    def close(self):
        if self.closed:return
        self.closed=True
        for timer in (self.pending,self.timer):
            if timer:self.after_cancel(timer)
        self.worker.close()
