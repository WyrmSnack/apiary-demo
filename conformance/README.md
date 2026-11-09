# Conformance suite for the Colony Substrate Specification v0.9.0

The suite checks an implementation of the Colony Substrate Specification (summary: `spec/SUMMARY.md`) from the outside. It starts the
implementation as an MCP stdio server, calls its tools against a temporary colony, and inspects the files
it leaves on disk. It imports nothing from the reference implementation, so an implementation in any
language can be tested.

## Run it

```bash
python -m pip install -r requirements-dev.txt
python conformance/run.py reference                    # the reference implementation in apiary/
python conformance/run.py naive --expect-fail          # the textbook as written: must not conform
python conformance/run.py "node my-colony-server.js"   # yours: any command that starts an MCP stdio server
```

`run.py` writes a per-requirement table to `evidence/conformance-<name>-<platform>.md`. For plain pytest
output: `python -m pytest conformance --impl "<command>"`.

## What your implementation must support

- The six tools in spec section 10, with those parameter names.
- `COLONY_ROOT` (M-3) and the `APIARY_CLOCK` test hook (H-1). Without the hook, the lease tests cannot run.
- A `python` acceptance program that is Python 3.11 or later (A-3). The suite writes `probe.py` into each
  colony and uses `python probe.py ...` as the acceptance command, to see the exact argv your
  implementation passes.

## How tests map to the spec

A test's name starts with the requirements it checks: `test_P10_A2_invalid_acceptance_...` checks P-10 and
A-2. The acceptance tests take their cases from `spec/vectors/acceptance.json`, so a change to that
grammar is a change to data, not to test code. The other vector files are for unit-testing your parser
directly; the reference implementation's tests (`tests/test_grammar_vectors.py`) show how.

## Platform-dependent checks

`test_P7_...` and `test_P13_..._open_elsewhere` assert CONFLICT on Windows and success on POSIX, because
POSIX can rename a file another process holds open and Windows cannot. Run the suite on both.
