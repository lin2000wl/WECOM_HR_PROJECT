import re
import os
from typing import Dict, Any, List
import asyncio  # 异步支持
from wcferry import Wcf, WxMsg  # 导入类型，解决类型注解未定义

# 已移除对 wcferry 的依赖，由企业微信服务替代
# from wcferry import Wcf, WxMsg

from src.logger import logger
from src.config import get_message_template
# 导入 state_manager 单例 和状态常量
from src.utils.state_manager import state_manager, STATE_WAITING_SELECTION, STATE_IDLE
# 导入 db_interface 和 query_handler (用于 'A' 选项)
from src.db_interface import db_interface
# from src.handlers.query_handler import process_query # Check if this needs refactoring or direct call - Removed direct import, handle 'A' locally for now
# 导入需要调用的函数
from .query_handler import _fetch_and_send_candidates
# 导入 llm_client (用于对比)
from src.llm_client import llm_client
from src.enterprise_wechat_service import EnterpriseWeChatService  # 引入企业微信服务
ew_service = EnterpriseWeChatService()  # 初始化企业微信服务实例

# --- Helper Functions ---

def _validate_indices(indices: List[int], max_index: int) -> bool:
    """校验用户输入的序号列表是否都在有效范围内。"""
    if not indices: # 列表不能为空
        return False
    for index in indices:
        if not (1 <= index <= max_index):
            return False
    return True

def _get_candidates_by_indices(indices: List[int], cached_results: List[Dict]) -> List[Dict]:
    """根据序号列表从缓存中获取对应的候选人信息列表。"""
    selected = []
    indices_set = set(indices) # 提高查找效率
    for result in cached_results:
        if result.get("index") in indices_set:
            selected.append(result)
    # 按输入序号排序 (可选, 但可能更好)
    selected.sort(key=lambda x: indices.index(x.get("index")))
    return selected

def _format_greeting_message(template: str, candidate_name: str | None, position: str | None) -> str:
    """格式化发送给候选人的初步沟通消息。"""
    if not template: return "你好！" # Fallback
    if candidate_name:
        template = template.replace("[候选人姓名]", candidate_name)
    if position:
        template = template.replace("[职位名称]", position)
    else:
        template = template.replace("[职位名称]", "相关") # Default

    # TODO: Replace placeholders with actual data from config or user context
    template = template.replace("[你的名字/公司名]", "我们的招聘团队")
    template = template.replace("[平台/渠道]", "内部推荐")
    template = template.replace("[简要职责]", "该职位的职责")
    template = template.replace("[招聘人员姓名]", "HR")
    template = template.replace("([招聘人员联系方式])", "") # Remove if empty
    
    return template

# --- Action Placeholder Functions ---

