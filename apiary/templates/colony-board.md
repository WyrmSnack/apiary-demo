---
name: colony-board
description: Show a plan as the Colony Coordination Board before create_plan - one card per task coloured by who does it, the longest run of agent tasks before the human sees the work, create_plan's refusals, and a Mermaid flowchart - then revise it with the human. Use every time you are about to show the human a plan table, and when the human asks to see the board, the flow, the checkpoints, or the colony's state.
---

# The Colony Coordination Board

Follow `castes/queen.md` section 3. Every plan is shown to the human as a **table and a board** before `create_plan`.

## Before create_plan

1. Draft the plan exactly as you will pass it to `create_plan`: `tasks` (slug, objective, acceptance or gate_code,
   writes, depends_on, lane, and **`by`**) and `decisions`.
2. **Say who does each task** with `by`: `Queen`, `Forager`, `Nurse`, `Guardian` or `Human`. A `by: Human` task is a
   **checkpoint**: the human looks at the work there. It closes only after the human writes `approve <id>` in chat
   (the guard reads their words; an answer you offered in a question does not count), and its `DONE` line says
   `human approved`. Put one where the human should see the work before more is built on it.
3. Call **`plan_board`** with the same `tasks` and `decisions`, a `limit` (default 3: the most agent tasks in a row
   before a human one) and a `name` for the goal (lowercase words joined by `-`). It writes nothing in `tasks/`, the
   ledger or TRACES; with a name it writes `boards/<name>.board.json`, `.mmd` and `.html`, and adds a line to
   `boards/<name>.revisions.jsonl` (how many times the plan was revised before the human's yes).
4. Read what it returns:
   - `REFUSED: ...` or `CONFLICT: ...`: what `create_plan` would refuse. Fix it before showing the plan.
   - `RUN <n> > <limit>`: that many agent tasks run in a chain with no human checkpoint. Add a `by: Human` task in
     the chain, or tell the human why the run is safe and ask whether to raise the limit.
   - `NO-HUMAN`: no checkpoint at all. The human sees nothing until the plan ends.
   - `VERIFY-BY <slug>`: a task in a verify lane must be `by: Guardian`, a different caste from the work it checks.
   - The Mermaid flowchart after them: paste it under the table, in a ```` ```mermaid ```` block.
5. **Show the human the table and the board** (the Mermaid block, and the path to `boards/<name>.html`). Wait for a
   yes. If they change the plan, call `plan_board` again with the same name, then show it again.
6. Then `create_plan` with exactly the plan the board showed.

The human may edit the HTML board (add a checkpoint, rewire a dependency, change who does a card) and press
**Export plan.json**. That file is a plan, not a change to the colony: read it, pass it to `plan_board` again, show
the result, and create it only after their yes.

## From the command line

- `apiary board --plan plan.json [--name <name>] [--limit 3]`: the same board from a plan file (create_plan's shape,
  or a bare list of tasks). Exit 1 if create_plan would refuse it.
- `apiary board --live`: the colony as it stands, in `boards/live.*`: done, active, ready and blocked tasks, with each
  task's `WARN` and `ESCALATE` count. Show it when you report (section 5).
- `--note <vault folder>`: also write `<folder>/<name>.md`, a Markdown note with the findings and a mermaid block, for
  an Obsidian vault. `--vault <name>` names the vault (default: the colony folder's name): a card whose text holds
  `[[Some Note]]` links to `obsidian://open?vault=<vault>&file=Some Note` in the HTML and in Mermaid `click` lines.

## Rules

- `plan_board` and `apiary board` never create, claim or close a task. Only `create_plan` creates the plan.
- Never close a `by: Human` task without the human's `approve <id>`; never write those words for them.
- Write into an Obsidian vault only through folders the human listed in `.apiary/mcp-guard.json`; the guard refuses
  every other Obsidian MCP write, and that file is the human's.
