# 面向仓库级程序修复的自适应混合架构：工程骨架

这个目录放的是课题的可运行部分。目标是把开题稿里的实验协议变成能反复运行的命令，
每一步都留下可复核的记录。

## 仓库里有什么

| 目录 | 内容 | 是否入库 |
| --- | --- | --- |
| `src/swe_repair/` | 方法侧代码：状态机、路由器、预算、花费守卫、前缀执行器、受限交互执行器、反事实分析 | 是 |
| `scripts/` | 评测与实验脚本：数据冻结、harness 调用、反事实运行、判分、分析与出图 | 是 |
| `tests/` | 离线自检，共 170 项，不需要容器、模型或网络 | 是 |
| `configs/` | 冻结的实验配置 `frozen_v1.json` | 是 |
| `data/` | 冻结清单、实例列表、两份 parquet（约 4 MB） | 是 |
| `reports/` | **实验证据**：每次运行的预测文件、判分报告、反事实矩阵与分析 | 是 |
| `docs/` | 实验协议与实验记录 | 是 |
| `logs/` | 官方 harness 的容器日志（约 196 MB，摘要已进 `reports/`） | 否 |
| `vendor/` | WSL 与 Ubuntu 安装包（约 692 MB，与实验无关） | 否 |
| `work/` | 调试临时脚本 | 否 |

## 实验数据在哪、怎么读

`reports/` 是唯一的事实来源，`docs/实验记录.md` 里每条结论都指回具体文件。

| 文件 | 是什么 |
| --- | --- |
| `reports/cf_dev7_v23_matrix.json` | 7 实例 × 五组的反事实矩阵：每实例的前缀特征、两条分支的花费与结果、四组决策 |
| `reports/cf_dev7_v23_analysis.json` | 由上一份算出的四象限、策略得分、神谕缺口闭合率、每个特征的 AUC、规则触发分布 |
| `reports/cf_dev7_v23*.jsonl` | 交给官方 harness 的预测补丁（整包与按组拆分） |
| `reports/cf_dev7_v23-<组>.cf_dev7_v23.json` | 官方 harness 的判分报告（resolved / unresolved / empty_patch） |
| `reports/baseline_dev15_*` | 上一轮单轮固定流程基线（15 个实例） |
| `reports/gold.*.json` | 金标准扫描，用来确定哪些实例"标准答案自己都过不了" |

## 数据来源与冻结

数据集是 SWE-bench Lite。`data/frozen/manifest.json` 记了名称、修订号、每个分片的 sha256、
实例数量和清单哈希；清单一旦冻结，正式实验只允许用这份清单。

`data/raw/` 是下载后的原始副本（12 列），`data/harness/` 是给官方 harness 用的 schema v2 副本
（多 `image` 等列，缺了会 `KeyError`）。两份的实例 ID 逐一比对过，完全一致。

## 快速复现

```bash
# 0. 装宿主侧依赖（缺 requests 时，第 1 步会有 15 个客户端测试失败）
pip install -r requirements.txt

# 1. 离线自检（无容器、无网络、免费，期望 170/170 通过）
python scripts/run_offline_tests.py

# 2. 五组反事实（Ubuntu 侧，需要 Docker 与模型密钥）
/opt/swe-env/bin/python scripts/run_cf.py --interactive-calls 6 --interactive-tools 10 \
    --max-tokens 16384 --tag my_run --total-cny 7.5

# 3. 判分（免费，不调模型）
/opt/swe-env/bin/python scripts/split_preds.py my_run
bash scripts/score_all_arms.sh my_run

# 4. 反事实分析
/opt/swe-env/bin/python scripts/analyse_cf.py --tag my_run
```

模型密钥放在仓库根目录的 `.env`，写成 `DEEPSEEK_API_KEY=...`。该文件已在 `.gitignore` 中，
**不要提交**。

## 现在能做什么

| 任务 | 状态 | 命令 |
| --- | --- | --- |
| 冻结数据集 | 已完成 | `python scripts/freeze_dataset.py` |
| 日志 schema（任务4） | 已完成 | `python tests/test_runlog.py` |
| 状态记录器 | 已完成 | `python tests/test_state.py` |
| 路由器 | 已完成 | `python tests/test_router.py` |
| 阈值校准 | 已完成 | `python tests/test_calibration.py` |
| 路由自检演示 | 已完成 | `python scripts/router_demo.py` |
| 模型客户端与计费 | 已完成 | `python tests/test_llm.py` |
| 花费上限守卫 | 已完成 | `python tests/test_spend.py` |
| 环境自检（Windows） | 已完成 | `python scripts/check_env.py` |
| 装 WSL 与 Ubuntu | 已完成 | 见下文「评测环境」 |
| Docker 与 harness（Ubuntu 侧） | 已完成 | `bash scripts/check_env_wsl.sh` |
| 单实例评测链路（任务2） | **已完成** | `bash scripts/run_gold_smoke.sh` |
| 全 dev 集金标准扫描 | **已完成**（15/23，见下） | `bash scripts/run_gold_dev_split.sh` |
| 金标准可解子集（dev） | **已完成** | `python scripts/build_gold_subset.py --run-id gold_dev_full --split dev` |
| 全 test 集金标准扫描 | 运行中 | `bash scripts/run_gold_test_split.sh` |
| 扫描进度查看 | 已完成 | `python scripts/gold_progress.py --run-id gold_test_full` |
| 判分通路自检（任务3 前半） | **已完成** | `bash scripts/run_baseline_stub.sh` |
| 基线实现（单轮固定流程） | **已完成** | `/opt/swe-env/bin/python scripts/run_baseline.py --dry-run` |
| 基线试跑（任务3） | **已完成：铺满 15 个可用实例，原样 4/15、修后 6/15** | `bash scripts/run_baseline_dev15.sh` |
| 基线与成本汇总 | 已完成 | `python scripts/summarise_baseline.py --help` |

