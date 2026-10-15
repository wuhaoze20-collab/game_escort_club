# -*- coding: utf-8 -*-
"""把 .drawio 渲染成 PNG 预览，并用真实字体度量做一次「文字是否超框」审计。

这是**校验用的工具**，不是交付物：交付物只有 .drawio 文件。
validate_drawio.py 用的是无依赖的文字宽度估算（子 Agent 也能跑）；
本脚本用 Pillow + 系统中文字体做像素级度量，结果更准，用来人工复核布局。

用法：
    python preview_drawio.py <文件或目录> [...]
输出：
    _src/preview/<文件名>__<页名>.png
"""

import os
import re
import sys
import math
import xml.etree.ElementTree as ET

sys.stdout.reconfigure(encoding="utf-8")

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

FONT_PATH = r"C:\Windows\Fonts\msyh.ttc"
FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "preview")

FS = 13
_font_cache = {}


def font(size=FS, bold=False):
    key = (size, bold)
    if key not in _font_cache:
        path = FONT_BOLD if bold else FONT_PATH
        _font_cache[key] = ImageFont.truetype(path, size)
    return _font_cache[key]


def unesc(v):
    """ET 已把 &lt;br&gt; 还原成 <br>，这里把它换回真正的换行。"""
    return (v or "").replace("<br>", "\n")


def style_get(style, key, default=None):
    m = re.search(r"(?:^|;)%s=([^;]*)" % re.escape(key), style or "")
    return m.group(1) if m else default


def _is_cjk(ch):
    """与 drawio_kit.text_width_units 同一口径：CJK 与全角标点可逐字断行。"""
    return ord(ch) > 0x2E7F


def _break_units(seg):
    """把一段文字拆成「可整段搬运的最小单位」：空格与 CJK 字符各自成单位，
    连续的半角字符（英文标识符、路径、数字）绑成一个整体。"""
    units, cur = [], ""
    for ch in seg:
        if ch == " " or _is_cjk(ch):
            if cur:
                units.append(cur)
                cur = ""
            units.append(ch)
        else:
            cur += ch
    if cur:
        units.append(cur)
    return units


def _split_long_run(run, f, max_px, out):
    """单个半角长串本身就超宽时，只能在串内部断开（draw.io 同样会这么做）。"""
    while f.getlength(run) > max_px and len(run) > 1:
        k = 1
        while k < len(run) and f.getlength(run[:k + 1]) <= max_px:
            k += 1
        out.append(run[:k])
        run = run[k:]
    return run


def wrap_px(text, f, max_px):
    """按真实像素宽度折行，模拟 draw.io（mxText）的断行规则：

    - 只在**空格**与 **CJK 字符**处断行，绝不会把英文标识符拦腰截断；
    - 只有当某个半角长串自身就宽于一行时才在串内强制断开。
    这比逐字符贪心更接近真实渲染，折出的行数只多不少，
    因此用它做「是否超框」审计是更严的下界。
    """
    out = []
    for seg in text.split("\n"):
        if not seg:
            out.append("")
            continue
        line = ""
        for u in _break_units(seg):
            if u == " " and not line:
                continue
            if not line or f.getlength(line + u) <= max_px:
                line += u
                continue
            if line.strip():
                out.append(line.rstrip())
                line = ""
                if u == " ":
                    continue
                line = u
            else:
                line = u
            line = _split_long_run(line, f, max_px, out)
        if line.strip():
            out.append(line.rstrip())
        elif not out or out[-1] != "":
            pass
    return out if out else [""]


def draw_text_block(d, box, text, f, color, align="center", valign="middle",
                    pad=8):
    x, y, w, h = box
    lines = wrap_px(text, f, max(10, w - 2 * pad))
    lh = f.size + 5
    total = len(lines) * lh
    if valign == "top":
        ty = y + pad
    elif valign == "middle":
        ty = y + (h - total) / 2.0
    else:
        ty = y + h - total - pad
    for i, ln in enumerate(lines):
        tw = f.getlength(ln)
        if align == "left":
            tx = x + pad
        elif align == "right":
            tx = x + w - pad - tw
        else:
            tx = x + (w - tw) / 2.0
        d.text((tx, ty + i * lh), ln, font=f, fill=color)
    return total


def shape_points(kind_shape, x, y, w, h):
    if kind_shape == "rhombus":
        return [(x + w / 2, y), (x + w, y + h / 2), (x + w / 2, y + h), (x, y + h / 2)]
    if kind_shape == "parallelogram":
        s = min(0.18 * w, 26)
        return [(x + s, y), (x + w, y), (x + w - s, y + h), (x, y + h)]
    return None


