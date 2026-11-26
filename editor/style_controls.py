"""Shared everyday typography controls; specialist values stay behind Advanced."""
from dataclasses import asdict
import tkinter as tk
from tkinter import ttk, colorchooser, simpledialog
from ui import theme as t
from .typography import CaptionStyle, THEMES, theme_style
from .style_preferences import load_style_library, save_style_library

FONT_SIZES=(16,20,24,28,32,36,40,48,56,64,72,88,96,120,144)
OUTLINES={'None':0,'Thin':1,'Light':2,'Medium':5,'Thick':6,'Heavy':10}
SHADOWS={'None':0,'Light':3,'Medium':4,'Strong':6,'Heavy':10}
POSITIONS={'Top left':('Top','left'),'Top centre':('Top','centre'),'Top right':('Top','right'),
           'Middle left':('Centre','left'),'Centre':('Centre','centre'),'Middle right':('Centre','right'),
           'Bottom left':('Bottom','left'),'Bottom centre':('Bottom','centre'),'Bottom right':('Bottom','right')}
COLOURS=('#FFFFFF','#FFD83D','#FF4466','#27DEF5','#32D583','#000000')


def style_values(values,theme):
    values=dict(values)
    for key in ('font_size','outline','shadow','shadow_x','shadow_y'):values[key]=int(values[key])
    for key in ('band_width','band_y','background_opacity','x_offset','y_offset','shadow_opacity'):values[key]=float(values[key])
    style=CaptionStyle(theme=theme,**values);style.validate();return style


