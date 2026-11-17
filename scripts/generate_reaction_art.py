"""Build original Pulse vector-like emoji PNGs. Pillow is authoring-only, not runtime."""
from pathlib import Path
import math
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]/'assets'/'emoji'
ROOT.mkdir(exist_ok=True)
INK = '#18243a'
YELLOW = '#ffd23c'


def make(name):
    im = Image.new('RGBA',(768,768))
    d = ImageDraw.Draw(im)
    def ellipse(box,fill,outline=None,width=3):
        d.ellipse(tuple(round(v*3) for v in box),fill,outline,width=width*3)
    def poly(points,fill):
        d.polygon([(int(x*3),int(y*3)) for x,y in points],fill)
    def line(points,fill=INK,width=7):
        d.line([(int(x*3),int(y*3)) for x,y in points],fill,width*3,joint='curve')
    if name in ('laugh','cry','shock','dog','cat'):
        if name=='cat':
            poly([(30,100),(24,12),(100,52)],'#ef9f3d');poly([(156,52),(232,12),(226,100)],'#ef9f3d')
        if name=='dog':
            ellipse((4,34,82,204),'#78462d');ellipse((174,34,252,204),'#78462d')
        ellipse((25,24,231,232),'#efb66b' if name=='dog' else '#ef9f3d' if name=='cat' else YELLOW,INK,4)
        if name=='laugh':
            line([(61,99),(79,87),(97,100)]);line([(159,100),(177,87),(195,99)])
            ellipse((65,119,192,205),INK);ellipse((91,167,165,202),'#fa668b');line([(73,129),(183,129)],'#ffffff',12)
            ellipse((27,115,55,166),'#52b8ff');ellipse((201,115,229,166),'#52b8ff')
        elif name=='cry':
            line([(61,90),(96,103)]);line([(160,103),(195,90)])
            for x in (69,169):poly([(x,104),(x+18,104),(x+23,203),(x-5,203)],'#54bafa')
            ellipse((96,144,160,196),INK)
        elif name=='shock':
            for x in (65,160):ellipse((x,73,x+32,116),'#ffffff',INK)
            ellipse((104,140,152,204),INK)
        else:
            for x in (75,166):ellipse((x,93,x+16,119),INK)
            ellipse((88,132,168,198),'#fff0d6');poly([(111,140),(145,140),(128,160)],INK)
            line([(128,159),(128,176),(114,182)],width=4);line([(128,176),(142,182)],width=4)
            if name=='cat':
                for y in (140,158):line([(35,y),(87,y+5)],width=3);line([(169,y+5),(221,y)],width=3)
    elif name=='skull':
        ellipse((32,16,224,201),'#ffffff',INK,5)
        poly([(70,165),(186,165),(178,230),(78,230)],'#ffffff')
        ellipse((62,79,111,137),INK);ellipse((145,79,194,137),INK)
        poly([(128,133),(112,158),(144,158)],INK)
        for x in (94,117,140,163):line([(x,194),(x,228)],width=4)
    elif name=='heart':
        ellipse((18,35,140,159),'#ff4f78');ellipse((116,35,238,159),'#ff4f78')
        poly([(25,118),(231,118),(128,234)],'#ff4f78');line([(52,71),(77,61)],'#ffb2c4',8)
    elif name=='star':
        pts=[(128+ (112 if i%2==0 else 50)*math.sin(i*math.pi/5),128-(112 if i%2==0 else 50)*math.cos(i*math.pi/5)) for i in range(10)]
        poly(pts,YELLOW);ellipse((87,100,103,122),INK);ellipse((153,100,169,122),INK);line([(108,150),(128,161),(148,150)],width=5)
    elif name=='alert':
        poly([(128,15),(247,228),(9,228)],INK);poly([(128,38),(226,214),(30,214)],YELLOW)
        line([(128,86),(128,155)],width=17);ellipse((119,176,137,194),INK)
    elif name=='siren':
        ellipse((55,60,201,203),'#ff465f',INK,4);poly([(56,129),(200,129),(206,211),(50,211)],'#ff465f')
        poly([(32,205),(224,205),(224,231),(32,231)],INK);line([(86,106),(97,85)],'#ffadb7',10)
        for a,b in (((128,9),(128,34)),((24,45),(43,64)),((213,64),(232,45))):line([a,b],YELLOW,8)
    elif name=='bulb':
        ellipse((58,20,198,170),YELLOW,INK,4);poly([(87,142),(169,142),(157,205),(99,205)],YELLOW)
        for y in (201,215,229):line([(100,y),(156,y)],INK,10)
        line([(98,73),(85,99)],'#fff8c5',9)
    elif name=='fire':
        poly([(132,7),(150,68),(188,37),(212,118),(239,159),(220,217),(162,245),(88,238),(30,194),(26,144),(75,72),(72,132)],'#ff6b25')
        poly([(133,92),(153,149),(178,127),(190,191),(153,224),(103,224),(70,187),(100,135),(103,177)],YELLOW)
    im.resize((256,256),Image.Resampling.LANCZOS).save(ROOT/f'emoji.{name}.png')


if __name__=='__main__':
    for name in ('skull','laugh','cry','shock','heart','star','dog','cat','bulb','fire','alert','siren'):
        make(name)
