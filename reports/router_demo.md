# 路由规则自检（构造状态，未调用模型）

- 配置版本：`frozen_v1`，配置哈希：`710008a8dd826ff434da38f0a32f6686aa2573818bb98f59d416c09755e4e0f0`
- 演示阈值：u_loc > 0.50、u_dup > 0.50（正式阈值须在开发集上定稿）

| 构造状态 | 观测信号 | 路由 | 生效规则 |
| --- | --- | --- | --- |
| public candidate already passes | prefix: public validation passed | `stop` | `early_stop_public_pass` |
| environment failure survived one recovery | failure: env_setup, 1 recovery attempt | `stop` | `stop_env_failure` |
| budget too small for another step | budget: 500 tokens left, floor is 2048 | `stop` | `stop_budget_insufficient` |
| localisation passes disagree | u_loc = 1.000 over 2 passes | `interactive` | `interactive_on_wide_localization_disagreement` |
| candidates repeat themselves | u_dup = 0.600 over 5 candidates | `interactive` | `interactive_on_high_duplicate_rate` |
| stack points outside the inspected context | frames: pkg/parse.py, pkg/normalise.py (unread) | `interactive` | `interactive_on_out_of_scope_stack_evidence` |
| nothing runnable to check behaviour with | signal: none, checks_run = 0 | `interactive` | `interactive_when_no_behavioural_signal` |
| no interactive trigger fires | narrow localisation, distinct candidates, signal present | `fixed` | `fixed_continuation_otherwise` |

## 同一前缀状态下的各组对比

| 组别 | 路由 | 原因 |
| --- | --- | --- |
| A fixed workflow | `fixed` | `fixed_continuation_otherwise` |
| C simple cascade | `interactive` | `cascade_all_eligible_failures` |
| D adaptive (this rule set) | `fixed` | `fixed_continuation_otherwise` |
| E random p=0.30 (seed 0) | `fixed` | `random_routing_stay` |

## 运行记录校验

由上述状态生成的运行记录：通过 schema 校验

