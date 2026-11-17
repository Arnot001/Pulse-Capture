"""Pulse Originals: composed sound gestures, not pitch-shifted stock samples.

Every entry is an explicit arrangement of transients, textures and resonances.
Pure Python authoring/runtime synthesis keeps the installed app dependency-free.
The nineteen legacy IDs retain their original renderer and cached waveforms.
"""
from array import array
import math
import random
import wave

CATEGORIES = ('Comedy', 'Reactions', 'Memes', 'Cinematic', 'Failures', 'Animals',
              'Transitions', 'Suspense')


def hit(voice, frequency=220, duration=.3, at=0, end=None, gain=.6, pan=0, mod=0):
    return (voice, at, duration, frequency, frequency if end is None else end, gain, pan, mod)


def run(voice, pitches, step=.12, duration=.18, at=0, gain=.5):
    return [hit(voice, p, duration, at+i*step, gain=gain, pan=(i%3-1)*.25)
            for i, p in enumerate(pitches)]


# Names describe an audible action. Similar instruments have different timing,
# layers, articulation and envelopes; no catalogue entry is a resampled clone.
RECIPES = {}


def add(category, slug, name, *events):
    flat = [event for group in events for event in (group if isinstance(group, list) else [group])]
    RECIPES[f'original.{slug}'] = (name, category, tuple(flat))


add('Comedy', 'rimshot', 'Tiny stage rimshot', hit('wood', 420, .08), hit('snare', 180, .15, .14), hit('cymbal', 6000, .65, .28))
add('Comedy', 'banana_slip', 'Banana peel slip', hit('rubber', 650, .45, end=1900), hit('impact', 90, .3, .43), hit('bird', 1500, .3, .7))
add('Comedy', 'rubber_steps', 'Rubber shoe footsteps', run('rubber', [260,380,240,410], .23, .13), hit('bubble', 800, .16, .9))
add('Comedy', 'spring_door', 'Spring door wobble', hit('wood', 140, .1), hit('spring', 370, 1.1, .08, end=90, mod=22))
add('Comedy', 'balloon_escape', 'Balloon escapes', hit('breath', 800, 1.2, gain=.4), hit('rubber', 1700, 1.1, end=250, mod=27))
add('Comedy', 'toy_horn', 'Toy squeeze horn', hit('brass', 260, .19, end=310), hit('brass', 370, .32, .23, end=240))
add('Comedy', 'woodpecker_door', 'Impatient wooden knock', run('wood',[510,510,510],.1,.08), run('wood',[700,440],.17,.12,.45))
add('Comedy', 'jelly_wobble', 'Jelly wobble', hit('bubble', 330, .8, end=110, mod=18), hit('water', 900, .3, .45))
add('Comedy', 'comic_splat', 'Custard splat', hit('water', 330, .22, gain=.8), hit('impact', 75, .19), hit('bubble', 230, .35, .14))
add('Comedy', 'sneaky_toes', 'Sneaky tiptoes', run('wood',[610,720,590,800,560],.17,.09,gain=.4))
add('Comedy', 'rubber_band', 'Rubber band twang', hit('string', 170, .75, end=130, mod=14), hit('tick', 2400, .03))
add('Comedy', 'nose_honk', 'Double nose honk', hit('vowel', 310, .13, mod=3), hit('brass', 450, .27, .18, end=300))
add('Comedy', 'pots_tumble', 'Pots and pans tumble', run('metal',[320,510,700,280,890],.14,.48), hit('impact',80,.4,.68))
add('Comedy', 'comical_springboard', 'Springboard launch', hit('wood',170,.1), hit('spring',140,.55,.05,end=1200), hit('sweep',1800,.3,.45,end=4000))
add('Comedy', 'gulp', 'Cartoon gulp', hit('vowel',220,.12,end=130,mod=2), hit('bubble',410,.2,.11,end=180))
add('Comedy', 'tiny_violin', 'Tiny violin lament', run('string',[660,622,587,440],.3,.34,gain=.4))
add('Comedy', 'comedy_crickets', 'Awkward cricket pause', run('insect',[3200,3200,4100],.38,.18,gain=.35))
add('Comedy', 'boomerang', 'Boomerang return', hit('sweep',2300,.35,end=300,pan=-.8), hit('spring',250,.55,.4,end=1000,pan=.8))

