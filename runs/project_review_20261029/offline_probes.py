"""Synthetic read-only source probes; NOT experiment/evaluation records.

No network, credentials, Docker, dataset patch or archived code is used.
Print observations about the current implementation without changing it.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import socket
import sys
from types import SimpleNamespace as NS
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def deny_network(*args, **kwargs):
    raise RuntimeError("network disabled by project review")


socket.socket.connect = deny_network
socket.socket.connect_ex = deny_network
socket.create_connection = deny_network
socket.getaddrinfo = deny_network

from swe_repair import experiment as ex
from swe_repair.budget import Budget, BudgetState
from swe_repair.calibration import select_switch_probability
from swe_repair.execution import ResourceLimit
from swe_repair.llm import ChatResult
from swe_repair.prefix import PrefixResult
from swe_repair.router import RouterConfig, route_for_arm
from swe_repair.state import ContextView, FailureRecord, Localization, RepairState, TaskManifest

spec = importlib.util.spec_from_file_location("review_analysis", ROOT / "scripts/analyse_cf.py")
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)

raw = json.loads((ROOT / "configs/proposal_v1.json").read_text(encoding="utf-8"))
cfg = RouterConfig.from_config(raw).with_thresholds(.5, .5)


def state(iid="synthetic__repo-1", frame=None):
    result = RepairState(TaskManifest(iid, "synthetic/repo", "base", cfg.config_version, cfg.digest))
    result.budget = BudgetState("synthetic", Budget(100000, 12, 80, 1200))
    result.localization = Localization.from_file_sets({"one": ["pkg/x.py"], "two": ["pkg/x.py"]})
    result.context = ContextView(read_files=frozenset({"pkg/x.py"}))
    if frame:
        result.failures.add(FailureRecord.from_output(
            "synthetic public test", 1, stage="test", repo_root="/testbed",
            stdout=f'Traceback (most recent call last):\n  File "{frame}", line 1, in f\nAssertionError: synthetic'))
    return result


def route_probe(frame):
    observed = state(frame=frame)
    decision = route_for_arm("D", observed, cfg)
    return {"input_frame": frame, "stored_frames": list(observed.failures.latest.repo_frames),
            "route": decision.route, "rule": decision.rule}


def missing_verdict_probe():
    first = state("synthetic__repo-1", "/testbed/pkg/new.py")
    second = state("synthetic__repo-2")
    m = {"mode": "diagnostic", "split": "dev", "designated_instances": [first.task.instance_id, second.task.instance_id], "cases": []}
    for s in (first, second):
        m["cases"].append({"instance_id": s.task.instance_id, "mode": "diagnostic", "paired_eligible": True,
                           "prefix_snapshot": s.to_dict(), "stages": {}, "decisions": {
                               "A": {"route": "fixed"}, "D": route_for_arm("D", s, cfg).to_dict()}})
    reports = {"A": {"unresolved_ids": [first.task.instance_id]}, "ESC": {"resolved_ids": [first.task.instance_id]}}
    result = analysis.analyze(m, reports)
    all_routes = [route_for_arm("D", s, cfg).route for s in (first, second)]
    observed_routes = [route_for_arm("D", RepairState.from_dict(o["prefix_snapshot"]), cfg).route
                       for o in result["observations"]]
    return {"eligible": result["paired_eligible"], "complete_pairs": result["paired_complete"],
            "all_eligible_trigger_rate": select_switch_probability(all_routes),
            "observations_only_trigger_rate": select_switch_probability(observed_routes)}


def foreign_report_probe():
    iid = "synthetic__repo-1"
    m = {"mode": "formal", "arm": "D", "split": "test", "config_hash": "CURRENT",
         "designated_instances": [iid], "cases": [{"instance_id": iid, "arm": "D", "mode": "formal",
             "stages": {}, "selected_route": "stop", "policy_cost_cny": 0}]}
    foreign = {"run_id": "UNRELATED_OLD_RUN", "config_hash": "OTHER_CONFIG",
               "predictions_sha256": "OTHER_PREDICTIONS", "resolved_ids": [iid]}
    result = analysis.analyze(m, {"D": foreign})
    return {"accepted": True, "foreign_run_id": foreign["run_id"], "status": result["records"][0]["status"],
            "resolved_rate": result["primary_summaries"]["D"]["resolved_rate"]}


class Box:
    def __init__(self, image, name):
        self.image, self.name, self.workdir = image, name, "/testbed"
    def start(self): pass
    def close(self): pass
    def revert(self): pass
    def head(self): return "base"
    def image_digest(self): return "sha256:synthetic"


class Client:
    config = NS(max_tokens=100, model="deepseek-flash")
    requests = 0
    def chat(self, messages, **kwargs):
        self.requests += 1
        record = NS(cost_cny=.01, prompt_tokens=10, output_tokens=10,
                    served_model="deepseek-flash", finish_reason="stop")
        return ChatResult(record, {"content": "no candidate"}, "no candidate", "", [])


def orchestration_probe(exhaust=False):
    def prefix(row, client, **kwargs):
        s = state()
        return PrefixResult(s, "base", (), (), context_text="synthetic")
    def exhausted(*args, **kwargs):
        raise ResourceLimit("synthetic resource exhaustion")
    row = {"instance_id": "synthetic__repo-1", "repo": "synthetic/repo", "base_commit": "base", "problem_statement": "synthetic"}
    client = Client()
    with patch.object(ex, "run_prefix", prefix):
        if exhaust:
            with patch.object(ex, "candidate_messages", exhausted):
                case = ex.run_case(row, client, raw, mode="formal", arm="A", calibration=True, box_factory=Box)
        else:
            case = ex.run_case(row, client, raw, mode="formal", arm="A", calibration=True, box_factory=Box)
    return {"requests": client.requests, "case_status": case["status"], "stage_status": case["stages"]["fixed"]["status"],
            "remaining_model_calls": case["stages"]["fixed"]["budget"]["remaining"]["model_call"]}


if __name__ == "__main__":
    result = {"kind": "synthetic_source_review_only", "external_frame": route_probe("/opt/venv/lib/python/site-packages/dependency/helper.py"),
              "suffix_test_frame": route_probe("/testbed/pkg/widget_test.py"), "foreign_report": foreign_report_probe(),
              "missing_verdict_trigger_rate": missing_verdict_probe(), "fixed_one_attempt": orchestration_probe(),
              "aggregate_budget_status": orchestration_probe(exhaust=True)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