六个测试文件共 142 项检查，都不需要容器、模型或网络。

## 已冻结的数据集

`data/frozen/manifest.json` 记录了数据集名称、修订号、每个分片的 sha256、
实例数量和实例清单的哈希。清单一旦冻结，正式实验只允许用这份清单。

| 分片 | 实例数 | 仓库数 |
| --- | --- | --- |
| dev | 23 | 用于调试环境与校准阈值 |
| test | 300 | 主实验用 |

### 为什么有两份 parquet

`data/raw/*.parquet` 是从 `princeton-nlp/SWE-bench_Lite` 命名空间取下的**冻结凭证**，
12 列，只有题目正文，没有镜像信息。而当前版本的官方 harness（5.0.2）要求数据集里
带 `image`、`eval_script`、`log_parser`、`eval_type` 这几列，否则会在
`make_test_spec` 处抛 `KeyError: 'image'`。

所以另取了一份同名的 `SWE-bench/SWE-bench_Lite`（17 列，schema v2）放在
`data/harness/`，**只作为 harness 的输入**。两份的实例 ID 集合做过逐一比对，完全一致：
dev 23 个、test 300 个。凭证仍以 `data/frozen/manifest.json` 为准，
两份文件的 sha256、来源 URL、上游修订号记在 `data/harness/manifest.json`。

测试集的仓库分布并不均匀：django 114 个、sympy 77 个，两者合起来占了 191/300。
所以主结果必须同时报逐仓库的宏平均，否则结论会被这两个仓库主导。

需要注意的一处工程细节：HuggingFace 的官方 `resolve` 链接会跳转到
`cas-bridge.xethub.hf.co`，这个域名在本机网络上会触发证书拦截，无法下载。
脚本改为走 datasets-server 的 parquet 接口，它指向同一个 xet 对象，
但由可达的 CDN 提供。因此 manifest 里同时记录了“官方 resolve 指向的 xet 对象 id”
和“实际下载文件的 sha256”，用来证明两者是同一份内容。

## 金标准可解子集

**标准答案自己也过不了 8 个实例。** 这是本周最有价值的一条发现。

做法：把数据集自带的标准补丁（`--predictions_path gold`）当成选手提交，跑遍整个 dev 集。
标准补丁就是参考答案，按理 23/23 全过；实际只过了 15 个。把失败的 8 个拎出来
**单独串行重跑**，仍然 8 个全败——是环境层面的系统性问题，不是并发或机器抖动。

| 类别 | 数量 | 实例 | 原因 |
| --- | --- | --- | --- |
| `numpy_2_removed_alias` | 5 | pvlib 全部 5 个 | 镜像装的是 NumPy 2.x，仓库在该提交点仍在用 `np.Inf` 这类 2.0 已删掉的别名，代码连导入都进不去，任何补丁都过不了 |
| `test_fixture_missing_attribute` | 2 | pydicom 1139、1413 | 测试夹具自身漂移，测试去读一个没设置的属性，与补丁无关 |
| `build_dependency_fetch_failed` | 1 | pyvista 4315 | 测试阶段要现场联网拉构建依赖，超时，测试根本没跑起来 |

按仓库看保留情况：

| 仓库 | 保留 | 原有 | 说明 |
| --- | --- | --- | --- |
| pylint-dev | 5 | 5 | 全部可用 |
| sqlfluff | 5 | 5 | 全部可用 |
| pydicom | 3 | 5 | 2 个因夹具漂移剔除 |
| marshmallow-code | 2 | 2 | 全部可用 |
| pvlib | 0 | 5 | 整仓不可用 |
| pyvista | 0 | 1 | 整仓不可用 |

**pvlib 与 pyvista 整个仓库全军覆没**，所以任何关于这两个仓库的结论都不能从这份子集里下。

为什么必须剔除：留着这些实例会造成两重伤害。一是天花板被压住——每一组的解决率都不可能
超过 15/23，而这个上限不是方法造成的；二是偏差有方向——坏实例按仓库扎堆，而主结果要报
逐仓库宏平均，某个仓库整组归零会把均值拖到一个解释不清的位置。

```bash
# --dry-run 先看一遍，不写文件
python scripts/build_gold_subset.py --run-id gold_dev_full --split dev \
    --extra-run-id gold_dev_full_retry
```

