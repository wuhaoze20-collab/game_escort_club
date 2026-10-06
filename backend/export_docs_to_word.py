# -*- coding: utf-8 -*-
"""从数据库导出 kb_documents 为 Word 文档，存到 docs/agreements/"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from models import KbDocument
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "agreements")
os.makedirs(OUTPUT_DIR, exist_ok=True)

db = SessionLocal()
try:
    docs = db.query(KbDocument).filter(KbDocument.enabled == 1).order_by(KbDocument.sort_order.asc(), KbDocument.id.asc()).all()
    for d in docs:
        doc = Document()
        # 标题
        title = doc.add_heading(d.title, level=0)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        # 分类/版本信息
        meta = doc.add_paragraph()
        meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = meta.add_run(f"分类：{d.category or '未分类'}    版本：v{d.version}")
        run.font.size = Pt(10)
        run.font.color.rgb = RGBColor(128, 128, 128)
        doc.add_paragraph()
        # 正文（按换行分段）
        for line in (d.content or "").split("\n"):
            line = line.strip()
            if not line:
                doc.add_paragraph()
                continue
            # 第X条/第X章作为小标题
            if line.startswith("第") and any(c in line for c in ["条", "章", "节"]):
                p = doc.add_paragraph()
                run = p.add_run(line)
                run.bold = True
                run.font.size = Pt(12)
            else:
                p = doc.add_paragraph(line)
                p.paragraph_format.first_line_indent = Pt(24)
        # 文件名：doc_key.docx
        filename = f"{d.doc_key}.docx"
        filepath = os.path.join(OUTPUT_DIR, filename)
        doc.save(filepath)
        print(f"已导出：{filename}（{d.title}）")
    print(f"\n共导出 {len(docs)} 篇文档到 {OUTPUT_DIR}")
finally:
    db.close()
