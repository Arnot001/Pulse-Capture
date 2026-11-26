"""Render styled whole-clip text and captions over a mixed-source sequence."""
from dataclasses import replace
import os
import pytest
from tests.test_sequence_render import sequence, run
from editor.transforms import FULL_FRAME_FORMAT
from editor.text_overlay import TextOverlay,Caption,TextResources
from editor.typography import CaptionStyle
from editor.models import TrimRange
from editor.cuts import CutPlan
from editor.ffmpeg_export import build_export_command
from editor.preview import preview_command
from editor.project_file import save_project,load_project
from editor.edit_history import EditSnapshot

pytestmark=pytest.mark.skipif(os.environ.get('PULSE_RUN_FFMPEG_TESTS')!='1',reason='Opt-in FFmpeg')


@pytest.mark.parametrize('preset',('Original',FULL_FRAME_FORMAT))
def test_style_preview_export_and_project_match_across_aspect_ratios(sequence,preset):
    ffmpeg,probe,media,edits,folder=sequence
    style=CaptionStyle(font_family='Arial',font_size=64,colour='#FFD83D',outline_colour='#103355',
                       italic=True,underline=True,background_enabled=True,background_opacity=.4,animation='none')
    text=TextOverlay(True,'Whole clip',position='Top',style=style,
                     captions=(Caption(.2,3.4,'Timed caption',style=replace(style,colour='#FF4466')),))
    edits=replace(edits.with_format(media,preset),text=text)
    trim=TrimRange(0,media.duration);cuts=CutPlan()
    with TextResources(text) as resources:
        out=folder/'styled.mp4'
        run(build_export_command(ffmpeg,media,trim,out,edits,text_resources=resources,cuts=cuts))
        still=run(preview_command(ffmpeg,media,1.7,360,320,edits,False,resources,trim,cuts))
        frame=run([ffmpeg,'-v','error','-ss','1.7','-i',str(out),'-frames:v','1','-vf',
                   'scale=360:320:force_original_aspect_ratio=decrease,setsar=1','-c:v','ppm','-f','image2pipe','pipe:1'])
        expected=still.split(b'\n',3)[-1];actual=frame.split(b'\n',3)[-1]
        assert len(expected)==len(actual)
        assert sum(abs(a-b) for a,b in zip(expected,actual))/len(expected)<4
    state=EditSnapshot(trim,cuts,edits);project=folder/'styled.pulse.json'
    save_project(project,media,state);assert load_project(project)==(media,state)
