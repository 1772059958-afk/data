"""Write a SWE-bench predictions file from the frozen dev/test lists.

    python scripts/make_predictions.py --split dev --out runs/preds_stub.jsonl \
        --mode empty

The harness accepts one JSON object per line with exactly these keys. The
generation side produces this file; the harness only ever reads it, which is
what keeps the generation and evaluation stages separable.

Modes, in the order they are useful while wiring things up:

  empty   every instance gets an empty patch. Grading must come back
          "unresolved"; nothing should be silently counted as a success.
  gold    copies the reference patch out of the dataset. Grading must come
          back "resolved"; this is the positive control.
  stub    a syntactically valid but deliberately wrong patch, to confirm the
          harness runs the tests rather than trusting the patch text.

`gold` reads the dataset, so it is for plumbing checks only -- never for a
reported baseline number.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

STUB_PATCH = (
    "diff --git a/README.rst b/README.rst\n"
    "--- a/README.rst\n"
    "+++ b/README.rst\n"
    "@@ -1,1 +1,2 @@\n"
    " existing first line\n"
    "+stub patch inserted by make_predictions.py\n"
)


def read_instances(split: str) -> dict[str, str]:
    path = os.path.join(REPO, "data", "harness", f"{split}.parquet")
    table = pq.read_table(path, columns=["instance_id", "patch"]).to_pylist()
    return {row["instance_id"]: row["patch"] for row in table}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--split", choices=["dev", "test"], default="dev")
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", choices=["empty", "gold", "stub"], default="empty")
    ap.add_argument("--model-name", default="stub/no-model-call")
    ap.add_argument("--only", nargs="*", help="subset of instance ids")
    args = ap.parse_args()

    gold = read_instances(args.split) if args.mode == "gold" else {}

    listing = os.path.join(REPO, "data", "frozen", f"instances_{args.split}.txt")
    with open(listing, encoding="utf-8") as fh:
        ids = [line.strip() for line in fh if line.strip()]

    if args.only:
        wanted = set(args.only)
        missing = wanted - set(ids)
        if missing:
            print("not in this split:", sorted(missing), file=sys.stderr)
            return 2
        ids = [i for i in ids if i in wanted]

    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as fh:
        for instance_id in ids:
            if args.mode == "gold":
                patch = gold[instance_id]
            elif args.mode == "stub":
                patch = STUB_PATCH
            else:
                patch = ""
            fh.write(
                json.dumps(
                    {
                        "instance_id": instance_id,
                        "model_name_or_path": args.model_name,
                        "model_patch": patch,
                    }
                )
                + "\n"
            )

    print(f"wrote {len(ids)} predictions to {out_path} (mode={args.mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
