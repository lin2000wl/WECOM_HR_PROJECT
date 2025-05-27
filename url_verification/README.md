# 企业微信URL验证服务 (url_verification)

## 项目概述

这是一个基于 Flask 的企业微信回调服务器，专门用于处理企业微信的 URL 验证和消息回调。该服务器实现了企业微信开发所需的基本功能，包括 URL 验证、消息接收和响应处理。

## 项目结构

```
url_verification/
├── app.py              # Flask 应用主文件
├── crypto_utils.py     # 加密解密工具函数
├── requirements.txt    # Python 依赖列表
├── env.example         # 环境变量配置示例
└── README.md          # 项目说明文档
```

## 主要功能

### 1. URL 验证服务
- **路由**: `/` 和 `/wework-callback` (GET 请求)
- **功能**: 处理企业微信的 URL 验证请求
- **实现**: 使用 `crypto_utils.validate_url` 函数进行签名验证和解密

### 2. 消息回调处理
- **路由**: `/wechat_callback` (GET/POST 请求)
- **功能**: 
  - GET: 企业微信 URL 有效性验证
  - POST: 接收企业微信推送的加密消息
- **特点**: 包含详细的调试日志输出

## 环境配置

### 必需的环境变量

复制 `env.example` 为 `.env` 文件并配置以下变量：

```env
TOKEN=your_wework_token
ENCODING_AES_KEY=your_encoding_aes_key
CORP_ID=your_corp_id
FLASK_RUN_PORT=8502
FLASK_DEBUG=True
```

### 依赖项

参见 `requirements.txt` 文件：
```
Flask==2.3.2
python-dotenv==1.0.0
pycryptodome==3.19.1
requests==2.31.0
```

## 安装和运行

### 1. 进入项目目录
```bash
cd url_verification
```

### 2. 安装依赖
```bash
pip install -r requirements.txt
```

### 3. 配置环境变量
```bash
cp env.example .env
# 编辑 .env 文件，填入企业微信应用的配置信息
```

### 4. 运行服务器
```bash
python app.py
```

服务器将在 `http://0.0.0.0:8502` 启动，开启调试模式。

## API 接口

### GET `/` 或 `/wework-callback`
**用途**: 企业微信 URL 验证

**参数**:
- `msg_signature`: 消息签名
- `timestamp`: 时间戳
- `nonce`: 随机数
- `echostr`: 加密的随机字符串

**响应**: 解密后的 echostr 内容

### GET/POST `/wechat_callback`
**用途**: 企业微信消息回调处理

**GET 请求** (URL 验证):
- 参数同上
- 简化实现：直接返回 echostr 参数

**POST 请求** (消息接收):
- 接收企业微信推送的加密消息
- 当前为简化实现，直接返回 "success"

## 开发说明

### 当前实现状态
- ✅ URL 验证功能完整实现
- ✅ 基础消息接收框架
- ⚠️ 消息解密和业务处理逻辑为占位实现

### 待完善功能
1. **完整的消息解密**: 需要实现 `WXBizMsgCrypt` 类
2. **业务消息处理**: 根据具体需求处理不同类型的消息
3. **消息回复**: 实现加密回复消息的功能

### 调试信息
服务器会输出详细的请求日志，包括：
- 请求方法和路径
- 请求头信息
- 验证参数
- 消息内容（POST 请求）

## 安全注意事项

1. **生产环境配置**:
   - 关闭调试模式 (`debug=False`)
   - 使用 HTTPS
   - 配置适当的防火墙规则

2. **敏感信息保护**:
   - 不要在代码中硬编码 TOKEN 等敏感信息
   - 使用环境变量管理配置

3. **错误处理**:
   - 当前实现包含基本的错误处理
   - 建议添加更详细的日志记录

## 相关文件

- `crypto_utils.py`: 加密解密工具函数
- `.env`: 环境变量配置文件
- `requirements.txt`: Python 依赖列表

## 企业微信开发文档

参考企业微信官方开发文档：
- [企业微信API文档](https://developer.work.weixin.qq.com/document/)
- [回调模式开发指南](https://developer.work.weixin.qq.com/document/path/90930) 