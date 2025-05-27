import os
from dotenv import load_dotenv
import logging

# 加载 .env 文件中的环境变量
# 在项目的早期阶段，确保 .env 文件存在且路径正确
# 对于更健壮的部署，环境变量可能由CI/CD或容器编排工具注入
dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path, override=True)
    # DEBUG: 打印 load_dotenv 后的原始环境变量值
    print(f"DEBUG_CONFIG_EW: Raw value from os.getenv after load_dotenv: '{os.getenv('AUTHORIZED_USER_IDS_EW')}'")
else:
    # 在无法找到.env文件时记录一个警告，但允许程序继续，以便某些配置可以从实际环境变量中获取
    # 或者在严格模式下，这里应该抛出异常
    logging.warning(f".env file not found at {dotenv_path}. Relying on environment variables.")
    # DEBUG: 如果 .env 不存在，也打印一下，看看系统环境变量里是否有这个值
    print(f"DEBUG_CONFIG_EW: .env not found. Raw value from os.getenv: '{os.getenv('AUTHORIZED_USER_IDS_EW')}'")

# 企业微信配置
WECOM_CORP_ID = os.getenv("WECOM_CORP_ID")
WECOM_AGENT_ID = os.getenv("WECOM_AGENT_ID")
WECOM_APP_SECRET = os.getenv("WECOM_APP_SECRET")
WECOM_CALLBACK_TOKEN = os.getenv("WECOM_CALLBACK_TOKEN")
WECOM_CALLBACK_AES_KEY = os.getenv("WECOM_CALLBACK_AES_KEY")

# LLM 配置
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_BASE = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1") # 提供一个默认值
LLM_QUERY_MODEL = os.getenv("LLM_QUERY_MODEL", "deepseek-chat")
LLM_RESUME_MODEL = os.getenv("LLM_RESUME_MODEL", "deepseek-chat")
LLM_SUMMARY_MODEL = os.getenv("LLM_SUMMARY_MODEL", "deepseek-chat")

# MongoDB 配置
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DATABASE = os.getenv("MONGO_DATABASE")

# 应用配置
_authorized_user_ids_ew_str = os.getenv("AUTHORIZED_USER_IDS_EW", "")
# DEBUG: 打印赋给 _authorized_user_ids_ew_str 的值
print(f"DEBUG_CONFIG_EW: Value assigned to _authorized_user_ids_ew_str: '{_authorized_user_ids_ew_str}'")

AUTHORIZED_USER_IDS_EW = [uid.strip() for uid in _authorized_user_ids_ew_str.split(',') if uid.strip()]
# DEBUG: 打印最终处理后的列表
print(f"DEBUG_CONFIG_EW: Final list assigned to AUTHORIZED_USER_IDS_EW: {AUTHORIZED_USER_IDS_EW}")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
BOT_NAME = os.getenv("BOT_NAME", "智能招聘机器人")

# 状态管理器配置
STATE_CACHE_TTL_SECONDS = int(os.getenv("STATE_CACHE_TTL_SECONDS", 180))
STATE_CACHE_MAXSIZE = int(os.getenv("STATE_CACHE_MAXSIZE", 1024)) # 添加MAXSIZE配置

# 核心处理器配置
INITIAL_CANDIDATE_POOL_SIZE = int(os.getenv("INITIAL_CANDIDATE_POOL_SIZE", 30))
TOP_N_CANDIDATES = int(os.getenv("TOP_N_CANDIDATES", 5))
WECOM_CORE_PROCESSOR_MAX_WORKERS = int(os.getenv("WECOM_CORE_PROCESSOR_MAX_WORKERS", 5)) # 添加MAX_WORKERS配置

# 外部联系人同步功能配置
TAG_ID_SYNC_SUCCESS = os.getenv("TAG_ID_SYNC_SUCCESS")
_sync_hr_userids_str = os.getenv("SYNC_HR_USERIDS", "")
SYNC_HR_USERIDS = [uid.strip() for uid in _sync_hr_userids_str.split(',') if uid.strip()]
SYNC_SCHEDULE_CRON = os.getenv("SYNC_SCHEDULE_CRON")