def _get_resume(wcf: Wcf, msg: WxMsg, candidates: List[Dict], state_manager):
    """处理获取简历的请求。(任务 1.5 实现)"""
    sender_wxid = msg.sender
    # 文件只能发送给私聊用户
    if msg.from_group():
        logger.warning(f"用户 [{sender_wxid}] 在群聊中请求简历，不支持。")
        room_id = msg.roomid
        # 使用企业微信服务发送错误提示
        asyncio.create_task(
            ew_service.send_text_message(
                content="抱歉，无法在群聊中直接发送简历文件。",
                user_ids=[room_id],
                tag_ids=[sender_wxid]
            )
        )
        return
    # 私聊可以直接发送
    user_wxid = sender_wxid
    logger.info(f"用户 [{user_wxid}] 请求获取候选人简历: {[c.get('name') for c in candidates]}")

    files_sent_count = 0
    files_not_found_count = 0
    files_path_missing_count = 0
    files_send_failed_count = 0

    for candidate in candidates:
        resume_path = candidate.get("resume_path")
        name = candidate.get("name", "未知姓名")

        if resume_path and isinstance(resume_path, str):
            # Ensure the path uses the correct separator for the OS
            normalized_path = os.path.normpath(resume_path)
            abs_resume_path = os.path.abspath(normalized_path)
            if os.path.exists(abs_resume_path):
                logger.info(f"尝试发送简历 {abs_resume_path} 给用户 {user_wxid}")
                try:
                    # 异步上传并发送文件
                    async def send_resume():
                        media_id = await ew_service.upload_temporary_media(file_path=abs_resume_path)
                        if media_id:
                            await ew_service.send_file_message(media_id=media_id, user_ids=[user_wxid])
                        else:
                            await ew_service.send_text_message(
                                content=f"抱歉，发送候选人 {name} 的简历时失败了。",
                                user_ids=[user_wxid]
                            )
                    asyncio.create_task(send_resume())
                    # 记录发送成功
                    logger.info(f"已异步开始发送简历 {abs_resume_path} 给用户 {user_wxid}。")
                    files_sent_count += 1
                except Exception as e:
                    logger.error(f"发送简历 {abs_resume_path} 给用户 {user_wxid} 时发生异常: {e}", exc_info=True)
                    files_send_failed_count += 1
                    # 使用接口发送文本
                    asyncio.create_task(
                        ew_service.send_text_message(
                            content=f"抱歉，发送候选人 {name} 的简历时发生程序错误。",
                            user_ids=[user_wxid]
                        )
                    )
            else:
                logger.warning(f"候选人 {name} 的简历文件不存在: {abs_resume_path} (原始路径: {resume_path})。")
                files_not_found_count += 1
                # 使用接口发送文本
                asyncio.create_task(
                    ew_service.send_text_message(
                        content=f"抱歉，找不到候选人 {name} 的简历文件 ({os.path.basename(abs_resume_path)})。",
                        user_ids=[user_wxid]
                    )
                )
        else:
            logger.warning(f"候选人 {name} 没有记录简历文件路径。")
            files_path_missing_count += 1
            # 使用接口发送文本
            asyncio.create_task(
                ew_service.send_text_message(
                    content=f"抱歉，候选人 {name} 没有记录简历文件。",
                    user_ids=[user_wxid]
                )
            )

    # Send a summary message after attempting all files
    summary_parts = []
    if files_sent_count > 0:
        summary_parts.append(f"成功发送 {files_sent_count} 份简历。")
    if files_send_failed_count > 0:
        summary_parts.append(f"{files_send_failed_count} 份发送失败。")
    if files_not_found_count > 0:
        summary_parts.append(f"{files_not_found_count} 份文件未找到。")
    if files_path_missing_count > 0:
        summary_parts.append(f"{files_path_missing_count} 位候选人无简历记录。")

    if summary_parts:
        asyncio.create_task(
            ew_service.send_text_message(
                content=" ".join(summary_parts),
                user_ids=[user_wxid]
            )
        )
    elif not candidates:
        # Should not happen if called correctly, but handle edge case
        logger.warning(f"_get_resume called for user {user_wxid} with empty candidate list.")
    else:
        # All candidates processed but none resulted in a countable outcome?
        logger.warning(f"_get_resume processed {len(candidates)} candidates for user {user_wxid} but no summary generated.")
        asyncio.create_task(
            ew_service.send_text_message(
                content="简历请求处理完毕。",
                user_ids=[user_wxid]
            )
        )

    # --- Refresh TTL Safely --- 
    context_key = msg.sender # Assuming private chat for resume
    existing_data = state_manager._get_user_data(context_key) # Use internal getter
    if existing_data:
        # Call update_state_and_cache_results passing all existing data to prevent reset
        state_manager.update_state_and_cache_results(
            user_id=context_key,
            state=STATE_WAITING_SELECTION, # Ensure state remains waiting
            results=existing_data.get("last_results"),
            query_criteria=existing_data.get("query_criteria"),
            parsed_query_data=existing_data.get("parsed_query_data"),
            current_offset=existing_data.get("query_offset"),
            has_more=existing_data.get("has_more")
        )
        logger.debug(f"TTL refreshed for {context_key} after _get_resume without data loss.")
    else:
        # This case means state likely expired *during* the operation, which is rare.
        logger.warning(f"Tried to refresh TTL for {context_key} after _get_resume, but user data not found (likely expired). State won't be refreshed.")

