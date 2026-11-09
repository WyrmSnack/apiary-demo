---
name: colony-plan
description: Plan a goal bigger than one task as lanes, show the plan to the human, create it in one create_plan call, then do the tasks solo (claim, work, close) or, when it pays, dispatch Forager subagents in parallel, wave by wave. Use whenever the human asks for something with several parts, or says plan, split, organise, or parallel.
---

# Planning a goal as lanes

Follow `castes/queen.md`. This skill is the working checklist.

## Draft the plan

Fill in this table and show it to the human before creating anything:

| Lane | Task (slug) | Check (acceptance or gate) | writes | Waits for | Why parallel / sequential |
|---|---|---|---|---|---|
| research | logo-research (Nurse) | `python -m apiary.gates.research research/logo-design` | research/logo-design/ | - | knowledge every lane needs; goes first |
| research | logo-research-verify (Guardian) | same, plus `--verified` | research/logo-design/ | logo-research | a different agent checks the sources |
| research | logo-knowledge (Nurse) | `python -m apiary.gates.knowledge knowledge --cards "Tools/Blender.md" "Concepts/Logo Legibility.md"` | knowledge/Tools/Blender.md, knowledge/Concepts/Logo Legibility.md | logo-research-verify | keeps what was learned, from verified cards only |
| decisions | (TRACEs, not tasks) | | | | shared choices every lane needs, citing research cards |
| geometry | rea-logo-geometry | gate: geometry.glb exists, 2 objects | art/logo/parts/geometry.py, art/logo/preview/geometry.glb | - | independent of look |
| look | rea-logo-look | gate: look.png rendered | art/logo/parts/look.py, art/logo/preview/look.png | - | independent of geometry |
| final | rea-3d-logo | gate: logo.glb and logo.png exist | art/logo/final/ | geometry, look | combines both |

Rules the table must pass:
- Every task has one check and its own `writes`. No two tasks that can run at once share a path.
- Every shared decision is a TRACE written before the lanes start.
- A chain where each step needs the last step's result stays one lane, in order. Say so in the last column.
- A goal that answers a realm decree ends with the task `decree-<id>`, which depends on the rest and checks the
  decree's objective as a whole (`castes/queen.md` section 7).
- Two to five lanes is usual. One lane means the work is a chain: say so, and do not force parallelism.
- Below the table, say who does the work: **solo**, or which tasks you will dispatch and why (`castes/queen.md` section 4).

## Create, in one call

One `create_plan` call with `caste: Queen`:

```json
{"caste": "Queen",
 "decisions": [{"key": "logo-palette", "value": "gold #C9A227 on charcoal #222"},
               {"key": "plan-rea-logo", "value": "lanes geometry, look, final; final combines both"}],
 "tasks": [{"slug": "rea-3d-logo", "objective": "...", "acceptance": "python gates/...", "writes": "art/logo/final/",
            "lane": "final", "depends_on": ["rea-logo-geometry", "rea-logo-look"]},
           {"slug": "rea-logo-geometry", "objective": "...", "acceptance": "...", "writes": "art/logo/parts/geometry.py",
            "lane": "geometry"},
           {"slug": "rea-logo-look", "objective": "...", "gate_code": "import sys ...", "writes": "art/logo/parts/look.py",
            "lane": "look"}]}
```

`depends_on` names slugs from the same plan (or ids of tasks that already exist). Order does not matter: the colony
numbers the tasks so each comes after what it waits for. A refusal writes nothing; fix what it names and call again.
`REFUSED ... writes overlap` means two tasks that can run at once would write the same file: narrow the `writes`, or
make one wait for the other.

## Do the work: solo unless dispatching pays

**Solo (the default, `castes/queen.md` section 4):** make fewer, larger tasks (two to four for a project you build
alone). Call `plan_status`, take a ready task, `claim_task` with `caste: Queen` (the result after its first line is
the task), do it inside its `writes`, `close_task`. Repeat in dependency order until nothing is ready or blocked. Put
independent tool calls in one message.

**Dispatch** only for a verify task (always a fresh agent), work too big for your context, or a wave of two or more
big independent tasks. Run `resume` yourself first. Then start an agent for **every** such ready task **in one
message** (parallel), with the Agent tool:

- a build task: **`subagent_type: forager`**, prompt "Task: `<task file>`.";
- a research or knowledge task: **`subagent_type: nurse`**, prompt "Task: `<task file>`. Research <question>.";
- a verify task: a fresh **`subagent_type: guardian`**, prompt "Task: `<task file>`. Verify research/<topic>/.".

`<task file>` is the file name only, such as `001-core.task` (no folder): `claim_task` takes the name, not a path.

The nurse and guardian agents read `castes/nurse.md` first, for the card format and the legal rules. These agents are
defined in `.claude/agents/` with their own short protocol and only the tools they need; add to the
prompt only what they must know that the task file does not say. Never dispatch a general-purpose agent for a task: it
starts with 55k to 60k tokens of context (Measured, Phase 8).

When a wave reports back, call `plan_status` again. Stop when nothing is ready or blocked. Then report lanes, results,
WARNs and ESCALATEs to the human.
