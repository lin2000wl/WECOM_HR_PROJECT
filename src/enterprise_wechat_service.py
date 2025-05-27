import httpx
import time
import logging
import os
import threading
from typing import Optional, List, Dict, Any

from src import config_ew # Assuming config_ew.py is in src and loads .env

logger = logging.getLogger(__name__)

class EnterpriseWeChatService:
    """
    封装与企业微信API交互的服务。
    包括 access_token 管理、消息发送等。
    """
    _instance = None
    _lock = threading.Lock()
    BASE_URL = "https://qyapi.weixin.qq.com/cgi-bin"

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # 防止重复初始化
        if hasattr(self, '_initialized') and self._initialized:
            return
        
        self.corp_id = config_ew.WECOM_CORP_ID
        self.app_secret = config_ew.WECOM_APP_SECRET
        self.agent_id = int(config_ew.WECOM_AGENT_ID) if config_ew.WECOM_AGENT_ID else None # AgentID might not be needed for all calls like gettoken
        
        self._access_token: Optional[str] = None
        self._token_expiry_time: float = 0
        self.client = httpx.AsyncClient()

        self._initialized = True
        # logger.info(f"{config_ew.BOT_NAME} - EnterpriseWeChatService 初始化完成。AgentID: {self.agent_id}")
        print(f"{config_ew.BOT_NAME} - EnterpriseWeChatService 初始化完成。AgentID: {self.agent_id}") # 临时

    async def close(self):
        await self.client.aclose()

    async def get_access_token(self) -> Optional[str]:
        """
        获取可用的 access_token。
        会处理缓存、过期和线程安全的刷新。

        Returns:
            str | None: 可用的 access_token，如果获取失败则返回 None。
        """
        if self._access_token and time.time() < self._token_expiry_time:
            return self._access_token

        url = f"{self.BASE_URL}/gettoken"
        params = {"corpid": self.corp_id, "corpsecret": self.app_secret}
        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            if data.get("errcode") == 0 and "access_token" in data:
                self._access_token = data["access_token"]
                # expires_in is in seconds, typically 7200. Subtract a buffer (e.g., 300s) for safety.
                self._token_expiry_time = time.time() + data.get("expires_in", 7200) - 300
                logger.info("Successfully fetched new access_token.")
                return self._access_token
            else:
                logger.error(f"Failed to get access_token: errcode={data.get('errcode')}, errmsg={data.get('errmsg')}")
                return None
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error while fetching access_token: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.exception("Exception while fetching access_token")
            return None

    async def send_text_message(
        self,
        content: str,
        user_ids: Optional[List[str]] = None,
        party_ids: Optional[List[str]] = None,
        tag_ids: Optional[List[str]] = None,
    ) -> bool:
        token = await self.get_access_token()
        if not token:
            return False

        url = f"{self.BASE_URL}/message/send?access_token={token}"
        
        payload: Dict[str, Any] = {
            "msgtype": "text",
            "agentid": self.agent_id,
            "text": {"content": content},
            "safe": 0,
            "enable_id_trans": 0,
            "enable_duplicate_check": 0,
        }

        if user_ids:
            payload["touser"] = "|".join(user_ids)
        if party_ids:
            payload["toparty"] = "|".join(party_ids)
        if tag_ids:
            payload["totag"] = "|".join(tag_ids)
        
        if not user_ids and not party_ids and not tag_ids:
            logger.warning("send_text_message called without any recipients (user_ids, party_ids, tag_ids). Defaulting to @all if applicable for agent.")
            # payload["touser"] = "@all" # Be careful with @all, requires specific app permissions

        logger.debug(f"Sending text message. URL: {url}, Payload: {payload}")
        try:
            # 每次调用使用独立的 AsyncClient，避免跨事件循环问题
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            if data.get("errcode") == 0:
                logger.info(f"Text message sent successfully. MsgID: {data.get('msgid')}")
                return True
            else:
                logger.error(f"Failed to send text message: errcode={data.get('errcode')}, errmsg={data.get('errmsg')}, invaliduser={data.get('invaliduser')}")
                return False
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error sending text message: {e.response.status_code} - {e.response.text}")
            return False
        except Exception as e:
            logger.exception("Exception sending text message")
            return False

    async def upload_temporary_media(self, file_path: str, media_type: str = "file") -> Optional[str]:
        token = await self.get_access_token()
        if not token:
            return None

        if not os.path.exists(file_path):
            logger.error(f"File not found for upload: {file_path}")
            return None
        
        url = f"{self.BASE_URL}/media/upload?access_token={token}&type={media_type}"
        
        try:
            with open(file_path, "rb") as f:
                files = {"media": (os.path.basename(file_path), f, "application/octet-stream")} # Heuristic content type
                if media_type == "image":
                    files = {"media": (os.path.basename(file_path), f, "image/jpeg")} # Adjust as needed
                elif media_type == "voice":
                    files = {"media": (os.path.basename(file_path), f, "audio/amr")} # Adjust as needed
                elif media_type == "video":
                     files = {"media": (os.path.basename(file_path), f, "video/mp4")} # Adjust as needed


                logger.debug(f"Uploading temporary media. URL: {url}, File: {file_path}, Type: {media_type}")
                # 使用独立 AsyncClient 进行上传
                async with httpx.AsyncClient() as client:
                    response = await client.post(url, files=files)
                response.raise_for_status()
                data = response.json()

            if data.get("errcode") == 0 and "media_id" in data:
                logger.info(f"Media uploaded successfully. Media ID: {data['media_id']}, Type: {data.get('type')}")
                return data["media_id"]
            else:
                logger.error(f"Failed to upload media: errcode={data.get('errcode')}, errmsg={data.get('errmsg')}")
                return None
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error uploading media: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.exception(f"Exception uploading media: {file_path}")
            return None

    async def send_file_message(
        self,
        media_id: str,
        user_ids: Optional[List[str]] = None,
        party_ids: Optional[List[str]] = None,
        tag_ids: Optional[List[str]] = None,
    ) -> bool:
        token = await self.get_access_token()
        if not token:
            return False

        url = f"{self.BASE_URL}/message/send?access_token={token}"
        
        payload: Dict[str, Any] = {
            "msgtype": "file",
            "agentid": self.agent_id,
            "file": {"media_id": media_id},
            "safe": 0,
            "enable_duplicate_check": 0,
        }

        if user_ids:
            payload["touser"] = "|".join(user_ids)
        if party_ids:
            payload["toparty"] = "|".join(party_ids)
        if tag_ids:
            payload["totag"] = "|".join(tag_ids)

        if not user_ids and not party_ids and not tag_ids:
            logger.warning("send_file_message called without any recipients. Defaulting to @all if applicable.")
            # payload["touser"] = "@all"
        
        logger.debug(f"Sending file message. URL: {url}, Payload: {payload}")
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            if data.get("errcode") == 0:
                logger.info(f"File message sent successfully. MsgID: {data.get('msgid')}")
                return True
            else:
                logger.error(f"Failed to send file message: errcode={data.get('errcode')}, errmsg={data.get('errmsg')}, invaliduser={data.get('invaliduser')}")
                return False
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error sending file message: {e.response.status_code} - {e.response.text}")
            return False
        except Exception as e:
            logger.exception("Exception sending file message")
            return False

    async def send_message_to_external_contact(
        self,
        sender_userid: str,
        external_user_id: str, # 单个外部联系人ID
        message_text: str
    ) -> Dict[str, Any]:
        """
        使用 /cgi-bin/externalcontact/add_msg_template API 向单个外部联系人发送文本消息。
        注意：这是一个异步任务，API调用成功仅代表任务创建成功。

        Args:
            sender_userid: 发送消息的企业成员UserID。
            external_user_id: 目标外部联系人的external_userid。
            message_text: 要发送的文本内容。

        Returns:
            dict: 企业微信API的响应JSON (包含errcode, errmsg, msgid等)。
                  如果获取token失败或发生其他网络错误，可能返回一个包含自定义错误信息的字典。
        """
        token = await self.get_access_token()
        if not token:
            logger.error("send_message_to_external_contact: Failed to get access_token.")
            return {"errcode": -1, "errmsg": "Failed to get access_token"}

        url = f"{self.BASE_URL}/externalcontact/add_msg_template?access_token={token}"
        
        payload = {
           "chat_type": "single",
           "external_userid": [external_user_id],
           "sender": sender_userid,
           "text": {
               "content": message_text
           }
        }
        # 可选：如果需要发送附件，可以添加其他字段如 image, link, miniprogram
        # "attachments": [
        #     {
        #         "msgtype": "image",
        #         "image": {
        #             "media_id": "MEDIA_ID",
        #             # "pic_url": "PIC_URL" # 如果是图文链接类型
        #         }
        #     }
        # ]

        logger.debug(f"Sending message to external contact. URL: {url}, Payload: {payload}")
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload)
            response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)
            data = response.json()
            if data.get("errcode") == 0:
                logger.info(f"Successfully created message task for external contact {external_user_id}. MsgID: {data.get('msgid')}")
            else:
                logger.error(f"Failed to create message task for external contact {external_user_id}: errcode={data.get('errcode')}, errmsg={data.get('errmsg')}, fail_list={data.get('fail_list')}")
            return data
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error sending message to external contact {external_user_id}: {e.response.status_code} - {e.response.text}")
            return {"errcode": e.response.status_code, "errmsg": f"HTTP error: {e.response.text}"}
        except Exception as e:
            logger.exception(f"Exception sending message to external contact {external_user_id}")
            return {"errcode": -2, "errmsg": f"Exception: {str(e)}"}

    async def batch_get_external_contacts(self, userid_list: List[str], cursor: Optional[str] = None, limit: int = 100) -> Optional[Dict[str, Any]]:
        """
        批量获取指定成员的客户详情列表。
        API: /cgi-bin/externalcontact/batch/get_by_user

        Args:
            userid_list: 发起批量获取的成员UserID列表，最多支持100个。
            cursor: 上一次调用时返回的next_cursor，第一次或从头开始拉取时无需填写。
            limit: 返回数据的最大数，最多不超过100。

        Returns:
            Optional[Dict[str, Any]]: API的JSON响应字典，如果失败则返回None。
                                      包含 external_contact_list 和 next_cursor。
        """
        print("EW_SERVICE_DEBUG: Entering batch_get_external_contacts")
        logger.debug(f"EW_SERVICE_DEBUG: batch_get_external_contacts called with userid_list={userid_list}, cursor={cursor}, limit={limit}")
        
        token = await self.get_access_token()
        if not token:
            logger.error("EW_SERVICE_DEBUG: Failed to get access_token in batch_get_external_contacts. Returning None.")
            print("EW_SERVICE_DEBUG: No token, returning None from batch_get_external_contacts")
            return None

        url = f"{self.BASE_URL}/externalcontact/batch/get_by_user?access_token={token}"
        
        payload: Dict[str, Any] = {
            "userid_list": userid_list,
            "limit": min(limit, 100) # Ensure limit does not exceed 100
        }
        if cursor:
            payload["cursor"] = cursor

        logger.debug(f"EW_SERVICE_DEBUG: Calling externalcontact/batch/get_by_user API. URL: {url}, Payload: {payload}")
        print(f"EW_SERVICE_DEBUG: About to make HTTP POST to {url} with payload {payload}")
        try:
            # 使用独立 AsyncClient，并设置超时
            async with httpx.AsyncClient(timeout=15.0) as client: # <--- 设置超时为15秒
                response = await client.post(url, json=payload)
            
            print(f"EW_SERVICE_DEBUG: HTTP POST call completed. Status: {response.status_code}")
            logger.debug(f"EW_SERVICE_DEBUG: API response status: {response.status_code}, text: {response.text[:200]}...")

            response.raise_for_status() # Check for HTTP errors
            data = response.json()
            logger.debug(f"EW_SERVICE_DEBUG: API response JSON: {data}")
            print(f"EW_SERVICE_DEBUG: API response JSON: {data}")
            return data
        except httpx.HTTPStatusError as e:
            logger.error(f"批量获取外部联系人详情时发生HTTP错误: {e.response.status_code} - {e.response.text}")
            return None
        except httpx.TimeoutException as e:
            logger.error(f"批量获取外部联系人详情时发生超时错误: {e}")
            print(f"EW_SERVICE_DEBUG: TimeoutException: {e}")
            return None
        except Exception as e:
            logger.exception("批量获取外部联系人详情时发生异常")
            return None

    async def mark_external_contact_tags(
        self, 
        operator_userid: str, 
        external_userid: str, 
        add_tag_ids: Optional[List[str]] = None, 
        remove_tag_ids: Optional[List[str]] = None
    ) -> bool:
        """
        编辑客户的企业标签。
        API: /cgi-bin/externalcontact/mark_tag

        Args:
            operator_userid: 执行操作的成员UserID。
            external_userid: 外部联系人的userid。
            add_tag_ids: 要为客户添加的标签id列表。
            remove_tag_ids: 要为客户移除的标签id列表。

        Returns:
            bool: 操作是否成功。
        """
        token = await self.get_access_token()
        if not token:
            return False

        if not add_tag_ids and not remove_tag_ids:
            logger.warning("mark_external_contact_tags 调用时未指定要添加或移除的标签。")
            return False # 或者 True，因为没有操作，可以认为"成功"完成了无操作

        url = f"{self.BASE_URL}/externalcontact/mark_tag?access_token={token}"
        
        payload: Dict[str, Any] = {
            "userid": operator_userid,
            "external_userid": external_userid
        }
        if add_tag_ids:
            payload["add_tag"] = add_tag_ids
        if remove_tag_ids:
            payload["remove_tag"] = remove_tag_ids
        
        logger.debug(f"编辑外部联系人标签。URL: {url}, Payload: {payload}")
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            if data.get("errcode") == 0:
                logger.info(f"成功编辑外部联系人 {external_userid} 的标签。操作者: {operator_userid}")
                return True
            else:
                logger.error(f"编辑外部联系人标签失败: errcode={data.get('errcode')}, errmsg={data.get('errmsg')}")
                return False
        except httpx.HTTPStatusError as e:
            logger.error(f"编辑外部联系人标签时发生HTTP错误: {e.response.status_code} - {e.response.text}")
            return False
        except Exception as e:
            logger.exception(f"编辑外部联系人 {external_userid} 标签时发生异常")
            return False

