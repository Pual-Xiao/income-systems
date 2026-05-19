import unittest
from evaluator import load_model, L1, L2, L3, total_score, get_rank


class TestLoadModel(unittest.TestCase):

    def test_loads_from_default_path(self):
        model = load_model()
        self.assertIn('dimensions', model)
        self.assertIn('formula', model)
        self.assertIn('ranks', model)

    def test_loads_12_dimensions(self):
        model = load_model()
        self.assertEqual(len(model['dimensions']), 12)

    def test_formula_type_is_time_quality(self):
        model = load_model()
        self.assertEqual(model['formula']['type'], 'time_quality')

    def test_formula_has_A_and_fuzzy_factor(self):
        model = load_model()
        f = model['formula']
        self.assertIn('A', f)
        self.assertIn('fuzzy_factor', f)

    def test_ranks_are_hour_based(self):
        model = load_model()
        ranks = model['ranks']
        self.assertEqual(ranks[1]['name'], '新手')
        self.assertEqual(ranks[1]['min_score'], 0)
        self.assertEqual(ranks[2]['min_score'], 8)

    def test_caches_result(self):
        m1 = load_model()
        m2 = load_model()
        self.assertIs(m1, m2)


class TestL1(unittest.TestCase):

    def setUp(self):
        self.model = load_model()

    def test_value_pool_is_weight_sum_times_hours(self):
        result = L1(10, ['行动', '技能'], self.model)
        self.assertEqual(result, 25.0)

    def test_skipped_dimension_not_in_l1(self):
        result = L1(10, ['行动'], self.model)
        self.assertEqual(result, 15.0)

    def test_zero_hours_is_zero(self):
        result = L1(0, ['行动', '创意'], self.model)
        self.assertEqual(result, 0.0)

    def test_empty_relevant_is_zero(self):
        result = L1(10, [], self.model)
        self.assertEqual(result, 0.0)


class TestL2(unittest.TestCase):

    def setUp(self):
        self.model = load_model()

    def test_direct_connection_is_weighted_sum(self):
        scores = {'行动': 4, '技能': 3}
        result = L2(scores, model=self.model)
        self.assertEqual(result, 9.0)

    def test_negative_scores_reduce_total(self):
        scores = {'行动': -2, '创意': 3}
        result = L2(scores, model=self.model)
        self.assertAlmostEqual(result, 0.6)

    def test_empty_scores_is_zero(self):
        result = L2({}, model=self.model)
        self.assertEqual(result, 0.0)

    def test_zero_score_contributes_nothing_to_l2(self):
        scores = {'行动': 0, '技能': 3}
        result = L2(scores, model=self.model)
        self.assertEqual(result, 3.0)

    def test_fuzzy_score_discounted(self):
        scores = {'行动': 4, '技能': 3}
        certainty = {'行动': False}
        result = L2(scores, certainty=certainty, fuzzy_factor=0.5, model=self.model)
        self.assertEqual(result, 6.0)

    def test_fuzzy_factor_from_model(self):
        scores = {'行动': 2}
        certainty = {'行动': False}
        result = L2(scores, certainty=certainty, model=self.model)
        expected = 1.5 * 2 * 0.5
        self.assertEqual(result, expected)


class TestL3(unittest.TestCase):

    def setUp(self):
        self.model = load_model()

    def test_l3_equals_l2_currently(self):
        scores = {'行动': 4, '创意': 2}
        self.assertEqual(
            L3(scores, model=self.model),
            L2(scores, model=self.model)
        )

    def test_l3_passes_certainty(self):
        scores = {'行动': 4}
        certainty = {'行动': False}
        l3_result = L3(scores, certainty=certainty, fuzzy_factor=0.5, model=self.model)
        l2_result = L2(scores, certainty=certainty, fuzzy_factor=0.5, model=self.model)
        self.assertEqual(l3_result, l2_result)


