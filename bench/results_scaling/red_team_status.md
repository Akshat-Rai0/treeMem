# Red-Team Privacy Test Status (WP4)

## Test File
`tests/test_red_team_privacy.py`

## Test Execution
Run: `python3 -m pytest tests/test_red_team_privacy.py -v`

## Results
**All 12 tests PASSED** (execution time: 2.13s)

## Test Coverage
The red-team test covers 26 attack scenarios across 11 MCP tools:

1. **Recall attacks** (5 scenarios)
   - Direct recall of private node
   - Recall with private keyword query
   - Recall with follow=true into private
   - Recall with reveal=true (denied without env var)
   - Recall parent to check teaser leaks

2. **Expand attacks** (3 scenarios)
   - Direct expand of private node
   - Expand with reveal=true
   - Expand parent to access private children

3. **Search attacks** (4 scenarios)
   - Search for private keywords
   - Search for SSN pattern
   - Search for API key pattern
   - Search with reveal=true

4. **Compress attacks** (2 scenarios)
   - Compress private node (check prompt leakage)
   - Compress with reveal=true

5. **Commit summary leak attacks** (3 scenarios)
   - Malicious summary with private details
   - Indirect term leakage attempts
   - Leak private facts into public parent

6. **Remember/search before place** (2 scenarios)
   - Search unplaced private facts
   - Place then search without reveal

7. **Transclusion attacks** (1 scenario)
   - Embed private fact in public summary

8. **Split attacks** (1 scenario)
   - Split nodes to expose private children

9. **Guided recall attacks** (2 scenarios)
   - Guided recall with private query
   - Guided recall for SSN

10. **Inheritance attacks** (2 scenarios)
    - Recall normal node under private parent
    - Expand normal node under private parent

11. **Rebuild attacks** (1 scenario)
    - Rebuild from journal preserves privacy

## Summary
- **Total attack attempts**: 26
- **Successful leaks**: 0
- **Privacy leak rate**: 0%

## Positive Control
The test includes private facts (bank routing number, SSN, API key) that are explicitly marked as `sensitivity="private"` and stored under a private parent node. All tests verify that these secrets are not leaked through any MCP tool surface.

## Content Leaks
None detected. All private content is properly masked across all attack vectors.
