# 大狗嚼电竞管理系统

基于 FastAPI + MySQL + 原生前端的完整前后端分离管理系统，实现多角色权限、内容管理、订单全流程、工资结算、打手评价、盈利统计等功能。

## 技术栈
- **后端**：Python 3.8+ / FastAPI / SQLAlchemy / MySQL / JWT鉴权 / bcrypt密码加密
- **前端**：原生HTML/CSS/JS + Tailwind CSS
- **开发工具**：VSCode

## 项目目录结构
```
game_escort_club/
├── backend/                     # 后端服务（FastAPI）
│   ├── api/                     # 接口路由（共 89 个接口）
│   │   ├── __init__.py
│   │   ├── auth_api.py          # 登录/注册/注册审核/改密/忘记密码
│   │   ├── content_api.py       # 公告/须知/价格/福利/支付方式/处罚通告等内容接口
│   │   ├── user_info_api.py     # 用户资料/昵称审核/等级/标签/充值/封禁(含客服申请-管理员审核)/公司账户
│   │   ├── order_api.py         # 点单/派单/接单/结单/确认结算/取消/工资记录
│   │   ├── rating_api.py        # 评价/投诉/回复/复查申请与审核
│   │   ├── stats_api.py         # 本月盈利统计
│   │   ├── tip_api.py           # 打赏接口
│   │   ├── withdraw_api.py      # 提现申请与审核
│   │   ├── notification_api.py  # 站内消息通知
│   │   ├── quote_api.py         # 台词增删改查 + 批量导入
│   │   ├── config_api.py        # 系统参数读取/修改/恢复默认/静默失败留痕清理
│   │   ├── ai_api.py            # AI 客服（千问）：对话/会话/历史 + 工具调用循环
│   │   └── ai_prompt_api.py     # AI 提示词段落与问答库管理 + 提示词预览
│   ├── database.py              # 数据库连接（默认 MySQL，DB_ENGINE=sqlite 可回退）
│   ├── models.py                # 数据库表模型（19 张表）
│   ├── schemas.py               # 请求/响应数据模型
│   ├── auth.py                  # JWT 鉴权与角色权限校验
│   ├── config_service.py        # 系统参数读取层（带缓存与默认值兜底）
│   ├── ai_service.py            # AI 提示词装配（数据库段落 + FAQ 注入）+ 调用千问
│   ├── ai_tools.py              # AI 工具（Function Calling）：查询余额/订单/价格等
│   ├── main.py                  # 程序入口（建表 + 自动补列/改类型 + 挂载路由与静态目录）
│   ├── seed_default_accounts.py # 默认账号与内容配置初始化（启动时幂等调用）
│   ├── seed_quotes.py           # 默认台词初始化（290 条，仅首次导入）
│   ├── seed_ai_content.py       # 默认提示词段落（5 段）与问答库（22 条）初始化
│   ├── seed_demo_data.py        # 演示数据填充脚本（可选，手动执行）
│   ├── check_consistency.py     # 一致性自检：前端菜单 / 后端路由 / AI 角色上下文
│   ├── check_ai_tools.py        # AI 工具安全性自检：权限边界 + 身份绑定
│   ├── backup_db.py             # MySQL 备份脚本（mysqldump，默认保留最近 7 份）
│   ├── requirements.txt         # Python 依赖清单
│   ├── .env.example             # 环境变量模板（复制为 .env 后填 API Key）
│   ├── .env                     # 本地密钥文件（**已被 .gitignore 排除，不会提交**）
│   └── venv/                    # 虚拟环境（本机已创建，勿删除）
├── frontend/                    # 前端页面（原生单页应用）
│   ├── index.html               # 单页入口（HTML + CSS + JS 全部在这一个文件内）
│   └── avatars/                 # 实际对外提供的头像（后端 /avatars 挂载此目录）
├── touxiangku/                  # 头像素材源（内容与 frontend/avatars 相同，供人工替换素材）
├── bizhiku/                     # 背景视频（已被 .gitignore 忽略，克隆后需自行放入）
├── backups/                     # MySQL 备份产物（*.sql，随仓库分发以同步页面内容）
├── CHANGELOG.md                 # 版本更新日志
└── README.md
```

> **两个容易踩坑的点**
> 1. 前端是**单文件**应用：`frontend/index.html` 内含全部 CSS 与 JS，没有构建步骤，改完刷新即生效。
> 2. `bizhiku/` 被 `.gitignore` 忽略，但 `index.html` 引用了其中的 `登录背景.mp4` 与 `背景.mp4`。**新克隆的仓库必须自己放入这两个视频**，否则页面背景静默 404（不影响其它功能）。头像则已随仓库提交（`frontend/avatars/`）。

## 架构说明

### 数据模型（19 张表）

| 表 | 作用 | 关键字段与状态 |
|---|---|---|
| `users` | 四种角色统一存储 | `role`(admin/service/boss/player)；`account_status`(注册审核 pending/approved/rejected)；`failed_attempts` + `lock_until`(登录锁定)；`pending_nickname`/`pending_avatar` + `nickname_status`(资料审核) |
| `content_config` | 页面内容（共 8 个模块） | `config_key` 唯一，`config_value` 存 JSON；**改页面内容 = 改这张表**，无需动代码。白名单见 `content_api.py` 的 `VALID_CONFIG_KEYS` |
| `boss_info` | 老板业务数据 | `consume_amount`(累计消费)、`balance`(大狗币余额)、`order_count` |
| `player_info` | 打手业务数据 | `backend_amount`(后台金额)、`good_rate`(好评率，无评价时为空)、`complaint_count`、`level_type` + `tech_level`(等级) |
| `player_tags` | 打手标签（需审核） | `status`：pending/approved/rejected |
| `orders` | 订单主表 | `order_no` 唯一；`status` 见下方状态机；`total_amount`、`service_note`(业务量)、`remark`(老板备注) |
| `salary_records` | 结单工资结算 | `order_id` 唯一（一单一结）；`order_total` = `club_commission` + `player_income` |
| `player_ratings` | 评价（一单一评） | `order_id` 唯一；`rating`(1-5)；`reply`(打手回复)；`review_status`：normal/reviewing/removed |
| `tip_records` | 打赏记录 | 关联订单；累计不超过订单金额的 30% |
| `withdrawal_records` | 提现申请 | `status`：pending/approved/rejected |
| `notifications` | 站内消息 | `user_id` 外键；`is_read` |
| `quotes` | 顶部台词栏的台词 | `text`、`source`(出处)、`enabled`(1/0，停用不参与轮换)、`sort_order`。**前台台词栏的唯一数据源**，后台「台词管理」可增删改 |
| `system_config` | 业务参数（键值表） | `config_key` 唯一、`config_value`(字符串存)、`value_type`(int/float/str/json)、`label`/`description`。**抽成比例、冷却天数、各类上限等全部在此**，改完立即生效 |
| `ai_conversations` | AI 客服会话 | `username`(归属用户)、`title`(由首条提问生成)、`updated_at`。**接口层强制校验归属**，不能读别人的会话 |
| `ai_messages` | AI 客服消息 | `conversation_id`、`role`(user/assistant/tool)、`content`、`prompt_tokens`/`completion_tokens`(用量统计)、`error`(调用失败原因)、`tools_used`(本条回答用到的工具名，用于审计) |
| `ai_prompts` | **AI 系统提示词段落** | `section_key` 唯一、`content`(段落正文)、`role`(空=全角色，否则仅该角色生效)、`priority`(拼接顺序)、`enabled`、`version`(每次保存+1)、`updated_by`。**提示词不再硬编码在代码里**，后台「提示词管理」可改、立即生效、可恢复出厂 |
| `ai_faqs` | **AI 问答库** | `question`、`keywords`(逗号分隔，命中用)、`answer`(标准答法)、`category`、`role`(生效角色)、`enabled`、`hit_count`。按提问关键词命中 Top N 条注入提示词，替代"每次塞全部资料" |
| `ai_faq_misses` | **未命中提问记录** | `question` 唯一、`role`、`count`(累计次数)、`last_at`。问答库的反馈闭环：管理员据此看到"用户常问但没覆盖"的问题并补问答 |
| `ban_requests` | 客服发起的拉黑申请 | `target_username`/`target_role`、`requested_by`、`reason`、`status`(pending/approved/rejected)、`note`、`processed_by`/`processed_at`。**单独建表而非在 `users` 上加列**：同一账号可能被多次申请（驳回后可再申请），需要留历史 |

