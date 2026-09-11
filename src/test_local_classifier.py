"""Unit tests for local_classifier.classify() using synthetic evidence —
deterministic and fast (no network, no retrieval), unlike
test_verify_medical.py which exercises the full live pipeline. Covers the
branches that are hard to hit reliably by luck through live retrieval:
no evidence, and two sources disagreeing.
"""

from local_classifier import classify


def check(name, result, expected_verdict):
    status = "PASS" if result["verdict"] == expected_verdict else "FAIL"
    print(f"[{status}] {name}: verdict={result['verdict']} confidence={result['confidence']}")
    print(f"         {result['explanation']}")
    return status == "PASS"


def main():
    results = []

    results.append(check(
        "no evidence at all",
        classify("The sky is green.", []),
        "insufficient_evidence",
    ))

    results.append(check(
        "single supporting source",
        classify(
            "Insulin is a hormone made by the pancreas.",
            [{"title": "Diabetes", "extract": "Insulin is a hormone made by your pancreas."}],
        ),
        "supported",
    ))

    results.append(check(
        "single contradicting source",
        classify(
            "Type 1 diabetes can be cured by drinking more water.",
            [{"title": "Diabetes", "extract": "Type 1 diabetes cannot be cured. It is a lifelong condition managed with insulin."}],
        ),
        "contradicted",
    ))

    results.append(check(
        "two sources strongly disagree",
        classify(
            "Vaccines cause autism.",
            [
                {"title": "Vaccine Myth Page", "extract": "Vaccines are a well established cause of autism in children."},
                {"title": "Vaccine Safety", "extract": "There is no link between vaccines and autism. This has been extensively studied and disproven."},
            ],
        ),
        "insufficient_evidence",
    ))

    correct = sum(results)
    print(f"\n{correct}/{len(results)} correct ({correct / len(results):.0%})")


if __name__ == "__main__":
    main()
