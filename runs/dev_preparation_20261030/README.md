# 小范围 dev 集成准备（未执行）

从完整 dev 23 按种子 20261030、仅依据实例 ID 与仓库分布选择 3 个实例。未读取旧方法成绩或 gold 通过名单，不是主实验子集或校准结论。

先验收 `pvlib__pvlib-python-1707`，通过接口、工具调用、完整补丁、公开测试和预算审计后再扩至其余实例。全部 23 个 dev 的未运行/环境状态保存在 full_dev_coverage.json。

当前仅有离线计划，配置仍 pending、live_authorized=false；没有读取密钥、启动容器、拉镜像或调用模型。本目录是准备材料，实际运行必须写另一个新 tag，不能把计划目录当作已运行矩阵。

first_instance_plan.json / remaining_plan.json / diagnostic_plan.json / gold_plan.json 均为 execute=false。分阶段时使用 first_instance 与 remaining，避免再跑 diagnostic 整批而重复生成。preparation.json 列出真实运行前的验收门槛、依赖可发现性和金额上限；可发现路径不表示服务可用。双分支诊断上界可能超过批次守卫，守卫不能自动提高。

真实运行仍需新的明确授权及已固定的服务端模型版本；不要通过改 pending 或授权布尔值绕过。小范围集成不能替代完整 dev 校准、正式三次重复、独立判分或消融。