> **金额单位与字段类型**（易错，改动前务必先看这里）：

| 字段 | 单位 | 类型 | 说明 |
|---|---|---|---|
| `orders.total_amount`、`salary_records.*`、`tip_records.*`、`withdrawal_records.*` | **分**（整数） | `int` | 所有订单/工资/打赏/提现金额统一用分，避免浮点误差 |
| `boss_info.balance` | **大狗币**（1 大狗币 = 1 元） | `DECIMAL(10,2)` | V3.8.0 起支持两位小数。订单金额不是 100 分整数倍时 `coins_required = 总额/100` 会产生小数，**用 int 列会被静默取整**，故必须用 DECIMAL |
| `boss_info.consume_amount` | **分** | `int` | 累计消费 |
| `player_info.backend_amount` | **分** | `int` | 打手后台金额。分是最小货币单位，**不需要小数**，故保持 int（模型曾误声明为 `Float`，V3.8.0 一并改正） |
| `content_config.company_balance` / `company_records` | **分** | JSON 内整数 | 前端展示时两处均 `/100` |
| `player_info.good_rate` | 百分比 | `Float` | 唯一真正需要小数的展示字段，无评价时为空 |

> `boss_info.balance` 与 `player_info.backend_amount` **单位不同**（元 vs 分），两者互相换算时务必 `×100` / `÷100`——V3.7.1 修的「封禁老板时金额少 100 倍」就是这两者被直接相加导致的。

> **`system_config` 有默认值兜底**：每条参数在 `config_service.py` 的 `CONFIG_META` 里都定义了出厂默认值与类型。数据库缺行、值非法或类型转换失败时一律回退默认值并打印告警，**业务不会因配置问题崩溃**。读取带 10 秒缓存，写入时立即失效，所以改完马上生效。

> **`content_config` 是复用表**：除 8 个页面内容模块外，它还存了两个**内部键** `company_balance`（公司账户余额）与 `company_records`（封禁资金流水）。这两个键不在 `VALID_CONFIG_KEYS` 白名单内，因此不会出现在 `/api/content/all` 里，也不能通过内容接口读写——**直接清空/重建这张表会连带清掉公司账户余额**。

### 订单状态机

```
create ─┬─ 未指定打手 ─→ pending(待派单) ─────┐
        └─ 指定打手 ──→ pending_accept(待打手确认)
                              ├─ accept ──→ assigned ──→ processing ──→ pending_settlement ──→ completed
                              └─ reject ──→ rejected ──(重新派单)──→ assigned
pending / pending_accept / assigned ──cancel──→ cancelled
processing / pending_settlement ──(管理员直接完成)──→ completed
```

对应实现见 `backend/api/order_api.py`，状态流转的合法前置条件由每个接口显式校验（非法状态返回 400）。

### 资金流转（大狗币 1:1 人民币）

1. **充值** → 老板 `balance` 增加（`/api/boss/recharge`）
2. **下单** → 校验并扣除老板大狗币，订单进入 `pending` / `pending_accept`
3. **拒单 / 取消** → 大狗币原路退回老板
4. **打手提交结单** → `processing` → `pending_settlement`，**此时资金尚未到打手账户**（保障老板资金安全）
5. **老板确认结单** → 写 `salary_records`：`club_commission`(30%，`CLUB_COMMISSION_RATE`) 归俱乐部 + `player_income`(70%) 计入打手 `backend_amount`
6. **打赏** → 老板额外打赏（≤订单 30%），直接计入打手后台金额
7. **提现** → 打手后台金额**入账满 30 天**（`withdraw_cooldown_days`，后台可调）后才可申请 → 管理员/客服审核 → 批准后扣除

**可提现额的计算规则**（`withdraw_api.calc_available_amount`，改这里前务必看懂）：

```
可提现 = max(0, min(已到期收入 + 期初结余, backend_amount) - 在途申请)
```

| 项 | 含义 |
|---|---|
| 已到期收入 | `salary_records` + `tip_records` 中**已过冷却期**的部分 |
| **期初结余** | `backend_amount` 里**没有收入记录支撑**的部分（建库时预设的历史余额）。它必然早于所有记录存在，按定义已过冷却期，故计入可提现基数 |
| `backend_amount` | 权威余额，封顶用，防止透支 |
| 在途申请 | 仅 `pending` 的提现占用额度 |

> ⚠️ **两个易错点**：① **已批准的提现不要在此处再减一次** —— `approve_withdraw()` 已经把它从 `backend_amount` 扣掉了，重复扣减会导致可提现额出现负数（V3.4.2 修的就是这个）；② **`backend_amount` 与收入记录必须自洽**，两者的差额会被当作"期初结余"直接视为可提现，因此手工改库时不要只改一边。

### 鉴权与权限

- 登录签发 JWT（`auth.py`，`SECRET_KEY` 环境变量可覆盖，默认 24 小时有效）
- 接口级权限用 `Depends(require_roles("admin", ...))` 校验，越权返回 403；前端再按角色隐藏菜单与按钮（**前端隐藏只是体验，真正的边界在后端**）

### 可维护配置（改后台即可，无需改代码或重启）

以下内容原先硬编码在代码里，现已全部迁入数据库，由后台页面维护：

| 内容 | 存放位置 | 后台入口 | 可操作角色 |
|---|---|---|---|
| **台词**（290 条，驱动顶部台词栏） | `quotes` 表 | 系统设置 → 台词管理 | 管理员 / 客服 |
| **业务参数**（18 项） | `system_config` 表 | 系统设置 → 系统参数 | 管理员（客服只读） |
| **AI 提示词**（5 段） | `ai_prompts` 表 | 系统设置 → 提示词管理 | **管理员**（含各角色权限清单与安全规则，故不对客服开放） |
| **AI 问答库**（22 条出厂） | `ai_faqs` 表 | 系统设置 → AI 问答库 | 管理员 / 客服 |

