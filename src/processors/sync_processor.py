import logging
import asyncio
import re # <--- 新增导入
from typing import List, Dict, Any, Optional

from src.enterprise_wechat_service import EnterpriseWeChatService
from src.db_interface import DBInterface
from src import config_ew
# from src.llm_client import LLMClient # SyncProcessor 可能不需要 LLMClient，暂时注释

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG) # <--- 强制设置模块级日志级别为DEBUG

class SyncProcessor:
    def __init__(self, ew_service: EnterpriseWeChatService, db_interface: DBInterface, llm_client=None): # llm_client 设为可选
        self.ew_service = ew_service
        self.db_interface = db_interface
        # 手机号提取的正则表达式，匹配11位数字，常见的号段开头
        self.phone_regex = re.compile(r"1[3-9]\d{9}")
        # self.llm_client = llm_client # 如果需要
        logger.info("SyncProcessor 初始化完成。")

    def _extract_phone_from_remark(self, remark: Optional[str]) -> Optional[str]:
        """从备注中提取第一个匹配的手机号码。"""
        if not remark:
            return None
        match = self.phone_regex.search(remark)
        return match.group(0) if match else None

    async def run_sync_for_hr(self, hr_userid: str, triggered_by_manual_command: bool = False):
        logger.info(f"开始为 HR 用户 {hr_userid} 执行外部联系人同步。手动触发: {triggered_by_manual_command}")
        
        all_external_contacts: List[Dict[str, Any]] = []
        current_cursor: Optional[str] = None
        page_count = 0
        MAX_PAGES_TO_FETCH = 100 # 安全上限，防止无限循环

        try:
            while page_count < MAX_PAGES_TO_FETCH:
                page_count += 1
                logger.info(f"HR {hr_userid}: 获取第 {page_count} 页外部联系人数据，cursor: {current_cursor}")
                print(f"SYNC_PROCESSOR_DEBUG: Just after logger.info for page {page_count}") # <--- 新增 print
                
                # 详细记录API调用前的参数
                api_call_params = {
                    "userid_list": [hr_userid],
                    "cursor": current_cursor,
                    "limit": 100
                }
                print(f"SYNC_PROCESSOR_DEBUG: api_call_params prepared: {api_call_params}") # <--- 新增 print
                logger.debug(f"HR {hr_userid}: 调用 batch_get_external_contacts API，参数: {api_call_params}")

                response_data = await self.ew_service.batch_get_external_contacts(
                    userid_list=[hr_userid], # batch_get_external_contacts 期望 userid_list
                    cursor=current_cursor,
                    limit=100 # API 最大限制
                )

                # 详细记录API的原始响应
                logger.debug(f"HR {hr_userid}: batch_get_external_contacts API 原始响应: {response_data}")

                if response_data and response_data.get("errcode") == 0:
                    contacts_on_page = response_data.get("external_contact_list", [])
                    # 记录当页获取的联系人数量和 next_cursor
                    next_cursor_from_api = response_data.get("next_cursor")
                    logger.info(f"HR {hr_userid}: 第 {page_count} 页API调用成功。获取联系人: {len(contacts_on_page)}。Next_cursor: '{next_cursor_from_api}'")
                    
                    if contacts_on_page:
                        all_external_contacts.extend(contacts_on_page)
                        logger.info(f"HR {hr_userid}: 第 {page_count} 页获取到 {len(contacts_on_page)} 个外部联系人。累计: {len(all_external_contacts)}")
                    
                    current_cursor = next_cursor_from_api # 更新 current_cursor
                    if not current_cursor:
                        logger.info(f"HR {hr_userid}: 已获取所有外部联系人数据 (API返回的 next_cursor 为空/None)。总计: {len(all_external_contacts)}")
                        break 
                else:
                    logger.error(f"HR {hr_userid}: 获取外部联系人数据失败或API返回错误。响应: {response_data}")
                    # 此处可以决定是否发送错误通知给用户
                    if triggered_by_manual_command:
                        await self.ew_service.send_text_message(
                            content=f"为用户 {hr_userid} 获取外部联系人列表时出错，请检查日志或联系管理员。",
                            user_ids=[hr_userid] # 假设 hr_userid 就是发起命令的用户
                        )
                    return # 提前退出同步过程
                
                await asyncio.sleep(0.2) # API 调用之间短暂延时，防止频率超限 (根据实际情况调整)

            if page_count >= MAX_PAGES_TO_FETCH:
                logger.warning(f"HR {hr_userid}: 获取外部联系人数据达到最大页数限制 ({MAX_PAGES_TO_FETCH})，可能仍有数据未获取。")

            logger.info(f"HR {hr_userid}: 共获取到 {len(all_external_contacts)} 个外部联系人进行处理。")

            # 任务 3.3: 筛选联系人
            filtered_contacts_for_processing: List[Dict[str, Any]] = []
            for contact_data in all_external_contacts:
                external_contact_info = contact_data.get("external_contact", {})
                follow_info = contact_data.get("follow_info", {})

                external_userid = external_contact_info.get("external_userid")
                if not external_userid:
                    logger.debug(f"HR {hr_userid}: 跳过一个没有 external_userid 的联系人记录: {contact_data}")
                    continue

                # 1. 检查是否已打成功同步标签
                existing_tags = follow_info.get("tag_id", [])
                if config_ew.TAG_ID_SYNC_SUCCESS and isinstance(existing_tags, list) and config_ew.TAG_ID_SYNC_SUCCESS in existing_tags:
                    logger.debug(f"HR {hr_userid}: 外部联系人 {external_userid} 已有同步成功标签，跳过处理。")
                    continue

                # 2. 提取手机号：优先顺序 external_contact.mobile -> follow_info.remark_mobiles[0] -> 从 follow_info.remark 提取
                contact_phone: Optional[str] = None
                extracted_phone_source = "未提取到"

                # 尝试从 external_contact.mobile
                mobile_from_profile = external_contact_info.get("mobile")
                if mobile_from_profile and self.phone_regex.fullmatch(mobile_from_profile):
                    contact_phone = mobile_from_profile
                    extracted_phone_source = "external_contact.mobile"
                
                # 如果上面没有，尝试从 follow_info.remark_mobiles
                if not contact_phone:
                    remark_mobiles_list = follow_info.get("remark_mobiles")
                    if remark_mobiles_list and isinstance(remark_mobiles_list, list) and len(remark_mobiles_list) > 0:
                        first_remark_mobile = remark_mobiles_list[0]
                        if first_remark_mobile and self.phone_regex.fullmatch(first_remark_mobile):
                            contact_phone = first_remark_mobile
                            extracted_phone_source = "follow_info.remark_mobiles[0]"

                # 如果上面都没有，尝试从 follow_info.remark 提取
                remark_text: Optional[str] = follow_info.get("remark") # remark_text 定义移到这里，避免重复获取
                if not contact_phone:
                    phone_from_remark_text = self._extract_phone_from_remark(remark_text)
                    if phone_from_remark_text:
                        contact_phone = phone_from_remark_text
                        extracted_phone_source = "follow_info.remark (提取)"
                
                if contact_phone:
                    logger.debug(f"HR {hr_userid}: 外部联系人 {external_userid} 提取到手机号 {contact_phone} (来源: {extracted_phone_source})。备注: '{remark_text}'")
                    contact_data['_extracted_phone_for_sync'] = contact_phone
                    filtered_contacts_for_processing.append(contact_data)
                    continue
                
                logger.debug(f"HR {hr_userid}: 外部联系人 {external_userid} (备注: '{remark_text}') 未找到有效手机号 (检查了 profile.mobile, remark_mobiles, remark提取)，跳过同步。")

            logger.info(f"HR {hr_userid}: 经过初步筛选 (有效手机号且未打同步成功标签)，有 {len(filtered_contacts_for_processing)} 个联系人需要进一步处理。")

            # 任务 3.4: 匹配数据库候选人记录
            # 任务 3.5: 更新候选人记录 (如果需要)
            # 模块 4: 调用企业微信API打标签
            # 模块 5: 准备并发送最终通知
            
            # 为模块5准备统计数据
            successfully_synced_count = 0
            failed_to_sync_count = 0
            # 示例: failed_contacts_details = [{'remark': '张三备注', 'ext_id': 'ext_userid_123', 'reason': '未找到DB记录'}]
            failed_contacts_processing_details: List[Dict[str, str]] = []

            for contact_to_process in filtered_contacts_for_processing:
                external_userid = contact_to_process.get("external_contact", {}).get("external_userid")
                phone_to_match = contact_to_process.get('_extracted_phone_for_sync')
                contact_remark = contact_to_process.get("follow_info", {}).get("remark", "无备注")

                if not external_userid or not phone_to_match:
                    logger.warning(f"HR {hr_userid}: 联系人数据不完整，跳过。External ID: {external_userid}, Phone: {phone_to_match}")
                    failed_to_sync_count += 1
                    failed_contacts_processing_details.append({
                        'remark_or_name': contact_remark or external_userid,
                        'external_id': external_userid or "N/A",
                        'reason': '外部联系人ID或提取的手机号为空'
                    })
                    continue

                logger.debug(f"HR {hr_userid}: 尝试为外部联系人 {external_userid} (手机号: {phone_to_match}) 匹配DB候选人。")
                candidate_in_db = await asyncio.to_thread(self.db_interface.find_candidate_by_phone, phone_to_match)

                if candidate_in_db:
                    logger.info(f"HR {hr_userid}: 匹配成功！外部联系人 {external_userid} (手机: {phone_to_match}) -> DB候选人 {candidate_in_db.name} (ID: {candidate_in_db._id})。")
                    
                    # 任务 3.5: 更新候选人记录 (如果企业微信的 external_userid 尚未记录)
                    # 假设 Candidate模型有一个字段如 external_wecom_id 来存储 external_userid
                    if not getattr(candidate_in_db, 'external_wecom_id', None) or candidate_in_db.external_wecom_id != external_userid:
                        update_data = {"external_wecom_id": external_userid}
                        # 如果企业微信备注中有更通用或更新的信息，也可以考虑更新DB中的某些字段
                        # 例如：企业微信的 external_contact.name, external_contact.corp_name 等
                        # remark_name = contact_to_process.get("external_contact", {}).get("name")
                        # if remark_name and remark_name != candidate_in_db.name: # 简单的例子
                        #     update_data["name_from_wecom_external"] = remark_name
                        
                        # 使用正确的 ID 字段 candidate_in_db._id
                        updated_db_entry = await asyncio.to_thread(
                            self.db_interface.update_candidate_by_id, 
                            candidate_in_db._id,  # <--- 使用 _id
                            update_data
                        )
                        if updated_db_entry:
                            logger.info(f"HR {hr_userid}: 已更新DB中候选人 {candidate_in_db.name} (ID: {candidate_in_db._id}) 的 external_wecom_id 为 {external_userid}。")
                        else:
                            logger.error(f"HR {hr_userid}: 更新DB中候选人 {candidate_in_db.name} (ID: {candidate_in_db._id}) 的 external_wecom_id 失败。")
                            # 即使更新失败，也可能继续尝试打标签，取决于策略
                    
                    # 模块 4: 调用企业微信API打标签
                    if config_ew.TAG_ID_SYNC_SUCCESS:
                        logger.debug(f"HR {hr_userid}: 尝试为外部联系人 {external_userid} 打上同步成功标签 {config_ew.TAG_ID_SYNC_SUCCESS}。操作者: {hr_userid}")
                        tag_added = await self.ew_service.mark_external_contact_tags(
                            operator_userid=hr_userid, 
                            external_userid=external_userid, 
                            add_tag_ids=[config_ew.TAG_ID_SYNC_SUCCESS]
                        )
                        if tag_added:
                            logger.info(f"HR {hr_userid}: 成功为外部联系人 {external_userid} 打上同步成功标签。")
                            successfully_synced_count += 1
                        else:
                            logger.error(f"HR {hr_userid}: 为外部联系人 {external_userid} 打同步成功标签失败。")
                            failed_to_sync_count += 1
                            failed_contacts_processing_details.append({
                                "remark_or_name": contact_remark or external_userid,
                                "external_id": external_userid,
                                "reason": "打标签失败"
                            })
                    else:
                        logger.warning(f"HR {hr_userid}: 未配置 TAG_ID_SYNC_SUCCESS，跳过为 {external_userid} 打标签。")
                        # 如果不打标签，但匹配并更新了DB，是否算成功同步？取决于定义
                        # 假设这种情况不算完全的"同步成功并标记"
                        failed_to_sync_count += 1 # 或者定义一个新的计数器
                        failed_contacts_processing_details.append({
                            "remark_or_name": contact_remark or external_userid,
                            "external_id": external_userid,
                            "reason": "未配置成功标签ID"
                        })
                else:
                    logger.info(f"HR {hr_userid}: 未在数据库中找到手机号为 {phone_to_match} (来自外部联系人 {external_userid}) 的候选人记录。")
                    failed_to_sync_count += 1
                    failed_contacts_processing_details.append({
                        "remark_or_name": contact_remark or external_userid,
                        "external_id": external_userid,
                        "reason": "DB中未找到匹配手机号"
                    })

                await asyncio.sleep(0.1) # 每个联系人处理之间短暂延时

            logger.info(f"HR {hr_userid}: 外部联系人与DB匹配处理完成。成功同步数: {successfully_synced_count}, 失败数: {failed_to_sync_count}")

            # 模块 5: 准备并发送最终通知
            total_checked_for_processing = len(filtered_contacts_for_processing)
            completion_message = f"""HR 用户 {hr_userid} 的外部联系人同步任务已完成。
总共获取外部联系人数: {len(all_external_contacts)}。
筛选后待处理数 (有手机号且未标记): {total_checked_for_processing}。
成功同步并标记数: {successfully_synced_count}。
处理失败或未匹配数: {failed_to_sync_count}。"""
            if failed_to_sync_count > 0 and failed_contacts_processing_details:
                # 正确的 f-string 格式化，确保括号和引号正确配对和转义
                details_strings = []
                for item in failed_contacts_processing_details[:5]:
                    details_strings.append(f" - \"{item['remark_or_name']}\" (ID: {item['external_id']}): {item['reason']}")
                failed_list_str = "\n失败/未匹配详情 (最多显示5条):\n" + "\n".join(details_strings)
                completion_message += failed_list_str
                if len(failed_contacts_processing_details) > 5:
                    completion_message += f"\n  ...等另外 {len(failed_contacts_processing_details) - 5} 条记录。"
            elif total_checked_for_processing > 0 and successfully_synced_count == total_checked_for_processing:
                completion_message += "所有符合条件的联系人均已成功同步并标记。"
            elif total_checked_for_processing == 0:
                 completion_message += "没有需要处理的联系人（可能都已标记或无有效手机号）。"
            else:
                completion_message += "处理完成，详情请查看日志。"
            
            # 发送通知 (手动触发时发送给触发者，自动任务时可考虑发送给管理员列表)
            # 现在这个逻辑是：如果是手动触发，就发消息给触发者HR；如果是自动任务，就不主动发消息（除非配置了特定管理员通知）
            if triggered_by_manual_command:
                try:
                    await self.ew_service.send_text_message(
                        content=completion_message,
                        user_ids=[hr_userid]
                    )
                    logger.info(f"已向 HR 用户 {hr_userid} 发送同步完成通知。")
                except Exception as e_notify:
                    logger.error(f"向 HR 用户 {hr_userid} 发送同步完成通知失败: {e_notify}")
            else:
                # 将 completion_message 合并到 f-string 的同一行
                log_message = f"自动同步任务为 HR {hr_userid} 完成。通知内容:\n{completion_message}"
                logger.info(log_message)
                # 未来可以加入发送给管理员的逻辑，如果 config_ew 中有相关配置
                # admin_user_ids = config_ew.get_admin_user_ids_for_sync_report() 
                # if admin_user_ids:
                #     await self.ew_service.send_text_message(content=f"针对HR {hr_userid} 的自动同步完成:\n{completion_message}", user_ids=admin_user_ids)

        except Exception as e:
            logger.error(f"为HR用户 {hr_userid} 执行外部联系人同步时发生严重错误: {e}", exc_info=True)
            if triggered_by_manual_command:
                try:
                    await self.ew_service.send_text_message(
                        content=f"执行外部联系人同步时发生严重错误，请联系管理员。错误: {str(e)[:100]}...",
                        user_ids=[hr_userid]
                    )
                except Exception as e2:
                    logger.error(f"发送严重错误通知给用户 {hr_userid} 时再次出错: {e2}")
        
        logger.info(f"HR 用户 {hr_userid} 的外部联系人同步处理完毕。") 