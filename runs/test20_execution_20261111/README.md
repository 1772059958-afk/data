# 2026-11-11 dev 校准与冻结：执行记录

本目录记录本轮真实准备与执行。**用户最新要求立即保存现场，dev也留下次。完整dev23校准及配置冻结未完成，实验已停止。** 关闭/备份见 `shutdown_audit.json`，费用见 `final_cost_audit.json`，完整续跑说明见 [现场保存文档](../../docs/现场保存与续跑_20261111.md)。本轮不再启动任何实验。

## 授权与固定边界

- 本轮新增模型费用上限100 CNY，覆盖 dev 校准与原定 test20 五组一次；所有新增请求共用 `batch_ledger.json`，不复用或改写11月6日账本。
- 用户先要求冻结后停止，随后进一步要求dev也留下次、立即保存；以 `STOP_REQUESTED.json` 和 `SESSION_SAVED.json` 为当前边界。正式清单仍为固定20例、A/B/C/D/E、一次、seed20261111、repeat0，下次须明确续跑。
- 用户批准可变服务别名加逐请求后端指纹监测，见 `model_identity_amendment_approved.json`。官方当前映射DeepSeek-V4.1-Flash-1017；实际别名deepseek-flash，指纹 `bc19ba97cbe016479903222bb1578db6`。`immutable_version=false`，不声称固定了不可变快照。
- 主配置及离线准备原件不回写，实际运行另存配置/tag。不得把状态字符串改成frozen掩盖缺项。

## 已完成的实际工作

1. 新增跨进程账本已建，探测入口也接入该账本；记录真实fingerprint/provider_created，身份违例在记账后熔断共享client并停止批次，退出码非零。
2. 对应完整离线套件383/383通过；原始93/93、归档131/131通过。日志为 `offline_before_generation_01.*` 和 `preservation_before_live.*`。此通过数仅对应当时源码。
3. 真实身份探测1次成功。仅项目.env由受控入口读取；凭据未写入本目录或容器。
4. 三例公开screen环境准备完成：pydicom1256公开136+56通过；astroid1866公开56通过1跳过；pyvista4315数组子集7通过1跳过。实际image/base commit/clean与清理均核对。
5. 首轮三例真实负载在 `../dev_screen_baseline_20261111_01/` 完成，62个模型请求；加探测共63条账本记录，累计估算0.55175828 CNY、pending=null。不是实付账单。原矩阵/预测/快照/费用均保留。
6. 扩展公开基线复核发现PyVista三文件有3失败、243通过、8跳过；三失败是缺tqdm/meshio，在无补丁基线已存在。修正镜像e731651d…已完成，同命令在两次断网验证均246通过、8跳过；新映射为 `environment/screen_images_corrected_01.json`。修正环境的三例生成尚未开始，原首轮不能混入其成绩。
7. dev其余20例与test20的公开浅基线已缓存至D盘并核对真实HEAD/Git对象；候选依赖按公开版本与SHA保存。这些缓存不代表容器验收通过。
8. Docker官方UI数据迁移已完成，见 `migration/after_ui_relocation.json`：D盘新位置、9个镜像/标签及卷一致、无活动容器。两个VHDX停机备份均验SHA，原件未由本项目删除；迁移后评分控制器健康复核通过。

## 审计与材料入口

| 材料 | 路径 |
| --- | --- |
| 新100元授权与阶段停止点 | `authorization.json`、`stop_after_freeze_amendment.json` |
| 累计费用与未决请求 | `batch_ledger.json` |
| 模型版本限制、实际探测与批准 | `model_identity_review.md`、`model_probe_01/`、`model_identity_observation.json`、`model_identity_amendment_approved.json` |
| 实测源码快照 | `source_snapshot/manifest.json`与对应文件 |
| 资源检查预定义 | `resource_screen_protocol.json` |
| 首轮资源/费用/身份观察 | `resource_screen_baseline_01_review.json` |
| 公开环境与D缓存 | `environment/`下的validation、source_cache与prefetch_handoff |
| Docker备份和迁移 | `migration/`，备份实际位于D盘专用目录 |
| 独立评分控制器与dev评分流程 | `scoring_preflight/readiness_after_migration.json`、`scoring_preflight/dev_scoring_handoff.md` |

## 下次续跑的门槛（本轮不执行）

1. 使用已经验收的PyVista修正镜像；完整dev23准备脚本仍是草稿，manifest与nose-only新锁缺失，先完善并自检。
2. 完整dev23逐例公开环境验收；失败保留原因，不换例。
3. 在修正环境完成预注册三例资源与prefix比例检查，再固定执行设置做完整dev23同快照配对。
4. 冻结dev预测后独立官方判分，回放完整D规则，E概率取全部eligible前缀。缺前缀、缺标签、全部平局与信号不可达均明确披露，不用complete cases代替指定总体。
5. 审阅并保存真实冻结配置、完整哈希与局限；无法冻结的事项继续pending。
6. 核对账本pending、关闭本轮容器/下载桥/后台执行，维护交接文档。正式test20本会话不运行。

最终停止状态、费用与关闭证明以 `SESSION_SAVED.json`、`final_cost_audit.json` 和 `shutdown_audit.json` 为准。以上后续门槛均未执行，不能当作已完成证据。
