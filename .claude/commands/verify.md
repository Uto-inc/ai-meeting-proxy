---
description: Run full verification loop (lint, security scan, tests) before committing.
---

# Verification Loop

Run each phase sequentially. Stop immediately on failure and report the issue.

## Phase 1: Lint & Format Check

```bash
ruff check main.py config.py tests/
ruff format --check main.py config.py tests/
```

If ruff finds fixable issues, fix them with `ruff check --fix` and `ruff format`, then re-run the check.

## Phase 2: Security Scan

```bash
bandit -r main.py config.py -q
```

Report any findings. High/Medium severity issues must be fixed before proceeding.

## Phase 3: Tests

```bash
GCP_PROJECT_ID=local-test pytest -q
```

All tests must pass.

## Phase 4: Diff Review

```bash
git diff --stat
```

Review the diff for:
- Hardcoded secrets or API keys
- Debug print() statements left in code
- Unintended file changes
- Files over 800 lines

## Output

Report results in this format:

| Phase | Status |
|-------|--------|
| Lint | PASS/FAIL |
| Security | PASS/FAIL |
| Tests | PASS/FAIL |
| Diff Review | PASS/FAIL |

**Overall: READY / NOT READY**
