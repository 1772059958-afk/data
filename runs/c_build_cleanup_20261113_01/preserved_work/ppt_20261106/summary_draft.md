# 两例五组实验摘要（数据汇总草稿）

本轮按照用户最后确定的规模，使用预先固定的 `pvlib__pvlib-python-1707` 和 `pydicom__pydicom-1139`，各执行 A–E 五组一次。累计模型费用守卫为 100 元，每个策略实例的守卫为 2 元。首轮双例诊断已完成，环境修复后的校准和五组结果仍待汇总。

## 源码与执行机制

待从最终变更和验收记录更新。已补充 dev-only `pilot` 的执行与评测身份：B 从原始问题独立交互，A/C/D/E 复用本次同配置的实际前缀缓存，每组仅执行实际选中的分支。独立判分保留 pilot 身份，正式汇总拒绝混入 pilot。

## 环境与接口

pvlib 的官方镜像初始 HEAD 与指定基线不一致，切回基线后又遇到 NumPy 2.0.2 移除 `np.Inf` 的兼容问题。独立派生镜像固定指定 commit 和 NumPy 1.26.4，断网容器完整执行公开 `test_pvsystem.py`，245 项全部通过。

pydicom 官方镜像下载未完成，本轮使用固定公开基线的独立源码派生镜像。首次完整公开测试发现 pytest 8.3.5 不再执行旧式 `setup`，产生 41 个初始化错误。修复镜像固定 pytest 7.4.4，并按指定公开源码中的 SHA256 预缓存一份公开 fixture，随后断网执行 `test_dataset.py` 120 项和 `test_valuerep.py` 38 项，全部通过。源码与测试保持干净，修复完成了可执行的公开验证链路。

已完成的项目 `.env` 模型探测返回 `OK`，服务端报告 `deepseek-flash`，输入37 token、输出12 token，一次请求。按 usage 和价格表估算费用0.00017元。先前旧系统 Key 探测保留0.00425元的未知usage预留。此前单例prefix验收为3次请求、40871 token、10次container exec、122.584秒，usage费用估算0.19823128元。这些历史集成请求与本轮五组策略成本分别列账。

## 离线验证

当前活动离线套件为347/347通过，包含评分辅助标签兼容修复。待最终源码状态确认后更新通过数，并补本轮保护检查。

## 配对诊断与候选校准

首轮双例诊断 `dev2_diagnostic_20261106_01` 已完整运行，新增生成费用估算0.64838336元。因随后发现pydicom公开验证的pytest兼容问题，该轮作为集成环境探测保留，费用进入累计台账。修复环境后的诊断与独立判分将提供候选校准数据。

修复环境后的 `dev2_diagnostic_20261106_02` 已产生独立配对结果。唯一eligible实例pvlib的固定、交互分支均resolved。临时阈值使用0.75/0.75，E按D在全部eligible前缀的触发率匹配为1/1=1.0。九种阈值组合都得到平局，当前数据不能判断哪个阈值更好。候选只用于本轮接口验收并保持待审阅状态。pydicom在前缀公开测试通过后共享停止，但独立判分为unresolved，可作为公开验证与最终解决不一致的真实案例；待最终pilot确认。

## 五组逐例结果

待填写2×5结果，保留实际路线、生成终止状态、冻结补丁、独立判分状态和resolved标签。未提交、未评测、基础设施故障与真实未解决分别记录。

## 质量与费用

待填写A–E各组解决数、完整策略成本和真实新增生成成本，并汇总模型请求、累计输入输出token、container exec与墙钟时间。完整策略成本包含继承的前缀，缓存命中不会记成零前缀成本。诊断双分支成本和之前接口探测单独登记。

## 失败实例

待从本轮真实候选与公开失败报告中选择一例，说明代码/环境/输出预算分别造成的现象、候选是否保留、路由如何选择以及独立判分结论。保留失败结果，不以新实例替换。

## 本轮结论的范围

本轮是两例dev、各组一次的pilot接口验收。同两例的独立配对结果用于临时策略候选，随后仍在这两例验收五组，因而只能给出逐例观察与本次质量成本点。主配置仍待完整dev校准与不可变模型版本冻结，正式总体的重复、聚类区间、消融和人工语义抽查仍是后续任务。费用采用usage估算或未知usage保守预留，尚未核对账单。

## 下一步

待结合实测失败决定优先修复，然后完成完整dev校准与冻结、独立正式总体重复、路由证据/反馈/停滞消融和语义审查。

## 现有来源

- `runs/dev2_acceptance_20261106/preregistration.json`
- `runs/dev2_acceptance_20261106/environment/pydicom/validation.json`
- `runs/dev2_acceptance_20261106/environment/pydicom/public_environment_repair_summary.json`
- `runs/dev2_acceptance_20261106/environment/pvlib/public_test_pvsystem_execution_v2.json`
- `runs/dev2_diagnostic_20261106_01/environment_rejection.json`
- `runs/dev2_acceptance_20261106/environment/pydicom/README.md`
- `runs/prefix_environment_20261106/validation.json`
- `runs/prefix_environment_20261106/cost_summary.json`
- `runs/prefix_dev1_20261106_01/integration_summary.json`
- `runs/model_probe_20261106_02/result.json`
- 最终诊断与pilot目录待补
