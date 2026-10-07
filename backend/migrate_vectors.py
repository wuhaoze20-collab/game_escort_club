# -*- coding: utf-8 -*-
"""一次性迁移脚本：把 ai_chunks.embedding 列的向量搬到 ai_vectors 表。

运行方式：
    cd backend
    venv\Scripts\python.exe migrate_vectors.py

迁移完成后可以安全删除 ai_chunks 表的 embedding/dim/model 列（可选）。
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal, engine
from models import AiChunk, AiVector, Base


def migrate():
    # 自动创建 ai_vectors 表（如果不存在）
    Base.metadata.create_all(bind=engine, tables=[AiVector.__table__])
    print("ai_vectors 表已就绪")

    db = SessionLocal()
    try:
        # 1. 找出所有有向量的 chunk
        chunks = db.query(AiChunk).filter(AiChunk.embedding.isnot(None)).all()
        print(f"找到 {len(chunks)} 条带向量的 chunk")

        migrated = 0
        skipped = 0
        for chunk in chunks:
            # 检查 ai_vectors 表是否已有记录
            existing = db.query(AiVector).filter(AiVector.chunk_id == chunk.id).first()
            if existing is not None:
                skipped += 1
                continue
            # 验证向量格式
            try:
                vec = json.loads(chunk.embedding)
                if not isinstance(vec, list) or len(vec) == 0:
                    print(f"  跳过 chunk_id={chunk.id}：向量格式无效")
                    continue
            except Exception as e:
                print(f"  跳过 chunk_id={chunk.id}：JSON 解析失败 {e}")
                continue

            # 写入 ai_vectors 表
            vec_row = AiVector(
                chunk_id=chunk.id,
                embedding=chunk.embedding,
                dim=int(chunk.dim or len(vec)),
                model=chunk.model or "",
            )
            db.add(vec_row)
            migrated += 1

        db.commit()
        print(f"\n迁移完成：新增 {migrated} 条，跳过已存在 {skipped} 条")

        # 2. 验证
        total_vec = db.query(AiVector).count()
        print(f"ai_vectors 表现有 {total_vec} 条记录")

    except Exception as e:
        db.rollback()
        print(f"迁移失败：{e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
