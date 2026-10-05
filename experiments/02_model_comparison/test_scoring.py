"""Protect the comparison from optimistic scoring of failed or invented outputs."""
import copy
import json
import unittest
from pathlib import Path
from compare_models import score

class ScoringChecks(unittest.TestCase):
    def setUp(self):
        self.gold = json.loads(Path(__file__).with_name('cases_test.json').read_text())[:1]
        case = self.gold[0]
        self.record = {'id': case['id'], 'answer': copy.deepcopy(case['gold']),
                       'validation_errors': [], 'differences': []}

    def test_perfect_reference_has_full_accuracy(self):
        result = score({'cases': [self.record]}, self.gold)
        self.assertEqual(result['status_accuracy'], 1)
        self.assertEqual(result['status_macro_f1'], 1)
        self.assertEqual(result['valid_cases'], 1)

    def test_failed_response_is_not_removed_from_denominator(self):
        result = score({'cases': [{'id': self.record['id'], 'error': 'timeout'}]}, self.gold)
        self.assertEqual(result['field_count'], 6)
        self.assertEqual(result['status_accuracy'], 0)
        self.assertEqual(result['valid_cases'], 0)

    def test_invented_medication_counts_as_unsupported_positive(self):
        self.record['answer']['已用药物']['status'] = 'present'
        result = score({'cases': [self.record]}, self.gold)
        self.assertEqual(result['unsupported_positive_fields'], 1)

if __name__ == '__main__':
    unittest.main()