def _get_details(wcf: Wcf, msg: WxMsg, candidates: List[Dict], state_manager):
    """处理获取详细信息的请求。(任务 1.4 实现)"""
    sender_wxid = msg.sender
    room_id = msg.roomid if msg.from_group() else None
    receiver_id = room_id if room_id else sender_wxid
    at_user_id = sender_wxid if room_id else None

    logger.info(f"用户 [{sender_wxid}] (来自: {receiver_id}) 请求获取候选人详细信息: {[c.get('name') for c in candidates]}")

    full_details_message = []
    for candidate in candidates:
        details_message = []
        name = candidate.get("name", "未知姓名")
        info = candidate.get("extracted_info")
        details_message.append(f"--- {name} 的详细信息 ---")

        if isinstance(info, dict):
            location = info.get('current_location', None)
            if location: details_message.append(f"📍 当前地点: {location}")

            summary = info.get('summary', None)
            if summary: details_message.append(f"📝 摘要: {summary}")

            skills = info.get('skills', [])
            if skills: details_message.append(f"💡 技能: {', '.join(skills)}")

            certs = info.get('certifications', [])
            if certs:
                # v1.2.2 Handle list of certificate objects
                cert_strings = []
                for cert_obj in certs:
                    if isinstance(cert_obj, dict):
                        name = cert_obj.get('name')
                        level = cert_obj.get('level_keyword')
                        if name:
                             cert_str = f"{level}{name}" if level else name
                             cert_strings.append(cert_str)
                    elif isinstance(cert_obj, str): # Fallback for old format
                         cert_strings.append(cert_obj)
                if cert_strings:
                     details_message.append(f"🏅 证书: {', '.join(cert_strings)}")

            experience = info.get('experience', [])
            if experience:
                details_message.append("\n🏢 工作经历:")
                for exp in experience:
                    if isinstance(exp, dict):
                        exp_line = []
                        if exp.get('title'): exp_line.append(exp['title'])
                        if exp.get('company'): exp_line.append(f"@ {exp['company']}")
                        date_parts = []
                        if exp.get('start_date'): date_parts.append(exp['start_date'])
                        if exp.get('end_date'): date_parts.append(exp['end_date'])
                        if date_parts: exp_line.append(f"({ ' - '.join(date_parts) })")
                        details_message.append(f"  - {' '.join(exp_line)}")
                        # Optionally add description if needed
                        # if exp.get('description'): details_message.append(f"    {exp['description'][:100]}...")
                    else:
                         logger.warning(f"经验条目格式不正确: {exp}")

            education = info.get('education', [])
            if education:
                details_message.append("\n🎓 教育背景:")
                for edu in education:
                     if isinstance(edu, dict):
                        edu_line = []
                        if edu.get('school'): edu_line.append(edu['school'])
                        major_degree = []
                        if edu.get('major'): major_degree.append(edu['major'])
                        if edu.get('degree'): major_degree.append(edu['degree'])
                        if major_degree: edu_line.append(f"({', '.join(major_degree)})")
                        date_parts = []
                        if edu.get('start_date'): date_parts.append(edu['start_date'])
                        if edu.get('end_date'): date_parts.append(edu['end_date'])
                        if date_parts: edu_line.append(f"({ ' - '.join(date_parts) })")
                        details_message.append(f"  - {' '.join(edu_line)}")
                     else:
                         logger.warning(f"教育条目格式不正确: {edu}")

            if not location and not summary and not skills and not certs and not experience and not education:
                 details_message.append("(未提取到详细信息)")

        else:
            details_message.append("无法获取详细信息或信息格式错误。")

        full_details_message.append("\n".join(details_message))

    if full_details_message:
        # 使用企业微信服务异步发送详细信息
        asyncio.create_task(
            ew_service.send_text_message(
                content="\n\n".join(full_details_message),
                user_ids=[receiver_id],
                tag_ids=[at_user_id] if at_user_id else None
            )
        )
    else:
        # 应急：未生成详细信息
        logger.warning(f"尝试为用户 [{sender_wxid}] 获取详细信息，但未能生成任何内容。")
        asyncio.create_task(
            ew_service.send_text_message(
                content="无法生成所选候选人的详细信息。",
                user_ids=[receiver_id],
                tag_ids=[at_user_id] if at_user_id else None
            )
        )

    # --- Refresh TTL Safely --- 
    context_key = f"{sender_wxid}_{room_id}" if room_id else sender_wxid
    existing_data = state_manager._get_user_data(context_key) # Use internal getter
    if existing_data:
        # Call update_state_and_cache_results passing all existing data to prevent reset
        state_manager.update_state_and_cache_results(
            user_id=context_key,
            state=STATE_WAITING_SELECTION, # Ensure state remains waiting
            results=existing_data.get("last_results"),
            query_criteria=existing_data.get("query_criteria"),
            parsed_query_data=existing_data.get("parsed_query_data"),
            current_offset=existing_data.get("query_offset"),
            has_more=existing_data.get("has_more")
        )
        logger.debug(f"TTL refreshed for {context_key} after _get_details without data loss.")
    else:
        logger.warning(f"Tried to refresh TTL for {context_key} after _get_details, but user data not found (likely expired). State won't be refreshed.")