def edge_point(rect, toward, anchor=None):
    """rect=(x,y,w,h)；anchor=(ax, ay) 为 0~1 比例，否则用指向 toward 的交点。"""
    x, y, w, h = rect
    if anchor:
        return (x + anchor[0] * w, y + anchor[1] * h)
    cx, cy = x + w / 2.0, y + h / 2.0
    dx, dy = toward[0] - cx, toward[1] - cy
    if dx == 0 and dy == 0:
        return (cx, cy)
    sx = (w / 2.0) / abs(dx) if dx else float("inf")
    sy = (h / 2.0) / abs(dy) if dy else float("inf")
    s = min(sx, sy)
    return (cx + dx * s, cy + dy * s)


def arrow(d, p_from, p_to, color, dashed=False):
    (x1, y1), (x2, y2) = p_from, p_to
    if dashed:
        # 简单虚线
        total = math.hypot(x2 - x1, y2 - y1)
        if total < 1:
            return
        step, on = 7.0, True
        t = 0.0
        while t < total:
            t2 = min(t + step, total)
            if on:
                a = (x1 + (x2 - x1) * t / total, y1 + (y2 - y1) * t / total)
                b = (x1 + (x2 - x1) * t2 / total, y1 + (y2 - y1) * t2 / total)
                d.line([a, b], fill=color, width=1)
            on = not on
            t = t2
    else:
        d.line([p_from, p_to], fill=color, width=1)
    # 箭头
    ang = math.atan2(y2 - y1, x2 - x1)
    L, W = 9, 4
    for sign in (1, -1):
        d.line([(x2, y2),
                (x2 - L * math.cos(ang) + sign * W * math.sin(ang),
                 y2 - L * math.sin(ang) - sign * W * math.cos(ang))],
               fill=color, width=1)


