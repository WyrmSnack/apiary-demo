# EXPORT

Written by `tools/export.py`. This repository is built from the private `apiary-sdk` repository; it is not
a fork you can pull from, and it is regenerated rather than edited by hand.

- **Source commit:** `e704dc91b9b0a0284d327fe3282d0782eb610af7` (apiary 0.9.0)
- **Files copied unchanged from that commit:** 126; changed by the substitutions below: 5; written for this repository: 13
- **File-list digest:** `3d745dc9116d3302`
- **Scrub scan:** passed, 0 findings (home folders, the author's private folder names, e-mail addresses, GitHub, Anthropic and AWS tokens, private keys)

## What is copied

| From `apiary-sdk` | To |
|---|---|
| `apiary` | `apiary` |
| `tests` | `tests` |
| `conformance` | `conformance` |
| `spec/vectors` | `spec/vectors` |
| `spec/LICENSE` | `spec/LICENSE` |
| `ci/clean_install_check.py` | `ci/clean_install_check.py` |
| `ci/annotate_junit.py` | `ci/annotate_junit.py` |
| `pyproject.toml` | `pyproject.toml` |
| `requirements-dev.txt` | `requirements-dev.txt` |
| `LICENSE` | `LICENSE` |
| `LICENSING.md` | `LICENSING.md` |
| `CONTRIBUTING.md` | `CONTRIBUTING.md` |
| `.gitattributes` | `.gitattributes` |
| `MEASUREMENTS.md` | `measurements/MEASUREMENTS.md` |
| `docs/PHASE6.md` | `measurements/method/PHASE6.md` |
| `docs/PHASE7.md` | `measurements/method/PHASE7.md` |
| `docs/PHASE8.md` | `measurements/method/PHASE8.md` |
| `docs/PHASE9.md` | `measurements/method/PHASE9.md` |
| `bench/skirmish` | `bench/skirmish` |
| `bench/tally` | `bench/tally` |

## What is changed, and why

| File | Why |
|---|---|
| `tests/test_hook.py` | a fixture held the author's home folder |
| `tests/test_measure.py` | a fixture held the author's home folder |
| `tests/test_migrate.py` | a docstring named the author's folders |
| `conformance/README.md` | the full spec text is not in this repository |
| `CONTRIBUTING.md` | the authoring kit is not in this repository |

## What is left out, and why

| Left out | Why |
|---|---|
| `spec/SUBSTRATE_SPEC.md` (the full spec text) | decided 2026-10-19: the demo carries a summary (`spec/SUMMARY.md`); the vectors and the conformance suite are here in full |
| `bench/results/`, `evidence/` | run records and logs that hold private session paths; their numbers are in `measurements/MEASUREMENTS.md` and the write-ups |
| `tests/test_bench.py` | it reads `bench/results/` (16 tests); the other 673 unit tests are here |
| `authoring-kit/`, `docs/` other than the measurement plans, the realm, the textbook | not part of the demo |