**业务参数清单**（`config_service.CONFIG_META`，含默认值与类型校验）：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `club_commission_rate` | 0.3 | 俱乐部抽成比例（0~1） |
| `tip_max_rate` | 0.3 | 单笔订单累计打赏上限比例 |
| `withdraw_cooldown_days` | 30 | 提现冷却天数 |
| `recharge_max_amount` | 10000000 | 单次充值上限（分） |
| `login_max_failed_attempts` | 5 | 连续输错密码锁定阈值 |
| `login_lock_minutes` | 10 | 账户锁定时长（分钟） |
| `token_expire_minutes` | 1440 | 登录令牌有效期（分钟） |
| `order_min_amount` / `order_max_amount` | 100 / 5000000 | 订单金额下限 / 上限（分） |
| `order_max_duration_min` | 1440 | 单笔订单时长上限（分钟） |
| `order_remark_max_len` / `order_service_note_max_len` / `game_type_max_len` | 500 / 50 / 50 | 各类文本字段字数上限 |
| `nickname_max_len` / `tag_max_len` | 20 / 20 | 昵称 / 标签字数上限 |
| `violation_nickname` | 违规昵称 | 昵称被打回后的占位文案 |
| `tech_levels` / `level_types` | 985…明星护 / 娱乐陪·技术陪 | 打手等级列表（JSON 数组） |
| `ai_enabled` | true | 是否启用 AI 客服（关闭后前端不显示气泡） |
| `ai_model` | qwen-plus | 千问模型名（qwen-turbo 更快更便宜、qwen-max 最强） |
| `ai_daily_limit` | 30 | 每人每日提问上限（0 = 不限制） |
| `ai_temperature` | 0.3 | 回答随机度，客服场景建议偏低 |
| `ai_max_tokens` | 800 | 单次回答最大长度 |
| `ai_extra_instruction` | 见下 | 附加到系统提示词末尾的临时话术（**出厂内容为常见问答标准答法与语气要求**，可整段改写或清空） |
| `ai_history_rounds` | 6 | 每次携带的历史对话轮数 |
| `ai_faq_top_n` | 4 | 问答库按关键词命中的条数上限（0 = 关闭按需注入） |

> 修改参数会**立即生效**（写入即失效缓存）。填了非法值会被拒绝并提示原因（例如比例越界、类型不符），不会写进库。
> 台词改动会同步影响所有角色的顶部台词栏（前端登录时拉取一次，之后本地 10 秒轮换，不会高频请求后端）。

### AI 客服（接入通义千问）

登录后右下角有一个**悬浮气泡**，点开即可对话。它是**客服答疑型**：只依据数据库里的内容配置回答，不查个人订单数据。

**配置步骤（三步）**：

```bash
# 1. 把模板复制为 .env
cd C:\Users\18642\game_escort_club\backend
copy .env.example .env

# 2. 编辑 .env，填入你的阿里云百炼 API Key
#    DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxx

# 3. 重启后端
venv\Scripts\python.exe main.py
```

> **不配置也能正常启动**：AI 功能会自动关闭（前端不显示气泡），其它功能完全不受影响。

**工作原理**：每次提问时，后端拼一份系统提示词塞给千问，按以下顺序组装：

| 顺序 | 内容 | 来源 | 谁能改 |
|---|---|---|---|
| ① | **提示词段落**（角色设定、回答规则 1-6、界面与路径 7-10、权限 11-13、安全 14-16） | `ai_prompts` 表 | **管理员**（「系统设置 → 提示词管理」，改完立即生效、可恢复出厂） |
| ② | 当前用户（称呼、角色） | 运行时 | — |
| ③ | **该用户的真实侧边栏菜单 + 权限 + 操作路径** | `ai_service.ROLE_MENUS/CAPS/FLOWS` | 改代码（须与前端保持一致） |
| ④ | **平台知识库** | `content_config` 的 8 个内容模块 | 管理员/客服（内容页编辑） |
| ⑤ | **问答库命中片段**（按提问关键词挑出 Top N 条） | `ai_faqs` 表 | **管理员/客服**（「AI 问答库」） |
| ⑥ | 当前时间 | 运行时 | — |
| ⑦ | 【补充指示】常见问答标准答法与语气要求 | `system_config.ai_extra_instruction` | 管理员（「系统参数」） |

因此：

- **在后台改了价格/公告/充值福利，AI 的回答会自动跟着变** —— 不需要改任何代码
- **改提示词也不用改代码、不用重启**（V3.9.0 起提示词存数据库），并可在同一页「预览」按角色真实拼一次提示词
- **AI 是按角色区分的**：打手问"怎么充值"，回答是"充值中心是老板专属，打手账号没有充值入口、无法充值"，**不会**给出一套充值步骤；老板问同样的问题才会拿到真实路径
- 提示词明确要求"平台资料里没有的就说不确定、**绝不编造价格规则**"

### AI 工具（Function Calling）—— 让 AI 从"会说"到"会查"

V3.9.0 起 AI 可以调用**只读查询工具**，用户问"我还有多少钱""我那单到哪了"时不再只能让用户自己去页面看：

| 工具 | 作用 | 允许角色 |
|---|---|---|
| `query_my_orders` | 查**自己**的订单（可按状态过滤） | 老板 / 打手 |
| `query_my_balance` | 查**自己**的余额（老板=大狗币；打手=后台金额+可提现） | 老板 / 打手 |
| `query_price` | 查平台价目表（可按游戏/段位过滤） | 全部角色 |
| `query_my_withdrawals` | 查**自己**的提现记录与可提现金额 | 打手 |
| `query_monthly_profit` | 查本月盈利与订单总额 | **仅管理员** |

> ⚠️ **三条铁律（`backend/ai_tools.py` 的注释里有详细说明）**：
> 1. **身份只来自令牌，绝不接受 AI "听来"的参数。** 所有工具函数签名都是 `(db, user)`，
>    **没有 `username` 参数** —— 就算模型被诱导去查别人，它也无从表达这个意图。
> 2. **权限与 HTTP 接口同源**：`TOOL_ROLES` 必须与各接口的 `require_roles` 一致，
>    且每次执行前再校验一次（模型可能编造工具名或越权调用）。
> 3. **全部只读**：没有下单/提现/拉黑这类写操作。写操作必须由用户在界面上二次确认，
>    不能让 AI 直接改库。
>
> 提示词里的"你没有权限"只是**话术**，上述工具层校验才是安全边界。

> ⚠️ **维护耦合（重要）**：`backend/ai_service.py` 里的 `ROLE_MENUS` / `ROLE_CAPS` / `ROLE_FLOWS`
> 是菜单与权限的**副本**。**改了前端菜单或接口权限，必须同步这三处**，否则 AI 会按旧结构回答，
> 给出不存在的菜单项、或越权的操作步骤。前端 `menuConfig` 处也留了同样的提醒注释。
>
> **不用靠记 —— 跑一次自检脚本即可**（它会逐字比对，并顺带检查前端调的接口是否真实存在）：
>
> ```powershell
> cd backend
> venv\Scripts\python.exe check_consistency.py            # 打印报告
> venv\Scripts\python.exe check_consistency.py --strict   # 有不一致时以非 0 退出（提交前用）
> ```

**几个容易踩的坑**：

| 坑 | 说明 |
|---|---|
| **Key 与地域绑定** | 用北京接口就必须配北京的 Key，否则返回 `401 invalid_api_key`（不是 Key 失效）。换地域要同时改 `.env` 里的 `QWEN_BASE_URL` |
| **`.env` 绝不能提交** | 已在 `.gitignore` 中排除；提交前用 `git status` 确认它没出现 |
| **必须设超时** | 已内置（默认 60 秒）。千问不通时请求会在超时后返回可读提示，不会把后端拖死 |
| **有每日上限** | 默认每人每天 30 条（`ai_daily_limit`，后台可调），防止被刷导致费用失控 |
| **不要改成 async** | 调用用的是同步 `requests`，与项目其它接口一致（FastAPI 会放进线程池）。改成 `async def` 会阻塞事件循环 |
| **菜单/权限改动要同步** | 漏改会让 AI 给出错误路径或越权步骤。**别靠记 —— 跑 `python check_consistency.py` 自检**，它会逐字比对 ROLE_MENUS 与前端 menuConfig、并抽查 ROLE_FLOWS 里的菜单路径是否真实存在 |

### 异常留痕（`ops_alerts`）

项目里有不少防御性写法是**静默回退**的：系统参数读失败就用默认值、可提现额算出负值就归零、
初始化失败只打印一行。好处是业务不崩，坏处是**出了问题没人知道**。

