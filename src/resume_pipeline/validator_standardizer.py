# Placeholder for rewrite
import re
import os
from typing import Dict, Any, Tuple, Optional, List
from datetime import datetime

from ..logger import logger
from ..utils.ranking_data import check_certificate_exists

# 用于清理文件名的正则表达式，移除常见的非法字符
FILENAME_INVALID_CHARS = r'[\\/:*?"<>|]'
PHONE_NUMBER_PATTERN = re.compile(r'\d{11}') # 简单的11位数字模式

def _sanitize_filename(name: str) -> str:
    """移除文件名中的非法字符。"""
    # 替换非法字符为空字符串
    sanitized = re.sub(FILENAME_INVALID_CHARS, '', name)
    # 移除首尾空格
    return sanitized.strip()

def _parse_date(date_str: str) -> Optional[datetime]:
    """尝试解析 YYYY-MM, YYYY.MM 或 YYYY 格式的日期字符串。"""
    if not date_str or not isinstance(date_str, str):
        return None
    try:
        # 优先尝试 YYYY-MM 或 YYYY.MM 格式
        match = re.match(r'(\d{4})[.-](\d{1,2})', date_str)
        if match:
            year, month = int(match.group(1)), int(match.group(2))
            # 确保月份有效
            if 1 <= month <= 12:
                return datetime(year, month, 1) # 使用月份第一天作为代表
            else:
                 logger.debug(f"月份无效: {month} in '{date_str}'")
                 return None
        else:
            # 尝试 YYYY 格式
            match_year = re.match(r'^(\d{4})$', date_str)
            if match_year:
                year = int(match_year.group(1))
                # 假设年份有效，可以根据需要增加年份范围检查
                return datetime(year, 1, 1) # 假设年初开始
            else:
                 logger.debug(f"无法识别的日期格式: '{date_str}'")
                 return None
    except (ValueError, TypeError) as e:
        logger.debug(f"解析日期 '{date_str}' 时出错: {e}")
        return None

def _calculate_experience_years(experiences: List[Dict[str, Any]]) -> int:
    """尝试从工作经历中估算总工作年限。返回整数年限。"""
    if not experiences or not isinstance(experiences, list):
        return 0

    earliest_start = None
    latest_end = None
    present_job = False

    for exp in experiences:
        if not isinstance(exp, dict):
            continue

        start_str = exp.get("start_date")
        end_str = exp.get("end_date")

        # 解析开始日期
        start_date = _parse_date(start_str)
        if start_date:
            if earliest_start is None or start_date < earliest_start:
                earliest_start = start_date

        # 解析结束日期，处理"至今"
        if end_str:
            end_lower = end_str.lower()
            if any(indicator in end_lower for indicator in ['至今', 'present', 'current', 'now']):
                present_job = True
                # 如果有至今的工作，最新结束时间至少是现在
                current_time = datetime.now()
                if latest_end is None or current_time > latest_end:
                    latest_end = current_time
            else:
                end_date = _parse_date(end_str)
                if end_date:
                    # 如果是年底结束，为了计算方便，可以视为下一年年初
                    # 例如 2022 结束，视为 2023-01-01
                    # 但更简单的是直接使用解析出的日期（如 2022-12-01 或 2022-01-01）
                    if latest_end is None or end_date > latest_end:
                        latest_end = end_date

    # 如果有标记为"至今"的工作，确保 latest_end 是当前时间（如果比记录的还晚）
    if present_job:
        current_time = datetime.now()
        if latest_end is None or current_time > latest_end:
            latest_end = current_time

    if earliest_start and latest_end and latest_end > earliest_start:
        # 计算总时长（天数），然后近似为年
        total_duration_days = (latest_end - earliest_start).days
        # 使用 365.25 更准确地估算年数，或者简单除以 365
        years = round(total_duration_days / 365.25)
        logger.debug(f"估算总工作年限: {years} 年 (从 {earliest_start.date()} 到 {latest_end.date()})")
        return max(0, years) # 确保非负
    elif earliest_start and latest_end: # Case where end <= start
        logger.debug(f"最早开始日期 {earliest_start.date()} 不在最晚结束日期 {latest_end.date()} 之前，返回 0 年。")
        return 0
    elif earliest_start: # 只有开始日期，没有有效的结束日期
         # 如果只有开始日期，至少算0年或1年？取决于策略
         # 认为至少有段经历，算1年比较合理
         logger.debug("只找到最早开始日期，无法精确估算总年限，按 1 年计算。")
         return 1
    else:
        logger.debug("无法从工作经历中估算有效工作年限，返回 0 年。")
        return 0 # 没有有效日期信息

