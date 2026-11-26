from dataclasses import replace
from pathlib import Path
import pytest
from editor.models import MediaInfo, TrimRange
from editor.sequence import SourceClip, project_media, positions, locate, split_clip, remap_state, validate_sequence
from editor.transforms import EditOptions
from editor.cuts import CutPlan, CutRange
from editor.edit_history import EditSnapshot, EditHistory
from editor.text_overlay import Caption, TextOverlay
from editor.typography import CaptionStyle
from editor.reactions import VisualCue


def clips():
    return tuple(SourceClip(str(i),MediaInfo(Path(f'{i}.mp4'),6,640,360,24+i*6,i!=1),0,6) for i in range(3))


def state(seq):
    return EditSnapshot(TrimRange(0,18),CutPlan(),EditOptions(sequence=seq,
        text=TextOverlay(captions=(Caption(7,9,'Second clip',style=CaptionStyle(italic=True)),)),
        overlays=(VisualCue('emoji','face.laugh',7,9),)))


def test_append_duration_and_boundary_seek():
    seq=clips()
    assert project_media(seq).duration==18
    assert project_media(seq).has_audio
    assert locate(seq,6)==(seq[1],0)
    assert locate(seq,17)==(seq[2],5)
    assert locate(seq,18)==(seq[2],6)


def test_reorder_attached_and_project_wide_overlays():
    seq=clips();old=state(seq)
    new=(seq[1],seq[0],seq[2])
    moved=remap_state(old,seq,new)
    assert (moved.edits.text.captions[0].start,moved.edits.text.captions[0].end)==(1,3)
    assert moved.edits.overlays[0].start==1
    assert moved.edits.text.captions[0].style.italic
    fixed=remap_state(replace(old,edits=replace(old.edits,overlay_anchor='project')),seq,new)
    assert fixed.edits.text.captions[0].start==7
    assert fixed.edits.overlays[0].start==7


def test_split_trim_remove_duplicate_and_undo():
    seq=clips();old=state(seq)
    split,origins=split_clip(seq,1,8)
    changed=remap_state(old,seq,split,origins)
    assert len(changed.edits.text.captions)==2
    assert [(c.start,c.end) for c in changed.edits.text.captions]==[(7,8),(8,9)]
    trimmed=(seq[0],replace(seq[1],start=2),seq[2])
    changed=remap_state(old,seq,trimmed)
    assert changed.trim.end==16
    assert [(c.start,c.end) for c in changed.edits.text.captions]==[(6,7)]
    removed=remap_state(old,seq,(seq[0],seq[2]))
    assert not removed.edits.text.captions and not removed.edits.overlays
    duplicate=replace(seq[1],id='copy')
    copied=remap_state(old,seq,seq+(duplicate,),{'copy':seq[1].id})
    assert [c.start for c in copied.edits.text.captions]==[7,19]
    history=EditHistory(old);history.record(copied)
    assert history.undo()==old and history.redo()==copied


def test_cuts_and_outer_trim_follow_source_content():
    seq=clips();old=replace(state(seq),trim=TrimRange(1,17),cuts=CutPlan((CutRange(3,4),)))
    new=(seq[1],seq[0],seq[2])
    changed=remap_state(old,seq,new)
    assert [(r.start,r.end) for r in changed.cuts.ranges]==[(6,7),(9,10),(17,18)]
    assert changed.cuts.kept_duration(changed.trim)==15


def test_missing_source_and_invalid_clip():
    with pytest.raises(ValueError,match='Missing source'): validate_sequence(clips(),True)
    with pytest.raises(ValueError): split_clip(clips(),0,0)
    with pytest.raises(ValueError): validate_sequence((clips()[0],clips()[0]))