`backend/ops_alerts.py` 把这类「被兜住的异常」记下来，由 `/api/config/all` 带出，
前端在**「系统参数」页顶部**以告警条显示（管理员可见），并提供「已处理，清空」按钮。

目前会留痕的事件：

| key | 触发条件 | 意味着什么 |
|---|---|---|
| `recharge_config_broken` | 「充值福利」配置非法 | 充值已被暂停，需修配置 |
| `recharge_gift_bad:*` | 某档位赠送值不是整数 | 该档按 0 赠送处理 |
| `config_read:*` | 读系统参数失败 | 可能连不上库，当前按默认值运行 |
| `config_bad_value:*` | 参数值不是合法类型 | 当前按默认值运行，需到设置页修正 |
| `withdraw_negative:*` | 可提现额算出负值 | **账目不一致**，附四项数值便于定位 |

> 特点：进程内存储、同 key 合并计数（不刷屏）、最多 50 条、重启即清空。
> **它不是日志系统**，只为让静默故障可见。要加新的事件，调用 `ops_alerts.record(key, message)` 即可。

**相关文件**：路由 `backend/api/ai_api.py`，服务层 `backend/ai_service.py`（含菜单/权限/路径定义），密钥 `backend/.env`。

> **关于回复的渲染**：气泡用前端 `renderAiText()` 渲染 —— **先 `escapeHtml` 转义，再把 `**加粗**` 还原成 `<strong>`**。
> 顺序不能颠倒（先转义、后插入自己生成的标签），否则会引入 XSS 风险。
> 提示词里也要求模型输出纯文本，两层互为兜底。

## 快速启动（详细环境配置）

### 第 0 步：前置检查（只做一次）

**要求**：Windows 系统 + Python 3.8 及以上（本项目本机实测使用 Python 3.11）。

1. 确认 Python 已安装。打开 CMD 或 VSCode 终端，依次输入：
   ```bash
   python --version
   ```
   - 能输出版本号（如 `Python 3.11.x`）→ 继续第 1 步
   - 提示 `'python' 不是内部或外部命令` → 说明 `python` 命令不在 PATH 中，改用以下任一方式：
     - 用 Windows 官方启动器：`py --version`（可用则后续命令把 `python` 换成 `py`）
     - 或使用 Python 安装目录的完整路径，例如本机：`C:\Program Files\Python311\python.exe --version`

2. 确认已安装 Git（用于拉取/推送 Gitee 仓库）：
   ```bash
   git --version
   ```

### 第 1 步：创建虚拟环境（第一次才需要）

在项目根目录打开终端，进入 `backend` 目录，创建虚拟环境：

```bash
cd C:\Users\18642\game_escort_club\backend
python -m venv venv
```

> 如果 `python` 命令不可用，用 `py -m venv venv` 或完整路径：
> ```bash
> "C:\Program Files\Python311\python.exe" -m venv venv
> ```

创建成功后会生成 `backend\venv\` 目录（本仓库已包含该目录，若存在可跳过此步）。

### 第 2 步：安装依赖（第一次才需要）

**方式一：激活虚拟环境后安装（推荐）**

```bash
venv\Scripts\activate          # Windows 激活虚拟环境，出现 (venv) 前缀即成功
pip install -r requirements.txt
```

**方式二：不激活，直接调用 venv 内的 pip（等价）**

```bash
venv\Scripts\pip install -r requirements.txt
```

> **网络慢/安装失败时**：使用国内镜像源加速：
> ```bash
> pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
> ```

**验证依赖是否装好**（关键一步，装完必须确认）：

```bash
venv\Scripts\python -c "import fastapi, uvicorn, sqlalchemy, jose, bcrypt; print('依赖OK')"
```

- 输出 `依赖OK` → 环境就绪，继续第 3 步
- 报 `ModuleNotFoundError: No module named 'xxx'` → 说明对应依赖未装上，重新执行 `pip install -r requirements.txt`（或用镜像源重装）

### 第 3 步：导入最新数据库备份（推荐，与作者内容保持一致）

> **重要**：公告、下单须知、价格、充值福利、处罚通告等内容都存储在 **MySQL 数据库**里，不在 Git 代码中。直接启动后端会用 `seed_default_accounts.py` 里的默认内容初始化（且 seed 幂等，**不会覆盖数据库中已存在的数据**）。想让你的页面内容与 Gitee 仓库作者完全一致，请导入 `backups/` 下**最新**的 `.sql` 备份文件（每个备份文件名带时间戳，取日期最新的那个）。

先确认已按"数据库配置"章节创建好库与账号，然后导入（命令中的文件名换成 `backups/` 里最新的）:

```bash
mysql -u game_escort -p123456 game_escort_club < backups\game_escort_club_20260911_180022.sql
```

> - 导入会覆盖数据库中的全部数据（用户、内容、订单等），第一次初始化或想与作者同步时使用。
> - 只想保留作者最新内容、不要测试订单时，可先导入备份，再按"第 5 步"方式一清空业务流水。
> - 不导入备份直接启动也可以运行，但页面内容可能与作者仓库不一致。

### 第 4 步：启动后端服务

```bash
cd C:\Users\18642\game_escort_club\backend
venv\Scripts\python main.py
```

> **必须用 `backend\venv` 里的解释器**，不要用系统 Python 或其它项目的虚拟环境（见下方排查表第 1 条）。
> 工作目录现已不再影响运行——路径都基于 `main.py` 自身位置解析，所以也可以用绝对路径从任意目录启动：
> ```bash
> C:\Users\18642\game_escort_club\backend\venv\Scripts\python.exe C:\Users\18642\game_escort_club\backend\main.py
> ```

- 启动成功标志：终端出现 `Uvicorn running on http://127.0.0.1:8000`，且首次启动自动完成**建表 + 初始化默认数据**（11 个测试账号、公告/价格等默认内容、6 名打手、290 条台词、26 项系统参数、5 段 AI 提示词、22 条 AI 问答）
- 后端服务地址：`http://localhost:8000`
- 在线接口文档（Swagger）：`http://localhost:8000/docs`

**常见启动失败排查**：

| 现象 | 原因 | 解决办法 |
|---|---|---|
| `ModuleNotFoundError: No module named 'fastapi'` | **用错了 Python 解释器**（最常见）：用了系统 Python，或用了**别的项目**的虚拟环境 | 必须用本项目的 `backend\venv\Scripts\python.exe`。用 `python -c "import sys; print(sys.executable)"` 确认当前解释器路径，若输出不是 `...\game_escort_club\backend\venv\...` 就是选错了 |
| `RuntimeError: Directory '../frontend/avatars' does not exist` | 在旧版本中因工作目录不是 `backend` 导致（**V3.4.1 已修复，不再依赖工作目录**） | 升级到最新代码；或先 `cd` 到 `backend` 再启动 |
| `[Errno 10048] ... address already in use` | 8000 端口被占用 | 方法一：`netstat -ano | findstr 8000` 查出 PID 后 `taskkill /F /PID <PID>` 结束占用进程；方法二：改 `main.py` 里的 `port=8000` 为其他端口 |
| 启动无报错但页面连不上 | 后端没起来 / 前端 API 地址不对 | 确认终端停留在运行状态（不要关闭窗口）；确认 `frontend/index.html` 顶部 `API_BASE` 为 `http://localhost:8000` |

> **本机有多个 Python 时的建议**：不要靠 `python` 这个命令名去猜，直接用完整路径启动最稳妥：
> ```
> cd C:\Users\18642\game_escort_club\backend
> venv\Scripts\python.exe main.py
> ```

> **最省事的启动方式**：双击 `backend\启动.bat`。该脚本**固定使用本项目的 `backend\venv`**，并在启动前先校验依赖是否齐全，选错解释器这类问题不会再出现。

