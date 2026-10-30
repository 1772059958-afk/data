# 面向仓库级程序修复的自适应混合架构

本项目研究在相同模型、初始信息和资源上限下，失败证据能否帮助选择固定延续或受限交互。本轮已完成开题对齐修复与离线验证；真实环境集成和新协议下的正式实验尚未进行。

当前用户授权仅限代码修复、归档、文档和离线验证。`configs/proposal_v1.json` 是待校准草案，`execution.live_authorized=false`。默认实验入口只生成计划，不启动 Docker 或调用模型。旧结果不能作为恢复后方法的主结果。

研究依据见 [开题正文摘录](docs/开题报告正文摘录.md)，当前约束见 [开题对齐协议](docs/实验协议_开题对齐.md)，后续实验 agent 先读 [AGENTS.md](AGENTS.md)。

2026-10-30 已完成边界修复和小范围 dev 离线准备，当前活动套件 291/291 通过，原始/归档资产完整。详见 [修复验收与 dev 准备](docs/修复验收与dev准备_20261030.md)；真实容器、付费生成和新协议官方判分仍未执行。

## 活动目录

| 目录 | 内容 |
| --- | --- |
| `src/swe_repair/` | 状态、路由、固定/交互执行、预算、模型客户端、校准与统计 |
| `scripts/` | 离线测试、计划/实验入口、分层抽样、判分与分析工具 |
| `tests/` | 假模型、假容器和纯逻辑回归测试；不要求模型密钥 |
| `configs/proposal_v1.json` | 待 dev 校准的开发配置，不能冒充已冻结协议 |
| `data/` | 原始和 harness parquet、dev/test 清单、历史金标准覆盖凭证 |
| `reports/` | 原有实验结果，仅作历史诊断，原文件不可覆盖 |
| `runs/` | 新计划与后续新实验独立输出；每个 tag 不可覆盖 |
| `docs/` | 当前协议、历史记录、修复分析与验证说明 |
| `dustbin/` | 退役实现/配置/协议/周报，禁止作为实验入口 |

原始 `data/` 和 `reports/` 的 93 个文件有修复前 SHA-256 保护清单。归档是保存失效实现和结论的来源，不是删除原始证据。

## 离线验证与计划

```powershell
# 无模型、无容器、无密钥；修改代码后须重新运行，不沿用历史通过数
python scripts/run_offline_tests.py

# 核对原始实验文件和退役归档
python scripts/verify_preservation.py --archive

# 默认只显示 dev 配对诊断计划，不执行
python scripts/run_cf.py --config configs/proposal_v1.json --mode diagnostic --split dev --calibration --tag dev_plan

# 从完整 test 清单预注册分层子集，生成新文件，不接触模型结果
python scripts/sample_instances.py --size 60 --seed 20261029 --out runs/plans/test60.json

# 免费 gold 环境扫描的离线计划，仍不启动容器
python scripts/scan_gold.py --split dev --tag gold_new --dry-run

# 小范围 dev 的离线准备：仅依据 ID 与仓库分布取 3 例，保留全部 23 例台账
python scripts/prepare_dev.py --size 3 --seed 20261030 --out runs/dev_preparation_20261030
```

60 只是命令示例，不是已选定的主实验样本量。样本规模须在正式结果揭晓前确定，并写入配置和计划清单。

本轮禁止运行付费实验。未来只有用户明确解除限制、确认范围和预算，并完成配置校准/冻结后，才可使用 `--execute --allow-paid`。配置授权与显式开关是技术门闩，不替代用户授权。不要通过构造客户端、旧脚本或修改 pending/null 值来绕过预检。

离线通过说明规则、隔离、预算等在假执行环境中通过回归；不代表真实服务兼容、容器测试环境或修复能力已通过验收。完整验证状态和未完成事项见 [离线验证记录](docs/离线验证_20261029.md)。

## 实验设计

A 是共享前缀后的固定延续，B 从零受限交互，C 在共享停止条件之后对所有可继续失败升级，D 根据失败证据选择，E 按 dev 冻结的 D 触发率随机选择。D 在证据不足但环境可运行时保守选择固定延续；局部应用或语法问题优先固定修正。不能为了让 D 和 C 不同而事后改规则。

正式模式只执行选中的延续；A/C/D/E 的同实例、同重复复用实际前缀快照，并分别完整计入前缀成本。诊断模式只对 eligible 前缀失败从独立克隆快照运行固定/交互两条分支。两分支起点和剩余预算相同，诊断总开销与策略成本分开。ESC 是诊断分支，不是 C 的别名。

