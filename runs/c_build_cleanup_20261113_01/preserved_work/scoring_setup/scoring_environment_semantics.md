# Official scoring and environment classification

SWE-bench 5.0.2 creates normal per-instance reports from parsed test results.
A test command exiting 1 is not itself a harness exception. Parsed pytest ERROR
results can therefore produce `unresolved_ids`, while `error_ids` remains empty.
Harness `error_ids` covers absent/invalid per-instance reports and evaluation
exceptions, including timeouts; it is not a count of pytest ERROR results.

The official report adds `infra_failure_ids` and `ambiguous_failure_ids` to
existing unresolved/error IDs. The original verdict remains present and the
denominator is unchanged. Relevant public wheel sources are
`swebench/harness/run_evaluation.py` (execution/grading), `grading.py`
(`get_logs_eval`, `get_eval_report`), `reporting.py` (`make_run_report`), and
`infra_failure.py` (ordered advisory signatures).

The current signatures include browser/display/memory/container/network faults,
missing modules, no tests collected, and timeouts. They do not classify a generic
pytest fixture/setup AttributeError. Thus an absent infrastructure flag is
unknown evidence about environment health, not positive health evidence.

Project fix: `cf.verdict_status` now checks mutually exclusive primary verdicts
first, then accepts an overlapping infrastructure annotation on unresolved/error.
It returns the independent environment category for analysis without modifying
the official report. Conflicting primary verdicts, two infrastructure categories,
and resolved/empty-patch plus an infrastructure annotation remain invalid.
Legacy reports containing only an infrastructure category remain supported.
The category stays in the primary population and keeps its cost. Related offline
analysis/scoring/statistics regression: 62/62 passed.

For this run, save the compatible prepared image ID, baseline commit, installed
pytest/fixture compatibility changes, public clean-baseline probe outcome and
probe log hashes before generation. Use that same immutable image in the frozen
generation config and evaluator-only dataset projection. Keep any environment
diagnosis alongside the unchanged official report, with its evidence and scope;
do not rewrite an official unresolved label based solely on an AttributeError.
If evaluation later exposes an unclassified initialization fault, record it as a
separate environment observation pending review rather than calling it confirmed
model failure. Hidden test logs remain exclusively in the evaluator directory.

The prior prefix summary has a new additive clarification under
`runs/dev2_acceptance_20261106/environment/scoring/frozen_prefix_acceptance_addendum.json`:
the official harness completed and returned unresolved; zero harness errors alone
does not establish environment health. Neither frozen inputs nor official output
were changed.
