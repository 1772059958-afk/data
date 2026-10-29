"""Build this week's progress deck on the opening-report template.

The advisor's two notes drive the structure: explain the mechanism before any
result, and use figures rather than tables. So the deck opens with the schematic
as a full page, follows it with a diagram of why a decision is needed, and only
then shows results as charts. Every number here comes from a file under
reports/, and the n=7 caveat is stated on the pages that show a comparison.
"""

from __future__ import annotations

import os

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt
from pptx.oxml.ns import qn

# 模板（组里那份开题 PPT）不在本仓库里：它带着本地路径与学号，不适合入库。
# 需要重建 deck 时用环境变量指向它，例如：
#   $env:DECK_TEMPLATE = "D:\path\to\开题ppt.pptx"
TEMPLATE = os.environ.get("DECK_TEMPLATE", "")

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT_DIR = os.path.join(REPO, "docs", "deliverables")
OUT = os.path.join(OUT_DIR, "第7周进展汇报_自适应混合架构.pptx")
SCHEMATIC = os.path.join(OUT_DIR, "mechanism_overview.png")

FONT = "微软雅黑"
INK = RGBColor(0x20, 0x20, 0x20)
BLUE = RGBColor(0x2F, 0x55, 0x97)
GREY = RGBColor(0x60, 0x60, 0x60)
PALE = RGBColor(0xF2, 0xF2, 0xF2)
LIGHT = RGBColor(0xDC, 0xE9, 0xF5)
RED = RGBColor(0xB0, 0x2A, 0x2A)

TOP = 130.0        # content top, pt
DATE_TEXT = "2026/10/23"

LAY_COVER = 0
LAY_DESIGN = 4      # nav highlights 方法设计
LAY_TOOL = 6        # nav highlights 原型工具
LAY_EVAL = 5        # nav highlights 实验评估
LAY_SUMMARY = 7     # nav highlights 总结与展望


# --------------------------------------------------------------------------
# low level helpers
# --------------------------------------------------------------------------


def style(run, size: float, *, bold: bool = False, colour: RGBColor = INK) -> None:
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = colour
    run.font.name = FONT
    rpr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        node = rpr.find(qn(tag))
        if node is None:
            node = rpr.makeelement(qn(tag), {})
            rpr.append(node)
        node.set("typeface", FONT)


def textbox(slide, x: float, y: float, w: float, h: float,
            lines, *, size: float = 18.0, colour: RGBColor = INK,
            bold: bool = False, align=PP_ALIGN.LEFT, spacing: float = 6.0):
    box = slide.shapes.add_textbox(Inches(x / 72), Inches(y / 72),
                                   Inches(w / 72), Inches(h / 72))
    frame = box.text_frame
    frame.word_wrap = True
    first = True
    for item in lines:
        body, opts = (item, {}) if isinstance(item, str) else item
        para = frame.paragraphs[0] if first else frame.add_paragraph()
        first = False
        para.alignment = opts.get("align", align)
        para.space_after = Pt(opts.get("spacing", spacing))
        run = para.add_run()
        run.text = body
        style(run, opts.get("size", size), bold=opts.get("bold", bold),
              colour=opts.get("colour", colour))
    return box


def panel(slide, x: float, y: float, w: float, h: float,
          *, fill=PALE, line=RGBColor(0xBF, 0xBF, 0xBF), radius=True):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
        Inches(x / 72), Inches(y / 72), Inches(w / 72), Inches(h / 72),
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    shape.line.color.rgb = line
    shape.line.width = Pt(1.0)
    shape.shadow.inherit = False
    shape.text_frame.text = ""
    return shape


def title_of(slide, body: str, *, size: float = 23.2) -> None:
    holder = slide.shapes.title
    holder.text_frame.text = ""
    para = holder.text_frame.paragraphs[0]
    run = para.add_run()
    run.text = body
    style(run, size, bold=True, colour=INK)


