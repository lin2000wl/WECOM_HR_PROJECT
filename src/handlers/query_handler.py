from typing import Dict, Any, List, Optional
import os # Add os import at the top if not already present
import logging # Import logging
import re # v1.2.1 Import re for regex escaping
import asyncio  # 导入异步支持

from src.logger import logger # Use absolute import
# from ..db_interface import db_interface # Relative
from src.db_interface import db_interface # Absolute
# from ..models.candidate import Candidate # Relative
from src.models.candidate import Candidate # Absolute
# from ..config import get_cache_config # Relative
from src.config import get_cache_config, get_scoring_rules # Absolute, Add get_scoring_rules
# 导入 state_manager 单例
from src.utils.state_manager import state_manager, STATE_WAITING_SELECTION, STATE_IDLE
# 导入 wcferry_interface
# from src.wcferry_interface import send_text, send_file
# Import llm_client
from src.llm_client import llm_client
# Import scoring utils
from src.utils.scoring_utils import calculate_score_for_dimension
# v1.2 Import: Import certificate ranking helper
from src.utils.ranking_data import get_matching_levels, LEVEL_INFO, CHINESE_LEVELS, NUMERIC_LEVELS # v1.2.3 Import necessary level constants
from src.enterprise_wechat_service import EnterpriseWeChatService  # 使用企业微信服务替代 wcferry 接口
from wcferry import Wcf, WxMsg  # 导入类型，解决类型注解未定义

ew_service = EnterpriseWeChatService()  # 企业微信服务实例

# --- v1.2.2 Skill Synonyms Definition ---
SKILL_SYNONYMS = [
    {"cad", "autocad", "cad制图"},
    # {"python", "py"}, # Add more synonym groups here as needed
]
# --- End Skill Synonyms Definition ---

# 简单的状态键常量
# STATE_KEY = "state"
STATE_KEY = "state"
RESULTS_KEY = "last_query_results"

# --- v1.2.2 Helper function for skill expansion ---
def _expand_skills(skills: List[str]) -> List[str]:
    """将技能列表根据 SKILL_SYNONYMS 进行扩展。"""
    if not skills:
        return []
    
    expanded_set = set()
    normalized_input_skills = {skill.strip().lower() for skill in skills if isinstance(skill, str) and skill.strip()}
    
    found_in_group = set()
    for skill in normalized_input_skills:
        matched_group = False
        for group in SKILL_SYNONYMS:
            if skill in group:
                expanded_set.update(group) # Add all synonyms from the matched group
                found_in_group.add(skill) # Mark this skill as processed via group
                matched_group = True
                break # Move to the next skill once a group is found
        # If the skill wasn't part of any synonym group, add it directly
        if not matched_group:
            expanded_set.add(skill)
            
    final_list = list(expanded_set)
    logger.debug(f"原始技能: {skills}, 扩展后技能: {final_list}")
    return final_list
# --- End helper function ---

