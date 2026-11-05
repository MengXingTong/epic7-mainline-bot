"""Observed Theater directory: left detail, right per-episode rows and seasons."""
from dataclasses import dataclass
import re
import cv2
import numpy as np
from theater_core import Episode, confident, norm, unique


@dataclass(frozen=True)
class Row:
    number: int
    token: object
    completed: bool = False
    locked: bool = False
    countdown: bool = False
    completion_unknown: bool = False
    reward_ready: bool = False


@dataclass(frozen=True)
class Directory:
    episode: Episode | None
    rows: tuple[Row, ...]
    view: object = None
    cost: int | None = None
    stock: int | None = None


def row_numbers(o):
    result = []
    for t in o.tokens:
        m = re.fullmatch(r'第(\d{1,3})集', norm(t.text))
        if m and confident(t) and o.in_region(t, (.735, .13, .877, .995)):
            result.append((int(m[1]), t))
    return sorted(result, key=lambda pair: pair[1].center[1])


def is_directory(o):
    return bool(unique(o, ('月光剧场',), (0, 0, .40, .13))
                and unique(o, ('目录',), (.76, .08, .87, .23)) and len(row_numbers(o)) >= 2)


def _row_status(o, numbers):
    rows = []
    for index, (number, token) in enumerate(numbers):
        cy = token.center[1]
        bottom = min(cy + o.height*.095,
                     numbers[index+1][1].y if index+1 < len(numbers) else o.height)
        labels = [norm(t.text) for t in o.tokens if confident(t)
                  and o.in_region(t, (.735, .13, .877, .995))
                  and cy + o.height*.012 < t.center[1] < bottom]
        complete = '完成' in labels and 'theater_complete:' + str(number) in o.visuals
        locked = any(t in ('无法观览', '未解锁', '不可观览', '尚未开放') for t in labels)
        countdown = any(re.fullmatch(r'\d+(?:天|小时|时|分钟|分)后可观览', t) for t in labels)
        uncertain = ('完成' in labels and not complete) or (complete and countdown)
        rows.append(Row(number, token, complete and not locked and not countdown, locked, countdown, uncertain,
                        '可获得奖励' in labels and not locked and not countdown and not complete))
    return tuple(rows)


def read_directory(o):
    if not is_directory(o):
        return None
    numbers = row_numbers(o)
    rows = _row_status(o, numbers)
    details = set()
    for t in o.tokens:
        if confident(t) and o.in_region(t, (.015, .60, .46, .79)):
            m = re.fullmatch(r'第(\d{1,3})集[.．·、\-]?(\D.{1,35})', norm(t.text))
            if m:
                details.add(int(m[1]))
    selected = {int(v.split(':')[1]) for v in o.visuals if re.fullmatch(r'theater_selected:\d+', v)}
    seasons = {int(v.split(':')[1]) for v in o.visuals if re.fullmatch(r'theater_season:\d+', v)}
    logo = [t for t in o.tokens if confident(t) and o.in_region(t, (.02, .10, .33, .40))
            and .06*o.height <= t.h <= .20*o.height
            and re.fullmatch(r'[\u3400-\u9fff]{1,12}', norm(t.text))]
    title = ''.join(norm(t.text) for t in sorted(logo, key=lambda t: (t.y, t.x)))
    episode = None
    if (len(details) == len(selected) == len(seasons) == 1 and details == selected
            and len([n for n, t in numbers if n in selected]) == 1 and 3 <= len(title) <= 30):
        episode = Episode(title, next(iter(selected)), next(iter(seasons)))
    view = unique(o, ('进行观览',), (.57, .85, .73, .98))
    costs = []
    for t in o.tokens:
        if confident(t) and o.in_region(t, (.51, .85, .60, .98)):
            m = re.fullmatch(r'(\d{1,3})/(\d{1,5})', norm(t.text))
            if m:
                costs.append(tuple(map(int, m.groups())))
    cost, stock = costs[0] if len(costs) == 1 else (None, None)
    return Directory(episode, rows, view, cost, stock)


