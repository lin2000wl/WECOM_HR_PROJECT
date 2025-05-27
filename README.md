# 企业微信智能招聘机器人

基于 Python、企业微信自建应用框架和 DeepSeek LLM 的智能招聘助理，旨在自动化招聘流程中的候选人筛选、初步联系和简历管理。

> **注意：** 本项目已从早期的 `wcferry` 框架迁移到企业微信自建应用框架，提供更稳定、更安全的企业级解决方案。

## 项目概述

本项目是一个完整的智能招聘解决方案，包含以下核心组件：

### 🎯 主要服务组件
1. **智能招聘机器人主服务** (`src/`) - 通过企业微信应用处理招聘查询和简历管理的核心服务
2. **URL验证服务** (`url_verification/`) - 独立的企业微信回调URL验证服务，用于开发调试和回调测试
3. **代理转发服务** (`wework_proxy_app/`) - HTTP代理转发服务，解决内网部署与企业微信公网回调的连接问题
4. **后台简历处理流程** - 自动化处理和入库PDF简历的离线处理系统

### 🏗️ 架构优势
- **模块化设计:** 各服务独立部署，可根据需要灵活组合
- **开发友好:** URL验证服务便于快速测试企业微信回调配置
- **部署灵活:** 代理服务解决内网部署难题，支持多种网络环境
- **生产就绪:** 完整的错误处理、日志记录和监控机制

## 主要功能

### 🤖 企业微信智能交互
*   **企业微信集成:** 基于 FastAPI 构建的回调服务器，支持企业微信消息加解密、签名校验
*   **多场景支持:** 支持私聊和群聊@机器人两种交互方式
*   **并发处理:** 使用线程池实现多用户并发查询，响应迅速
*   **状态管理:** 带TTL的会话状态管理，支持3分钟超时自动清理

### 🧠 智能查询理解
*   **自然语言解析:** 利用 DeepSeek LLM 解析复杂的招聘查询指令
*   **高级语义理解:**
    *   **学历范围:** 理解"本科以上"、"硕士及以上"等范围表达
    *   **学历同义词:** 自动扩展"本科"/"学士"等同义词
    *   **公司经验:** 提取并模糊匹配过往公司名称
    *   **证书/职称等级:** 支持"中级工程师及以上"、"一级建造师"等复杂查询
    *   **职位/证书歧义:** 智能区分查询意图
    *   **设计类别:** 识别"建筑设计"、"电气设计"、"给排水设计"等专业分类

### 🎯 智能筛选与排序
*   **多维度评分:** 基于经验、技能、地点、证书、学历等维度进行综合评分
*   **配置化规则:** 通过 `config.yaml` 灵活配置评分权重和逻辑
*   **智能排序:** 返回评分最高的Top N候选人
*   **AI摘要生成:** 自动生成候选人对比分析摘要

### 📋 交互式结果展示
*   **结构化展示:** 清晰展示候选人关键信息和AI分析摘要
*   **按需操作:** 支持多种后续操作
    *   `简历 X` - 获取候选人简历PDF文件
    *   `信息 X` - 查看候选人详细信息
    *   `联系 X` - 自动发送初步沟通消息
    *   `A` - 查看更多符合条件的候选人
    *   `B` - 结束当前查询

### 👥 外部联系人同步
*   **批量获取:** 通过企业微信API批量获取HR名下的外部联系人信息
*   **智能匹配:** 根据外部联系人的手机号自动匹配内部数据库中的候选人记录
*   **数据同步:** 将匹配成功的外部联系人ID更新到内部数据库
*   **标签管理:** 为成功同步的外部联系人自动打上"已同步"标签
*   **触发方式:** 支持手动指令触发和定时自动同步两种模式
*   **结果通知:** 同步完成后自动发送统计报告和失败列表

### 📄 后台简历处理
*   **自动化流程:** 扫描、提取、解析、校验、入库一体化
*   **多格式支持:** PDF文本提取 + OCR备选方案
*   **智能解析:** LLM提取结构化简历信息
*   **文件管理:** 自动分类处理（成功/失败/待处理）
*   **数据入库:** MongoDB存储，支持Upsert操作

