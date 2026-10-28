"""Per-instance quadrant detail for the analysis page, v2.2 vs v2.3."""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def show(tag: str) -> None:
    path = os.path.join(REPO, "reports", f"{tag}_analysis.json")
    if not os.path.exists(path):
        print(f"{tag}: missing")
        return
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    print(f"=== {tag}")
    print("counts:", json.dumps(data["quadrants"]["counts"], ensure_ascii=False))
    print("needed:", data["quadrants"]["escalation_necessary_share"])
    short = {"Q1_double_success": "①双成功", "Q2_fixed_only": "②仅固定",
             "Q3_interactive_only": "③仅交互", "Q4_double_failure": "④双失败"}
    for row in data["per_instance"]:
        iid = row["instance_id"].split("__")[-1]
        print(f"  {iid:20s} fixed={str(row['fixed_resolved']):5s} "
              f"inter={str(row['interactive_resolved']):5s} "
              f"{short.get(row['quadrant'], row['quadrant'])}")
    print()


show("cf_dev7_v22")
show("cf_dev7_v23")
