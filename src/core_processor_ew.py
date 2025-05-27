import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, Optional, List
import re

from src.enterprise_wechat_service import EnterpriseWeChatService
from src.handlers.auth_handler_ew import AuthHandlerEw
from src.llm_client import LLMClient
from src.db_interface import DBInterface
from src.utils.state_manager import (
    state_manager, STATE_IDLE, STATE_WAITING_SELECTION,
    STATE_CONTACT_CANDIDATE_DETAILS_FLOW, 
    STEP_AWAITING_WORK_LOCATION, 
    STEP_AWAITING_JOB_CONTENT, 
    STEP_AWAITING_TIME_ARRANGEMENT
)
from src import config_ew
from src.utils.ranking_data import get_matching_levels, LEVEL_INFO, CHINESE_LEVELS, NUMERIC_LEVELS
from src import config  # 导入通用配置以获取评分规则
from src.utils.scoring_utils import calculate_score_for_dimension  # 导入评分函数
from src.processors.sync_processor import SyncProcessor

logger = logging.getLogger(__name__)

# --- Skill Synonyms Definition (from query_handler.py) ---
SKILL_SYNONYMS = [
    {"cad", "autocad", "cad制图"},
    # {"python", "py"}, # Add more synonym groups here as needed
]
# --- End Skill Synonyms Definition ---