产出 `data/frozen/instances_dev_gold_ok.txt`（15 个实例，带 sha256）与
`data/frozen/gold_subset_dev.json`（逐项剔除理由与报错原文，可审计而非只能被信任）。

### 开发集和测试集只共用一个仓库

dev 的 6 个仓库是 `marshmallow-code / pvlib / pydicom / pylint-dev / pyvista / sqlfluff`，
test 的 12 个仓库是 `django / sympy / matplotlib / scikit-learn / pytest-dev / sphinx-doc /
astropy / psf / pylint-dev / pydata / mwaskom / pallets`。**交集只有 `pylint-dev` 一个。**

所以 dev 上剔掉 8 个这件事，对 test 没有任何担保：test 必须自己扫一遍。顺带一层后果是，
在 dev 上校准出来的路由阈值不保证对 test 的另外 11 个仓库同样合适，这条限制要写进结论，
不能默认成立。

```bash
bash scripts/launch_gold_test_split.sh 8    # 后台跑，不占终端；可反复重跑续跑
python scripts/gold_progress.py --run-id gold_test_full --split test
```

这一步不调用模型、不产生费用，只占机时，同时把 12 个仓库的镜像提前拉到本地。
在它跑完之前，任何基于 test 的结论都还是悬着的。

### 先把镜像拉完，再跑评测

第一次 test 扫描栽在拉取上：47 个实例报 `connection aborted`、11 个报注册表 `500`，
而这些都发生在评测**过程中**。harness 会把「拉取失败」当成「该实例已跑完」，
于是这些实例一个结果都没有，而且不主动去数就发现不了。

所以把下载和评测拆成两步。拉取是整条链路里唯一走网络、也是唯一会随机抽风的一环，
让它单独带着重试去跑；评测跑起来时镜像已经全在本地，网络抖动最多浪费一次重试，
而不是变成一个静默缺失的结果。

```bash
bash scripts/launch_prepull.sh test 4       # 后台预拉，失败自动重试，可重复跑
bash scripts/run_gold_test_split.sh gold_test_full 8   # 镜像齐了再评测
```

`prepull_images.sh` 结束时会把没拉下来的镜像列出来并返回非零，重跑一遍即可只补那几个。

## 运行记录 schema

`src/swe_repair/runlog.py` 实现了开题稿附录 A.2 的 19 个必填字段，
外加一份 JSON Schema 和一个校验器。

```bash
python -m swe_repair.runlog --schema                  # 打印 JSON Schema
python -m swe_repair.runlog --validate runs/x.jsonl   # 校验日志
python -m swe_repair.runlog --digest runs/x.jsonl     # 日志指纹
```

几条刻意加进去的约束：

- 失败任务也必须写记录。只统计成功的运行会让成本分析失真。
- 选了分支就必须给出 `route_reason`，即哪条冻结规则生效了。
- `route=stop` 必须配一个停的终止原因：早停、环境失败、预算不足或出错，防止把“停”当成兜底。
- 评测标签由离线评测器写入独立文件，生成阶段的 `evaluation_status` 只能是状态占位。

## 配置冻结

`configs/frozen_v1.json` 抄录了开题稿里的全部实验参数，并标出了哪些还处于
`calibration: pending`（前缀预算比例、路由阈值、模型版本）。这些值必须在开发集上
定稿，之后连同配置哈希一起写进每条运行记录。

## 状态、路由与预算

这一层是开题稿第 3、4 节的方法本身，全部离线可跑，不依赖容器。

| 模块 | 对应开题稿 | 做什么 |
| --- | --- | --- |
| `src/swe_repair/state.py` | 表 3.1 | 六个状态项：任务清单、定位、补丁历史、失败记录、预算、决策轨迹 |
| `src/swe_repair/router.py` | 第 4.2 节 | 按冻结的规则顺序决定走固定延续、交互延续还是停 |
| `src/swe_repair/budget.py` | 第 3.2 节 | 四元资源向量的核算；调用前预检，越限如实记账 |
| `src/swe_repair/fingerprint.py` | 第 4.2 节 | 错误分型与错误指纹（路径、行号归一化） |
| `src/swe_repair/patchutil.py` | 第 4.4 节 | 补丁去重与候选选择用的差异统计 |
| `src/swe_repair/calibration.py` | 第 4.2、6.4 节 | 在开发集的配对结果上选阈值，并出敏感性报告 |

几条刻意加进去的约束：

- **阈值没定稿就不路由。** 配置里 `localization_disagreement_threshold` 与
  `duplicate_rate_threshold` 还是 `null` 时，D 组路由会直接抛错，而不是偷偷用一个
  默认值。正式实验前必须先在开发集上定稿，再连同配置哈希一起冻结。
- **停的规则对五组一视同仁。** A、C、D、E 共用“已有可行候选就冻结、环境失败、
  预算不足”这三条停止规则，各组只在“还能继续时往哪走”上不同。这样 C 与 D 的差别
  才干净地落在证据上。
- **生成侧状态装不进评测字段。** `state.assert_generation_only` 会递归检查，
  一旦状态里出现 `patch`、`test_patch`、`FAIL_TO_PASS` 之类的字段就直接报错，
  这是第 3.1 节承诺的字段白名单。
