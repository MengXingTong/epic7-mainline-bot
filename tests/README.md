# Offline test suites

- `test_safety.py`: resource veto, paid revival, no-repeat entry, verification chain and recognized UI regressions.
- `test_launcher.py`: environment selection, foreground package check, safe manual resume, Unicode paths and aspect-ratio validation.

No test sends game input. Launcher tests use temporary directories and mocks; safety tests replace logging/input/persistence with in-memory fakes.

Real game screenshots and OCR fixtures are deliberately excluded. Set `EPIC7_PRIVATE_FIXTURES` to a local directory to run those additional cases. Without it the fixture-dependent cases are explicitly skipped, not reported as passed.

## Experimental PC tests

- `test_pc_backend.py`: mock transport guards, window/DPI/multi-monitor geometry matrix, profile/account checks, initialization failures and non-destructive manual reconciliation. Native Windows API declarations are inspected using mocked DLLs; no native capture or input is executed.
- `test_pc_fixtures.py`: optional saved PC map images, enabled only with `EPIC7_PC_FIXTURES` pointing at a private local directory. These are classifier regressions, not native input acceptance.

A passed geometry matrix does not mean every monitor, GPU, DPI mode or game UI has been tested live. PC input remains opt-in and experimental.

- `test_pc_quickstart.py`: automatic account field discovery, bounded startup navigation, no daily configuration prompts, legacy history reuse, safe first-use initialization, account mismatch/active guards, read-only behavior and STOP restoration; all native APIs are faked.

## Legacy story and Saint 3-7

`test_story.py` covers exact preparation-stage reads, three/five-wave CLEAR, blue exits before/after settlement, native region routes, map panning, task switching and success-only repetition. Its synthetic policy cases run without private screenshots and never call native input. Saved-image regressions use `EPIC7_STORY_FIXTURES` (local `.local/story-validation` by default); absent private fixtures are explicitly skipped. `test_pc_backend.py` also checks drag cancellation, geometry changes, frame consumption and paired release using fakes.