#### 在 PyCharm 里运行时必须改解释器

PyCharm 的运行按钮用的是**它自己配置的解释器**，跟 `main.py` 里的代码无关。本项目务必指向 `backend\venv`：

1. `File` → `Settings` → `Project: game_escort_club` → `Python Interpreter`
2. 齿轮 → `Add Local Interpreter` → `Existing`
3. 选择 `C:\Users\18642\game_escort_club\backend\venv\Scripts\python.exe` → 确定
4. 再打开 `Run` → `Edit Configurations...`，确认 `main` 这条配置的 `Python interpreter` 也选成上面这个（运行配置里的解释器是单独存的，改项目 SDK 不一定同步）

> 注意：项目根的 `.venv` 目录已在整理时删除（它缺 `uvicorn` 等依赖，本来就不完整）。**唯一正确且完整的环境是 `backend\venv`。** 若 PyCharm 里还留着指向 `game_escort_club\.venv` 的失效解释器，删掉即可。

**关闭后端**：在运行窗口按 `Ctrl + C`，或直接关闭该终端窗口。

### 第 5 步：启动前端页面（二选一）

**方式一：直接双击打开（最简单）**

在文件资源管理器中双击 `frontend\index.html`，用浏览器打开即可正常使用（后端已开启 CORS，支持 file:// 协议直连）。

**方式二：VSCode + Live Server（推荐开发用）**

1. VSCode 扩展市场搜索安装 **Live Server** 插件
2. 右键 `frontend\index.html` → **Open with Live Server**
3. 浏览器自动打开 `http://127.0.0.1:5500` 页面

> 前后端是分离的：前端页面（5500 或 file://）通过 HTTP 请求访问后端（8000），**两个服务都要开着**才能完整使用。

### 第 6 步：重置数据库（可选）

系统数据默认存放在 **MySQL**（库名 `game_escort_club`，账号 `game_escort` / 密码 `123456`）。
想恢复初始状态时，清空业务数据后重启后端即可重新初始化：

```bash
# 方式一：只清业务流水（订单/评价/工资/打赏/提现），保留用户与内容配置
mysql -u game_escort -p123456 -e "USE game_escort_club; TRUNCATE TABLE orders; TRUNCATE TABLE player_ratings; TRUNCATE TABLE salary_records; TRUNCATE TABLE tip_records; TRUNCATE TABLE withdrawal_records;"
venv\Scripts\python main.py       # 重启后端（订单等业务数据保持空，其余保留）

# 方式二：彻底重置（清空全部表并重新初始化默认演示数据）
mysql -u game_escort -p123456 -e "USE game_escort_club; SET FOREIGN_KEY_CHECKS=0; DROP TABLE IF EXISTS users, content_config, boss_info, player_info, player_tags, orders, salary_records, player_ratings, tip_records, withdrawal_records; SET FOREIGN_KEY_CHECKS=1;"
venv\Scripts\python main.py       # 重启后端，自动重建所有表+初始化默认数据
```

> 注意：两种方式都会丢失业务数据（订单/评价/提现记录等），仅测试环境建议使用。

## 测试账号（统一密码：123456）
| 账号 | 角色 | 昵称 | 权限说明 |
|---|---|---|---|
| guanliyuan | 管理员 | 店长 | 全部权限，可查看所有信息、编辑内容、管理订单、查看本月盈利 |
| kefu | 客服 | 客服小蜜 | 可查看所有老板/打手信息，可编辑基础内容，可人工派单、管理订单 |
| laoban / laoban_02 / laoban_03 | 老板 | 老板阿昊 / 老板二狗 / 老板三少 | 可查看基础内容，可点单并直接指定打手、查看打手公开数据、评价打手、打赏、查看自己的账户信息 |
| dashou / dashou_02 / dashou_03 | 打手 | 小达 / 阿岚 / 老猫 | 娱乐陪/技术陪，可编辑自我介绍、添加标签（审核后展示）、接单/拒单、提交结单、回复评价、申请评价复查、提现、查看自己的账户信息 |
| dashou_04 / dashou_05 / dashou_06 | 打手 | 北冥 / 阿澈 / 星火 | 等级覆盖 985 / 211 / 大专 / 魔王护 / 明星护，其余权限同上 |

## 核心功能
### 1. 多角色权限体系
- JWT令牌鉴权，登录后24小时有效
- 后端接口级权限校验，越权请求返回403
- 前端菜单和按钮按角色动态显示
- 打手公开数据与敏感数据隔离：老板点单只能看到接单数、好评率、投诉、自我介绍，后台金额等敏感信息仅管理员/客服可见
- 账户安全：连续输错密码 5 次锁定 10 分钟；支持忘记密码重置与"我的账户"修改密码

### 2. 内容管理
- 共 **8 个**内容模块：店铺公告、下单须知、价格预览、充值福利、会员福利、支付方式、处罚通告、赛事专栏
- 所有登录用户可查看，仅管理员和客服可编辑
- 内容存储在数据库，修改实时生效

### 3. 用户信息管理
- 老板信息：账户名、累计消费、账户余额、点单次数
- 打手信息：账户名、接单次数、投诉次数、好评率、后台金额、自我介绍
- 管理员/客服可查看全部列表，老板/打手只能查看自己的信息
- 金额单位统一为分，避免浮点精度问题

### 4. 点单中心（老板专属）
- 老板可查看所有打手的公开数据（接单数、好评率、投诉、自我介绍）和近期评价
- 选择打手直接下单，填写备注（如要求、急单提示），订单自动进入"待打手确认"状态
- 我的订单列表：可取消订单，已完成订单可评价打手、打赏打手

### 5. 打手接单/拒单
- 打手在"我的订单"查看老板备注，自行决定接单或拒单
- 接受后进入已接单状态，可开始服务；拒绝后金额自动退回老板余额

### 5.5 结单确认流程（金额安全）
- 打手开始服务后可"提交结单"，订单进入"待确认结单"状态
- 老板在点单中心"确认结单"后，金额才转入打手账户并计入双方次数
- 管理员/客服也可直接完成结算；打手提交结单后金额尚未到账，保障老板资金安全

### 5.6 评价复查（打手申诉）
- 打手可对老板评价提交"复查申请"并填写理由，提交后该评价暂时对所有人隐藏
- 管理员在"评价复查"页面审核：移除该评价（通过）或保留该评价（驳回，评价恢复显示）
- 评价被移除后打手好评率自动重新计算，打手可查看复查状态与管理员的处理备注

### 6. 打赏功能
- 老板结单后可对打手打赏，无冷却时间，累计不超过订单金额的30%
- 打赏消耗大狗币（1元 = 1大狗币），打手后台金额按1:1折算为人民币实时到账

### 6.5 充值中心（大狗币）
- 老板专属充值页面，对打手账户隐藏；充值福利档位直接显示在金额卡上（充100送10大狗币等）
- 点击金额卡 → 弹出支付方式选择（微信/支付宝/QQ钱包/银行卡）→ 确认到账
- 大狗币 1:1 充值，老板点单与打赏均消耗大狗币，结算时打手后台自动折算为人民币

### 6.6 打手等级与标签
- 打手等级分两类：娱乐陪 / 技术陪；技术陪由低到高细分 985 → 211 → 大专 → 魔王护 → 明星护
- 打手可在"我的账户"修改等级，老板点单时可见等级徽章
- 打手可自行添加标签（如"王者百星"），提交后由管理员/客服在"标签审核"页面审核，通过后对老板展示
- 打手可查看标签审核状态（审核中/已展示/未通过）并删除标签

