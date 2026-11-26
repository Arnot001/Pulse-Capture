"""Virtualised installed-font popup. Workers discover files; only Tk draws rows."""
from queue import Queue, Empty
import threading
import tkinter as tk
import tkinter.font as tkfont
from ui import theme as t
from .caption_fonts import installed_fonts
from .style_preferences import load_style_library, remember_font


def font_rows(names, query, selected, preferences):
    available = set(names)
    pinned = [selected, *preferences.get('recent_fonts',()), *preferences.get('favourite_fonts',())]
    ordered = dict.fromkeys([*(n for n in pinned if n in available), *sorted(available,key=str.casefold)])
    return [n for n in ordered if query.casefold() in n.casefold()]


class FontPicker(tk.Toplevel):
    ROW = 48

    def __init__(self, parent, selected, choose):
        super().__init__(parent)
        self.title('Choose font'); self.configure(bg=t.BG)
        self.transient(parent.winfo_toplevel())
        self.geometry(f'520x{min(470,self.winfo_screenheight()-100)}')
        self.minsize(390,300)
        self.selected, self.choose = selected, choose
        self.names, self.rows, self.index = (), [], 0
        self.preferences = load_style_library()
        self.tk_families={name.casefold() for name in tkfont.families(self)}
        self.queue = Queue(); self.closed = False; self.timer = None
        self.query = tk.StringVar()
        entry = tk.Entry(self,textvariable=self.query,bg=t.CONTROL,fg=t.TEXT,insertbackground=t.CYAN)
        entry.pack(fill='x',padx=12,pady=12);entry.focus_set()
        self.query.trace_add('write',lambda *_:self.filter())
        panel=tk.Frame(self,bg=t.BG);panel.pack(fill='both',expand=True,padx=12)
        self.canvas=tk.Canvas(panel,bg=t.PANEL,highlightthickness=0,takefocus=True)
        bar=tk.Scrollbar(panel,command=self.scroll);bar.pack(side='right',fill='y')
        self.canvas.pack(fill='both',expand=True)
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.bind('<Configure>',lambda _:self.draw())
        self.canvas.bind('<MouseWheel>',self.wheel)
        self.canvas.bind('<Button-1>',self.click)
        self.bind('<Down>',lambda _:self.move(1));self.bind('<Up>',lambda _:self.move(-1))
        self.bind('<Return>',lambda _:self.accept());self.bind('<Escape>',lambda _:self.destroy())
        self.note=t.label(self,'Loading installed fonts…',9,t.MUTED,wraplength=490)
        self.note.pack(fill='x',padx=12,pady=10)
        self.protocol('WM_DELETE_WINDOW',self.destroy)
        # The worker captures only a queue, never a Tk object or bound method.
        queue=self.queue
        def discover():
            try:queue.put((tuple(installed_fonts()),None))
            except Exception as exc:queue.put(((),str(exc)))
        threading.Thread(target=discover,daemon=True).start()
        self.timer=self.after(40,self.poll)

    def poll(self):
        self.timer=None
        try:names,error=self.queue.get_nowait()
        except Empty:
            self.timer=self.after(40,self.poll);return
        self.names=names;self.filter()
        self.note.configure(text=error or ('Selected font unavailable here; rendering uses the existing fallback. '
            if self.selected not in names else '')+'★ Favourite · Recent fonts first · Enter selects · Escape closes')

    def filter(self):
        self.rows=font_rows(self.names,self.query.get(),self.selected,self.preferences)
        self.index=self.rows.index(self.selected) if self.selected in self.rows else 0
        self.canvas.configure(scrollregion=(0,0,1,len(self.rows)*self.ROW))
        self.canvas.yview_moveto(0);self.draw()

    def draw(self):
        self.canvas.delete('all')
        top=self.canvas.canvasy(0);width=max(200,self.canvas.winfo_width())
        first=max(0,int(top//self.ROW));last=min(len(self.rows),first+int(self.canvas.winfo_height()/self.ROW)+2)
        for index in range(first,last):
            name=self.rows[index];y=index*self.ROW
            if index==self.index:self.canvas.create_rectangle(0,y,width,y+self.ROW,fill='#17464f',outline=t.CYAN)
            self.canvas.create_text(17,y+24,text='★' if name in self.preferences.get('favourite_fonts',()) else '☆',fill=t.CYAN,font=(t.FONT,-18))
            # Always retain a readable name, even if a symbol face has no letters.
            label=name+(' · list sample uses fallback' if name.casefold() not in self.tk_families else '')
            self.canvas.create_text(40,y+10,text=label,anchor='w',fill=t.MUTED,font=(t.FONT,-10))
            self.canvas.create_text(40,y+31,text=name+'   Aa Bb Cc',anchor='w',fill=t.TEXT,font=(name,-18))
        if not self.rows:self.canvas.create_text(16,24,text='No matching installed fonts',anchor='w',fill=t.MUTED)

    def scroll(self,*args):self.canvas.yview(*args);self.draw()
    def wheel(self,event):self.scroll('scroll',-1 if event.delta>0 else 1,'units');return 'break'

    def move(self,step):
        self.index=max(0,min(len(self.rows)-1,self.index+step))
        top=self.canvas.canvasy(0);y=self.index*self.ROW;height=self.canvas.winfo_height()
        if y<top or y+self.ROW>top+height:
            self.canvas.yview_moveto(max(0,y-height/2)/max(1,len(self.rows)*self.ROW))
        self.draw();return 'break'

    def click(self,event):
        index=int(self.canvas.canvasy(event.y)//self.ROW)
        if not 0<=index<len(self.rows):return
        self.index=index
        if event.x<34:
            try:remember_font(self.rows[index],True)
            except OSError as exc:self.note.configure(text=str(exc));return
            self.preferences=load_style_library();self.draw()
        else:self.accept()

    def accept(self):
        if not self.rows:return 'break'
        name=self.rows[self.index]
        try:remember_font(name)
        except OSError:pass  # A read-only preferences folder must not block styling.
        self.choose(name);self.destroy();return 'break'

    def destroy(self):
        if self.closed:return
        self.closed=True
        if self.timer:self.after_cancel(self.timer)
        super().destroy()
