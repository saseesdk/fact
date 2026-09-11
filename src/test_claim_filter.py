"""Validate the fact/opinion separation before wiring it into verify().

Metaphors are graded against "opinion" (i.e. "not checkable") — see the
calibration notes at the top of claim_filter.py for why a 3-way split was
dropped in favor of this binary one.
"""

import json

from claim_filter import classify_statement, is_checkable_claim

CASES_FILE = "src/json/claim_filter_test.json"

EXPECTED_MAP = {
    "factual claim": "fact",
    "opinion or subjective statement": "opinion",
    "metaphor or figurative expression": "opinion",
}


def main():
    with open(CASES_FILE) as f:
        cases = json.load(f)

    correct = 0
    for case in cases:
        expected = EXPECTED_MAP[case["expected"]]
        scores = classify_statement(case["sentence"])
        actual = "fact" if is_checkable_claim(scores) else "opinion"
        is_correct = actual == expected
        correct += is_correct
        status = "PASS" if is_correct else "FAIL"
        print(f"[{status}] expected={expected:8s} got={actual:8s} {scores}  {case['sentence']}")

    print(f"\n{correct}/{len(cases)} correct ({correct / len(cases):.0%})")


if __name__ == "__main__":
    main()