def _generate_query_tags(parsed_data: Dict[str, Any], original_filename: str) -> Dict[str, Any]:
    """根据解析出的信息生成用于查询的标签。"""
    query_tags = {}
    # 确保 extracted_info 存在且是字典
    extracted_info = parsed_data.get("extracted_info")
    if not isinstance(extracted_info, dict):
        extracted_info = {}

    # 1. 提取职位标签 (所有工作经历中的职位名称，去重)
    positions = set()
    experiences = extracted_info.get("experience", [])
    if isinstance(experiences, list):
        for exp in experiences:
            if isinstance(exp, dict) and exp.get("title") and isinstance(exp["title"], str):
                positions.add(exp["title"].strip())
    query_tags["positions"] = list(filter(None, positions)) # 过滤掉可能的空字符串

    # 2. 提取/估算最低工作年限
    # 优先使用 LLM 可能提取的总年限 (如果 prompt 支持且字段存在)
    # 例如: llm_years = extracted_info.get("total_experience_years")
    # if llm_years and isinstance(llm_years, int) and llm_years >= 0:
    #     query_tags["min_experience_years"] = llm_years
    # else:
    # 如果 LLM 未提取或无效，则尝试从经历中估算
    calculated_years = _calculate_experience_years(experiences)
    query_tags["min_experience_years"] = calculated_years

    # 3. 提取标准化技能标签 (小写，去重)
    skills = extracted_info.get("skills", [])
    normalized_skills = set()
    if isinstance(skills, list):
        for skill in skills:
            if isinstance(skill, str):
                normalized_skills.add(skill.strip().lower())
    query_tags["skills_normalized"] = list(filter(None, normalized_skills))

    # 4. 提取地点标签 (直接使用，或根据需要进行规范化)
    location = extracted_info.get("current_location")
    if isinstance(location, str): # Allow empty string
        # TODO: Consider normalizing location (e.g., remove '市', map districts to city)
        query_tags["location"] = location.strip()
    else:
        query_tags["location"] = None # Ensure the key exists even if null

    # 5. 提取资格证书标签 (小写，去重)
    certs = extracted_info.get("certifications", []) # v1.2: Now expects list of dicts
    normalized_certs = set()
    if isinstance(certs, list):
        for cert_obj in certs: # Iterate over objects
            # v1.2: Expecting dict {'name': '...', 'level_keyword': '...'}
            if isinstance(cert_obj, dict) and 'name' in cert_obj:
                base_name = cert_obj.get('name')
                level_keyword = cert_obj.get('level_keyword') # Can be null/None

                if base_name and isinstance(base_name, str):
                    base_name = base_name.strip()
                    # Combine name and level keyword (if exists)
                    full_cert_name = f"{level_keyword}{base_name}" if level_keyword and isinstance(level_keyword, str) and level_keyword.strip() else base_name

                    if full_cert_name:
                        # Check existence using the updated function
                        if not check_certificate_exists(full_cert_name):
                            logger.warning(f"发现待审核证书: '{full_cert_name}' (来自文件: {original_filename})")
                        # Add the normalized (lowercase) full name to query tags
                        normalized_certs.add(full_cert_name.lower())
                else:
                    logger.warning(f"在简历解析结果中发现无效的证书基础名称: {cert_obj} (文件: {original_filename})")
            elif isinstance(cert_obj, str): # Fallback for old format (if LLM fails to adapt)
                 original_cert_name = cert_obj.strip()
                 if original_cert_name:
                    if not check_certificate_exists(original_cert_name):
                         logger.warning(f"发现待审核证书 (旧格式): '{original_cert_name}' (来自文件: {original_filename})")
                    normalized_certs.add(original_cert_name.lower())
            else:
                 logger.warning(f"在简历解析结果中跳过无效的证书对象: {cert_obj} (文件: {original_filename})")

    query_tags["certifications"] = list(filter(None, normalized_certs))

    # 6. 提取学校和学位 (可选，作为标签)
    education_entries = extracted_info.get("education", [])
    schools = set()
    degrees = set()
    if isinstance(education_entries, list):
        for edu in education_entries:
            if isinstance(edu, dict):
                if edu.get("school") and isinstance(edu["school"], str):
                    schools.add(edu["school"].strip())
                if edu.get("degree") and isinstance(edu["degree"], str):
                    degrees.add(edu["degree"].strip())
    query_tags["schools"] = list(filter(None, schools))
    query_tags["degrees"] = list(filter(None, degrees))

    logger.debug(f"生成的查询标签: {query_tags}")
    return query_tags

