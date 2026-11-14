---
name: stdlib-unittest-runner
description: Enforces conversion of procedural test scripts into standard unittest.TestCase test modules under tests/ and running automated test discovery.
---

# Standard Library Unittest Runner

This skill enforces strict unit and regression testing standards utilizing Python's built-in `unittest` framework with zero external dependencies.

## 1. Test Module Architecture
- All test files must reside in the [tests/](file:///C:/Users/ASUS/Desktop/delta-liquidity-monitor/tests) directory.
- Test filenames must match `test_*.py` pattern.
- Every test module must declare classes inheriting from `unittest.TestCase`.
- Avoid naked `assert` statements in top-level functions or script blocks; use standard assertions:
  - `self.assertEqual(a, b)`
  - `self.assertAlmostEqual(a, b, places=...)`
  - `self.assertTrue(x)`
  - `self.assertRaises(ValueError)`

## 2. Test Execution Command
Run the test suite from the repository root:
```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

## 3. Mandatory Invariant Checks
Unit tests must verify:
- Financial math precision (exact Decimal output, budget conservation).
- Clean handling of edge cases (empty order books, zero depth, network timeouts).
- Idempotency and file safety of storage sinks (CSV, SQLite) using `tempfile.TemporaryDirectory()`.
