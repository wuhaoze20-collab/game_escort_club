# 游戏护航俱乐部管理系统

基于 FastAPI + SQLite + 原生前端的完整前后端分离管理系统，实现多角色权限、内容管理、订单全流程、工资结算、打手评价、盈利统计等功能。

## 技术栈
- **后端**：Python 3.8+ / FastAPI / SQLAlchemy / SQLite / JWT鉴权 / bcrypt密码加密
- **前端**：原生HTML/CSS/JS + Tailwind CSS
- **开发工具**：VSCode

## 项目目录结构
```
game_escort_club/
├── backend/                 # 后端服务
│   ├── api/                 # 接口路由
│   │   ├── __init__.py
│   │   ├── auth_api.py      # 认证接口
│   │   ├── content_api.py   # 内容管理接口
│   │   ├── user_info_api.py # 用户信息接口
│   │   ├── order_api.py     # 订单业务接口
│   │   ├── rating_api.py    # 打手评价接口
│   │   └── stats_api.py     # 盈利统计接口
│   ├── database.py          # 数据库连接配置
│   ├── models.py            # 数据库表模型
│   ├── schemas.py           # 请求响应数据模型
│   ├── auth.py              # 鉴权与权限校验
│   ├── main.py              # 程序入口
│   ├── requirements.txt     # 依赖清单
│   └── game_club.db         # SQLite数据库文件（运行后自动生成）
└── frontend/                # 前端页面
    └── index.html           # 单页应用
```

## 快速启动

### 1. 创建虚拟环境并安装依赖（第一次）
在 VSCode 中打开终端，进入 backend 目录：
```bash
cd backend
python -m venv venv          # 创建虚拟环境（Windows）
venv\Scripts\activate        # 激活虚拟环境（Windows）
pip install -r requirements.txt   # 安装依赖
```

### 2. 启动后端服务
```bash
cd backend
venv\Scripts\python main.py   # 使用虚拟环境的Python启动服务
```
启动后后端运行在 `http://localhost:8000`，访问 `http://localhost:8000/docs` 可查看自动生成的接口文档。

### 3. 启动前端页面
在 VSCode 中右键 `frontend/index.html`，选择 **Open with Live Server**（需先安装 Live Server 插件），浏览器自动打开页面。

> 注意：前端默认请求 `http://localhost:8000`，如后端端口修改，请同步修改 `frontend/index.html` 顶部的 `API_BASE` 常量。

## 测试账号（统一密码：123456）
| 账号 | 角色 | 权限说明 |
|---|---|---|
| guanliyuan | 管理员 | 全部权限，可查看所有信息、编辑内容、管理订单、查看本月盈利 |
| kefu | 客服 | 可查看所有老板/打手信息，可编辑基础内容，可管理订单 |
| laoban / laoban_02 / laoban_03 | 老板 | 可查看基础内容，可点单并直接指定打手、评价打手、查看自己的账户信息 |
| dashou / dashou_02 / dashou_03 | 打手 | 可查看基础内容，可编辑自我介绍、开始自己的订单、查看自己的账户信息 |

## 核心功能
### 1. 多角色权限体系
- JWT令牌鉴权，登录后24小时有效
- 后端接口级权限校验，越权请求返回403
- 前端菜单和按钮按角色动态显示
- 打手公开数据与敏感数据隔离：老板点单只能看到接单数、好评率、投诉、自我介绍，后台金额等敏感信息仅管理员/客服可见

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
- 选择打手直接下单，订单自动进入"已分配"状态
- 我的订单列表：可取消待分配/已分配订单，已完成订单可评价打手

### 5. 打手自我介绍
- 打手可在"我的账户"页面编辑自我介绍
- 自我介绍实时展示给所有老板，作为点单参考

### 6. 打手评价模块
- 老板对已完成订单评价（1-5星 + 文字），一单一评，不可重复
- 评价自动更新打手好评率（4星及以上算好评）
- 所有老板点单时可见其他老板的评价

### 7. 订单全流程
- 创建订单（自动校验老板余额，冻结对应金额；老板点单可直接指定打手）
- 分配打手 / 开始服务 / 完成订单（自动结算：俱乐部抽成30%，打手收入自动入账，统计自动更新）
- 取消订单（自动退回老板余额）
- 订单列表按角色过滤

### 8. 本月盈利（管理员专属）
- 本月总盈利（俱乐部抽成合计）、完成订单数、订单总额、打手发放总额
- 按打手汇总盈利明细

### 9. 工资结算
- 订单完成自动生成工资记录
- 记录订单原始金额、俱乐部抽成、打手收入
- 打手只能查看自己的工资记录

## 接口列表
| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| POST | /api/login | 登录获取令牌 | 所有人 |
| GET | /api/content/all | 获取所有内容配置 | 所有登录用户 |
| GET | /api/content/{key} | 获取单个内容配置 | 所有登录用户 |
| PUT | /api/content/{key} | 更新内容配置 | 管理员/客服 |
| GET | /api/boss/list | 获取老板列表 | 管理员/客服 |
| GET | /api/player/list | 获取打手列表(含敏感数据) | 管理员/客服 |
| GET | /api/player/public | 获取打手公开列表(不含敏感数据) | 所有登录用户 |
| GET | /api/boss/me | 获取当前老板信息 | 老板 |
| GET | /api/player/me | 获取当前打手信息 | 打手 |
| PUT | /api/player/intro | 更新打手自我介绍 | 打手本人 |
| POST | /api/order/create | 创建订单(可指定打手) | 管理员/客服/老板 |
| POST | /api/order/{id}/assign | 分配打手 | 管理员/客服 |
| POST | /api/order/{id}/start | 开始服务 | 管理员/客服/打手 |
| POST | /api/order/{id}/complete | 完成订单并结算 | 管理员/客服 |
| POST | /api/order/{id}/cancel | 取消订单 | 管理员/客服/老板 |
| GET | /api/order/list | 获取订单列表 | 所有登录用户(按角色过滤) |
| GET | /api/order/salary/list | 获取工资记录 | 管理员/客服/打手 |
| POST | /api/rating/create | 评价打手 | 老板 |
| GET | /api/rating/player/{name} | 查询打手评价列表 | 所有登录用户 |
| GET | /api/rating/my | 查询我的评价记录 | 老板 |
| GET | /api/stats/monthly-profit | 本月盈利统计 | 管理员 |

## 开发说明
1. 数据库表结构在 `backend/models.py`，修改后删除 `game_club.db` 重启服务会自动重建
2. 默认数据初始化在 `backend/main.py` 的 `init_default_data()`
3. 俱乐部抽成比例在 `backend/api/order_api.py` 的 `CLUB_COMMISSION_RATE` 常量
4. 生产环境请修改 `backend/auth.py` 的 `SECRET_KEY` 并收紧CORS配置

## 常见问题
### 1. 前端请求失败
确认后端已启动，且前端 `API_BASE` 地址正确。后端CORS已放开。

### 2. 登录提示密码错误
确认使用默认账号和密码 `123456`。若修改过数据库，删除 `game_club.db` 重启服务重新初始化。

### 3. 接口文档无法访问
确认后端正常启动，访问 `http://localhost:8000/docs`。
