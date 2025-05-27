# src/utils/state_manager.py
import time
from typing import Dict, Any, List, Optional
import threading # 引入线程锁
from cachetools import TTLCache # 引入 TTL 缓存
# from ..logger import logger # Remove relative import
from src.logger import logger # Use absolute import
from src import config_ew # 导入配置以便读取TTL和MAXSIZE

# Define state constants
STATE_IDLE = "idle"
STATE_WAITING_SELECTION = "waiting_selection"
# STATE_WAITING_JOB_DETAILS = "waiting_job_details" # Replaced by more specific flow states

# New constants for the multi-step contact candidate flow
STATE_CONTACT_CANDIDATE_DETAILS_FLOW = "contact_candidate_details_flow" 
STEP_AWAITING_WORK_LOCATION = "awaiting_work_location"
STEP_AWAITING_JOB_CONTENT = "awaiting_job_content"
STEP_AWAITING_TIME_ARRANGEMENT = "awaiting_time_arrangement"

# Default Cache settings (can be overridden by config_ew)
DEFAULT_CACHE_MAXSIZE = 1024 # 最多缓存的用户状态数量
DEFAULT_CACHE_TTL = 180     # 状态缓存时间 (秒), 3分钟

class StateManager:
    """
    管理用户交互状态和临时数据（如上次查询结果和查询上下文）。
    使用带 TTL 的线程安全缓存实现。
    """
    def __init__(self, ttl_seconds: Optional[int] = None, max_size: Optional[int] = None):
        effective_ttl = ttl_seconds if ttl_seconds is not None else DEFAULT_CACHE_TTL
        effective_maxsize = max_size if max_size is not None else DEFAULT_CACHE_MAXSIZE
        
        self._user_states: TTLCache = TTLCache(maxsize=effective_maxsize, ttl=effective_ttl)
        self._lock = threading.Lock()
        logger.info(f"StateManager 初始化成功 (TTLCache 模式, TTL={effective_ttl}s, Maxsize={effective_maxsize})。")

    def _get_user_data(self, user_id: str) -> Optional[Dict[str, Any]]:
        """内部方法：安全地获取指定用户的缓存数据。"""
        with self._lock:
            return self._user_states.get(user_id)

    def get_state(self, user_id: str) -> str:
        """获取用户的当前状态。如果用户不存在或状态过期，返回 IDLE。"""
        user_data = self._get_user_data(user_id)
        return user_data.get("state", STATE_IDLE) if user_data else STATE_IDLE

    def store_parsed_query_data(self, user_id: str, parsed_data: Dict[str, Any]):
        """在缓存中存储 LLM 解析出的原始查询条件。"""
        with self._lock:
            user_data = self._user_states.get(user_id, {})
            user_data['parsed_query_data'] = parsed_data
            # Also ensure state exists if we are storing query data
            if 'state' not in user_data:
                 user_data['state'] = STATE_IDLE # Or maybe infer state? Keep it simple.
            self._user_states[user_id] = user_data
            logger.debug(f"为用户 [{user_id}] 存储了原始解析查询条件。")

    def cache_results(self, user_id: str, results: List[Dict[str, Any]]):
        """缓存用户的上次查询结果。"""
        with self._lock:
            user_data = self._user_states.get(user_id, {})
            user_data['last_results'] = results
            if 'state' not in user_data:
                user_data['state'] = STATE_IDLE
            self._user_states[user_id] = user_data
            logger.debug(f"为用户 [{user_id}] 缓存了 {len(results) if results else 0} 条查询结果。")

    def update_state(self, user_id: str, state: str):
        """更新用户的状态。"""
        with self._lock:
            user_data = self._user_states.get(user_id, {})
            user_data['state'] = state
            self._user_states[user_id] = user_data
            logger.debug(f"用户 [{user_id}] 状态更新为: {state}")

    def get_last_results(self, user_id: str) -> Optional[List[Dict[str, Any]]]:
        """获取用户的上次查询结果。如果用户不存在或状态过期，返回 None。"""
        user_data = self._get_user_data(user_id)
        return user_data.get("last_results") if user_data else None

    def get_query_criteria(self, user_id: str) -> Optional[Dict[str, Any]]:
        """获取用户的上次 MongoDB 查询条件。如果用户不存在或状态过期，返回 None。"""
        user_data = self._get_user_data(user_id)
        return user_data.get("query_criteria") if user_data else None

    def get_parsed_query_data(self, user_id: str) -> Optional[Dict[str, Any]]:
        """获取用户的上次 LLM 解析的查询条件。如果用户不存在或状态过期，返回 None。"""
        user_data = self._get_user_data(user_id)
        return user_data.get("parsed_query_data") if user_data else None

    def get_query_offset(self, user_id: str) -> int:
        """获取用户下次查询应使用的偏移量。如果用户不存在或状态过期，返回 0。"""
        user_data = self._get_user_data(user_id)
        return user_data.get("query_offset", 0) if user_data else 0

    def get_has_more(self, user_id: str) -> bool:
        """检查缓存中是否标记还有更多候选人。如果用户不存在或状态过期，返回 False。"""
        user_data = self._get_user_data(user_id)
        return user_data.get("has_more", False) if user_data else False

    def clear_state(self, user_id: str):
        """清除用户的状态和所有缓存数据。"""
        with self._lock:
            if user_id in self._user_states:
                del self._user_states[user_id]
                logger.debug(f"清除了用户 [{user_id}] 的状态和所有缓存数据。")
            else:
                logger.debug(f"尝试清除用户 [{user_id}] 的状态，但该用户不存在或已过期于状态管理器中。")

    def update_state_and_cache_results(
        self,
        user_id: str,
        state: str,
        results: Optional[List[Dict[str, Any]]] = None,
        query_criteria: Optional[Dict[str, Any]] = None,
        parsed_query_data: Optional[Dict[str, Any]] = None, # Added
        current_offset: Optional[int] = None,
        has_more: Optional[bool] = None # Added
    ):
        """
        原子地更新状态、缓存结果、查询条件、解析数据、偏移量和是否有更多标记。
        操作会刷新该用户的 TTL。
        """
        with self._lock:
            # 获取当前数据或创建新字典
            # Important: Preserve existing parsed_query_data if not provided in this update
            user_data = self._user_states.get(user_id, {})
            existing_parsed_data = user_data.get('parsed_query_data')

            # 更新数据
            user_data["state"] = state
            user_data["last_results"] = results
            user_data["query_criteria"] = query_criteria
            
            if parsed_query_data is not None:
                 user_data['parsed_query_data'] = parsed_query_data
            elif existing_parsed_data is not None:
                 user_data['parsed_query_data'] = existing_parsed_data
                 
            if current_offset is not None:
                user_data["query_offset"] = current_offset
            else:
                if state == STATE_IDLE or results is None:
                    user_data["query_offset"] = 0
            
            if has_more is not None:
                user_data["has_more"] = has_more
            else:
                 user_data["has_more"] = results is not None and len(results) > 0

            self._user_states[user_id] = user_data

        results_log = f"{len(results)}条结果" if results else "无结果"
        context_log = "有查询条件" if query_criteria else "无查询条件"
        parsed_data_log = "有解析数据" if user_data.get('parsed_query_data') else "无解析数据"
        offset_log = f"下次偏移量 {user_data.get('query_offset', 'N/A')}"
        has_more_log = f"有更多: {user_data.get('has_more')}"
        logger.debug(f"用户 [{user_id}] 状态更新为: {state}，缓存 {results_log}，{context_log}，{parsed_data_log}，{offset_log}，{has_more_log}。(TTL已刷新)")

    # --- Methods for the new multi-step contact candidate flow ---
    def set_contact_flow_state(
        self, 
        user_id: str, 
        step: str, 
        candidate_external_userid: str, 
        candidate_name: str, 
        hr_sender_userid: str,
        collected_info: Optional[Dict[str, Optional[str]]] = None
    ):
        """
        初始化或完全覆盖特定用户的"联系候选人"多轮对话流程的状态。
        会将主状态设置为 STATE_CONTACT_CANDIDATE_DETAILS_FLOW。
        """
        with self._lock:
            user_data = self._user_states.get(user_id, {})
            user_data["state"] = STATE_CONTACT_CANDIDATE_DETAILS_FLOW
            user_data["contact_flow_data"] = {
                "flow": STATE_CONTACT_CANDIDATE_DETAILS_FLOW, # Identifier for the flow itself
                "step": step,
                "candidate_external_userid": candidate_external_userid,
                "candidate_name": candidate_name,
                "hr_sender_userid": hr_sender_userid,
                "collected_info": collected_info if collected_info is not None else {}
            }
            self._user_states[user_id] = user_data
            logger.debug(f"用户 [{user_id}] 进入联系候选人流程，步骤: {step}。候选人: {candidate_name} ({candidate_external_userid})。 (TTL已刷新)")

    def get_contact_flow_state(self, user_id: str) -> Optional[Dict[str, Any]]:
        """获取用户当前的"联系候选人"流程特定数据。"""
        user_data = self._get_user_data(user_id)
        if user_data and user_data.get("state") == STATE_CONTACT_CANDIDATE_DETAILS_FLOW:
            return user_data.get("contact_flow_data")
        return None

    def update_contact_flow_step_and_info(
        self,
        user_id: str,
        new_step: str,
        info_key_to_update: Optional[str] = None,
        info_value: Optional[str] = None,
    ):
        """更新用户在"联系候选人"流程中的当前步骤和/或已收集的信息中的一项。"""
        with self._lock:
            user_data = self._user_states.get(user_id)
            if not user_data or user_data.get("state") != STATE_CONTACT_CANDIDATE_DETAILS_FLOW:
                logger.warning(f"尝试为用户 [{user_id}] 更新联系候选人流程信息，但用户不在此流程中或状态不存在。")
                return

            flow_data = user_data.get("contact_flow_data", {})
            flow_data["step"] = new_step
            if info_key_to_update and info_value is not None:
                if "collected_info" not in flow_data:
                    flow_data["collected_info"] = {}
                flow_data["collected_info"][info_key_to_update] = info_value
            
            user_data["contact_flow_data"] = flow_data
            self._user_states[user_id] = user_data # This refreshes TTL
            logger.debug(f"用户 [{user_id}] 联系候选人流程更新。新步骤: {new_step}。更新信息项: {info_key_to_update}。 (TTL已刷新)")