### 6.7 头像与昵称（资料审核）
- 所有账户可自定义昵称；**头像由系统按角色/等级默认分配，任何人不可自定义选用**（touxiangku 图库仅供默认使用）
- 默认头像：管理员→管理员头像、客服→客服头像、老板→老板默认头像、打手→对应等级头像（985/211/大专/魔王护/明星护/娱乐陪）
- 在"我的账户"填写新昵称，提交后进入"待审核"；管理员/客服在"头像昵称审核"页面审核：通过后展示，**不合规打回**改为"违规昵称"
- 点击任意头像可弹出查看完整头像大图
- 头像与昵称展示覆盖：侧边栏/顶栏、打手卡、老板/打手管理列表、订单列表、评价列表
- 默认打手共 6 名（dashou ~ dashou_06），覆盖 985/211/大专/魔王护/明星护/娱乐陪 全部等级

### 7. 提现功能
- 打手后台金额入账满30天冷却期后，可在提现中心发起提现
- 管理员/客服在提现审核页面批准或拒绝，批准后金额从打手后台扣除

### 8. 打手自我介绍与评价回复
- 打手可在"我的账户"编辑自我介绍，老板点单时可见
- 打手可查看老板的评价并回复，回复对所有人可见

### 9. 打手订单中心
- 打手可查看自己的全部订单及完成情况（待确认/已接单/服务中/待确认结单/已完成/已拒单）
- 服务中订单可"提交结单"，提交后等待老板确认，确认后金额入账

### 10. 订单管理（客服/管理员）
- 人工派单：可对待派单或打手拒单的订单指派打手
- 查看全部订单状态

### 11. 处罚通告
- 第7个内容模块：违规处罚公示，所有登录用户可查询，仅管理员和客服可编辑
- 第8个内容模块为「赛事专栏」（`matches`）：游戏赛事直播链接列表，字段为 game/title/url

### 12. 本月盈利（管理员专属）
- 本月总盈利（俱乐部抽成合计）、完成订单数、订单总额、打手发放总额
- 按打手汇总盈利明细

### 13. 工资结算
- 订单完成自动生成工资记录
- 记录订单原始金额、俱乐部抽成、打手收入
- 打手只能查看自己的工资记录

## 接口列表

共 **89 个接口**。除「所有人」外均需 `Authorization: Bearer <token>`；权限由 `auth.py` 的 `require_roles()` 在接口级校验，越权返回 403。

> 另有一个应用级路由 `GET /`（返回 `frontend/index.html`），它不算业务接口，故未计入 89。
> 因此 `check_consistency.py` 报告的是 **90 条路由**、归一化后 **85 个路径**（差额来自同一路径的不同方法，
> 如 `GET`/`POST /api/player/tags`），与 `/openapi.json` 的 `paths` 数量一致。

### 认证与账户（6）
| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| POST | /api/login | 登录获取令牌（连续错5次锁定10分钟） | 所有人 |
| POST | /api/register | 注册账号（老板即刻生效，打手/客服需审核） | 所有人 |
| GET | /api/admin/registration-list | 注册审核列表 | 管理员 |
| POST | /api/admin/registration-decision | 注册审核通过 / 驳回 | 管理员 |
| POST | /api/reset-password | 忘记密码重置（重置后自动解锁） | 所有人 |
| POST | /api/change-password | 修改密码（校验原密码） | 所有登录用户 |

### 内容配置（3）
| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| GET | /api/content/all | 获取所有内容配置 | 所有登录用户 |
| GET | /api/content/{config_key} | 获取单个内容配置 | 所有登录用户 |
| PUT | /api/content/{config_key} | 更新内容配置 | 管理员/客服 |

### 站内通知（4）
| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| GET | /api/notification/list | 获取通知列表 | 所有登录用户 |
| GET | /api/notification/unread-count | 未读数量 | 所有登录用户 |
| POST | /api/notification/{notification_id}/read | 标记单条已读 | 所有登录用户 |
| POST | /api/notification/read-all | 全部标记已读 | 所有登录用户 |

### 用户资料 / 标签 / 账户（21）
| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| GET | /api/boss/list | 获取老板列表 | 管理员/客服 |
| GET | /api/player/list | 获取打手列表(含敏感数据) | 管理员/客服 |
| GET | /api/player/public | 获取打手公开列表(不含敏感数据) | 所有登录用户 |
| GET | /api/boss/me | 获取当前老板信息 | 老板 |
| GET | /api/player/me | 获取当前打手信息 | 打手 |
| PUT | /api/profile | 修改昵称（提交审核） | 所有登录用户 |
| GET | /api/profile/review | 昵称审核列表 | 管理员/客服 |
| POST | /api/profile/review/{username} | 昵称审核通过 / 打回 | 管理员/客服 |
| PUT | /api/player/intro | 更新打手自我介绍 | 打手本人 |
| PUT | /api/player/level | 修改打手等级 | 打手本人 |
| GET | /api/player/tags | 查询我的标签 | 打手本人 |
| POST | /api/player/tags | 添加标签（提交审核） | 打手本人 |
| DELETE | /api/player/tags/{tag_id} | 删除我的标签 | 打手本人 |
| GET | /api/player/tags/review | 标签审核列表 | 管理员/客服 |
| POST | /api/player/tags/{tag_id}/decision | 标签审核通过 / 驳回 | 管理员/客服 |
| POST | /api/boss/recharge | 老板充值大狗币 | 老板 |
| POST | /api/admin/ban/{username} | 拉黑老板/打手（后台金额转入公司账户，**不可逆**） | 管理员 |
| POST | /api/ban/request | 客服发起拉黑申请（不立即执行，等管理员审核） | 客服 |
| GET | /api/ban/requests | 拉黑申请列表 | 管理员/客服 |
| POST | /api/ban/requests/{id}/decision | 拉黑申请审核（approve 通过后才真正执行 / reject 驳回） | 管理员 |
| GET | /api/admin/company-balance | 查询公司后台余额 | 管理员 |

### 订单与工资（11）
| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| POST | /api/order/create | 创建订单(可指定打手,带备注) | 管理员/客服/老板 |
| POST | /api/order/{order_id}/assign | 人工派单 | 管理员/客服 |
| POST | /api/order/{order_id}/accept | 打手接受订单 | 打手本人 |
| POST | /api/order/{order_id}/reject | 打手拒绝订单（金额退回老板） | 打手本人 |
| POST | /api/order/{order_id}/start | 开始服务 | 管理员/客服/打手 |
| POST | /api/order/{order_id}/submit-settlement | 打手提交结单 | 打手本人 |
| POST | /api/order/{order_id}/confirm-settlement | 老板确认结单（金额入账） | 管理员/客服/老板 |
| POST | /api/order/{order_id}/complete | 直接完成订单并结算 | 管理员/客服 |
| POST | /api/order/{order_id}/cancel | 取消订单 | 管理员/客服/老板 |
| GET | /api/order/list | 获取订单列表 | 所有登录用户(按角色过滤) |
| GET | /api/order/salary/list | 获取工资记录 | 管理员/客服/打手 |

### 评价 / 投诉 / 复查（9）
| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| POST | /api/rating/create | 评价打手 | 老板 |
| POST | /api/rating/complaint | 投诉打手（该订单记为★1差评） | 老板 |
| GET | /api/rating/player/{player_username} | 查询打手评价列表 | 所有登录用户 |
| GET | /api/rating/my | 查询我发出的评价 | 老板 |
| GET | /api/rating/my-reviews | 查询我收到的评价 | 打手本人 |
| PUT | /api/rating/{rating_id}/reply | 打手回复评价 | 打手本人 |
| POST | /api/rating/{rating_id}/review-request | 申请评价复查 | 打手本人 |
| GET | /api/rating/review-list | 复查审核列表 | 管理员/客服 |
| POST | /api/rating/{rating_id}/review-decision | 复查裁决（移除 / 保留） | 管理员 |

