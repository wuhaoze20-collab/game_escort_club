# -*- coding: utf-8 -*-
"""AI 提示词段落与问答库的首次初始化（幂等）。

两个表的分工：
· `ai_prompts` —— 系统提示词的**段落**（角色设定、回答规则、权限、安全等）。
  出厂内容来自 `ai_service.PROMPT_SECTIONS`，这里负责写入数据库。
· `ai_faqs`    —— **问答库**，按关键词命中后只注入相关几条（见 ai_service.build_faq_context）。

幂等策略：**各自整体判空**。表里已有数据就整体跳过，绝不覆盖后台的增删改。
因此后台删掉某条 FAQ 或改坏某段提示词后重启，不会被重新塞回来。

FAQ 的两个要点：
1. `role` 字段决定这条问答对谁生效（''=所有角色）。同一件事对不同角色的正确答法常常
   相反 —— 例如"怎么充值"对老板是操作路径、对打手是"你没有这个权限"。这正是必须分角色的原因。
2. 答案里可以写 `{config_key}` 占位符，注入时会替换成系统参数的当前值，
   避免管理员改了阈值后问答库还在说旧数字（见 ai_service.render_placeholders）。
"""

from models import AiFaq, AiPrompt

# 问答库出厂内容
# 字段：question 标准问法 / keywords 命中关键词（逗号分隔）/ answer 标准答法
#       role 生效角色（''=全角色）/ category 分类
DEFAULT_FAQS = [
    # ——— 充值（老板与打手的权限完全相反，必须分开写）———
    {
        "question": "老板怎么充值大狗币？", "category": "充值", "role": "boss",
        "keywords": "充值,充钱,充值中心,充大狗币,买大狗币",
        "answer": "左侧菜单「店铺运营」→「充值中心」，选择金额与支付方式后提交。"
                  "充值比例是 1 元 = 1 大狗币，按档位还有额外赠送（赠送规则见「充值中心」页面）。",
    },
    {
        "question": "打手可以充值吗？", "category": "充值", "role": "player",
        "keywords": "充值,充钱,充值中心,充大狗币,买大狗币",
        "answer": "充值中心是老板专属功能，打手账号没有充值入口、无法充值。"
                  "打手的收入来自接单结算与老板打赏，不需要自己充值。",
    },
    # ——— 提现 ———
    {
        "question": "打手怎么提现？多久能到账？", "category": "提现", "role": "player",
        "keywords": "提现,提现中心,取钱,提款,多久到账,什么时候到账,多久能提,能提多少,提多少,"
                    "提现多久,怎么提,能不能提,提现规则",
        "answer": "左侧菜单「我的工作」→「提现中心」。只有入账满 {withdraw_cooldown_days} 天的"
                  "后台金额才能申请提现，提交后由管理员或客服审核，审核通过后打款。"
                  "审核期间这笔金额会被占用，不能重复申请。",
    },
    {
        "question": "为什么我的可提现金额是 0？", "category": "提现", "role": "player",
        "keywords": "可提现,提现为0,不能提现,提不了,为什么提不了,提现失败,提现额度",
        "answer": "常见原因有三种：一是收入还没满 {withdraw_cooldown_days} 天冷却期；"
                  "二是已有提现申请在审核中，占用了额度；三是后台金额已经被之前的提现扣减过。"
                  "具体以「提现中心」显示的数字为准。",
    },
    {
        "question": "老板能把大狗币提现吗？", "category": "提现", "role": "boss",
        "keywords": "提现,取钱,退款,把余额取出来",
        "answer": "提现是打手专属功能，老板账号没有提现入口。"
                  "如果你的大狗币需要处理，请通过平台内渠道联系管理员。",
    },
    # ——— 结算 ———
    {
        "question": "打手什么时候能拿到钱？", "category": "结算", "role": "player",
        "keywords": "结单,结算,到账,工资,什么时候拿到钱,收入",
        "answer": "流程是：你提交结单 → 老板确认结单 → 费用才转入你的后台金额。"
                  "只有你提交、老板还没确认时，钱不会到账。结单比例是 "
                  "俱乐部抽成 {club_commission_rate}，其余计入你的后台金额。",
    },
    {
        "question": "老板确认结单是什么意思？", "category": "结算", "role": "boss",
        "keywords": "确认结单,结单,结算,确认,为什么要点确认",
        "answer": "打手提交结单后需要你在订单页点「确认结单」，费用才会转入打手后台。"
                  "这一步是保障你自己资金的环节：确认前费用不会付给打手。",
    },
    # ——— 打赏 ———
    {
        "question": "怎么给打手打赏？", "category": "打赏", "role": "boss",
        "keywords": "打赏,小费,奖励打手,红包",
        "answer": "订单完成（已结单）后可在订单页给打手打赏。打赏金额须为整数元，"
                  "单笔订单的累计打赏不能超过订单金额的 {tip_max_rate}（按比例计算）。"
                  "打赏和点单一样消耗大狗币。",
    },
    {
        "question": "打手能给自己打赏吗？", "category": "打赏", "role": "player",
        "keywords": "打赏,小费,自己打赏",
        "answer": "打赏由老板发起，打手无法给自己打赏。收到的打赏会直接计入你的后台金额，"
                  "可在「我的工作」里查看打赏记录。",
    },
    # ——— 点单 ———
    {
        "question": "老板怎么下单？", "category": "点单", "role": "boss",
        "keywords": "下单,点单,怎么点,下单流程,点单中心,找人陪玩",
        "answer": "左侧菜单「我的点单」→「点单中心」：选择游戏与业务类型、填服务时长，"
                  "可以指定打手也可以不指定（不指定则由客服派单），还能填备注说明段位与要求。"
                  "金额由系统按单价自动计算，不能手动改。",
    },
    {
        "question": "打手能自己接单吗？", "category": "点单", "role": "player",
        "keywords": "接单,拒单,抢单,怎么接",
        "answer": "打手不能主动点单。有订单被派给你时会出现在「我的工作 → 我的订单」里，"
                  "你可以「接受」或「拒绝」；接受后开始服务，服务完成再提交结单。",
    },
    {
        "question": "订单可以取消或退款吗？", "category": "点单", "role": "boss",
        "keywords": "取消,退单,退款,不想要了,不点了",
        "answer": "还没完成的订单可以取消，消耗的大狗币按原路退回你的账户。"
                  "已完成（已结单）的订单不能取消。",
    },
    # ——— 账号与资料 ———
    {
        "question": "忘记密码怎么办？", "category": "账号", "role": "",
        "keywords": "忘记密码,密码忘了,重置密码,改密码,密码错误",
        "answer": "在登录页点「忘记密码？」，输入账号和新密码即可重置。"
                  "已经登录的话，也可以在「个人中心 → 我的账户」里修改密码。",
    },
    {
        "question": "账号被锁定了怎么办？", "category": "账号", "role": "",
        "keywords": "锁定,登录不上,登不上去,密码错误太多次,账号被锁",
        "answer": "连续输错密码 {login_max_failed_attempts} 次会锁定账户 {login_lock_minutes} 分钟，"
                  "等待时间到了就能重新登录。如果确认密码记不清了，用「忘记密码」重置会自动解锁。",
    },
    {
        "question": "改昵称和头像为什么要审核？", "category": "账号", "role": "",
        "keywords": "改昵称,改名字,改头像,头像审核,昵称审核,换头像",
        "answer": "在「个人中心 → 我的账户」提交新的昵称或头像，需要管理员或客服审核通过后才生效。"
                  "审核期间原来显示的内容不变。",
    },
    # ——— 评价与投诉 ———
    {
        "question": "怎么评价或投诉打手？", "category": "评价", "role": "boss",
        "keywords": "评价,投诉,差评,举报,打分",
        "answer": "订单完成后在订单页可以给打手评价（1~5 星）。投诉会记为 1 星差评并进入复查流程，"
                  "由管理员或客服处理。",
    },
    {
        "question": "被打手被差评了怎么办？", "category": "评价", "role": "player",
        "keywords": "差评,复查,申诉,被投诉,评价删除",
        "answer": "在「我的工作 → 我的评价」可以回复老板的评价，也可以对差评提交复查申请，"
                  "由管理员或客服审核。确实违规的评价会被移除。",
    },
    # ——— 规则与处罚 ———
    {
        "question": "平台怎么抽成？", "category": "规则", "role": "",
        "keywords": "抽成,分成,提成,佣金,平台抽多少",
        "answer": "每笔结单金额中，俱乐部抽成 {club_commission_rate}，其余计入打手的后台金额。"
                  "具体比例以平台当前设置为准。",
    },
    {
        "question": "什么情况会被拉黑注销账号？", "category": "规则", "role": "",
        "keywords": "拉黑,封号,注销,处罚,违规,处罚通告",
        "answer": "严重违规的账号会被拉黑注销：账户余额会转入公司账户，账号无法再登录，"
                  "**此操作不可撤销**。已执行的处理会公示在「店铺运营 → 处罚通告」里。",
    },
    {
        "question": "能不能私下转账交易？", "category": "规则", "role": "",
        "keywords": "私下,转账,微信,加好友,支付宝,便宜点,打折",
        "answer": "平台不支持私下交易。所有点单、打赏都必须通过平台走，才有资金保障、"
                  "也才能评价和投诉。价格是平台统一定价，客服没有调整价格的权限。",
    },
    # ——— 通用 ———
    {
        "question": "怎么联系人工客服？", "category": "通用", "role": "",
        "keywords": "人工,人工客服,真人,客服电话,联系方式,投诉平台",
        "answer": "人工客服请通过平台内渠道联系。我这边只能回答平台业务相关的问题。",
    },
    {
        "question": "平台都有哪些游戏和服务？", "category": "通用", "role": "",
        "keywords": "什么游戏,有哪些游戏,服务项目,能玩什么,价格表",
        "answer": "具体游戏、业务类型和单价请看「店铺运营 → 价格预览」页面，"
                  "那里是平台当前价格，以它为准。",
    },
]


def seed_ai_prompts(db) -> int:
    """首次写入提示词段落（幂等：表内已有数据则整体跳过）"""
    if db.query(AiPrompt).count() > 0:
        return 0
    import ai_service  # 延迟导入，避免循环依赖
    for s in ai_service.PROMPT_SECTIONS:
        db.add(AiPrompt(
            section_key=s["key"],
            title=s.get("title", ""),
            content=s["content"],
            role=s.get("role", ""),
            priority=s.get("priority", 100),
            enabled=1,
            version=1,
            updated_by="system",
        ))
    db.commit()
    return len(ai_service.PROMPT_SECTIONS)


def seed_ai_faqs(db) -> int:
    """首次写入问答库（幂等：表内已有数据则整体跳过）"""
    if db.query(AiFaq).count() > 0:
        return 0
    for f in DEFAULT_FAQS:
        db.add(AiFaq(
            question=f["question"],
            keywords=f.get("keywords", ""),
            answer=f["answer"],
            category=f.get("category", ""),
            role=f.get("role", ""),
            enabled=1,
        ))
    db.commit()
    return len(DEFAULT_FAQS)