add('Reactions','gasp','Surprised gasp',hit('breath',1800,.4,end=3500),hit('vowel',390,.22,.1,end=650,mod=1))
add('Reactions','slow_clap','Three slow claps',run('clap',[800,800,800],.48,.16,gain=.75))
add('Reactions','applause','Small room applause',[hit('clap',700,.16,i*.065,gain=.3+(i%3)*.08,pan=(i%5-2)*.35) for i in range(20)])
add('Reactions','surprise_bell','Surprise bell and breath',hit('glass',1400,.7),hit('breath',1300,.17))
add('Reactions','question','Questioning chirrup',hit('vowel',270,.42,end=740,mod=2),hit('tick',1800,.06,.48))
add('Reactions','agreement','Friendly agreement',run('vowel',[310,390],.23,.18,gain=.45))
add('Reactions','disbelief','Disbelief wobble',hit('vowel',230,.65,end=180,mod=9),hit('wood',160,.12,.7))
add('Reactions','cheer','Mini victory cheer',run('brass',[392,494,587],.12,.5),hit('cymbal',6500,.7,.3,gain=.2))
add('Reactions','thinking','Thinking taps',run('wood',[420,420,530],.32,.09),hit('glass',1300,.35,1.05))
add('Reactions','double_take','Double take',hit('scrape',1300,.12),hit('scrape',900,.17,.22),hit('spring',420,.35,.4))
add('Reactions','sigh','Deflated sigh',hit('breath',2100,.9,end=380,gain=.5),hit('vowel',160,.65,.1,end=100,gain=.25))
add('Reactions','relief','Relief exhale',hit('breath',1200,.7,end=400),run('glass',[523,659],.22,.55,.15,gain=.25))
add('Reactions','heartbeat','Startled double heartbeat',hit('kick',65,.22),hit('kick',48,.3,.28),hit('breath',500,.6,.05,gain=.15))
add('Reactions','side_eye','Side-eye string pluck',hit('string',196,.38),hit('string',208,.5,.18,gain=.35))
add('Reactions','revelation','Sudden revelation',run('glass',[784,988,1175],.08,.65),hit('shimmer',440,.9,.1,gain=.25))
add('Reactions','panic','Little panic flurry',run('wood',[500,720,930,640,400],.07,.1),hit('alarm',880,.55,.2,end=1320,mod=9))
add('Reactions','approval','Approval stamp',hit('impact',120,.16),hit('wood',620,.08,.03),hit('glass',880,.4,.12))
add('Reactions','shush','Shush',hit('breath',5500,.65,end=2200,gain=.5),hit('grain',4200,.17,.1,gain=.15))

