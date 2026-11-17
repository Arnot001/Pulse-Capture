"""Author 64 original animated vector reactions. Pillow is build-time only.

Run from the repository root. Outputs are shipped; the editor never needs Pillow.
Each storyboard changes expression, shape or action, not just colour or position.
"""
from pathlib import Path
import hashlib
import json
import math
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'assets'/'reactions'
STORIES = {
    'Faces': [('laugh','Laughing tears'),('cry','Tears on tap'),('sob','Ugly sob'),('facepalm','Full facepalm'),
              ('shock','Jaw drop'),('eye_roll','Maximum eye roll'),('smug','Smug little grin'),('blush','Caught blushing')],
    'Comedy': [('spit_take','Spit take'),('buffering','Brain buffering'),('peek','Nosy peek'),('shrug','No idea shrug'),
               ('shades','Deal with it'),('rage','Steam-powered rage'),('confetti','Party face'),('sleep','Bored to sleep')],
    'Skulls & Ghosts': [('jaw','Skull jaw drop'),('crack','Cracking up'),('melt','Melting skull'),('ghost','Soul leaves body'),
                        ('grave','Here lies my dignity'),('brain','Brain has left'),('bones','Crossbones applause'),('dead','Dead battery skull')],
    'Questions & Hearts': [('question','One enormous question'),('doubt','Questions multiply'),('alert','Sudden realisation'),('idea','Lightbulb moment'),
                           ('heartbreak','Heart breaks'),('hearts','Heart explosion'),('loading','Still processing'),('verdict','Nope then yep')],
    'Explosions': [('boom','Comic kaboom'),('rocket','Rocket misfire'),('fuse','Fuse countdown'),('volcano','Emotional eruption'),
                   ('popcorn','Popcorn chaos'),('mind','Mind blown'),('meteor','Incoming meteor'),('mushroom','Mushroom cloud')],
    'Alarms': [('siren','Red alert siren'),('clock','Alarm clock panic'),('warning','Warning overload'),('flag','Enormous red flag'),
               ('phone','Phone will not stop'),('button','Panic button'),('radar','Suspicion radar'),('heat','Overheating')],
    'Animals': [('cat','Judgemental cat'),('dog','Very excited dog'),('frog','Frog side-eye'),('owl','Owl disbelief'),
                ('duck','Duck quack'),('crab','Crab applause'),('penguin','Penguin wipeout'),('snail','Still waiting snail')],
    'Big Reactions': [('clap','Slow clap'),('up','Thumbs up'),('down','Thumbs down'),('mic','Mic drop'),
                      ('drum','Rimshot'),('trophy','Tiny victory'),('exit','Emergency exit'),('curtain','That is all')],
}
INK='#17243c'; GOLD='#ffd344'; WHITE='#fff6e8'; RED='#ff506b'; BLUE='#59c7ff'; MINT='#63edbc'; PURPLE='#a992ff'
COLORS=[INK,GOLD,WHITE,RED,BLUE,MINT,PURPLE,'#ed944a','#7951a8','#7d94ae','#263d5e','#ffb4c0']
S=2
FONT=ROOT/'assets/fonts/DejaVuSans-Bold.ttf'