def _contact_candidate(wcf: Wcf, msg: WxMsg, candidates: List[Dict], state_manager):
    """处理联系候选人的请求。(任务 1.6 实现)"""
    sender_wxid = msg.sender
    room_id = msg.roomid if msg.from_group() else None
    receiver_id = room_id if room_id else sender_wxid
    at_user_id = sender_wxid if room_id else None
    context_key = f"{sender_wxid}_{room_id}" if room_id else sender_wxid # 状态键

    if len(candidates) != 1:
        logger.error(f"联系候选人逻辑错误：收到 {len(candidates)} 个候选人，应为 1 个。")
        # 异步发送内部错误提示
        asyncio.create_task(
            ew_service.send_text_message(
                content="内部错误：联系候选人时出现问题。",
                user_ids=[receiver_id],
                tag_ids=[at_user_id] if at_user_id else None
            )
        )
        return

    candidate = candidates[0]
    candidate_wxid = candidate.get("wxid")
    candidate_name = candidate.get("name", "该候选人")
    logger.info(f"上下文 [{context_key}] 请求联系候选人: {candidate_name} ({candidate_wxid})")

    if candidate_wxid:
        # Format greeting message
        greeting_template = get_message_template("greeting")
        # Try to get position from the query context if available
        parsed_data = state_manager.get_parsed_query_data(context_key)
        position = parsed_data.get('position') if parsed_data else "相关职位"

        greeting_message = _format_greeting_message(greeting_template, candidate_name, position)

        logger.info(f"尝试向候选人 [{candidate_wxid}] 发送初步沟通消息: {greeting_message}")
        try:
            # 异步创建向外部联系人发送消息任务
            asyncio.create_task(
                ew_service.send_message_to_external_contact(
                    sender_userid=sender_wxid,
                    external_user_id=candidate_wxid,
                    message_text=greeting_message
                )
            )
            logger.info(f"已创建联系候选人消息任务，external_userid={candidate_wxid}")
            asyncio.create_task(
                ew_service.send_text_message(
                    content=f"已尝试向候选人 {candidate_name} 发送初步沟通消息。",
                    user_ids=[receiver_id],
                    tag_ids=[at_user_id] if at_user_id else None
                )
            )
            state_manager.clear_state(context_key)
            logger.info(f"用户 [{context_key}] 完成联系操作，状态已清除。")
        except Exception as e:
            logger.error(f"向候选人 [{candidate_wxid}] 发送消息时发生异常: {e}", exc_info=True)
            asyncio.create_task(
                ew_service.send_text_message(
                    content=f"抱歉，尝试联系候选人 {candidate_name} 时发生程序错误。",
                    user_ids=[receiver_id],
                    tag_ids=[at_user_id] if at_user_id else None
                )
            )
            state_manager.update_state_and_cache_results(user_id=context_key, state=STATE_WAITING_SELECTION)
            return
    else:
        logger.warning(f"无法联系候选人 {candidate_name}，因为缺少 wxid。")
        asyncio.create_task(
            ew_service.send_text_message(
                content=f"抱歉，无法联系候选人 {candidate_name}，缺少联系方式 (wxid)。",
                user_ids=[receiver_id],
                tag_ids=[at_user_id] if at_user_id else None
            )
        )
        state_manager.update_state_and_cache_results(user_id=context_key, state=STATE_WAITING_SELECTION)
        return

