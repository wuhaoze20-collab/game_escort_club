"""把DeepSeek配置写入系统配置表"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from database import SessionLocal
from models import ContentConfig
from datetime import datetime

db = SessionLocal()

configs = {
    "ai_base_url": "https://api.deepseek.com/v1/chat/completions",
    "ai_model": "deepseek-chat",
    "ai_api_key": "sk-填入你自己的APIKey",
}

for key, val in configs.items():
    row = db.query(ContentConfig).filter(ContentConfig.config_key == key).first()
    if not row:
        row = ContentConfig(config_key=key, config_value=val)
        db.add(row)
    else:
        row.config_value = val
    row.updated_at = datetime.now()

db.commit()
db.close()
print("✅ 系统配置已更新：")
for k, v in configs.items():
    print(f"  {k} = {v}")