- **路由的退化会被点名。** `router.RoutingStats` 统计每条规则的触发次数；如果 D 组
  把绝大多数实例都送进交互分支，它就退化成 C 组了，统计里会直接给出这条警告。

```bash
python scripts/router_demo.py     # 8 个构造状态 → 决策表，写到 reports/router_demo.md
```

演示脚本用构造出来的失败状态覆盖每一条规则，并演示同一前缀状态下 A/C/D/E 四组
分别走到哪里；最后用其中一条状态生成一份运行记录，并当场用 schema 校验一遍。
演示阈值是显式传进去的（u_loc > 0.50、u_dup > 0.50），因为正式阈值还等着开发集定稿。

## 模型与费用

全流程只用一个模型，这是开题稿里写死的约束：换了模型就分不清收益来自架构还是
来自模型本身。

| 模块 | 做什么 |
| --- | --- |
| `src/swe_repair/llm.py` | 模型调用客户端；每次调用记录服务端返回的模型名、token 用量、耗时、估算费用 |
| `src/swe_repair/pricing.py` | 官方价目表与计费；按北京时间区分高峰/空闲档 |

选定的模型是 **`deepseek-flash`**（服务端版本 DeepSeek-V4.1-Flash）。理由：

- 支持 Tool Calls，受限交互那一侧的六个工具要靠它；
- 上下文 1M，仓库级任务塞得下；
- 价格低，300 个实例 × 5 组 × 3 轮的规模才有可能跑完。

两个必须一起冻结、不能各臂不同的设置：

- **思考模式**。DeepSeek 默认是打开的，而且 effort 默认 high。开或关对延迟和
  费用影响很大，所以代码里强制显式声明，并写进每条记录；不声明就不给跑。
- **推理强度**。`low / high / max` 三档里的哪一档。

还有一处容易踩的坑：思考模式下 `temperature` 是**不生效**的，接口不会报错，
只会静默忽略。`ModelConfig` 因此在思考模式打开时直接拒绝 `temperature`，
免得实验看起来配了参数、实际没配上。同理，`top_p` 只在思考模式生效，
且只有 0.95–1.0 有意义。

另一个实现细节：带 `tools` 参数时，上一轮的 `reasoning_content` 必须原样回传，
否则多轮工具调用会丢上下文。客户端已经处理，并有对应的自检。

### 怎么提供 key

不要写进代码，也不要贴进聊天记录。放在仓库根目录的 `.env` 里（已加入
`.gitignore`）：

```bash
cp .env.example .env      # 然后把 sk-... 填进去
python scripts/check_deepseek.py
```

`check_deepseek.py` 只发三次很小的调用：一次关思考、一次开思考、一次工具调用。
它会打印服务端实际提供的模型名、token 用量、耗时和**估算费用**，用来确认
key 可用、计费通路正确、工具调用能用。它不打印 key。

价格表记在 `pricing.py` 里，并带一个日期。北京时间周一至周五 9:00–12:00 与
14:00–18:00 是高峰档，其余为空闲档，价格差一倍。有一处刻意的简化：官方定义
还排除中国法定节假日，但节假日日历没有编码进去，所以落在节假日的工作日会按
高峰价算——方向是偏高估，不会低估。

### 规模估计

按 flash 的空闲档价（未命中缓存 1 元/百万输入、4 元/百万输出）粗算，若单次实例
平均消耗 20 万输入 token 与 2 万输出 token，单次约 0.3 元；300 实例 × 5 组 × 3
轮 ≈ 4500 次，量级在一千元出头。这是估算不是承诺，真数字要等开发集上跑出来。

```bash
python scripts/estimate_cost.py                    # 不改任何东西，纯算账
python scripts/estimate_cost.py --cache-hit 0.5    # 假设一半 prompt 命中缓存
```

实测输出（默认假设）：

| 场景 | 调用次数 | 空闲档 | 高峰档 |
| --- | --- | --- | --- |
| 单个冒烟实例 | 1 | 0.28 元 | 0.56 元 |
| 开发集 × 1 组 | 23 | 6.44 元 | 12.88 元 |
| 开发集 × 5 组 × 3 轮 | 345 | 96.60 元 | 193.20 元 |
| 测试集 × 5 组 × 3 轮 | 4500 | 1260.00 元 | 2520.00 元 |

高峰档是北京时间周一至周五 9:00–12:00 与 14:00–18:00，其余时间半价。
**把长任务排在空闲档，账单直接减半，实验本身一个字都不用改。**

### 花钱的规则：先问，再花

这条不是靠自觉，是代码里挡着的。`src/swe_repair/spend.py` 做了两道闸：

- **调用前**按最坏情况（prompt 全部未命中缓存 + 最大输出长度）预估这次调用的花费。
  超出剩余额度就直接抛错，**请求根本不会发出去**。
- **调用后**记账。一旦越过上限就报错并停止；那一次的用量仍然记下来，
  不会因为报错就丢掉成本数据（和 `budget.py` 对超额的处理一致）。

还有一条批量的闸：预估花费超过阈值时，必须传入确切的确认语句才会放行，
写错了不算数。

```python
guard.require_approval(estimated_cny, phrase="I approve this spend")
```