def _build_mongo_query(parsed_data: Dict[str, Any]) -> Dict[str, Any]:
    """根据 LLM 解析的数据构建 MongoDB 查询条件 (v1.2.2 更新技能处理)。"""
    query = {}
    filters = []

    # --- Handle Experience, Skills, Location, Education, Previous Companies FIRST ---
    # ... (代码与之前相同，处理经验、技能、地点、学历、曾任职公司) ...
    # 处理工作年限条件
    min_experience = parsed_data.get("experience_years_min")
    max_experience = parsed_data.get("experience_years_max")
    exp_filter = {}
    try:
        if min_experience is not None:
            exp_filter["$gte"] = int(min_experience)
        if max_experience is not None:
            exp_filter["$lte"] = int(max_experience)
    except (ValueError, TypeError) as e:
        logger.warning(f"处理经验年限条件时出错 (min: {min_experience}, max: {max_experience}): {e}，已忽略经验条件。")
        exp_filter = {}
    if exp_filter:
        filters.append({"query_tags.min_experience_years": exp_filter})

    # 处理技能
    skills = parsed_data.get("skills")
    if skills and isinstance(skills, list) and len(skills) > 0:
        expanded_skills = _expand_skills(skills) # Expand synonyms
        if expanded_skills:
            skill_or_conditions = []
            for skill in expanded_skills:
                try:
                    # Escape potential regex special characters in the skill name
                    escaped_skill = re.escape(skill)
                    # Use regex for case-insensitive substring matching within the array elements
                    skill_or_conditions.append({
                        "query_tags.skills_normalized": {"$regex": escaped_skill, "$options": "i"}
                    })
                except Exception as e:
                    logger.error(f"处理技能 '{skill}' 构建 regex 时出错: {e}")
            
            if skill_or_conditions:
                filters.append({"$or": skill_or_conditions})
                logger.info(f"添加扩展/模糊技能查询条件 ($or): {expanded_skills}")

    # 处理地点
    location = parsed_data.get("location")
    if location and isinstance(location, str) and location.strip():
         filters.append({"query_tags.location": {"$regex": location.strip(), "$options": "i"}})
         logger.debug(f"添加地点查询条件: {location.strip()}")

    # 处理学历 (使用 education_levels 列表和 $in 操作符，并扩展同义词)
    education_levels = parsed_data.get("education_levels") # Get the list
    if education_levels and isinstance(education_levels, list) and len(education_levels) > 0:
        # Ensure all items in the list are valid strings and strip whitespace
        valid_levels = [level.strip() for level in education_levels if isinstance(level, str) and level.strip()]
        if valid_levels:
            # --- Query Expansion for synonyms ---
            expanded_levels = set(valid_levels) # Use a set to handle potential duplicates easily
            if "本科" in expanded_levels:
                expanded_levels.add("学士")
                logger.debug("检测到'本科'，自动扩展查询包含'学士'。")
            if "学士" in expanded_levels:
                expanded_levels.add("本科")
                logger.debug("检测到'学士'，自动扩展查询包含'本科'。")
            # Add more synonyms here if needed
            # e.g., master/graduate student?
            if "硕士" in expanded_levels:
                expanded_levels.add("研究生")
                logger.debug("检测到'硕士'，自动扩展查询包含'研究生'。")
            if "研究生" in expanded_levels:
                expanded_levels.add("硕士")
                logger.debug("检测到'研究生'，自动扩展查询包含'硕士'。")
            
            

            final_levels_list = list(expanded_levels)
            # --- End Query Expansion ---

            # Use $in operator with the expanded list
            if final_levels_list: # Ensure the list is not empty after potential expansion/filtering
                filters.append({"query_tags.degrees": {"$in": final_levels_list}})
                logger.debug(f"添加学历查询条件 ($in 匹配，扩展同义词后): {final_levels_list}")
            else:
                 logger.debug("扩展同义词后，有效的学历等级列表为空。")
        else:
            logger.debug("LLM 返回的 education_levels 列表为空或无效。")

    # 处理曾任职公司
    previous_companies = parsed_data.get("previous_companies")
    company_filters = []
    if previous_companies and isinstance(previous_companies, list) and len(previous_companies) > 0:
        for company in previous_companies:
            if isinstance(company, str) and company.strip():
                company_filters.append({"extracted_info.experience.company": {"$regex": company.strip(), "$options": "i"}})
    if company_filters:
        if len(company_filters) > 1:
            filters.append({"$or": company_filters})
            logger.debug(f"添加公司经验查询条件 ($or 匹配): {previous_companies}")
        elif len(company_filters) == 1:
            filters.append(company_filters[0])
            logger.debug(f"添加公司经验查询条件 (单一匹配): {previous_companies}")

    # --- NOW Handle Position and Certifications (Simplified Ambiguity Handling) ---
    # --- v1.2 Update: Modify Certifications handling using ranking_data ---
    position = parsed_data.get("position")
    certifications_data = parsed_data.get("certifications", []) # Expect list of dicts: [{'name': '...', 'modifier': '...'}]
    generic_level_keywords = [] # Store keywords from generic title queries

    # 1. Handle Position: Always use $or to search in positions OR certifications
    #    (Keep this logic for now, might handle ambiguous terms)
    if position and isinstance(position, str) and position.strip():
        pos_term = position.strip()
        filters.append({
            "$or": [
                {"query_tags.positions": {"$regex": pos_term, "$options": "i"}},
                {"query_tags.certifications": {"$regex": pos_term, "$options": "i"}}
            ]
        })
        logger.debug(f"处理职位/证书词 '{pos_term}'，使用 $or 在 positions 或 certifications 中搜索。")

    # 2. v1.2 Handle Certifications using get_matching_levels
    final_cert_list = []
    if certifications_data and isinstance(certifications_data, list):
        for cert_obj in certifications_data:
            # v1.2 update: Expecting {'name': '...', 'level_keyword': '...', 'modifier': '...'}
            if isinstance(cert_obj, dict) and 'name' in cert_obj:
                base_name = cert_obj.get('name')
                level_keyword = cert_obj.get('level_keyword') # Can be None or a string like "中级"
                modifier = cert_obj.get('modifier') # e.g., 'ge', 'eq', 'gt'. Not currently used by get_matching_levels but useful for logging/future

                # --- v1.2.3 Handle Generic Title Query --- 
                if (not base_name or base_name == "职称") and level_keyword and modifier:
                    # Generic level query (e.g., "中级以上职称")
                    logger.debug(f"处理泛指职称查询: level='{level_keyword}', mod='{modifier}'")
                    # We need to get the target level keywords based on modifier
                    if level_keyword in LEVEL_INFO:
                        info = LEVEL_INFO[level_keyword]
                        system = info["system"]
                        current_index = info["index"]
                        source_list = CHINESE_LEVELS if system == "chinese" else NUMERIC_LEVELS
                        target_indices = []
                        if modifier == "ge": target_indices = range(current_index, len(source_list))
                        elif modifier == "gt": target_indices = range(current_index + 1, len(source_list))
                        else: target_indices = [current_index]
                        target_keywords = [source_list[i] for i in target_indices if 0 <= i < len(source_list)]
                        if target_keywords:
                            generic_level_keywords.extend(target_keywords)
                            logger.debug(f"泛指职称查询生成目标关键词: {target_keywords}")
                    else:
                        logger.warning(f"泛指职称查询的等级关键词 '{level_keyword}' 未知，已忽略。")
                # --- End Generic Title Query Handling ---
                elif base_name and isinstance(base_name, str):
                    # Specific certificate query
                    base_name = base_name.strip()
                    # level_keyword can be None, get_matching_levels should handle it
                    if level_keyword and isinstance(level_keyword, str):
                        level_keyword = level_keyword.strip()
                    elif level_keyword is not None: # Handle cases where it's not a string but not None
                        logger.warning(f"证书对象中的 level_keyword 不是有效字符串: {level_keyword}, 将其视为 None。 对象: {cert_obj}")
                        level_keyword = None

                    # Pass base_name and level_keyword to get_matching_levels
                    # Modifier is not directly used by get_matching_levels currently
                    expanded_levels = get_matching_levels(base_name, level_keyword, modifier)
                    # --- DEBUG LOG --- 
                    logger.debug(f"get_matching_levels(base='{base_name}', kw='{level_keyword}', mod='{modifier}') returned: {expanded_levels}")
                    # --- END DEBUG LOG --- 

                    if expanded_levels:
                        final_cert_list.extend(expanded_levels)
                        logger.debug(f"处理证书 '{base_name}' (kw: {level_keyword}, mod: {modifier}), 扩展后等级: {expanded_levels}")
                else:
                    logger.warning(f"无效的证书基础名称在对象中: {cert_obj}")
            else:
                logger.warning(f"跳过无效的证书对象: {cert_obj}")

    # Combine specific cert names and generic level keywords for the final regex
    final_terms_for_regex = list(set(final_cert_list + generic_level_keywords))

    if final_terms_for_regex:
        # Remove duplicates
        # final_terms_for_regex is already a unique list from the set operation
        # v1.2.1 Change from $in to $regex with OR pattern for fuzzy matching
        # Escape special regex characters in each certificate name
        escaped_terms = [re.escape(term) for term in final_terms_for_regex]
        # Create the OR pattern
        regex_pattern = "|".join(escaped_terms)
        # --- DEBUG LOG --- 
        logger.debug(f"构建的证书/职称 Regex 模式: {regex_pattern}")
        # --- END DEBUG LOG ---
        filters.append({
            "query_tags.certifications": {
                "$regex": regex_pattern,
                "$options": "i" # Case-insensitive matching
            }
        })
        logger.info(f"添加扩展后的证书/职称查询条件 ($regex OR): {regex_pattern}")

    # --- Final Query Construction ---
    if filters:
        query["$and"] = filters

    # --- 新增：处理 design_category --- 
    if design_category := parsed_data.get('design_category'):
        if design_category in ["建筑设计", "电气设计", "给排水设计"]:
             # 精确匹配 design_category
             query['query_tags.design_category'] = design_category
        # 如果 design_category 是 null 或其他值，则不加入此筛选条件

    logger.info(f"构建的 MongoDB 查询: {query}")
    return query

