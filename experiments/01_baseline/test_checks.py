"""Checks for evaluation mistakes that would make model comparisons misleading."""
import copy
import json
import unittest
from pathlib import Path
from run import compare, validate


class EvaluationChecks(unittest.TestCase):
    def setUp(self):
        self.case = json.loads(Path(__file__).with_name("cases.json").read_text())[0]
        self.answer = copy.deepcopy(self.case["gold"])

    def test_reference_is_valid(self):
        self.assertEqual(validate(self.answer, self.case["turns"]), [])
        self.assertEqual(compare(self.answer, self.case["gold"]), [])

    def test_invented_quote_is_rejected(self):
        self.answer["咳嗽"]["evidence"][0]["quote"] = "凭空捏造的话"
        self.assertTrue(validate(self.answer, self.case["turns"]))

    def test_doctor_question_is_not_patient_evidence(self):
        self.answer["咳嗽"]["evidence"] = [{"turn_id": 1, "quote": "发烧"}]
        self.assertTrue(validate(self.answer, self.case["turns"]))

    def test_negation_error_is_visible_even_with_valid_quote(self):
        self.answer["发热"]["status"] = "present"
        self.answer["发热"]["value"] = "没有发烧"
        self.assertEqual(validate(self.answer, self.case["turns"]), [])
        self.assertTrue(compare(self.answer, self.case["gold"]))


if __name__ == "__main__":
    unittest.main()
