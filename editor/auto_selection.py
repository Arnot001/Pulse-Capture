"""Source-wide, quality-gated local selection using existing analysis-v1 samples.

This is evidence ranking, not semantic joke/plot recognition. Plans still use
the existing chronological shots/cuts and the same eight-shot validator.
"""
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
import math
import re

SELECTOR_VERSION = 2
POOL_LIMIT = 180
SEEDS = 12


@dataclass(frozen=True)
class Moment:
    start: float
    end: float
    quality: float
    opening: float
    change: float
    closing: float
    region: tuple
    features: tuple
    words: frozenset


def overlap(a, b):
    return max(0., min(a.end,b.end)-max(a.start,b.start))


def gap(a, b):
    return max(0., max(a.start,b.start)-min(a.end,b.end))


def similarity(a, b):
    """Weak redundancy evidence only: similar motion/luma/audio is not identity."""
    activity = math.exp(-sum(abs(x-y) for x,y in zip(a.features,b.features))*5)
    if a.words and b.words:
        return .5*activity+.5*len(a.words & b.words)/len(a.words | b.words)
    return activity


class Selector:
    def __init__(self, analysis, media, options, transcript, cancelled):
        self.media,self.options,self.transcript,self.cancelled=media,options,transcript,cancelled
        self.samples=sorted(analysis['samples'],key=lambda s:s['time'])
        self.times=[s['time'] for s in self.samples]
        self.step=analysis.get('step') or (self.times[1]-self.times[0] if len(self.times)>1 else .5)
        self.scenes=sorted(set(t for t in analysis.get('scenes',[]) if 0<t<media.duration))
        self.edges=sorted(set([0.,media.duration,*self.scenes,*[c[k] for c in transcript for k in ('start','end')]]))
        self.weights={'Gaming':(2.5,.4,.8),'News/Preview':(1.4,.3,.35),
                      'Funny Moments':(1.8,.65,.85),'Comedy / Roast':(1.8,.65,.85)}[options.style]
        self.peak=max((self.weights[0]*s['motion']+self.weights[1]*s.get('audio',0)
                       for s in self.samples if s['brightness']>=.035),default=0)
        self.weak_evidence=self.peak<.025 and not transcript

    def group(self,start,end):
        return self.samples[bisect_left(self.times,start):bisect_left(self.times,end)]

    def measure(self,start,end):
        samples=self.group(start,end)
        if not samples:return None
        bad=lambda s:s['brightness']<.035 or (s['brightness']>.985 and s['motion']<.008)
        # Cut-to-black spikes must never masquerade as exciting action. Permit
        # at most a sub-frame boundary error, not sustained black filler.
        if any(bad(s) for s in samples):return None
        wm,wa,wc=self.weights
        energy=[wm*s['motion']+wa*s.get('audio',0) for s in samples]
        mean=sum(energy)/len(energy)
        change=sum(min(.5,s.get('scene',0)) for s in samples)/len(samples)
        variation=max(energy)-min(energy)
        cues=[c for c in self.transcript if c['start']<end and c['end']>start]
        speech=min(1,sum(max(0,min(end,c['end'])-max(start,c['start'])) for c in cues)/(end-start))
        active_floor=max(.008,max(energy)*.25,self.peak*.04)
        occupied=sum(e>=active_floor or any(c['start']<=s['time']<c['end'] for c in cues)
                     for e,s in zip(energy,samples))/len(samples)
        if not self.weak_evidence and occupied<.65:return None
        # Sustained activity and speech outweigh isolated cuts. The peak/change
        # terms favour action and unusual changes for Gaming/Comedy.
        quality=.72*mean+.18*max(energy)+wc*(change+.12*variation)+(.16 if self.options.style=='News/Preview' else .09)*speech
        clipped=sum(c['start']+.08<t<c['end']-.08 for c in cues for t in (start,end))
        quality=max(0,quality-.04*clipped)
        opening=sum(energy[:max(1,round(2/self.step))])/len(energy[:max(1,round(2/self.step))])
        closing=sum(energy[-max(1,round(2/self.step)):])/len(energy[-max(1,round(2/self.step)):])
        # One long uncut scene may contain multiple events minutes apart. Bound
        # region IDs in that case; do not call the entire source a single moment.
        middle=(start+end)/2
        scene=bisect_right(self.scenes,middle)
        boundaries=[0.,*self.scenes,self.media.duration]
        a,b=boundaries[scene:scene+2]
        region=(scene, int((middle-a)/max(20,self.options.maximum))) if b-a>2*self.options.maximum else (scene,0)
        words=frozenset(w for c in cues for w in re.findall(r"[\w']+",c['text'].lower()) if len(w)>3)
        features=(sum(s['motion'] for s in samples)/len(samples),change,
                  sum(s['brightness'] for s in samples)/len(samples),sum(s.get('audio',0) for s in samples)/len(samples))
        return Moment(start,end,quality,opening,variation+change,closing,region,features,words)

    def pool(self,length):
        # Sample every part of the timeline, not just a top-N cluster. Scene and
        # transcript edges can start OR end a shot of the requested length.
        stride=max(1,round(max(1.5,length/3)/self.step))
        starts={0.,max(0,self.media.duration-length)}
        for i,s in enumerate(self.samples):
            if i%stride==0:
                starts.add(s['time']);starts.add(s['time']-length/2)
        for edge in self.edges:
            starts.add(edge);starts.add(edge-length)
        values=[]
        for i,start in enumerate(sorted(starts)):
            if i%80==0:self.cancelled()
            if start<0 or start+length>self.media.duration+1e-7:continue
            item=self.measure(round(start,6),round(start+length,6))
            if item is not None:values.append(item)
        if not values:return []
        # Buckets are a candidate-retention mechanism, never a coverage quota.
        # Weak or black buckets contribute nothing if they fail the quality gate.
        best=max(v.quality for v in values)
        floor=max(.012,best*.23) if best>.025 else 0
        values=[v for v in values if v.quality>=floor]
        buckets={}
        width=max(length,self.media.duration/36)
        for v in values:buckets.setdefault(int(v.start/width),[]).append(v)
        retained=[]
        for bucket in buckets.values():
            for v in sorted(bucket,key=lambda v:(-v.quality,v.start)):
                if all(overlap(v,x)/length<.55 for x in retained):retained.append(v)
                if sum(int(x.start/width)==int(v.start/width) for x in retained)>=5:break
        return sorted(retained,key=lambda v:(-v.quality,v.start))[:POOL_LIMIT]

    def reuse(self,item,previous):
        penalty=0
        for short in previous:
            for old in short:
                fraction=overlap(item,old)/min(item.end-item.start,old.end-old.start)
                near=math.exp(-gap(item,old)/max(4,self.options.maximum*.35))
                penalty=max(penalty,1.1*fraction+.32*near+.22*(item.region==old.region))
        return penalty

    def assemble(self,pool,count,previous,target):
        if len(pool)<count:return []
        peak=max(max(v.quality for v in pool),.025)
        separation=max(3,min(12,target*.3))
        distance=max(separation,self.media.duration*.18)
        ranked=sorted(pool,key=lambda v:-(v.quality/peak-.85*self.reuse(v,previous)))
        seeds=[]
        for item in ranked:
            if all(gap(item,x)>=separation for x in seeds):seeds.append(item)
            if len(seeds)>=SEEDS:break
        results=[]
        for seed in seeds:
            self.cancelled()
            chosen=[seed]
            for _ in range(count-1):
                eligible=[v for v in pool if all(gap(v,x)>=separation for x in chosen)]
                if not eligible:break
                def incremental(v):
                    nearest=min(gap(v,x) for x in chosen)
                    same=max(float(v.region==x.region) for x in chosen)
                    redundancy=max(similarity(v,x) for x in chosen)
                    return (v.quality/peak+.35*min(1,nearest/distance)-.24*same-.06*redundancy
                            -.85*self.reuse(v,previous))
                chosen.append(max(eligible,key=lambda v:(incremental(v),-v.start)))
            if len(chosen)!=count:continue
            if count>1 and len({v.region for v in chosen})==1:continue
            chosen.sort(key=lambda v:v.start)
            # Keep the established cross-candidate overlap validator stricter
            # than its 35% limit, even if a high-scoring shot is tempting again.
            if any(sum(overlap(a,b) for a in chosen for b in old)/min(target,sum(b.end-b.start for b in old))>.30 for old in previous):continue
            quality=sum(v.quality for v in chosen)/count
            novelty=sum(self.reuse(v,previous) for v in chosen)/count
            span=(chosen[-1].end-chosen[0].start)/max(target,self.media.duration)
            regions=len({v.region for v in chosen})/count
            # Story proxies only: chronological opening energy, context, a
            # change, then a closing beat. No claims about jokes, facts or plot.
            story=(.10*chosen[0].opening+.06*max(v.change for v in chosen)+.04*chosen[-1].closing)
            bonus=(.13*regions+.12*min(1,span/.6)) if count>=3 else .07*span if count==2 else 0
            rank=quality+story+peak*(bonus-.75*novelty)
            results.append((rank,chosen))
        return results

    def select(self):
        target=min(self.media.duration,(self.options.minimum+self.options.maximum)/2)
        # Three to six readable shots when duration and usable material allow;
        # never subdivide a continuous fallback just to inflate its shot count.
        preferred=max(1,min(6,round(target/7)))
        counts=sorted(range(1,min(6,int(target/3))+1),key=lambda n:(abs(n-preferred),n))
        if self.weak_evidence:counts=[1]
        variants=[]
        for duration in sorted({target,float(self.options.minimum)},reverse=True):
            for count in counts:
                if duration/count<3:continue
                pool=self.pool(duration/count)
                if pool:variants.append((duration,count,pool))
        previous=[]
        for _ in range(self.options.count):
            possibilities=[]
            for duration,count,pool in variants:
                for rank,chosen in self.assemble(pool,count,previous,duration):
                    # A small length preference, not permission to add filler.
                    possibilities.append((rank+.012*duration/target,chosen))
            if not possibilities:break
            _,chosen=max(possibilities,key=lambda p:(p[0],-p[1][0].start))
            previous.append(chosen)
        return previous

    def shots(self,chosen):
        result=[]
        for item in chosen:
            window=self.group(item.start,item.end)
            def focus(at):
                near=sorted(window,key=lambda s:abs(s['time']-at))[:3]
                return sorted(s.get('focus_x',.5) for s in near)[len(near)//2]
            result.append(dict(start=item.start,end=item.end,focus_x=focus(item.start+.3),focus_y=.5,
                               end_focus_x=focus(item.end-.3),end_focus_y=.5))
        return result


def select_local(analysis,media,options,transcript=(),cancelled=lambda:None):
    options.validate()
    if media.duration<options.minimum:
        raise ValueError('The source is shorter than your minimum duration. Lower the target or choose a longer video.')
    selector=Selector(analysis,media,options,transcript,cancelled)
    selected=selector.select()
    if not selected:
        raise ValueError('Not enough suitable non-black footage for the requested duration. Lower the target or review the footage manually.')
    shorts=[]
    for index,chosen in enumerate(selected):
        mixed=len(chosen)>1
        reason=(f'{len(chosen)} separated regions selected across the source, in chronological order. '
                'Quality-gated motion, scene changes, audio and available speech; explicit separation and reuse penalties. '
                if mixed else 'Continuous edit: separated regions did not provide a stronger, sufficiently usable selection at this duration. ')
        reason+=('Opening energy, context, change and closing activity are storytelling proxies, not recognised jokes or plot.'
                 if options.style!='News/Preview' else 'Scene variety and speech coverage favour a showcase; local evidence cannot verify news claims or identify topics.')
        if len(selected)<options.count:reason+=' Fewer candidates avoid low-quality filler or excessive repetition.'
        shorts.append(dict(title=f'{options.style} · selection {index+1}',
                           description='Local-only candidate. Review the selected moments and give this Short a specific title before publishing.',
                           rationale=reason,verification=['Review the hook, shot transitions, speech boundaries and factual claims.'],
                           shots=selector.shots(chosen),captions=[]))
    return {'shorts':shorts}


def source_ranges(shots):
    """Compact real source ranges for both local and AI candidate cards."""
    merged=[]
    for shot in shots:
        if merged and abs(merged[-1][1]-shot['start'])<.02:merged[-1][1]=shot['end']
        else:merged.append([shot['start'],shot['end']])
    def stamp(t):
        minutes,seconds=divmod(int(t),60)
        return f'{minutes}:{seconds:02d}'
    return ' + '.join(f'{stamp(a)}–{stamp(b)}' for a,b in merged)