add('Memes','buffering','Brain buffering',run('digital',[620,620,620],.3,.08),hit('digital',260,.3,.95,end=90))
add('Memes','system_panic','System panic cascade',run('digital',[1100,930,800,690,510,250],.055,.09),hit('crackle',1800,.45,.3))
add('Memes','receipt','Receipt printer',run('grain',[1800]*8,.09,.045),hit('scrape',1200,.3,.76,end=2500))
add('Memes','pixel_win','Pixel victory staircase',run('pulse',[523,659,784,1046],.095,.18),hit('glass',1568,.45,.4))
add('Memes','pixel_loss','Pixel lives lost',run('pulse',[784,587,392,196],.14,.19),hit('digital',110,.35,.5,end=40))
add('Memes','camera_zoom','Suspicious camera zoom',hit('grain',1200,.35,end=2800),hit('impact',70,.5,.3),hit('string',175,.6,.35))
add('Memes','dramatic_typing','Furious typing then return',run('tick',[2400,1900,3100,1800,2700,3300,2100],.055,.04),hit('wood',260,.16,.5))
add('Memes','empty_wallet','Empty wallet moth',hit('scrape',600,.25),run('insect',[2200,2600,1800],.17,.13,.35,gain=.25))
add('Memes','brain_spark','One remaining brain cell',hit('crackle',2800,.12),hit('glass',900,.55,.17),hit('digital',160,.12,.7))
add('Memes','disconnect','Disconnected mid-thought',hit('pulse',660,.16),hit('grain',3000,.07,.18),hit('digital',330,.35,.3,end=80))
add('Memes','tiny_fanfare','Extremely tiny fanfare',run('brass',[440,554,659,880],.1,.16,gain=.4),hit('wood',300,.08,.65))
add('Memes','bad_idea','Bad idea switch',hit('tick',1300,.05),hit('alarm',300,.5,.08,end=210,mod=17),hit('crackle',900,.2,.55))
add('Memes','dramatic_reveal','Overdramatic reveal',hit('sweep',250,.5,end=3200),hit('brass',110,.7,.48),hit('impact',42,.85,.48))
add('Memes','rewind','Tape rewind stop',hit('grain',1400,.8,end=4000,mod=22),hit('wood',300,.1,.82))
add('Memes','notification_storm','Notification avalanche',run('glass',[880,1100,1320,990,1480,1660],.09,.25,gain=.4))
add('Memes','loading_complete','Loading finally complete',run('tick',[600,600,600],.28,.07),run('pulse',[780,1040],.09,.2,1.1))
add('Memes','bonk_echo','Bonk with embarrassed echo',hit('wood',360,.16),hit('wood',360,.15,.25,gain=.22),hit('wood',360,.14,.5,gain=.08))
add('Memes','plot_twist','Plot twist chord',hit('string',196,.65),hit('string',277,.65),hit('metal',610,.5,.05,gain=.22))

add('Cinematic','door_slam','Vault door slam',hit('metal',80,.55),hit('impact',37,1.3,.06),hit('scrape',350,.6,.25,gain=.25))
add('Cinematic','trailer_hit','Layered trailer hit',hit('kick',48,1.1),hit('metal',210,.8),hit('crackle',1800,.3),hit('shimmer',900,1.4,.1,gain=.2))
add('Cinematic','sub_drop','Long sub drop',hit('impact',110,1.8,end=28),hit('sweep',450,.45,end=40,gain=.25))
add('Cinematic','metal_bow','Bowed metal reveal',hit('metal',180,1.6,end=290,mod=6,gain=.5),hit('breath',2300,1.2,.2,gain=.2))
add('Cinematic','space_door','Space door pressure seal',hit('scrape',300,.9,end=750),hit('breath',4000,.5,.55),hit('impact',70,.35,.95))
add('Cinematic','thunder','Rolling thunder',hit('crackle',180,.35),hit('breath',90,2.2,.05,end=40,gain=.9),run('impact',[45,38,32],.42,.9,.25,gain=.25))
add('Cinematic','glass_shatter','Crystal shatter',hit('clap',5000,.08),run('glass',[1900,2350,3100,2700,4100,1600],.035,.5,gain=.35))
add('Cinematic','airlock','Airlock decompress',hit('wood',220,.08),hit('breath',6500,1.5,.08,end=600),hit('metal',130,.7,1.3))
add('Cinematic','power_up','Reactor power up',hit('pulse',55,1.7,end=660,mod=12),hit('sweep',200,1.5,end=6000,gain=.4),hit('glass',1320,.5,1.5))
add('Cinematic','power_down','Reactor power down',hit('alarm',740,1.2,end=45,mod=4),hit('crackle',1200,.4,.8),hit('wood',90,.15,1.3))
add('Cinematic','sword','Sword unsheath',hit('scrape',1800,.4,end=4800),hit('metal',1750,1.0,.3,gain=.4))
add('Cinematic','arrow','Arrow flies and lands',hit('sweep',2200,.3,end=700,pan=-.8),hit('wood',240,.18,.3,pan=.7),hit('string',620,.55,.32,gain=.3))
add('Cinematic','portal','Portal opens',hit('shimmer',220,1.6,end=880,mod=8),hit('water',200,1.2,.3,gain=.3),hit('impact',60,.8,1.2))
add('Cinematic','engine','Engine ignition',hit('crackle',180,.22),hit('growl',65,1.5,.15,end=180,mod=15),hit('metal',600,.3,.15,gain=.2))
add('Cinematic','ice_crack','Ice shelf cracks',run('crackle',[1200,2100,850],.18,.2),hit('metal',250,.9,.5),hit('impact',42,1,.55))
add('Cinematic','cinema_drum','Ceremonial drum triplet',run('kick',[110,90,55],.22,.7,gain=.8),hit('cymbal',3600,1.2,.48,gain=.25))
add('Cinematic','orbital_ping','Orbital sonar ping',hit('glass',950,1.2),hit('glass',950,.8,.6,gain=.16),hit('breath',160,1.4,gain=.1))
add('Cinematic','debris','Falling debris',run('wood',[170,290,430,200,510,310],.12,.14),hit('grain',700,1.0,.3,gain=.3))