def set_date(slide) -> None:
    for shape in slide.shapes:
        if shape.is_placeholder and shape.placeholder_format.idx == 2:
            shape.text_frame.text = ""
            run = shape.text_frame.paragraphs[0].add_run()
            run.text = DATE_TEXT
            style(run, 11.0, colour=GREY)


def note(slide, body: str) -> None:
    slide.notes_slide.notes_text_frame.text = body


def bar_chart(slide, x, y, w, h, categories, series, *, colours=None,
              number_format='0', legend: bool = True, max_value=None):
    data = CategoryChartData()
    data.categories = categories
    for name, values in series:
        data.add_series(name, values)
    frame = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED,
                                   Inches(x / 72), Inches(y / 72),
                                   Inches(w / 72), Inches(h / 72), data)
    chart = frame.chart
    chart.has_title = False
    chart.has_legend = legend
    if legend:
        chart.legend.position = XL_LEGEND_POSITION.BOTTOM
        chart.legend.include_in_layout = False
        chart.legend.font.size = Pt(12)
        chart.legend.font.name = FONT
    plot = chart.plots[0]
    plot.gap_width = 60
    plot.has_data_labels = True
    labels = plot.data_labels
    labels.number_format = number_format
    labels.number_format_is_linked = False
    labels.position = XL_LABEL_POSITION.OUTSIDE_END
    labels.font.size = Pt(13)
    labels.font.bold = True
    labels.font.name = FONT
    if colours:
        for index, colour in enumerate(colours):
            point = plot.series[0].points[index]
            point.format.fill.solid()
            point.format.fill.fore_color.rgb = colour
    else:
        for index, series_obj in enumerate(plot.series):
            colour = BLUE if index == 0 else RGBColor(0xBF, 0xBF, 0xBF)
            series_obj.format.fill.solid()
            series_obj.format.fill.fore_color.rgb = colour
    axis = chart.category_axis
    axis.tick_labels.font.size = Pt(13)
    axis.tick_labels.font.name = FONT
    value_axis = chart.value_axis
    value_axis.visible = False
    value_axis.has_major_gridlines = False
    if max_value is not None:
        value_axis.maximum_scale = max_value
    return frame


def drop_slides(prs) -> None:
    lst = prs.slides._sldIdLst
    for entry in list(lst):
        rid = entry.get(qn("r:id"))
        prs.part.drop_rel(rid)
        lst.remove(entry)


# --------------------------------------------------------------------------
# the deck
# --------------------------------------------------------------------------


