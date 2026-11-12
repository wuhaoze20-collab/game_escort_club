"""切换到DeepSeek模型配置，同时保留千问配置作为备选"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from database import SessionLocal
from models import ContentConfig
import json
from datetime import datetime

db = SessionLocal()

# 读取当前AI配置
ai_cfg = db.query(ContentConfig).filter(ContentConfig.config_key == "ai_config").first()
if not ai_cfg:
    ai_cfg = ContentConfig(config_key="ai_config", config_value="{}")
    db.add(ai_cfg)

cfg = json.loads(ai_cfg.config_value or "{}")

# 保存两套预设
cfg["presets"] = {
    "qwen": {
        "name": "通义千问 qwen-plus（原配置）",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "model": "qwen-plus",
        "api_key": cfg.get("api_key", "")  # 保留原来的key
    },
    "deepseek": {
        "name": "DeepSeek V3（快速便宜）",
        "base_url": "https://api.deepseek.com/v1/chat/completions",
        "model": "deepseek-chat",
        "api_key": "sk-填入你自己的APIKey"
    }
}

# 当前激活的是DeepSeek
cfg["active_preset"] = "deepseek"
cfg["base_url"] = cfg["presets"]["deepseek"]["base_url"]
cfg["model"] = cfg["presets"]["deepseek"]["model"]
cfg["api_key"] = cfg["presets"]["deepseek"]["api_key"]

ai_cfg.config_value = json.dumps(cfg, ensure_ascii=False)
ai_cfg.updated_at = datetime.now()

db.commit()
db.close()
print("✅ 已切换到DeepSeek配置")
print("  - 对话模型：deepseek-chat (DeepSeek V3)")
print("  - 向量模型：保留原千问 text-embedding-v3 不变")
print("  - 后台RAG配置界面可以随时切回千问qwen-plus")