def _handle_more_results(wcf: Wcf, msg: WxMsg, state_manager):
    """处理用户请求查看更多结果 ('A') 的逻辑。(任务 1.7 更新)"""
    sender_wxid = msg.sender
    room_id = msg.roomid if msg.from_group() else None
    receiver_id = room_id if room_id else sender_wxid
    at_user_id = sender_wxid if room_id else None
    context_key = f"{sender_wxid}_{room_id}" if room_id else sender_wxid

    logger.info(f"用户 [{context_key}] 请求查看更多结果 ('A')。")

    # Get necessary info from state
    query_criteria = state_manager.get_query_criteria(context_key)
    next_offset = state_manager.get_query_offset(context_key)
    parsed_query_data = state_manager.get_parsed_query_data(context_key)
    has_more = state_manager.get_has_more(context_key)

    if not query_criteria or not parsed_query_data:
        logger.warning(f"无法为用户 [{context_key}] 处理 'A' 请求：缺少查询条件或解析数据缓存。")
        # 使用企业微信服务发送提示
        asyncio.create_task(
            ew_service.send_text_message(
                content="抱歉，无法获取您之前的查询信息来查找更多结果。请重新发起查询。",
                user_ids=[receiver_id],
                tag_ids=[at_user_id] if at_user_id else None
            )
        )
        state_manager.clear_state(context_key)
        return

    if not has_more:
         logger.info(f"用户 [{context_key}] 请求 'A'，但缓存标记已无更多结果。")
         # 使用企业微信服务发送无更多提示
         asyncio.create_task(
             ew_service.send_text_message(
                 content="根据您之前的查询，没有更多符合条件的候选人了。",
                 user_ids=[receiver_id],
                 tag_ids=[at_user_id] if at_user_id else None
             )
         )
         state_manager.clear_state(context_key) # Clear state as there are no more pages
         return

    logger.info(f"尝试为用户 [{context_key}] 获取下一页结果 (offset={next_offset})。")
    # limit = 5 # Display limit per page
    try:
        # Call the updated function from query_handler
        candidates_found_next_page = _fetch_and_send_candidates(
            wcf=wcf,
            msg=msg,
            query_criteria=query_criteria,
            offset=next_offset,
            # limit=limit, # Limit is handled inside _fetch_and_send_candidates
            state_manager=state_manager,
            parsed_query_data=parsed_query_data
        )

        if not candidates_found_next_page:
            # _fetch_and_send_candidates handles sending "no more found" now if offset > 0
            logger.info(f"为用户 [{context_key}] 调用 _fetch_and_send_candidates 后未找到更多结果 (offset={next_offset})。状态已清除。")
            # Ensure state is cleared if needed (it should be by the called function)
            if state_manager.get_state(context_key) != STATE_IDLE:
                 state_manager.clear_state(context_key)
        else:
             logger.info(f"成功为用户 [{context_key}] 发送了下一页结果。")

    except Exception as e:
        logger.error(f"处理用户 [{context_key}] 的 'A' 请求时发生错误: {e}", exc_info=True)
        # 异步发送错误提示
        asyncio.create_task(
            ew_service.send_text_message(
                content="抱歉，在查找更多结果时遇到错误，请稍后再试。",
                user_ids=[receiver_id],
                tag_ids=[at_user_id] if at_user_id else None
            )
        )
        # Keep state? Or clear?
        state_manager.update_state_and_cache_results(user_id=context_key, state=STATE_WAITING_SELECTION) # Refresh TTL for retry?

def _handle_reject_all(wcf: Wcf, msg: WxMsg, state_manager):
    """处理用户选择都不满意 ('B') 的逻辑。(任务 1.7 更新)"""
    sender_wxid = msg.sender
    room_id = msg.roomid if msg.from_group() else None
    receiver_id = room_id if room_id else sender_wxid
    at_user_id = sender_wxid if room_id else None
    context_key = f"{sender_wxid}_{room_id}" if room_id else sender_wxid

    logger.info(f"用户 [{context_key}] 选择都不满意 ('B')。")
    # 使用企业微信服务异步发送结束提示
    asyncio.create_task(
        ew_service.send_text_message(
            content="好的，已了解。如果您需要新的查询，请重新发送指令。",
            user_ids=[receiver_id],
            tag_ids=[at_user_id] if at_user_id else None
        )
    )
    state_manager.clear_state(context_key)
    logger.info(f"用户 [{context_key}] 完成 'B' 操作，状态已清除。")