### 🔐 URL验证服务 (`url_verification/`)
*   **独立验证服务:** 基于Flask的企业微信回调URL验证服务
*   **加密解密:** 完整的企业微信消息加解密功能
*   **多端点支持:** 支持多种回调路径配置（`/`, `/wework-callback`, `/wechat_callback`）
*   **调试友好:** 详细的请求日志和错误处理
*   **快速部署:** 独立运行，便于测试和调试企业微信回调配置

### 🌐 代理转发服务 (`wework_proxy_app/`)
*   **透明代理:** HTTP请求透明转发，保持数据完整性
*   **路径映射:** 自动处理`/wework-callback/*`路径转发到内网目标服务器
*   **错误处理:** 完善的超时和连接错误处理机制
*   **生产就绪:** 支持负载均衡和反向代理配置
*   **内网穿透:** 解决企业微信回调URL必须公网访问的问题

## 技术架构

### 核心技术栈
*   **后端框架:** FastAPI + Uvicorn (主服务) / Flask (验证和代理服务)
*   **企业微信集成:** httpx (API调用) + WXBizMsgCrypt (消息加解密)
*   **自然语言处理:** DeepSeek LLM API (通过 openai SDK)
*   **数据库:** MongoDB + pymongo 驱动
*   **并发处理:** Python threading.ThreadPoolExecutor
*   **状态管理:** cachetools.TTLCache (线程安全)

### 文档处理
*   **PDF处理:** PyPDF2/pdfminer.six (文本提取) + pdf2image + Pillow
*   **OCR引擎:** pytesseract (Tesseract OCR Python包装器)
*   **配置管理:** PyYAML + python-dotenv
*   **日志系统:** Python logging模块

### 数据模型
*   **候选人信息:** 基本信息、工作经历、教育背景、技能证书
*   **查询标签:** 优化的检索字段（positions, skills, degrees, certifications等）
*   **文件路径:** 标准化的简历文件存储路径

## 项目结构

```
HR_Project_Bot_2.0/
├── src/                          # 主要源代码
│   ├── main_ew.py               # 企业微信版主应用 (FastAPI)
│   ├── enterprise_wechat_service.py  # 企业微信API服务
│   ├── core_processor_ew.py     # 核心处理器
│   ├── db_interface.py          # 数据库接口
│   ├── llm_client.py           # LLM客户端
│   ├── state_manager.py        # 状态管理器
│   ├── config_ew.py            # 企业微信配置
│   ├── logger.py               # 日志模块
│   ├── handlers/               # 业务处理器
│   │   ├── auth_handler_ew.py  # 认证处理器
│   │   ├── intent_handler.py   # 意图识别
│   │   ├── query_handler.py    # 查询处理
│   │   └── selection_handler.py # 选择处理
│   ├── models/                 # 数据模型
│   │   └── candidate.py        # 候选人模型
│   ├── processors/             # 专用处理器
│   │   └── sync_processor.py   # 外部联系人同步处理器
│   ├── resume_pipeline/        # 简历处理管道
│   │   ├── trigger.py          # 触发器
│   │   ├── scanner.py          # 文件扫描器
│   │   ├── text_extractor.py   # 文本提取器
│   │   ├── ocr_processor.py    # OCR处理器
│   │   ├── resume_parser.py    # 简历解析器
│   │   ├── validator_standardizer.py # 校验标准化器
│   │   ├── file_manager.py     # 文件管理器
│   │   └── db_updater.py       # 数据库更新器
│   └── utils/                  # 工具函数
│       └── scoring_utils.py    # 评分工具
├── url_verification/           # URL验证服务
│   ├── app.py                  # Flask验证应用
│   ├── crypto_utils.py         # 加密解密工具
│   ├── requirements.txt        # 验证服务依赖
│   └── README.md              # 验证服务文档
├── wework_proxy_app/          # 代理转发服务
│   ├── app.py                 # Flask代理应用
│   ├── requirements.txt       # 代理服务依赖
│   └── README.md             # 代理服务文档
├── data/                      # 原始简历文件
│   ├── error/                 # 处理失败的文件
│   └── pending/               # 待人工处理的文件
├── processed_resumes/         # 处理成功的简历
├── logs/                      # 日志文件
├── tests/                     # 测试文件
├── docs/                      # 项目文档
├── config.yaml               # 主配置文件
├── requirements.txt          # 主项目依赖
├── .env.example             # 环境变量示例
└── README.md                # 项目说明
```

