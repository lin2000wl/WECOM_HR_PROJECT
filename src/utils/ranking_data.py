# src/utils/ranking_data.py

import re
from ..logger import logger # 假设 logger 可用

# 特定证书等级规则 (优先匹配)
CERTIFICATE_RANKS = {
    "建筑师": {
        # levels 列表可选，主要用于快速判断是否存在
        "levels": ["助理建筑师", "中级建筑师", "高级建筑师", "教授级高级建筑师"],
        # values 字典用于比较等级高低
        "values": {
            "助理建筑师": 1,
            "中级建筑师": 2,
            "高级建筑师": 3,
            "教授级高级建筑师": 4,
        }
    },
    "注册建造师": {
        "levels": ["二级注册建造师", "一级注册建造师", "二级建造师", "一级建造师"], # 包含常用别名
        "values": {
            "一级注册建造师": 1, "一级建造师": 1,
            "二级注册建造师": 2, "二级建造师": 2,
        }
    },
    # --- 在这里添加更多证书/职称的等级信息 ---
    # 示例：工程师职称 (简化)
     "工程师": {
         "levels": ["助理工程师", "工程师", "高级工程师", "教授级高级工程师"],
         "values": {
             "助理工程师": 1,
             "工程师": 2,
             "中级工程师": 2, # 别名
             "高级工程师": 3,
             "教授级高级工程师": 4,
         }
    },
}

# --- v1.2 通用等级关键词定义 ---
CHINESE_LEVELS = ["助理", "中级", "高级"]
NUMERIC_LEVELS = ["一级", "二级", "三级"] # 确认: 一级(index 0) < 二级(index 1) < 三级(index 2)

# 通用等级关键词信息查找表 ('system'区分体系, 'index'确定顺序)
LEVEL_INFO = {}
for i, level in enumerate(CHINESE_LEVELS):
    LEVEL_INFO[level] = {"system": "chinese", "index": i}
LEVEL_INFO["初级"] = {"system": "chinese", "index": 0} # 别名

for i, level in enumerate(NUMERIC_LEVELS):
    LEVEL_INFO[level] = {"system": "numeric", "index": i}
# --- 结束 v1.2 定义 ---

def get_matching_levels(base_name: str, level_keyword: str | None, modifier: str | None) -> list[str]:
    """
    根据基础名称、等级关键词和修饰符获取匹配的证书全名列表。
    优先使用 CERTIFICATE_RANKS 中的特定规则。
    """
    # 组合出完整的证书名称 (如果提供了等级关键词)
    full_cert_name = f"{level_keyword}{base_name}" if level_keyword else base_name

    # --- 1. 尝试特定规则 --- 
    for category, data in CERTIFICATE_RANKS.items():
        category_values = data.get("values", {})
        if full_cert_name in category_values:
            target_value = category_values[full_cert_name]
            logger.debug(f"证书 '{full_cert_name}' 在预定义库 '{category}' 中找到，应用特定规则 (value={target_value})。")
            matching_levels_names = []
            if modifier == "ge": # 大于等于
                matching_levels_names = [name for name, value in category_values.items() if value >= target_value]
            elif modifier == "gt": # 大于
                matching_levels_names = [name for name, value in category_values.items() if value > target_value]
            else: # eq, None 或其他，视为等于
                matching_levels_names = [name for name, value in category_values.items() if value == target_value]
            
            if matching_levels_names:
                logger.debug(f"特定规则匹配结果: {list(set(matching_levels_names))}")
                return list(set(matching_levels_names))
            else:
                logger.warning(f"在特定规则库中找到 '{full_cert_name}' 但未匹配到有效级别 (modifier: {modifier})，仅返回原始名称。")
                return [full_cert_name] # 如果规则存在但无匹配（比如查最高级的gt），返回原名

    # --- 2. 尝试通用规则 --- 
    if level_keyword and level_keyword in LEVEL_INFO:
        info = LEVEL_INFO[level_keyword]
        system = info["system"]
        current_index = info["index"]
        source_list = CHINESE_LEVELS if system == "chinese" else NUMERIC_LEVELS
        target_indices = []

        if modifier == "ge": # 大于等于
            target_indices = range(current_index, len(source_list))
        elif modifier == "gt": # 大于
            target_indices = range(current_index + 1, len(source_list))
        else: # eq, None 或其他，视为等于
            target_indices = [current_index]
        
        target_levels = [source_list[i] for i in target_indices if 0 <= i < len(source_list)]

        if target_levels:
            # 组合关键词和基础名称
            generated_names = [f"{level}{base_name}" for level in target_levels]

            # --- v1.2.1 Enhancement: Add '注册' variants for specific professions --- 
            registrable_professions = ["建筑师", "建造师", "工程师"] # 可以扩展这个列表
            if base_name in registrable_professions:
                registered_names = [f"{level}注册{base_name}" for level in target_levels]
                # 也添加仅带注册的基础名称
                registered_names.append(f"注册{base_name}") 
                generated_names.extend(registered_names)
            # --- End Enhancement ---

            logger.debug(f"应用通用规则 for '{full_cert_name}', 生成: {list(set(generated_names))}")
            return list(set(generated_names))
        else:
             logger.debug(f"应用通用规则 for '{full_cert_name}' 未找到目标等级 (modifier: {modifier})。")
             # 即使有关键词，但modifier导致没结果，也返回原名
             return [full_cert_name]

    # --- 3. 如果无规则适用，返回原始组合名（或基础名） --- 
    logger.debug(f"无特定或通用规则适用 for '{full_cert_name}'，返回原始名称。")
    return [full_cert_name]

def check_certificate_exists(cert_name: str) -> bool:
    """检查证书全名是否已知（在特定库或可按通用规则分解）"""
    # 1. 检查特定库
    for category, data in CERTIFICATE_RANKS.items():
        if cert_name in data.get("values", {}):
            return True
            
    # 2. 尝试按通用规则分解 (检查是否以已知关键词开头)
    # 按长度倒序匹配关键词，更精确
    sorted_keywords = sorted(LEVEL_INFO.keys(), key=len, reverse=True)
    for keyword in sorted_keywords:
        if cert_name.startswith(keyword):
             # 简单认为只要能匹配到已知关键词前缀就算存在
             # 后续可以增加对 base_name 的检查，例如不能为空
             base_name_part = cert_name[len(keyword):].strip()
             if base_name_part: # 确保基础名称部分不为空
                return True
                
    # 如果都找不到，则认为不存在
    return False

# --- 注意：以上函数实现已根据讨论更新，但仍需通过测试验证 --- 