# Modified _format_results_message to accept summary
def _format_results_message(results: list[Candidate], summary: Optional[str] = None, original_pool_size: Optional[int] = None) -> str:
    """将候选人列表格式化为发送给用户的消息，并可选地附加摘要。

    Args:
        results: 要展示的 Top N 候选人列表。
        summary: LLM 生成的摘要。
        original_pool_size: (可选) 排序前的候选人池大小，用于提供额外信息。
    """
    if not results:
        # This case might be handled before calling this function now
        return "抱歉，未找到符合条件的候选人。"

    display_count = len(results)
    # message_lines = [f"以下是 {len(results)} 位符合条件的候选人。请使用以下指令操作："]
    # More concise intro:
    if original_pool_size and original_pool_size > display_count:
        message_lines = [f"从 {original_pool_size} 位初步匹配者中，为您筛选出评分最高的 {display_count} 位候选人:"]
    else:
        message_lines = [f"找到 {display_count} 位符合条件的候选人:"]

    for i, candidate in enumerate(results):
        name = candidate.name or "未知姓名"
        position = (candidate.query_tags.get("positions") or ["未知职位"])[0]
        experience = candidate.query_tags.get("min_experience_years")
        exp_str = f"{experience}年经验" if experience is not None else "经验未知"
        skills = candidate.extracted_info.get("skills", [])
        skills_str = ", ".join(skills[:3]) + ("..." if len(skills) > 3 else "")
        skills_display = f" (技能: {skills_str})" if skills_str else ""
        # Use relative index (1-based) for display
        message_lines.append(f"{i + 1}. {name} - {position} - {exp_str}{skills_display}")
        # Optionally display score for debugging:
        # if 'match_score' in candidate.__dict__: # Check if score attribute exists (may need conversion to dict)
        #     message_lines[-1] += f" (Score: {candidate.match_score:.2f})"

    # Append the summary if provided
    if summary:
        message_lines.append("\n--- 简要分析 ---")
        message_lines.append(summary)

    # Append instructions
    message_lines.append("\n--- 指令示例 ---")
    message_lines.append("- 获取简历: 简历 1 (可指定多个)")
    message_lines.append("- 获取详细信息: 信息 2 (可指定多个)")
    message_lines.append("- 联系候选人: 联系 1 (只能指定一个)")
    message_lines.append("- 查看更多匹配: A (按评分排序)") # Clarify pagination order
    message_lines.append("- 都不满意/放弃: B")

    return "\n".join(message_lines)

