# 周报交付物

这里是各组会用来汇报的定稿文件。**二进制文件，只在定稿时提交**，不要每改一版都提交一次。

| 文件 | 是什么 | 怎么来的 |
| --- | --- | --- |
| `第7周进展汇报_自适应混合架构.pptx` | 第 7 周组会 PPT，12 页 | `python scripts/build_week7_deck.py` |
| `第7周进展汇报_讲稿.docx` | 对应 PPT 的逐页讲稿，含时间控制与预演问答 | `python scripts/build_speaker_script.py` |
| `mechanism_overview.svg` | 机制总览图，可编辑矢量源 | `python scripts/make_schematic.py` |
| `mechanism_overview.pdf` | 同一张图的 PDF，183 × 121 mm，字体已嵌入 | 由 SVG 导出 |
| `mechanism_overview.png` | 同一张图的位图预览 | 由 SVG 导出 |

## 生成这几份文件的前提

1. **两个 Python 构建脚本需要 `python-pptx` 与 `python-docx`**，本仓库的离线测试不依赖它们。
2. `build_week7_deck.py` 需要一个 PPT 模板（组里那份开题 PPT）。模板不在本仓库里，
   用环境变量指定：

   ```powershell
   $env:DECK_TEMPLATE = "D:\path\to\开题ppt-xxx.pptx"
   python scripts/build_week7_deck.py
   ```

   没有设这个变量时脚本会直接报错退出，不会静默生成一个样式不对的 deck。

3. `make_schematic.py` 只写 SVG。SVG 转 PDF/PNG 需要外部渲染器（本仓库用的是
   Edge 的 headless 打印 + cairosvg），这一步没有写进脚本，因为依赖与平台相关。

## 数据与结论的对应关系

PPT 里的每个数字都能在 `reports/` 里找到出处，`docs/实验记录.md` 的
`exp-20261023-01` 与 `exp-20261023-02` 两条记录逐条列了指向。

主要对应：

| 结论 | 文件 |
| --- | --- |
| 五组解决数 A3/B4/C4/D4/E3 | `reports/cf_dev7_v23-<组>.cf_dev7_v23.json` |
| 神谕 5/7、缺口闭合率 0.5 | `reports/cf_dev7_v23_analysis.json` |
| 四象限 2/1/2/2 | 同上 `quadrants` |
| 规则触发分布 | `reports/cf_dev7_v23_matrix.json` 的 `router_rules` |
| 空补丁 6/7 → 1/7 | `cf_dev7_v22_*` 与 `cf_dev7_v23_*` 两组对比 |
