import logging
from typing import List, Set

from src import config_ew # 导入企业微信配置模块

logger = logging.getLogger(__name__)

class AuthHandlerEw:
    """
    处理企业微信用户的授权认证。
    """
    def __init__(self):
        """
        初始化授权处理器，加载授权用户ID列表。
        """
        try:
            # 从配置模块获取授权用户ID列表 (字符串形式，逗号分隔)
            authorized_ids_str = config_ew.AUTHORIZED_USER_IDS_EW 
            if isinstance(authorized_ids_str, str):
                # 分割字符串并去除空白符，然后存入集合以便快速查找
                self.authorized_user_ids: Set[str] = {
                    uid.strip() for uid in authorized_ids_str.split(',') if uid.strip()
                }
            elif isinstance(authorized_ids_str, list): # 兼容已经是列表的情况
                 self.authorized_user_ids: Set[str] = {
                    str(uid).strip() for uid in authorized_ids_str if str(uid).strip()
                }
            else:
                self.authorized_user_ids: Set[str] = set()
                logger.warning(
                    "AUTHORIZED_USER_IDS_EW 配置格式不正确或未配置，将没有用户被授权。"
                    f"当前获取到的值: {authorized_ids_str}, 类型: {type(authorized_ids_str)}"
                )
            
            logger.info(f"AuthHandlerEw 初始化完成。授权用户ID: {self.authorized_user_ids}")
        except AttributeError:
            self.authorized_user_ids: Set[str] = set()
            logger.exception(
                "config_ew 中似乎缺少 AUTHORIZED_USER_IDS_EW 配置。"
                "请确保 .env 文件中有 WECOM_AUTHORIZED_USER_IDS 并且 config_ew.py 正确加载了它。"
                "将没有用户被授权。"
            )
        except Exception as e:
            self.authorized_user_ids: Set[str] = set()
            logger.exception(f"AuthHandlerEw 初始化失败: {e}。将没有用户被授权。")


    def is_authorized(self, user_id: str) -> bool:
        """
        检查给定的企业微信用户ID是否已授权。

        Args:
            user_id: 要检查的企业微信用户ID (通常是回调消息中的 FromUserName)。

        Returns:
            bool: 如果用户已授权则返回 True，否则返回 False。
        """
        if not user_id:
            logger.warning("尝试检查一个空的 user_id。")
            return False
        
        is_auth = user_id in self.authorized_user_ids
        if is_auth:
            logger.debug(f"用户 '{user_id}' 已授权访问。")
        else:
            logger.info(f"用户 '{user_id}' 未授权访问。授权列表: {self.authorized_user_ids}")
        return is_auth

if __name__ == '__main__':
    # 简单的测试代码
    logging.basicConfig(level=logging.DEBUG)
    
    # 假设你的 .env 文件中有 WECOM_AUTHORIZED_USER_IDS_EW = "user1,user2, another_user "
    # 并且 config_ew.py 正确加载了它
    
    print("--- 测试 AuthHandlerEw --- ")
    # 模拟 config_ew 在测试时加载正确的配置
    class MockConfigEw:
        # 注意：在实际项目中，config_ew.AUTHORIZED_USER_IDS_EW 应该由 config_ew.py 从 .env 加载
        # 此处仅为方便独立测试 auth_handler_ew.py
        # 如果直接运行此文件进行测试，需要确保 .env 和 config_ew.py 配置正确，
        # 或者像下面这样临时模拟一个配置值
        # AUTHORIZED_USER_IDS_EW = "id_test_1, id_test_2, id_test_3 " 
        
        # 为了让直接运行此文件能通过，我们先尝试从真正的config_ew导入
        # 如果失败（比如在CI环境或未完全配置时），再使用下面的模拟值
        try:
            from src import config_ew as actual_config_ew
            AUTHORIZED_USER_IDS_EW = actual_config_ew.AUTHORIZED_USER_IDS_EW
            print(f"成功从 src.config_ew 加载配置: {AUTHORIZED_USER_IDS_EW}")
        except ImportError:
            print("无法从 src.config_ew 加载配置，使用模拟值进行测试。确保您的 .env 和 config_ew.py 配置正确。")
            AUTHORIZED_USER_IDS_EW = "user_alpha,user_beta, user_gamma " # 模拟值

    # 将模拟的配置赋值给 config_ew，以便 AuthHandlerEw 能使用
    # 这种方式仅适用于当前 __main__ 测试块，不会影响模块的正常导入
    original_config_ew = config_ew 
    config_ew = MockConfigEw()

    auth_handler = AuthHandlerEw()
    
    test_cases = [
        ("user_alpha", True),
        ("user_beta", True),
        ("user_gamma", True), # 测试带空格的情况
        ("User_Alpha", False), # 大小写敏感
        ("unknown_user", False),
        ("".strip(), False), # 空字符串
        (None, False)
    ]
    
    print(f"测试使用的授权列表: {auth_handler.authorized_user_ids}")

    all_passed = True
    for user, expected in test_cases:
        result = auth_handler.is_authorized(user)
        print(f"测试用户 '{user}': 期望结果={expected}, 实际结果={result} -> {'通过' if result == expected else '失败'}")
        if result != expected:
            all_passed = False
            
    if all_passed:
        print("所有 AuthHandlerEw 测试用例通过！")
    else:
        print("部分 AuthHandlerEw 测试用例失败。")

    # 恢复原始的 config_ew 模块，以防干扰其他可能的导入（虽然在此脚本末尾不太可能）
    config_ew = original_config_ew 