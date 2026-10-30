"""Which rule decided D on each instance, and which rules were also true."""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
TAG = "cf_dev7_v23"

with open(os.path.join(REPO, "reports", f"{TAG}_matrix.json"), encoding="utf-8") as fh:
    matrix = json.load(fh)

SHORT = {
    "freeze_when_public_candidate_passes": "①冻结",
    "stop_on_env_failure_after_one_recovery": "②环境",
    "stop_when_budget_insufficient": "③预算",
    "interactive_on_wide_localization_disagreement": "④u_loc",
    "interactive_on_high_duplicate_rate": "⑤u_dup",
    "interactive_on_out_of_scope_stack_evidence": "⑥越界栈",
    "interactive_when_no_behavioural_signal": "⑦无信号",
    "fixed_continuation_otherwise": "⑧固定",
}

for item in matrix["instances"]:
    iid = item["instance_id"].split("__")[-1]
    rules = item.get("router_rules") or []
    firing = [SHORT.get(r["rule"], r["rule"]) for r in rules if r.get("fires")]
    first = firing[0] if firing else "(none)"
    decided = matrix["decisions"].get(item["instance_id"], {})
    feats = item["features"]
    print(f"{iid:20s} u_loc={str(feats.get('u_loc'))[:5]:5s} "
          f"pass={feats.get('n_public_pass')} signal={feats.get('behavioural_signal'):15s} "
          f"决定={first:8s} 全部成立={firing} D={decided.get('D')}")
