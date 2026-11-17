"""Rebuild the auditable inventory; optionally render a contact sheet for review."""
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from editor.reaction_library import ReactionLibrary, SFX, EMOJI, bundled_gifs
from editor.sound_design import RECIPES
from editor.music import TRACKS


def build():
    library=ReactionLibrary()
    records=[]
    for key in SFX:
        item=library.metadata(key)
        item['recipe_source']='editor/sound_design.py' if key in RECIPES else 'editor/reaction_library.py'
        item['recipe_sha256']=hashlib.sha256(repr(RECIPES.get(key,SFX[key])).encode()).hexdigest()
        records.append(item)
    records.extend(dict(item,path=f'assets/reactions/{key}.gif') for key,item in bundled_gifs().items())
    for key in EMOJI:
        path=library.resolve(key)
        records.append(dict(id=key,kind='emoji',path=path.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            licence='Pulse Original Media',licence_record='assets/licenses/PULSE_ORIGINAL_MEDIA.md'))
    for name in TRACKS:
        records.append(dict(id=TRACKS[name]['slug'],name=name,kind='music',source='editor/music.py',licence='Pulse Original Media',
                            licence_record='assets/licenses/PULSE_ORIGINAL_MEDIA.md'))
    records.append(dict(id='dejavu-sans-bold',kind='font',path='assets/fonts/DejaVuSans-Bold.ttf',source='DejaVu Fonts',
                        licence='DejaVu / Bitstream Vera font licence',licence_record='assets/licenses/LICENSE_DEJAVU'))
    (ROOT/'assets/media_manifest.json').write_text(json.dumps(dict(version=1,assets=records),indent=2)+'\n',encoding='utf-8')
    if len(sys.argv)>1:
        from PIL import Image,ImageDraw,ImageFont
        output=Path(sys.argv[1]);output.mkdir(parents=True,exist_ok=True)
        sheet=Image.new('RGB',(1280,1280),'#0d1421');draw=ImageDraw.Draw(sheet)
        font=ImageFont.truetype(str(ROOT/'assets/fonts/DejaVuSans-Bold.ttf'),11)
        for i,(key,item) in enumerate(bundled_gifs().items()):
            with Image.open(library.resolve(key)) as gif:
                gif.seek(min(6,gif.n_frames-1));thumb=gif.convert('RGBA').resize((128,128))
            x,y=(i%8)*160,(i//8)*160
            sheet.paste(thumb,(x+16,y+4),thumb)
            draw.text((x+80,y+140),item['name'],fill='#ffffff',font=font,anchor='mm')
        sheet.save(output/'reaction-contact-sheet.png')
    print(f'Inventory: {len(SFX)} sound effects, {len(bundled_gifs())} GIFs, {len(EMOJI)} emoji, {len(TRACKS)} music tracks.')


if __name__=='__main__':build()
