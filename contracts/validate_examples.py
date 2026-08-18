"""Phase 0 검증 스크립트: contracts/*.schema.json 예시 인스턴스가 스키마를 통과하는지 확인.

사용법: python contracts/validate_examples.py
"""
import json
import sys
from pathlib import Path

import jsonschema

CONTRACTS_DIR = Path(__file__).parent
EXAMPLES_DIR = CONTRACTS_DIR / "examples"

CASES = [
    ("component-descriptor.schema.json", "valid-temperature-sensor.json", True),
    ("component-descriptor.schema.json", "invalid-missing-required-field.json", False),
]


def main() -> int:
    failures = 0
    for schema_file, example_file, expect_valid in CASES:
        schema = json.loads((CONTRACTS_DIR / schema_file).read_text(encoding="utf-8"))
        instance = json.loads((EXAMPLES_DIR / example_file).read_text(encoding="utf-8"))

        errors = list(jsonschema.Draft202012Validator(schema).iter_errors(instance))
        is_valid = len(errors) == 0

        status = "OK" if is_valid == expect_valid else "FAIL"
        print(f"[{status}] {example_file} against {schema_file} "
              f"(expected_valid={expect_valid}, actual_valid={is_valid})")
        if is_valid != expect_valid:
            failures += 1
            for e in errors:
                print(f"    - {e.message}")

    if failures:
        print(f"\n{failures} case(s) failed.")
        return 1
    print("\nAll cases passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
