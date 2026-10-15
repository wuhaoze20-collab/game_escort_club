# -*- coding: utf-8 -*-
"""drawio_kit —— 本项目流程图（.drawio / mxGraphModel XML）统一生成工具。

设计目标
--------
1. 全项目同一套视觉规范：配色、圆角、字号、箭头、分组框都集中在这里，
   任何一张图都用同一批 kind，观感一致。
2. 生成的 XML 一定合法：id 统一登记（重复即报错）、文本统一转义，
   不会出现重复 id、未转义字符、断掉的 source/target。
3. 输出**不压缩**：直接写 <mxGraphModel>，draw.io 打开即可编辑。

用法
----
    from drawio_kit import Page, write_drawio, place

    p = Page("页名")
    p.node("n1", "开始", 40, 40, 180, 56, kind="start")
    p.node("n2", "处理", 280, 40, 200, 60, kind="process")
    p.edge("n1", "n2", "下一步")
    write_drawio(r"...\\out.drawio", [p])

坐标与尺寸都是像素，x 向右、y 向下，原点在画布左上角。
"""

import math
from xml.sax.saxutils import escape

# ——————————————————————————————————————————————
# 视觉规范（全项目统一，改这里 = 改所有图）
# ——————————————————————————————————————————————

FONT = "Microsoft YaHei"   # 中文字体
FS = 13                    # 节点字号
EFS = 12                   # 连线标签字号
FONT_COLOR = "#333333"
EDGE_COLOR = "#666666"

# kind -> (填充色, 描边色, 形状样式前缀)
KINDS = {
    "start":    ("#D5E8D4", "#82B366", "ellipse"),
    "end":      ("#D5E8D4", "#82B366", "ellipse"),
    "process":  ("#DAE8FC", "#6C8EBF", "rounded=1;arcSize=10"),
    "step":     ("#DAE8FC", "#6C8EBF", "rounded=1;arcSize=10"),
    "decision": ("#FFE6CC", "#D79B00", "rhombus"),
    "io":       ("#FFF2CC", "#D6B656",
                 "shape=parallelogram;perimeter=parallelogramPerimeter;fixedSize=1"),
    "data":     ("#F5F5F5", "#666666",
                 "shape=cylinder3;boundedLbl=1;backgroundOutline=1;size=12"),
    "external": ("#B0E3E6", "#0E8088", "rounded=1;arcSize=10"),
    "error":    ("#F8CECC", "#B85450", "rounded=1;arcSize=10"),
    "note":     ("#FFFFFF", "#999999", "shape=note;size=14"),
    "label":    ("none", "none", "text"),
}

# 视觉上算“终点”（没有出边也不算断头路）的 kind
TERMINAL_KINDS = ("start", "end", "data", "note", "label")


def text_width_units(s, font=FS):
    """粗略估算一段文字占多少个“字号宽度”单位（中文按 1.0，英文按约 0.55）。"""
    w = 0.0
    for ch in s:
        o = ord(ch)
        if o > 0x2E7F:            # CJK / 全角标点
            w += 1.0
        elif ch in "iljI.,;:'!|`":
            w += 0.30
        elif ch in "mwMW@%":
            w += 0.85
        elif ch.isupper():
            w += 0.68
        else:
            w += 0.55
    return w


def auto_height(text, width, font=FS, pad=18, line_gap=8):
    """按文字长度估算所需高度，避免文字被框截断。"""
    avail = max(24.0, width - pad)
    lines = 0
    for seg in str(text).split("\n"):
        need = text_width_units(seg, font) * font
        lines += max(1, int(math.ceil(need / avail)))
    return max(44, int(lines * (font + line_gap) + pad))