def validate_and_standardize(parsed_data: Dict[str, Any], original_filename: str) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]], Optional[str]]:
    """
    校验 LLM 解析结果，生成标准化文件名和查询标签。

    Args:
        parsed_data (Dict[str, Any]): 从 resume_parser 获取的解析结果。
        original_filename (str): 原始 PDF 文件名 (用于日志)。

    Returns:
        Tuple[bool, Optional[str], Optional[Dict[str, Any]], Optional[str]]:
            - is_valid (bool): 校验是否通过 (关键信息存在)。
            - standardized_filename (Optional[str]): 生成的标准化文件名 (如 "张三1234.pdf")，校验失败则为 None。
            - processed_data (Optional[Dict[str, Any]]): 添加了 query_tags 的原始数据，校验失败则为 None。
            - validation_error (Optional[str]): 校验失败的原因，成功则为 None。
    """
    logger.info(f"开始校验和标准化简历数据: {original_filename}")

    if not parsed_data or not isinstance(parsed_data, dict):
        logger.error(f"输入数据无效或为空。文件: {original_filename}")
        # 返回原始数据可能没有意义，因为它是无效的
        return False, None, None, "输入数据无效或为空"

    # 1. 校验关键信息：姓名和手机号
    # 优先从顶层获取，如果顶层没有，尝试从 extracted_info 获取 (作为备选)
    name = parsed_data.get("name")
    phone = parsed_data.get("phone")

    if not name and isinstance(parsed_data.get("extracted_info"), dict):
        name = parsed_data["extracted_info"].get("name")
    if not phone and isinstance(parsed_data.get("extracted_info"), dict):
        phone = parsed_data["extracted_info"].get("phone")

    # 校验姓名
    if not name or not isinstance(name, str) or not name.strip():
        error_msg = "缺少有效的候选人姓名。"
        logger.warning(f"{error_msg} 文件: {original_filename}") # 改为 warning，允许移到 pending
        # 即使缺少姓名，也尝试处理，但标记为无效，文件名用原始名代替
        # 这样可以将文件移到 pending 目录，而不是 error
        # 仍然需要生成标签，以便后续手动处理时有信息
        query_tags = _generate_query_tags(parsed_data, original_filename)
        processed_data = parsed_data.copy()
        processed_data["query_tags"] = query_tags
        if "extracted_info" not in processed_data:
            processed_data["extracted_info"] = {}
        return False, None, processed_data, error_msg # is_valid=False, 无标准文件名, 返回带标签数据

    # 校验手机号
    if not phone or not isinstance(phone, str) or not phone.strip():
        error_msg = "缺少有效的候选人手机号。"
        logger.warning(f"{error_msg} 文件: {original_filename}")
        query_tags = _generate_query_tags(parsed_data, original_filename)
        processed_data = parsed_data.copy()
        processed_data["query_tags"] = query_tags
        if "extracted_info" not in processed_data:
            processed_data["extracted_info"] = {}
        return False, None, processed_data, error_msg

    # 提取手机号后四位，尝试清理非数字字符
    cleaned_phone = re.sub(r'\D', '', phone)
    if len(cleaned_phone) < 4:
        error_msg = f"手机号 '{phone}' 清理后 ('{cleaned_phone}') 不足 4 位，无法安全用于生成文件名。"
        logger.warning(f"{error_msg} 文件: {original_filename}")
        query_tags = _generate_query_tags(parsed_data, original_filename)
        processed_data = parsed_data.copy()
        processed_data["query_tags"] = query_tags
        if "extracted_info" not in processed_data:
            processed_data["extracted_info"] = {}
        return False, None, processed_data, error_msg

    phone_last4 = cleaned_phone[-4:]

    # 简单校验手机号格式 (可选)
    # if not PHONE_NUMBER_PATTERN.match(cleaned_phone):
    #      logger.warning(f"手机号 '{phone}' (清理后: {cleaned_phone}) 格式可能无效，但仍继续处理。文件: {original_filename}")

    # 2. 生成标准化文件名
    sanitized_name = _sanitize_filename(name)
    standardized_filename = f"{sanitized_name}{cleaned_phone[-4:]}.pdf"
    logger.info(f"生成的标准化文件名: {standardized_filename}")

    # 3. 生成查询标签 (v1.2 Pass original_filename)
    query_tags = _generate_query_tags(parsed_data, original_filename)

    # 4. 准备最终返回的数据
    processed_data = parsed_data.copy()
    processed_data["query_tags"] = query_tags

    # 确保 extracted_info 存在
    if "extracted_info" not in processed_data:
         processed_data["extracted_info"] = {}

    # 可以在这里添加其他标准化逻辑，例如日期格式统一等

    logger.info(f"简历数据校验和标准化完成: {original_filename}")
    # 只要姓名和手机号的基本要素存在，就认为校验通过 (is_valid=True)
    # 即使名字清理后为空或手机号不足4位，上面已经返回 is_valid=False 了
    return True, standardized_filename, processed_data, None

