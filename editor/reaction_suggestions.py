"""Reviewable local caption-to-sound matches; no semantic vision or paid calls."""
from .soundboard import normalized, reaction_groups, search_text
from .reactions import SoundCue


def is_voice(item):
    # Preserve recognition of older SAPI imports that predate audio_type.
    return (item.get('audio_type') == 'windows_voice' or item.get('category') == 'Voices'
            or item.get('name', '').startswith('Voice - '))


def output_intervals(start, end, cuts, trim, speed):
    for segment in cuts.kept_segments(trim):
        left, right = max(start, segment.start), min(end, segment.end)
        if right > left:
            yield cuts.source_elapsed(left, trim)/speed, cuts.source_elapsed(right, trim)/speed


def caption_context(window):
    """Use the same source/output mapping as Quick Edit, including assembled plans."""
    convert = lambda a,b: output_intervals(a,b,window.cuts,window.trim,window.edits.speed)
    captions = [dict(start=a, end=b, text=c.text) for c in window.edits.text.captions
                for a,b in convert(c.start,c.end)]
    total = window.edits.output_duration(window.cuts.kept_duration(window.trim))
    speech = []
    if window.media.has_audio:
        if window.auto_candidate and window.auto_candidate[1]:
            speech = [span for cue in window.auto_candidate[1]
                      for span in convert(cue['start'],cue['end'])]
        elif window.pulse_candidate:
            from .pulse_plan import timeline_positions
            plan = window.pulse_candidate[0]
            # A Pulse freeze/title is silent. Treat every audible shot as
            # protected when a speech transcript is unavailable.
            speech = [span for item,(a,b) in zip(plan['timeline'],timeline_positions(plan))
                      if item['kind']=='shot' and item.get('volume',1)>0
                      for span in convert(a,b)]
        else:
            speech = [(0,total)]  # Unknown speech is not proof of silence.
    return captions, speech, total


def suggest(library, captions, speech, total, existing=(), dismissed=()):
    """At most three distinct, short imported reactions, in dialogue-free gaps."""
    used = {cue.asset_id for cue in existing} | set(dismissed)
    occupied = [(cue.at-.2, cue.at+cue.length(library)+.2) for cue in existing]
    occupied += [(max(0,a-.15), b+.15) for a,b in speech]
    items = [item for item in library.items('sfx') if item['id'].startswith('import.')
             and not is_voice(item) and .1 <= item.get('duration',0) <= 4]
    result = []
    for caption in sorted(captions,key=lambda c:c['start']):
        context = dict(name=caption['text'], kind='sfx')
        groups = reaction_groups(context)
        words = {w for w in normalized(caption['text']).split() if len(w)>3} - {
            'what','where','when','that','this','with','from','have','does','there','they','your','just','really'}
        ranked = []
        for item in items:
            if item['id'] in used:continue
            shared = len(words & set(search_text(item).split()))
            score = 3*len(groups & reaction_groups(item)) + (shared if shared>=2 else 0)
            if score:ranked.append((score,item))
        for _,item in sorted(ranked,key=lambda pair:(-pair[0],pair[1]['id'])):
            try:library.resolve(item['id'],'sfx')
            except (OSError,ValueError):continue
            at = max(0,caption['start'])
            length = item['duration']
            for a,b in sorted(occupied):
                if at < b and at+length > a:at=b
            if at+length > total or at > caption['end']+2:continue
            cue = SoundCue(item['id'],round(at,6),volume=.65,duck_source=.35)
            result.append((cue,caption['text']))
            used.add(item['id']);occupied.append((max(0,at-2),at+length+2))
            break
        if len(result)==3:break
    return result
