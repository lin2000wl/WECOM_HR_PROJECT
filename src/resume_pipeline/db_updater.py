import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any
import os

from src.db_interface import db_interface # Import the instance
from src.models.candidate import Candidate # Assuming Candidate model is needed for type hinting or validation

logger = logging.getLogger(__name__)

class DbUpdater:
    """Handles updating the candidate database with processed resume information."""

    def __init__(self, db_interface_instance):
        """
        Initializes the DbUpdater.

        Args:
            db_interface_instance: An instance of db_interface to interact with the database.
        """
        self.db_interface = db_interface_instance
        if not self.db_interface.is_connected():
            logger.critical("DbUpdater initialized but database is not connected!")
            # Decide handling: raise error or allow continuation with failures

    def upsert_candidate(self, candidate_data: Dict[str, Any], processed_pdf_path: Path) -> bool:
        """
        Updates or inserts a candidate record in the database based on extracted data.

        Uses 'name' and 'phone' as the primary keys for the upsert operation.

        Args:
            candidate_data: Dictionary containing extracted info (should have name, phone).
            processed_pdf_path: The final path of the processed resume PDF file
                                  in the 'processed_resumes' directory.

        Returns:
            True if the upsert operation was successful, False otherwise.
        """
        if not self.db_interface.is_connected():
            logger.error("Database not connected, cannot upsert candidate.")
            return False

        # Ensure essential keys are present (could be done in validator too)
        name = candidate_data.get('name')
        phone = candidate_data.get('phone')
        if not name or not phone:
            logger.error(f"Cannot upsert candidate due to missing name ('{name}') or phone ('{phone}'). Data: {candidate_data}")
            return False

        # Add/Update the resume path
        candidate_data['resume_pdf_path'] = str(processed_pdf_path)

        # Add/Update query tags (this logic might be better placed in validator_standardizer)
        # Example: simple position and skill tagging
        query_tags = candidate_data.get('query_tags', {})
        # --- Placeholder: Actual tag generation logic should be implemented --- 
        # Example based on first found job title and skills
        if not query_tags.get('positions') and candidate_data.get('extracted_info', {}).get('experience'):
             first_exp = candidate_data['extracted_info']['experience'][0]
             if first_exp.get('title'):
                 query_tags['positions'] = [first_exp['title']] # Simple tagging
        if not query_tags.get('skills_normalized') and candidate_data.get('extracted_info', {}).get('skills'):
             query_tags['skills_normalized'] = [s.lower() for s in candidate_data['extracted_info']['skills'] if isinstance(s, str)]
        # Example: calculate min experience (very basic, needs refinement)
        if not query_tags.get('min_experience_years') and candidate_data.get('extracted_info', {}).get('experience'):
             try:
                 total_years = 0
                 # Very naive calculation: sum durations assuming YYYY-MM format or YYYY
                 # This needs a proper date parsing library and logic
                 # for exp in candidate_data['extracted_info']['experience']:
                 #     start = exp.get('start_date')
                 #     end = exp.get('end_date')
                 #     # ... complex date diff logic ...
                 # Placeholder: use a fixed value or leave null if complex logic not implemented
                 if len(candidate_data['extracted_info']['experience']) > 0:
                      query_tags['min_experience_years'] = 1 # Placeholder
             except Exception as e:
                 logger.warning(f"Failed to calculate min_experience_years: {e}")
        # --- End Placeholder ---
        candidate_data['query_tags'] = query_tags

        # 构建要插入/更新到 MongoDB 的文档
        # 注意：这里假设 parsed_data 包含了所有 Candidate 模型需要的顶级字段
        # 以及嵌套的 extracted_info 和可能的 query_tags
        candidate_doc = {
            # "name": parsed_data.get("name"), # 这些应该已经包含在 parsed_data 中
            # "phone": parsed_data.get("phone"),
            # "email": parsed_data.get("email"),
            **candidate_data, # 直接解包 LLM 返回的字典，因为它的结构就是我们想要的
            "resume_pdf_path": str(processed_pdf_path), # 添加处理后的 PDF 路径 (转换为字符串)
            "last_processed_time": datetime.utcnow(),
            "source_file_original_name": os.path.basename(str(processed_pdf_path)) # 保留原始文件名 (转换为字符串)
        }
        
        # 确保 query_tags 存在 (即使为空)
        if 'query_tags' not in candidate_doc or not isinstance(candidate_doc['query_tags'], dict):
            candidate_doc['query_tags'] = {}
            
        # --- 新增：准备 query_tags --- 
        # 1. 设计类别 (从 parsed_data 的顶级获取)
        design_category = candidate_data.get('design_category')
        if design_category in ["建筑设计", "电气设计", "给排水设计"]:
            candidate_doc['query_tags']['design_category'] = design_category
        else:
            # 如果不是预设的三个类别或为 null，则在 query_tags 中也设为 null 或不设置
            # 这里选择设置为 null，以便查询时可以区分未分类和特定分类
            candidate_doc['query_tags']['design_category'] = None

        # 2. 学历标签 (从 extracted_info.education 提取并标准化)
        degrees = set()
        if candidate_data.get('extracted_info', {}).get('education'):
            for edu in candidate_data['extracted_info']['education']:
                if edu.get('degree'):
                    degrees.add(edu['degree'].lower())
        candidate_doc['query_tags']['degrees'] = list(degrees)

        logger.debug(f"Attempting to upsert candidate '{name}' with data: {candidate_doc}")

        # Call the db_interface method
        success = self.db_interface.upsert_candidate(candidate_doc)

        if success:
            logger.info(f"Successfully upserted candidate '{name}' (Phone: {phone}) into database.")
        else:
            logger.error(f"Failed to upsert candidate '{name}' (Phone: {phone}) into database.")

        return success