几个刻意的默认值，都是为了「忘了设置也不会出事」：

| 项 | 默认值 | 为什么 |
| --- | --- | --- |
| 上限 | 1 元 | 忘了调高，就什么大实验都跑不起来，只会失败 |
| 需要确认的阈值 | 1 元 | 任何超过一块钱的批量都要先问 |
| 未知 prompt 长度时按 | 10 万 token | 宁可高估拒绝，也不低估放行 |
| 缓存命中假设 | 0 | 按全部未命中算，是偏高的方向 |

想放宽必须显式写出来：

```python
SpendGuard(SpendPolicy(ceiling_cny=5.0, max_calls=20))
```

`scripts/check_deepseek.py` 也带闸：默认上限 0.5 元、最多 6 次调用。
它只发三次很小的请求，跑完会打印实际花了多少。

## 评测环境

评测链路要求容器运行时，这是唯一的硬门槛。官方评测是每个实例起一个容器，
没有容器跑不了。这部分已经装好并跑通，下面是踩过的坑，换机器时要照着走一遍。

**一处必须说清的限定**：管道是通的，管道底下的地基却有洞。把标准答案扫遍整个 dev 集，
23 个实例里只有 15 个能过——也就是说这个开发集真正的可用上限是 15，不是 23。
原因、剔除清单和冻结产物见「金标准可解子集」。

### 这台机器上不能用 `wsl --install`

`wsl --install` 会去微软商店的投递节点 `tlu.dl.delivery.mp.microsoft.com` 取包，
而这个节点在本机网络上被中间人拦掉了（第一次跑就卡在 4.5% 然后报错）。
原因是：本机开了一个本地代理 `127.0.0.1:7890`，但只挂在系统代理（WinINET）上，
PowerShell 走它，`curl.exe` 直连不走它，而 **`wsl --install` 走的是 WinHTTP，
`netsh winhttp show proxy` 显示“直连”**，于是它绕过代理去敲商店节点，必然失败。

所以这里改走官方发布渠道，全程绕开商店：

1. `scripts/install_wsl_app.ps1`（**管理员**）——开启两个 Windows 功能，然后安装
   GitHub 官方发布的 WSL 安装包 `wsl.3.0.3.0.x64.msi`（签名与哈希都会先校验）；
2. 重启电脑（必须：`vmcompute`、`hns` 这些服务要重启后才出现）；
3. `scripts/import_ubuntu.ps1`（普通权限）——用 Ubuntu 官方的 24.04 根文件系统
   直接 `wsl --import`，不经过商店，也就绕开了同一个投递节点。

两个安装包放在 `vendor/` 下（已加入 `.gitignore`），版本与哈希：

| 文件 | 大小 | 校验 |
| --- | --- | --- |
| `wsl.3.0.3.0.x64.msi` | 367,575,040 B | 微软签名 `Valid`；sha256 `AE977286…F211` |
| `ubuntu-noble-wsl-amd64-wsl.rootfs.tar.gz` | 356,739,129 B | 与 Ubuntu 官方 `SHA256SUMS` 一致（`8251e27f…315ea`） |

下载命令（走本地代理，`curl.exe` 要显式指定 `-x`）：

```powershell
curl.exe -x http://127.0.0.1:7890 -L -C - -o vendor\wsl.3.0.3.0.x64.msi `
  https://github.com/microsoft/WSL/releases/download/3.0.3/wsl.3.0.3.0.x64.msi
curl.exe -x http://127.0.0.1:7890 -L -C - -o vendor\ubuntu-noble-wsl-amd64-wsl.rootfs.tar.gz `
  https://cloud-images.ubuntu.com/wsl/releases/24.04/current/ubuntu-noble-wsl-amd64-wsl.rootfs.tar.gz