def place(x0, y0, col_w, row_h, cols, i):
    """网格定位：第 i 个元素的 (x, y)。"""
    return x0 + (i % cols) * col_w, y0 + (i // cols) * row_h


def _esc(text):
    """转义 XML，并把换行变成 html 换行（节点 style 里统一开了 html=1）。

    注意：换行必须写成 &lt;br&gt; 而不是 <br> —— 属性值里出现裸的 '<'
    会让 XML 直接解析失败。draw.io 读到 &lt;br&gt; 后会按 html=1 渲染成换行。
    """
    return escape(str(text)).replace("\n", "&lt;br&gt;")


class Page(object):
    """一张图（draw.io 的一个 <diagram> 页）。"""

    def __init__(self, name):
        self.name = name
        self._cells = []       # 已渲染的 mxCell XML 片段
        self._ids = set()
        self._geom = {}        # id -> (x, y, w, h, kind_string)
        self._edges = []       # (id, src, dst)
        self._nedge = 0

    # ——— 内部 ———
    def _reg(self, nid):
        if nid in self._ids:
            raise ValueError("重复的 id：%s" % nid)
        self._ids.add(nid)
        return nid

    # ——— 节点 ———
    def node(self, nid, text, x, y, w=200, h=None, kind="process", font=None,
             align="center", valign="middle", bold=False, dashed=False,
             fill=None, stroke=None):
        """画一个节点。h 传 None 时按文字自动估算高度。"""
        if kind not in KINDS:
            raise ValueError("未知 kind：%s" % kind)
        self._reg(nid)
        f = font or FS
        fill_c, stroke_c, base = KINDS[kind]
        if fill:
            fill_c = fill
        if stroke:
            stroke_c = stroke
        if h is None:
            pad = 30 if kind == "io" else 18
            h = auto_height(text, w, f, pad=pad)
        style = ("%s;whiteSpace=wrap;html=1;fillColor=%s;strokeColor=%s;strokeWidth=1;"
                 "fontSize=%d;fontFamily=%s;fontColor=%s;align=%s;verticalAlign=%s;"
                 % (base, fill_c, stroke_c, f, FONT, FONT_COLOR, align, valign))
        if bold:
            style += "fontStyle=1;"
        if dashed:
            style += "dashed=1;"
        self._geom[nid] = (x, y, w, h, kind)
        self._cells.append(
            '<mxCell id="%s" value="%s" style="%s" vertex="1" parent="1">'
            '<mxGeometry x="%s" y="%s" width="%s" height="%s" as="geometry"/></mxCell>'
            % (nid, _esc(text), style, x, y, w, h))
        return nid

    def group(self, gid, title, x, y, w, h, dashed=True):
        """画一个分组框 / 泳道底框（虚线、无填充、标题在左上角）。"""
        self._reg(gid)
        style = ("rounded=0;whiteSpace=wrap;html=1;fillColor=none;strokeColor=#B3B3B3;"
                 "strokeWidth=1;fontSize=%d;fontFamily=%s;fontColor=#595959;"
                 "align=left;verticalAlign=top;spacingLeft=10;spacingTop=6;fontStyle=1;"
                 % (FS, FONT))
        if dashed:
            style += "dashed=1;"
        self._geom[gid] = (x, y, w, h, "group")
        self._cells.append(
            '<mxCell id="%s" value="%s" style="%s" vertex="1" parent="1">'
            '<mxGeometry x="%s" y="%s" width="%s" height="%s" as="geometry"/></mxCell>'
            % (gid, _esc(title), style, x, y, w, h))
        return gid

    def label(self, nid, text, x, y, w=400, h=30, font=None, bold=False,
              align="left"):
        """纯文字标题 / 注释文字（无边框）。"""
        self._reg(nid)
        f = font or FS + 2
        style = ("text;whiteSpace=wrap;html=1;strokeColor=none;fillColor=none;"
                 "fontSize=%d;fontFamily=%s;fontColor=#1F2937;align=%s;"
                 "verticalAlign=middle;" % (f, FONT, align))
        if bold:
            style += "fontStyle=1;"
        self._geom[nid] = (x, y, w, h, "label")
        self._cells.append(
            '<mxCell id="%s" value="%s" style="%s" vertex="1" parent="1">'
            '<mxGeometry x="%s" y="%s" width="%s" height="%s" as="geometry"/></mxCell>'
            % (nid, _esc(text), style, x, y, w, h))
        return nid

    # ——— 连线 ———
    def edge(self, src, dst, label="", dashed=False, exit_x=None, exit_y=None,
             entry_x=None, entry_y=None, color=EDGE_COLOR, arrow="blockThin",
             label_bg="#FFFFFF"):
        """画一条带箭头的连线。exit_x/entry_x 用 0~1 的锚点比例（0.5 = 中点）。"""
        self._nedge += 1
        eid = "e%d" % self._nedge
        self._reg(eid)
        style = ("edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;endArrow=%s;endFill=1;"
                 "strokeColor=%s;strokeWidth=1;fontSize=%d;fontFamily=%s;"
                 "fontColor=%s;labelBackgroundColor=%s;jumpStyle=arc;"
                 % (arrow, color, EFS, FONT, FONT_COLOR, label_bg))
        if dashed:
            style += "dashed=1;"
        if exit_x is not None and exit_y is not None:
            style += "exitX=%s;exitY=%s;exitDx=0;exitDy=0;" % (exit_x, exit_y)
        if entry_x is not None and entry_y is not None:
            style += "entryX=%s;entryY=%s;entryDx=0;entryDy=0;" % (entry_x, entry_y)
        self._cells.append(
            '<mxCell id="%s" value="%s" style="%s" edge="1" parent="1" '
            'source="%s" target="%s">'
            '<mxGeometry relative="1" as="geometry"/></mxCell>'
            % (eid, _esc(label), style, src, dst))
        self._edges.append((eid, src, dst))
        return eid

    def chain(self, ids, labels=None, **kw):
        """把一串 id 依次连成一条链。labels 可给 len(ids)-1 个标签。"""
        labels = labels or []
        out = []
        for i in range(len(ids) - 1):
            lbl = labels[i] if i < len(labels) else ""
            out.append(self.edge(ids[i], ids[i + 1], lbl, **kw))
        return out

    # ——— 输出 ———
    def render(self, index=0):
        xs = [g[0] + g[2] for g in self._geom.values()]
        ys = [g[1] + g[3] for g in self._geom.values()]
        pw = int(max(xs + [830]) + 40)
        ph = int(max(ys + [600]) + 40)
        pw = int(math.ceil(pw / 10.0) * 10)
        ph = int(math.ceil(ph / 10.0) * 10)
        head = ('<diagram id="page%d" name="%s">\n'
                '  <mxGraphModel dx="1200" dy="900" grid="1" gridSize="10" guides="1" '
                'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
                'pageWidth="%d" pageHeight="%d" math="0" shadow="0">\n'
                '    <root>\n'
                '      <mxCell id="0"/>\n'
                '      <mxCell id="1" parent="0"/>\n'
                % (index + 1, _esc(self.name), pw, ph))
        body = "\n".join("      " + c for c in self._cells)
        tail = ('\n    </root>\n  </mxGraphModel>\n</diagram>')
        return head + body + tail


def write_drawio(path, pages, host="app.diagrams.net"):
    """把若干 Page 写成一个 .drawio 文件（未压缩）。"""
    body = "\n".join(p.render(i) for i, p in enumerate(pages))
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<mxfile host="%s" agent="drawio_kit" version="24.7.17" type="device">\n'
           '%s\n</mxfile>\n' % (host, body))
    with open(path, "w", encoding="utf-8", newline="\n") as fp:
        fp.write(xml)
    return path
