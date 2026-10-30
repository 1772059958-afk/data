"""Generate the mechanism overview schematic as hand-built SVG.

Design brief (confirmed):
  scope   = the method's main flow only (no arm swimlanes, no quadrant panel)
  canvas  = 183 mm double column, drawn at final size so 1 unit = 1 pt
  note    = one grey footnote stating the thresholds are placeholders

Layout is a top-down pipeline: instance -> shared prefix -> decision point ->
the two continuations -> freeze -> grade. The prefix is one outlined container
so its five internal steps read as a single shared stage, which is the point the
figure argues: only what happens after the decision point differs.
"""

from __future__ import annotations

import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT = os.path.join(REPO, "docs", "deliverables", "mechanism_overview.svg")

FONT = "Arial, 'Microsoft YaHei', 'Segoe UI', sans-serif"

INK = "#1A1A1A"
GREY_LINE = "#7A7A7A"
GREY_FILL = "#F2F2F2"
ACCENT = "#1F4E79"
ACCENT_FILL = "#DCE9F5"
WHITE = "#FFFFFF"

F_LABEL = 6.0      # box titles
F_DETAIL = 5.5     # descriptive lines
F_TITLE = 7.0      # container title, panel letter


def esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def text(x: float, y: float, body: str, size: float, *, bold: bool = False,
         anchor: str = "middle", ink: str = INK) -> str:
    weight = ' font-weight="bold"' if bold else ""
    return (
        f'  <text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}"'
        f' text-anchor="{anchor}" fill="{ink}"{weight}>{esc(body)}</text>\n'
    )


def box(x: float, y: float, w: float, h: float, *, fill: str = GREY_FILL,
        stroke: str = GREY_LINE, width: float = 0.8, rx: float = 3.0) -> str:
    return (
        f'  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" ry="{rx}"'
        f' fill="{fill}" stroke="{stroke}" stroke-width="{width}"/>\n'
    )


def arrow(x1: float, y1: float, x2: float, y2: float, *, width: float = 0.8,
          marker: str = "arrow") -> str:
    return (
        f'  <line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{INK}"'
        f' stroke-width="{width}" marker-end="url(#{marker})"/>\n'
    )


def path(d: str, *, width: float = 0.8, marker: str | None = "arrow") -> str:
    end = f' marker-end="url(#{marker})"' if marker else ""
    return (
        f'  <path d="{d}" fill="none" stroke="{INK}" stroke-width="{width}"{end}/>\n'
    )


def dot(x: float, y: float) -> str:
    return f'  <circle cx="{x}" cy="{y}" r="1.6" fill="{INK}"/>\n'