# --- New Reusable Function --- 
def _fetch_and_send_candidates(
    wcf: Wcf,
    msg: WxMsg, # Pass msg for context (sender, roomid)
    query_criteria: Dict[str, Any],
    offset: int, # Offset for pagination (refers to the *original* sorted pool)
    # limit: int, # Limit now comes from config for final display
    state_manager,
    parsed_query_data: Dict[str, Any] # Pass the originally parsed LLM query data for scoring
) -> bool:
    """
    根据查询条件获取候选人，进行评分排序，(获取摘要)，格式化并发送Top N列表，更新状态。
    返回 True 如果找到了候选人，否则返回 False。
    """
    sender_wxid = msg.sender
    room_id = msg.roomid if msg.from_group() else None
    receiver_id = room_id if room_id else sender_wxid
    at_user_id = sender_wxid if room_id else None
    context_key = f"{sender_wxid}_{room_id}" if room_id else sender_wxid

    # --- Get Scoring Configuration --- 
    scoring_config = get_scoring_rules()
    perform_scoring = scoring_config is not None
    initial_pool_size = scoring_config.get('initial_candidate_pool_size', 30) if perform_scoring else 5 # Default limit if scoring disabled
    display_limit = 5 # How many candidates to show per page (fixed for now)

    # --- Database Query (Get initial pool or just display limit) --- 
    candidates_pool_models: List[Candidate] = []
    total_found_in_db = 0 # How many were found in total matching criteria (for logging)
    
    # If scoring is enabled, we fetch a larger pool initially ONLY for the first page (offset == 0)
    # For subsequent pages (offset > 0), we fetch only the required display_limit
    # as the full pool ranking is assumed to be stable.
    # This needs refinement for true pagination of a large ranked list.
    # Let's simplify: Always fetch initial_pool_size if scoring, otherwise display_limit.
    fetch_limit = initial_pool_size if perform_scoring else display_limit

    # IMPORTANT Pagination Note:
    # If scoring is enabled, offset applies to the *potentially larger* initial pool.
    # If scoring is disabled, offset applies directly to the database query.
    # The logic here assumes we fetch the full pool, score, sort, then paginate in memory.
    # This is INEFFICIENT for large datasets. A better approach would involve
    # storing scores or using DB-level sorting if possible.
    # For now, proceed with in-memory sorting of the initial pool.

    fetch_offset = 0 # We always fetch the full pool from offset 0 for in-memory sorting
    if not perform_scoring:
        fetch_offset = offset # If not scoring, offset applies directly

    try:
        logger.info(f"数据库查询开始 (上下文: {context_key}, offset: {fetch_offset}, limit: {fetch_limit}) query: {query_criteria}")
        # We fetch the initial pool (or just display limit if not scoring)
        candidates_pool_models = db_interface.find_candidates(query_criteria, limit=fetch_limit, offset=fetch_offset)
        total_found_in_db = len(candidates_pool_models) # Rough count from this fetch
        logger.info(f"数据库查询完成，初步找到 {total_found_in_db} 位候选人。")
    except Exception as e:
        logger.error(f"数据库查询失败 (上下文: {context_key}, query={query_criteria}, offset={fetch_offset}): {e}", exc_info=True)
        # 使用企业微信服务发送错误提示
        asyncio.create_task(
            ew_service.send_text_message(
                content="抱歉，查询候选人时遇到数据库错误，请稍后再试。",
                user_ids=[receiver_id]
            )
        )
        state_manager.clear_state(context_key)
        return False

    # --- Scoring and Sorting (if enabled and candidates found) ---
    scored_and_sorted_candidates: List[Candidate] = candidates_pool_models
    if perform_scoring and candidates_pool_models:
        logger.info(f"开始为 {total_found_in_db} 位候选人进行评分 (上下文: {context_key})...")
        dimensions_config = scoring_config.get('dimensions', {})
        candidate_scores = {}
        for candidate in candidates_pool_models:
            total_score = 0.0
            # Use candidate.__dict__ or a custom to_dict method if needed for path access
            try:
                # Attempt to get candidate data as dict for path access in scoring
                candidate_dict = candidate.to_dict() # Assuming Candidate model has a to_dict method
            except AttributeError:
                 logger.error(f"Candidate object {candidate.name if hasattr(candidate, 'name') else 'Unknown'} does not have a to_dict method. Falling back to direct attribute access (might fail for nested paths).")
                 # Fallback or specific handling if to_dict doesn't exist
                 # For now, we might need to adjust how _safe_get_value works or pass candidate directly
                 # Let's assume to_dict exists for now based on previous implementation assumption.
                 # If this fails, scoring logic needs rework or Candidate model needs update.
                 candidate_dict = candidate.__dict__ # Less safe fallback

            for dim_name, dim_config in dimensions_config.items():
                if dim_config.get('enabled', False):
                    try:
                        dim_score = calculate_score_for_dimension(dim_config, parsed_query_data, candidate_dict)
                        total_score += dim_score
                        # logger.debug(f" Cand {candidate.name}, Dim '{dim_name}', Score: {dim_score:.2f}")
                    except Exception as e:
                        logger.error(f"计算维度 '{dim_name}' 分数时出错 for candidate {candidate.name if hasattr(candidate, 'name') else 'Unknown'}: {e}", exc_info=True)
            # Store score directly on the object (if mutable) or in a separate map
            # candidate.match_score = total_score # Requires adding attribute to Candidate model or using setattr
            # Use candidate._id (MongoDB default ID field name) and convert to string for dict key
            if hasattr(candidate, '_id') and candidate._id:
                 candidate_scores[str(candidate._id)] = total_score # Use str(_id) as key
                 logger.debug(f"候选人 {candidate.name} (ID: {candidate._id}) 总分: {total_score:.2f}")
            else:
                 logger.warning(f"候选人 {candidate.name if hasattr(candidate, 'name') else 'Unknown'} 缺少 _id 属性，无法存储分数。")

        # Sort the original list based on scores from the map
        scored_and_sorted_candidates = sorted(
            candidates_pool_models,
            # Use str(_id) to get the key from the map
            key=lambda c: candidate_scores.get(str(c._id), 0) if hasattr(c, '_id') else 0,
            reverse=True
        )
        logger.info(f"候选人评分和排序完成 (上下文: {context_key}).")
        # Clear score map if not needed
        del candidate_scores

    # --- Pagination of Scored/Sorted List --- 
    # Now apply the pagination offset and limit to the *scored_and_sorted_candidates* list
    start_index = offset
    end_index = offset + display_limit
    candidates_to_display = scored_and_sorted_candidates[start_index:end_index]
    original_pool_size_info = total_found_in_db if perform_scoring else None # Size before pagination

    # --- Handle Sending and State Update --- 
    if candidates_to_display:
        # --- Get Brief Comparison Summary (Only for the candidates being displayed) --- 
        summary_text = None
        candidates_info_for_summary = [
            {
                "index": i + 1, # Relative index for this page
                "name": cand.name,
                "extracted_info": cand.extracted_info
            }
            for i, cand in enumerate(candidates_to_display) # Use the final list
        ]
        if candidates_info_for_summary:
            try:
                # Use the originally parsed query data for context
                summary_text = llm_client.get_brief_comparison_summary(parsed_query_data, candidates_info_for_summary)
                if not summary_text:
                    logger.warning(f"未能为上下文 [{context_key}] 生成简短对比摘要。将只发送列表。")
            except Exception as e:
                logger.error(f"调用 LLM 生成简短摘要时出错 (上下文: {context_key}): {e}", exc_info=True)
                summary_text = None 
        
        # Format and send the list (passing the summary and original pool size)
        response_message = _format_results_message(candidates_to_display, summary_text, original_pool_size_info)
        logger.info(f"准备向目标 [{receiver_id}] (来自上下文: {context_key}) 发送结果消息 (第 {offset // display_limit + 1} 页)..." )
        # 异步发送结果消息
        asyncio.create_task(
            ew_service.send_text_message(
                content=response_message,
                user_ids=[receiver_id],
                tag_ids=[at_user_id] if at_user_id else None
            )
        )
        # 省略同步结果检查与错误回退，假定异步发送成功
        
        # Prepare results for caching (using relative index for *this page*)
        cached_results = [
            {
                "index": i + 1, # Store relative index (1 to N) for the current page
                "wxid": cand.wxid,
                "resume_path": cand.resume_pdf_path,
                "name": cand.name,
                "extracted_info": cand.extracted_info
            }
            for i, cand in enumerate(candidates_to_display) # Use the final list
        ]
        
        # Update state
        # next_offset should point to the start of the *next* page in the scored/sorted list
        next_offset = end_index # The start index for the next page
        # Check if there might be more candidates in the original pool beyond the next page
        has_more = next_offset < len(scored_and_sorted_candidates)

        state_manager.update_state_and_cache_results(
            user_id=context_key,
            state=STATE_WAITING_SELECTION,
            results=cached_results,
            query_criteria=query_criteria, # The mongo query used to get the pool
            parsed_query_data=parsed_query_data, # Store the parsed data for rescoring if needed?
            current_offset=next_offset, # Offset for the *next* page fetch (in the sorted list)
            has_more=has_more, # Store if more candidates might exist in the pool
            # Store the full sorted list? Might be too large. Store only IDs?
            # sorted_candidate_ids=[c.id for c in scored_and_sorted_candidates] # Option for pagination
        )
        logger.info(f"上下文 [{context_key}] 状态更新为等待选择，缓存了 {len(candidates_to_display)} 条结果，下次偏移量 {next_offset}。可能有更多: {has_more}")
        return True # Indicate success (candidates found and sent)
    else:
        # No candidates found at this offset in the scored list
        # This could happen if offset is beyond the total number found
        if offset == 0:
             # If it was the first page, means no candidates matched at all
             logger.info(f"在数据库查询 {query_criteria} 后，未找到任何候选人。")
             asyncio.create_task(
                 ew_service.send_text_message(
                     content="抱歉，未找到符合条件的候选人。",
                     user_ids=[receiver_id],
                     tag_ids=[at_user_id] if at_user_id else None
                 )
             )
             state_manager.clear_state(context_key)
             return False # Indicate no candidates found initially
        else:
             # If it was a subsequent page ('A' command), means no more candidates
             logger.info(f"在偏移量 {offset} 处，没有更多符合条件的候选人（上下文: {context_key}）。")
             # Message is handled by selection_handler
             return False # Indicate no more candidates found for pagination

