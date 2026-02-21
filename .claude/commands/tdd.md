---
description: Test-driven development workflow with pytest. Write tests first, then implement.
---

# TDD Workflow

Follow the RED -> GREEN -> REFACTOR cycle strictly.

## Process

### 1. RED - Write Failing Tests First

- Define the expected behavior as pytest test cases in `tests/`
- Use `fastapi.testclient.TestClient` for endpoint tests
- Mock GCP services (mutate `settings` or patch clients) to avoid external calls
- Run tests to confirm they fail:

```bash
GCP_PROJECT_ID=local-test pytest -q
```

### 2. GREEN - Write Minimal Implementation

- Write the minimum code needed to make tests pass
- Do not optimize or refactor yet
- Run tests to confirm they pass:

```bash
GCP_PROJECT_ID=local-test pytest -q
```

### 3. REFACTOR - Clean Up

- Improve code quality while keeping tests green
- Extract helpers if functions exceed ~50 lines
- Run the full verification loop:

```bash
ruff check main.py config.py tests/ && GCP_PROJECT_ID=local-test pytest -q
```

## Testing Conventions

- Test files: `tests/test_<module>.py`
- Test functions: `def test_<behavior>() -> None:`
- Use `_set_default_test_settings()` pattern from existing tests to reset shared state
- For endpoint tests, always test both success and error paths
- For auth-protected endpoints, test with and without valid API key
