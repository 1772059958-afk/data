# 模型身份与计价复核（2026-11-11）

范围：只读源码、既有探测记录与官方公开文档。没有读取项目 `.env`、密钥，没有发出认证请求或模型调用。此报告不是本轮接口实测，也不批准模型冻结。

## 官方公开信息

1. 官方中文价格页当前将请求标识 `deepseek-flash` 对应的模型版本列为 `DeepSeek-V4.1-Flash-1017`。旧 `deepseek-v4-flash` 与 vision-exp 名称仍被接受，但会重定向至当前 Flash，并非可恢复旧版本的入口。[模型与价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)
2. Chat API 的模型请求枚举仅列 `deepseek-flash` 和 `deepseek-v4-pro`。响应具有 `model`、`id`、`created` 和 `system_fingerprint`；文档将 fingerprint 描述为后端配置指纹。请求 schema 没有指定 fingerprint、不可变 snapshot 或生成 seed 的参数。由此不能证明可在官方 API 请求或恢复一个不可变模型版本；价格页中的版本名称是官方当前映射证据。[Chat API](https://api-docs.deepseek.com/api/create-chat-completion/)
3. `/models` 提供可调用 `id`、显示名称、上下文/输出限制、effort 与协议能力。显示名称并非单独可调用的 snapshot 承诺；服务端也可能省略部分元数据。[Models API](https://api-docs.deepseek.com/api/list-models/)
4. 官方新闻证实 1017 已上线 API；新闻中的公开权重版本不自动等于官方 API 可固定的部署版本。[1017 发布](https://api-docs.deepseek.com/news/news261017/)

以上是公开文档复核；本轮实际 `/models` 与响应字段是否存在，仍由根代理的项目凭据探测确认。

## 本地实现与已有证据

- `runs/model_probe_20261106_02/result.json` 仅观测到 `served_model=deepseek-flash`，不含不可变版本证据或 fingerprint。它是旧接口验收事实，不代表当前本轮模型已固定。
- `llm.CallRecord` 当前保存 requested/served model、payload `id`、时间、usage、effort 等，未保存 `system_fingerprint` 或响应 `created`。`_post` 也不保留 HTTP 响应 headers。
- `BudgetedClient._check_served_model` 当前只核响应模型别名及是否报告 model。因此它可以发现别名改变，无法发现别名未变而后端改变。`llm.py` 开头关于“保证版本不会漂移”的表述超出当前实现证据，应更正。
- `model_version` 当前同时被用作预期响应标识。不能直接把 `DeepSeek-V4.1-Flash-1017` 写入该字段后假定响应 `model` 会返回它；应将请求别名、官方文档版本映射和实际后端指纹分别记录。

## 最小可行选项与边界

若维持计划的**可请求/恢复不可变 snapshot**要求，当前公开官方接口没有已证实的满足方式；在获得具体版本端点或提供方保证前，正式冻结仍有阻塞，不能填写 `immutable_version=true`。

可实施更强的运行期观测：保存每次响应 model/id/created/system_fingerprint，显式固定有效采样与 effort；由本轮探测记录预期指纹，缺失或变化时停止并保留费用与已发送请求，不自动重试或跨后端拼接结果。仅保留非凭据响应 header 白名单（如实际存在的 Date/request ID），不全量保存 header。该方案**检测后端配置变化，不等于不可变模型快照**，不能据此回写一个虚假的不可变冻结；采用这一可复现性受限协议需要明确记录其相对原计划的变化。

思考模式中 temperature 无效，项目保持 `None` 合理；Flash 的有效 top_p 默认1.0，可以显式设置1.0。项目运行种子控制路由/调度，不应写成 API 随机生成已获 seed 固定。

## 当前 CNY 价格复核

官方中文页与 `pricing.py` 当前 Flash 表一致（每百万 token）：

| 项目 | 空闲 | 高峰 |
| --- | ---: | ---: |
| 输入缓存命中 | 0.02 | 0.04 |
| 输入缓存未命中 | 1.00 | 2.00 |
| 输出 | 4.00 | 8.00 |

高峰为北京时间周一至周五9–12及14–18，排除中国法定节假日。源码对假日默认保守高估，已有说明。本轮必须保存价格核验日期/来源；基于usage的金额仍是估算，不能称账单实付。此报告未改变价格表和旧记录。

## 后续身份审计补齐（同日追加）

以上“本地实现”段落记录改造前状态。根代理随后指定最小审计修复，已落实：`CallRecord` 保存真实有效的 `system_fingerprint` 与 `provider_created`，缺失或无效值保持未知；修正文首不可变保证措辞；`BudgetedClient` 可选期望指纹，默认 None 保持旧 dev 行为。若配置期望指纹，响应缺失或变化会在usage和费用记账后拒绝接受该回答；已有模型别名违例同样触发共享 client 的身份熔断。同 client 即使建立新 Runtime/分支也在下一次模型请求之前拒绝，不消耗额外请求。熔断标记仅使用固定安全原因码。`experiment.py` 在 prefix 与后续分支传入配置指纹。

新增6项直接回归和2项编排回归；与模型、交互、核心契约及prefix相关套件合计112/112通过。测试均为离线假transport/假容器，未读取 `.env`、未发真实请求。全套与真实探测由根代理另行运行。此审计增强仍不构成不可变版本保证，不会自动冻结配置或放宽正式协议。