add('Failures','sad_robot','Sad robot shutdown',run('digital',[440,330,220],.22,.23),hit('pulse',110,.4,.65,end=35))
add('Failures','deflate','Inflatable dream deflates',hit('rubber',850,.9,end=140,mod=19),hit('breath',3000,1.1,end=400,gain=.4))
add('Failures','wrong_answer','Wrong answer clunks',hit('alarm',110,.3,mod=14),hit('wood',190,.15,.35))
add('Failures','broken_machine','Machine coughs and stops',run('growl',[110,95,70],.25,.16),hit('crackle',800,.18,.6),hit('metal',350,.6,.8))
add('Failures','wilt','Flower wilts',hit('string',620,.9,end=100),hit('scrape',450,.35,.5,gain=.25))
add('Failures','empty_can','Empty can rolls away',run('metal',[730,690,640,600,570],.12,.19,gain=.35),hit('scrape',900,.6,.3,gain=.2))
add('Failures','falling_stairs','Cartoon stair tumble',run('wood',[360,310,280,230,180,120],.17,.16),hit('impact',65,.4,.95))
add('Failures','flat_tire','Flat tyre hiss',hit('rubber',330,.13),hit('breath',5200,1.4,.1,end=700))
add('Failures','missed_jump','Missed jump',hit('pulse',400,.2,end=1200),hit('sweep',1800,.6,.3,end=100),hit('impact',55,.3,.85))
add('Failures','wobbly_chair','Wobbly chair collapse',run('scrape',[420,540,350],.22,.18),hit('wood',120,.23,.8),hit('metal',360,.5,.83))
add('Failures','denied','Access denied triple pulse',run('alarm',[210,210,160],.2,.12,gain=.4))
add('Failures','broken_glass','Dropped glass and silence',hit('wood',230,.07),run('glass',[2400,3300,1900,4100],.04,.45,.1,gain=.4))
add('Failures','sad_whistle','Whistle loses confidence',hit('bird',1800,.85,end=400,mod=7),hit('breath',900,.3,.7,gain=.2))
add('Failures','battery_dies','Battery dies',run('pulse',[1200,700,300],.28,.09),hit('digital',150,.55,.8,end=20))
add('Failures','dud','Firework dud',hit('crackle',3500,.8,gain=.3),hit('wood',180,.08,.9),hit('breath',600,.35,1,gain=.2))
add('Failures','record_skip','Record skips out',run('scrape',[900,900,900],.18,.11),hit('grain',800,.35,.6,end=120))
add('Failures','crumple','Paper plan crumples',run('crackle',[1800,2200,1400,1700],.15,.24,gain=.4),hit('wood',230,.12,.8))
add('Failures','sad_bells','Three disappointed bells',run('glass',[660,622,440],.32,.7,gain=.4))

