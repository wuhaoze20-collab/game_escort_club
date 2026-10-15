# -*- coding: utf-8 -*-
"""扫描所有 .drawio：连线走线是否穿过「无关节点」的方框。

无法在本机跑 draw.io 真渲染，所以这里用 preview_drawio 的同一套
「正交折线近似」几何来取样判定：把每条连线拆成若干段，沿线逐点采样，
若采样点落进某个既非起点也非终点的节点矩形内，就报出来。

这会抓到「箭头穿过别的方框」这类只有渲染才看得见的缺陷。
"""

import glob
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import preview_drawio as pv  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

DRAWIO = r"C:\Users\18642\game_escort_club\docs\flowcharts\drawio"


def rect_contains(r, p, margin=1.0):
    x, y, w, h = r
    return (x + margin) < p[0] < (x + w - margin) and (y + margin) < p[1] < (y + h - margin)


def route_points(sr, tr, exit_a, entry_a):
    scenter = (sr[0] + sr[2] / 2.0, sr[1] + sr[3] / 2.0)
    tcenter = (tr[0] + tr[2] / 2.0, tr[1] + tr[3] / 2.0)
    p1 = pv.edge_point(sr, tcenter, exit_a)
    p2 = pv.edge_point(tr, scenter, entry_a)
    if abs(p2[0] - p1[0]) >= abs(p2[1] - p1[1]):
        mx = (p1[0] + p2[0]) / 2.0
        return [p1, (mx, p1[1]), (mx, p2[1]), p2]
    my = (p1[1] + p2[1]) / 2.0
    return [p1, (p1[0], my), (p2[0], my), p2]


total = 0
for f in sorted(glob.glob(os.path.join(DRAWIO, "*.drawio"))):
    root = ET.fromstring(open(f, "rb").read().decode("utf-8"))
    print("=" * 72)
    print(os.path.basename(f))
    for diag in root.findall("diagram"):
        model = diag.find("mxGraphModel")
        if model is None:
            continue
        verts = {}
        edges = []
        for c in model.findall(".//mxCell"):
            cid = c.get("id")
            if cid in ("0", "1"):
                continue
            g = c.find("mxGeometry")
            if g is None:
                continue
            r = (float(g.get("x") or 0), float(g.get("y") or 0),
                 float(g.get("width") or 0), float(g.get("height") or 0))
            if c.get("edge") == "1":
                edges.append((cid, c, r))
            else:
                verts[cid] = (c, r)
        hits = []
        for eid, e, er in edges:
            s, t = e.get("source"), e.get("target")
            if s not in verts or t not in verts:
                continue
            style = e.get("style") or ""
            exit_a = entry_a = None
            if pv.style_get(style, "exitX") is not None:
                exit_a = (float(pv.style_get(style, "exitX")),
                          float(pv.style_get(style, "exitY", 0.5)))
            if pv.style_get(style, "entryX") is not None:
                entry_a = (float(pv.style_get(style, "entryX")),
                           float(pv.style_get(style, "entryY", 0.5)))
            pts = route_points(verts[s][1], verts[t][1], exit_a, entry_a)
            # 沿线采样
            samples = []
            for i in range(len(pts) - 1):
                a, b = pts[i], pts[i + 1]
                n = max(2, int(max(abs(b[0] - a[0]), abs(b[1] - a[1])) / 4) + 1)
                for k in range(n + 1):
                    samples.append((a[0] + (b[0] - a[0]) * k / n,
                                    a[1] + (b[1] - a[1]) * k / n))
            for oid, (oc, orr) in verts.items():
                if oid in (s, t):
                    continue
                ost = oc.get("style") or ""
                # 跳过纯分组底框与无填充的装饰框（穿过它们是正常的）
                if "fillColor=none" in ost:
                    continue
                if ost.startswith("text;"):
                    continue
                if any(rect_contains(orr, p) for p in samples):
                    hits.append((eid, s, t, oid))
        if hits:
            total += len(hits)
            for eid, s, t, oid in hits:
                print("   [页 %s] 连线 %s（%s -> %s）穿过节点 %s"
                      % (diag.get("name"), eid, s, t, oid))
        else:
            print("   页「%s」：无连线穿过无关节点" % diag.get("name"))

print()
print("全项目：连线穿框 %d 处" % total)