class CoreProcessor:
    """
    核心处理器，负责处理来自企业微信的消息，协调各个组件完成招聘任务。
    """
    def __init__(self, ew_service: EnterpriseWeChatService):
        """
        初始化核心处理器。

        Args:
            ew_service: EnterpriseWeChatService的实例，用于与企业微信API交互。
        """
        self.ew_service = ew_service
        self.auth_handler = AuthHandlerEw()
        
        self.llm_client = LLMClient()
        self.db_interface = DBInterface()
        self.state_manager = state_manager
        self.sync_processor = SyncProcessor(ew_service=self.ew_service, db_interface=self.db_interface)
        
        max_workers = 5
        if hasattr(config_ew, 'WECOM_CORE_PROCESSOR_MAX_WORKERS'):
            try:
                max_workers = int(config_ew.WECOM_CORE_PROCESSOR_MAX_WORKERS)
            except ValueError:
                logger.warning(f"无法将 WECOM_CORE_PROCESSOR_MAX_WORKERS ('{config_ew.WECOM_CORE_PROCESSOR_MAX_WORKERS}') 解析为整数，将使用默认值 {max_workers}")
        
        self.thread_pool = ThreadPoolExecutor(max_workers=max_workers)

        logger.info(f"CoreProcessor 初始化完成，依赖组件已加载。线程池最大工作数: {max_workers}。") # TTL 信息由 StateManager 自己记录

    # --- Helper function for skill expansion (from query_handler.py) ---
    def _expand_skills(self, skills: List[str]) -> List[str]: # Made it a method
        """将技能列表根据 SKILL_SYNONYMS 进行扩展。"""
        if not skills:
            return []
        
        expanded_set = set()
        normalized_input_skills = {skill.strip().lower() for skill in skills if isinstance(skill, str) and skill.strip()}
        
        # found_in_group = set() # Not strictly needed for the logic if we just update expanded_set
        for skill in normalized_input_skills:
            matched_group = False
            for group in SKILL_SYNONYMS: # SKILL_SYNONYMS is now a global constant in this module
                if skill in group:
                    expanded_set.update(group)
                    # found_in_group.add(skill) 
                    matched_group = True
                    break
            if not matched_group:
                expanded_set.add(skill)
                
        final_list = list(expanded_set)
        logger.debug(f"原始技能: {skills}, 扩展后技能: {final_list}")
        return final_list
    # --- End helper function ---

    # --- Build MongoDB Query (adapted from query_handler.py) ---
    def _build_mongo_query(self, parsed_data: Dict[str, Any]) -> Dict[str, Any]: # Made it a method
        """根据 LLM 解析的数据构建 MongoDB 查询条件。"""
        query = {}
        filters = []

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
            expanded_skills = self._expand_skills(skills) 
            if expanded_skills:
                skill_or_conditions = []
                for skill_val in expanded_skills: # Renamed skill to skill_val to avoid conflict with outer scope if any
                    try:
                        escaped_skill = re.escape(skill_val)
                        skill_or_conditions.append({
                            "query_tags.skills_normalized": {"$regex": escaped_skill, "$options": "i"}
                        })
                    except Exception as e:
                        logger.error(f"处理技能 '{skill_val}' 构建 regex 时出错: {e}")
                
                if skill_or_conditions:
                    filters.append({"$or": skill_or_conditions})
                    logger.info(f"添加扩展/模糊技能查询条件 ($or): {expanded_skills}")

        # 处理地点
        location = parsed_data.get("location")
        if location and isinstance(location, str) and location.strip():
            filters.append({"query_tags.location": {"$regex": location.strip(), "$options": "i"}})
            logger.debug(f"添加地点查询条件: {location.strip()}")

        # 处理学历
        education_levels = parsed_data.get("education_levels")
        if education_levels and isinstance(education_levels, list) and len(education_levels) > 0:
            valid_levels = [level.strip() for level in education_levels if isinstance(level, str) and level.strip()]
            if valid_levels:
                expanded_levels_set = set(valid_levels)
                if "本科" in expanded_levels_set: expanded_levels_set.add("学士")
                if "学士" in expanded_levels_set: expanded_levels_set.add("本科")
                if "硕士" in expanded_levels_set: expanded_levels_set.add("研究生")
                if "研究生" in expanded_levels_set: expanded_levels_set.add("硕士")
                
                final_levels_list = list(expanded_levels_set)
                if final_levels_list:
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
            elif len(company_filters) == 1:
                filters.append(company_filters[0])
            logger.debug(f"添加公司经验查询条件: {previous_companies}")

        # 处理职位：根据是否指定证书动态模糊匹配 positions 和 certifications
        certifications_data = parsed_data.get("certifications", [])


        # 初始化后续证书列表与通用等级关键词列表
        final_cert_list = []
        if certifications_data and isinstance(certifications_data, list):
            for cert_obj in certifications_data:
                if isinstance(cert_obj, dict) and 'name' in cert_obj:
                    base_name = cert_obj.get('name')
                    level_keyword = cert_obj.get('level_keyword')
                    modifier = cert_obj.get('modifier')

                    if (not base_name or base_name == "职称") and level_keyword and modifier:
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
                                final_cert_list.extend(target_keywords)
                        else:
                            logger.warning(f"泛指职称查询的等级关键词 '{level_keyword}' 未知。")
                    elif base_name and isinstance(base_name, str):
                        base_name = base_name.strip()
                        if level_keyword and isinstance(level_keyword, str): level_keyword = level_keyword.strip()
                        elif level_keyword is not None: level_keyword = None
                        
                        expanded_levels = get_matching_levels(base_name, level_keyword, modifier)
                        if expanded_levels:
                            final_cert_list.extend(expanded_levels)
                    else:
                        logger.warning(f"无效的证书基础名称: {cert_obj}")
                else:
                    logger.warning(f"跳过无效的证书对象: {cert_obj}")
        
        final_terms_for_regex = list(set(final_cert_list))
        if final_terms_for_regex:
            escaped_terms = [re.escape(term) for term in final_terms_for_regex]
            regex_pattern = "|".join(escaped_terms)
            filters.append({"query_tags.certifications": {"$regex": regex_pattern, "$options": "i"}})
            logger.debug(f"添加证书模糊匹配查询条件 (OR pattern): {regex_pattern}")

        # --- 处理 design_category: 模糊匹配 design_category 字段 ---
        design_category = parsed_data.get("design_category")
        if isinstance(design_category, str) and design_category.strip():
            term = design_category.strip()
            try:
                pattern = re.escape(term)
                filters.append({
                    "query_tags.design_category": {"$regex": pattern, "$options": "i"}
                })
                logger.debug(f"处理 design_category 词 '{term}'，使用模糊匹配 design_category。")
            except Exception as e:
                logger.error(f"构建 design_category 模糊查询正则时出错: {e}")

        if filters:
            query["$and"] = filters
        
        logger.info(f"构建的 MongoDB 查询: {query if query else '{}'}")
        return query
    # --- End Build MongoDB Query ---

    async def handle_ew_message(self, msg_data: Dict[str, Any]):
        """
        处理从企业微信回调接收到的已解密和解析的消息数据。

        Args:
            msg_data (Dict[str, Any]): 包含消息详情的字典，
                                      例如: {'MsgType': 'text', 'FromUserName': 'user_id', 'Content': 'hello'}
        """
        logger.debug(f"CoreProcessor 收到消息: {msg_data}")

        user_id = msg_data.get("FromUserName")
        msg_type = msg_data.get("MsgType")
        content = msg_data.get("Content", "").strip() # Default to empty string if no content

        if not user_id:
            logger.warning("消息中缺少 FromUserName (user_id)，无法处理。")
            return

        # 1. 权限校验
        if not self.auth_handler.is_authorized(user_id):
            logger.info(f"用户 {user_id} 未授权，消息被忽略。")
            # Optionally, send a message to unauthorized user (be careful about spamming)
            # await self.ew_service.send_text_message(content="您没有权限使用此机器人。", user_ids=[user_id])
            return

        logger.info(f"用户 {user_id} 已授权。消息类型: {msg_type}, 内容: '{content}'")

        # 2. TODO: 检查是否为文本消息 (或其他我们支持的消息类型)
        if msg_type != "text":
            logger.info(f"接收到非文本消息类型 '{msg_type}' 来自用户 {user_id}，当前版本仅处理文本消息。")
            await self.ew_service.send_text_message(content="抱歉，我目前主要处理文本消息。", user_ids=[user_id])
            return

        if not content: # Handle empty text messages after stripping
            logger.info(f"用户 {user_id} 发送了空文本消息，已忽略。")
            # Optionally send a polite 'I didn't get that' message
            return

        # 3. TODO: 提交任务到线程池进行异步处理
        loop = asyncio.get_running_loop() # Prefer get_running_loop if sure one is running (e.g., in FastAPI)
        loop.run_in_executor(self.thread_pool, self._process_message_task_sync_wrapper, user_id, content, msg_data)
        logger.info(f"用户 {user_id} 的消息 '{content}' 已提交到线程池处理。")

    def _process_message_task_sync_wrapper(self, user_id: str, text_content: str, original_msg_data: Dict[str, Any]):
        """同步包装器，用于在线程池中运行异步任务。"""
        try:
            asyncio.run(self._process_message_task_async(user_id, text_content, original_msg_data))
        except Exception as e:
            # This top-level exception in the thread should be logged thoroughly.
            logger.critical(f"线程池任务执行中发生未捕获的严重错误 (用户: {user_id}, 内容: {text_content}): {e}", exc_info=True)
            # Consider how to notify admin or if a generic message should be sent to user.
            # Sending a message back to the user from here can be tricky if ew_service methods are async
            # and we are in a sync wrapper without an event loop.
            # For now, just log critical error.

    async def _process_message_task_async(self, user_id: str, text_content: str, original_msg_data: Dict[str, Any]):
        """
        异步处理文本消息的任务，包括新查询、后续选择或特定指令。
        """
        logger.info(f"ASYNC_TASK_DEBUG: 用户 {user_id} - 原始消息内容 (text_content): '{text_content}' (长度: {len(text_content)})")

        # 首先检查是否为特定指令, 允许带或不带 / 开头
        normalized_text_content = text_content.strip()
        logger.info(f"ASYNC_TASK_DEBUG: 用户 {user_id} - strip()后内容 (normalized_text_content): '{normalized_text_content}' (长度: {len(normalized_text_content)})")

        is_sync_command_slash = (normalized_text_content == "/sync_external_contacts")
        is_sync_command_plain = (normalized_text_content == "同步外部联系人")
        
        logger.info(f"ASYNC_TASK_DEBUG: 用户 {user_id} - normalized_text_content == '/sync_external_contacts': {is_sync_command_slash}")
        logger.info(f"ASYNC_TASK_DEBUG: 用户 {user_id} - normalized_text_content == '同步外部联系人': {is_sync_command_plain}")

        if is_sync_command_slash or is_sync_command_plain:
            logger.info(f"用户 {user_id} 触发了外部联系人同步指令 ('{text_content}')。")
            try:
                # 发送一个即时反馈给用户，告知任务已开始
                await self.ew_service.send_text_message(
                    content="收到外部联系人同步指令。任务正在后台执行中，完成后会通知您。",
                    user_ids=[user_id]
                )
                # 创建后台任务执行实际的同步操作，并等待它完成
                sync_task = asyncio.create_task(self.sync_processor.run_sync_for_hr(hr_userid=user_id, triggered_by_manual_command=True))
                logger.info(f"已为用户 {user_id} 创建后台同步任务，现在开始等待其完成...")
                await sync_task # <--- 新增：等待后台任务完成
                logger.info(f"用户 {user_id} 的后台同步任务已执行完毕。")
            except Exception as e:
                logger.error(f"处理外部联系人同步指令或其执行时出错 (用户: {user_id}): {e}", exc_info=True) # <--- 添加 exc_info=True
                try:
                    await self.ew_service.send_text_message(
                        content="执行外部联系人同步指令失败，请联系管理员。",
                        user_ids=[user_id]
                    )
                except Exception as e2:
                    logger.error(f"发送同步指令失败通知给用户 {user_id} 时再次出错: {e2}")
            return # 指令处理完毕，直接返回

        current_state = state_manager.get_state(user_id)
        logger.info(f"ASYNC_TASK_DEBUG: 用户 {user_id} - 当前状态 (从 state_manager 获取): {current_state}")

        if is_sync_command_slash or is_sync_command_plain: # 已在前面处理
            pass # 避免重复进入，因为同步指令已在前面处理并 await
        elif current_state == STATE_IDLE:
            logger.info(f"用户 {user_id} 处于空闲状态，将文本 '{normalized_text_content}' 作为新查询处理。")
            await self._handle_new_query_task(user_id, normalized_text_content)
        elif current_state == STATE_WAITING_SELECTION or current_state == STATE_CONTACT_CANDIDATE_DETAILS_FLOW:
            logger.info(f"用户 {user_id} 处于 {current_state} 状态，将文本 '{normalized_text_content}'作为后续操作处理。")
            await self._handle_follow_up_task(user_id, normalized_text_content)
        else:
            logger.warning(f"用户 {user_id} 处于未知或未处理状态: {current_state}，消息: '{normalized_text_content}' 被忽略。")
            # 可以选择发送一个通用提示
            await self.ew_service.send_text_message(
                content="抱歉，我现在无法理解您的指令。如果您想开始新的查询，请直接发送您的招聘需求。",
                user_ids=[user_id]
            )
            self.state_manager.clear_state(user_id) # 清除未知状态，返回IDLE

        logger.info(f"ASYNC_TASK_DEBUG: 用户 {user_id} 的消息 '{text_content}' 处理流程结束。")

    async def _handle_new_query_task(self, user_id: str, query_text: str):
        logger.info(f"开始处理新查询来自用户 {user_id}: '{query_text}'")
        
        # 1. Parse intent using LLMClient
        parsed_data = self.llm_client.parse_query_intent(query_text)

        if not parsed_data: # Includes None or empty dict from LLM
            logger.warning(f"LLM未能成功解析用户 {user_id} 的查询: '{query_text}'")
            await self.ew_service.send_text_message(content="抱歉，我不太理解您的需求，请换一种方式描述，或者更具体一些。", user_ids=[user_id])
            self.state_manager.clear_state(user_id) # Clear any potentially partially set state
            return

        # 2. 构建DB查询 
        mongo_query = self._build_mongo_query(parsed_data) 
        
        if not mongo_query or not mongo_query.get("$and"): # Check if any filters were actually added
            logger.warning(f"无法为用户 {user_id} 的解析数据构建有效的数据库查询 (无有效过滤器): {parsed_data}")
            await self.ew_service.send_text_message(content="抱歉，根据您的描述无法构建有效的查询条件，请尝试提供更具体的招聘要求。", user_ids=[user_id])
            self.state_manager.clear_state(user_id)
            return

        logger.info(f"为用户 {user_id} 构建的数据库查询条件: {mongo_query}")

        # 3. Query DBInterface
        pool_size = getattr(config_ew, 'INITIAL_CANDIDATE_POOL_SIZE', 30)
        candidates_pool = self.db_interface.find_candidates(mongo_query, limit=pool_size, offset=0)
        
        if not candidates_pool:
            logger.info(f"数据库查询未找到与用户 {user_id} 条件匹配的候选人。查询: {mongo_query}")
            await self.ew_service.send_text_message(content="抱歉，目前没有找到完全符合您条件的候选人。您可以稍后调整条件再试。", user_ids=[user_id])
            self.state_manager.clear_state(user_id)
            return

        # 4. 评分结果 (使用 scoring_utils)
        scoring_config = config.get_scoring_rules()
        if scoring_config:
            dimensions = scoring_config.get('dimensions', {})
            scored_list = []
            for candidate in candidates_pool:
                # 准备候选人数据用于评分
                candidate_data = {
                    'query_tags': candidate.query_tags if isinstance(candidate.query_tags, dict) else {},
                    'extracted_info': candidate.extracted_info if isinstance(candidate.extracted_info, dict) else {}
                }
                # 回退逻辑：如果 query_tags 中未设置技能/证书/地点，则使用 extracted_info 中对应数据
                tags = candidate_data['query_tags']
                info = candidate_data['extracted_info'] or {}
                # 技能回退
                if not tags.get('skills_normalized') and info.get('skills'):
                    tags['skills_normalized'] = [s.strip().lower() for s in info.get('skills', []) if isinstance(s, str)]
                # 证书回退
                if not tags.get('certifications') and info.get('certifications'):
                    tags['certifications'] = [c for c in info.get('certifications', []) if isinstance(c, str)]
                # 地点回退
                if not tags.get('location') and info.get('current_location'):
                    tags['location'] = info.get('current_location')
                candidate_data['query_tags'] = tags
                total_score = 0.0
                for dim_name, dim_conf in dimensions.items():
                    try:
                        # 计算该维度得分
                        dim_score = calculate_score_for_dimension(dim_conf, parsed_data, candidate_data)
                        # 记录维度得分
                        logger.info(f"候选人 {candidate.name} | 维度 '{dim_name}' 得分: {dim_score:.2f}")
                        total_score += dim_score
                    except Exception as e:
                        logger.error(f"评分维度 {dim_name} 计算错误: {e}")
                setattr(candidate, 'score', total_score)
                scored_list.append(candidate)
            # 按分数降序排序
            sorted_candidates = sorted(scored_list, key=lambda x: getattr(x, 'score', 0.0), reverse=True)
        else:
            sorted_candidates = candidates_pool

        # 5. 保存全局排序列表供后续选择命令使用
        self._last_sorted_candidates = sorted_candidates
        # 6. Select Top N
        top_n_count = getattr(config_ew, 'TOP_N_CANDIDATES', 5)
        top_n_candidates = sorted_candidates[:top_n_count]

        # 准备用于缓存和摘要的候选人关键信息字典列表
        candidate_details_for_cache = []
        for candidate in top_n_candidates:
            candidate_details_for_cache.append({
                "name": candidate.name,
                "extracted_info": getattr(candidate, 'extracted_info', None),
                "resume_pdf_path": getattr(candidate, 'resume_pdf_path', None),
                "wxid": getattr(candidate, 'wxid', None),
                "external_wecom_id": getattr(candidate, 'external_wecom_id', None),
                "score": getattr(candidate, 'score', None)
            })
        # 7. 构建基于查询条件和候选人数据的对比分析摘要
        summary_lines = ["**对比分析摘要：**"]
        for i, cand in enumerate(top_n_candidates, 1):
            # 实际工作年限
            exp_actual = cand.query_tags.get('min_experience_years') if hasattr(cand, 'query_tags') else None
            exp_str = f"{exp_actual}年经验" if exp_actual is not None else "经验未知"
            # 职称列表
            certs = cand.query_tags.get('certifications') if hasattr(cand, 'query_tags') else []
            cert_str = "、".join(certs) if certs else "无职称信息"
            summary_lines.append(f"{i}. **{cand.name}**：{exp_str}，**{cert_str}**。")
        summary_text = "\n".join(summary_lines)

        # 8. Format response (list of candidates + summary + options)
        # 显示总候选人数量及当前页范围
        total_candidates = len(sorted_candidates)
        displayed_end = len(top_n_candidates)
        response_message_parts = [f"根据您的需求，共找到 {total_candidates} 位候选人，显示第 1 到 {displayed_end} 位："]
        for i, candidate in enumerate(top_n_candidates, 1):
            # 获取候选人名称和分数
            candidate_name = candidate.name or f"候选人{i}"
            score = getattr(candidate, 'score', None)
            score_text = f" (匹配度: {score:.1f})" if score is not None else ""
            # 仅列表序号、姓名与匹配度
            response_message_parts.append(
                f"{i}. {candidate_name}{score_text}"
            )
            
            # 格式化过程中已构建 candidate_details_for_cache，用于更新状态缓存

        response_message_parts.append(summary_text)
        response_message_parts.append("\n您可以回复：")
        response_message_parts.append("  - '简历 X': 获取第X位候选人的简历")
        response_message_parts.append("  - '信息 X': 获取第X位候选人的详细信息")
        response_message_parts.append("  - '联系 X': 联系第X位候选人")
        response_message_parts.append("  - 'A': 查看更多")
        response_message_parts.append("  - 'B': 都不满意/结束")
        
        final_response_text = "\n".join(response_message_parts)
        # 记录回复内容到日志并打印到终端，方便调试
        logger.info(f"回复内容 (用户 {user_id}):\n{final_response_text}")
        print(f"回复内容 (用户 {user_id}):\n{final_response_text}")

        # TODO: 9. Set state using StateManager
        self.state_manager.update_state_and_cache_results(
            user_id=user_id,
            state=STATE_WAITING_SELECTION,
            results=candidate_details_for_cache,
            query_criteria=mongo_query,
            parsed_query_data=parsed_data,
            current_offset=len(top_n_candidates),
            has_more=len(sorted_candidates) > len(top_n_candidates)
        )

        # 10. Send response using self.ew_service
        await self.ew_service.send_text_message(content=final_response_text, user_ids=[user_id])
        logger.info(f"已向用户 {user_id} 发送初步候选人列表和摘要。")

    async def _handle_follow_up_task(self, user_id: str, reply_text: str):
        logger.info(f"开始处理后续操作来自用户 {user_id}: '{reply_text}'")
        # 处理多步联系候选人流程
        contact_flow = self.state_manager.get_contact_flow_state(user_id)
        if contact_flow:
            step = contact_flow.get('step')
            candidate_external_id = contact_flow.get('candidate_external_userid')
            candidate_name = contact_flow.get('candidate_name')
            collected_info = contact_flow.get('collected_info', {})
            # 第一步：工作地点
            if step == STEP_AWAITING_WORK_LOCATION:
                work_location = reply_text.strip()
                # 更新状态至请求工作内容
                self.state_manager.update_contact_flow_step_and_info(
                    user_id, STEP_AWAITING_JOB_CONTENT,
                    info_key_to_update='work_location',
                    info_value=work_location
                )
                await self.ew_service.send_text_message(
                    content=f"已记录工作地点：{work_location}。请提供候选人 [{candidate_name}] 的工作内容：",
                    user_ids=[user_id]
                )
                return
            # 第二步：工作内容
            if step == STEP_AWAITING_JOB_CONTENT:
                job_content = reply_text.strip()
                self.state_manager.update_contact_flow_step_and_info(
                    user_id, STEP_AWAITING_TIME_ARRANGEMENT,
                    info_key_to_update='job_content',
                    info_value=job_content
                )
                await self.ew_service.send_text_message(
                    content=f"已记录工作内容：{job_content}。请提供您希望的沟通时间：",
                    user_ids=[user_id]
                )
                return
            # 第三步：沟通时间
            if step == STEP_AWAITING_TIME_ARRANGEMENT:
                time_arr = reply_text.strip()
                # 更新时间信息并完成流程
                self.state_manager.update_contact_flow_step_and_info(
                    user_id, STATE_CONTACT_CANDIDATE_DETAILS_FLOW,
                    info_key_to_update='time_arrangement',
                    info_value=time_arr
                )
                info = self.state_manager.get_contact_flow_state(user_id).get('collected_info', {})
                # 构造邀请消息
                inv_message = (
                    f"您好，{candidate_name}，" 
                    f"我们希望在 {info.get('work_location')} 安排 {info.get('job_content')} 的岗位洽谈，" 
                    f"时间定在 {time_arr}，请您确认，谢谢！"
                )
                try:
                    # 使用与 send_message_to_external_contact 签名匹配的参数
                    await self.ew_service.send_message_to_external_contact(
                        sender_userid=user_id,
                        external_user_id=candidate_external_id,
                        message_text=inv_message
                    )
                    await self.ew_service.send_text_message(
                        content="已向候选人发送沟通邀请，流程结束。", user_ids=[user_id]
                    )
                except Exception as e:
                    logger.error(f"联系候选人时出错: {e}", exc_info=True)
                    await self.ew_service.send_text_message(
                        content="发送沟通邀请失败，请稍后重试。", user_ids=[user_id]
                    )
                # 清理状态
                self.state_manager.clear_state(user_id)
                return

        # 获取缓存的上次查询结果和相关上下文
        last_results = self.state_manager.get_last_results(user_id)
        query_criteria = self.state_manager.get_query_criteria(user_id)
        parsed_data = self.state_manager.get_parsed_query_data(user_id)
        offset = self.state_manager.get_query_offset(user_id)
        has_more = self.state_manager.get_has_more(user_id)
        if not last_results or not query_criteria:
            await self.ew_service.send_text_message(content="抱歉，您的操作已超时或状态已丢失，请重新发起查询。", user_ids=[user_id])
            self.state_manager.clear_state(user_id)
            return
        cmd = reply_text.strip()
        lower = cmd.lower()
        # 获取全局排序列表
        full_sorted = getattr(self, '_last_sorted_candidates', [])
        total_sorted = len(full_sorted)

        # 处理 '简历 X'
        if lower.startswith("简历 "):
            parts = cmd.split()
            if len(parts) >= 2 and parts[1].isdigit():
                selected = int(parts[1])
                # 全局映射
                if 1 <= selected <= total_sorted:
                    cand = full_sorted[selected-1]
                    resume_path = getattr(cand, 'resume_pdf_path', None)
                if resume_path:
                    try:
                        media_id = await self.ew_service.upload_temporary_media(resume_path)
                        if media_id:
                            await self.ew_service.send_file_message(media_id=media_id, user_ids=[user_id])
                        else:
                            await self.ew_service.send_text_message(content=f"抱歉，无法上传第{selected}位候选人的简历。", user_ids=[user_id])
                    except Exception as e:
                        logger.error(f"发送简历错误: {e}", exc_info=True)
                        await self.ew_service.send_text_message(content="发送简历时出错。", user_ids=[user_id])
                    # 提示用户后续操作选项
                    await self.ew_service.send_text_message(
                        content="您可以继续回复：'简历 X' 获取简历、'信息 X' 获取详细信息、'联系 X' 联系候选人、'A' 查看更多、'B' 结束。",
                        user_ids=[user_id]
                    )
                    return
                await self.ew_service.send_text_message(content="请使用格式 '简历 X'，例如 '简历 1'。", user_ids=[user_id])
                return
        # 处理 '信息 X'
        if lower.startswith("信息 "):
            parts = cmd.split()
            if len(parts) >= 2 and parts[1].isdigit():
                selected = int(parts[1])
                # 全局映射
                if 1 <= selected <= total_sorted:
                    cand = full_sorted[selected-1]
                    info = getattr(cand, 'extracted_info', {}) or {}
                info_text = "\n".join(f"{k}: {v}" for k, v in info.items())
                await self.ew_service.send_text_message(content=info_text or "暂无详细信息。", user_ids=[user_id])
                # 提示用户后续操作选项
                await self.ew_service.send_text_message(
                    content="您可以继续回复：'简历 X' 获取简历、'信息 X' 获取详细信息、'联系 X' 联系候选人、'A' 查看更多、'B' 结束。",
                    user_ids=[user_id]
                )
                return
            await self.ew_service.send_text_message(content="请使用格式 '信息 X'，例如 '信息 1'。", user_ids=[user_id])
            return
        # 处理 '联系 X'
        if lower.startswith("联系 ") or lower.startswith("聯絡 ") or lower.startswith("联络 "): # Added variants for "联系"
            parts = cmd.split()
            if len(parts) >= 2 and parts[1].isdigit():
                selected_idx_one_based = int(parts[1])
                if last_results and 1 <= selected_idx_one_based <= len(last_results):
                    candidate_data_from_cache = last_results[selected_idx_one_based - 1]
                    # 使用候选人缓存中的 wxid 作为 external_wecom_id
                    candidate_external_id = candidate_data_from_cache.get('external_wecom_id') or candidate_data_from_cache.get('wxid')
                    # 'candidate_name_for_contact_flow' was stored for this purpose
                    candidate_name = candidate_data_from_cache.get('candidate_name_for_contact_flow', candidate_data_from_cache.get('name', '未知候选人'))

                    if candidate_external_id and candidate_name:
                        logger.info(f"用户 {user_id} 选择联系候选人: {candidate_name} ({candidate_external_id})。启动信息收集流程。")
                        self.state_manager.set_contact_flow_state(
                            user_id=user_id,
                            step=STEP_AWAITING_WORK_LOCATION,
                            candidate_external_userid=candidate_external_id,
                            candidate_name=candidate_name,
                            hr_sender_userid=user_id, # The HR interacting is the sender
                            collected_info={} # Initialize empty collected_info
                        )
                        await self.ew_service.send_text_message(
                            content=f"请提供候选人 [{candidate_name}] 的工作地点：",
                            user_ids=[user_id]
                        )
                    else:
                        logger.warning(f"无法为序号 {selected_idx_one_based} 的候选人获取 external_wecom_id 或 name。缓存数据: {candidate_data_from_cache}")
                        await self.ew_service.send_text_message(content=f"抱歉，无法获取第 {selected_idx_one_based} 位候选人的外部联系ID或姓名，无法发起联系。", user_ids=[user_id])
                    return 
                else:
                    await self.ew_service.send_text_message(content=f"无效的序号。请输入 1 到 {len(last_results) if last_results else 0} 之间的数字。", user_ids=[user_id])
                    return
            await self.ew_service.send_text_message(content="请使用格式 '联系 X' (或 '联络 X')，例如 '联系 1'。", user_ids=[user_id])
            return
        # 处理 'A' (查看更多)
        if lower == 'a':
            # 查看下一页候选人，先获取全量候选人池并重新评分排序
            if has_more:
                # 拉取候选人池（从 offset=0）的初始数据用于排序
                pool_size = getattr(config_ew, 'INITIAL_CANDIDATE_POOL_SIZE', 30)
                full_pool = self.db_interface.find_candidates(query_criteria, limit=pool_size, offset=0)
                if not full_pool:
                    await self.ew_service.send_text_message(content="没有更多符合条件的候选人了。", user_ids=[user_id])
                    self.state_manager.clear_state(user_id)
                    return

                # 对全量池进行评分和排序
                scoring_config = config.get_scoring_rules()
                if scoring_config:
                    dimensions = scoring_config.get('dimensions', {})
                    scored_list = []
                    for cand in full_pool:
                        cand_data = {'query_tags': cand.query_tags or {}, 'extracted_info': cand.extracted_info or {}}
                        total_score = 0.0
                        for dim_name, dim_conf in dimensions.items():
                            try:
                                score = calculate_score_for_dimension(dim_conf, parsed_data, cand_data)
                                total_score += score
                            except Exception as e:
                                logger.error(f"分页评分维度 {dim_name} 错误: {e}")
                        setattr(cand, 'score', total_score)
                        scored_list.append(cand)
                    sorted_full = sorted(scored_list, key=lambda x: getattr(x, 'score', 0.0), reverse=True)
                else:
                    sorted_full = full_pool

                # 依据当前偏移进行分页
                top_n = getattr(config_ew, 'TOP_N_CANDIDATES', 5)
                start = offset
                end = offset + top_n
                next_page = sorted_full[start:end]
                if not next_page:
                    await self.ew_service.send_text_message(content="没有更多符合条件的候选人了。", user_ids=[user_id])
                    self.state_manager.clear_state(user_id)
                    return

                # 构建缓存详情和摘要
                details = []
                for cand in next_page:
                    details.append({
                        'name': cand.name,
                        'extracted_info': cand.extracted_info,
                        'resume_pdf_path': cand.resume_pdf_path,
                        'wxid': cand.wxid,
                        'score': getattr(cand, 'score', None)
                    })

                # 手动构建摘要，基于查询条件和候选人 query_tags
                summary_lines = ["**对比分析摘要：**"]
                for idx, cand in enumerate(next_page, start + 1):
                    # 实际工作年限
                    exp_actual = cand.query_tags.get('min_experience_years') if hasattr(cand, 'query_tags') else None
                    exp_str = f"{exp_actual}年经验" if exp_actual is not None else "经验未知"
                    # 职称列表
                    certs = cand.query_tags.get('certifications') if hasattr(cand, 'query_tags') else []
                    cert_str = "、".join(certs) if certs else "无职称信息"
                    summary_lines.append(f"{idx}. **{cand.name}**：{exp_str}，**{cert_str}**。")
                summary = "\n".join(summary_lines)

                # 格式化下一页结果
                # 显示总候选人数量及当前页范围
                total_candidates = len(sorted_full)
                start_idx = start + 1
                end_idx = end if end <= total_candidates else total_candidates
                response_parts = [f"根据您的需求，共找到 {total_candidates} 位候选人，显示第 {start_idx} 到 {end_idx} 位："]
                for i, cand in enumerate(next_page, start_idx):
                    name = cand.name or f"候选人{i}"
                    score_txt = f" (匹配度: {getattr(cand, 'score', 0.0):.1f})"
                    raw = cand.extracted_info.get('summary') if cand.extracted_info else None
                    excerpt = raw[:50] + '...' if raw and len(raw) > 50 else (raw or '暂无摘要')
                    response_parts.append(f"{i}. {name}{score_txt}")
                response_parts.append(f"\n{summary}")
                response_parts.append("\n您可以继续回复：'简历 X', '信息 X', '联系 X', 'A' 查看更多, 'B' 结束")
                final_response = "\n".join(response_parts)

                # 更新状态并刷新缓存
                self.state_manager.update_state_and_cache_results(
                    user_id=user_id,
                    state=STATE_WAITING_SELECTION,
                    results=details,
                    query_criteria=query_criteria,
                    parsed_query_data=parsed_data,
                    current_offset=end,
                    has_more=len(sorted_full) > end
                )

                # 发送下一页结果
                await self.ew_service.send_text_message(content=final_response, user_ids=[user_id])
            else:
                await self.ew_service.send_text_message(content="没有更多符合条件的候选人了。", user_ids=[user_id])
                self.state_manager.clear_state(user_id)
            return
        # 处理 'B' (结束)
        if lower == 'b':
            await self.ew_service.send_text_message(content="好的，已结束本次查询。", user_ids=[user_id])
            self.state_manager.clear_state(user_id)
            return
        # 无效指令
        await self.ew_service.send_text_message(content="无效指令。请回复 '简历 X', '信息 X', '联系 X', 'A', 或 'B'。", user_ids=[user_id])
        return

    async def shutdown(self):
        """
        优雅地关闭 CoreProcessor，例如关闭线程池。
        """
        logger.info("CoreProcessor 正在关闭...")
        self.thread_pool.shutdown(wait=True)
        if hasattr(self.ew_service, 'close') and callable(getattr(self.ew_service, 'close')):
            await self.ew_service.close()
        if hasattr(self.db_interface, 'close_connection') and callable(getattr(self.db_interface, 'close_connection')):
            # db_interface.close_connection() is sync, but atexit handles it.
            # If we need explicit async shutdown for db, db_interface would need async close.
            pass 
        logger.info("CoreProcessor 已关闭。")

# 示例: 如何在 FastAPI 应用中使用 (通常在 main_ew.py 或 app_ew.py)
# global_core_processor: CoreProcessor = None

# async def startup_event():
#     global global_core_processor
#     ew_service_instance = EnterpriseWeChatService()
#     global_core_processor = CoreProcessor(ew_service=ew_service_instance)
#     logger.info("Application startup: CoreProcessor created.")

# async def shutdown_event():
#     if global_core_processor:
#         await global_core_processor.shutdown()
#         logger.info("Application shutdown: CoreProcessor shut down.")

# # 在 FastAPI app 中:
# # app = FastAPI(on_startup=[startup_event], on_shutdown=[shutdown_event])
# # 
# # @app.post("/api/v1/wecom/callback")
# # async def receive_wecom_message(...):
# #     # ... (解密和解析消息体为 msg_dict)
# #     if global_core_processor:
# #         asyncio.create_task(global_core_processor.handle_ew_message(msg_dict)) # 非阻塞处理
# #     return "" # 立即回复企微 