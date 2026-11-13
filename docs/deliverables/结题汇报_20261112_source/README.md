# 结题PPT构建源

保留原蓝白北航模板、母版/版式、字体和可编辑文本表格。最终交付PPT在上级目录。build_deck.mjs从项目根目录运行，使用已配置的Codex bundled Node与@oai/artifact-tool；不使用python-pptx、不修改原模板。默认只导出work/ppt_closeout_20261112/draft/candidate.pptx及预览，--finalize才调用结构/字体/布局校验器；最终文件禁止覆盖，重新修订需指定新的输出文件名。讲解备注同时嵌入PPT。

本目录保存了可复现源，因此后续可在确认其他构建源也已保存后清理work中的预览和草稿。delivery_manifest.json提供文件哈希与来源。