class Art:
    def __init__(self):
        self.image=Image.new('RGBA',(256*S,256*S))
        self.d=ImageDraw.Draw(self.image)

    def box(self,b):return tuple(round(x*S) for x in b)
    def oval(self,b,fill=GOLD,outline=INK,w=4):self.d.ellipse(self.box(b),fill,outline,w*S)
    def rect(self,b,fill=GOLD,outline=INK,w=4,r=8):self.d.rounded_rectangle(self.box(b),r*S,fill,outline,w*S)
    def line(self,pts,fill=INK,w=5):self.d.line([(round(x*S),round(y*S)) for x,y in pts],fill,w*S,joint='curve')
    def poly(self,pts,fill):self.d.polygon([(round(x*S),round(y*S)) for x,y in pts],fill)
    def text(self,xy,s,size=30,fill=INK,anchor='mm'):
        self.d.text((round(xy[0]*S),round(xy[1]*S)),s,font=ImageFont.truetype(str(FONT),size*S),fill=fill,anchor=anchor,
                    stroke_width=S if fill==WHITE else 0,stroke_fill=INK)
    def arc(self,b,start,end,fill=INK,w=5):self.d.arc(self.box(b),start,end,fill,w*S)
    def star(self,x,y,r=12,fill=GOLD,turn=0):
        self.poly([(x+(r if i%2==0 else r*.45)*math.cos(turn+i*math.pi/5),y+(r if i%2==0 else r*.45)*math.sin(turn+i*math.pi/5)) for i in range(10)],fill)
    def burst(self,x,y,p,color=GOLD):
        for j in range(10):
            a=j*math.tau/10
            r=35+p*70
            self.line([(x+math.cos(a)*(r-12),y+math.sin(a)*(r-12)),(x+math.cos(a)*r,y+math.sin(a)*r)],color,5)
    def face(self,x=128,y=128,r=75,color=GOLD,mood='happy',p=0):
        self.oval((x-r,y-r,x+r,y+r),color)
        for ex in (x-r*.36,x+r*.36):
            if mood=='blank':continue
            if mood in ('laugh','cry','sleep'):
                self.arc((ex-13,y-27,ex+13,y-7),190 if mood=='laugh' else 0,350 if mood=='laugh' else 180)
            elif mood=='angry':
                sign=1 if ex<x else -1
                self.line([(ex-12,y-28-sign*6),(ex+12,y-28+sign*6)])
                self.oval((ex-5,y-18,ex+5,y-4),INK,INK,1)
            else:
                self.oval((ex-13,y-28,ex+13,y+1),WHITE,INK,2)
                dx=math.sin(p*math.tau)*6 if mood=='roll' else 0
                self.oval((ex-5+dx,y-22,ex+5+dx,y-7),INK,INK,1)
        if mood in ('shock','cry','laugh'):
            h=20+(20*abs(math.sin(p*math.tau)) if mood!='shock' else 25*p)
            self.oval((x-23,y+14,x+23,y+14+h),INK,INK,1)
            if mood=='laugh':self.oval((x-14,y+22+h*.5,x+14,y+12+h),RED,RED,1)
        elif mood=='angry': self.line([(x-24,y+35),(x,y+23),(x+24,y+35)])
        elif mood=='sleep':self.oval((x-10,y+22,x+10,y+35),INK,INK,1)
        else:self.arc((x-32,y+5,x+32,y+44),5,175)
    def drop(self,x,y,size=10):
        self.poly([(x,y-size*1.6),(x-size,y),(x+size,y)],BLUE)
        self.oval((x-size,y-size*.4,x+size,y+size),BLUE,BLUE,1)
    def heart(self,x,y,size=28,color=RED):
        self.oval((x-size,y-size,x+2,y+2),color,color,1)
        self.oval((x-2,y-size,x+size,y+2),color,color,1)
        self.poly([(x-size,y-3),(x+size,y-3),(x,y+size)],color)
    def skull(self,x=128,y=115,jaw=0):
        self.oval((x-65,y-63,x+65,y+57),WHITE)
        self.rect((x-37,y+29+jaw,x+37,y+70+jaw),WHITE,r=5)
        for ex in (x-28,x+28):self.oval((ex-18,y-17,ex+18,y+13),INK,INK,1)
        self.poly([(x,y+9),(x-12,y+31),(x+12,y+31)],INK)
        for dx in (-20,0,20):self.line([(x+dx,y+43+jaw),(x+dx,y+68+jaw)],INK,3)
    def hand(self,x,y,up=True,color=GOLD):
        self.rect((x-22,y-17,x+25,y+32),color,r=12)
        self.rect((x-18,y-45 if up else y+20,x-3,y+5 if up else y+62),color,r=7)
        self.line([(x+5,y),(x+23,y),(x+5,y+10),(x+23,y+10)],INK,2)