# --- Main Handler Function ---

def handle_user_response(wcf: Wcf, msg: Any, state_manager):
    """
    处理处于 STATE_WAITING_SELECTION 状态的用户的回复。
    (任务 1.3 更新)
    """
    if not isinstance(msg, WxMsg):
         logger.warning("handle_user_response 收到非 WxMsg 对象")
         return

    sender_wxid = msg.sender
    room_id = msg.roomid if msg.from_group() else None
    context_key = f"{sender_wxid}_{room_id}" if room_id else sender_wxid
    receiver_id = room_id if room_id else sender_wxid # Target for replies
    at_user_id = sender_wxid if room_id else None # Who to @ in group replies

    content = msg.content.strip()
    logger.info(f"处理用户 [{context_key}] 的等待回复: {content}")

    cached_results = state_manager.get_last_results(context_key)
    if cached_results is None:
        # This can happen if state expired between core_processor check and handler execution
        logger.warning(f"用户 [{context_key}] 处于等待状态，但找不到缓存结果，可能已超时。")
        asyncio.create_task(
            ew_service.send_text_message(
                content="抱歉，您的操作已超时或状态已丢失，请重新发起查询。",
                user_ids=[receiver_id],
                tag_ids=[at_user_id] if at_user_id else None
            )
        )
        state_manager.clear_state(context_key)
        return

    max_index = len(cached_results)
    if max_index == 0:
        logger.error(f"逻辑错误：用户 [{context_key}] 处于等待状态，但缓存结果列表为空。")
        asyncio.create_task(
            ew_service.send_text_message(
                content="抱歉，处理您的请求时遇到内部状态错误。",
                user_ids=[receiver_id],
                tag_ids=[at_user_id] if at_user_id else None
            )
        )
        state_manager.clear_state(context_key)
        return

    # --- Parse user command --- 
    command = None
    indices = []

    # Try matching specific commands first (A, B)
    if content.upper() == 'A':
        command = 'A'
    elif content.upper() == 'B':
        command = 'B'
    else:
        # Try matching "简历 X,Y", "信息 X", "联系 X"
        match_resume = re.match(r"^简历\s*([\d\s]+)$", content, re.IGNORECASE)
        match_info = re.match(r"^信息\s*([\d\s]+)$", content, re.IGNORECASE)
        match_contact = re.match(r"^联系\s*(\d+)$", content, re.IGNORECASE)

        if match_resume:
            command = "简历"
            try:
                indices_str = match_resume.group(1).split()
                indices = [int(i.strip()) for i in indices_str if i.strip().isdigit()]
            except ValueError:
                 logger.warning(f"用户 [{context_key}] 输入简历指令，但序号格式错误: {content}")
                 command = "无效"
        elif match_info:
            command = "信息"
            try:
                indices_str = match_info.group(1).split()
                indices = [int(i.strip()) for i in indices_str if i.strip().isdigit()]
            except ValueError:
                 logger.warning(f"用户 [{context_key}] 输入信息指令，但序号格式错误: {content}")
                 command = "无效"
        elif match_contact:
            command = "联系"
            try:
                indices = [int(match_contact.group(1).strip())]
            except ValueError:
                 # Should not happen with regex, but safeguard
                 logger.warning(f"用户 [{context_key}] 输入联系指令，但序号格式错误: {content}")
                 command = "无效"
        else:
            # Try matching just numbers (assume it means '信息')
            try:
                indices_str = content.split()
                indices = [int(i.strip()) for i in indices_str if i.strip().isdigit()]
                if indices and len(indices_str) == len(indices): # Ensure all parts were numbers
                    command = "信息" # Default action for just numbers
                    logger.debug(f"用户 [{context_key}] 输入数字 {indices}，默认为请求信息。")
                else:
                    command = "无效"
            except ValueError:
                command = "无效"

    # --- Execute command --- 
    if command == 'A':
        _handle_more_results(wcf, msg, state_manager)
    elif command == 'B':
        _handle_reject_all(wcf, msg, state_manager)
    elif command in ["简历", "信息", "联系"]:
        if not _validate_indices(indices, max_index):
            logger.warning(f"用户 [{context_key}] 输入指令 '{command}'，但序号无效或超出范围 (1-{max_index}): {indices}")
            asyncio.create_task(
                ew_service.send_text_message(
                    content=f"请输入有效的候选人序号 (1 到 {max_index})。例如：信息 1 或 简历 1,3",
                    user_ids=[receiver_id],
                    tag_ids=[at_user_id] if at_user_id else None
                )
            )
            state_manager.update_state_and_cache_results(user_id=context_key, state=STATE_WAITING_SELECTION) # Refresh TTL
        else:
            selected_candidates = _get_candidates_by_indices(indices, cached_results)
            if not selected_candidates:
                 logger.error(f"逻辑错误：用户 [{context_key}] 输入有效序号 {indices}，但未能从缓存 {cached_results} 中获取候选人。")
                 asyncio.create_task(
                     ew_service.send_text_message(
                         content="抱歉，获取所选候选人信息时出错。",
                         user_ids=[receiver_id],
                         tag_ids=[at_user_id] if at_user_id else None
                     )
                 )
                 state_manager.update_state_and_cache_results(user_id=context_key, state=STATE_WAITING_SELECTION) # Refresh TTL
            else:
                if command == "简历":
                    if msg.from_group():
                         asyncio.create_task(
                             ew_service.send_text_message(
                                 content="抱歉，无法在群聊中直接发送简历文件。",
                                 user_ids=[receiver_id],
                                 tag_ids=[at_user_id] if at_user_id else None
                             )
                         )
                         state_manager.update_state_and_cache_results(user_id=context_key, state=STATE_WAITING_SELECTION) # Refresh TTL
                    else:
                         _get_resume(wcf, msg, selected_candidates, state_manager)
                         # _get_resume now handles TTL refresh internally
                elif command == "信息":
                    _get_details(wcf, msg, selected_candidates, state_manager)
                    # _get_details now handles TTL refresh internally
                elif command == "联系":
                    if len(indices) > 1:
                         logger.warning(f"用户 [{context_key}] 尝试一次联系多个候选人: {indices}")
                         asyncio.create_task(
                             ew_service.send_text_message(
                                 content="抱歉，一次只能联系一位候选人。请使用 '联系 X' 指令，只指定一个序号。",
                                 user_ids=[receiver_id],
                                 tag_ids=[at_user_id] if at_user_id else None
                             )
                         )
                         state_manager.update_state_and_cache_results(user_id=context_key, state=STATE_WAITING_SELECTION) # Refresh TTL
                    else:
                         _contact_candidate(wcf, msg, selected_candidates, state_manager)
                         # _contact_candidate handles state clearing or TTL refresh internally
    else: # command == "无效"
        logger.info(f"用户 [{context_key}] 输入无效指令: {content}")
        # 异步发送帮助提示
        asyncio.create_task(
            ew_service.send_text_message(
                content="无法识别您的指令。请使用以下格式回复：\n - 简历 X\n - 信息 X\n - 联系 X\n - A (更多)\n - B (结束)",
                user_ids=[receiver_id],
                tag_ids=[at_user_id] if at_user_id else None
            )
        )

        # --- v1.2.3 Fix: Refresh TTL safely without clearing data ---
        existing_data = state_manager._get_user_data(context_key) # Use internal getter
        if existing_data:
            # Call update_state_and_cache_results passing all existing data to prevent reset
            state_manager.update_state_and_cache_results(
                user_id=context_key,
                state=STATE_WAITING_SELECTION, # Ensure state remains waiting
                results=existing_data.get("last_results"),
                query_criteria=existing_data.get("query_criteria"),
                parsed_query_data=existing_data.get("parsed_query_data"),
                current_offset=existing_data.get("query_offset"),
                has_more=existing_data.get("has_more")
            )
            logger.debug(f"TTL refreshed for {context_key} after invalid command without data loss.")
        else:
            logger.warning(f"Tried to refresh TTL for {context_key} after invalid command, but user data not found (likely expired anyway). State won't be refreshed.")
        # --- End Fix ---

# if __name__ == '__main__':
#     # Add minimal testing code here if needed
#     pass 