### 打赏（2）
| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| POST | /api/tip/create | 打赏打手(≤订单30%) | 老板 |
| GET | /api/tip/player/me | 查询我的打赏记录 | 打手 |

### 提现（6）
| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| GET | /api/withdraw/available | 查询可提现金额(30天冷却) | 打手 |
| POST | /api/withdraw/create | 发起提现申请 | 打手 |
| GET | /api/withdraw/my | 查询我的提现记录 | 打手 |
| GET | /api/withdraw/list | 查询所有提现申请 | 管理员/客服 |
| POST | /api/withdraw/{withdraw_id}/approve | 批准提现 | 管理员/客服 |
| POST | /api/withdraw/{withdraw_id}/reject | 拒绝提现 | 管理员/客服 |

### 数据统计（1）
| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| GET | /api/stats/monthly-profit | 本月盈利统计 | 管理员 |

### 台词管理（5）
| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| GET | /api/quote/list | 台词列表（管理员/客服含停用项，其他用户仅启用的） | 所有登录用户 |
| POST | /api/quote/create | 新增台词 | 管理员/客服 |
| PUT | /api/quote/{quote_id} | 修改台词（内容/出处/启用状态/排序） | 管理员/客服 |
| DELETE | /api/quote/{quote_id} | 删除台词 | 管理员/客服 |
| POST | /api/quote/batch-import | 批量导入（每行一条，`台词|出处`，自动跳过重复） | 管理员/客服 |

### 系统参数（4）
| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| GET | /api/config/all | 读取全部参数（含默认值、类型、说明）与静默失败留痕 | 管理员/客服 |
| PUT | /api/config/{config_key} | 修改参数（校验类型与取值范围，改完立即生效） | 管理员 |
| POST | /api/config/{config_key}/reset | 恢复该参数为默认值 | 管理员 |
| POST | /api/config/alerts/clear | 清空静默失败留痕列表 | 管理员 |

### AI 客服（5）
| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| GET | /api/ai/status | 查询是否可用、模型、今日剩余次数（前端据此决定是否显示气泡） | 所有登录用户 |
| POST | /api/ai/chat | 发消息并获取回复（带上会话上下文；按角色挂载工具，可查余额/订单/价格） | 所有登录用户 |
| GET | /api/ai/conversations | 我的会话列表 | 所有登录用户 |
| GET | /api/ai/conversations/{id}/messages | 某会话的历史消息 | **仅会话归属者** |
| DELETE | /api/ai/conversations/{id} | 删除会话及其消息 | **仅会话归属者** |

### AI 提示词与问答库（12）
> 提示词段落**仅管理员**可见可改（内容含各角色权限清单与安全规则）；
> 问答库**管理员 + 客服**均可维护（问答是面向用户的业务口径，客服最清楚用户在问什么）。

| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| GET | /api/ai/prompts | 列出全部提示词段落（含出厂内容、版本、修改人、是否已改） | 管理员 |
| PUT | /api/ai/prompts/{section_key} | 修改某段（内容/标题/生效角色/优先级/启用），每次保存 version+1 | 管理员 |
| POST | /api/ai/prompts/{section_key}/reset | 该段恢复出厂内容 | 管理员 |
| GET | /api/ai/prompts/preview | **按角色真实拼一次完整提示词**（可带一句提问检验问答库命中） | 管理员 |
| GET | /api/ai/faqs | 问答库列表 | 管理员/客服 |
| POST | /api/ai/faqs | 新增问答（答法里的 `{参数名}` 会校验是否为有效系统参数） | 管理员/客服 |
| PUT | /api/ai/faqs/{faq_id} | 修改问答（问法/答法/关键词/分类/角色/启停） | 管理员/客服 |
| DELETE | /api/ai/faqs/{faq_id} | 删除问答 | 管理员/客服 |
| POST | /api/ai/faqs/batch-import | 批量导入（每行 `问法\|答法\|关键词\|分类\|角色`，后三项可省略，自动跳过重复） | 管理员/客服 |
| GET | /api/ai/faqs/misses | 用户常问但**没有命中**问答库的提问（按次数排序） | 管理员/客服 |
| DELETE | /api/ai/faqs/misses/{miss_id} | 忽略某条未命中记录 | 管理员/客服 |
| POST | /api/ai/faqs/misses/clear | 清空全部未命中记录 | 管理员/客服 |

## 开发说明
1. 数据库表结构在 `backend/models.py`（19 张表）。改表后重启后端即可：新表由 `Base.metadata.create_all()` 自动创建，**新增列**由 `main.py` 的 `migrate_db()` 自动补齐（走 `information_schema` 检测），无需手动 `ALTER`
   - `migrate_db()` 除补列外还做**列类型迁移**：例如 `boss_info.balance` 若仍是 `int`，会在启动时自动 `ALTER` 成 `DECIMAL(10,2)`（包含 `NULL` 归零）。迁移前先查 `information_schema` 判断当前类型，**已是目标类型则不执行**，因此可反复重启而不会重复改表
   - 新增列一律加进 `main.py` 顶部的 `ADD_COLUMNS` 元组，格式 `(表名, 列名, DDL)`；判定走 `information_schema`，已存在则跳过
   - 新增需要小数或不同精度的金额字段时，请同时在 `models.py` 声明正确类型、在 `schemas.py` 用 `float`（用 `int` 会把小数**静默截断**），并在 `migrate_db()` 里补一段类型迁移
2. 默认账号与页面内容初始化在 `backend/seed_default_accounts.py`；默认台词在 `backend/seed_quotes.py`；AI 提示词与问答库在 `backend/seed_ai_content.py`。三者都在启动时幂等调用（**各自整体判空**），**已存在的数据不会被覆盖** —— 所以后台删掉的问答或改坏的提示词，重启不会自己回来
3. **俱乐部抽成比例等业务参数不要写死在代码里**：一律通过 `config_service.get_config(...)` 读取（`system_config` 表），默认值定义在 `config_service.CONFIG_META`。新增业务参数只需在 `CONFIG_META` 里加一条，后台设置页会自动出现该项
   - ⚠️ 新增的配置项若**内容可能很长**（如整段提示词），存量库需要放宽列宽：`main.py` 的 `migrate_columns_to_text()` 已把 `system_config.config_value` 与 `content_config.config_value` 改为 `TEXT`，因为 255 会直接报 `Data too long`（V3.9.0 踩过）
   - ⚠️ **改了出厂默认值不会影响已初始化的库**（seed 幂等：表非空即整体跳过）。需要让存量库也拿到新内容时，要么在后台界面上改，要么写一个一次性同步脚本按 `question`/`section_key` 找到已有行只更新目标字段（**不要整行覆盖**，否则会冲掉后台的编辑）
4. **改了前端菜单或接口权限后，跑一次一致性自检**：`venv\Scripts\python.exe check_consistency.py`。它检查 5 件事——ROLE_MENUS 与 menuConfig 是否逐字一致、每个菜单 key 是否都有对应页面、有没有不可达页面、前端调用的接口是否真实存在、ROLE_FLOWS/CAPS 里写的菜单路径是否真实。加 `--strict` 可在不一致时以非 0 退出（适合放进提交前检查），加 `--out 文件名` 可把 UTF-8 报告写文件（Windows 控制台是 GBK，直接重定向会变乱码）
   - **改了 `ai_tools.py` 后另外跑** `venv\Scripts\python.exe check_ai_tools.py`：它检查 15 项工具层安全边界——敏感工具是否只暴露给有权角色、`TOOLS` 与 `TOOL_ROLES` 是否同步、**所有工具函数签名里有没有身份参数**（这条是防越权的根本）、越权与编造工具名在运行时是否真被拒、结果里是否泄露他人账号、是否都是只读工具。同样支持 `--strict` / `--out`
