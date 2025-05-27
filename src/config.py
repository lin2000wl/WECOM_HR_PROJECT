import yaml
import os
from typing import Dict, Any, List, Optional

# 定义配置文件的路径
CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.yaml')

def load_config(config_path=CONFIG_FILE):
    """
    Loads the configuration from a YAML file.

    Args:
        config_path (str): The path to the configuration file.

    Returns:
        dict: The configuration dictionary.
        None: If the file is not found or cannot be parsed.
    """
    if not os.path.exists(config_path):
        print(f"错误：配置文件未找到于 {config_path}")
        # Fallback or default config can be added here if needed
        # For now, return an empty dict or raise error
        return {} # 返回空字典，避免后续 None 引发错误

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        return config if config else {}
    except yaml.YAMLError as e:
        print(f"错误：解析配置文件失败 {config_path}: {e}")
        return {} # 返回空字典
    except Exception as e:
        print(f"错误：加载配置文件时发生未知错误 {config_path}: {e}")
        return {} # 返回空字典

# Load the configuration globally on module import
config = load_config()

# Helper functions to get specific config sections safely
def get_wcferry_config():
    return config.get('wcferry', {})

def get_authorized_users():
    return config.get('authorized_users', [])

def get_deepseek_config():
    return config.get('deepseek', {})

def get_mongodb_config():
    return config.get('mongodb', {})

def get_paths_config():
    return config.get('paths', {})

def get_message_template(template_name):
    return config.get('message_templates', {}).get(template_name, "")

def get_logging_config():
    return config.get('logging', {})

def get_cache_config():
    return config.get('cache', {})

# Add the missing getter function for OCR configuration
def get_ocr_config():
    return config.get('ocr', {}) # Returns the ocr section, or empty dict if not found

def get_scoring_rules() -> Optional[Dict[str, Any]]:
    """Safely retrieves the scoring_rules configuration.

    Performs basic validation:
    - Checks if 'scoring_rules' exists.
    - Checks if 'initial_candidate_pool_size' is a positive integer.
    - Checks if 'dimensions' exists and is a dictionary.

    Returns:
        Optional[Dict[str, Any]]: The scoring_rules dictionary if valid, otherwise None.
    """
    scoring_config = config.get('scoring_rules')
    if not scoring_config:
        print("警告：配置文件中未找到 'scoring_rules' 部分。将跳过评分排序功能。")
        return None

    pool_size = scoring_config.get('initial_candidate_pool_size')
    if not isinstance(pool_size, int) or pool_size <= 0:
        print(f"警告：'scoring_rules.initial_candidate_pool_size' ({pool_size}) 无效。必须是正整数。将跳过评分排序功能。")
        return None

    dimensions = scoring_config.get('dimensions')
    if not isinstance(dimensions, dict):
        print("警告：'scoring_rules.dimensions' 必须是一个字典。将跳过评分排序功能。")
        return None

    # Further validation for each dimension's structure (weight, enabled, logic, etc.) could be added here.
    # For now, we'll keep it simple.

    return scoring_config

if __name__ == '__main__':
    # Example usage: Print loaded configuration
    print("已加载配置:")
    print(config)
    print("\n授权用户:")
    print(get_authorized_users())
    print("\nDeepSeek API Key:")
    print(get_deepseek_config().get('api_key'))
    print("\n数据库名称:")
    print(get_mongodb_config().get('database'))
    print("\n打招呼模板:")
    print(get_message_template('greeting'))
    print("\n评分规则配置:")
    print(get_scoring_rules()) 