def validate_config():
    """校验关键配置是否存在"""
    missing_configs = []
    if not WECOM_CORP_ID:
        missing_configs.append("WECOM_CORP_ID")
    if not WECOM_AGENT_ID:
        missing_configs.append("WECOM_AGENT_ID")
    if not WECOM_APP_SECRET:
        missing_configs.append("WECOM_APP_SECRET")
    if not WECOM_CALLBACK_TOKEN:
        missing_configs.append("WECOM_CALLBACK_TOKEN")
    if not WECOM_CALLBACK_AES_KEY:
        missing_configs.append("WECOM_CALLBACK_AES_KEY")
    if not DEEPSEEK_API_KEY:
        missing_configs.append("DEEPSEEK_API_KEY")
    if not LLM_QUERY_MODEL: # 检查新加的配置
        missing_configs.append("LLM_QUERY_MODEL")
    if not LLM_RESUME_MODEL:
        missing_configs.append("LLM_RESUME_MODEL")
    if not LLM_SUMMARY_MODEL:
        missing_configs.append("LLM_SUMMARY_MODEL")
    if not MONGO_URI:
        missing_configs.append("MONGO_URI")
    if not MONGO_DATABASE:
        missing_configs.append("MONGO_DATABASE")
    
    # 新增对外部联系人同步配置的校验（TAG_ID_SYNC_SUCCESS 是必须的）
    if not TAG_ID_SYNC_SUCCESS:
        missing_configs.append("TAG_ID_SYNC_SUCCESS")
    # SYNC_HR_USERIDS 和 SYNC_SCHEDULE_CRON 是可选的，或者说，如果启用了自动同步，它们才是必须的。
    # 暂时不在基础校验中强制它们，具体逻辑由 SyncProcessor 判断。

    if missing_configs:
        raise ValueError(f"企业微信或应用核心配置缺失，请检查 .env 文件或环境变量: {', '.join(missing_configs)}")
    
    logging.info("所有关键配置已加载.")

# 在模块加载时可以考虑是否立即校验，或者提供一个函数供应用启动时调用
# validate_config() # 如果希望在导入时就校验，取消此行注释

if __name__ == '__main__':
    # 用于测试配置加载
    print("WECOM_CORP_ID:", WECOM_CORP_ID)
    print("AUTHORIZED_USER_IDS:", AUTHORIZED_USER_IDS_EW)
    print("LOG_LEVEL:", LOG_LEVEL)
    try:
        validate_config()
        print("配置校验通过")
    except ValueError as e:
        print(f"配置校验失败: {e}")

# 也可以在这里加载 config.yaml 中的通用配置
# import yaml
# try:
#     with open("config.yaml", 'r', encoding='utf-8') as f:
#         yaml_config = yaml.safe_load(f)
# except FileNotFoundError:
#     print("Warning: config.yaml not found.")
#     yaml_config = {}
# except Exception as e:
#     print(f"Error loading config.yaml: {e}")
#     yaml_config = {}

# # 示例：从 yaml_config 获取配置
# QUERY_MODEL = yaml_config.get('deepseek', {}).get('query_model', 'deepseek-chat')

print("企业微信配置已加载:")
print(f"  Corp ID: {WECOM_CORP_ID}")
print(f"  Agent ID: {WECOM_AGENT_ID}")
print(f"  Authorized UserIDs: {AUTHORIZED_USER_IDS_EW}")
print(f"  LLM Query Model: {LLM_QUERY_MODEL}") # 打印新加的配置
print(f"  LLM Resume Model: {LLM_RESUME_MODEL}")
print(f"  LLM Summary Model: {LLM_SUMMARY_MODEL}")
print(f"  Tag ID for Sync Success: {TAG_ID_SYNC_SUCCESS}")
print(f"  HR UserIDs for Sync: {SYNC_HR_USERIDS}")
print(f"  Sync Schedule CRON: {SYNC_SCHEDULE_CRON}") 