# --- Modified process_query --- 
def process_query(wcf: Wcf, msg: WxMsg, parsed_data: Dict[str, Any], state_manager):
    """
    处理识别出的招聘查询意图 (入口点)。
    """
    sender_wxid = msg.sender
    room_id = msg.roomid if msg.from_group() else None
    receiver_id = room_id if room_id else sender_wxid
    at_user_id = sender_wxid if room_id else None
    context_key = f"{sender_wxid}_{room_id}" if room_id else sender_wxid

    logger.info(f"开始处理上下文 [{context_key}] 的初始查询: {parsed_data}")

    # 1. Build query
    mongo_query = _build_mongo_query(parsed_data)
    if not mongo_query.get("$and"):
        logger.warning(f"无法从解析数据 {parsed_data} 构建有效的查询条件。")
        # 使用企业微信服务发送错误提示
        asyncio.create_task(
            ew_service.send_text_message(
                content="抱歉，我无法根据您的描述构建有效的查询。请提供更具体的职位、经验或技能要求。",
                user_ids=[receiver_id]
            )
        )
        state_manager.clear_state(context_key)
        return
    
    # 2. Store the parsed_data (user criteria) in state *before* fetching
    # This is needed for scoring and potentially for rescoring/summary on page 'A'
    state_manager.store_parsed_query_data(context_key, parsed_data)
    logger.debug(f"上下文 [{context_key}] 的原始解析查询条件已存储。")

    # 3. Fetch, Score, Sort, Send first page (offset=0)
    # limit = 5 # Display limit per page
    try:
        candidates_found = _fetch_and_send_candidates(
            wcf=wcf,
            msg=msg,
            query_criteria=mongo_query,
            offset=0,
            # limit=limit, # Limit handled inside
            state_manager=state_manager,
            parsed_query_data=parsed_data # Pass parsed data for scoring
        )
        # The function now handles sending "not found" if applicable
        if not candidates_found and state_manager.get_state(context_key) != STATE_WAITING_SELECTION:
             logger.info(f"处理查询后，上下文 [{context_key}] 未找到候选人或遇到错误，状态已清除。")
        elif candidates_found:
             logger.info(f"成功处理初始查询并发送第一页结果 (上下文: {context_key})。")

    except Exception as e:
        logger.critical(f"处理查询时发生意外错误 (上下文: {context_key}): {e}", exc_info=True)
        # 异常时发送通用错误提示
        asyncio.create_task(
            ew_service.send_text_message(
                content="处理您的查询时发生内部错误，请稍后重试。",
                user_ids=[receiver_id]
            )
        )
        state_manager.clear_state(context_key)

if __name__ == '__main__':
    logger.warning("query_handler.py 的 __main__ 部分仅用于说明，无法直接运行完整流程。")
    # 这里的模拟测试需要重写以适应 state_manager，或者移除
    pass 