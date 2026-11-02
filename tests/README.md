# Offline test suites

- `test_safety.py`: resource veto, paid revival, no-repeat entry, verification chain and recognized UI regressions.
- `test_launcher.py`: environment selection, foreground package check, safe manual resume, Unicode paths and aspect-ratio validation.

No test sends game input. Launcher tests use temporary directories and mocks; safety tests replace logging/input/persistence with in-memory fakes.

Real game screenshots and OCR fixtures are deliberately excluded. Set `EPIC7_PRIVATE_FIXTURES` to a local directory to run those additional cases. Without it the fixture-dependent cases are explicitly skipped, not reported as passed.
