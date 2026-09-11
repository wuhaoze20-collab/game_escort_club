# 大狗嚼电竞管理系统

基于 FastAPI + MySQL + 原生前端的完整前后端分离管理系统，实现多角色权限、内容管理、订单全流程、工资结算、打手评价、盈利统计等功能。

## 技术栈
- **后端**：Python 3.8+ / FastAPI / SQLAlchemy / MySQL / JWT鉴权 / bcrypt密码加密
- **前端**：原生HTML/CSS/JS + Tailwind CSS
- **开发工具**：VSCode

## 项目目录结构
```
game_escort_club/
├── backend/                 # 后端服务（FastAPI）
│   ├── api/                 # 接口路由
│   │   ├── __init__.py
│   │   ├── auth_api.py      # 认证登录接口
│   │   ├── content_api.py   # 公告/须知/价格/福利/支付方式等内容接口
│   │   ├── user_info_api.py # 用户资料/昵称审核接口
│   │   ├── order_api.py     # 点单/接单/结单/派单/统计等订单接口
│   │   ├── rating_api.py    # 打手评价/回复/复查接口
│   │   ├── stats_api.py     # 本月盈利统计接口
│   │   ├── tip_api.py       # 打赏接口
│   │   └── withdraw_api.py  # 打手提现接口
│   ├── database.py          # 数据库连接配置（默认 MySQL，可切换 SQLite）
│   ├── models.py            # 数据库表模型
│   ├── schemas.py           # 请求/响应数据模型
│   ├── auth.py              # JWT 鉴权与角色权限校验
│   ├── main.py              # 程序入口（启动时自动建表+初始化默认数据）
│   ├── requirements.txt     # Python 依赖清单
│   ├── game_club.db         # SQLite 数据库文件（首次运行自动生成，可删除重建）
│   └── venv/                # 虚拟环境（本机已创建，勿删除）
├── frontend/                # 前端页面（原生单页应用）
│   ├── index.html           # 单页入口
│   └── avatars/             # 默认头像图片（系统按角色/等级自动分配）
├── touxiangku/              # 原始头像素材库（仅供默认分配使用，任何人不可选用）
├── CHANGELOG.md             # 版本更新日志
└── README.md
```

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

- 启动成功标志：终端出现 `Uvicorn running on http://127.0.0.1:8000`，且首次启动自动完成**建表 + 初始化默认数据**（10 个测试账号、公告/价格等默认内容、6 名打手）
- 后端服务地址：`http://localhost:8000`
- 在线接口文档（Swagger）：`http://localhost:8000/docs`

**常见启动失败排查**：

| 现象 | 原因 | 解决办法 |
|---|---|---|
| `ModuleNotFoundError: No module named 'fastapi'` | 没用 venv 的 Python，或依赖没装 | 必须用 `venv\Scripts\python main.py` 启动，并先完成第 2 步 |
| `[Errno 10048] ... address already in use` | 8000 端口被占用 | 方法一：`netstat -ano | findstr 8000` 查出 PID 后 `taskkill /F /PID <PID>` 结束占用进程；方法二：改 `main.py` 里的 `port=8000` 为其他端口 |
| 启动无报错但页面连不上 | 后端没起来 / 前端 API 地址不对 | 确认终端停留在运行状态（不要关闭窗口）；确认 `frontend/index.html` 顶部 `API_BASE` 为 `http://localhost:8000` |

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
- 店铺公告、下单须知、价格预览、充值福利、会员福利、支付方式6个模块
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

### 12. 本月盈利（管理员专属）
- 本月总盈利（俱乐部抽成合计）、完成订单数、订单总额、打手发放总额
- 按打手汇总盈利明细

### 13. 工资结算
- 订单完成自动生成工资记录
- 记录订单原始金额、俱乐部抽成、打手收入
- 打手只能查看自己的工资记录

## 接口列表
| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| POST | /api/login | 登录获取令牌（连续错5次锁定10分钟） | 所有人 |
| POST | /api/reset-password | 忘记密码重置（输入账号+新密码） | 所有人 |
| POST | /api/change-password | 修改密码（校验原密码） | 所有登录用户 |
| GET | /api/content/all | 获取所有内容配置 | 所有登录用户 |
| GET | /api/content/{key} | 获取单个内容配置 | 所有登录用户 |
| PUT | /api/content/{key} | 更新内容配置 | 管理员/客服 |
| GET | /api/boss/list | 获取老板列表 | 管理员/客服 |
| GET | /api/player/list | 获取打手列表(含敏感数据) | 管理员/客服 |
| GET | /api/player/public | 获取打手公开列表(不含敏感数据) | 所有登录用户 |
| GET | /api/boss/me | 获取当前老板信息 | 老板 |
| GET | /api/player/me | 获取当前打手信息 | 打手 |
| PUT | /api/player/intro | 更新打手自我介绍 | 打手本人 |
| POST | /api/order/create | 创建订单(可指定打手,带备注) | 管理员/客服/老板 |
| POST | /api/order/{id}/assign | 人工派单 | 管理员/客服 |
| POST | /api/order/{id}/accept | 打手接受订单 | 打手本人 |
| POST | /api/order/{id}/reject | 打手拒绝订单 | 打手本人 |
| POST | /api/order/{id}/start | 开始服务 | 管理员/客服/打手 |
| POST | /api/order/{id}/complete | 完成订单并结算 | 管理员/客服 |
| POST | /api/order/{id}/cancel | 取消订单 | 管理员/客服/老板 |
| GET | /api/order/list | 获取订单列表 | 所有登录用户(按角色过滤) |
| GET | /api/order/salary/list | 获取工资记录 | 管理员/客服/打手 |
| POST | /api/rating/create | 评价打手 | 老板 |
| GET | /api/rating/player/{name} | 查询打手评价列表 | 所有登录用户 |
| PUT | /api/rating/{id}/reply | 打手回复评价 | 打手本人 |
| GET | /api/rating/my | 查询我的评价记录 | 老板 |
| POST | /api/tip/create | 打赏打手(≤订单30%) | 老板 |
| GET | /api/tip/player/me | 查询我的打赏记录 | 打手 |
| GET | /api/withdraw/available | 查询可提现金额(30天冷却) | 打手 |
| POST | /api/withdraw/create | 发起提现申请 | 打手 |
| GET | /api/withdraw/my | 查询我的提现记录 | 打手 |
| GET | /api/withdraw/list | 查询所有提现申请 | 管理员/客服 |
| POST | /api/withdraw/{id}/approve | 批准提现 | 管理员/客服 |
| POST | /api/withdraw/{id}/reject | 拒绝提现 | 管理员/客服 |
| GET | /api/stats/monthly-profit | 本月盈利统计 | 管理员 |

## 开发说明
1. 数据库表结构在 `backend/models.py`，修改后删除 `game_club.db` 重启服务会自动重建
2. 默认数据初始化在 `backend/main.py` 的 `init_default_data()`
3. 俱乐部抽成比例在 `backend/api/order_api.py` 的 `CLUB_COMMISSION_RATE` 常量
4. 生产环境请修改 `backend/auth.py` 的 `SECRET_KEY` 并收紧CORS配置

## 数据库配置（MySQL）

系统默认使用本机 MySQL 8（`D:\MySQL`，root 密码 `123456`）。首次使用时执行以下命令初始化库和专用账号：

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
确认使用默认账号和密码 `123456`。连续输错 5 次会锁定 10 分钟；忘记密码可点击登录页"忘记密码？"直接重置（重置后自动解锁）。若修改过数据库，删除 `game_club.db` 重启服务重新初始化。

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
