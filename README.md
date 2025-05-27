# 企业微信智能招聘机器人

基于 Python、企业微信自建应用框架和 DeepSeek LLM 的智能招聘助理，旨在自动化招聘流程中的候选人筛选、初步联系和简历管理。

> **注意：** 本项目已从早期的 `wcferry` 框架迁移到企业微信自建应用框架，提供更稳定、更安全的企业级解决方案。

## 项目概述

本项目是一个完整的智能招聘解决方案，包含两个核心流程：
1. **在线用户交互流程** - 通过企业微信应用处理招聘查询
2. **后台简历处理流程** - 自动化处理和入库PDF简历

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

## 技术架构

### 核心技术栈
*   **后端框架:** FastAPI + Uvicorn (ASGI服务器)
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
git clone <[repository_url](https://github.com/lin2000wl/WECOM_HR_PROJECT.git)>
cd HR_Project_Bot_2.0

# 创建虚拟环境
python -m venv .venv
# Windows
.\.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
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
  sync_timeout_seconds: 300
```

### 4. 启动服务
```bash
# 开发环境
python -m src.main_ew

# 生产环境 (推荐)
uvicorn src.main_ew:app --host 0.0.0.0 --port 8502
```

### 5. 后台简历处理
```bash
# 手动触发简历处理
python -m src.resume_pipeline.trigger
```

## 使用示例

### 查询示例
**私聊查询:**
```
找北京地区的软件工程师，5年以上经验，需要精通Python和Docker
搜索硕士及以上学历，有华为或腾讯工作经历的算法专家
给我推荐有PMP证书的项目经理
找中级工程师及以上，做过电气设计的
有没有一级建造师？
```

**群聊查询 (需要@机器人):**
```
@机器人 找深圳做嵌入式的，本科以上学历
@机器人 搜索在恒大干过的土建工程师
@机器人 需要高级职称的建筑设计师
```

### 交互流程
1. **发送查询** → 机器人解析并搜索
2. **接收结果** → Top N候选人列表 + AI摘要
3. **后续操作:**
   - `简历 1` → 获取第1位候选人简历
   - `信息 2` → 查看第2位候选人详情
   - `联系 3` → 联系第3位候选人
   - `A` → 查看更多候选人
   - `B` → 结束查询

### 外部联系人同步
**手动触发同步:**
```
更新外部联系人
/sync_contacts
```

**自动同步:**
- 系统根据配置的CRON表达式自动执行
- 默认每小时同步一次HR名下的外部联系人
- 自动匹配手机号并更新数据库
- 为成功同步的联系人打上标签

**同步结果通知示例:**
```
外部联系人同步完成报告：
📊 总计获取: 25个外部联系人
🔍 待处理: 18个 (已排除重复标签)
✅ 成功同步: 15个
❌ 同步失败: 3个

失败详情:
- 张三1234 [ext_123] - DB中未找到匹配手机号
- 李四5678 [ext_456] - 打标签失败
- 王五9012 [ext_789] - 外部联系人ID为空
```

## 项目结构

```
HR_Project_Bot_2.0/
├── .cursor/rules/          # 项目文档
│   ├── architecture.mdc    # 架构设计
│   ├── prd.mdc            # 产品需求
│   ├── procedure.mdc      # 流程文档
│   └── ...
├── src/                   # 源代码
│   ├── main_ew.py         # 企业微信主应用
│   ├── enterprise_wechat_service.py  # 企业微信API服务
│   ├── core_processor_ew.py          # 核心处理器
│   ├── handlers/          # 业务处理器
│   ├── models/           # 数据模型
│   ├── processors/       # 专用处理器
│   │   └── sync_processor.py  # 外部联系人同步处理器
│   ├── resume_pipeline/  # 简历处理管道
│   └── utils/           # 工具模块
├── data/                # 待处理简历
├── processed_resumes/   # 已处理简历
├── tests/              # 测试用例
├── config.yaml         # 主配置文件
├── .env               # 环境变量
└── requirements.txt   # Python依赖
```

## 部署指南

### 开发环境
1. 使用内网穿透工具 (ngrok/frp) 暴露本地端口
2. 配置企业微信回调URL指向公网地址
3. 启动FastAPI应用进行调试

### 生产环境
1. **服务器配置:**
   ```bash
   # 使用Supervisor管理进程
   sudo apt install supervisor
   
   # 配置Nginx反向代理
   sudo apt install nginx
   ```

2. **HTTPS配置:**
   ```nginx
   server {
       listen 443 ssl;
       server_name your_domain.com;
       
       ssl_certificate /path/to/cert.pem;
       ssl_certificate_key /path/to/key.pem;
       
       location /api/v1/wecom/callback {
           proxy_pass http://127.0.0.1:8502;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
       }
   }
   ```

3. **进程管理:**
   ```ini
   [program:hr_bot]
   command=/path/to/.venv/bin/uvicorn src.main_ew:app --host 127.0.0.1 --port 8502
   directory=/path/to/HR_Project_Bot_2.0
   user=hr_bot
   autostart=true
   autorestart=true
   ```

## 监控与维护

### 日志监控
*   应用日志: `logs/app.log`
*   新证书发现: `logs/new_certificates.log`
*   错误追踪: 详细的异常堆栈和上下文信息

### 性能监控
*   LLM API调用次数和耗时
*   数据库查询性能
*   并发处理能力
*   状态缓存命中率

### 定期维护
*   检查 `data/error/` 和 `data/pending/` 目录
*   更新证书等级规则 (`src/utils/ranking_data.py`)
*   优化LLM Prompt提升解析准确率
*   数据库索引优化
*   **外部联系人同步维护:**
    *   检查企业微信"已同步"标签是否存在
    *   监控同步失败率，及时处理格式不规范的备注
    *   定期清理过期的外部联系人数据
    *   验证HR用户权限和客户联系权限

## 开发文档

详细的开发文档位于 `.cursor/rules/` 目录：
*   `architecture.mdc` - 系统架构设计
*   `prd.mdc` - 产品需求文档  
*   `procedure.mdc` - 业务流程说明
*   `implementation.mdc` - 实施计划
*   `enterprise_wechat_development_guide.mdc` - 企业微信开发指南
*   `migration_plan_wcferry_to_wecom.mdc` - 迁移方案

## 贡献指南

1. Fork 项目
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

## 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 联系方式

如有问题或建议，请通过以下方式联系：
*   提交 Issue
*   发送邮件至项目维护者
*   企业微信群讨论

---

**注意事项:**
*   确保企业微信应用配置正确
*   定期备份MongoDB数据
*   监控LLM API使用量和成本
*   遵守数据隐私和安全规范
*   **外部联系人同步注意事项:**
    *   需要在企业微信后台预先创建"已同步"标签
    *   HR用户必须具有"客户联系"权限
    *   外部联系人备注格式需要包含有效手机号
    *   注意企业微信API调用频率限制
    *   定期检查同步失败的联系人并手动处理 
