import json
from pathlib import Path

_MODEL = None


def load_model(path=None):
    """加载 model.json，缓存。"""
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    if path is None:
        path = Path(__file__).parent / 'model.json'
    with open(path, 'r', encoding='utf-8') as f:
        _MODEL = json.load(f)
    return _MODEL


def L1(hours, relevant_dim_ids, model=None):
    """第一层：价值池 = 相关维度权重之和 × 耗时

    relevant_dim_ids: 只包含「相关」的维度，跳过的维度不在此列表中。
    """
    if model is None:
        model = load_model()
    dim_map = {d['id']: d['weight'] for d in model['dimensions']}
    total_weight = sum(dim_map.get(did, 0) for did in relevant_dim_ids)
    return total_weight * hours


def _get_fuzzy_factor(model):
    f = model.get('formula', {})
    return f.get('fuzzy_factor', 1.0)


def L2(scores, certainty=None, fuzzy_factor=None, model=None):
    """第二层：直接连接 = Σ(维度weight × score × 确定性系数)

    scores: {dim_id: score}
    certainty: {dim_id: bool}  True=确定, False=模糊。缺失默认为 True。
    fuzzy_factor: 模糊维度的折扣系数。默认从 model.json 读取。
    """
    if model is None:
        model = load_model()
    if fuzzy_factor is None:
        fuzzy_factor = _get_fuzzy_factor(model)
    if certainty is None:
        certainty = {}

    dim_map = {d['id']: d['weight'] for d in model['dimensions']}
    total = 0.0
    for dim_id, s in scores.items():
        weight = dim_map.get(dim_id, 0)
        cert = certainty.get(dim_id, True)  # 缺失 = 确定
        factor = 1.0 if cert else fuzzy_factor
        total += weight * s * factor
    return total


def L3(scores, certainty=None, fuzzy_factor=None, model=None):
    """第三层：涟漪扩散 = Σ(维度weight × score × 确定性系数)

    当前计算逻辑与 L2 相同。分离为独立函数是为了将来换网络扩散
    等算法时可以只改 L3，不动 L2。
    """
    return L2(scores, certainty=certainty, fuzzy_factor=fuzzy_factor, model=model)


def _weight_sum(dim_ids, model):
    """计算一组维度 ID 的权重之和"""
    dim_map = {d['id']: d['weight'] for d in model['dimensions']}
    return sum(dim_map.get(did, 0) for did in dim_ids)


def total_score(hours, direct_scores, ripple_scores,
                direct_certainty=None, ripple_certainty=None,
                fuzzy_factor=None, model=None):
    """时间货币公式：有效贡献小时 = A × (L1 / total_weight) × l2_factor × l3_factor

    L1 = 相关维度权重和 × 小时（事件本身的价值池）
    l_factor = 1 + 加权得分 / (权重和 × quality_scale)

    quality_scale = 2.5:
      均分 0   → 系数 1.0（时间等值）
      均分 +2.5 → 系数 2.0（时间加倍）
      均分 -2.5 → 系数 0（时间白费）
      均分 -5  → 系数 -1（帮倒忙）
    """
    if model is None:
        model = load_model()
    if fuzzy_factor is None:
        fuzzy_factor = _get_fuzzy_factor(model)

    dim_map = {d['id']: d['weight'] for d in model['dimensions']}
    total_weight = sum(d['weight'] for d in model['dimensions'])
    f = model['formula']
    A = f['A']
    Q = f.get('quality_scale', 2.5)

    # L1：事件本身的价值池
    l1 = L1(hours, list(direct_scores.keys()), model)

    # L2：直接影响的质量系数
    l2_raw = L2(direct_scores, certainty=direct_certainty,
                fuzzy_factor=fuzzy_factor, model=model)
    l2_weights = _weight_sum(direct_scores.keys(), model)
    l2_norm = l2_raw / (l2_weights * Q) if l2_weights > 0 else 0
    l2_factor = 1 + l2_norm

    # L3：涟漪扩散的质量系数
    l3_raw = L3(ripple_scores, certainty=ripple_certainty,
                fuzzy_factor=fuzzy_factor, model=model)
    l3_weights = _weight_sum(ripple_scores.keys(), model)
    l3_norm = l3_raw / (l3_weights * Q) if l3_weights > 0 else 0
    l3_factor = 1 + l3_norm

    effective_hours = A * (l1 / total_weight) * l2_factor * l3_factor
    return round(effective_hours, 2)


def get_rank(total, model=None):
    """累计总分 → 当前排名"""
    if model is None:
        model = load_model()
    current = model['ranks'][0]
    for rank in model['ranks']:
        if total >= rank['min_score']:
            current = rank
    return current
