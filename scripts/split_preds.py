"""Split a multi-model predictions file into one file per arm.

The harness takes a predictions file and processes the models it contains, but
it stops after the first one in practice, so each arm is scored separately with
its own file. Splitting is also clearer to read back: one file, one arm.

    /opt/swe-env/bin/python work/split_preds.py cf_dev4
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

tag = sys.argv[1] if len(sys.argv) > 1 else "cf_dev4"
src = os.path.join(REPO, "reports", f"{tag}.jsonl")
groups: dict[str, list[dict]] = {}
with open(src, encoding="utf-8") as fh:
    for line in fh:
        row = json.loads(line)
        groups.setdefault(row["model_name_or_path"], []).append(row)

for model, rows in groups.items():
    arm = model[len(tag) + 1:] if model.startswith(f"{tag}-") else model
    out = os.path.join(REPO, "reports", f"{tag}_{arm}.jsonl")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{arm:4s} -> {os.path.relpath(out, REPO)}  rows={len(rows)} "
          f"nonempty={sum(1 for r in rows if (r.get('model_patch') or '').strip())}")