add('Animals','dog_bark','Cartoon dog double bark',run('growl',[180,150],.32,.22,gain=.7))
add('Animals','cat_meow','Cartoon cat meow',hit('vowel',560,.65,end=320,mod=2),hit('breath',1500,.1,gain=.2))
add('Animals','kitten_purr','Kitten purr',hit('purr',85,1.6,mod=26,gain=.6))
add('Animals','duck_quack','Duck quack triplet',run('vowel',[360,410,330],.23,.15,gain=.6))
add('Animals','owl_hoot','Owl hoot',hit('vowel',310,.4,end=270,mod=1),hit('vowel',260,.65,.55,mod=1))
add('Animals','frog_croak','Pond frog croak',run('growl',[130,155,110],.35,.23,gain=.5))
add('Animals','bird_chirp','Garden bird phrase',run('bird',[2100,2800,2400,3200],.16,.12,gain=.35))
add('Animals','chicken','Chicken cluck',run('vowel',[540,680,500,460],.18,.085,gain=.5))
add('Animals','rooster','Rooster morning call',run('brass',[520,640,720,610],.25,.3,gain=.4),hit('vowel',610,.6,.8,end=400))
add('Animals','elephant','Tiny elephant trumpet',hit('brass',170,.8,end=420,mod=12),hit('breath',500,.8,gain=.3))
add('Animals','bee','Bee flyby',hit('insect',220,1.2,end=180,mod=35,pan=-.7),hit('insect',180,.7,1,end=120,pan=.8,gain=.3))
add('Animals','mosquito','Mosquito near ear',hit('insect',680,1.2,end=870,mod=9,pan=.8,gain=.25))
add('Animals','horse','Horse clip clop',run('wood',[380,260,380,260,380,260],.16,.075))
add('Animals','monkey','Cartoon monkey chatter',run('vowel',[720,650,820,590,760],.18,.12,gain=.4))
add('Animals','whale','Underwater whale call',hit('vowel',160,1.6,end=420,mod=1,gain=.45),hit('water',180,1.7,gain=.15))
add('Animals','snake','Snake warning hiss',hit('breath',6800,1.1,end=4200,gain=.5),run('tick',[5000]*7,.07,.04,.5,gain=.2))
add('Animals','pig','Cartoon pig snort',hit('growl',95,.27,mod=32),hit('vowel',190,.24,.3,end=110,mod=4))
add('Animals','dolphin','Dolphin chatter',run('bird',[2800,3600,3100,3900,2500],.09,.07,gain=.3),hit('water',800,.4,.3,gain=.2))

add('Transitions','page_flip','Book page flip',hit('scrape',2500,.22,end=1200),hit('wood',550,.07,.2,gain=.3))
add('Transitions','zipper','Zipper wipe',hit('grain',1700,.45,end=3400,mod=90),hit('tick',2000,.05,.45))
add('Transitions','brush','Paintbrush swish',hit('breath',2200,.5,end=900,gain=.65),hit('water',600,.13,.43,gain=.3))
add('Transitions','digital_scan','Digital scan pass',hit('digital',300,.55,end=2400,mod=30),hit('tick',4500,.06,.6))
add('Transitions','reverse_glass','Reverse glass reveal',hit('shimmer',1200,.65,end=2200),hit('glass',1800,.5,.62))
add('Transitions','tape_stop','Tape stop',hit('pulse',440,.7,end=25),hit('grain',900,.65,end=80,gain=.3))
add('Transitions','shutter','Camera shutter',hit('tick',1900,.04),hit('wood',450,.06,.04),hit('tick',2600,.035,.13))
add('Transitions','spark_wipe','Electrical spark wipe',hit('crackle',4500,.3),hit('sweep',800,.5,.1,end=4800,gain=.4))
add('Transitions','bubble_wipe','Bubble curtain',run('bubble',[900,750,1100,650,1400],.07,.2,gain=.4))
add('Transitions','suction','Suction pop transition',hit('water',170,.42,end=700),hit('bubble',1600,.13,.4))
add('Transitions','whip','Whip pan snap',hit('sweep',400,.25,end=5500),hit('clap',7000,.1,.23,gain=.8))
add('Transitions','swoop','Soft aerial swoop',hit('sweep',600,.85,end=3200,pan=-.65),hit('breath',1200,.7,.3,pan=.65,gain=.3))
add('Transitions','metal_slide','Metal slide latch',hit('scrape',1100,.55,end=3600),hit('metal',740,.5,.5),hit('wood',200,.1,.52))
add('Transitions','water_drop','Water drop dissolve',hit('bubble',1500,.2,end=550),hit('water',800,.7,.1,gain=.35))
add('Transitions','wind_reverse','Reversing gust',hit('sweep',400,.65,end=7000),hit('breath',4500,.3,.6,end=200))
add('Transitions','pixel_curtain','Pixel curtain closes',run('digital',[1800,1300,900,650,400,190],.075,.12,gain=.45))
add('Transitions','flutter','Paper flutter wipe',run('scrape',[1400,2000,1600,2500],.12,.14,gain=.4))
add('Transitions','laser_cut','Laser cut sting',hit('pulse',2400,.2,end=110),hit('metal',1800,.35,.18,gain=.25))

