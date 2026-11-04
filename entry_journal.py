"""Keep original attempts while distinguishing cancelled taps from actual entries."""
import copy
import hashlib
import json
import time
import uuid


def attempt_digest(entry):
    return hashlib.sha256(json.dumps(entry,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()


def can_enter(ledger,key):
    key=str(key)
    if key in ledger['completed']:return False
    if key not in ledger['attempted']:return True
    records=ledger.get('entry_dispatches',{}).get(key,[])
    digest=attempt_digest(ledger['attempted'][key])
    # Every earlier reservation must have affirmative evidence of zero press.
    # Missing/unknown/sent states and mismatched original records stay blocked.
    return bool(records) and all(r.get('status')=='not_sent' and r.get('original_sha256')==digest for r in records)


def reserve_entry(ledger,key,details):
    key=str(key)
    if not can_enter(ledger,key):raise ValueError('该关已有实际或结果不明的入场记录，不重复开战。')
    ledger['attempted'].setdefault(key,copy.deepcopy(details))
    record=dict(id=uuid.uuid4().hex,status='reserved',reserved_at=time.time(),
                original_sha256=attempt_digest(ledger['attempted'][key]),entry=copy.deepcopy(details))
    ledger.setdefault('entry_dispatches',{}).setdefault(key,[]).append(record)
    return record


def finish_dispatch(record,status,reason=''):
    if record['status']!='reserved' or status not in ('sent','not_sent'):
        raise ValueError('入场发送记录状态不一致。')
    record.update(status=status,finished_at=time.time(),reason=reason)
