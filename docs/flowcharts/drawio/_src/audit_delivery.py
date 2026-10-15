# -*- coding: utf-8 -*-
"""交付物独立审计：逐个 .drawio 做结构/编码/压缩方式检查，并核对旧产物未被改动。

用法：python audit_delivery.py
"""

import glob
import os
import re
import sys
import xml.etree.ElementTree as ET

sys.stdout.reconfigure(encoding="utf-8")

ROOT = r"C:\Users\18642\game_escort_club\docs\flowcharts"
DRAWIO = os.path.join(ROOT, "drawio")
SRC = os.path.join(DRAWIO, "_src")

PROTECTED = [
    os.path.join(ROOT, "advance-rag.html"),
    os.path.join(ROOT, "advance-rag-flow.png"),
    os.path.join(ROOT, "graph-rag.html"),
    os.path.join(ROOT, "graph-rag-flow.png"),
]

print("=" * 74)
print("一、逐个 .drawio 结构 / 编码 / 压缩方式")
print("=" * 74)
total_pages = 0
for f in sorted(glob.glob(os.path.join(DRAWIO, "*.drawio"))):
    raw = open(f, "rb").read()
    name = os.path.basename(f)
    try:
        txt = raw.decode("utf-8")
        enc = "UTF-8"
    except UnicodeDecodeError as e:
        print("%-34s  非 UTF-8：%s" % (name, e))
        continue
    bom = "有BOM" if raw.startswith(b"\xef\xbb\xbf") else "无BOM"
    bad = "有U+FFFD" if "\ufffd" in txt else "无乱码"
    try:
        root = ET.fromstring(txt)
        parsed = "解析通过"
    except ET.ParseError as e:
        print("%-34s  XML 解析失败：%s" % (name, e))
        continue
    if root.tag != "mxfile":
        print("%-34s  根元素不是 mxfile" % name)
    models = [d.find("mxGraphModel") for d in root.findall("diagram")]
    comp = any(m is not None and m.get("compressed") == "true" for m in models)
    rawattr = [m.get("compressed") for m in models if m is not None]
    pages = len(root.findall("diagram"))
    total_pages += pages
    # 抽查：每页第一个非空 value 是否含追溯信息
    print("%-34s %7d B  %s  %s  %s  %s  页数=%d"
          % (name, len(raw), enc, bom, bad,
             "压缩(不合格)" if comp else "未压缩", pages))
    print("       compressed 属性值：%s" % (rawattr,))
print("合计页数：%d" % total_pages)

print()
print("=" * 74)
print("二、每页标题栏是否带「代码依据」追溯信息")
print("=" * 74)
for f in sorted(glob.glob(os.path.join(DRAWIO, "*.drawio"))):
    root = ET.fromstring(open(f, "rb").read().decode("utf-8"))
    for d in root.findall("diagram"):
        vals = [c.get("value") or "" for c in d.findall(".//mxCell")]
        hit = [v for v in vals if "依据" in v]
        print("%-32s | %-40s | %s"
              % (os.path.basename(f), d.get("name"), "有依据标注" if hit else "**缺依据标注**"))

print()
print("=" * 74)
print("三、受保护旧产物是否被改动（看修改时间）")
print("=" * 74)
for p in PROTECTED:
    if os.path.exists(p):
        import datetime
        t = datetime.datetime.fromtimestamp(os.path.getmtime(p))
        print("%-32s 最后修改 %s" % (os.path.basename(p), t.strftime("%Y-%m-%d %H:%M:%S")))
    else:
        print("%-32s **缺失**" % os.path.basename(p))

print()
print("=" * 74)
print("四、_src 工具与生成脚本清单")
print("=" * 74)
import datetime
for f in sorted(set(glob.glob(os.path.join(SRC, "*")))):
    if os.path.isfile(f):
        t = datetime.datetime.fromtimestamp(os.path.getmtime(f))
        print("%-30s %7d B  %s" % (os.path.basename(f), os.path.getsize(f),
                                   t.strftime("%m-%d %H:%M:%S")))
