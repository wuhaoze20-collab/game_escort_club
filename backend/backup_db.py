# -*- coding: utf-8 -*-
"""
MySQL 备份脚本：使用 mysqldump 导出数据库到 backups/ 目录
- 备份文件：backups/game_escort_club_YYYYMMDD_HHMMSS.sql
- 自动清理旧备份，默认保留最近 7 份（环境变量 BACKUP_KEEP 可调）
- SQLite 模式下自动跳过

用法：venv\Scripts\python backup_db.py
可选环境变量：MYSQLDUMP_PATH（mysqldump 路径）、BACKUP_KEEP（保留份数）
"""
import glob
import os
import subprocess
import sys
from datetime import datetime

from database import DB_ENGINE, MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DB


def main():
    if DB_ENGINE != "mysql":
        print("当前为 SQLite 模式（DB_ENGINE=sqlite），无需 mysqldump 备份。")
        return

    dump = os.getenv("MYSQLDUMP_PATH", r"D:\MYsql\bin\mysqldump.exe")
    keep = int(os.getenv("BACKUP_KEEP", "7"))
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    backup_dir = os.path.join(project_root, "backups")
    os.makedirs(backup_dir, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(backup_dir, f"game_escort_club_{ts}.sql")

    # 通过 MYSQL_PWD 环境变量传密码，避免出现在命令行/进程列表中
    env = os.environ.copy()
    env["MYSQL_PWD"] = MYSQL_PASSWORD
    cmd = [
        dump,
        f"-u{MYSQL_USER}",
        f"-h{MYSQL_HOST}",
        f"-P{MYSQL_PORT}",
        "--default-character-set=utf8mb4",
        "--single-transaction",   # 一致性快照，不锁表
        "--routines",
        "--set-gtid-purged=OFF",  # MySQL 8 兼容
        MYSQL_DB,
    ]

    try:
        with open(out_path, "wb") as f:
            result = subprocess.run(cmd, env=env, stdout=f, stderr=subprocess.PIPE)
        if result.returncode != 0:
            err = result.stderr.decode("utf-8", errors="replace")
            os.remove(out_path)
            print(f"❌ 备份失败：{err}")
            sys.exit(1)
    except FileNotFoundError:
        print(f"❌ 找不到 mysqldump：{dump}，请设置环境变量 MYSQLDUMP_PATH")
        sys.exit(1)

    size_mb = os.path.getsize(out_path) / 1024 / 1024
    print(f"✅ 备份成功：{out_path}（{size_mb:.2f} MB）")

    # 清理旧备份，只保留最近 keep 份
    files = sorted(glob.glob(os.path.join(backup_dir, "game_escort_club_*.sql")))
    for f in files[:-keep]:
        os.remove(f)
        print(f"  已清理旧备份：{os.path.basename(f)}")
    print(f"  当前保留 {min(len(files), keep)} 份备份")


if __name__ == "__main__":
    main()
