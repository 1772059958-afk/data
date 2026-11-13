# test20 五组一次：离线准备

用户于 2026-11-11 将正式对照限定为 20 例、A/B/C/D/E、一次，共 100 策略单元。抽样/运行种子 20261111，repeat_index=0。抽样仅使用完整 test300 的 ID 与仓库分层，不使用 gold、模型成绩或镜像可用性；固定 20 例不可替换。

本目录保存准备与注册材料，所有单元尚未运行。配置仍 pending、live_authorized=false；真实费用上限尚待新确认。旧两例100元授权已收尾，不能沿用余额。6元/2元为继承的开发占位；budget_proposal.json 中的上界不授予执行权限。

- instances.json：20例、12仓库、种子、配额及总体/清单哈希。
- preregistration.json：单次描述性设计与主要D−C/D−E比较；不进行CI、显著性、非劣或随机稳定性推断。
- execution_matrix.json：100条未执行策略单元。
- full_dev_coverage.json：新校准的完整dev23台账，旧两例不冒充新设置下已跑记录。
- resource_screen_instances.json：仅按ID/仓库选出的3例负载检查清单。
- environment_inventory.json：20个指定test实例的镜像/基线身份待核验项。
- budget_proposal.json：尚未授权的费用决定项。
- plan_A.json至plan_E.json、dev_diagnostic_plan.json：实际入口生成的execute=false计划。
- artifact_manifest.json、offline_validation.json与validation/：准备文件身份及本次离线核验。

后续先完成dev资源与路由校准、模型身份与完整冻结，再新建真实run。A/C/D/E共享实际prefix、各组完整计入prefix成本，B独立起点；正式不额外运行配对备选分支。缺失判分、环境失败、未解决分开记录，主分母每组20，另报共同可运行子集。

计划与命令见 [下一阶段实验计划](../../docs/下一阶段实验计划_test20_20261111.md)，dev方法见 [dev校准方案](../../docs/dev校准执行方案_20261111.md)。不得把本目录、合成测试或dry-run当成实测成绩。