# Example usage (for testing, typically this would be in your main app logic)
if __name__ == '__main__':
    import asyncio
    import logging
    logging.basicConfig(level=logging.DEBUG, 
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Ensure you have a .env file with WECOM_CORP_ID, WECOM_APP_SECRET, WECOM_AGENT_ID
    # and that src/config_ew.py loads them.

    async def main_test():
        service = EnterpriseWeChatService()
        
        # Test get_access_token
        token = await service.get_access_token()
        if not token:
            logger.error("Failed to get token for testing. Exiting.")
            await service.close()
            return

        # --- Test send_text_message ---
        # Replace 'YOUR_TEST_USER_ID' with an actual UserID from your enterprise
        test_user_id = "LinWeiLong" # MODIFY THIS
        if test_user_id == "UserId1":
             logger.warning("Please modify 'test_user_id' in the example usage of enterprise_wechat_service.py before testing send_text_message.")
        else:
            success_text = await service.send_text_message(
                content="Hello from EnterpriseWeChatService! This is a test text message.",
                user_ids=[test_user_id]
            )
            logger.info(f"Text message send attempt result: {success_text}")

        # --- Test upload_temporary_media and send_file_message ---
        # Create a dummy file for testing upload
        dummy_file_path = "test_upload.txt"
        with open(dummy_file_path, "w") as f:
            f.write("This is a test file for media upload and send file message.")
        
        media_id = await service.upload_temporary_media(file_path=dummy_file_path, media_type="file")
        
        if media_id:
            logger.info(f"Dummy file uploaded, media_id: {media_id}")
            if test_user_id == "UserId1":
                logger.warning("Please modify 'test_user_id' for send_file_message test.")
            else:
                success_file = await service.send_file_message(media_id=media_id, user_ids=[test_user_id])
                logger.info(f"File message send attempt result: {success_file}")
        else:
            logger.error("Failed to upload dummy file, cannot test send_file_message.")
            
        # Clean up dummy file
        if os.path.exists(dummy_file_path):
            os.remove(dummy_file_path)
            logger.info(f"Cleaned up dummy file: {dummy_file_path}")

        await service.close()

    asyncio.run(main_test()) 