def build() -> str:
    parts: list[str] = []
    add = parts.append

    add('<?xml version="1.0" encoding="UTF-8"?>\n')
    add(
        '<svg xmlns="http://www.w3.org/2000/svg" width="183mm" height="121mm"'
        ' viewBox="0 0 519 343" role="img">\n'
    )
    add("  <defs>\n")
    add(
        f'    <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5"'
        f' markerWidth="5" markerHeight="5" orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{INK}"/></marker>\n'
    )
    add("  </defs>\n")
    add(f'  <rect x="0" y="0" width="519" height="343" fill="{WHITE}"/>\n')

    # panel letter
    add('  <g id="t:panel">\n')
    add(text(4, 12, "a", F_TITLE, bold=True, anchor="start"))
    add("  </g>\n")

    # 1 instance -----------------------------------------------------------
    add('  <g id="n:instance">\n')
    add(box(169, 18, 180, 30, fill=WHITE))
    add(text(259, 32, "① 任务实例", F_LABEL))
    add(text(259, 43, "problem statement + repo", F_DETAIL))
    add("  </g>\n")
    add(arrow(259, 48, 259, 61))

    # 2 shared prefix ------------------------------------------------------
    add('  <g id="c:prefix">\n')
    add(box(8, 62, 503, 80, fill="none", stroke=GREY_LINE, width=0.9, rx=4))
    add(text(16, 76, "② 共享前缀（A / C / D / E 完全共用，同一预算）", F_TITLE,
              bold=True, anchor="start"))

    inner = [
        (24, 74, "索引", ["仓库清单"]),
        (106, 82, "定位 ×2", ["词法 + 模型"]),
        (196, 80, "读文件", ["受字符上限"]),
        (284, 76, "N 个候选", ["同一提示词"]),
        (368, 128, "逐候选校验", ["应用 · 语法", "公开测试"]),
    ]
    for x, w, title, details in inner:
        add(f'  <g id="n:prefix-{len(parts)}">\n')
        add(box(x, 84, w, 46, fill=GREY_FILL))
        add(text(x + w / 2, 101, title, F_LABEL))
        for i, line in enumerate(details):
            add(text(x + w / 2, 114 + i * 10, line, F_DETAIL))
        add("  </g>\n")
    add("  </g>\n")
    add(arrow(259, 142, 259, 157))

    # 3 decision point (the single accent) ---------------------------------
    add('  <g id="n:decision">\n')
    add(box(139, 158, 240, 42, fill=ACCENT_FILL, stroke=ACCENT, width=1.4))
    add(text(259, 175, "③ 决策点（每任务仅一次）", F_LABEL))
    add(text(259, 189, "可行候选数 · u_loc · u_dup · 行为信号 · 剩余预算", F_DETAIL))
    add("  </g>\n")

    # branch split ---------------------------------------------------------
    add(path("M 259 200 L 259 208", marker=None))
    add(dot(259, 208))
    add(path("M 155 208 L 363 208", marker=None))
    add(path("M 155 208 L 155 217"))
    add(path("M 363 208 L 363 217"))

    # 4a fixed continuation ------------------------------------------------
    add('  <g id="n:fixed">\n')
    add(box(55, 218, 200, 52, fill=GREY_FILL))
    add(text(155, 236, "④a 固定延续（A）", F_LABEL))
    add(text(155, 249, "继续生成候选，不调用工具", F_DETAIL))
    add(text(155, 260, "无反馈信号", F_DETAIL))
    add("  </g>\n")

    # 4b bounded interaction ----------------------------------------------
    add('  <g id="n:interactive">\n')
    add(box(263, 218, 200, 52, fill=GREY_FILL))
    add(text(363, 236, "④b 受限交互（本次实现）", F_LABEL))
    add(text(363, 249, "6 工具 · 4 状态 · 停滞 3 次", F_DETAIL))
    add(text(363, 260, "预算耗尽强制交出补丁", F_DETAIL))
    add("  </g>\n")

    # merge -----------------------------------------------------------------
    add(path("M 155 270 L 155 280", marker=None))
    add(path("M 363 270 L 363 280", marker=None))
    add(path("M 155 280 L 363 280", marker=None))
    add(dot(185, 280))
    add(path("M 185 280 L 185 289"))

    # 5 freeze --------------------------------------------------------------
    add('  <g id="n:freeze">\n')
    add(box(120, 290, 130, 26, fill=GREY_FILL))
    add(text(185, 306, "⑤ 冻结唯一候选", F_LABEL))
    add("  </g>\n")
    add(arrow(250, 303, 265, 303))

    # 6 grade ---------------------------------------------------------------
    add('  <g id="n:grade">\n')
    add(box(266, 290, 150, 26, fill=WHITE))
    add(text(341, 306, "⑥ 官方 harness 判分", F_LABEL))
    add("  </g>\n")
    add(text(341, 327, "resolved / unresolved", F_DETAIL))

    # footnote --------------------------------------------------------------
    add('  <g id="t:footnote">\n')
    add(text(
        8, 338,
        "设计示意，不含实测结果；阈值 0.50 与切换概率 0.50 为占位值，尚未校准。",
        F_DETAIL, anchor="start",
    ))
    add("  </g>\n")

    add("</svg>\n")
    return "".join(parts)


def main() -> int:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    svg = build()
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(svg)
    print(f"written: {OUT}  ({len(svg)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
