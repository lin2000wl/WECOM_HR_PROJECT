#!/usr/bin/env python3
"""
企业微信URL验证服务启动脚本
"""

import os
import sys
from pathlib import Path

def check_environment():
    """检查环境配置"""
    env_file = Path('.env')
    if not env_file.exists():
        print("❌ 未找到 .env 文件")
        print("📝 请复制 env.example 为 .env 并配置相关参数:")
        print("   cp env.example .env")
        return False
    
    # 检查必需的环境变量
    from dotenv import load_dotenv
    load_dotenv()
    
    required_vars = ['TOKEN', 'ENCODING_AES_KEY', 'CORP_ID']
    missing_vars = []
    
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        print(f"❌ 缺少必需的环境变量: {', '.join(missing_vars)}")
        print("📝 请在 .env 文件中配置这些变量")
        return False
    
    print("✅ 环境配置检查通过")
    return True

def main():
    """主函数"""
    print("🚀 企业微信URL验证服务启动中...")
    print("=" * 50)
    
    # 检查环境
    if not check_environment():
        sys.exit(1)
    
    # 启动应用
    try:
        from app import app
        port = int(os.getenv("FLASK_RUN_PORT", 8502))
        debug_mode = os.getenv("FLASK_DEBUG", "False").lower() in ('true', '1', 't')
        
        print(f"🌐 服务将在 http://0.0.0.0:{port} 启动")
        print(f"🔧 调试模式: {'开启' if debug_mode else '关闭'}")
        print("=" * 50)
        print("📋 可用的API端点:")
        print("   GET  /                    - URL验证")
        print("   GET  /wework-callback     - URL验证")
        print("   GET  /wechat_callback     - 消息回调验证")
        print("   POST /wechat_callback     - 消息接收")
        print("=" * 50)
        print("💡 按 Ctrl+C 停止服务")
        
        app.run(host='0.0.0.0', port=port, debug=debug_mode)
        
    except ImportError as e:
        print(f"❌ 导入错误: {e}")
        print("📝 请确保已安装所有依赖: pip install -r requirements.txt")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 启动失败: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main() 