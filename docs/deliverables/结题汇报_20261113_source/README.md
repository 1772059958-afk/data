# 结题汇报深入分析版

交付文件：`../结题汇报_深入分析版_20261113_定稿.pptx`，21页。

沿用项目蓝白北航模板，正文采用“结论＋证据”的简明写法。内容包括研究对象与价值、五组设计、开发集校准、正式结果、成本、路由差异、案例分析、研究问题回答与逐例附录。两张图表和全部结果表格均可编辑，逐页说明见 `讲稿与来源.md`。

数据来源为已完成的正式20例五组一次、原开发集校准及已完成的正式结果语义/日志复核。取消的补充设置不纳入本版分析。数据汇总为 `runs/ppt_analysis_20261113_01/analysis.json`，校验收据为同目录 `validation_receipt_final.json`。

`build_deck.mjs` 使用 `@oai/artifact-tool` 导入原模板并生成演示文稿。运行前需指定 `RUNTIME_NODE_MODULES`、`RUNTIME_PYTHON` 和 `PRESENTATIONS_SKILL_DIR`。从项目根目录执行 `node docs/deliverables/结题汇报_20261113_source/build_deck.mjs --finalize`；重新构建时以 `PPT_FINAL_PATH` 指向新的输出文件。`render_final.mjs` 负责定稿逐页渲染。

2026-11-13 用户要求PPT完成后的工作暂缓，未继续清理、commit、push或关机。预览暂留 `work/ppt_update_20261113/`，后续处理等待新指令。没有“定稿”后缀的同日文件是内部校样，供版本对照。