每个候选从干净基线应用，保留此前有效候选，排除无法应用、语法错误及范围外补丁。生成侧只看白名单字段和 checkout 可发现的公开信息；官方补丁、隐藏测试与最终结果不进入生成。所有组使用同一候选选择规则。

全局预算约束累计 token、实际模型请求、`container_exec` 工具执行和墙钟时间；会话内还限制六种具名工具的调用次数。重试、失败请求和收尾计入预算，收尾额度预留在上限内。费用是按项目价格表估算值；缺失 usage 的中断请求保守预留并标记未知，不称为实付。

## 新数据分析

新驱动在 `runs/<tag>/` 保存生效配置、清单、完整前缀快照、阶段事件、矩阵和预测。已有 tag 拒绝覆盖。阶段事件用于审计，未承诺中断后的自动安全续跑；重启前先核对已发请求和费用。

官方判分与生成分开运行，模型和补丁冻结后才允许评测读取隐藏测试。各报告的输入哈希、run id 和标签必须与新预测匹配。后续可使用新分析器，例如：

```powershell
python scripts/analyse_cf.py --matrix runs/new_diagnostic/matrix.json --report FIXED=runs/new_diagnostic/fixed_verdict.json --report ESC=runs/new_diagnostic/esc_verdict.json --out runs/new_diagnostic/analysis.json --records-out runs/new_diagnostic/evaluated_records.jsonl
```

后续判分计划入口为 `python scripts/score_run.py runs/<tag>`，默认不执行。`bash scripts/score_all_arms.sh runs/<tag>` 是显式容器评测入口，从矩阵读取 split 和清单，在新的 `scoring/<arm>/` 写报告与 provenance sidecar；分析器核对预测、补丁和运行身份后才接收标签。它不调用模型，但需要 Docker 和官方 harness，当前未执行。

dev 配对分析含完整 `observations` 后，可离线生成待审阅的校准候选：

```powershell
python scripts/calibrate_router.py --observations runs/new_diagnostic/analysis.json --config configs/proposal_v1.json --out runs/new_diagnostic/calibration.json
```

校准脚本不自动冻结配置、不授权付费，也不接受旧矩阵充当新配对观察。正式多次重复分别分析生成 `evaluated_records.jsonl` 后，使用 `scripts/summarize_experiment.py --records <多个正式重复的记录文件> --instances <指定清单> --repeats 3 --left A --right D --out runs/new_summary/summary.json` 汇总；诊断模式记录、重复不完整或混合配置不能冒充正式主结果。

缺失报告不是未解决。主分析保留预先指定的总体，另报所有组可运行的共同子集。四象限只使用 eligible 且分支判分完整的实例，并显式列出缺失。至少三次正式重复后，按实例重采样、保留其全部重复，报告 95% 置信区间、逐仓库结果与宏平均。仍须完成信号/反馈/停滞消融、敏感性和人工语义审查。

## 历史证据与退役内容

旧 dev 金标准为 15/23，test 只覆盖 98/300；另外 202 个未覆盖，不能记为失败。98 个是历史便利覆盖，不自动成为新主实验总体。dev 可用于校准，test 抽样不得根据正式方法成绩选择。

旧 `cf_dev4`、v2.2、v2.3 来自不同实现，不能拼接或当作三次重复。旧单轮基线包含额外评测信息，不进入恢复后的公平比较。真实 C、D 相同决策时成本也应相同；旧文稿中使用无条件 ESC 成本代表 C 的比较已停用。详见 [历史报告说明](reports/README.md) 与 [退役归档说明](dustbin/README.md)。

`docs/实验记录.md` 的历史正文保留，后续只追加更正或新实验。修复前 README、旧协议、配置、脚本和交付物在 `dustbin/legacy_20261029/`，不要将其中命令复制回活动流程。

## 运行依赖

标准库离线套件不需要 requests、pyarrow、swebench 或 pytest。只有经授权的真实生成/容器评测才需要对应依赖、模型密钥和 WSL/Linux Docker 环境；依赖见 `requirements.txt`。正式运行前需记录实际 Python/依赖版本、模型服务端版本与镜像 digest，不能依赖下限版本约束或 latest 标签推定复现性。

密钥通过环境变量或未入库 `.env` 提供，不得写入日志、配置或提交。当前不需要读取或配置密钥。
