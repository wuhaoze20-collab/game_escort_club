"""同步新的处罚体系规则到数据库：更新知识库文档、AI提示词、处罚公告默认值"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from database import SessionLocal, engine
from models import ContentConfig, Base
import json
from datetime import datetime

# 创建表（如果不存在新字段，SQLAlchemy create_all 会补）
Base.metadata.create_all(bind=engine)

db = SessionLocal()

# ========== 1. 更新用户服务协议里的违规处理章节 ==========
print("更新知识库文档...")
kb_user = db.query(ContentConfig).filter(ContentConfig.config_key == "kb_user_agreement").first()
new_user_agreement = """第一章 总则与协议接受

第一条 本协议全称为大狗嚼电竞用户服务协议，是用户与大狗嚼电竞平台之间就使用平台提供的游戏陪玩、护航、上分及相关增值服务所订立的具有约束力的协议。用户包括在平台下单消费的老板、在平台接单提供服务的打手，以及其他访问或使用平台功能的自然人。

第二条 本协议所称平台，指由大狗嚼电竞运营的游戏陪玩服务平台，包括其网站、移动客户端、小程序及后续可能推出的其他服务载体。

第三条 用户在使用平台服务前，应当完整阅读并同意本协议全部条款，特别是关于大狗币充值、会员权益、订单结算、违规处理、免责声明及争议解决的条款。用户完成注册、点击同意或实际使用平台服务，即视为已接受本协议全部条款。

第十二条 用户应当妥善保管账号、密码及验证码。登录连续输错密码5次的，账号将被临时锁定10分钟，锁定期内无法登录，锁定时间届满后自动解除。

第四章 大狗币充值规则
第十七条 大狗币是平台内虚拟货币，1元人民币等于1大狗币，老板使用大狗币支付平台订单。大狗币不具有法定货币属性，不可兑换现金，不可在用户之间转让，不可提现。

第十二章 违规处理与处罚体系

第六十二条 平台对违规行为实行分级处罚体系，根据情节轻重分为：警告、临时封禁（1天/3天/7天/30天）、永久拉黑（注销账号）三个层级。

第六十三条 对言语不当、消极服务等轻微违规行为，平台给予警告并记录在案；警告累计3次的，升级为临时封禁处罚。

第六十四条 临时封禁处罚规则：
  · 轻度违规：临时封禁1天，期间无法登录和接单/下单
  · 中度违规（无故拒单、态度恶劣、引导私下交易）：临时封禁3天或7天
  · 较重违规：临时封禁30天
  临时封禁期间用户无法登录，封禁到期后系统自动解除封禁，账号恢复正常使用。

第六十五条 对作弊、诈骗、恶意刷单、多次违规屡教不改等严重违规行为，平台将发起永久拉黑。永久拉黑流程为：
  · 管理员或客服提交拉黑申请后，账号进入24小时缓冲期
  · 缓冲期内用户可联系管理员申诉，管理员核实后可解除拉黑
  · 缓冲期届满未解除的，账号永久封禁注销，账户余额/后台金额转入公司账户，无法恢复

第六十六条 账号被临时封禁或拉黑缓冲期期间，用户登录时会收到剩余封禁时间提示，系统自动在封禁到期后解除限制。被永久封禁的账号无法恢复使用。

第六十七条 用户对处罚决定有异议的，可在收到通知后3个工作日内联系客服申诉，管理员审核后作出最终决定。

第十三章 免责声明与责任限制
第七十条 在法律允许的最大范围内，平台对用户承担的赔偿责任总额不超过该用户就争议订单实际支付的大狗币金额。"""

if kb_user:
    kb_user.config_value = new_user_agreement
    kb_user.updated_at = datetime.now()
    print("  ✓ 用户服务协议已更新")

# ========== 2. 更新打手服务规范的处罚章节 ==========
kb_player = db.query(ContentConfig).filter(ContentConfig.config_key == "kb_player_rules").first()
new_player_rules = """第一章 总则与适用范围
第一条 本规范全称为打手服务规范与行为准则，是打手在大狗嚼电竞平台提供游戏陪玩、护航、上分等服务时应当遵守的行为标准。

第十章 处罚与申诉
第五十八条 平台对打手违规行为实行分级处罚体系，根据情节轻重分为警告、临时封禁（1天/3天/7天/30天）、永久拉黑三个层级。

第五十九条 对言语不当、消极服务等轻微违规行为，平台给予警告；警告累计3次升级为临时封禁。

第六十条 临时封禁规则：
  · 轻度违规：封禁1天
  · 中度违规（无故拒单、态度恶劣）：封禁3天或7天
  · 较重违规：封禁30天
  封禁期间打手无法登录接单，到期自动解封。

第六十一条 对作弊、诈骗、恶意刷单、代练账号共享、多次违规等严重违规行为，平台将发起永久拉黑。提交后进入24小时缓冲期，缓冲期内可申诉解除；逾期未解除的账号永久注销，后台金额转入公司账户。

第六十二条 打手收到封禁通知后，登录页面会显示剩余封禁时间。对处罚有异议的，可在3个工作日内通过客服渠道提交申诉并提供证据。

第六十三条 申诉材料包括订单号、聊天记录、录屏、系统通知截图等。管理员审核后作出最终决定。申诉期间处罚继续执行，确有错误的予以撤销。"""

if kb_player:
    kb_player.config_value = new_player_rules
    kb_player.updated_at = datetime.now()
    print("  ✓ 打手服务规范已更新")

# ========== 3. 更新处罚公告默认文案 ==========
pun = db.query(ContentConfig).filter(ContentConfig.config_key == "punishment").first()
if pun:
    plist = json.loads(pun.config_value or "[]")
    plist.insert(0, {
        "level": "规则更新",
        "desc": "平台升级处罚体系：新增临时封禁（1/3/7/30天）选项，拉黑前设24小时缓冲期可申诉解除，封禁到期自动恢复。",
        "date": datetime.now().strftime("%Y-%m-%d")
    })
    pun.config_value = json.dumps(plist, ensure_ascii=False)
    print("  ✓ 处罚公告已更新")

# ========== 4. 更新AI提示词里的处罚相关描述 ==========
print("更新AI提示词...")
from ai_service import PROMPT_SECTIONS
# 找到规则部分更新
for section in PROMPT_SECTIONS:
    if "规则" in section.get("section", "") or "处罚" in section.get("content", "")[:100]:
        # 这里只打日志，实际 ai_prompts 表由 seed_ai_content 维护
        pass

# 更新 ai_prompts 表
ai_prompt = db.query(ContentConfig).filter(ContentConfig.config_key == "ai_prompt_main").first()
if ai_prompt:
    # 追加新的处罚规则说明
    old = ai_prompt.config_value
    new_rules = """

【处罚体系最新规则】
1. 临时封禁分5档：1天、3天、7天、30天、永久，管理员可根据违规程度选择
2. 拉黑不是立即执行：提交拉黑后进入24小时缓冲期，期间可申诉解除，逾期才永久注销
3. 封禁/拉黑后用户会被立即踢下线，登录时会提示剩余解封时间
4. 临时封禁到期自动解封，不需要人工操作
5. 客服只能提交拉黑申请，最终由管理员审核
"""
    if "处罚体系最新规则" not in old:
        ai_prompt.config_value = old + new_rules
        ai_prompt.updated_at = datetime.now()
        print("  ✓ AI主提示词已更新")

db.commit()
db.close()
print("\n✅ 所有处罚规则已同步到数据库！")
