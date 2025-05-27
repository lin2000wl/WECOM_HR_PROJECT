from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure
from typing import List, Dict, Optional, Any
from datetime import datetime

from src import config_ew # 修改导入
from .logger import logger # 假设 logger 在同级目录的 logger.py 中，或者调整为 from src.logger import logger
from .models.candidate import Candidate # 导入 Candidate 模型

class DBInterface:
    """处理与 MongoDB 数据库交互的类。"""
    _instance = None
    _client = None
    _db = None
    _collection = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(DBInterface, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        
        # 从 config_ew 获取配置
        uri = config_ew.MONGO_URI
        db_name = config_ew.MONGO_DATABASE
        # 假设集合名称也在 config_ew 中定义，如果不存在则使用默认值
        collection_name = getattr(config_ew, 'MONGO_CANDIDATE_COLLECTION', 'candidates') 

        try:
            logger.info(f"连接到 MongoDB: {uri}")
            self._client = MongoClient(uri, serverSelectionTimeoutMS=5000) # 设置连接超时
            # The ismaster command is cheap and does not require auth.
            # self._client.admin.command('ismaster') # 验证连接
            # self._client.admin.command('ismaster') # 验证连接 - Commented out for mongomock compatibility
            self._db = self._client[db_name]
            self._collection = self._db[collection_name]
            logger.info(f"成功连接到 MongoDB 数据库 '{db_name}', 集合 '{collection_name}'.")
            # 可以考虑在这里创建索引，例如根据 name 和 phone
            self.create_indexes()
            self._initialized = True
        except ConnectionFailure as e:
            logger.critical(f"无法连接到 MongoDB: {e}")
            # 在无法连接数据库时，应该如何处理？抛出异常或允许程序继续但功能受限？
            # 目前选择记录严重错误并允许程序继续，但后续操作会失败
            self._client = None 
            self._db = None
            self._collection = None
        except Exception as e:
            logger.critical(f"初始化 MongoDB 连接时发生未知错误: {e}", exc_info=True)
            self._client = None
            self._db = None
            self._collection = None

    def is_connected(self) -> bool:
        """检查数据库是否已成功连接。"""
        return self._collection is not None

    def create_indexes(self):
        """为常用查询字段创建索引。"""
        if not self.is_connected():
            return
        try:
            # 为 name 和 phone 创建联合唯一索引（如果它们是主要标识符）
            # 确保数据一致性
            self._collection.create_index([("name", 1), ("phone", 1)], name='name_phone_unique_idx', unique=True)
            # 单独的 name 和 phone 索引不再需要，因为复合索引的前缀可用于 name 查询
            # 如果 phone 需要高性能独立查询，可以考虑保留 phone 索引，但通常复合唯一性更重要
            # self._collection.create_index([("name", 1)], background=True)
            # self._collection.create_index([("phone", 1)], background=True)
            # 为 query_tags 中的字段创建索引 (保留 background=True)
            self._collection.create_index([("query_tags.positions", 1)], name='positions_idx', background=True)
            self._collection.create_index([("query_tags.min_experience_years", 1)], name='experience_idx', background=True)
            self._collection.create_index([("query_tags.skills_normalized", 1)], name='skills_idx', background=True)
            logger.info("已尝试创建/确保 MongoDB 索引存在。")
        except OperationFailure as e:
            logger.warning(f"创建 MongoDB 索引时出错 (可能已存在或权限问题): {e}")
        except Exception as e:
            logger.error(f"创建 MongoDB 索引时发生未知错误: {e}", exc_info=True)
            
    def upsert_candidate(self, candidate_data: Dict[str, Any]) -> bool:
        """
        插入或更新单个候选人记录。
        基于姓名和手机号作为唯一标识符进行更新。

        Args:
            candidate_data (Dict[str, Any]): 包含候选人信息的字典 (应符合 Candidate 模型，但不含 _id)。

        Returns:
            bool: 操作是否成功。
        """
        if not self.is_connected():
            logger.error("数据库未连接，无法 upsert 候选人。")
            return False
        
        if not candidate_data.get("name") or not candidate_data.get("phone"):
            logger.error("无法 upsert 候选人：缺少姓名或手机号。")
            return False

        filter_query = {
            "name": candidate_data["name"],
            "phone": candidate_data["phone"]
        }
        
        # 添加 last_processed_time
        candidate_data["last_processed_time"] = datetime.now()

        update_data = {"$set": candidate_data}

        try:
            result = self._collection.update_one(filter_query, update_data, upsert=True)
            if result.upserted_id:
                logger.info(f"成功插入新候选人: {candidate_data.get('name')}")
            elif result.modified_count > 0:
                logger.info(f"成功更新候选人: {candidate_data.get('name')}")
            else:
                # matched_count > 0 and modified_count == 0 表示找到但未修改（数据相同）
                if result.matched_count > 0:
                     logger.info(f"候选人数据无变化: {candidate_data.get('name')}")
                else:
                     # 理论上 upsert=True 不会到这里，除非有并发问题？
                     logger.warning(f"Upsert 操作未匹配也未插入: {candidate_data.get('name')}")
            return True
        except OperationFailure as e:
            logger.error(f"Upsert 候选人 {candidate_data.get('name')} 失败: {e}")
            return False
        except Exception as e:
            logger.error(f"Upsert 候选人时发生未知错误: {e}", exc_info=True)
            return False

    def find_candidates(self, query: Dict[str, Any], limit: int = 10, offset: int = 0) -> List[Candidate]:
        """
        根据查询条件查找候选人。

        Args:
            query (Dict[str, Any]): MongoDB 查询条件的字典。
            limit (int): 返回的最大结果数量。
            offset (int): 跳过的记录数 (用于分页)。

        Returns:
            List[Candidate]: 匹配的候选人对象列表。
        """
        if not self.is_connected():
            logger.error("数据库未连接，无法查找候选人。")
            return []

        candidates = []
        try:
            # 使用 skip() 方法实现 offset
            results = self._collection.find(query).skip(offset).limit(limit)
            for doc in results:
                try:
                    candidates.append(Candidate.from_dict(doc))
                except Exception as e:
                     logger.error(f"从数据库文档转换 Candidate 对象失败: {e}, 文档: {doc}", exc_info=True)
            logger.info(f"数据库查询 '{query}' (跳过 {offset} 条) 找到 {len(candidates)} 条记录 (限制 {limit} 条)。")
        except OperationFailure as e:
            logger.error(f"查找候选人失败 (查询: {query}, 偏移: {offset}): {e}")
        except Exception as e:
            logger.error(f"查找候选人时发生未知错误 (查询: {query}, 偏移: {offset}): {e}", exc_info=True)
        
        return candidates

    def find_candidate_by_id(self, candidate_id: str) -> Optional[Candidate]:
        """通过 MongoDB ObjectId 查找单个候选人。"""
        if not self.is_connected():
            logger.error("数据库未连接，无法按 ID 查找候选人。")
            return None
        from bson import ObjectId
        from bson.errors import InvalidId
        try:
            obj_id = ObjectId(candidate_id)
        except InvalidId:
            logger.error(f"无效的候选人 ID 格式: {candidate_id}")
            return None
        
        try:
            doc = self._collection.find_one({"_id": obj_id})
            if doc:
                return Candidate.from_dict(doc)
            else:
                logger.warning(f"未找到 ID 为 {candidate_id} 的候选人。")
                return None
        except Exception as e:
            logger.error(f"按 ID {candidate_id} 查找候选人时出错: {e}", exc_info=True)
            return None

    def find_candidate_by_phone(self, phone_number: str) -> Optional[Candidate]:
        """通过手机号码查找单个候选人。"""
        if not self.is_connected():
            logger.error("数据库未连接，无法按手机号查找候选人。")
            return None
        
        if not phone_number or not isinstance(phone_number, str):
            logger.error(f"无效的手机号码参数: {phone_number}")
            return None
        
        try:
            # 假设手机号直接存储在顶层 "phone" 字段
            doc = self._collection.find_one({"phone": phone_number})
            if doc:
                logger.info(f"通过手机号 {phone_number} 找到候选人: {doc.get('name')}")
                return Candidate.from_dict(doc)
            else:
                logger.info(f"未找到手机号为 {phone_number} 的候选人记录。")
                return None
        except Exception as e:
            logger.error(f"按手机号 {phone_number} 查找候选人时出错: {e}", exc_info=True)
            return None

    def update_candidate_by_id(self, candidate_doc_id: str, update_fields: Dict[str, Any]) -> bool:
        """
        通过 MongoDB ObjectId 更新单个候选人记录的指定字段。

        Args:
            candidate_doc_id (str): 候选人的 MongoDB ObjectId 字符串。
            update_fields (Dict[str, Any]): 包含要更新的字段和它们新值的字典。

        Returns:
            bool: 更新操作是否成功修改了记录。
        """
        if not self.is_connected():
            logger.error("数据库未连接，无法按 ID 更新候选人。")
            return False
        
        from bson import ObjectId
        from bson.errors import InvalidId

        try:
            obj_id = ObjectId(candidate_doc_id)
        except InvalidId:
            logger.error(f"无效的候选人文档 ID 格式: {candidate_doc_id}，无法更新。")
            return False
        
        if not update_fields or not isinstance(update_fields, dict):
            logger.error(f"无效的更新字段参数: {update_fields}，无法更新候选人 {candidate_doc_id}。")
            return False

        try:
            # 添加 last_processed_time 到更新字段中
            updates_with_timestamp = {**update_fields, "last_processed_time": datetime.now()}
            
            result = self._collection.update_one(
                {"_id": obj_id},
                {"$set": updates_with_timestamp}
            )
            
            if result.modified_count > 0:
                logger.info(f"成功更新候选人 (ID: {candidate_doc_id})。更新字段: {update_fields}")
                return True
            elif result.matched_count > 0:
                logger.info(f"候选人 (ID: {candidate_doc_id}) 已找到但无需更新 (数据与提供的值相同)。更新字段: {update_fields}")
                return True # 认为匹配到且数据相同也算一种 "成功" 操作，或者可以返回 False，取决于业务定义
            else:
                logger.warning(f"未找到 ID 为 {candidate_doc_id} 的候选人进行更新，或更新操作未产生任何更改。")
                return False
        except OperationFailure as e:
            logger.error(f"按 ID ({candidate_doc_id}) 更新候选人失败: {e}")
            return False
        except Exception as e:
            logger.error(f"按 ID ({candidate_doc_id}) 更新候选人时发生未知错误: {e}", exc_info=True)
            return False
            
    def close_connection(self):
        """关闭 MongoDB 连接。"""
        if self._client:
            try:
                self._client.close()
                logger.info("MongoDB 连接已关闭。")
            except Exception as e:
                logger.error(f"关闭 MongoDB 连接时出错: {e}", exc_info=True)
            finally:
                 self._client = None
                 self._db = None
                 self._collection = None
                 DBInterface._instance = None # 重置单例，以便可以重新初始化

# 创建一个全局的数据库接口实例
db_interface = DBInterface()

# 在程序退出时尝试关闭连接 (可以使用 atexit 模块注册)
import atexit
atexit.register(db_interface.close_connection)

if __name__ == '__main__':
    # 确保 MongoDB 服务正在运行
    if db_interface.is_connected():
        logger.info("运行 DBInterface 示例...")
        
        # 示例 1: Upsert 一个候选人
        candidate1_data = {
            "name": "李四",
            "phone": "13900139000",
            "email": "lisi@example.com",
            "resume_pdf_path": "processed_resumes/李四9000.pdf",
            "extracted_info": {
                "summary": "后端开发工程师",
                "skills": ["Java", "Spring", "MySQL"]
            },
             "query_tags": {
                "positions": ["后端工程师", "Java工程师"],
                "min_experience_years": 3,
                "skills_normalized": ["java", "spring", "mysql"]
            }
        }
        db_interface.upsert_candidate(candidate1_data)

        # 示例 2: Upsert 另一个候选人 (用于查询测试)
        candidate2_data = {
            "name": "王五",
            "phone": "13700137000",
            "resume_pdf_path": "processed_resumes/王五7000.pdf",
            "extracted_info": {
                 "summary": "全栈工程师",
                 "skills": ["Python", "React", "Node.js", "MongoDB"]
            },
             "query_tags": {
                "positions": ["全栈工程师", "软件工程师"],
                "min_experience_years": 5,
                "skills_normalized": ["python", "react", "nodejs", "mongodb"]
            }
        }
        db_interface.upsert_candidate(candidate2_data)
        
        # 示例 3: 更新李四的信息
        candidate1_update = {
            "name": "李四",
            "phone": "13900139000",
            "email": "lisi_updated@example.com", # 更新邮箱
            "wxid": "wxid_lisi_123", # 添加 wxid
            "resume_pdf_path": "processed_resumes/李四9000_v2.pdf",
            "extracted_info": {
                "summary": "资深后端开发工程师", # 更新摘要
                "skills": ["Java", "Spring Boot", "MySQL", "Redis"] # 更新技能
            },
            "query_tags": {
                "positions": ["后端工程师", "Java工程师", "架构师"],
                "min_experience_years": 4, # 更新经验
                "skills_normalized": ["java", "springboot", "mysql", "redis"]
            }
        }
        db_interface.upsert_candidate(candidate1_update)

        # 示例 4: 查询所有候选人 (限制 5 个)
        print("\n--- 查询所有候选人 (限制 5) ---")
        all_candidates = db_interface.find_candidates({}, limit=5)
        for cand in all_candidates:
            print(cand.name, cand.phone, cand.resume_pdf_path, cand.query_tags.get("min_experience_years"))

        # 示例 5: 查询职位包含 "工程师" 且经验 >= 4 年的候选人
        print("\n--- 查询经验 >= 4 年的工程师 ---")
        query_criteria = {
            "query_tags.positions": {"$regex": "工程师"}, # 使用正则模糊匹配职位
            "query_tags.min_experience_years": {"$gte": 4}
        }
        engineer_candidates = db_interface.find_candidates(query_criteria)
        for cand in engineer_candidates:
            print(cand.name, cand.phone, cand.query_tags.get("positions"), cand.query_tags.get("min_experience_years"))
            
        # 示例 6: 查询技能包含 "python" (忽略大小写) 的候选人
        print("\n--- 查询技能包含 Python 的候选人 ---")
        python_query = {
            "query_tags.skills_normalized": "python" 
        }
        python_candidates = db_interface.find_candidates(python_query)
        for cand in python_candidates:
             print(cand.name, cand.phone, cand.query_tags.get("skills_normalized"))

    else:
        logger.error("无法连接到数据库，示例代码无法运行。请检查 MongoDB 服务状态和配置。") 