add('Suspense','clock','Clock in an empty room',run('tick',[1700,1100,1700,1100],.5,.07,gain=.45),hit('breath',90,2,gain=.1))
add('Suspense','heartbeat_rise','Accelerating heartbeat',[hit('kick',60,.2,at,gain=.7) for at in (0,.25,.75,.96,1.35,1.52,1.82,1.96)])
add('Suspense','door_creak','Creeping door hinge',hit('scrape',280,1.6,end=850,mod=5),hit('wood',130,.15,1.5))
add('Suspense','string_cluster','Uneasy string cluster',hit('string',196,1.5,mod=4),hit('string',208,1.7,gain=.3),hit('string',311,1.3,.2,gain=.25))
add('Suspense','breath_behind','Breath behind you',hit('breath',1100,1.1,pan=-.8,gain=.5),hit('breath',2300,.7,.8,pan=.8,gain=.3))
add('Suspense','distant_knock','Distant unanswered knock',run('wood',[180,180,180],.43,.18,gain=.5),hit('impact',45,1.5,gain=.12))
add('Suspense','water_cave','Cave droplets',run('bubble',[1600,1200,1800],.6,.4,gain=.35),hit('breath',100,2,gain=.08))
add('Suspense','radio_search','Searching radio static',hit('grain',1800,1.4,end=6000,mod=13),run('pulse',[700,1300,500],.33,.08,.2,gain=.2))
add('Suspense','dark_swarm','Dark insect swarm',hit('insect',170,1.7,end=330,mod=22,gain=.5),hit('breath',1300,1.6,gain=.25))
add('Suspense','pulse_alarm','Muted pulse alarm',run('alarm',[440,440,440,440],.36,.2,gain=.3),hit('impact',42,1.5,gain=.18))
add('Suspense','bowed_glass','Bowed glass unease',hit('shimmer',770,1.8,end=830,mod=3),hit('metal',530,1.6,gain=.2))
add('Suspense','floorboard','Floorboard gives way',hit('scrape',190,.9,end=420),hit('crackle',600,.2,.8),hit('wood',85,.25,.96))
add('Suspense','countdown','Last three seconds',run('pulse',[880,880,1320],.7,.12,gain=.4),hit('impact',55,.6,1.5))
add('Suspense','drone','Subterranean drone',hit('growl',42,2.3,end=50,mod=3,gain=.5),hit('string',73,2.1,.1,gain=.25))
add('Suspense','whisper','Passing whisper texture',hit('breath',3500,1.4,end=1600,pan=-.6),hit('grain',2300,.8,.5,pan=.7,gain=.15))
add('Suspense','chain','Chain drags in darkness',run('metal',[360,510,280,430],.25,.3,gain=.4),hit('scrape',650,1.2,gain=.3))
add('Suspense','tension_release','Tension snaps',hit('string',220,1.0,end=440,mod=5),hit('clap',2000,.1,1),hit('impact',50,.7,1.05))
add('Suspense','alien_signal','Unanswered alien signal',run('digital',[370,950,610,1250],.27,.18,gain=.35),hit('shimmer',160,1.6,gain=.2))

SFX = {key: (name, category, round(max(e[1]+e[2] for e in events)+.18, 3))
       for key, (name, category, events) in RECIPES.items()}