## 环境要求

### 基础环境
*   **操作系统:** Windows/Linux (推荐Linux用于生产部署)
*   **Python:** 3.8+ 
*   **MongoDB:** 可访问的MongoDB实例
*   **企业微信:** 已创建的自建应用和配置的回调URL

### 可选组件
*   **Tesseract OCR:** 处理图片型PDF (需安装中文语言包)
*   **Poppler:** pdf2image依赖 (PDF转图片)
*   **反向代理:** Nginx/Caddy (生产环境推荐)

## 快速开始

### 1. 环境准备
```bash
# 克隆项目
git clone https://github.com/lin2000wl/WECOM_HR_PROJECT.git
cd HR_Project_Bot_2.0

# 创建虚拟环境
python -m venv .venv
# Windows
.\.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

# 安装主项目依赖
pip install -r requirements.txt

# 安装URL验证服务依赖（如需要）
cd url_verification
pip install -r requirements.txt
cd ..

# 安装代理转发服务依赖（如需要）
cd wework_proxy_app
pip install -r requirements.txt
cd ..
```

### 2. 企业微信配置
1. **创建自建应用:**
   - 登录企业微信管理后台 → 应用管理 → 自建应用
   - 记录 CorpID、AgentID、Secret

2. **配置回调:**
   - 设置回调URL: `https://your_domain.com/api/v1/wecom/callback`
   - 配置Token和EncodingAESKey
   - 配置可信IP白名单

### 3. 配置文件设置

创建 `.env` 文件：
```env
# 企业微信配置
WECOM_CORP_ID="your_corp_id"
WECOM_AGENT_ID="your_agent_id" 
WECOM_APP_SECRET="your_app_secret"
WECOM_CALLBACK_TOKEN="your_callback_token"
WECOM_CALLBACK_AES_KEY="your_callback_aes_key"

# LLM配置
DEEPSEEK_API_KEY="your_deepseek_api_key"
DEEPSEEK_API_BASE="https://api.deepseek.com"

# MongoDB配置
MONGO_URI="mongodb://localhost:27017/"
MONGO_DATABASE="hr_recruitment"

# 授权用户
AUTHORIZED_USER_IDS_EW="userid1,userid2"

# 外部联系人同步配置
TAG_ID_SYNC_SUCCESS="your_sync_success_tag_id"
SYNC_HR_USERIDS="hr_userid1,hr_userid2"
SYNC_SCHEDULE_CRON="0 * * * *"  # 每小时执行一次，可选
```

配置 `config.yaml`：
```yaml
# 详细配置请参考项目中的config.yaml示例
database:
  mongodb:
    uri: "mongodb://localhost:27017/"
    database: "hr_recruitment"
    collection: "candidates"

llm:
  deepseek:
    query_model: "deepseek-chat"
    resume_model: "deepseek-chat"
    summary_model: "deepseek-chat"

paths:
  data: "./data"
  processed: "./processed_resumes"
  error: "./data/error"
  pending: "./data/pending"

cache:
  ttl_seconds: 180

scoring_rules:
  initial_candidate_pool_size: 30
  # ... 其他评分配置

# 外部联系人同步配置
external_contact_sync:
  enabled: true
  batch_size: 100
```

### 4. 运行服务

#### 方式一：独立运行各服务

**主招聘机器人服务:**
```bash
# 在项目根目录
python src/main_ew.py
# 或使用uvicorn
uvicorn src.main_ew:app --host 0.0.0.0 --port 8502
```

**URL验证服务（用于测试企业微信回调配置）:**
```bash
cd url_verification
python app.py
# 默认运行在 http://0.0.0.0:8502
```

**代理转发服务（用于内网部署）:**
```bash
cd wework_proxy_app
# 先配置.env文件中的TARGET_SERVER_URL
echo "TARGET_SERVER_URL=http://your-internal-server.com" > .env
python app.py
# 默认运行在 http://0.0.0.0:8502
```

