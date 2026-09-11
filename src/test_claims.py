"""Run the hand-picked claim set through verify() and report accuracy.

This is the Phase 8 "MVP validation" idea pulled forward to Phase 2 scale:
before building anything else, know whether the core loop is even accurate
enough to be worth productizing.
"""

import json
import sys
import time

from verify import verify

CLAIMS_FILE = "src/json/claims.json"


def main():
    with open(CLAIMS_FILE) as f:
        cases = json.load(f)

    correct = 0
    results = []

    for case in cases:
        claim = case["claim"]
        expected = case["expected"]
        try:
            result = verify(claim)
            actual = result["verdict"]
        except Exception as e:
            actual = f"ERROR: {e}"
            result = {}

        is_correct = actual == expected
        correct += is_correct
        results.append({
            "claim": claim,
            "expected": expected,
            "actual": actual,
            "correct": is_correct,
            "confidence": result.get("confidence"),
            "evidence_count": result.get("evidence_count"),
        })

        status = "PASS" if is_correct else "FAIL"
        print(f"[{status}] expected={expected:22s} got={actual:22s} claim={claim}")
        time.sleep(0.3)  # be polite to Wikipedia's API

    total = len(cases)
    print(f"\n{correct}/{total} correct ({correct / total:.0%})")

    with open("src/json/test_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("Full results written to test_results.json")


if __name__ == "__main__":
    sys.exit(main())
