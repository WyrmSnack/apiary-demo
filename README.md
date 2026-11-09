# apiary-demo

Apiary lets Claude Code agents share work through plain files: an append-only ledger, a decision log, and a `tasks/`
folder. A task closes only when its own check passes, and a guard hook refuses any edit that bypasses the colony's
tools. This repository is the public demo edition: the working core, its tests, a conformance suite, a recorded
walkthrough, and write-ups of what I measured.

> **No outside users.** Apiary is my own self-directed project. Nobody outside it uses apiary, depends on it, or has
> run it in production. Every measurement here is me testing my own design on my own machine, and each write-up says so.
> If you try it, you are the first.

## The write-ups

Each one has a measured before and after, the method, the limits, and the commands to rerun what can be rerun here.

| Write-up | Before | After |
|---|---|---|
| [**I benchmarked my multi-agent framework, and it lost on cost**](writeups/01-it-lost-on-cost.md) | The textbook colony: **7.7x** a plain session's tokens on a small game (7.19M against 0.93M), same score | After the redesign: **0.90M** tokens, 87% fewer, about a plain session's cost. Still not cheaper than plain, and no better: the claim lost |
| [**The design I started from fails the spec I wrote for it**](writeups/02-the-textbook-design-fails-its-own-spec.md) | The textbook design, as written: **8 of 49** spec requirements | The reference implementation: **49 of 49** |
| [**The guard had a hole, and how I know the fix holds**](writeups/03-the-guard-had-a-hole.md) | Apiary 0.8.0: an MCP tool could write the ledger; the 71 new guard tests: **42 failed** | Apiary 0.9.0: refused; **101 of 101** pass; **30 of 30** planted bugs caught |

One more, from the benchmark runs ([`measurements/`](measurements/MEASUREMENTS.md)): before the guard required the
human's reply before creating tasks, **2 of 3** solo colony runs skipped asking for approval of the plan. After it
(apiary 0.6.1), **6 of 6** colony runs asked.

## See it work in two minutes

```bash
git clone https://github.com/WyrmSnack/apiary-demo
cd apiary-demo
python -m pip install -e .
python demo/walkthrough.py
```

The walkthrough makes a colony in a temporary folder and plays the agent's part with the same tools an agent gets: it
creates a task whose check fails, claims it, is refused at close, rewrites its own check and is refused again, is
stopped by the guard when it edits the ledger directly, then does the work and closes. Its output from one run is in
[`demo/walkthrough.txt`](demo/walkthrough.txt). No model is involved, so it costs nothing.

To use it with Claude Code on a repository of your own, see [`QUICKSTART.md`](QUICKSTART.md).

## What is here

| Path | What |
|---|---|
| `apiary/` | The core: grammar, protocol (claim, renew, close, resume with fencing tokens and leases), MCP server, CLI, the Claude Code guard hook, `apiary init` |
| `tests/` | 673 unit tests |
| `conformance/` | Tests any implementation from the outside, over MCP stdio and the files on disk. `naive_server.py` is the textbook design as written |
| `spec/` | A [summary of the specification](spec/SUMMARY.md) and its language-neutral test vectors |
| `demo/` | The walkthrough and a recorded run |
| `writeups/` | The three write-ups above |
| `measurements/` | Every benchmark run's numbers, and the pre-registered plans (hypotheses and decision rules committed before the first run) |
| `bench/` | The two benchmark specs and their hidden tests, so you can grade your own build |
| `EXPORT.md`, `tools/export.py` | How this repository is built from the private core: the commit, the file list, what is left out and why, the scrub scan |

## Run the checks

```bash
python -m pip install -r requirements-dev.txt
python -m pip install -e .
python -m pytest -q tests                          # unit tests
python conformance/run.py reference                # must conform
python conformance/run.py naive --expect-fail      # the textbook as written: must not
python ci/clean_install_check.py                   # install as a user would, then use it as Claude Code does
```

CI runs all of these on Linux and Windows on every push (`.github/workflows/ci.yml`).

## What this is not

- **Not used by anyone else**, as above.
- **Not the whole project.** The full specification text, connectors for game tools, the cross-project "realm", raw
  run records and the textbook stay in a private repository. `EXPORT.md` lists what was left out.
- **Not a security boundary.** The guard is a speed bump for agents that make mistakes. A shell script an agent writes
  and runs gets past it; see the limits in [write-up 03](writeups/03-the-guard-had-a-hole.md).
- **Not cheaper than one agent.** See [write-up 01](writeups/01-it-lost-on-cost.md).
- **Not open to contributions yet** (see `LICENSING.md`). Issues are welcome.

## License

Code: [GNU AGPL v3](LICENSE). Specification material (`spec/`): [CC BY-SA 4.0](spec/LICENSE); you may implement the
spec under any license. Plain-language summary: [`LICENSING.md`](LICENSING.md).