#### 方式二：生产环境部署

**使用Supervisor管理服务:**
```ini
# /etc/supervisor/conf.d/hr_bot.conf
[program:hr_bot_main]
command=/path/to/venv/bin/uvicorn src.main_ew:app --host 0.0.0.0 --port 8502
directory=/path/to/HR_Project_Bot_2.0
user=your_user
autostart=true
autorestart=true
stdout_logfile=/var/log/hr_bot_main.log
stderr_logfile=/var/log/hr_bot_main_error.log

[program:hr_bot_proxy]
command=/path/to/venv/bin/python wework_proxy_app/app.py
directory=/path/to/HR_Project_Bot_2.0
user=your_user
autostart=true
autorestart=true
stdout_logfile=/var/log/hr_bot_proxy.log
stderr_logfile=/var/log/hr_bot_proxy_error.log
```

**Nginx反向代理配置:**
```nginx
server {
    listen 443 ssl;
    server_name your_domain.com;
    
    # SSL配置...
    
    # 主服务路由
    location /api/v1/wecom/callback {
        proxy_pass http://localhost:8502/api/v1/wecom/callback;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    # 代理转发路由（如果使用代理模式）
    location /wework-callback/ {
        proxy_pass http://localhost:8503/wework-callback/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 5. 测试验证

**测试URL验证服务:**
```bash
# 访问验证端点
curl "http://localhost:8502/?msg_signature=xxx&timestamp=xxx&nonce=xxx&echostr=xxx"
```

**测试代理转发:**
```bash
# 测试代理转发功能
curl "http://localhost:8502/wework-callback/test"
```

**测试主服务:**
- 在企业微信应用中发送消息给机器人
- 查看日志确认消息接收和处理

## 使用指南

### 基本查询示例
```
# 在企业微信中发送以下消息给机器人：

"找一个本科以上学历的建筑设计师，有恒大工作经验，会CAD和Revit"

"需要一级建造师证书，5年以上施工经验，在深圳工作"

"招聘电气工程师，中级职称及以上，熟悉强电设计"
```

### 外部联系人同步
```
# 手动触发同步（在企业微信中发送）：
"更新外部联系人"

# 同步结果示例：
本次外部联系人同步完成！
📊 统计信息：
- 总获取联系人数：25
- 待处理联系人数：20  
- 成功同步并标记：15
- 同步失败：5

❌ 以下联系人同步失败：
[张三] [external_userid_123] - 原因：手机号格式不正确
[李四] [external_userid_456] - 原因：数据库中未找到匹配记录
```

### 后台简历处理
```bash
# 手动触发简历处理
python src/resume_pipeline/trigger.py

# 查看处理日志
tail -f logs/resume_processing.log
```

### URL验证服务使用指南

**适用场景：**
- 企业微信回调URL配置测试
- 开发环境快速验证
- 消息加解密功能调试
- 回调参数格式验证

**配置步骤：**
1. **配置环境变量** (`url_verification/.env`)：
```env
FLASK_APP=app.py
FLASK_RUN_PORT=8502
FLASK_DEBUG=True
WECOM_CORP_ID="your_corp_id"
WECOM_CALLBACK_TOKEN="your_callback_token"
WECOM_CALLBACK_AES_KEY="your_callback_aes_key"
```

2. **启动验证服务：**
```bash
cd url_verification
python app.py
```

3. **配置企业微信回调URL：**
   - URL: `https://your_domain.com/` 或 `https://your_domain.com/wework-callback`
   - 支持多种路径格式：`/`, `/wework-callback`, `/wechat_callback`

**调试功能：**
- 详细的请求日志记录
- 加解密过程可视化
- 错误信息详细输出
- 支持GET验证和POST消息接收

### 代理转发服务使用指南

**适用场景：**
- 内网服务器部署，需要公网回调访问
- 多环境部署（开发/测试/生产）
- 负载均衡和故障转移
- 网络隔离环境下的服务连接