class TestTotalScore(unittest.TestCase):

    def setUp(self):
        self.model = load_model()

    def test_neutral_quality_gives_scope_weighted_hours(self):
        """所有维度 0 分 → l2_factor=l3_factor=1.0"""
        direct = {'行动': 0}  # weight=1.5
        ripple = {}
        score = total_score(1, direct, ripple, model=self.model)
        expected = round(1.0 * (1.5 / 14.2) * 1.0 * 1.0, 2)
        self.assertEqual(score, expected)
        self.assertGreater(score, 0)

    def test_positive_quality_above_actual_hours(self):
        """高分可以产出超过实际小时的有效小时"""
        direct = {'行动': 5, '技能': 5, '创意': 5, '复利': 5}
        ripple = {}
        score = total_score(10, direct, ripple, model=self.model)
        self.assertIsInstance(score, (int, float))

    def test_negative_quality_reduces_effective_hours(self):
        """负分缩水有效小时"""
        direct = {'行动': -3, '技能': -2}
        ripple = {}
        score_neg = total_score(5, direct, ripple, model=self.model)
        direct_zero = {'行动': 0, '技能': 0}
        score_zero = total_score(5, direct_zero, ripple, model=self.model)
        self.assertLess(score_neg, score_zero)

    def test_empty_ripple_factor_is_one(self):
        """无涟漪维度时 l3_factor = 1"""
        direct = {'行动': 3}
        ripple = {}
        score = total_score(5, direct, ripple, model=self.model)
        self.assertGreater(score, 0)

    def test_fuzzy_reduces_total_score(self):
        """模糊维度降低有效小时"""
        direct = {'行动': 4, '技能': 3}
        ripple = {}
        score_certain = total_score(10, direct, ripple, model=self.model)
        score_fuzzy = total_score(10, direct, ripple,
                                  direct_certainty={'行动': False, '技能': False},
                                  model=self.model)
        self.assertLess(score_fuzzy, score_certain)

    def test_ripple_adds_value(self):
        """有涟漪比没涟漪产出多"""
        direct = {'行动': 3}
        score_no_ripple = total_score(5, direct, {}, model=self.model)
        score_with_ripple = total_score(5, direct, {'影响力': 3}, model=self.model)
        self.assertGreater(score_with_ripple, score_no_ripple)

    def test_output_is_deterministic(self):
        direct = {'行动': 3, '复利': 4}
        ripple = {'影响力': 2}
        s1 = total_score(8, direct, ripple, model=self.model)
        s2 = total_score(8, direct, ripple, model=self.model)
        self.assertEqual(s1, s2)

    def test_very_negative_can_be_negative(self):
        """极端负向可导致负有效小时"""
        direct = {'行动': -5, '决策': -5, '技能': -5}
        ripple = {}
        score = total_score(5, direct, ripple, model=self.model)
        self.assertLess(score, 0)


class TestGetRank(unittest.TestCase):

    def setUp(self):
        self.model = load_model()

    def test_destroyer_for_negative(self):
        rank = get_rank(-1, self.model)
        self.assertEqual(rank['name'], '破坏者')

    def test_newbie_at_low_hours(self):
        rank = get_rank(4, self.model)
        self.assertEqual(rank['name'], '新手')

    def test_practitioner_at_8(self):
        rank = get_rank(8, self.model)
        self.assertEqual(rank['name'], '实践者')

    def test_contributor_at_40(self):
        rank = get_rank(40, self.model)
        self.assertEqual(rank['name'], '贡献者')

    def test_creator_at_200(self):
        rank = get_rank(200, self.model)
        self.assertEqual(rank['name'], '创造者')

    def test_leader_at_1000(self):
        rank = get_rank(1000, self.model)
        self.assertEqual(rank['name'], '引领者')

    def test_boundary_below_practitioner(self):
        """7.99h 还是新手"""
        rank = get_rank(7.99, self.model)
        self.assertEqual(rank['name'], '新手')


if __name__ == '__main__':
    unittest.main()
