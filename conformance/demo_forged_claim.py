"""Shows, end to end, why spec L-10 exists: with the authoring kit's server, an agent that does not hold
a claim can close the task by forging a CLAIM line through append_ledger.

  python conformance/demo_forged_claim.py kit         # the forgery closes the task
  python conformance/demo_forged_claim.py reference   # refused
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import KNOWN          # noqa: E402
from harness import Colony, token_of  # noqa: E402

impl = KNOWN[sys.argv[1] if len(sys.argv) > 1 else "kit"]
with tempfile.TemporaryDirectory() as d:
    col = Colony(Path(d), impl)
    col.task("014-a.task")
    owner = token_of(col.call("claim_task", task_file="014-a.task"))
    print(f"[{impl.name}] owner claims 014-a.task, token={owner}")
    forged = "f" * 16
    for step, args in [("append_ledger", {"caste": "Forager", "signal": "CLAIM", "path": "tasks/active/014-a.task",
                                          "note": f"token={forged} lease_until=2099-01-01T00:00Z"}),
                       ("close_task", {"task_file": "014-a.task", "token": forged})]:
        print(f"[{impl.name}] intruder {step}: {col.call(step, **args).splitlines()[0]}")
    print(f"[{impl.name}] 014-a.task is now in {col.where('014-a.task')}/")