```

### 装好之后

```bash
bash scripts/check_env_wsl.sh          # 容器运行时、harness 环境、冻结数据集、schema v2
bash scripts/run_gold_smoke.sh         # 任务2：单实例金标准冒烟
bash scripts/run_gold_dev_split.sh     # 整个 dev 集（23 个实例、6 个仓库）
```

`--predictions_path gold` 表示直接喂数据集里的标准补丁，预期每个实例都判为
resolved。这一步不调用任何模型，因此不花钱，专门用来验证“提交补丁 → 应用 →
跑测试 → 给出标签”这条闭环是通的。`check_env_wsl.sh` 会把这条命令连同实例 ID
一起打印出来。

注意「链路通」和「实例可用」是两件事：单实例冒烟通过，只说明管道能跑；
整个 dev 集扫下来有 8 个实例连标准答案都过不了，那是镜像本身的缺陷。

**已实测**（2026-10-15，实例 `marshmallow-code__marshmallow-1343`）：

| 项目 | 实测值 |
| --- | --- |
| 结果 | 1 个实例全部 resolved，0 个失败 |
| 评测耗时 | 缓存后 24 秒；同仓库第二个实例在并发争抢下约 4 分钟 |
| 单实例镜像 | 单个 3.6–6.0 GB，视仓库而定（实测 marshmallow 3.6 GB、pvlib 5.9 GB） |
| 首次拉取镜像 | 约 25 分钟，平均不到 1 MB/s |
| 数据集加载 | 23 条 dev 示例，约 1800 示例/秒 |
| 全 dev 集金标准扫描 | 23 个实例里 15 个 resolved、8 个 unresolved（4 worker，1067 秒）；失败的 8 个串行重跑仍全败 |

关键的一条：**镜像才是成本大头，不是跑测试**。同一个仓库的实例会共用基础层，
所以 300 个 test 实例占的磁盘是「仓库数」级别，不是 300 倍。
首次拉完之后的单个实例评测是分钟级，这对任务5 的成本试算很有利。

去重后的实测占用（2026-10-15）：

| 观察 | 数值 |
| --- | --- |
| 3 个仓库、9 个镜像，去重后总占用 | 17.8 GB |
| 折算到每个仓库 | 约 5.9 GB |
| 单个镜像标注大小 | 3.6–6.0 GB（仓库越大越贵） |
| 同一仓库的第二个实例 | 只增加增量层，几乎不占额外空间 |

按此外推：开发集 6 个仓库约 35 GB，测试集 11 个仓库约 65 GB。
**所以磁盘够用，但一定要按仓库预拉，不要按实例拉。**

镜像名规则可以直接算出来，不必查表：
`swebench/sweb.eval.x86_64.<instance_id 里的 __ 换成 _1776_>:latest`。

评测跑在 Ubuntu 里而不是 Windows 里，因为官方 harness 要驱动容器并往容器里拷文件：
守护进程在同一个文件系统里，宿主路径和守护进程路径就是同一条路径，没有转换可以出错。
冻结好的数据集通过 `/mnt/c/...` 照样读得到。

`scripts/setup_docker.ps1` 这个名字保留着，但已经只是转发到上面第 1 步的脚本，
免得旧笔记里的命令失效。

`setup_docker_in_wsl.sh` 会在 `/opt/swe-env` 里建一个 Linux 侧的 Python 虚拟环境装
harness（虚拟环境不能建在 `/mnt/c` 上，drvfs 上装 venv 会出问题）。

WSL 里没有常驻 systemd 时，重启后需要手动起服务：`sudo service docker start`。

### 走代理比走镜像站快二十倍

这是本项目里性价比最高的一次改动，值得写进论文的可复现性一节。

第一版方案是配国内镜像站（`docker.m.daocloud.io`、`docker.1panel.live`），
因为 Docker Hub 从 WSL 里直连不通。能用，但实测只有 **1 MB/s 上下**，
单个镜像要 25 分钟，全 dev 集六个仓库要跑几个小时。曾短暂误判为“卡死了”，
实际是慢。

后来发现真正的原因是 WSL 的虚拟网络默认够不到宿主机的代理：代理软件只监听
`127.0.0.1`，而 WSL 走 NAT 出去，两者不在同一个回环里。在代理软件里打开
**允许局域网连接**之后，`172.30.240.1:7890`（WSL 的默认网关，也就是宿主机）
立刻可达，实测 3.6 MB/s，并且能直连 Docker Hub。

```bash
bash scripts/test_host_proxy.sh          # 先确认代理通不通、多快
bash scripts/setup_proxy_in_wsl.sh       # 配到 shell、dockerd 和 daemon.json
bash scripts/docker_use_hub_direct.sh    # 摘掉镜像站，改走 Hub
bash scripts/fix_daemon_json.sh          # daemon.json 原先带了个尾逗号，不是合法 JSON，顺手修掉
```

效果：单个镜像从 25 分钟降到 **63 秒**。全 dev 集从「几个小时」降到十几分钟。
实测多 worker 并发时整体下行约 **78 MB/s**，test 集 11 个仓库的镜像一个多小时就能全部落地。

注意这是**机器相关的**：`allowed LAN` 是代理软件的设置，换一台机器要重新开；
网关 IP 每次 WSL 重启都可能变，所以三个脚本都是现算网关，不写死。
`setup_proxy_in_wsl.sh --revert` 可以全部撤销回到镜像站方案。

## 任务3：基线试跑

生成侧已经写好：`scripts/run_baseline.py` 是一个**单轮固定流程基线**，一次提问换一个补丁。
它从实例自己的容器镜像里读仓库上下文（镜像里已经有那个提交点的代码），所以除了模型接口之外不需要网络。
先把 prompt 拼出来打印大小、确认不超预算，再真正调用；调用前后都记账，单实例有硬上限。

**它不是 Agentless，报告里不能写成 Agentless。** 它存在的意义是让"生成补丁→判分→记账"
这条通路第一次跑出真实数字，而不是继续停在图上。

```bash
/opt/swe-env/bin/python scripts/run_baseline.py --dry-run          # 只看 prompt 大小，不花钱
bash scripts/run_baseline_dev.sh 3 2.0                             # 三个实例，单实例上限 2 元
bash scripts/run_baseline_dev15.sh                                 # 全部 15 个可用实例，生成并判分
```

`run_baseline_dev.sh` 做三件事：先打印 prompt 大小（不花钱），再生成补丁，最后交给官方 harness 判分。
所有数字写进 `reports/`，成本和结果分开记。

### 第一次实测结果（2026-10-16）

deepseek-flash，思考模式开、档位 `low`，单实例上限 2 元。三个开发实例全部已解决：

| 实例 | 结果 | 补丁行数 | 花销 |
| --- | --- | --- | --- |
| `marshmallow-code__marshmallow-1343` | 已解决 | 11 | 0.108 元 |
| `marshmallow-code__marshmallow-1359` | 已解决 | 10 | 0.067 元 |
| `pydicom__pydicom-1256` | 已解决 | 13 | 0.022 元 |
| 合计 | 3 / 3 | | **0.283 元** |

单实例平均 **0.094 元**。之前按"20 万输入、2 万输出"的粗假设推成本，量级比实测大好几倍；
现在有了实测词元数和官方单价，正式实验的预算才算得出来。

**三个实例不是结论。** 它们是从"标准答案能解"的子集里挑的，样本只有三个，
只说明通路成立和单价量级，说明不了方法好坏。

### 铺满 15 个可用实例（2026-10-16）

3 个样本确实不能当结论。把同一套流程铺到 `data/frozen/instances_dev_gold_ok.txt` 的全部 15 个实例，
原样跑一遍：**4/15 已解决（26.7%）**，整批 1.34 元、单实例 0.089 元、中位数 0.103 元
（分布 0.015–0.188 元，相差 12 倍）。这一轮跑在上午，是**高峰时段价**，空闲时段约为一半。

失败的 11 个按原因拆开，只有 2 个是"改错了代码"：

| 失败形态 | 个数 | 说明 |
| --- | --- | --- |
| 补丁打上但测试没过 | 2 | 补丁能应用，改法与参考解不同 |
| 补丁根本打不上 | 5 | harness 应用补丁时就拒绝，测试一步没跑到 |
| 一个补丁都没写出来 | 4 | 推理把输出长度吃光，`finish_reason=length` |

对症修了两处机械故障之后重跑这 11 个：**6/15（40.0%）**，两次跑合计 2.85 元，
折合每个"已解决" 0.48 元。

```bash
# 第一遍：原样口径
/opt/swe-env/bin/python scripts/run_baseline.py --max-tokens 16384 \
    --per-instance-cny 2.0 --total-cny 6.0 --tag baseline_dev15
