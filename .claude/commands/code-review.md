---
description: Review staged or recent changes for quality, security, and correctness.
---

# Code Review

Review the current changes (staged + unstaged) against this checklist.

## Steps

1. Run `git diff` to see all changes (staged and unstaged).
2. If no changes, run `git diff HEAD~1` to review the latest commit.

## Review Checklist

### Correctness
- Logic errors or off-by-one mistakes
- Missing error handling for edge cases
- Async/sync mismatches (blocking calls in async functions should use `run_in_threadpool`)

### Security
- No hardcoded secrets, API keys, or tokens
- All user inputs validated via Pydantic or `_normalize_text_input`
- HTTP error responses don't leak internal details
- File uploads validated (MIME + extension + magic bytes)

### Python Quality
- Type hints on all function signatures
- `logging` used instead of `print()`
- f-strings for string formatting
- No unused imports or variables
- Functions under 50 lines, files under 800 lines

### FastAPI Patterns
- Auth guard (`Depends(_auth_guard)`) on all non-health endpoints
- Pydantic models for complex request/response schemas
- Proper HTTP status codes (400 for bad input, 401 for auth, 413 for size limits, 503 for unavailable services)

### Tests
- New functionality has corresponding tests
- Edge cases covered (empty input, oversized input, invalid format)

## Output

Provide a structured review with:
- **Issues** (must fix before merge)
- **Suggestions** (nice to have)
- **Approved** or **Changes Requested**