def frame(group,key,p):
    a=Art(); s=math.sin(p*math.tau); c=math.cos(p*math.tau); pulse=(s+1)/2
    if group in ('Faces','Comedy'):
        mood={'laugh':'laugh','cry':'cry','sob':'cry','shock':'shock','eye_roll':'roll','rage':'angry','sleep':'sleep','spit_take':'shock'}.get(key,'happy')
        y=128+(4*s if key in ('laugh','sob','rage') else 0)
        if key=='peek':y=200-90*pulse
        a.face(y=y,mood=mood,p=p,color=RED if key=='rage' else GOLD)
        if key in ('laugh','cry','sob'):
            for j in range(4 if key=='sob' else 2):
                x=70 if j%2==0 else 186
                a.drop(x+8*s,115+((p+j*.25)%1)*100,9 if key!='sob' else 13)
        elif key=='facepalm':
            x=200-65*pulse;y=205-95*pulse
            a.rect((x-24,y-44,x+22,y+35),GOLD,r=20)
            for j in range(4):a.rect((x-24+j*12,y-70-(j%2)*8,x-12+j*12,y),GOLD,w=2,r=7)
        elif key=='shock':a.burst(128,128,pulse,RED)
        elif key=='eye_roll':a.text((128,223),'SERIOUSLY?',18,WHITE)
        elif key=='smug':
            a.arc((84,98,112,116),0,180,w=7);a.star(195,162,10+7*pulse,WHITE,p)
        elif key=='blush':
            for x in (75,181):a.oval((x-14,y+6,x+14,y+20),RED,RED,1)
            a.heart(206,55-15*pulse,14)
        elif key=='spit_take':
            for j in range(6):a.drop(128+(j-2.5)*20*pulse,160-45*pulse+10*j,5+3*pulse)
        elif key=='buffering':
            a.rect((75,22,181,64),WHITE,r=15)
            for j in range(3):a.oval((93+j*26,36,103+j*26,46),BLUE if int(p*6)%3==j else INK,INK,1)
        elif key=='peek':a.rect((5,209,251,255),PURPLE)
        elif key=='shrug':
            for x in (20,216):a.hand(x+10,170-35*pulse)
            a.text((128,35),'?',35,WHITE)
        elif key=='shades':
            y=15+92*min(1,p*2)
            for x in (74,143):a.rect((x,y,x+43,y+29),INK,r=5)
            a.line([(112,y+5),(148,y+5)])
        elif key=='rage':
            for j in range(3):a.arc((30+j*85,30-20*pulse,58+j*85,65),90,280,WHITE,7)
        elif key=='confetti':
            a.poly([(90,61),(128,0),(164,61)],PURPLE)
            for j in range(16):a.star(10+(j*61)%236,(j*37+p*160)%245,5,COLORS[j%len(COLORS)],p+j)
        elif key=='sleep':a.text((180+25*p,60-40*p),'Z',round(20+20*p),PURPLE)
    elif group=='Skulls & Ghosts':
        if key=='grave':
            a.rect((60,62,196,222), '#7d94ae',r=55);a.text((128,112),'RIP',36)
            a.text((128,159),'DIGNITY',19);a.oval((20,209,236,238),INK)
            a.star(210,70-30*pulse,12,WHITE,p)
        elif key=='ghost':
            a.skull(y=164)
            y=90-60*pulse;a.oval((88,y-38,168,y+38),BLUE)
            a.poly([(88,y),(88,y+55),(105,y+35),(124,y+55),(145,y+35),(168,y+55),(168,y)],BLUE)
            a.oval((105,y-10,116,y+6),INK);a.oval((140,y-10,151,y+6),INK)
        else:
            a.skull(jaw=25*pulse if key in ('jaw','dead') else 4*s)
            if key=='crack':a.line([(132,52),(112,78),(140,101),(121,124+32*pulse)],INK,5)
            elif key=='melt':
                for j in range(5):a.rect((70+j*24,175,85+j*24,200+35*((p+j*.2)%1)),WHITE,WHITE,r=7)
            elif key=='brain':
                y=60-38*pulse
                a.oval((94,y-20,166,y+22),RED);a.line([(128,y-16),(115,y),(140,y+8)],INK,3)
                a.line([(170,y),(208,y-10),(197,y-20)],MINT)
            elif key=='bones':
                for sign in (-1,1):
                    x=128+sign*(45-20*pulse)
                    a.line([(x-30,213),(x+30,195)],WHITE,12)
                    a.oval((x-38,205,x-22,221),WHITE);a.oval((x+22,187,x+38,203),WHITE)
            elif key=='dead':
                a.rect((85,211,171,241),INK,r=3);a.rect((90,216,95+65*(1-p),236),RED,RED,w=1,r=1)
    elif group=='Questions & Hearts':
        if key in ('question','doubt','alert'):
            a.oval((48,40,208,207),PURPLE if key!='alert' else GOLD)
            a.text((128+6*s,126),'!' if key=='alert' else '?',120)
            if key=='doubt':
                for j in range(3):a.text((25+j*100,35+30*math.sin(p*math.tau+j)),'?',28,BLUE)
        elif key=='idea':
            a.oval((70,45,186,160),GOLD);a.rect((102,155,154,205),'#7d94ae')
            a.line([(110,155),(110,110),(145,110),(145,155)],INK,4)
            a.burst(128,103,pulse,GOLD)
        elif key=='heartbreak':
            a.heart(128,120,75)
            a.line([(128,46),(108,93),(142,121),(115,156),(128,195)],WHITE,round(4+12*pulse))
            a.drop(187,180+35*p,9)
        elif key=='hearts':
            a.heart(128,130,45+10*pulse)
            for j in range(6):
                angle=j*math.tau/6;a.heart(128+90*p*math.cos(angle),128+90*p*math.sin(angle),10+10*(1-p))
        elif key=='loading':
            for j in range(8):
                theta=j*math.tau/8;radius=7+6*((j-int(p*8))%8)/7
                x,y=128+70*math.cos(theta),110+70*math.sin(theta)
                a.oval((x-radius,y-radius,x+radius,y+radius),BLUE,BLUE,1)
            a.text((128,218),'PROCESSING',21,WHITE)
        else:
            inset=8*pulse
            a.oval((38+inset,38+inset,218-inset,218-inset),RED if p<.5 else MINT)
            if p<.5:a.line([(84,84),(172,172)],WHITE,15);a.line([(172,84),(84,172)],WHITE,15)
            else:a.line([(75,126),(112,164),(183,87)],WHITE,15)
    elif group=='Explosions':
        if key=='boom':
            a.star(128,128,65+50*pulse,RED,p*.3);a.star(128,128,50+36*pulse,GOLD,-p*.3);a.text((128,130),'BOOM',35)
        elif key=='rocket':
            x,y=60+130*p,205-160*p
            a.poly([(x-15,y+25),(x-25,y+70),(x+8,y+30)],GOLD)
            a.poly([(x-20,y+25),(x,y-30),(x+24,y+20)],RED);a.oval((x-9,y-1,x+9,y+17),WHITE)
            a.burst(195,40,max(0,(p-.65)*3),GOLD) if p>.65 else None
        elif key=='fuse':
            a.oval((66,95,190,218),INK);a.line([(128,100),(154,57),(201,57)],'#ed944a',7)
            a.star(201-42*p,57,12+7*pulse,GOLD,p*4);a.text((128,157),str(3-min(2,int(p*3))),40,WHITE)
        elif key=='volcano':
            a.poly([(18,231),(92,116),(164,116),(240,231)],'#7951a8')
            a.oval((91,106,165,130),RED)
            for j in range(8):
                q=(p+j*.13)%1;a.oval((120+(j-3.5)*23*q,110-85*math.sin(q*math.pi),130+(j-3.5)*23*q,123-85*math.sin(q*math.pi)),GOLD,GOLD,1)
        elif key=='popcorn':
            a.poly([(73,140),(183,140),(167,231),(89,231)],RED)
            for x in (100,126,152):a.line([(x,149),(x,224)],WHITE,10)
            for j in range(8):
                q=(p+j*.13)%1;x=128+(j-3.5)*19*q;y=140-100*math.sin(q*math.pi)
                a.oval((x-12,y-12,x+12,y+12),GOLD)
        elif key=='mind':
            a.face(y=160,r=65,mood='shock',p=p)
            for j in range(7):a.star(128+(j-3)*22*p,90-70*p,10+8*p,GOLD if j%2 else RED,p+j)
        elif key=='meteor':
            x,y=220-150*p,20+160*p;a.poly([(x+20,y),(250,0),(x,y+20)],RED)
            a.oval((x-20,y-20,x+20,y+20),'#ed944a');a.burst(62,202,max(0,(p-.65)*3),GOLD) if p>.65 else None
        else:
            r=25+45*pulse;a.rect((108,114,148,231),'#ed944a',r=15)
            for x in (78,128,178):a.oval((x-r,110-r,x+r,110+r),GOLD)
            a.oval((50,213,206,242),RED)
    elif group=='Alarms':
        if key=='siren':
            a.oval((67,59,189,193),RED);a.rect((65,124,191,205),RED);a.rect((40,199,216,229),INK)
            a.poly([(128,120),(128+116*c,40+38*s),(128+116*c,188+38*s)],GOLD)
            a.oval((112+8*c,86,144+8*c,140),WHITE)
        elif key=='clock':
            a.oval((47,62,209,224),WHITE);a.line([(128,142),(128+50*s,142-50*c)],RED,6);a.line([(128,142),(97,113)])
            for x in (65,193):a.oval((x-31,24+6*s,x+31,68+6*s),GOLD)
        elif key=='warning':
            a.poly([(128,20),(246,225),(10,225)],GOLD);a.text((128+5*s,154),'!',round(95+15*pulse),RED if p<.5 else INK)
        elif key=='flag':
            a.line([(64,27),(64,236)],WHITE,8)
            a.poly([(68,30),(206,40+15*s),(187,94+15*s),(68,101)],RED)
        elif key=='phone':
            x=128+8*math.sin(p*math.tau*3);a.rect((x-47,40,x+47,222),INK);a.rect((x-36,58,x+36,188),BLUE)
            a.text((x,118),'RING',19);a.arc((14,85,65,160),100,260,RED);a.arc((191,85,242,160),-80,80,RED)
        elif key=='button':
            a.oval((35,147,221,232),INK);a.oval((45,108+20*pulse,211,204),RED);a.text((128,156+12*pulse),'PANIC',28,WHITE)
        elif key=='radar':
            a.oval((29,29,227,227),INK)
            for r in (30,60,90):a.arc((128-r,128-r,128+r,128+r),0,360,MINT,2)
            a.line([(128,128),(128+95*c,128+95*s)],MINT,5);a.oval((169,68,179,78),RED,RED,1)
        else:
            a.rect((107,32,149,201),WHITE,r=20);a.oval((92,175,164,247),RED)
            a.rect((118,170-115*pulse,138,208),RED,RED,1,7);a.text((199,60),'HOT',23,RED)
    elif group=='Animals':
        if key in ('cat','dog','frog','owl','duck'):
            color={'cat':'#ed944a','dog':'#ed944a','frog':MINT,'owl':PURPLE,'duck':GOLD}[key]
            if key=='cat':a.poly([(51,98),(34,17),(109,67)],color);a.poly([(147,67),(222,17),(205,98)],color)
            if key=='dog':
                for x in (40,216):a.oval((x-25,64+10*s,x+25,183+10*s),'#7951a8')
            a.face(y=136+(8*s if key=='dog' else 0),color=color,mood='blank' if key=='frog' else 'roll' if key=='cat' else 'shock',p=p)
            if key=='cat':
                for y in (139,154):a.line([(25,y),(83,y+4)],INK,3);a.line([(173,y+4),(231,y)],INK,3)
            elif key=='dog':a.oval((112,172,144,208+14*pulse),RED);a.oval((112,140,144,157),INK)
            elif key=='frog':
                for x in (84,172):a.oval((x-26,48,x+26,100),MINT);a.oval((x-10+9*s,60,x+10+9*s,83),INK)
            elif key=='owl':
                for x in (88,168):a.oval((x-30,88,x+30,146),WHITE);a.oval((x-7,104,x+7,129),INK)
                a.poly([(113,151),(143,151),(128,172)],GOLD)
            else:a.oval((111,147,221,170+25*pulse),'#ed944a')
        elif key=='crab':
            a.oval((68,126,188,210),RED)
            for x in (91,165):a.line([(x,134),(x,95)],RED,8);a.oval((x-10,83,x+10,105),WHITE);a.oval((x-4,90,x+4,99),INK)
            for sign in (-1,1):
                x=128+sign*(80-25*pulse);a.line([(128+sign*45,170),(x,106)],RED,12)
                a.arc((x-23,65,x+23,113),35+30*pulse,325-30*pulse,RED,14)
                for j in range(3):a.line([(128+sign*50,180+j*9),(128+sign*95,175+j*16)],RED,6)
        elif key=='penguin':
            a.oval((75,52,181,221),INK);a.oval((91,113,165,214),WHITE)
            for x in (106,150):a.oval((x-6,80,x+6,96),WHITE)
            a.poly([(116,104),(140,104),(128,118)],GOLD)
            a.line([(75,140),(40,120+50*pulse)],INK,12);a.line([(181,140),(218,120+50*pulse)],INK,12)
            a.image=a.image.rotate(65*max(0,s),Image.Resampling.BICUBIC)
        else:
            a.rect((40,177,229,216),MINT,r=19);a.oval((65,99,173,207),PURPLE)
            a.arc((85,119,153,187),0,300,INK,5);a.arc((103,137,135,169),0,300,INK,4)
            for x in (195,219):a.line([(x,180),(x+5*s,143)],MINT,7);a.oval((x-5+5*s,130,x+9+5*s,145),WHITE)
            a.text((128,54),'ANY DAY NOW',18,WHITE)
    else:
        if key in ('clap','up','down'):
            if key=='clap':
                a.hand(90+25*pulse,125);a.hand(166-25*pulse,125)
                if pulse>.8:a.burst(128,125,(pulse-.8)*4,GOLD)
            else:
                a.hand(128,115+10*s,up=key=='up',color=MINT if key=='up' else RED)
                a.text((128,226),'NICE' if key=='up' else 'NOPE',30,WHITE)
        elif key=='mic':
            y=50+140*p*p;a.rect((114,y,140,y+61),INK);a.oval((98,y-26,156,y+30),'#7d94ae')
            for j in range(4):a.line([(107,y-10+j*7),(148,y-10+j*7)],INK,2)
            a.line([(33,235),(223,235)],MINT,6)
            if p>.8:a.burst(128,222,(p-.8)*4,WHITE)
        elif key=='drum':
            a.rect((54,133,202,212),RED);a.oval((54,111,202,156),WHITE)
            a.line([(55,50),(115,120+15*s)],GOLD,9);a.line([(202,50),(143,120-15*s)],GOLD,9)
            a.text((128,237),'BA DUM TSS',19,WHITE)
        elif key=='trophy':
            a.rect((108,135,148,206),GOLD);a.rect((78,201,178,232),INK)
            a.arc((25,62,99,144),70,290,GOLD,12);a.arc((157,62,231,144),-110,110,GOLD,12)
            a.poly([(65,56),(191,56),(174,143),(128,168),(82,143)],GOLD)
            a.star(128,101,26,WHITE,p*.4);a.star(218,30,10+7*pulse,MINT,p)
        elif key=='exit':
            a.rect((130,35,233,235),MINT);a.rect((145,49,219,226),INK);x=55+115*p
            a.oval((x-13,86,x+13,112),WHITE);a.line([(x,112),(x,160),(x-22*s,197)],WHITE,10)
            a.line([(x,160),(x+25*s,198)],WHITE,10);a.line([(x-25,138),(x+25,130)],WHITE,8)
            a.text((181,19),'EXIT',22,MINT)
        else:
            a.rect((14,30,242,232),INK)
            width=25+95*pulse
            a.rect((14,30,14+width,232),RED,r=0);a.rect((242-width,30,242,232),RED,r=0)
            for x in range(25,240,20):
                if x<14+width or x>242-width:a.line([(x,35),(x,226)],'#ffb4c0',3)
            a.rect((8,15,248,43),GOLD)
    return a.image.resize((256,256),Image.Resampling.LANCZOS)


