# -*- coding: utf-8 -*-
"""扫描所有 .drawio 中的「英文标识符被折行切断」问题。

判据：节点文字按 <br> 或换行拆成多行后，若某行的最后一个字符与下一行的
第一个字符都是 [A-Za-z0-9_]（也就是断点两侧都还在字母数字里），
即视为把一个英文标识符拦腰截断——这是真实可读性缺陷，
而不是有意的换行（有意换行会断在空格、标点或中文之后）。
"""

import glob
import os
import re
import sys
import xml.etree.ElementTree as ET

sys.stdout.reconfigure(encoding="utf-8")

DRAWIO = r"C:\Users\18642\game_escort_club\docs\flowcharts\drawio"
ALNUM = re.compile(r"[A-Za-z0-9_]")

total = 0
for f in sorted(glob.glob(os.path.join(DRAWIO, "*.drawio"))):
    root = ET.fromstring(open(f, "rb").read().decode("utf-8"))
    hits = []
    for d in root.findall("diagram"):
        for c in d.findall(".//mxCell"):
            if c.get("vertex") != "1":
                continue
            val = c.get("value") or ""
            if not val:
                continue
            lines = re.split(r"<br\s*/?>|\n", val)
            lines = [ln.strip() for ln in lines]
            if len(lines) < 2:
                continue
            for a, b in zip(lines[:-1], lines[1:]):
                if not a or not b:
                    continue
                if ALNUM.match(a[-1]) and ALNUM.match(b[0]):
                    hits.append((c.get("id"), a[-18:], b[:18]))
    total += len(hits)
    print("=" * 70)
    print("%s  —— 折行断词 %d 处" % (os.path.basename(f), len(hits)))
    for cid, tail, head in hits:
        print("   [%s]  …%s  ||  %s…" % (cid, tail, head))

print()
print("全项目合计：%d 处英文标识符折行截断" % total)