def synthesize(asset_id, path, rate=48000):
    name, category, events = RECIPES[asset_id]
    count = round(SFX[asset_id][2]*rate)
    left, right = array('f', [0])*count, array('f', [0])*count
    rng = random.Random(asset_id)
    for voice, at, duration, f0, f1, gain, pan, mod in events:
        start, frames = round(at*rate), round(duration*rate)
        phase = low = previous = 0.
        for i in range(frames):
            u, t = i/max(1, frames-1), i/rate
            f = f0+(f1-f0)*u
            if voice in ('spring','rubber','bubble'):
                f += f*.3*math.sin((mod or 35)*t)*math.exp(-3*u)
            elif mod:
                f *= 1+.035*math.sin(2*math.pi*mod*t)
            phase += 2*math.pi*f/rate
            white = rng.uniform(-1,1)
            low += min(.85, 2*math.pi*max(40,f)/rate)*(white-low)
            high = white-previous
            previous = white
            sine = math.sin(phase)
            edge = min(1, t/.004, (duration-t)/.018)
            decay = math.exp(-5*u)
            body = math.sin(math.pi*u)**.7
            if voice in ('wood','tick'):
                value = (sine+.35*math.sin(phase*2.71)+.25*white)*math.exp(-14*u)
            elif voice in ('metal','glass'):
                value = (sine+.5*math.sin(phase*2.756)+.3*math.sin(phase*5.404))*math.exp(-4*u)
                if mod: value *= .4+.6*body
            elif voice in ('impact','kick'):
                value = (math.sin(phase+10*(1-math.exp(-35*t)))+.35*low)*math.exp(-6*u)
            elif voice == 'snare': value = (.7*white+.3*sine)*math.exp(-11*u)
            elif voice == 'clap': value = high*.5*math.exp(-12*u)*(.35+.65*abs(math.sin(t*750)))
            elif voice == 'cymbal': value = (high*.3+.15*math.sin(phase*1.43))*math.exp(-5*u)
            elif voice in ('breath','sweep'): value = low*3*body
            elif voice == 'scrape': value = (low*2+.2*sine)*body*(.35+.65*abs(math.sin(t*(mod or 83))))
            elif voice == 'grain': value = (high*.2+.5*low)*body*(1 if int(t*(mod or 47))%3 else .1)
            elif voice == 'crackle': value = (white if rng.random()<.12 else low)*math.exp(-3*u)*1.2
            elif voice == 'water': value = (sine*low*2+.3*low)*body
            elif voice == 'shimmer': value = (sine+.3*math.sin(phase*2.01)+.2*math.sin(phase*4.13))*body*.6
            elif voice == 'string': value = (sine+.4*math.sin(phase*2)+.2*math.sin(phase*3))*(.35*body+.65*decay)
            elif voice in ('brass','alarm'): value = (sine+.5*math.sin(phase*3)+.25*math.sin(phase*5))*body*.7
            elif voice == 'pulse': value = (sine+.33*math.sin(phase*3)+.2*math.sin(phase*5))*edge*.7
            elif voice == 'digital': value = (round(sine*4)/4)*body*(.4+.6*(int(t*31)%2))
            elif voice == 'vowel':
                value = (sine+.5*math.sin(phase*3)+.25*math.sin(phase*5+.6*math.sin(t*13)))*body*.7
            elif voice == 'growl': value = (math.tanh(sine*3)*.6+low*.8)*body*(.6+.4*math.sin(t*92))
            elif voice == 'purr': value = (low*2+.2*sine)*body*(.3+.7*abs(math.sin(t*math.pi*(mod or 25))))
            elif voice == 'insect': value = (sine+.3*math.sin(phase*7))*body*(.35+.65*abs(math.sin(t*(mod or 55))))
            elif voice == 'bird': value = math.sin(phase+2*math.sin(phase*.16))*body*.7
            else: value = (sine+.2*math.sin(phase*2))*decay
            value *= max(0,edge)*gain
            pos = start+i
            if pos >= count: break
            l, r = value*math.sqrt((1-pan)/2), value*math.sqrt((1+pan)/2)
            left[pos] += l; right[pos] += r
            # Quiet, unequal early reflections give transients space without a
            # long reverb tail that would mask dialogue.
            for delay, amount in ((.071,.12),(.137,.06)):
                j = pos+round(delay*rate)
                if j<count: left[j] += r*amount; right[j] += l*amount
    peak = max(max(map(abs,left)), max(map(abs,right)), .01)
    gain = min(2.5, .82/peak)
    pcm = array('h')
    for l, r in zip(left,right):
        pcm.extend((round(max(-.9,min(.9,l*gain))*32767),round(max(-.9,min(.9,r*gain))*32767)))
    with wave.open(str(path),'wb') as stream:
        stream.setparams((2,2,rate,0,'NONE','not compressed'))
        stream.writeframes(pcm.tobytes())
