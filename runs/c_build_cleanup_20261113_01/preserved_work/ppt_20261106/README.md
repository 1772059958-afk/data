# 两例五组实验汇报源文件

本目录保存可编辑PPT的JavaScript构建脚本、数据与来源。参考模板为 `docs/deliverables/组会汇报_边界修复与dev准备_20261030.pptx`。幻灯片沿用参考的10页、母版、字体和背景，结果及成本采用原生表格。逐页来源写入 `report_data.json` 并进入演讲者备注。

## 生成

需要当前 Presentations 技能提供的 Node、`@oai/artifact-tool` 和验证程序。脚本自行从本目录向上发现项目根目录，不依赖用户名或固定检出路径。

设置由 `load_workspace_dependencies` 提供的环境路径：

```powershell
$env:RUNTIME_NODE_MODULES = '<runtime dependencies>/node/node_modules'
$env:RUNTIME_PYTHON = '<runtime dependencies>/python/python.exe'
$env:PRESENTATIONS_SKILL_DIR = '<presentations skill directory>'
```

首次实际创建之前，按技能独立执行一次 `container_tools/mark_artifact_operation_started.mjs --operation-kind create --expected-output-count 1 --output-format pptx`。仅查看源码或重新渲染时不重复标记。

```powershell
& '<runtime node executable>' build_deck.mjs report_data.json
```

草稿和逐页PNG写入 `work/ppt_20261106/`。检查全部预览并修排后，加入 `--finalize` 运行最终结构/字体/表格验证，写入 `docs/deliverables/组会汇报_两例五组实验_20261106.pptx`。最终器不会覆盖同名输出。后续修订应通过 `PPT_FINAL_PATH` 指定新输出文件名，可用 `PPT_BUILD_DIR` 指定独立构建目录。

`fill_report_data.mjs` 从已保存的四份最终实验汇总与 `release_validation.json` 更新派生数据，并计算逐页来源SHA256。它只读取已有结果，不运行生成或评测。演讲者备注中的每页本地资料路径可对应回本目录数据中的 `source_hashes`。

`complete` 必须为 `true`，数据校验要求两例五组完整10格、五组费用、最终离线记录和逐页来源。未评测记录保留 `resolved: null`。脚本不调用模型或运行基准评测。