# 第二遍：输出上限翻倍 + 重算 hunk 行数
/opt/swe-env/bin/python scripts/run_baseline.py --max-tokens 32768 --repair-hunks \
    --per-instance-cny 2.0 --total-cny 8.0 --tag baseline_dev15_retry
```

汇总：`python scripts/summarise_baseline.py --run reports/baseline_dev15_run.json \
--run reports/baseline_dev15_retry_run.json --tag baseline_dev15 --out reports/baseline_dev15_combined_summary.json`

**钱几乎都花在通路故障上**：成功那 4 个只花 0.12 元，失败那 11 个花了 1.22 元。
所以下一步是修通路，不是调方法。

### 一个把失败伪装成"方法不行"的坑

第一次跑的时候有一个实例没过，而且不是答错——补丁根本没写出来。
查下来：开了思考模式之后，推理过程也占输出长度，那个实例把 4096 个输出 token 全花在推理上，
正好用满，回复被截断，`finish_reason` 是 `length` 而不是 `stop`。
把 `--max-tokens` 提到 16384 重跑，输出 13341 个 token，补丁正常写出，判为已解决。

**结论：思考模式下的输出上限必须给推理留足余量**，否则失败会伪装成"方法不行"。
这也说明通过率不能只看数字，要连 `finish_reason` 一起看。

铺满 15 个实例之后这条更清楚了：提到 16384 仍然有 4 个被截断；再提到 32768，
其中 2 个照样被吃光。**加额度不是解法**，得给推理单独设上限，或者让路由对这类实例换策略。

### 另一类坑：补丁格式错误会伪装成方法失败

5 个实例的补丁在 harness 里根本没被应用。逐个查下来，多数是**模型写的 hunk 头部行数和正文对不上**，
`git apply` 直接判 `corrupt patch`，连测试机会都没有——编辑内容本身可能是对的。

`--repair-hunks` 按正文重算每个 `@@` 的行数。离线验证（`work/test_repair.py`）：
`pylint-dev__astroid-1196` 的补丁只修行数就从 `corrupt patch` 变成正常应用，
重跑后判为已解决；另外两个（`sqlfluff-1763` 用错文件名、`pydicom-901` 上下文对不上）是真的写错了，
修行数救不回来。

两处修复是一起动的，所以"哪个补丁靠哪处修复才过"是逐个核对的，不是单变量实验；
要严格拆开，需要下周把两处修复分别单独跑一遍。

真实基线的顺序是：

1. 选定一个固定流程类基线实现，在 3 到 5 个开发实例上生成补丁。
2. 把生成结果写成 predictions jsonl（字段：`instance_id`、`model_name_or_path`、
   `model_patch`）。
3. 用同一个评测入口判分（harness 也在 Ubuntu 侧）：

   ```bash
   python -m swebench.harness.run_evaluation --dataset_name data/harness --split dev \
       --predictions_path path/to/preds.jsonl --run_id baseline_dev_1 \
       --instance_ids <id1> <id2> <id3> --max_workers 1
   ```

4. 对比 `runs/eval_records.jsonl` 里的记录，得到第一份真实的成本与解决率数据。

**模型已经定了**：`deepseek-flash`，理由和设置见上文「模型与费用」。
**仍然卡的**：一个 API key 和额度。key 到位之前，第 1 步没法真跑。
另外基线的固定流程具体照哪套实现（Agentless 的哪一步、几轮补丁）也还没定，
这件事影响结果口径，应该和老师确认后再冻结。

### key 到位之前能做完的部分

第 2 到 4 步里的格式与判分这几段不需要模型。`scripts/run_baseline_stub.sh`
会把三个已知答案的提交各跑一遍，用来证明判分是可信的：

| 提交内容 | 应该得到 | 检验什么 |
| --- | --- | --- |
| 空补丁 | 0 个已解决　**已实测符合** | 没有东西会被误判成“修好了” |
| 故意写错的补丁 | 0 个已解决　**已实测符合** | 评测器真的去跑测试，而不是相信补丁文本 |
| 标准答案补丁 | 全部已解决　**已实测符合** | 正对照，管道本身没坏 |

三遍都跑过了：空补丁 0/2、错误补丁 0/2、标准答案 2/2，与预期完全一致。
把中间的生成环节换成真实模型即可，前后的接口一个字都不用改。

```bash
python scripts/make_predictions.py --split dev --out runs/preds.jsonl --mode empty
bash scripts/run_baseline_stub.sh dev stub_dev 2
```

## 目录

```
configs/frozen_v1.json        冻结的实验配置
data/raw/*.parquet            下载的原始分片
data/frozen/                  实例清单与冻结凭证
data/harness/*.parquet        harness 输入（schema v2，带 image 列）
vendor/                       WSL 安装包与 Ubuntu 根文件系统（已加入 .gitignore）
reports/                      评测报告（运行后生成）
runs/                         运行记录（运行后生成）
scripts/freeze_dataset.py     任务1：冻结数据集
scripts/run_gold_smoke.sh     任务2：单实例金标准冒烟
scripts/run_gold_dev_split.sh 任务2：整个 dev 集金标准扫描
scripts/make_predictions.py   任务3：写 submissions 文件（空/错误/标准答案三种）
scripts/run_baseline_stub.sh  任务3：不花钱的那半段，三个已知答案各跑一遍
scripts/check_env.py          Windows 侧环境自检
scripts/check_env_wsl.sh      Ubuntu 侧环境自检（容器、harness、数据集）
scripts/net_probe_wsl.sh      WSL 侧网络可达性探测
scripts/probe_mirrors.sh      镜像站可达性与响应速度对比
scripts/probe_blob_speed.sh   镜像站实际下载带宽实测
scripts/test_host_proxy.sh    检测宿主机代理在 WSL 里是否可用、多快
scripts/setup_proxy_in_wsl.sh 把 WSL、dockerd 指到宿主机代理（--revert 可撤销）
scripts/docker_use_hub_direct.sh 在镜像站与 Hub 直连之间切换
scripts/measure_pull.sh       给一次镜像拉取计时，算平均带宽
scripts/check_deepseek.py     验证 key 可用，并实测一次调用的费用
scripts/estimate_cost.py      不动网络，只估算各规模实验要花多少钱
scripts/router_demo.py        路由自检演示（构造状态 → 决策表）
scripts/install_wsl_app.ps1   第一步：装 WSL 应用（需管理员，绕开商店）
scripts/import_ubuntu.ps1     第二步：导入 Ubuntu 24.04（重启后运行）
scripts/setup_docker.ps1      旧名字，转发到 install_wsl_app.ps1
scripts/setup_docker_in_wsl.sh 第三步：Ubuntu 侧装 Docker、镜像加速与 harness；
                              同时探测代理，并把 apt/pip/docker 一起指过去
src/swe_repair/runlog.py      任务4：运行记录 schema 与记录器
src/swe_repair/state.py       状态记录器（表 3.1 的六个状态项）
src/swe_repair/router.py      路由器（第 4.2 节的规则顺序与四组对照）
src/swe_repair/budget.py      预算核算（四元资源向量）
src/swe_repair/fingerprint.py 错误分型与错误指纹
src/swe_repair/patchutil.py   补丁路径与行数统计
src/swe_repair/calibration.py 阈值校准
src/swe_repair/llm.py         模型调用客户端与用量记账
src/swe_repair/pricing.py     官方价目表与计费（高峰/空闲档）
src/swe_repair/spend.py       花费上限守卫：调用前预检、越限即拒、批量需确认
tests/test_runlog.py          schema 自检（11 项）
tests/test_state.py           状态与信号自检（29 项）
tests/test_router.py          路由与四组对照自检（29 项）
tests/test_calibration.py     阈值校准自检（10 项）
tests/test_llm.py             模型客户端、计费、重试与额度守卫自检（43 项）
tests/test_spend.py           花费上限与预算估算自检（20 项）
.env.example                  key 的放置示例（真正的 .env 已 gitignore）
```
