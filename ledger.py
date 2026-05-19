import json
from datetime import date
from pathlib import Path

from evaluator import L1, L2, L3, total_score, load_model

_DATA_DIR = Path(__file__).parent / 'data'


def _person_dir(person_id):
    return _DATA_DIR / person_id


def _ensure_person(person_id):
    """首次使用时自动创建个人目录和空文件。"""
    d = _person_dir(person_id)
    d.mkdir(parents=True, exist_ok=True)
    pending_path = d / 'pending.json'
    ledger_path = d / 'ledger.json'
    if not pending_path.exists():
        _save(pending_path, {'person_id': person_id, 'items': []})
    if not ledger_path.exists():
        _save(ledger_path, {'person_id': person_id, 'behaviors': [], 'events': []})
    return d


def _load(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _next_id(prefix, items):
    if not items:
        return f'{prefix}001'
    ids = [item['id'] for item in items if item['id'].startswith(prefix)]
    if not ids:
        return f'{prefix}001'
    max_num = max(int(i[len(prefix):]) for i in ids)
    return f'{prefix}{max_num + 1:03d}'


# ── 事件 ──────────────────────────────────────────────

def add_event(person_id, name, parent_event_id=None):
    """创建新事件（写入个人账本）。"""
    _ensure_person(person_id)
    ledger_path = _person_dir(person_id) / 'ledger.json'
    data = _load(ledger_path)
    eid = _next_id('e', data['events'])
    data['events'].append({
        'id': eid,
        'name': name,
        'parent_event_id': parent_event_id,
        'status': 'ongoing',
        'outcome': None,
    })
    _save(ledger_path, data)
    return eid


def complete_event(person_id, event_id, outcome):
    """完结事件。返回未结算分配列表供回溯评分。"""
    ledger_path = _person_dir(person_id) / 'ledger.json'
    data = _load(ledger_path)
    for ev in data['events']:
        if ev['id'] == event_id:
            ev['status'] = 'completed'
            ev['outcome'] = outcome
            break
    _save(ledger_path, data)
    return get_unsettled_allocations(person_id, event_id)


def get_event(person_id, event_id):
    ledger_path = _person_dir(person_id) / 'ledger.json'
    data = _load(ledger_path)
    for ev in data['events']:
        if ev['id'] == event_id:
            return ev
    return None


# ── 待分配池（pending.json）──────────────────────────

def add_pending(person_id, description, hours, dimensions, asset=None, notes=None):
    """行为父事件不明确 → 写入待分配池。"""
    _ensure_person(person_id)
    pending_path = _person_dir(person_id) / 'pending.json'
    data = _load(pending_path)
    pid = _next_id('p', data['items'])
    data['items'].append({
        'id': pid,
        'timestamp': str(date.today()),
        'description': description,
        'hours': hours,
        'dimensions': dimensions,
        'asset': asset,
        'notes': notes,
    })
    _save(pending_path, data)
    return pid


def get_pending_pool(person_id):
    """返回某人待分配池中所有行为。"""
    pending_path = _person_dir(person_id) / 'pending.json'
    if not pending_path.exists():
        return []
    data = _load(pending_path)
    return data['items']


def classify_pending(person_id, pending_id, parent_event_id):
    """归类：从待分配池移除 → 写入账本 → 创建分配。

    返回 (behavior_id, allocation_index)
    """
    _ensure_person(person_id)
    pending_path = _person_dir(person_id) / 'pending.json'
    ledger_path = _person_dir(person_id) / 'ledger.json'

    pending_data = _load(pending_path)
    item = None
    for i, p in enumerate(pending_data['items']):
        if p['id'] == pending_id:
            item = pending_data['items'].pop(i)
            break
    if item is None:
        raise ValueError(f'待分配项 {pending_id} 不存在')

    _save(pending_path, pending_data)

    ledger_data = _load(ledger_path)
    bid = _next_id('b', ledger_data['behaviors'])
    behavior = {
        'id': bid,
        'timestamp': item['timestamp'],
        'description': item['description'],
        'hours': item['hours'],
        'dimensions': item['dimensions'],
        'asset': item.get('asset'),
        'allocations': [{
            'parent_event_id': parent_event_id,
            'status': 'provisional',
            'scores': None,
            'certainty': {},
            'allocated_at': str(date.today()),
            'settled_at': None,
        }],
    }
    ledger_data['behaviors'].append(behavior)
    _save(ledger_path, ledger_data)

    return bid, 0


# ── 行为记录（ledger.json）────────────────────────────

def add_behavior(person_id, description, hours, dimensions,
                 parent_event_id=None, asset=None):
    """记录一个行为。

    如果 parent_event_id 提供 → 直接写入账本并创建分配记录。
    如果 parent_event_id 为空 → 写入待分配池（等同 add_pending）。
    """
    if parent_event_id is None:
        return add_pending(person_id, description, hours, dimensions,
                          asset=asset)

    _ensure_person(person_id)
    ledger_path = _person_dir(person_id) / 'ledger.json'
    data = _load(ledger_path)
    bid = _next_id('b', data['behaviors'])
    data['behaviors'].append({
        'id': bid,
        'timestamp': str(date.today()),
        'description': description,
        'hours': hours,
        'dimensions': dimensions,
        'asset': asset,
        'allocations': [{
            'parent_event_id': parent_event_id,
            'status': 'provisional',
            'scores': None,
            'certainty': {},
            'allocated_at': str(date.today()),
            'settled_at': None,
        }],
    })
    _save(ledger_path, data)
    return bid


def get_behavior(person_id, bid):
    ledger_path = _person_dir(person_id) / 'ledger.json'
    if not ledger_path.exists():
        return None
    data = _load(ledger_path)
    for b in data['behaviors']:
        if b['id'] == bid:
            return b
    return None


# ── 分配 ──────────────────────────────────────────────

def allocate(person_id, behavior_id, parent_event_id):
    """为已存在的 behavior 追加一个分配（资产复用）。"""
    ledger_path = _person_dir(person_id) / 'ledger.json'
    data = _load(ledger_path)
    for b in data['behaviors']:
        if b['id'] == behavior_id:
            alloc = {
                'parent_event_id': parent_event_id,
                'status': 'provisional',
                'scores': None,
                'certainty': {},
                'allocated_at': str(date.today()),
                'settled_at': None,
            }
            b['allocations'].append(alloc)
            _save(ledger_path, data)
            return len(b['allocations']) - 1
    raise ValueError(f'行为 {behavior_id} 不存在')


# ── 结算 ──────────────────────────────────────────────

def settle(person_id, behavior_id, allocation_index, scores, certainty=None):
    """为一个 allocation 写入评分。

    可多次调用（修正评分）。父事件 completed 时自动标记为 settled。
    """
    ledger_path = _person_dir(person_id) / 'ledger.json'
    data = _load(ledger_path)
    for b in data['behaviors']:
        if b['id'] == behavior_id:
            alloc = b['allocations'][allocation_index]
            alloc['scores'] = scores
            if certainty:
                alloc['certainty'] = certainty
            alloc['settled_at'] = str(date.today())

            parent_event = get_event(person_id, alloc['parent_event_id'])
            if parent_event and parent_event['status'] == 'completed':
                alloc['status'] = 'settled'
            else:
                alloc['status'] = 'provisional'

            _save(ledger_path, data)
            return alloc
    raise ValueError(f'行为 {behavior_id} 不存在')


# ── 查询 ──────────────────────────────────────────────

def get_unsettled_allocations(person_id, event_id):
    """某事件下所有未锁定分配。"""
    ledger_path = _person_dir(person_id) / 'ledger.json'
    if not ledger_path.exists():
        return []
    data = _load(ledger_path)
    result = []
    for b in data['behaviors']:
        for i, a in enumerate(b['allocations']):
            if a['parent_event_id'] == event_id and a['status'] != 'settled':
                result.append({
                    'behavior_id': b['id'],
                    'allocation_index': i,
                    'scores': a['scores'],
                    'status': a['status'],
                })
    return result


def compute_contribution(person_id, behavior_id, allocation_index, model=None):
    """计算某个 allocation 的有效贡献小时。"""
    if model is None:
        model = load_model()

    b = get_behavior(person_id, behavior_id)
    if b is None:
        raise ValueError(f'行为 {behavior_id} 不存在')
    alloc = b['allocations'][allocation_index]

    if alloc['scores'] is None:
        raise ValueError(f'分配尚未评分，无法计算贡献')

    score = total_score(
        b['hours'],
        direct_scores=alloc['scores'],
        ripple_scores={},
        direct_certainty=alloc.get('certainty') or None,
        model=model,
    )
    from evaluator import get_rank
    rank = get_rank(score, model)
    return score, rank


def compute_person_total(person_id, model=None):
    """计算某人所有已评分分配的累计有效小时和排名。"""
    if model is None:
        model = load_model()

    ledger_path = _person_dir(person_id) / 'ledger.json'
    if not ledger_path.exists():
        return 0.0, None

    data = _load(ledger_path)
    total = 0.0
    for b in data['behaviors']:
        for alloc in b['allocations']:
            if alloc['scores'] is not None:
                score, _ = compute_contribution(person_id, b['id'],
                                                b['allocations'].index(alloc),
                                                model=model)
                total += score

    from evaluator import get_rank
    return round(total, 2), get_rank(total, model)


def compute_event_total(person_id, event_id, model=None):
    """某事件下所有已评分分配的累计有效小时。"""
    if model is None:
        model = load_model()

    ledger_path = _person_dir(person_id) / 'ledger.json'
    if not ledger_path.exists():
        return 0.0, None

    data = _load(ledger_path)
    total = 0.0
    for b in data['behaviors']:
        for alloc in b['allocations']:
            if (alloc['parent_event_id'] == event_id
                    and alloc['scores'] is not None):
                score, _ = compute_contribution(person_id, b['id'],
                                                b['allocations'].index(alloc),
                                                model=model)
                total += score

    from evaluator import get_rank
    return round(total, 2), get_rank(total, model)


def get_event_behaviors(person_id, event_id):
    """某事件下所有已分配行为（含原始小时和评分状态）。"""
    ledger_path = _person_dir(person_id) / 'ledger.json'
    if not ledger_path.exists():
        return []
    data = _load(ledger_path)
    result = []
    for b in data['behaviors']:
        for alloc in b['allocations']:
            if alloc['parent_event_id'] == event_id:
                result.append({
                    'behavior_id': b['id'],
                    'description': b['description'],
                    'hours': b['hours'],
                    'dimensions': b['dimensions'],
                    'scores': alloc['scores'],
                    'status': alloc['status'],
                })
    return result


def get_ongoing_events(person_id):
    """进行中的事件列表（供冷启动了解当前状态）。"""
    ledger_path = _person_dir(person_id) / 'ledger.json'
    if not ledger_path.exists():
        return []
    data = _load(ledger_path)
    return [ev for ev in data['events'] if ev['status'] == 'ongoing']