**部署架构：**
```
企业微信服务器 → 公网代理服务器 → 内网目标服务器
     ↓                    ↓                ↓
  回调请求         wework_proxy_app      主招聘服务
```

**配置步骤：**
1. **公网服务器配置** (`wework_proxy_app/.env`)：
```env
FLASK_APP=app.py
FLASK_RUN_PORT=8502
FLASK_DEBUG=False  # 生产环境
TARGET_SERVER_URL="http://192.168.1.100:8502"  # 内网目标服务器
```

2. **启动代理服务：**
```bash
cd wework_proxy_app
python app.py
```

3. **Nginx配置示例：**
```nginx
upstream hr_bot_proxy {
    server 127.0.0.1:8502;
    # 可配置多个代理实例实现负载均衡
    # server 127.0.0.1:8503 backup;
}

server {
    listen 443 ssl;
    server_name your_domain.com;
    
    location /wework-callback/ {
        proxy_pass http://hr_bot_proxy/wework-callback/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # 超时配置
        proxy_connect_timeout 30s;
        proxy_send_timeout 30s;
        proxy_read_timeout 30s;
    }
}
```

**监控和故障排除：**
- 代理服务提供详细的转发日志
- 支持超时和连接错误处理
- 自动重试机制（可配置）
- 健康检查端点

### 服务部署最佳实践

**开发环境：**
```bash
# 1. 使用URL验证服务快速测试
cd url_verification && python app.py

# 2. 配置内网穿透（如ngrok）
ngrok http 8502

# 3. 在企业微信后台配置ngrok提供的公网URL
```

**生产环境：**
```bash
# 1. 使用代理转发模式
# 公网服务器运行代理服务
cd wework_proxy_app && python app.py

# 2. 内网服务器运行主服务
cd .. && python src/main_ew.py

# 3. 配置Nginx反向代理和SSL
# 4. 使用Supervisor管理进程
# 5. 配置日志轮转和监控
```

## 监控与维护

### 关键监控指标

**主服务监控：**
*   **服务可用性:** 各服务的运行状态和响应时间
*   **消息处理:** 企业微信消息接收和处理成功率
*   **LLM调用:** API调用次数、成功率、响应时间
*   **数据库性能:** 查询响应时间、连接数
*   **简历处理:** 处理成功率、错误分类统计
*   **外部联系人同步:** 同步成功率、失败原因分析

**URL验证服务监控：**
*   **验证成功率:** 企业微信回调URL验证的成功率
*   **加解密性能:** 消息加解密处理时间
*   **错误率:** 验证失败和解密错误的频率
*   **请求量:** 验证请求的数量和频率

**代理转发服务监控：**
*   **转发成功率:** HTTP请求转发的成功率
*   **响应时间:** 端到端请求响应时间
*   **目标服务健康:** 内网目标服务器的可达性
*   **连接池状态:** 并发连接数和连接池使用情况
*   **错误类型分布:** 超时、连接失败等错误的分类统计

### 日志管理

**主服务日志：**
*   **应用日志:** `logs/app.log` - 主要业务逻辑日志
*   **错误日志:** `logs/error.log` - 错误和异常信息
*   **简历处理日志:** 简历处理流程的详细记录

**URL验证服务日志：**
*   **验证日志:** `url_verification/logs/` - URL验证和消息处理日志
*   **加解密日志:** 详细的加解密过程记录
*   **调试日志:** 开发环境下的详细调试信息

**代理转发服务日志：**
*   **转发日志:** `wework_proxy_app/logs/` - 请求转发记录
*   **性能日志:** 响应时间和性能指标
*   **错误日志:** 转发失败和连接错误记录

**系统日志：**
*   **Nginx访问日志:** 反向代理访问记录
*   **Supervisor日志:** 进程管理和重启记录

### 维护建议

**日常维护：**
*   **定期检查:** 每日检查服务状态和错误日志
*   **数据备份:** 定期备份MongoDB数据和简历文件
*   **依赖更新:** 定期更新Python依赖包
*   **性能优化:** 根据使用情况调整配置参数
*   **容量规划:** 监控存储空间和数据库大小

