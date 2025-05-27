from typing import Tuple, Optional, Dict, Any

from src.llm_client import llm_client # 导入 LLM 客户端
from src.logger import logger

# 定义可能的意图类型
INTENT_RECRUITMENT_QUERY = "recruitment_query"
INTENT_OTHER = "other"
INTENT_SELECTION = "selection_reply" # 后续添加，用于处理序号回复
INTENT_ERROR = "error"

def check_intent(user_message: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    检查用户消息的意图，特别是是否为招聘查询。

    Args:
        user_message (str): 用户发送的文本消息内容。

    Returns:
        Tuple[str, Optional[Dict[str, Any]]]: 
            - 第一个元素是识别出的意图类型 (例如 "recruitment_query", "other", "error")。
            - 第二个元素是 LLM 解析出的结构化数据 (如果意图是 recruitment_query 且解析成功)，否则为 None。
    """
    logger.debug(f"开始检查用户消息意图: '{user_message}'")

    # --- 后续可以加入对特定格式回复（如纯数字序号）的快速判断 --- 
    # if user_message.isdigit():
    #     logger.info("消息可能是序号回复，标记为 INTENT_SELECTION")
    #     return INTENT_SELECTION, {"selection": int(user_message)} # 假设结构

    # 调用 LLM 进行查询意图解析
    parsed_data = llm_client.parse_query_intent(user_message)

    if parsed_data is None:
        # LLM 调用失败或返回无法解析的内容
        logger.error(f"意图识别失败：LLM 调用或解析出错。消息: '{user_message}'")
        return INTENT_ERROR, None
    elif isinstance(parsed_data, dict) and parsed_data: 
        # LLM 返回了非空字典，认为是招聘查询意图
        logger.info(f"识别到招聘查询意图。消息: '{user_message}', 解析结果: {parsed_data}")
        return INTENT_RECRUITMENT_QUERY, parsed_data
    elif isinstance(parsed_data, dict) and not parsed_data:
         # LLM 返回了空字典 {}，表示与招聘无关或无法解析
        logger.info(f"消息未识别为招聘查询意图 (LLM 返回空字典)。消息: '{user_message}'")
        return INTENT_OTHER, None
    else:
        # 不应发生，但作为防御性编程
        logger.warning(f"LLM 返回了意外类型的数据: {type(parsed_data)}，内容: {parsed_data}")
        return INTENT_ERROR, None

if __name__ == '__main__':
    # --- 运行此示例前，请确保 config.yaml 中配置了有效的 DeepSeek API Key --- 
    if not llm_client.client:
        logger.error("LLM Client 未成功初始化，无法运行示例。请检查 API Key 配置和网络连接。")
    else:
        logger.info("运行 IntentHandler 示例...")
        
        test_messages = [
            "帮我找个5年以上经验的Java后端工程师，需要熟悉Spring Boot和MySQL",
            "有没有产品经理的机会？",
            "你好",
            "1", # 模拟序号回复 (当前逻辑会走 LLM)
            "谢谢你"
        ]

        for msg in test_messages:
            intent, data = check_intent(msg)
            print(f"消息: '{msg}' -> 意图: {intent}, 数据: {data}") 