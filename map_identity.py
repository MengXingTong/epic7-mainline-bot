"""Canonical mainline map identity, independent of chapter titles.

The numeric chapter and optional alphabetic branch are separate identity fields.
Existing main chapters retain their exact historic key; 8 and 8S never alias.
This module identifies a map, not an entry or completion permission.
"""
import re
import unicodedata


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
    return row.get('episode'),row.get('chapter'),row.get('chapter_suffix','')


def same_chapter(first,second):
    return chapter_identity(first)==chapter_identity(second)


def stage_key(row):
    return f"E{int(row['episode'])}-C{chapter_token(row)}-S{int(row['stage'])}"


def stage_order(row):
    return (int(row['episode']),int(row['chapter']),row.get('chapter_suffix',''),int(row['stage']))


def native_forward_chapter(source,target):
    if source.get('episode')!=target.get('episode'):return False
    a,b=source.get('chapter'),target.get('chapter')
    if not isinstance(a,int) or not isinstance(b,int):return False
    # A native main -> branch or branch/main -> next numeric main handoff.
    # No arbitrary jump, backward navigation or sibling-branch guess.
    return ((b==a+1 and not target.get('chapter_suffix'))
            or (b==a and not source.get('chapter_suffix') and bool(target.get('chapter_suffix'))))