# --- 单例创建逻辑 --- 
# 从配置中读取 TTL 和 MAXSIZE，如果配置不存在或无效，则使用默认值
configured_ttl = DEFAULT_CACHE_TTL
if hasattr(config_ew, 'STATE_CACHE_TTL_SECONDS'):
    try:
        configured_ttl = int(config_ew.STATE_CACHE_TTL_SECONDS)
    except ValueError:
        logger.warning(f"StateManager: 无法将 config_ew.STATE_CACHE_TTL_SECONDS ('{config_ew.STATE_CACHE_TTL_SECONDS}') 解析为整数，将使用默认TTL {DEFAULT_CACHE_TTL}s")

configured_maxsize = DEFAULT_CACHE_MAXSIZE
if hasattr(config_ew, 'STATE_CACHE_MAXSIZE'):
    try:
        configured_maxsize = int(config_ew.STATE_CACHE_MAXSIZE)
    except ValueError:
        logger.warning(f"StateManager: 无法将 config_ew.STATE_CACHE_MAXSIZE ('{config_ew.STATE_CACHE_MAXSIZE}') 解析为整数，将使用默认Maxsize {DEFAULT_CACHE_MAXSIZE}")

# 创建一个单例供其他模块使用
state_manager = StateManager(ttl_seconds=configured_ttl, max_size=configured_maxsize) 