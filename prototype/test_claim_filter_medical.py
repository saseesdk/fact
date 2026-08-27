"""Validate claim_filter.py on medical-style text specifically. The existing
claim_filter_test.json (Eiffel Tower, capitals, "time is money") predates
the medical-domain pivot (ROADMAP.md Phase 1) and never actually tested the
segregation step against the kind of text this prototype now targets:
health claims, hedged research language ("studies suggest"), and
medical-opinion rhetoric (miracle cures, anti-pharma sentiment).
"""

import json

from claim_filter import classify_statement, is_checkable_claim

CASES_FILE = "medical_segregation_test.json"


def main():
    with open(CASES_FILE) as f:
        cases = json.load(f)

    correct = 0
    for case in cases:
        scores = classify_statement(case["sentence"])
        actual = "fact" if is_checkable_claim(scores) else "opinion"
        is_correct = actual == case["expected"]
        correct += is_correct
        status = "PASS" if is_correct else "FAIL"
        print(f"[{status}] expected={case['expected']:8s} got={actual:8s} {scores}  {case['sentence']}")

    print(f"\n{correct}/{len(cases)} correct ({correct / len(cases):.0%})")


if __name__ == "__main__":
    main()
