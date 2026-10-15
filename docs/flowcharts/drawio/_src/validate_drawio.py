# -*- coding: utf-8 -*-
"""校验 .drawio 流程图：结构合法性 + 断头路 + 文字溢出风险 + 节点重叠。

用法：
    python validate_drawio.py <文件或目录> [更多文件...]

检查项：
  1. XML 能被 xml.etree.ElementTree 解析（不是“文件存在”即通过）
  2. 每页 <mxCell> 的 id 唯一
  3. 每个 parent / source / target 指向的 id 真实存在
  4. 连线两端都存在，且没有自环
  5. 除了终点类节点（椭圆 / 圆柱 / note / 纯文字 / 分组框），其余节点必须有出边
     —— 即“没有断头路”
  6. 顶点文字非空；文字估算高度 > 给定高度时提示可能截断
  7. 任意两个实心节点矩形重叠面积超过较小者 25% 时告警
  8. 文件为 UTF-8，且不含 U+FFFD 替换字符（乱码检测）
"""

import os
import sys
import math
import xml.etree.ElementTree as ET

sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from drawio_kit import text_width_units, FS  # noqa: E402

TERMINAL_STYLE_TOKENS = ("ellipse", "cylinder3", "shape=note", "text;")


def _is_container(style):
    return "fillColor=none" in style and "dashed=1" in style


def _is_label(style):
    return style.startswith("text;")


def _is_terminal(style):
    return any(t in style for t in TERMINAL_STYLE_TOKENS)


def _dim(cell):
    g = cell.find("mxGeometry")
    if g is None:
        return None
    try:
        return (float(g.get("x") or 0), float(g.get("y") or 0),
                float(g.get("width") or 0), float(g.get("height") or 0))
    except ValueError:
        return None


def check_file(path):
    problems = []
    warnings = []
    stats = []

    raw = open(path, "rb").read()
    if raw.startswith(b"\xef\xbb\xbf"):
        warnings.append("文件带 UTF-8 BOM（draw.io 可读，但建议去掉）")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        problems.append("不是合法 UTF-8：%s" % e)
        return problems, warnings, stats
    if "\ufffd" in text:
        problems.append("检测到 U+FFFD 替换字符，存在乱码")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        problems.append("XML 解析失败：%s" % e)
        return problems, warnings, stats

    if root.tag != "mxfile":
        warnings.append("根元素是 <%s>，通常应为 <mxfile>" % root.tag)

    diagrams = root.findall("diagram")
    if not diagrams:
        problems.append("没有任何 <diagram> 页")
        return problems, warnings, stats

    for diag in diagrams:
        page = diag.get("name") or diag.get("id") or "?"
        model = diag.find("mxGraphModel")
        if model is None:
            problems.append("[%s] 缺少 <mxGraphModel>" % page)
            continue
        if model.get("compressed") == "true":
            problems.append("[%s] 是压缩格式，无法校验" % page)
            continue

        cells = model.findall(".//mxCell")
        ids = {}
        for c in cells:
            cid = c.get("id")
            if cid is None:
                problems.append("[%s] 有 mxCell 缺少 id" % page)
                continue
            if cid in ids:
                problems.append("[%s] id 重复：%s" % (page, cid))
            ids[cid] = c

        vertices, edges = [], []
        for cid, c in ids.items():
            if c.get("edge") == "1":
                edges.append((cid, c))
            elif c.get("vertex") == "1":
                vertices.append((cid, c))

        for cid, c in ids.items():
            p = c.get("parent")
            if p is not None and p not in ids:
                problems.append("[%s] %s 的 parent=%s 不存在" % (page, cid, p))
        for eid, c in edges:
            s, t = c.get("source"), c.get("target")
            if s is None or t is None:
                problems.append("[%s] 连线 %s 缺少 source/target" % (page, eid))
                continue
            if s not in ids:
                problems.append("[%s] 连线 %s 的 source=%s 不存在" % (page, eid, s))
            if t not in ids:
                problems.append("[%s] 连线 %s 的 target=%s 不存在" % (page, eid, t))
            if s == t:
                problems.append("[%s] 连线 %s 是自环" % (page, eid))

        outs = {}
        for eid, c in edges:
            outs.setdefault(c.get("source"), 0)
            outs[c.get("source")] += 1

        solids = []
        for cid, c in vertices:
            style = c.get("style") or ""
            val = (c.get("value") or "").strip()
            if _is_container(style) or _is_label(style):
                continue
            if not val:
                warnings.append("[%s] 节点 %s 文字为空" % (page, cid))
            if not _is_terminal(style) and outs.get(cid, 0) == 0:
                problems.append("[%s] 断头路：节点 %s（%s）没有出边"
                                % (page, cid, val[:24]))
            d = _dim(c)
            if d:
                x, y, w, h = d
                if _is_terminal(style) and "ellipse" not in style \
                        and "cylinder3" not in style and "shape=note" not in style:
                    pass
                # 文字溢出粗判（仅对非形状特殊的节点）
                if "rhombus" not in style:
                    need = 0
                    pad = 30 if "parallelogram" in style else 18
                    avail = max(24.0, w - pad)
                    for seg in val.replace("<br>", "\n").split("\n"):
                        need += max(1, int(math.ceil(
                            text_width_units(seg, FS) * FS / avail)))
                    need_h = need * (FS + 8) + pad
                    if need_h > h * 1.35 and need > 1:
                        warnings.append("[%s] 节点 %s 文字可能超框（估需 %.0f，实给 %.0f）"
                                        % (page, cid, need_h, h))
                solids.append((cid, x, y, w, h, val))

        for i in range(len(solids)):
            for j in range(i + 1, len(solids)):
                a, b = solids[i], solids[j]
                ox = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
                oy = min(a[2] + a[4], b[2] + b[4]) - max(a[2], b[2])
                if ox > 0 and oy > 0:
                    inter = ox * oy
                    small = min(a[3] * a[4], b[3] * b[4])
                    if small > 0 and inter / small > 0.25:
                        warnings.append("[%s] 节点重叠：%s（%s） ↔ %s（%s）"
                                        % (page, a[0], a[5][:14], b[0], b[5][:14]))

        stats.append((page, len(vertices), len(edges)))

    return problems, warnings, stats


def collect(targets):
    files = []
    for t in targets:
        if os.path.isdir(t):
            for name in sorted(os.listdir(t)):
                if name.lower().endswith(".drawio"):
                    files.append(os.path.join(t, name))
        else:
            files.append(t)
    return files


def main(argv):
    files = collect(argv[1:])
    if not files:
        print("没有找到 .drawio 文件")
        return 2
    bad = 0
    for f in files:
        problems, warnings, stats = check_file(f)
        print("=" * 68)
        print("文件：%s" % f)
        for page, nv, ne in stats:
            print("  页「%s」：节点 %d 个，连线 %d 条" % (page, nv, ne))
        for w in warnings:
            print("  [警告] %s" % w)
        for p in problems:
            print("  [错误] %s" % p)
        if problems:
            bad += 1
            print("  结果：不通过")
        else:
            print("  结果：通过")
    print("=" * 68)
    print("共 %d 个文件，%d 个未通过" % (len(files), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