class StyleControls(tk.Frame):
    def __init__(self,parent,position,on_change,style=None,bands=False):
        super().__init__(parent,bg=t.BG)
        self.position,self.on_change,self.bands=position,on_change,bands
        self.loading=True;self.syncing=False;self.font_popup=None
        self.enabled=tk.BooleanVar(value=style is not None)
        initial=style or CaptionStyle()
        self.theme=tk.StringVar(value=initial.theme)
        self.variables={key:(tk.BooleanVar if isinstance(value,bool) else tk.StringVar)(value=value)
                        for key,value in asdict(initial).items() if key!='theme'}
        self.basic=tk.Frame(self,bg=t.BG);self.basic.pack(fill='x')
        self.basic.columnconfigure(0,weight=3);self.basic.columnconfigure(1,weight=2)
        font=self.group(self.basic,'Font',0,0)
        self.font_button=t.button(font,'',self.open_fonts)
        self.font_button.configure(textvariable=self.variables['font_family'],anchor='w',pady=5)
        self.font_button.pack(fill='x')
        self.combo(self.group(self.basic,'Size',0,1),self.variables['font_size'],FONT_SIZES)
        formatting=self.group(self.basic,'Formatting',1,0)
        for key,title in (('bold','B'),('italic','I'),('underline','U')):
            tk.Checkbutton(formatting,text=title,variable=self.variables[key],indicatoron=False,
                           font=(t.FONT,-13,'bold' if key=='bold' else key),width=3,
                           bg=t.CONTROL,fg=t.TEXT,selectcolor='#236270',activebackground=t.LINE,
                           relief='flat',pady=4,takefocus=True).pack(side='left',padx=(0,5))
        self.colour_button(self.group(self.basic,'Text colour',1,1),'colour')
        quick=tk.Frame(self.basic,bg=t.BG);quick.grid(row=2,column=0,columnspan=2,sticky='w',pady=(0,6))
        for colour in COLOURS:
            tk.Button(quick,bg=colour,activebackground=colour,width=3,relief='flat',
                      command=lambda c=colour:self.choose_colour('colour',c),takefocus=True).pack(side='left',padx=(0,5))
        self.location=tk.StringVar()
        options=[name for name,(zone,_) in POSITIONS.items() if not bands or zone!='Centre']+['Custom']
        self.combo(self.group(self.basic,'Position',3,0),self.location,options,True).bind('<<ComboboxSelected>>',self.choose_position)
        background=self.group(self.basic,'Background',3,1)
        tk.Checkbutton(background,text='Show background',variable=self.variables['background_enabled'],
                       bg=t.BG,fg=t.TEXT,selectcolor=t.CONTROL).pack(anchor='w')
        self.outline=tk.StringVar();self.shadow=tk.StringVar()
        self.combo(self.group(self.basic,'Outline',4,0),self.outline,(*OUTLINES,'Custom'),True).bind('<<ComboboxSelected>>',self.choose_outline)
        self.combo(self.group(self.basic,'Shadow',4,1),self.shadow,(*SHADOWS,'Custom'),True).bind('<<ComboboxSelected>>',self.choose_shadow)
        preset=self.group(self.basic,'Style preset',5,0)
        self.preset=tk.StringVar(value=initial.theme)
        self.picker=self.combo(preset,self.preset,(*THEMES,*load_style_library()['presets']),True)
        self.picker.bind('<<ComboboxSelected>>',self.choose_preset)
        actions=self.group(self.basic,'',5,1)
        for title,command in (('SAVE',self.save_preset),('RESET',self.reset)):
            button=t.button(actions,title,command);button.configure(padx=9,pady=5)
            button.pack(side='left',padx=(0,4))
        self.advanced_open=tk.BooleanVar(value=False)
        self.advanced_button=t.button(self,'▸ Advanced settings',self.toggle_advanced)
        self.advanced_button.configure(anchor='w',pady=5);self.advanced_button.pack(fill='x',pady=(8,0))
        self.advanced=tk.Frame(self,bg=t.BG)
        for col in range(2):self.advanced.columnconfigure(col,weight=1)
        labels=(('x_offset','Horizontal offset'),('y_offset','Vertical offset'),('band_width','Width inside band'),
                ('band_y','Height inside band'),('highlight','Highlight words'),('highlight_colour','Highlight colour'),
                ('outline','Outline thickness'),('outline_colour','Outline colour'),('shadow','Shadow depth'),
                ('shadow_colour','Shadow colour'),('shadow_x','Shadow horizontal'),('shadow_y','Shadow vertical'),
                ('shadow_opacity','Shadow opacity'),('background_colour','Background colour'),
                ('background_opacity','Background opacity'),('animation','Animation'),('alignment','Text alignment'))
        self.opacity=tk.StringVar()
        for i,(key,label) in enumerate(labels):
            group=self.group(self.advanced,label,i//2,i%2)
            if key.endswith('colour'):self.colour_button(group,key,hex_input=True)
            elif key=='background_opacity':
                self.combo(group,self.opacity,tuple(f'{p}%' for p in range(0,101,10))).bind('<<ComboboxSelected>>',self.set_opacity)
                # Typed custom percentages also work on Enter/focus loss.
                for widget in group.winfo_children():
                    widget.bind('<Return>',self.set_opacity);widget.bind('<FocusOut>',self.set_opacity)
            elif key in ('animation','alignment'):
                self.combo(group,self.variables[key],('none','fade','pop','shake') if key=='animation' else ('left','centre','right'),True)
            else:
                tk.Entry(group,textvariable=self.variables[key],bg=t.CONTROL,fg=t.TEXT,insertbackground=t.CYAN,width=12).pack(fill='x')
        legacy=tk.Checkbutton(self.advanced,text='Use styled text (off keeps legacy appearance)',variable=self.enabled,
                             bg=t.BG,fg=t.TEXT,selectcolor=t.CONTROL)
        legacy.grid(row=9,column=0,columnspan=2,sticky='w',pady=6)
        self.status=t.label(self,'',9,t.MUTED,wraplength=400,justify='left')
        self.status.pack(fill='x',pady=3)
        for key,var in self.variables.items():var.trace_add('write',lambda *_,k=key:self.changed(k))
        self.enabled.trace_add('write',lambda *_:self.changed())
        self.position.trace_add('write',lambda *_:self.changed())
        self.loading=False;self.sync()

    def group(self,parent,label,row,col):
        group=tk.Frame(parent,bg=t.BG);group.grid(row=row,column=col,sticky='ew',padx=(0,8),pady=3)
        if label:t.label(group,label,9,t.MUTED).pack(anchor='w',pady=(0,2))
        return group

    def combo(self,parent,var,values,readonly=False):
        combo=ttk.Combobox(parent,textvariable=var,values=values,state='readonly' if readonly else 'normal',width=12)
        combo.pack(fill='x');return combo

    def colour_button(self,parent,key,hex_input=False):
        button=t.button(parent,'Choose…',lambda:self.pick_colour(self.variables[key]))
        button.configure(pady=4,padx=7);button.pack(side='right' if hex_input else 'left',fill='x',expand=True)
        def paint(*_):
            value=self.variables[key].get()
            try:button.configure(bg=value,fg='#101820' if sum(int(value[i:i+2],16) for i in (1,3,5))>390 else '#FFFFFF')
            except (tk.TclError,ValueError):pass
        self.variables[key].trace_add('write',paint);paint()
        if hex_input:tk.Entry(parent,textvariable=self.variables[key],width=9,bg=t.CONTROL,fg=t.TEXT,insertbackground=t.CYAN).pack(side='left')

    def changed(self,key=None):
        if self.loading:return
        if key and not self.enabled.get():
            self.loading=True;self.enabled.set(True);self.loading=False
        self.sync();self.on_change()

    def sync(self):
        self.outline.set(next((k for k,v in OUTLINES.items() if str(v)==self.variables['outline'].get()),'Custom'))
        self.shadow.set(next((k for k,v in SHADOWS.items() if str(v)==self.variables['shadow'].get()),'Custom'))
        try:
            custom=any(float(self.variables[k].get())!=0 for k in ('x_offset','y_offset'))
            self.location.set('Custom' if custom else next((name for name,pair in POSITIONS.items()
                if pair==(self.position.get(),self.variables['alignment'].get())),'Custom'))
            self.opacity.set(f'{float(self.variables["background_opacity"].get())*100:g}%')
        except ValueError:pass

    def read_style(self):
        if not self.enabled.get():return None
        return style_values({k:v.get() for k,v in self.variables.items()},self.theme.get())

    def set_style(self,style):
        self.loading=True;self.enabled.set(style is not None)
        values=asdict(style or CaptionStyle());self.theme.set(values.pop('theme'));self.preset.set(self.theme.get())
        for k,v in values.items():self.variables[k].set(v)
        self.loading=False;self.sync();self.on_change()

    def choose_position(self,_=None):
        if self.location.get()=='Custom':
            if not self.advanced_open.get():self.toggle_advanced()
            return
        zone,alignment=POSITIONS[self.location.get()]
        self.loading=True;self.position.set(zone);self.variables['alignment'].set(alignment)
        self.variables['x_offset'].set('0');self.variables['y_offset'].set('0');self.variables['band_y'].set('.5')
        self.loading=False;self.changed('alignment')

    def choose_outline(self,_=None):
        if self.outline.get() in OUTLINES:self.variables['outline'].set(OUTLINES[self.outline.get()])
        elif not self.advanced_open.get():self.toggle_advanced()

    def choose_shadow(self,_=None):
        if self.shadow.get() not in SHADOWS:
            if not self.advanced_open.get():self.toggle_advanced()
            return
        value=SHADOWS[self.shadow.get()];self.loading=True
        for key in ('shadow','shadow_x','shadow_y'):self.variables[key].set(value)
        self.loading=False;self.changed('shadow')

    def set_opacity(self,_=None):
        try:
            value=float(self.opacity.get().rstrip('%'))/100
            if not 0<=value<=1:raise ValueError()
            self.variables['background_opacity'].set(value);self.status.configure(text='')
        except ValueError:self.status.configure(text='Use a background opacity from 0% to 100%.',fg=t.RED)

    def toggle_advanced(self):
        opened=not self.advanced_open.get();self.advanced_open.set(opened)
        if opened:self.advanced.pack(fill='x',before=self.status)
        else:self.advanced.pack_forget()
        self.advanced_button.configure(text=('▾' if opened else '▸')+' Advanced settings')

    def open_fonts(self):
        from .font_picker import FontPicker
        if self.font_popup and self.font_popup.winfo_exists():self.font_popup.lift();return
        self.font_popup=FontPicker(self,self.variables['font_family'].get(),self.variables['font_family'].set)

    def choose_colour(self,key,value):
        variable=self.variables[key] if isinstance(key,str) else key
        variable.set(value.upper())
        data=load_style_library();data['recent']=([value.upper()]+[c for c in data['recent'] if c!=value.upper()])[:12]
        try:save_style_library(data)
        except OSError as exc:self.status.configure(text=f'Colour applied; preferences could not be saved: {exc}',fg=t.MUTED)

    def pick_colour(self,variable):
        # Same working colour chooser and recent-colour storage, with optional HEX.
        chooser=tk.Toplevel(self);chooser.title('Choose colour');chooser.configure(bg=t.BG);chooser.transient(self.winfo_toplevel())
        def choose(value):self.choose_colour(variable,value);chooser.destroy()
        colours=(*COLOURS,'#9955FF',*load_style_library()['recent'])
        for i,colour in enumerate(dict.fromkeys(colours)):
            tk.Button(chooser,bg=colour,width=4,command=lambda c=colour:choose(c)).grid(row=i//6,column=i%6,padx=4,pady=4)
        def full_picker():
            value=variable.get()
            result=colorchooser.askcolor(color=value if len(value)==7 else '#FFFFFF',parent=chooser)
            if result and result[1]:choose(result[1])
        t.button(chooser,'Custom colour…',full_picker).grid(row=4,column=0,columnspan=6,sticky='ew')
        value=tk.StringVar(value=variable.get());entry=tk.Entry(chooser,textvariable=value);entry.grid(row=5,column=0,columnspan=4,padx=4,pady=6)
        note=t.label(chooser,'Optional HEX · #RRGGBB',9,t.MUTED);note.grid(row=6,column=0,columnspan=6)
        def hex_colour():
            import re
            if re.fullmatch('#[0-9A-Fa-f]{6}',value.get()):choose(value.get())
            else:note.configure(text='Use six HEX digits, for example #FFD83D',fg=t.RED)
        t.button(chooser,'USE HEX',hex_colour).grid(row=5,column=4,columnspan=2)
        entry.bind('<Return>',lambda _:hex_colour());chooser.bind('<Escape>',lambda _:chooser.destroy())

    def choose_preset(self,_=None):
        name=self.preset.get();data=load_style_library()
        self.set_style(CaptionStyle(**data['presets'][name]) if name in data['presets'] else theme_style(name))
        self.preset.set(name)

    def save_preset(self):
        try:
            style=self.read_style()
            if style is None:raise ValueError('Choose a text style first.')
            name=simpledialog.askstring('Save style preset','Preset name:',parent=self)
            if not name or not name.strip():return
            name=name.strip()[:80]
            if name in THEMES:raise ValueError('Choose a new name to preserve the built-in preset.')
            data=load_style_library();data['presets'][name]=asdict(style);save_style_library(data)
            self.picker.configure(values=(*THEMES,*data['presets']));self.preset.set(name)
            self.status.configure(text=f'Saved preset: {name}',fg=t.GREEN)
        except (ValueError,OSError) as exc:self.status.configure(text=str(exc),fg=t.RED)

    def reset(self):self.set_style(theme_style(self.theme.get()))


def scrollable_styles(parent):
    panel=tk.Frame(parent,bg=t.BG)
    canvas=tk.Canvas(panel,bg=t.BG,highlightthickness=0)
    bar=ttk.Scrollbar(panel,orient='vertical',command=canvas.yview)
    canvas.pack(side='left',fill='both',expand=True);bar.pack(side='right',fill='y')
    canvas.configure(yscrollcommand=bar.set)
    inner=tk.Frame(canvas,bg=t.BG);item=canvas.create_window(0,0,window=inner,anchor='nw')
    inner.bind('<Configure>',lambda _:canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>',lambda e:canvas.itemconfigure(item,width=e.width))
    # A private bindtag limits wheel scrolling to this panel, never other windows.
    tag=f'StyleScroll{id(panel)}'
    def attach(widget):
        widget.bindtags((tag,*widget.bindtags()))
        for child in widget.winfo_children():attach(child)
    def wheel(event):canvas.yview_scroll(-1 if event.delta>0 else 1,'units');return 'break'
    panel.bind_class(tag,'<MouseWheel>',wheel)
    panel.after_idle(lambda:attach(inner) if panel.winfo_exists() else None)
    panel.bind('<Destroy>',lambda e:panel.unbind_class(tag,'<MouseWheel>') if e.widget is panel else None)
    return panel,inner
