from typing import Optional, Dict, Any
import os # Import os for path operations in __main__

from ..logger import logger
from ..llm_client import llm_client
from .text_extractor import extract_text_from_pdf
from .ocr_processor import OcrProcessor # Import the class

# 控制是否启用 OCR 作为备选 (可以从配置读取，暂时硬编码为 True)
ENABLE_OCR_FALLBACK = True

# Create a single OcrProcessor instance for the module?
# Or create it inside the function if config might change?
# Let's create it inside for now, assuming config is loaded once.
# ocr_processor_instance = OcrProcessor()

def parse_resume_pdf(pdf_path: str) -> Optional[Dict[str, Any]]:
    """
    解析单个 PDF 简历文件，提取结构化信息。
    会先尝试直接提取文本，如果失败或为空，则尝试 OCR (如果启用)。
    然后调用 LLM 进行信息提取。

    Args:
        pdf_path (str): PDF 简历文件的绝对路径。

    Returns:
        Optional[Dict[str, Any]]: LLM 解析出的结构化数据字典，如果任何步骤失败则返回 None。
    """
    logger.info(f"开始解析简历 PDF: {pdf_path}")

    # 1. 尝试直接提取文本
    extracted_text = extract_text_from_pdf(pdf_path)

    # 2. 如果直接提取失败或文本为空，并且启用了 OCR，则尝试 OCR
    if extracted_text is None or not extracted_text.strip():
        logger.warning(f"直接文本提取失败或为空，文件: {pdf_path}。")
        if ENABLE_OCR_FALLBACK:
            logger.info(f"尝试使用 OCR 提取文本: {pdf_path}")
            # Instantiate OcrProcessor here or use a module-level instance
            ocr_processor_instance = OcrProcessor()
            if not ocr_processor_instance.is_available():
                logger.error(f"OCR processor is not available (Tesseract/Poppler configured?). Skipping OCR for {pdf_path}")
                return None
                
            extracted_text = ocr_processor_instance.ocr_pdf(pdf_path)
            if extracted_text is None:
                logger.error(f"OCR 提取文本也失败了: {pdf_path}")
                return None # OCR 也失败，无法继续
            elif not extracted_text.strip():
                 logger.warning(f"OCR 提取到的文本为空: {pdf_path}")
                 return None # OCR 提取文本为空
        else:
            logger.error(f"直接文本提取失败且 OCR 未启用: {pdf_path}")
            return None # 直接提取失败且未启用 OCR
            
    # 3. 调用 LLM 解析提取到的文本
    if not extracted_text:
        # 理论上不应该到这里，因为前面有检查
        logger.error(f"获取到的简历文本为空，无法调用 LLM: {pdf_path}")
        return None
        
    logger.info(f"成功获取简历文本 (长度: {len(extracted_text)})，准备调用 LLM 解析: {pdf_path}")
    # Corrected call based on llm_client.py inspection
    parsed_data_str = None
    try:
        parsed_data_str = llm_client.parse_resume(extracted_text) 
    except Exception as e:
        # Catch potential exceptions during the LLM call itself
        logger.error(f"调用 LLM 解析简历时发生异常: {e}. 文件: {pdf_path}", exc_info=True)
        return None # Return None if LLM call fails with exception

    if parsed_data_str is None:
        logger.error(f"LLM 简历解析失败 (返回 None): {pdf_path}")
        return None
    if not parsed_data_str.strip():
        logger.error(f"LLM 简历解析失败 (返回空字符串): {pdf_path}")
        return None

    # Parse the JSON string returned by LLM
    try:
        import json
        parsed_data = json.loads(parsed_data_str)
    except json.JSONDecodeError as e:
        logger.error(f"解析 LLM 返回的 JSON 时出错: {e}. LLM 返回: {parsed_data_str[:500]}... 文件: {pdf_path}")
        return None

    # Check critical keys after successful JSON parsing
    if not parsed_data or not isinstance(parsed_data, dict) or not parsed_data.get("name") or not parsed_data.get("phone"):
         logger.error(f"LLM 解析结果格式无效或缺少关键信息 (姓名或手机号): {pdf_path}. 数据: {parsed_data}")
         return None 

    logger.info(f"成功使用 LLM 解析简历: {pdf_path}。姓名: {parsed_data.get('name')}")
    return parsed_data

if __name__ == '__main__':
    # --- 运行此示例需要配置好 LLM API Key --- 
    # --- 以及 Tesseract 和 Poppler (如果需要测试 OCR fallback) --- 
    # --- 并提供一个名为 resume_test.pdf 的文件 --- 
    print("--- 测试 LLM 简历解析器 --- H")
    test_pdf_path = "resume_test.pdf"
    
    # 可以创建一个文本型 PDF 或图片型 PDF 用于测试
    if not os.path.exists(test_pdf_path):
        print(f"测试文件 {test_pdf_path} 不存在。请创建一个 PDF 文件用于测试。")
        # 提示：可以运行 text_extractor.py 生成 sample.pdf，然后重命名为 resume_test.pdf
    else:
        if not llm_client.client:
             logger.error("LLM Client 未初始化，无法运行解析测试。")
        else:
            abs_path = os.path.abspath(test_pdf_path)
            print(f"开始解析文件: {abs_path}")
            parsed_result = parse_resume_pdf(abs_path)

            if parsed_result:
                print("\n--- LLM 解析结果 --- H")
                import json
                # 打印格式化的 JSON
                print(json.dumps(parsed_result, indent=2, ensure_ascii=False))
            else:
                print("\n简历解析失败。") 