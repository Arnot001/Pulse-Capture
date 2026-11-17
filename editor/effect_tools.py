"""Named effects edit the existing Pulse recipe; rendering remains explicit."""
import copy
import tkinter as tk
from tkinter import ttk
from ui import theme as t
from .pulse_plan import timeline_positions, validate_pulse_plan
from .reaction_library import ReactionLibrary, _atomic_json

EFFECTS = ('Punch zoom','Quick shake','Freeze-frame','Replay','Text pop',
           'Scratch interruption','Simple glitch','Fade to black','Dissolve')


class EffectPicker:
    def __init__(self, dialog, panel):
        self.dialog=dialog
        t.label(panel,'Apply an effect to a timeline element',16,t.CYAN,True).pack(anchor='w',padx=16,pady=12)
        self.index=tk.StringVar(value='1')
        self.duration=tk.StringVar(value=str(ReactionLibrary().preferences().get('freeze_duration',1.8)))
        row=tk.Frame(panel,bg=t.PANEL);row.pack(fill='x',padx=16)
        for label,var in (('Element number (1-based)',self.index),('Freeze hold (seconds)',self.duration)):
            t.label(row,label,10).pack(side='left',padx=5)
            tk.Entry(row,textvariable=var,width=8).pack(side='left',padx=4)
        self.text=tk.StringVar(value='WAIT…')
        tk.Entry(panel,textvariable=self.text,font=(t.FONT,-18,'bold')).pack(fill='x',padx=16,pady=12)
        grid=tk.Frame(panel,bg=t.PANEL);grid.pack(fill='x',padx=16)
        for i,name in enumerate(EFFECTS):
            button=t.button(grid,name.upper(),lambda n=name:self.apply(n))
            button.grid(row=i//3,column=i%3,sticky='ew',padx=4,pady=4)
            grid.columnconfigure(i%3,weight=1)
        row=tk.Frame(panel,bg=t.PANEL);row.pack(fill='x',padx=16,pady=10)
        for name in ('Remove visual effect','Delete element','Undo'):
            t.button(row,name.upper(),lambda n=name:self.apply(n)).pack(side='left',padx=4)
        t.label(panel,'Select a numbered element from the validated timeline. Freeze/replay insert after it.\n'
                'Render Preview below to review the result in Quick Edit. Undo removes the last picker change.\n'
                'Existing captions, SFX and overlays retain their exact output timestamps; review timing after inserting elements.\n'
                'A scratch interruption changes picture only. Add its sound explicitly in SOUND FX.',
                10,t.MUTED,wraplength=740,justify='left').pack(anchor='w',padx=16,pady=12)
        self.history=[]

    def apply(self, effect):
        d=self.dialog
        if d.busy:return
        try:
            if effect=='Undo':
                if self.history:d.set_plan(self.history.pop())
                return
            previous=d.get_plan();plan=copy.deepcopy(previous);plan['version']=2
            index=int(self.index.get())-1
            if not 0<=index<len(plan['timeline']):raise ValueError('Choose an existing element number.')
            item=plan['timeline'][index]
            if effect=='Freeze-frame':
                from .pulse_plan import frame_duration
                duration=float(self.duration.get());frame_duration(duration,'Freeze hold')
                if item['kind']=='title':raise ValueError('Choose a source shot or freeze.')
                at=item['source_time'] if item['kind']=='freeze' else max(item['start'],item['end']-1/d.media.fps)
                plan['timeline'].insert(index+1,dict(kind='freeze',source_time=at,duration=duration,role='punchline'))
                library=ReactionLibrary();prefs=library.preferences();prefs['freeze_duration']=duration
                _atomic_json(library.root/'preferences.json',prefs)
            elif effect=='Replay':
                if item['kind']!='shot':raise ValueError('Choose a shot to replay.')
                replay=copy.deepcopy(item);replay.pop('transition',None);replay['role']='replay'
                plan['timeline'].insert(index+1,replay)
            elif effect=='Text pop':
                start,end=timeline_positions(plan)[index]
                plan['captions'].append(dict(start=start,end=end,text=self.text.get(),zone='top',basis='joke',typography={'animation':'pop'}))
            elif effect in ('Dissolve','Fade to black'):
                item['transition']=dict(type='dissolve' if effect=='Dissolve' else 'fade_black',duration=.2)
            elif effect=='Delete element':del plan['timeline'][index]
            elif effect=='Remove visual effect':
                for key in ('effect','zoom','transition'):item.pop(key,None)
            else:
                if item['kind']=='title':raise ValueError('Choose a shot or freeze for this visual effect.')
                item['effect']={'Punch zoom':'punch_zoom','Quick shake':'shake','Scratch interruption':'scratch','Simple glitch':'glitch'}[effect]
            for element in plan['timeline']:element.pop('at',None)
            validate_pulse_plan(plan,d.media)
            self.history.append(previous);d.set_plan(plan)
        except (ValueError,KeyError) as exc:d.status.configure(text=str(exc),fg=t.RED)