# Example Usage (for testing or integration)
if __name__ == '__main__':
    # This requires a running MongoDB instance and the db_interface to be connectable
    # Also needs candidate data and a path

    # Configure logging for testing this module directly
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    if db_interface.is_connected():
        print("\n--- Testing DbUpdater ---")
        updater = DbUpdater(db_interface)

        # Dummy data (replace with realistic data)
        dummy_data_1 = {
            'name': '测试候选人1',
            'phone': '13800138001',
            'email': 'test1@example.com',
            'extracted_info': {
                'summary': 'Summary for test 1',
                'experience': [],
                'education': [],
                'skills': ['Python', 'Testing']
            }
            # 'query_tags': {} # Let the function generate placeholder tags
        }
        dummy_path_1 = Path('/path/to/processed_resumes/测试候选人1001.pdf')

        print(f"\nAttempting upsert for: {dummy_data_1['name']}")
        success1 = updater.upsert_candidate(dummy_data_1, dummy_path_1)
        print(f"Upsert 1 successful: {success1}")

        # Test update
        dummy_data_1_update = {
            'name': '测试候选人1', # Same name/phone for update
            'phone': '13800138001',
            'email': 'test1_updated@example.com', # Updated email
            'extracted_info': {
                'summary': 'Updated summary for test 1',
                'experience': [],
                'education': [],
                'skills': ['Python', 'Testing', 'MongoDB'] # Added skill
            }
        }
        dummy_path_1_updated = Path('/path/to/processed_resumes/测试候选人1001_v2.pdf') # Path might change

        print(f"\nAttempting update for: {dummy_data_1_update['name']}")
        success_update = updater.upsert_candidate(dummy_data_1_update, dummy_path_1_updated)
        print(f"Update successful: {success_update}")

         # Test missing essential info
        dummy_data_invalid = {
            'name': '无效候选人',
            # 'phone': '139invalid',
            'email': 'invalid@example.com'
        }
        dummy_path_invalid = Path('/path/to/processed/无效候选人.pdf')
        print(f"\nAttempting upsert with missing info for: {dummy_data_invalid['name']}")
        success_invalid = updater.upsert_candidate(dummy_data_invalid, dummy_path_invalid)
        print(f"Upsert invalid successful: {success_invalid}") # Should be False
        assert not success_invalid

    else:
        print("Database not connected. Skipping DbUpdater tests.") 