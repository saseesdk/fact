"""Real end-to-end accuracy check for the medical pipeline: retrieval
(MedlinePlus) + NLI verdict, on actual medical claims — not the general
trivia set in claim_filter_test.json / test_claims.py, which predate the
medical-domain pivot (see ROADMAP.md Phase 1) and no longer reflect what
this prototype is actually being asked to do.
"""

import json

from verify import verify

CASES_FILE = "medical_claims_test.json"


def main():
    with open(CASES_FILE) as f:
        cases = json.load(f)

    correct = 0
    for case in cases:
        result = verify(case["claim"])
        is_correct = result["verdict"] == case["expected"]
        correct += is_correct
        status = "PASS" if is_correct else "FAIL"
        print(
            f"[{status}] expected={case['expected']:22s} got={result['verdict']:22s} "
            f"conf={result['confidence']:.2f} evidence={result['evidence_count']} "
            f"{case['claim']}"
        )
        print(f"         {result['explanation']}")

    print(f"\n{correct}/{len(cases)} correct ({correct / len(cases):.0%})")


if __name__ == "__main__":
    main()
