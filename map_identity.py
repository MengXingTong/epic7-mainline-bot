"""Canonical mainline map identity, independent of chapter titles.

The numeric chapter and optional alphabetic branch are separate identity fields.
Existing main chapters retain their exact historic key; 8 and 8S never alias.
This module identifies a map, not an entry or completion permission.
"""
import hashlib
import re
import unicodedata


def named_episode(title):
    """An explicit named Episode scope, never a fabricated numeric Episode."""
    title=' '.join(unicodedata.normalize('NFKC',title).split()).casefold()
    if (not title or len(title)>80 or not re.search(r'\w',title)
            or re.search(r'[\x00-\x1f\x7f<>/\\|]',title)):
        raise ValueError('具名Episode身份不完整，未发送输入。')
    return 'named:'+title


def episode_identity(row):
    value=row.get('episode')
    if type(value) is int and value>0:return ('numbered',value)
    if isinstance(value,str) and value.startswith('named:') and named_episode(value[6:])==value:
        return ('named',value[6:])
    raise ValueError('Episode身份字段无效，未发送输入。')


def valid_stage_identity(row):
    try:
        episode_identity(row);chapter_token(row)
        return type(row.get('chapter')) is int and type(row.get('stage')) is int and row['stage']>0
    except (KeyError,TypeError,ValueError):return False


def episode_handoff(source,target):
    """Current unlocked first node may start a distinct, fully read Episode.

    Named Episodes have no invented chronological number. This grants only a
    current-map handoff, not an old clear, backward navigation, or entry replay.
    The caller still checks the current selected/unlocked row and entry history.
    """
    try:a,b=episode_identity(source),episode_identity(target)
    except (TypeError,ValueError):return False
    if a==b or target.get('chapter')!=1 or target.get('chapter_suffix') or target.get('stage')!=1:return False
    return ('named' in (a[0],b[0]) or (a[0]==b[0]=='numbered' and b[1]==a[1]+1))


def parse_chapter(text):
    compact=re.sub(r'\s+','',unicodedata.normalize('NFKC',text)).upper()
    match=re.match(r'^第([1-9]\d{0,2})([A-Z]{0,3})章',compact)
    if not match:return None
    number,branch=match.groups()
    fields=dict(chapter=int(number))
    if branch:fields['chapter_suffix']=branch
    return fields


def chapter_header(frame):
    matches=[]
    for word in frame.words:
        if word.get('score',0)<.85 or not (80<=word['x']<=340 and 95<=word['y']<=160):continue
        fields=parse_chapter(word.get('text',''))
        if fields is not None:matches.append((fields,word))
    return matches[0] if len(matches)==1 else (None,None)


def chapter_token(row):
    number=int(row['chapter']);branch=row.get('chapter_suffix','')
    if number<=0 or not re.fullmatch(r'[A-Z]{0,3}',branch):raise ValueError('章节身份字段无效，未发送输入。')
    return str(number)+branch


def chapter_identity(row):
    return episode_identity(row),row.get('chapter'),row.get('chapter_suffix','')


def same_chapter(first,second):
    try:return chapter_identity(first)==chapter_identity(second)
    except (KeyError,TypeError,ValueError):return False


def stage_key(row):
    kind,value=episode_identity(row)
    # Historic numbered keys are byte-identical. Full title hashes keep named
    # scopes collision-resistant, filesystem-safe, and distinct from E1/C1.
    prefix='E'+str(value) if kind=='numbered' else 'EN-'+hashlib.sha256(value.encode('utf-8')).hexdigest()
    return f"{prefix}-C{chapter_token(row)}-S{int(row['stage'])}"


def stage_order(row):
    kind,value=episode_identity(row)
    return (0 if kind=='numbered' else 1,value,int(row['chapter']),row.get('chapter_suffix',''),int(row['stage']))


def native_forward_chapter(source,target):
    if source.get('episode')!=target.get('episode'):return False
    a,b=source.get('chapter'),target.get('chapter')
    if not isinstance(a,int) or not isinstance(b,int):return False
    # A native main -> branch or branch/main -> next numeric main handoff.
    # No arbitrary jump, backward navigation or sibling-branch guess.
    return ((b==a+1 and not target.get('chapter_suffix'))
            or (b==a and not source.get('chapter_suffix') and bool(target.get('chapter_suffix'))))