def reward_claim_target(image, o):
    """The free reward label plus a stem/down-chevron and separate U tray."""
    from abyss_core import Token
    label = unique(o, ('领取观览奖励',), (.55, .76, .67, .86))
    if label is None:
        return None
    raw = np.asarray(image.convert('RGB').resize((1600,900)))
    hsv = cv2.cvtColor(raw, cv2.COLOR_RGB2HSV)
    mask = cv2.inRange(hsv[690:775,1065:1155], (0,0,105), (180,70,255))
    count, labels, stats, centers = cv2.connectedComponentsWithStats(mask)
    stems = []; trays = []
    for index,(x,y,w,h,area) in enumerate(stats[1:],1):
        if 12<=w<=24 and 12<=h<=25 and 60<=area<=250:
            patch = labels[y:y+h,x:x+w] == index
            widths = patch.sum(axis=1)
            if widths[:max(2,h//3)].mean() < w*.4 and widths.max()>w*.75 and widths[-2:].mean()<w*.5:
                stems.append((x,y,w,h))
        if 26<=w<=40 and 7<=h<=16 and 80<=area<=260:
            patch = labels[y:y+h,x:x+w] == index
            if np.mean(patch[-3:])>.65 and np.mean(patch[:3,w//3:2*w//3])<.2:
                trays.append((x,y,w,h))
    # Independent components can have 1-2 px overlapping bounding boxes after
    # native-window resampling; they must still be separate arrow/tray shapes.
    pairs=[(a,b) for a in stems for b in trays
           if abs((a[0]+a[2]/2)-(b[0]+b[2]/2))<4 and -2<=b[1]-(a[1]+a[3])<=8]
    if len(pairs)!=1:
        return None
    a,b=pairs[0];x=1065+b[0]+b[2]/2;y=690+(a[1]+b[1]+b[3])/2
    return Token('verified_reward_claim',x*o.width/1600-1,y*o.height/900-1,2,2,
                 source='theater_reward_claim',score=1.0)


def apply_directory_visuals(image, o):
    """Only outline/season/check shapes; a large green count alone proves nothing."""
    if not is_directory(o):
        return o
    claim = reward_claim_target(image, o)
    if claim is not None:
        o.tokens.append(claim)
    raw = np.asarray(image.convert('RGB'))
    hsv = cv2.cvtColor(raw, cv2.COLOR_RGB2HSV)
    h, w = raw.shape[:2]
    # Analyze the outline at the canonical raster before thresholding.
    # At small native sizes anti-aliasing can split an intact thin outline
    # into two components. Four independent side-coverage checks stay intact;
    # normalized boxes are mapped back to this fresh observation's geometry.
    ring = np.asarray(image.convert('RGB').resize((1600, 900)))
    gold = cv2.inRange(cv2.cvtColor(ring, cv2.COLOR_RGB2HSV),
                       (15, 35, 140), (46, 255, 255))
    gh, gw = gold.shape
    gold[:, :int(gw*.73)] = 0
    gold[:, int(gw*.88):] = 0
    contours, _ = cv2.findContours(gold, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    edge = max(2, round(gh*.005))
    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)
        if not (.10*gw < bw < .16*gw and .075*gh < bh < .14*gh):
            continue
        patch = gold[y:y+bh, x:x+bw] > 0
        coverage = (np.mean(np.any(patch[:edge], axis=0)), np.mean(np.any(patch[-edge:], axis=0)),
                    np.mean(np.any(patch[:, :edge], axis=1)), np.mean(np.any(patch[:, -edge:], axis=1)))
        if min(coverage) > .45:
            boxes.append((x*w/gw, y*h/gh, bw*w/gw, bh*h/gh))
        elif sum(v > .45 for v in coverage) >= 3 and min(coverage) > .15:
            for number, token in row_numbers(o):
                cx,cy=token.center
                if x*w/gw<cx<(x+bw)*w/gw and y*h/gh<cy<(y+bh)*h/gh:
                    o.visuals.add('theater_soft_selected:'+str(number))
    for number, token in row_numbers(o):
        cx, cy = token.center
        if sum(x < cx < x+bw and y < cy < y+bh for x, y, bw, bh in boxes) == 1:
            o.visuals.add('theater_selected:' + str(number))
        # A row-local green tick has a descending short arm and ascending long
        # arm. Require its V-shaped trace, plus the separate OCR 完成 label.
        x1, x2 = round(w*.74), round(w*.772)
        y1, y2 = max(0, round(token.y+token.h)), min(h, round(cy+h*.085))
        patch = hsv[y1:y2, x1:x2]
        mask = cv2.inRange(patch, (32, 100, 100), (85, 255, 255))
        components, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for component in components:
            x, y, bw, bh = cv2.boundingRect(component)
            if not (.009*w < bw < .03*w and .01*h < bh < .05*h and 1.05 < bw/bh < 3):
                continue
            tick = mask[y:y+bh, x:x+bw]
            trace = [(i, float(np.median(np.flatnonzero(tick[:, i])))) for i in range(bw) if np.any(tick[:, i])]
            arms = [[v for i, v in trace if lo*bw <= i < hi*bw]
                    for lo, hi in ((0, .15), (.18, .60), (.85, 1))]
            if (all(arms) and max(arms[1])-np.median(arms[0]) > .10*bh
                    and max(arms[1])-np.median(arms[2]) > .40*bh):
                o.visuals.add('theater_complete:' + str(number))
    for t in o.tokens:
        m = re.fullmatch(r'第(\d{1,2})季', norm(t.text))
        if not m or not confident(t) or not o.in_region(t, (.89, .07, .99, .9)):
            continue
        cy = t.center[1]
        patch = hsv[max(0, round(cy-h*.05)):min(h, round(cy+h*.05)), round(w*.875):round(w*.89)]
        if patch.size:
            blue = cv2.inRange(patch, (90, 80, 120), (125, 255, 255)) > 0
            if np.mean(blue) >= .10 and np.mean(np.any(blue, axis=1)) >= .45:
                o.visuals.add('theater_season:' + m[1])
    return o


def paid_play_reading(image, o, reading, state, run_id, evidence_root):
    """Recognize the post-payment FREE play page, never another ticket entry.

    A missing season glow is not guessed: the exact complete subtitle must
    match the immutable, season-verified opening frame in the current chain.
    No context is borrowed for arbitrary lists or before a sent ticket.
    """
    import hashlib
    from pathlib import Path
    from assistant_config import read_json
    from theater_core import Reading
    active=state.get('active')
    compatible_page = reading.scene=='theater_list' or (reading.scene=='theater_blocked' and reading.reason.startswith('未核实本帧1张门票'))
    if (not compatible_page or not active or active.get('run_id')!=run_id
            or active.get('phase')!='await_guide' or active.get('playback_evidence')):
        return reading
    payments=[r for r in state.get('actions',[]) if r.get('key')==active.get('key') and r.get('kind')=='ticket']
    if len(payments)!=1 or payments[0].get('status')!='sent' or payments[0].get('run_id')!=run_id:
        return reading
    directory=read_directory(o)
    if directory is None or directory.cost is not None or directory.stock is not None or directory.view is None:
        return reading
    n=active.get('number')
    selected={int(v.split(':')[1]) for v in o.visuals if re.fullmatch(r'theater_(?:soft_)?selected:\d+',v)}
    if selected!={n}:
        return reading
    rows=[r for r in directory.rows if r.number==n and not r.locked and not r.countdown and not r.completed and not r.completion_unknown]
    if len(rows)!=1:
        return reading
    available=[t for t in o.tokens if confident(t) and norm(t.text)=='可观览'
               and o.in_region(t,(.735,.13,.877,.995)) and 0<t.center[1]-rows[0].token.center[1]<o.height*.065]
    if len(available)!=1:
        return reading
    captions=[norm(t.text) for t in o.tokens if confident(t) and o.in_region(t,(.015,.60,.46,.79)) and norm(t.text).startswith('第'+str(n)+'集')]
    logo=[t for t in o.tokens if confident(t) and o.in_region(t,(.02,.10,.33,.40))
          and .06*o.height<=t.h<=.20*o.height and re.fullmatch(r'[㐀-鿿]{1,12}',norm(t.text))]
    if ''.join(norm(t.text) for t in sorted(logo,key=lambda t:(t.y,t.x)))!=active.get('series') or len(captions)!=1:
        return reading
    root=Path(evidence_root).resolve();source=(root/active.get('evidence','')).resolve()
    if not source.is_relative_to(root/'evidence') or not source.is_file():
        return reading
    meta=read_json(source.with_suffix('.json'))
    if (not meta or meta.get('run_id')!=active.get('source_run_id',run_id) or meta.get('scene')!='theater_list' or meta.get('image_sha256')!=hashlib.sha256(source.read_bytes()).hexdigest()
            or meta.get('episode')!={k:active.get(k) for k in ('series','number','season')}):
        return reading
    original=[norm(t['text']) for t in meta['tokens'] if t.get('score',0)>=.85
              and .015*meta['width']<(t['x']+t['w']/2)<.46*meta['width']
              and .60*meta['height']<(t['y']+t['h']/2)<.79*meta['height']
              and norm(t['text']).startswith('第'+str(n)+'集')]
    if captions!=original or (directory.episode is not None and directory.episode.key!=active.get('key')):
        return reading
    hsv=cv2.cvtColor(np.asarray(image.convert('RGB').resize((1600,900))),cv2.COLOR_RGB2HSV)
    green=cv2.inRange(hsv[801:864,880:1136],(35,50,20),(90,255,255))>0
    if float(green.mean())<.65:
        return reading
    return Reading('theater_paid_ready',directory.view,Episode(active['series'],n,active['season']),
                   reason='同一付费入场的已解锁免费播放页；不重复确认门票。')


def reward_return_reading(o, reading, state, run_id, evidence_root):
    """Resolve only the exact post-reward directory when its season glow fades.

    Immutable, directly season-verified claim proof + the adjacent sent free
    dismissal anchor this context. Never restore an archive or invent a clear.
    """
    import copy
    import hashlib
    from pathlib import Path
    from dataclasses import replace
    from assistant_config import read_json
    from abyss_core import Observation, Token
    from theater_core import classify
    if (reading.scene != 'theater_list' or reading.episode is not None
            or any(re.fullmatch(r'theater_season:\d+', v) for v in o.visuals)):
        return reading
    actions = state.get('actions', [])
    if len(actions) < 2:
        return reading
    claim, close = actions[-2:]
    if (not isinstance(claim.get('id'), str) or not claim['id']
            or not isinstance(claim.get('evidence'), str) or not claim['evidence']):
        return reading
    if (claim.get('kind') != 'claim_reward' or claim.get('status') != 'sent'
            or close.get('kind') != 'close_reward_notice' or close.get('status') != 'sent'
            or close.get('run_id') != run_id):
        return reading
    active = state.get('active')
    if active:
        if (active.get('run_id') != run_id or close.get('key') != active.get('key')
                or claim.get('run_id') != run_id):
            return reading
        entry = active
    else:
        # A current-screen start can close an already-claimed notice without
        # recovering the old entry. Require the immediately preceding claim
        # and the latest untouched archive; all other current-run inputs veto.
        own = [a for a in actions if a.get('run_id') == run_id]
        archives = state.get('unresolved_entries', [])
        if (len(own) != 1 or close.get('key') is not None or not archives
                or not isinstance(archives[-1].get('entry'), dict)):
            return reading
        entry = archives[-1]['entry']
        if entry.get('run_id') != claim.get('run_id'):
            return reading
    if (entry.get('phase') != 'story' or not entry.get('playback_evidence')
            or claim.get('key') != entry.get('key')
            or sum(a.get('kind') == 'claim_reward' and a.get('key') == entry.get('key')
                   for a in actions) != 1):
        return reading
    root = Path(evidence_root).resolve()
    source = (root / claim.get('evidence', '')).resolve()
    if not source.is_relative_to(root/'evidence') or not source.is_file():
        return reading
    try:
        meta = read_json(source.with_suffix('.json'))
        if (not isinstance(meta, dict) or meta.get('run_id') != claim.get('run_id') or meta.get('scene') != 'theater_reward_ready'
                or meta.get('image_sha256') != hashlib.sha256(source.read_bytes()).hexdigest()):
            return reading
        source_o = Observation(meta['width'], meta['height'], [Token(**t) for t in meta['tokens']],
                               meta['captured_at'], visuals=set(meta['visuals']))
        source_reading = classify(source_o)
        expected = source_reading.episode
        old_episode = Episode(entry['series'], entry['number'], entry['season'])
        if (source_reading.scene != 'theater_reward_ready' or expected is None
                or source_reading.reward_episode != old_episode or claim.get('episode') != expected.key
                or expected.series != old_episode.series or expected.season != old_episode.season
                or expected.number not in (old_episode.number, old_episode.number+1)
                or {v for v in source_o.visuals if v.startswith('theater_season:')}
                   != {'theater_season:'+str(expected.season)}):
            return reading
        def caption(obs):
            return [norm(t.text) for t in obs.tokens if confident(t)
                    and obs.in_region(t, (.015,.60,.46,.79))
                    and norm(t.text).startswith('第'+str(expected.number)+'集')]
        current_caption, original_caption = caption(o), caption(source_o)
        if len(current_caption) != 1 or current_caption != original_caption:
            return reading
        contextual = copy.deepcopy(o)
        contextual.visuals.add('theater_season:'+str(expected.season))
        resolved = classify(contextual)
        if (resolved.episode != expected or old_episode.number not in resolved.completed
                or resolved.scene not in ('theater_list', 'theater_empty', 'theater_select_episode')):
            return reading
    except (OSError, ValueError, TypeError, KeyError):
        return reading
    # Audit provenance separately; do not label an absent glow as direct vision.
    o.visuals.add('theater_reward_context:'+claim['id'])
    return replace(resolved, reason='已哈希核验原领奖页；同剧目/完整集名/选框与独立完成行一致，沿原季数上下文。')


def free_start_reading(image, o, reading, state):
    """A free page can start only when no pending entry exists."""
    if state.get('active'):
        return reading
    return free_play_reading(image, o, reading)


def free_play_reading(image, o, reading, *, pressed_observation=False):
    """Recognize a complete zero-cost page; classification alone permits no input.

    Never borrows or clears a pending paid chain. A positive green button
    spanning the former fee panel is required, not just missing fee OCR.
    """
    from theater_core import Reading
    compatible = reading.scene == 'theater_list' or (
        reading.scene == 'theater_blocked' and reading.reason.startswith('未核实本帧1张门票'))
    if not compatible or reading.episode is None:
        return reading
    directory = read_directory(o)
    if (directory is None or directory.episode != reading.episode or directory.view is None
            or directory.cost is not None or directory.stock is not None):
        return reading
    if any(confident(t) and o.in_region(t, (.51, .85, .60, .98))
           and re.fullmatch(r'\d{1,3}/\d{1,5}', norm(t.text)) for t in o.tokens):
        return reading
    rows = [r for r in directory.rows if r.number == reading.episode.number]
    if (len(rows) != 1 or rows[0].locked or rows[0].countdown
            or rows[0].completed or rows[0].completion_unknown or rows[0].reward_ready):
        return reading
    available = [t for t in o.tokens if confident(t) and norm(t.text) == '可观览'
                 and o.in_region(t, (.735, .13, .877, .995))
                 and 0 < t.center[1]-rows[0].token.center[1] < o.height*.065]
    if len(available) != 1:
        return reading
    hsv = cv2.cvtColor(np.asarray(image.convert('RGB').resize((1600, 900))), cv2.COLOR_RGB2HSV)
    # Green surface left of the caption must extend over the cost-panel area.
    # An ordinary ticket entry has a separate dark/gold cost panel here.
    fee_surface = hsv[810:860, 900:940]
    if float((cv2.inRange(fee_surface, (35, 50, 20), (90, 255, 255)) > 0).mean()) < .65:
        return reading
    caption_surface = hsv[801:864, 960:1136]
    if (not pressed_observation
            and float((cv2.inRange(caption_surface, (35, 50, 20), (90, 255, 255)) > 0).mean()) < .65):
        return reading
    # Click feedback can turn the caption blue. This weaker post-send mode
    # returns an observation-only scene, NEVER the free-entry authorization.
    scene = 'theater_free_pending' if pressed_observation else 'theater_free_ready'
    return Reading(scene, directory.view, directory.episode,
                   reason='当前完整同季新集已解锁且费用区域为完整绿色播放控件；只发送一次免费观览。',
                   ticket_cost=0)
