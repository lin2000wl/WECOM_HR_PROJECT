# 企业微信代理转发服务 (wework_proxy_app/app.py)

## 项目概述

这是一个基于 Flask 的 HTTP 代理转发服务，专门用于将企业微信回调请求从公网域名转发到内网目标服务器。该服务作为中间代理层，解决了企业微信回调 URL 需要公网访问而实际处理服务在内网的问题。

## 核心功能

### HTTP 请求代理转发
- **监听路径**: `/wework-callback` 及其所有子路径
- **支持方法**: GET, POST, PUT, DELETE, PATCH, OPTIONS
- **转发机制**: 透明代理，保持原始请求的完整性
- **目标服务器**: 通过环境变量 `TARGET_SERVER_URL` 配置

## 工作原理

```
[企业微信服务器] 
    ↓ HTTPS 请求
[公网域名/wework-callback/*] 
    ↓ 代理转发
[本代理服务 (Flask)] 
    ↓ HTTP 请求
[内网目标服务器]
```

### 请求转发流程
1. 接收来自 `https://yourdomain.com/wework-callback/*` 的请求
2. 移除 `/wework-callback` 前缀
3. 转发到 `TARGET_SERVER_URL/*`
4. 将目标服务器的响应原样返回给客户端

## 环境配置

### 必需的环境变量

在 `.env` 文件中配置：

```env
TARGET_SERVER_URL=http://your-internal-server.com
FLASK_RUN_PORT=8502
FLASK_DEBUG=True
```

### 环境变量说明
- `TARGET_SERVER_URL`: 内网目标服务器地址（必需）
- `FLASK_RUN_PORT`: Flask 服务监听端口（默认: 8502）
- `FLASK_DEBUG`: 调试模式开关（默认: False）

### 依赖项

```
Flask
requests
python-dotenv
```

## 安装和部署

### 1. 安装依赖
```bash
cd wework_proxy_app
pip install -r requirements.txt
```

### 2. 配置环境变量
创建 `.env` 文件：
```bash
echo "TARGET_SERVER_URL=http://your-target-server.com" > .env
echo "FLASK_RUN_PORT=8502" >> .env
echo "FLASK_DEBUG=False" >> .env
```

### 3. 运行代理服务
```bash
python app.py
```

服务将在 `http://0.0.0.0:8502` 启动。

### 4. 配置反向代理 (推荐使用 Nginx)

```nginx
server {
    listen 443 ssl;
    server_name yourdomain.com;
    
    # SSL 配置...
    
    location /wework-callback/ {
        proxy_pass http://localhost:8502/wework-callback/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## 路由配置

### 支持的路由模式
- `/wework-callback` - 根路径
- `/wework-callback/` - 根路径（带斜杠）
- `/wework-callback/<path:path>` - 任意子路径
- `/wework-callback/<path:path>/` - 任意子路径（带斜杠）

### 转发示例
| 原始请求 | 转发目标 |
|---------|---------|
| `GET /wework-callback` | `GET TARGET_SERVER_URL` |
| `POST /wework-callback/webhook` | `POST TARGET_SERVER_URL/webhook` |
| `GET /wework-callback/api/v1/status?token=123` | `GET TARGET_SERVER_URL/api/v1/status?token=123` |

## 技术特性

### 1. 头部处理
- **移除跳跃头部**: 自动过滤 Connection、Keep-Alive 等不应转发的头部
- **Host 头部处理**: 自动设置为目标服务器的 Host
- **Content-Length**: 由 requests 库自动计算

### 2. 错误处理
- **连接超时**: 30秒超时，返回 504 Gateway Timeout
- **连接错误**: 返回 502 Bad Gateway
- **其他异常**: 返回 500 Internal Server Error，并记录详细日志

### 3. 安全特性
- **透明转发**: 不修改请求内容，保持数据完整性
- **日志记录**: 详细的错误日志便于问题排查
- **超时保护**: 防止长时间挂起的请求

## 使用场景

### 典型部署架构
```
[企业微信] → [公网域名+SSL] → [本代理服务] → [内网企业微信处理服务]
```

### 适用情况
1. **内网服务**: 企业微信处理服务部署在内网
2. **公网回调**: 企业微信要求回调 URL 必须是公网可访问的 HTTPS 地址
3. **安全隔离**: 不希望直接暴露内网服务到公网
4. **负载均衡**: 可以配置多个目标服务器实现负载分担

## 监控和调试

### 日志输出
代理服务会记录以下信息：
- 连接错误和超时
- 转发失败的详细原因
- 异常堆栈信息

### 健康检查
可以通过访问代理服务的根路径进行健康检查：
```bash
curl http://localhost:8502/wework-callback
```

### 性能监控
建议监控以下指标：
- 请求响应时间
- 错误率（502, 504 状态码）
- 并发连接数

## 生产环境建议

### 1. 安全配置
- 关闭调试模式 (`FLASK_DEBUG=False`)
- 使用 WSGI 服务器（如 Gunicorn）而非开发服务器
- 配置适当的防火墙规则

### 2. 性能优化
```bash
# 使用 Gunicorn 运行
gunicorn -w 4 -b 0.0.0.0:8502 app:app
```

### 3. 监控和日志
- 配置日志轮转
- 设置监控告警
- 定期检查服务状态

## 故障排除

### 常见问题

1. **502 Bad Gateway**
   - 检查 `TARGET_SERVER_URL` 是否正确
   - 确认目标服务器是否可访问

2. **504 Gateway Timeout**
   - 检查目标服务器响应时间
   - 考虑增加超时时间

3. **500 Internal Server Error**
   - 查看应用日志获取详细错误信息
   - 检查环境变量配置

### 调试命令
```bash
# 测试目标服务器连通性
curl -v $TARGET_SERVER_URL

# 检查代理服务状态
curl -v http://localhost:8502/wework-callback

# 查看实时日志
tail -f app.log
```

## 相关文件

- `requirements.txt`: Python 依赖列表
- `.env`: 环境变量配置文件
- `app.py`: 主应用文件 