def build() -> None:
    if not TEMPLATE:
        raise SystemExit(
            "没有指定 PPT 模板。模板是组里那份开题 PPT，不随仓库分发。\n"
            "先设置环境变量再运行：\n"
            '  $env:DECK_TEMPLATE = "D:\\path\\to\\开题ppt.pptx"'
        )
    if not os.path.exists(TEMPLATE):
        raise SystemExit(f"DECK_TEMPLATE 指向的文件不存在：{TEMPLATE}")
    prs = Presentation(TEMPLATE)
    drop_slides(prs)

    # 1 cover ---------------------------------------------------------------
    slide = prs.slides.add_slide(prs.slide_layouts[LAY_COVER])
    title_of(slide, "混合架构程序修复\n自适应混合架构研究", size=33.0)
    # The cover layout numbers its body placeholder 10, not 1, so pick it by
    # elimination rather than hard-coding an index.
    body = next(ph for ph in slide.placeholders if ph.placeholder_format.idx != 0)
    body.text_frame.text = ""
    for i, line in enumerate(["第 7 周进展汇报",
                              "汇报人：陈堉锋　张曹远臻",
                              "指导老师：张莉",
                              "2026 年 10 月"]):
        para = body.text_frame.paragraphs[0] if i == 0 else body.text_frame.add_paragraph()
        run = para.add_run()
        run.text = line
        style(run, 19.5, colour=INK)
    note(slide, "这周的主线一句话：五组对照第一次全部跑通，升级从净损失变成了净收益；"
                "但同时也证明，我们那套路由规则目前和全升级完全等价。")

    # 2 headline ------------------------------------------------------------
    slide = prs.slides.add_slide(prs.slide_layouts[LAY_DESIGN])
    title_of(slide, "本周主线：把「升级」从净损失修成净收益")
    set_date(slide)
    textbox(slide, 45, TOP, 870, 40, [
        ("五组对照（A 固定 / B 纯交互 / C 全升级 / D 自适应 / E 随机）在 7 个实例上首次全部产出补丁。",
         {"size": 17, "colour": GREY}),
    ])
    cards = [
        ("6/7 → 1/7", "交互分支交空补丁的实例数", "强制收尾前 → 后"),
        ("0.0 → 0.5", "神谕缺口闭合率", "D 组首次拿到一半可达增益"),
        ("3 → 4", "D 组解决数（满分 7）", "首次超过纯固定流程"),
    ]
    width, gap = 276.0, 24.0
    for index, (big, label, sub) in enumerate(cards):
        x = 45 + index * (width + gap)
        panel(slide, x, 185, width, 118, fill=LIGHT, line=BLUE)
        textbox(slide, x + 14, 197, width - 28, 44,
                [(big, {"size": 30, "bold": True, "colour": BLUE})])
        textbox(slide, x + 14, 246, width - 28, 26,
                [(label, {"size": 14, "colour": INK})])
        textbox(slide, x + 14, 272, width - 28, 22,
                [(sub, {"size": 12, "colour": GREY})])
    panel(slide, 45, 322, 870, 96, fill=PALE)
    textbox(slide, 60, 334, 840, 76, [
        ("但同一轮实验也暴露出一个结构性问题：D 组与 C 组的逐实例决策完全相同（各 4 次升级）。",
         {"size": 16, "colour": RED, "bold": True}),
        ("这不是实现 bug，而是规则集本身缺少「说不升级」的能力——详见第 10 页。",
         {"size": 15, "colour": INK}),
    ])
    note(slide, "先给结论，再讲机制。三个数字是本周的全部进展，最后一个红框是本周最重要的发现。")

    # 3 mechanism overview (figure 1) ---------------------------------------
    slide = prs.slides.add_slide(prs.slide_layouts[LAY_DESIGN])
    title_of(slide, "机制总览：唯一变量是「决策点之后怎么走」")
    set_date(slide)
    # The schematic is 519x343 units, so its height is fixed by the width.
    # Available band is y=130..490 (360 pt), which caps the width at ~545 pt.
    pic_w = 540.0
    pic_h = pic_w * 343 / 519
    slide.shapes.add_picture(SCHEMATIC, Inches((960 - pic_w) / 2 / 72),
                             Inches(130 / 72), width=Inches(pic_w / 72))
    note(slide, "这是老师上次说缺的那一页。讲法：从①走到⑥。\n"
                "重点强调灰底的②共享前缀由 A/C/D/E 四组完全共用、同一预算；"
                "蓝框③是唯一变量，它只读前缀算出来的证据——可行候选数、u_loc、u_dup、"
                "行为信号、剩余预算。\n"
                "落到一句话：我们的贡献不是更强的修复器，而是一个可评价的升级决策。")

    # 4 why a decision is needed (figure 2) --------------------------------
    slide = prs.slides.add_slide(prs.slide_layouts[LAY_DESIGN])
    title_of(slide, "为什么需要决策：两条路各有各的代价")
    set_date(slide)
    col_w = 420.0
    for index, (head, pros, cons) in enumerate([
        ("固定流程", ["预算可预测，便宜", "实现简单，延迟低"],
         ("一次生成，不看反馈", "改错就没有第二次机会", "本地化错了也无从纠正")),
        ("受限交互", ["能读栈、能跑测试", "可多轮修正"],
         ("每次都要多花 6–10 次调用", "对着简单题也会白花钱")),
    ]):
        x = 45 + index * (col_w + 30)
        panel(slide, x, 138, col_w, 232, fill=PALE)
        textbox(slide, x + 16, 148, col_w - 32, 30,
                [(head, {"size": 19, "bold": True, "colour": BLUE})])
        y = 186
        for line in pros:
            textbox(slide, x + 16, y, col_w - 32, 24,
                    [("＋  " + line, {"size": 15, "colour": INK})])
            y += 26
        y += 8
        for line in cons:
            textbox(slide, x + 16, y, col_w - 32, 24,
                    [("－  " + line, {"size": 15, "colour": RED})])
            y += 26
    panel(slide, 45, 386, 870, 74, fill=LIGHT, line=BLUE)
    textbox(slide, 60, 396, 840, 56, [
        ("所以问题不是「哪种更强」，而是「什么时候值得升级」——用前缀证据预测升级的边际价值。",
         {"size": 17, "bold": True, "colour": BLUE}),
        ("这就是本工作的主张：可证伪、有神谕上界、且不依赖更强的模型。",
         {"size": 14, "colour": INK}),
    ])
    note(slide, "这一页回答'为什么要有机制'。左边是上周那条基线，右边是交互分支，"
                "各自的能力和代价都列出来，自然引出'决策'这个研究对象。")

    # 5 two fixes (figure 3) ------------------------------------------------
    slide = prs.slides.add_slide(prs.slide_layouts[LAY_TOOL])
    title_of(slide, "原型工具：v2.3 两处修正，直接改写结果")
    set_date(slide)
    rows = [
        ("强制收尾", "预算耗尽时保留 1 次无工具调用，要求交出最好补丁",
         "空补丁 6/7 → 1/7"),
        ("公开测试发现", "只认同名 test_*.py → 名称 + 内容双路匹配",
         "行为信号 2/7 → 4/7"),
    ]
    y = 140
    for head, how, effect in rows:
        panel(slide, 45, y, 870, 96, fill=PALE)
        textbox(slide, 62, y + 12, 210, 30,
                [(head, {"size": 18, "bold": True, "colour": BLUE})])
        textbox(slide, 62, y + 48, 520, 36,
                [(how, {"size": 14, "colour": INK})])
        textbox(slide, 620, y + 26, 280, 34,
                [(effect, {"size": 18, "bold": True, "colour": RED})])
        y += 112
    panel(slide, 45, 372, 870, 86, fill=LIGHT, line=BLUE)
    textbox(slide, 60, 382, 840, 68, [
        ("这两处不是调参，是补实现：收尾让「探索过但没写」与「什么都没学到」可分，"
         "测试发现让 behavioural_signal 在 astroid / sqlfluff 上不再恒为 none。",
         {"size": 15, "colour": INK}),
        ("它们同时把升级从「净损失」翻成「净收益」：Q2（升级有害）从 3 个降到 1 个。",
         {"size": 15, "colour": BLUE, "bold": True}),
    ])
    note(slide, "这两处是我们自己实现里的缺陷，修完结果立刻变了，所以放在结果之前讲。")

    # 6 experimental design (figure 4) --------------------------------------
    slide = prs.slides.add_slide(prs.slide_layouts[LAY_EVAL])
    title_of(slide, "实验设计：A–E 五组各自是什么")
    set_date(slide)

    headers = [("组", 48, 34), ("", 92, 130), ("前缀", 228, 100),
               ("前缀之后怎么走", 340, 280), ("决策依据", 632, 286)]
    for text_, x, width in headers:
        if not text_:
            continue
        textbox(slide, x, 130, width, 20,
                [(text_, {"size": 11, "colour": GREY})])

    arms = [
        ("A", "固定流程", "共用", "固定延续：继续生成候选，不调工具",
         "无（只看共享停止规则）", False),
        ("B", "纯交互", "不用", "从零开始受限交互：6 工具 · 4 状态",
         "无", False),
        ("C", "简单级联", "共用", "只要没冻结就升级",
         "无（全部升级）", False),
        ("D", "自适应（本工作）", "共用", "按前缀证据决定",
         "u_loc · u_dup · 行为信号 · 预算", True),
        ("E", "随机路由", "共用", "以固定概率 0.5 升级", "抛硬币", False),
    ]
    y = 152
    for mark, name, prefix, after, basis, highlight in arms:
        fill = LIGHT if highlight else PALE
        line = BLUE if highlight else RGBColor(0xBF, 0xBF, 0xBF)
        panel(slide, 45, y, 870, 44, fill=fill, line=line)
        chip = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                      Inches(56 / 72), Inches((y + 8) / 72),
                                      Inches(26 / 72), Inches(26 / 72))
        chip.fill.solid()
        chip.fill.fore_color.rgb = BLUE if highlight else RGBColor(0x9A, 0x9A, 0x9A)
        chip.line.fill.background()
        chip.shadow.inherit = False
        chip.text_frame.text = ""
        textbox(slide, 56, y + 14, 26, 22,
                [(mark, {"size": 13, "bold": True, "colour": RGBColor(0xFF, 0xFF, 0xFF)})],
                align=PP_ALIGN.CENTER)
        textbox(slide, 92, y + 12, 130, 22,
                [(name, {"size": 13, "bold": highlight,
                         "colour": BLUE if highlight else INK})])
        textbox(slide, 228, y + 13, 100, 20,
                [(prefix, {"size": 12, "colour": INK})])
        textbox(slide, 340, y + 13, 280, 20,
                [(after, {"size": 12, "colour": INK})])
        textbox(slide, 632, y + 13, 286, 20,
                [(basis, {"size": 12, "colour": GREY})])
        y += 50

    panel(slide, 45, 416, 870, 52, fill=LIGHT, line=BLUE)
    textbox(slide, 60, 424, 840, 40, [
        ("评价方式：每个实例都跑两条分支（固定延续 / 交互升级），得到反事实四象限；"
         "指标＝解决数、升级次数、神谕缺口闭合率、四象限分布。",
         {"size": 13, "colour": INK}),
    ])
    note(slide, "这一页先讲清楚五组。关键区别只有两处：B 不用前缀，其余四组都共用同一个前缀；"
                "前缀之后，A 不升级、C 无条件升级、D 按证据升级、E 抛硬币。"
                "所以五组里只有 D 需要那份证据，这就是我们的研究点。\n"
                "评价方式一句话：两条分支都跑，才能知道「如果升级会不会更好」，这就是反事实。")

    # 7 five arms (figure 5) ------------------------------------------------
    slide = prs.slides.add_slide(prs.slide_layouts[LAY_EVAL])
    title_of(slide, "五组对照首次全部通电：D 组首次超过纯固定")
    set_date(slide)
    bar_chart(slide, 45, 132, 520, 300,
              ["A 固定", "B 纯交互", "C 全升级", "D 自适应", "E 随机"],
              [("解决数（满分 7）", (3, 4, 4, 4, 3))],
              colours=[RGBColor(0xBF, 0xBF, 0xBF), RGBColor(0xBF, 0xBF, 0xBF),
                       RGBColor(0xBF, 0xBF, 0xBF), BLUE, RGBColor(0xBF, 0xBF, 0xBF)],
              legend=False, max_value=7)
    textbox(slide, 585, 140, 330, 290, [
        ("读法", {"size": 17, "bold": True, "colour": BLUE}),
        ("n = 7 个实例，只验证通路与方向，不构成效果结论。", {"size": 14, "colour": GREY}),
        ("D 与 C 同为 4/7，但 D 只升级 4 次、C 升级 7 次。", {"size": 14}),
        ("神谕（只在该升级的实例上升级）= 5/7。", {"size": 14}),
        ("神谕缺口闭合率 0.5：可达增益 2 个实例，D 拿到 1 个。", {"size": 14}),
        ("成本：D 0.574 元 / A 0.519 元 / C 0.688 元。", {"size": 14}),
    ])
    note(slide, "注意先说 n=7 不做排序。这里的重点是 D 用比 C 少 3 次升级拿到同样解决数。")

    # 7 quadrants (figure 5) ------------------------------------------------
    slide = prs.slides.add_slide(prs.slide_layouts[LAY_EVAL])
    title_of(slide, "反事实四象限：只有 28.6% 的实例真的需要升级")
    set_date(slide)
    cells = [
        (45, 150, "① 双重成功", 2, "两边都能解 —— 升级是浪费", PALE),
        (475, 150, "② 仅固定成功", 1, "升级反而变差", RGBColor(0xFB, 0xE9, 0xE9)),
        (45, 292, "③ 仅交互成功", 2, "升级必要 —— 路由要抓的就是它", LIGHT),
        (475, 292, "④ 双失败", 2, "升级无望", PALE),
    ]
    for x, y, head, count, sub, fill in cells:
        panel(slide, x, y, 400, 126, fill=fill)
        textbox(slide, x + 16, y + 12, 200, 28,
                [(head, {"size": 16, "bold": True, "colour": BLUE})])
        textbox(slide, x + 250, y + 6, 130, 44,
                [(str(count), {"size": 30, "bold": True, "colour": INK})],
                align=PP_ALIGN.RIGHT)
        textbox(slide, x + 16, y + 66, 368, 44,
                [(sub, {"size": 14, "colour": INK})])
    textbox(slide, 45, 428, 870, 34, [
        ("升级必要占比 2/7 = 28.6%；其余 71.4% 的实例上升级是浪费（①④）或有害（②）。",
         {"size": 15, "colour": GREY}),
    ])
    note(slide, "四象限是把'要不要升级'变成可统计问题的关键。②那格最关键：升级会把已经修好的实例做坏。")

    # 8 before / after bar (figure 6) --------------------------------------
    slide = prs.slides.add_slide(prs.slide_layouts[LAY_EVAL])
    title_of(slide, "两处修正前后：空补丁与行为信号")
    set_date(slide)
    bar_chart(slide, 45, 132, 540, 300,
              ["交空补丁的实例数", "有行为信号的实例数"],
              [("v2.2 修正前", (6, 2)), ("v2.3 修正后", (1, 4))],
              max_value=7)
    textbox(slide, 605, 140, 310, 290, [
        ("同样 7 个实例", {"size": 17, "bold": True, "colour": BLUE}),
        ("空补丁从 6 个降到 1 个：交互分支终于能交东西了。", {"size": 14}),
        ("行为信号从 2 个升到 4 个：astroid / sqlfluff 的公开测试终于跑起来了。", {"size": 14}),
        ("连带效果：神谕缺口闭合率 0.0 → 0.5。", {"size": 15, "bold": True, "colour": RED}),
        ("两版结果不可混用，各自独立记录。", {"size": 13, "colour": GREY}),
    ])
    note(slide, "这张图回答'你这两处改动到底有没有用'。两组柱子都是 7 个实例里的计数。")

    # 9 anomaly: D equals C (figure 7) -------------------------------------
    slide = prs.slides.add_slide(prs.slide_layouts[LAY_EVAL])
    title_of(slide, "反常：D 与 C 决策完全相同，规则集缺少「不升级」")
    set_date(slide)
    bar_chart(slide, 45, 132, 540, 296,
              ["冻结（已有候选）", "定位分歧 u_loc", "无行为信号", "固定延续"],
              [("实际决定 D", (3, 3, 1, 0)), ("若不短路会触发", (3, 6, 3, 7))],
              max_value=7)
    textbox(slide, 605, 136, 310, 300, [
        ("证据", {"size": 17, "bold": True, "colour": BLUE}),
        ("四条升级规则都很容易满足：u_loc 在 6/7 实例上超阈值。", {"size": 14}),
        ("「固定延续」本可覆盖全部 7 个实例，却一次都没轮到。", {"size": 14, "colour": RED}),
        ("于是 D 与 C 逐实例决策一致（各 4 次升级），自适应退化成级联。", {"size": 14}),
        ("这一条与预算无关：前缀跑完还剩 14 万 token。", {"size": 13, "colour": GREY}),
    ])
    note(slide, "这是本周最重要的一页。不要说成'效果不好'，要说成'规则集结构上无法区分'，"
                "并提出两条可选改法请老师定。")

    # 10 blockers ----------------------------------------------------------
    slide = prs.slides.add_slide(prs.slide_layouts[LAY_SUMMARY])
    title_of(slide, "卡点：三件需要老师判断的事")
    set_date(slide)
    items = [
        ("规则 4（u_loc）方向是反的",
         "7 个实例上 AUC = 0.40，且在不需要升级的实例上更高。是换构造（改用多次模型定位之间的分歧），还是降级为次要规则？"),
        ("规则 7 的语义要不要收窄",
         "现在「没有行为信号」包含「检查跑了但只失败在格式/环境」，导致它几乎总是触发。是否改为「完全没有可跑检查时才升级」？"),
        ("n = 7 的定位",
         "本轮只当通路验证。主实验上 98 个已下载实例，需要约 100–250 元预算，是否按这个规模推进？"),
    ]
    y = 138
    for index, (head, body) in enumerate(items, start=1):
        panel(slide, 45, y, 870, 96, fill=PALE)
        textbox(slide, 58, y + 12, 45, 34,
                [(str(index), {"size": 24, "bold": True, "colour": BLUE})])
        textbox(slide, 108, y + 10, 780, 28,
                [(head, {"size": 17, "bold": True, "colour": INK})])
        textbox(slide, 108, y + 42, 780, 48,
                [(body, {"size": 13, "colour": GREY})])
        y += 106
    note(slide, "三件事都明确到要什么：要判断、要取舍、要预算。不要含糊说'请老师指导'。")

    # 11 next week ---------------------------------------------------------
    slide = prs.slides.add_slide(prs.slide_layouts[LAY_SUMMARY])
    title_of(slide, "下周计划：先把规则改对，再上规模")
    set_date(slide)
    steps = [
        ("①", "定规则改法", "按老师意见改规则 4 / 7，写进协议 v2.4，并记录改动前后不可混用"),
        ("②", "在 dev 15 上校准阈值", "一次定稿、冻结哈希，禁止事后回调"),
        ("③", "98 个实例跑反事实", "两分支各一次，产出四象限、AUC 与神谕缺口闭合率"),
        ("④", "补重复实验", "repeats = 3，报逐仓库宏平均，回答方差问题"),
    ]
    y = 140
    for mark, head, body in steps:
        textbox(slide, 45, y, 40, 32,
                [(mark, {"size": 20, "bold": True, "colour": BLUE})])
        textbox(slide, 92, y, 300, 32,
                [(head, {"size": 17, "bold": True, "colour": INK})])
        textbox(slide, 400, y + 4, 515, 40,
                [(body, {"size": 14, "colour": GREY})])
        y += 66
    panel(slide, 45, 412, 870, 46, fill=LIGHT, line=BLUE)
    textbox(slide, 60, 420, 840, 34, [
        ("需要：规则改法的判断（老师）＋ 约 100–250 元实验预算＋ dev 阈值定稿后不再改动。",
         {"size": 15, "bold": True, "colour": BLUE}),
    ])
    note(slide, "四条都可验证，下周能逐条对账。最后一行写清要什么资源。")

    os.makedirs(OUT_DIR, exist_ok=True)
    prs.save(OUT)
    print(f"saved: {OUT}")
    print(f"slides: {len(prs.slides)}")


if __name__ == "__main__":
    build()