if __name__ == '__main__':
    # 设置基本日志记录，以便在直接运行时看到输出
    import logging
    logging.basicConfig(level=logging.DEBUG)
    logger.setLevel(logging.DEBUG)

    print("--- 测试校验与标准化器 ---")

    test_data_success = {
        "name": "  张三/?*<>|  ",
        "phone": "  138-0013-8000  ",
        "email": "zhangsan@example.com",
        "extracted_info": {
            "summary": "资深工程师",
            "experience": [
                {"company": "A公司", "title": "软件工程师", "start_date": "2018.07", "end_date": "2022.12"},
                {"company": "B公司", "title": "后端工程师", "start_date": "2015-03", "end_date": "2018-06"},
                {"company": "C公司", "title": "架构师", "start_date": "2023-01", "end_date": "至今"} # 包含至今
            ],
            "education": [
                {"school": " XX大学 ", "degree": " 本科 "},
                {"school": " YY大学 ", "degree": "硕士"}
            ],
            "skills": [" Python ", " mongodb ", " ", "DOCKER", "Kubernetes"]
        }
    }

    test_data_only_year = {
        "name": "李四",
        "phone": "13900001111",
        "extracted_info": {
            "experience": [
                {"title": "Tester", "start_date": "2020", "end_date": "2021"}
            ]
        }
    }

    test_data_missing_info = {
        "name": "王五",
        "phone": "13712345678",
        # 没有 extracted_info
    }

    test_data_no_phone = {"name": "赵六", "email": "zhao@example.com"}
    test_data_bad_name = {"name": " //* ", "phone": "13912345678"}
    test_data_short_phone = {"name": "孙七", "phone": "123"}
    test_data_invalid_input = None
    test_data_empty_dict = {}
    test_data_only_start = {
         "name": "周八",
         "phone": "13500009999",
         "extracted_info": {
            "experience": [
                {"title": "助理", "start_date": "2022-05"} # 只有开始日期
            ]
         }
    }
    test_data_non_pdf = {
        "name": "吴九",
        "phone": "13344445555",
        "extracted_info": {"skills": ["Java"]}
    }


    def run_test(data, filename):
        print(f"\n--- 测试: {filename} ---")
        is_valid, fname, p_data, error = validate_and_standardize(data, filename)
        print(f"原始数据: {data}")
        print(f"校验通过: {is_valid}")
        print(f"标准文件名: {fname}")
        print(f"错误信息: {error}")
        if p_data:
            print("处理后数据 (部分):")
            print(f"  姓名: {p_data.get('name')}")
            print(f"  电话: {p_data.get('phone')}")
            print(f"  Query Tags: {p_data.get('query_tags')}")
        else:
            print("处理后数据: None")

    run_test(test_data_success, "张三简历_final.pdf")
    run_test(test_data_only_year, "李四_2021.pdf")
    run_test(test_data_missing_info, "王五.pdf")
    run_test(test_data_no_phone, "赵六_无手机.pdf")
    run_test(test_data_bad_name, "特殊字符姓名.pdf")
    run_test(test_data_short_phone, "短手机号孙七.pdf")
    run_test(test_data_invalid_input, "无效输入.pdf")
    run_test(test_data_empty_dict, "空字典.pdf")
    run_test(test_data_only_start, "周八只有开始日期.pdf")
    run_test(test_data_non_pdf, "吴九简历.docx") # 测试非 pdf 扩展名 