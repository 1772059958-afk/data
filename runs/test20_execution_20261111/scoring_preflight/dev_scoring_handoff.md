# dev 诊断判分与冻结交接（2026-11-11）

当前范围按根代理转述的用户新指令：完成 dev 校准并保存冻结审阅后，本轮停止；正式 test20 下轮再执行。本文件没有触发判分或生成。

## 每个诊断 tag 需要哪些独立报告

1. **路由阈值拟合的最小标签为 FIXED 与 ESC。** 它们必须来自该 tag 的 eligible 固定/交互两分支，完全相同前缀快照及剩余预算，各自冻结补丁后独立官方判分。不能从旧环境、旧配置、先前单例或其他 tag 拼接标签。
2. **A 报告用于共享停止案例和固定策略总体的检查。** 对公开通过而共享停止的实例，分析器可从 A 判分取得 prefix 最终标签；仅有 FIXED/ESC 的 eligible 报告不能说明这些非 eligible 案例是否真正解决。
3. **B 报告用于独立交互基线的完整诊断。** 现有 diagnostic 同时实际生成 B，计划要求区分其能力、额度和环境问题；需要报告 B 最终质量时必须独立判分，不能用 fixed/ESC 标签代替。B 的生成/研究费用始终记账，不因阈值数学没有用到它而隐去。
4. **C/D 报告不是阈值拟合的必要输入。** 诊断中的实际路由仍可审计，不能把无条件 ESC 成本当成真实 C。E 概率 pending 时没有 E 预测/判分是预期状态，不能强填随机结果。

注意，`score_run.py` 当前会枚举 tag 根目录的**所有** `predictions_*.jsonl` 并逐一启动官方 harness，没有 `--arms` 筛选开关。为保持原始生成产物和身份，不应移动、删除、重写预测文件来压缩评分任务。沿用现入口则会为所有已生成的实际 arm/branch 输出独立评分（典型为 A/B/C/D/FIXED/ESC）。上面的“最小”是分析依赖说明，不是承诺现入口只启动两个任务，也不授予绕过 provenance 的权限。

## 实际衔接

1. 完成整个新 tag 的指定实例，确认 matrix 不含 running case；冻结 matrix 与预测文件。
2. 默认计划审阅：

```powershell
.venv/Scripts/python.exe scripts/score_run.py runs/<new_dev_tag> --controller-image swe-repair/scoring-controller:20261106-cli --max-workers 1
```

确认 source parquet、配置中的准备镜像 ID、base commit 与运行身份一致，再使用相同命令加授权执行开关。`scoring/`和`controller/`必须尚不存在，不能覆盖旧评分。

3. 官方输出路径是 `runs/<tag>/scoring/<ARM>/<tag>-<ARM>.<tag>.json`，同目录 `.json.provenance.json` 由包装器生成。包装器将控制器实际ID固定为 `sha256:1f43c83b3d3c631d37af54a19828df269accd045a22c62c0aab5b2bfa713726f`（实际执行前再inspect），只回传路径/状态，不向生成上下文展开隐藏 console/log。
4. 使用 `analyse_cf.py --matrix runs/<tag>/matrix.json`，对本次已有的每个报告显式追加 `--report ARM=PATH`，输出新的 `analysis.json`与`evaluated_records.jsonl`。必须保留同tag的 sidecar，不能裸读旧 verdict JSON 充当独立标签。
5. 使用 `calibrate_router.py --observations runs/<tag>/analysis.json --config <该tag实际生成配置> --out <新候选路径>`。配置除 provenance 元数据外必须与生成前缀的完整执行设置一致；镜像、模型/采样、预算或交互设置改变就不能混入旧标签。

## 冻结前检查

- `designated_instances`保留完整 dev23；环境失败、缺失前缀、缺失判分分别记录，不用 complete cases 取代总体。
- `eligible_population_complete=true`，全部指定前缀可审计。若存在 `prefix_unavailable_instance_ids`，现校准器会拒绝估 E，不能仅删除缺项后重称完整。
- `observations`仅含双分支有有效行为标签的 eligible 配对；其他缺判分和基础设施错误保留为缺失，不算两分支都失败。
- 选阈值后对全部 `eligible_prefixes`回放完整九规则得到 E 概率；不使用交互胜率。若没有 eligible，不能自动填0、1或沿用旧两例的1.0。
- 全平局/样本不足/重复规则不可达的告警保留，不把网格平局或`stable=true`说成已证明路由有效。
- 校准候选自身仍为 pending/live=false；根代理需基于真实 dev 证据保存完整执行参数、模型身份限制、提示/源码/配置与镜像哈希的冻结审阅，不能只改状态。
- 新范围下本轮完成后不启动 test20，不因还有100元余额而扩大实例、重复或付费任务。

迁移后控制器的真实断网健康证据另见 `readiness_after_migration.json`。本文未读取隐藏测试内容、旧评测日志、凭据或基准补丁。