5. **AI 的提示词、问答库、工具是三处独立的扩展点**，改动位置分别是：提示词段落（`ai_prompts` 表 / 出厂内容在 `ai_service.PROMPT_SECTIONS`）、问答（`ai_faqs` 表 / 出厂内容在 `seed_ai_content.DEFAULT_FAQS`）、工具（`ai_tools.py` 的 `TOOLS` + `TOOL_ROLES`）。**新增工具必须同步这两个常量并登记到 README 的工具表**
6. 生产环境请修改 `backend/auth.py` 的 `SECRET_KEY`（用环境变量覆盖）并收紧 CORS 配置
   - ⚠️ 注意：`load_dotenv` 目前只在 `ai_service._load_env()` 里**懒加载**，而 `auth.py` 在 import 阶段就读了 `SECRET_KEY`，因此**把 `SECRET_KEY` 写进 `.env` 不会生效**，必须设**系统环境变量**（或把 `load_dotenv` 提到 `main.py` 最前面）。换密钥会让所有已签发令牌失效，需在无人使用时操作

## 数据库配置（MySQL）

系统默认使用本机 MySQL 8（安装目录 `D:\MYsql`，客户端在 `D:\MYsql\bin\mysql.exe`，root 密码 `123456`）。首次使用时执行以下命令初始化库和专用账号：

```sql
CREATE DATABASE IF NOT EXISTS game_escort_club CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'game_escort'@'localhost' IDENTIFIED BY '123456';
CREATE USER IF NOT EXISTS 'game_escort'@'127.0.0.1' IDENTIFIED BY '123456';
GRANT ALL PRIVILEGES ON game_escort_club.* TO 'game_escort'@'localhost';
GRANT ALL PRIVILEGES ON game_escort_club.* TO 'game_escort'@'127.0.0.1';
FLUSH PRIVILEGES;
```

后端通过环境变量控制连接（`backend/database.py`），默认值即为本机配置：

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| DB_ENGINE | mysql | `mysql` 或 `sqlite`（回退本地文件数据库） |
| MYSQL_HOST | localhost | MySQL 地址 |
| MYSQL_PORT | 3306 | MySQL 端口 |
| MYSQL_DB | game_escort_club | 数据库名 |
| MYSQL_USER | game_escort | 数据库账号 |
| MYSQL_PASSWORD | 123456 | 数据库密码 |

示例（使用其他 MySQL）：
```bash
set MYSQL_HOST=192.168.1.10
set MYSQL_USER=root
set MYSQL_PASSWORD=mysecret
venv\Scripts\python main.py
```

> 启动时自动建表并初始化默认数据；表结构变更通过 `main.py` 的 `migrate_db()` 自动补列，无需手动 ALTER。

> ⚠️ **关于 `DB_ENGINE=sqlite` 回退**：该分支只在「本机没有 MySQL」时才有意义。SQLite 与 MySQL 是两套**完全独立**的数据，切换后不会自动同步——后端会在 `backend/` 下新建一个空的 `game_club.db`，页面数据看起来像是"被清空了"（实际 MySQL 里的数据仍在，切回去即可）。日常开发请勿设置该变量。

## 工具脚本

### 1. 填充演示数据（体验完整功能）
```bash
cd C:\Users\18642\game_escort_club\backend
venv\Scripts\python seed_demo_data.py
```
- 新增 6 名打手（覆盖全部等级、带自我介绍与已审核标签）
- 生成约 30 笔历史订单 + 工资/评价/打赏/提现记录
- 幂等：orders 表已有数据时自动跳过

### 2. 备份数据库（MySQL）
```bash
venv\Scripts\python backup_db.py
```
- 备份到 `backups/game_escort_club_时间戳.sql`，默认保留最近 7 份
- 可选环境变量：`MYSQLDUMP_PATH`（mysqldump 路径）、`BACKUP_KEEP`（保留份数）

**定时自动备份**（Windows 计划任务，每天凌晨 3 点）：
```bash
schtasks /create /tn "game_club_backup" /tr "C:\Users\18642\game_escort_club\backend\venv\Scripts\python.exe C:\Users\18642\game_escort_club\backend\backup_db.py" /sc daily /st 03:00
```

**恢复备份**：
```bash
"D:\MYsql\bin\mysql.exe" -u game_escort -p123456 game_escort_club < backups\游戏备份文件名.sql
```

## 好评率与投诉规则

- **好评率**：仅统计有效评价（normal 状态），好评 = 4 星及以上；**没有评价的打手显示 `-`**
- **自动默认好评**：结单后 3 天内老板未评价的订单，系统自动记为好评（后台每 5 分钟扫描）
- **老板投诉**：已完成订单可点击"投诉"，该订单自动改为差评（★1），打手投诉次数 +1
- **申诉撤销**：打手可对差评申请复查，管理员批准后撤销差评并扣回投诉次数，该订单从好评率统计中屏蔽

## 注册功能

- 登录页点击"注册账号"，可注册三种身份：
  - **老板**：注册后立即生效，可直接登录点单
  - **打手**：注册时可选填陪玩等级与自我介绍，需管理员在"注册审核"页审核通过后才能登录
  - **客服**：需管理员审核通过后才能登录
- 管理员侧边栏 →「注册审核」可查看待审核账号并执行**通过 / 驳回**
- 被驳回的账号登录时提示"账号审核未通过，无法登录"

## 常见问题

### 1. 前端请求失败 / 数据加载不出来
1. 确认后端已启动且窗口保持运行：终端应显示 `Uvicorn running on http://127.0.0.1:8000`
2. 确认前端 `API_BASE` 与后端端口一致：`frontend/index.html` 顶部默认为 `http://localhost:8000`
3. 浏览器按 `F12` → Console 查看报错：若是 `Failed to fetch` / `ERR_CONNECTION_REFUSED`，说明后端没起来或端口不对
4. 后端 CORS 已放开，file:// 直接打开和 Live Server 打开均可正常请求

### 2. 登录提示密码错误 / 账户被锁定
确认使用默认账号和密码 `123456`。连续输错 5 次会锁定 10 分钟；忘记密码可点击登录页"忘记密码？"直接重置（重置后自动解锁）。若要恢复初始数据，见上文「第 6 步：重置数据库」（MySQL 清库后重启即可重新初始化）。

### 3. 接口文档无法访问
确认后端正常启动，访问 `http://localhost:8000/docs`（Swagger 在线接口文档）。

### 4. `venv\Scripts\python` 不是内部或外部命令
说明 `backend\venv` 目录不存在或被删了。按"第 1 步"重新创建虚拟环境并"第 2 步"安装依赖。

### 5. 安装依赖时报错 / 超时
网络问题，换国内镜像源重装：
```bash
venv\Scripts\pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 6. 后端无法连接 MySQL（Can't connect / Access denied）
1. 确认本机 MySQL 服务已启动（`netstat -ano | findstr 3306` 应有监听）
2. 确认数据库和账号存在：库 `game_escort_club`、用户 `game_escort`/`123456`（创建语句见下方"数据库配置"）
3. 如使用其他账号/密码，通过环境变量覆盖：`MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DB`
4. 不想用 MySQL 时，可用环境变量回退 SQLite：`set DB_ENGINE=sqlite` 后启动

### 7. 后端启动提示端口被占用
```bash
netstat -ano | findstr 8000    # 查看占用8000端口的PID
taskkill /F /PID <PID>         # 结束占用进程后重新启动
```
或修改 `backend/main.py` 中的 `port=8000` 为其他端口，并同步修改前端 `API_BASE`。
