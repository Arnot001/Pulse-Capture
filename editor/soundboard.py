"""Local sound discovery: descriptive search, never downloads or inferred rights."""
import re
import unicodedata
from urllib.parse import urlencode

REACTION_ALIASES = {
    'WTF': ('wtf', 'what the fuck', 'what is he doing', 'what is she doing'),
    'Disbelief': ('disbelief', 'nope', 'nah', 'hell no', 'aint no way', 'no way', 'bruh'),
    'Funny': ('funny', 'comedy', 'joke', 'comic'),
    'Rage': ('rage', 'angry', 'anger', 'furious'),
    'Cringe': ('cringe', 'awkward', 'facepalm'),
    'Laughing': ('laughing', 'laughter', 'laugh', 'lol', 'haha'),
    'Screaming': ('screaming', 'scream', 'yell', 'shriek'),
    'Dramatic': ('dramatic', 'drama', 'suspense', 'shock', 'shocked'),
}
RIGHTS_STATUSES = ('Unverified', 'Original recording', 'Licensed / permission-cleared')


def normalized(value):
    value = unicodedata.normalize('NFKC', str(value)).casefold().replace('’', "'")
    return ' '.join(re.findall(r'\w+', value.replace("'", '')))


def search_text(item):
    return normalized(' '.join(str(item.get(k, '')) for k in
        ('id', 'name', 'transcript', 'tags', 'aliases', 'category', 'artist')))


def reaction_groups(item):
    text = ' ' + search_text(item) + ' '
    return {group for group, aliases in REACTION_ALIASES.items()
            if any(' ' + normalized(alias) + ' ' in text for alias in (group, *aliases))}


def matches(item, query):
    text = search_text(item)
    if item.get('kind') == 'sfx':
        text += ' ' + normalized(' '.join(alias for group in reaction_groups(item)
                                         for alias in (group, *REACTION_ALIASES[group])))
    return all(word in text for word in normalized(query).split())


def in_category(item, category):
    return item['category'] == category or (item.get('kind') == 'sfx' and category in reaction_groups(item))


def rights_label(item):
    if not item['id'].startswith('import.'):
        return 'Pulse original media'
    return item.get('rights_status', 'Unverified')


def discovery_url(phrase):
    phrase = ' '.join(str(phrase).split())
    if not phrase or len(phrase) > 200:
        raise ValueError('Enter a sound name or phrase of 1–200 characters.')
    return 'https://www.google.com/search?' + urlencode({'q': phrase + ' reaction sound audio licence'})