def render_page(diag, out_png):
    model = diag.find("mxGraphModel")
    if model is None:
        return None, "缺少 mxGraphModel"
    pw = float(model.get("pageWidth") or 1000)
    ph = float(model.get("pageHeight") or 800)

    cells = model.findall(".//mxCell")
    vertices, edges = [], []
    for c in cells:
        cid = c.get("id")
        if cid in ("0", "1"):
            continue
        g = c.find("mxGeometry")
        if c.get("edge") == "1":
            edges.append(c)
            continue
        if g is None:
            continue
        x = float(g.get("x") or 0)
        y = float(g.get("y") or 0)
        w = float(g.get("width") or 0)
        h = float(g.get("height") or 0)
        vertices.append((cid, c, (x, y, w, h)))

    W = int(math.ceil(pw)) + 1
    H = int(math.ceil(ph)) + 1
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    vmap = {cid: (c, r) for cid, c, r in vertices}

    # 1) 容器 / 分组框
    for cid, c, (x, y, w, h) in vertices:
        style = c.get("style") or ""
        if "fillColor=none" in style and "dashed=1" in style:
            d.rectangle([x, y, x + w, y + h], outline="#B3B3B3")
            # 虚线效果：手工描一遍短划
            for x0 in range(int(x), int(x + w), 8):
                d.line([(x0, y), (min(x0 + 4, x + w), y)], fill="#B3B3B3")
                d.line([(x0, y + h), (min(x0 + 4, x + w), y + h)], fill="#B3B3B3")
            for y0 in range(int(y), int(y + h), 8):
                d.line([(x, y0), (x, min(y0 + 4, y + h))], fill="#B3B3B3")
                d.line([(x + w, y0), (x + w, min(y0 + 4, y + h))], fill="#B3B3B3")
            draw_text_block(d, (x + 8, y + 2, w - 16, 22),
                            unesc(c.get("value")),
                            font(FS, True), "#595959", align="left", valign="top",
                            pad=0)

    # 2) 连线
    for e in edges:
        style = e.get("style") or ""
        s, t = e.get("source"), e.get("target")
        if s not in vmap or t not in vmap:
            continue
        sc, sr = vmap[s]
        tc, tr = vmap[t]
        exit_a = None
        if style_get(style, "exitX") is not None:
            exit_a = (float(style_get(style, "exitX")), float(style_get(style, "exitY", 0.5)))
        entry_a = None
        if style_get(style, "entryX") is not None:
            entry_a = (float(style_get(style, "entryX")), float(style_get(style, "entryY", 0.5)))
        scenter = (sr[0] + sr[2] / 2.0, sr[1] + sr[3] / 2.0)
        tcenter = (tr[0] + tr[2] / 2.0, tr[1] + tr[3] / 2.0)
        p1 = edge_point(sr, tcenter, exit_a)
        p2 = edge_point(tr, scenter, entry_a)
        dashed = "dashed=1" in style
        color = style_get(style, "strokeColor", "#666666")
        if abs(p2[0] - p1[0]) >= abs(p2[1] - p1[1]):
            mx = (p1[0] + p2[0]) / 2.0
            pts = [p1, (mx, p1[1]), (mx, p2[1]), p2]
        else:
            my = (p1[1] + p2[1]) / 2.0
            pts = [p1, (p1[0], my), (p2[0], my), p2]
        for i in range(len(pts) - 1):
            arrow(d, pts[i], pts[i + 1], color, dashed=(dashed and i == len(pts) - 2))
        lbl = unesc(e.get("value"))
        if lbl:
            mid = pts[len(pts) // 2 - 1]
            mid2 = pts[len(pts) // 2]
            lx = (mid[0] + mid2[0]) / 2.0
            ly = (mid[1] + mid2[1]) / 2.0
            f = font(11)
            tw = f.getlength(lbl)
            d.rectangle([lx - tw / 2 - 3, ly - 8, lx + tw / 2 + 3, ly + 8], fill="white")
            d.text((lx - tw / 2, ly - 7), lbl, font=f, fill="#333333")

    # 3) 节点
    audits = []
    for cid, c, (x, y, w, h) in vertices:
        style = c.get("style") or ""
        val = unesc(c.get("value"))
        base = style.split(";")[0]
        if "fillColor=none" in style and "dashed=1" in style:
            continue
        fill = style_get(style, "fillColor", "#DAE8FC")
        stroke = style_get(style, "strokeColor", "#6C8EBF")
        fs = int(style_get(style, "fontSize", FS) or FS)
        pad = 30 if "parallelogram" in style else 8
        align = style_get(style, "align", "center") or "center"
        valign = style_get(style, "verticalAlign", "middle") or "middle"
        if style.startswith("text;"):
            draw_text_block(d, (x, y, w, h), val, font(fs, True), "#1F2937",
                            align=align, valign=valign, pad=0)
            continue
        if "ellipse" in base or "ellipse" in style:
            d.ellipse([x, y, x + w, y + h], fill=fill, outline=stroke)
        elif "cylinder3" in style:
            ry = min(12, h / 4.0)
            d.rectangle([x, y + ry / 2, x + w, y + h - ry / 2], fill=fill, outline=stroke)
            d.ellipse([x, y, x + w, y + ry * 2], fill=fill, outline=stroke)
            d.arc([x, y + h - ry * 2, x + w, y + h], 0, 180, fill=stroke)
            d.line([(x, y + h - ry), (x, y + ry)], fill=stroke)
            d.line([(x + w, y + h - ry), (x + w, y + ry)], fill=stroke)
            draw_text_block(d, (x, y + ry, w, h - ry * 1.5), val, font(fs),
                            style_get(style, "fontColor", "#333333"), align, valign, pad)
            continue
        elif "rhombus" in style:
            d.polygon([(x + w / 2, y), (x + w, y + h / 2), (x + w / 2, y + h), (x, y + h / 2)],
                      fill=fill, outline=stroke)
        elif "parallelogram" in style:
            s = min(0.18 * w, 26)
            d.polygon([(x + s, y), (x + w, y), (x + w - s, y + h), (x, y + h)],
                      fill=fill, outline=stroke)
        elif "shape=note" in style:
            d.polygon([(x, y), (x + w - 14, y), (x + w, y + 14), (x + w, y + h), (x, y + h)],
                      fill=fill, outline=stroke)
            d.line([(x + w - 14, y), (x + w - 14, y + 14), (x + w, y + 14)], fill=stroke)
        elif "rounded=1" in style:
            try:
                d.rounded_rectangle([x, y, x + w, y + h], radius=8, fill=fill, outline=stroke)
            except Exception:
                d.rectangle([x, y, x + w, y + h], fill=fill, outline=stroke)
        else:
            d.rectangle([x, y, x + w, y + h], fill=fill, outline=stroke)
        used = draw_text_block(d, (x, y, w, h), val, font(fs),
                              style_get(style, "fontColor", "#333333"),
                              align=align, valign=valign, pad=pad)
        # 真实度量：文字需要的高度 vs 实际高度
        if val.strip():
            need_lines = len(wrap_px(val, font(fs), max(10, w - 2 * pad)))
            need_h = need_lines * (fs + 5)
            if need_h > h - 6:
                audits.append((cid, val.split("\n")[0][:26], int(need_h), int(h)))

    img.save(out_png)
    return W, H, audits


def main(argv):
    targets = argv[1:]
    files = []
    for t in targets:
        if os.path.isdir(t):
            files += [os.path.join(t, n) for n in sorted(os.listdir(t))
                      if n.lower().endswith(".drawio")]
        else:
            files.append(t)
    os.makedirs(OUT_DIR, exist_ok=True)
    for f in files:
        base = os.path.splitext(os.path.basename(f))[0]
        data = open(f, "rb").read().decode("utf-8")
        root = ET.fromstring(data)
        for diag in root.findall("diagram"):
            page = diag.get("name") or "page"
            slug = re.sub(r'[\\/:*?"<>|]', "_", page)[:40]
            out = os.path.join(OUT_DIR, "%s__%s.png" % (base, slug))
            res = render_page(diag, out)
            if res and res[0]:
                W, H, audits = res
                print("%s -> %dx%d" % (os.path.basename(out), W, H))
                for cid, head, need, have in audits:
                    print("   [可能超框] %s（%s…）需要约 %dpx，实给 %dpx" % (cid, head, need, have))
            else:
                print("%s -> 渲染失败：%s" % (base, res[1] if res else "?"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