**安全维护：**
*   **证书更新:** 定期更新SSL证书
*   **密钥轮换:** 定期更换企业微信Token和AESKey
*   **访问审计:** 检查异常访问和登录记录
*   **权限检查:** 验证文件和目录权限设置

**服务维护：**
*   **进程监控:** 使用Supervisor确保服务自动重启
*   **资源监控:** 监控CPU、内存、磁盘使用情况
*   **网络监控:** 检查网络连接和带宽使用
*   **依赖服务:** 监控MongoDB、Nginx等依赖服务状态

### 故障排除

**企业微信回调相关问题：**

1. **回调URL验证失败**
   ```bash
   # 检查URL验证服务
   cd url_verification
   python app.py
   # 查看验证日志
   tail -f logs/verification.log
   ```
   - 检查CorpID、Token、AESKey配置
   - 验证公网域名和SSL证书
   - 使用URL验证服务进行调试

2. **消息接收失败**
   ```bash
   # 检查主服务日志
   tail -f logs/app.log | grep "callback"
   # 检查代理转发日志
   cd wework_proxy_app && tail -f logs/proxy.log
   ```
   - 验证回调URL路径配置
   - 检查代理转发服务状态
   - 确认内网目标服务器可达性

**代理转发相关问题：**

3. **代理转发超时**
   ```bash
   # 检查目标服务器连通性
   curl -v http://target-server:8502/health
   # 调整超时配置
   vim wework_proxy_app/.env
   ```
   - 检查TARGET_SERVER_URL配置
   - 验证内网网络连接
   - 调整超时参数设置

4. **负载均衡问题**
   ```bash
   # 检查Nginx配置
   nginx -t
   # 重载Nginx配置
   nginx -s reload
   ```
   - 验证upstream配置
   - 检查健康检查设置
   - 监控后端服务状态

**服务性能问题：**

5. **LLM调用失败**
   - 检查API Key配置和余额
   - 验证网络连接和防火墙
   - 查看API调用日志和错误码

6. **数据库连接问题**
   - 检查MongoDB服务状态
   - 验证连接字符串和认证
   - 监控连接池使用情况

7. **简历处理失败**
   - 检查文件权限和存储空间
   - 验证OCR组件安装和配置
   - 查看处理日志和错误分类

8. **外部联系人同步问题**
   - 检查企业微信API权限和配额
   - 验证标签ID和HR用户ID配置
   - 查看同步日志和失败原因

**紧急故障处理：**

```bash
# 快速重启所有服务
sudo supervisorctl restart all

# 检查服务状态
sudo supervisorctl status

# 查看最近的错误日志
tail -n 100 /var/log/hr_bot_*_error.log

# 检查系统资源
top
df -h
free -m

# 检查网络连接
netstat -tlnp | grep :8502
curl -I https://your_domain.com/api/v1/wecom/callback
```

## 开发指南

### 代码结构
*   **模块化设计:** 各功能模块独立，便于维护和扩展
*   **配置驱动:** 通过配置文件管理各种参数
*   **异步处理:** 使用线程池处理并发请求
*   **错误处理:** 完善的异常捕获和日志记录

### 扩展开发
*   **新增查询类型:** 在LLM Prompt中添加新的解析规则
*   **自定义评分规则:** 修改`config.yaml`中的评分配置
*   **新增消息类型:** 在handlers中添加新的处理逻辑
*   **集成其他服务:** 通过API接口集成外部系统

### 测试
```bash
# 运行单元测试
python -m pytest tests/

# 运行特定测试
python -m pytest tests/test_llm_client.py

# 生成测试覆盖率报告
python -m pytest --cov=src tests/
```

## 许可证

本项目采用 MIT 许可证。详情请参阅 [LICENSE](LICENSE) 文件。

## 贡献

欢迎提交 Issue 和 Pull Request 来改进本项目。

## 联系方式

如有问题或建议，请通过以下方式联系：
- GitHub Issues: [项目Issues页面](https://github.com/lin2000wl/WECOM_HR_PROJECT/issues)
- 项目仓库: [https://github.com/lin2000wl/WECOM_HR_PROJECT](https://github.com/lin2000wl/WECOM_HR_PROJECT) 