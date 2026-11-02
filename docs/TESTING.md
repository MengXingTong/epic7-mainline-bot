# Verification — 2026-11-02

## Current experimental PC changes

- Full local suite with private MuMu/PC fixtures: **90 passed**.
- Source-only suite, no private fixtures: **60 passed, 30 explicitly skipped** (90 discovered).
- 16:9 coordinate cases: 640×360, 960×540, 1024×576, 1280×720, 1600×900, 1920×1080, 2560×1440, 3840×2160.
- DPI matrix: 96, 120, 144, 168, 192; primary/secondary and negative screen origins. DPI is not applied a second time to physical client coordinates.
- Fake API regressions cover unfocused/covered windows, stale frames, resize/move/DPI/process changes, STOP, one-frame-one-input, button release on error, exact account preflight, profile locks and preserved failed attempts.
- Optional private PC screenshots validate cleared/uncleared map classification and client normalization. They are not included in Git.

## Important distinction

**Native GDI capture, SendInput, actual DPI hardware and full PC mission/CG/settlement have not completed live validation.** Tests use fakes or saved images; importing/running the unit suite never controls the game. PC input is disabled by default.

The local development verification did not enter or retry any PC mission. Historical attempts/completions/evidence were not cleared; a manual completion was reconciled only after the exact original stage was visibly green.

## Baseline

The original source migration had 48 full local tests (22 passed / 26 skipped without private fixtures) and passed GitHub Actions. See CHANGELOG for subsequent changes rather than treating baseline results as PC acceptance.