def build():
    OUT.mkdir(parents=True,exist_ok=True)
    palette=Image.new('P',(1,1))
    # Transparent index zero, with a fixed antialias-friendly palette per file.
    catalogue=[]
    for group,stories in STORIES.items():
        for key,name in stories:
            asset_id='reaction.'+key
            pictures=[frame(group,key,i/24) for i in range(24)]
            sheet=Image.new('RGB',(256*6,256*4),'#17243c')
            for i,im in enumerate(pictures):sheet.paste(im,(i%6*256,i//6*256),im)
            palette=sheet.quantize(colors=254)
            colors=[0,0,0]+palette.getpalette()[:254*3]+[255,255,255]
            palette.putpalette(colors)
            frames=[]
            for im in pictures:
                indexed=im.convert('RGB').quantize(palette=palette,dither=Image.Dither.NONE)
                indexed.paste(0,mask=im.getchannel('A').point(lambda alpha:255 if alpha<128 else 0))
                frames.append(indexed)
            path=OUT/(asset_id+'.gif')
            frames[0].save(path,save_all=True,append_images=frames[1:],duration=80,loop=0,
                           transparency=0,disposal=2,optimize=False)
            with Image.open(path) as gif:
                delays=[]
                for i in range(gif.n_frames):
                    gif.seek(i);delays.append(gif.info.get('duration',80)/1000)
            # Fast list thumbnails require no full GIF decode on the UI thread.
            thumb=OUT/(asset_id+'.png');pictures[6].resize((40,40),Image.Resampling.LANCZOS).save(thumb)
            catalogue.append(dict(id=asset_id,name=name,category=group,kind='gif',suffix='.gif',width=256,height=256,
                                  frames=len(delays),delays=delays,duration=round(sum(delays),6),
                                  sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                  source='Pulse original vector animation',artist='Pulse Capture',
                                  licence='Pulse Original Media',attribution='',licence_record='assets/licenses/PULSE_ORIGINAL_MEDIA.md'))
    (OUT/'catalogue.json').write_text(json.dumps(catalogue,indent=2)+'\n',encoding='utf-8')
    print(f'Built {len(catalogue)} original GIFs with thumbnails in {OUT}')


if __name__=='__main__':build()
