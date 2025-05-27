from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from pydantic import BaseModel, Field, Extra

# 注意：以下模型是基础版本，字段可能需要在后续开发中根据 LLM 提取能力和具体需求进行调整。

@dataclass
class Experience:
    """Represents a single work experience entry."""
    company: Optional[str] = None
    title: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    description: Optional[str] = None

@dataclass
class Education:
    """Represents a single education entry."""
    school: Optional[str] = None
    degree: Optional[str] = None
    major: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None

# New dataclass for nested extracted information
class ExtractedInfo(BaseModel):
    """Structure for information extracted by LLM from resume text."""
    summary: Optional[str] = None
    current_location: Optional[str] = None # 新增：当前地址
    experience: List[Experience] = Field(default_factory=list)
    education: List[Education] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list) # 新增：资格证书列表
    # Consider adding other potential fields like projects, languages, awards here
    # if the resume parsing prompt is updated to extract them.

    class Config:
        extra = Extra.allow # Allow extra fields from LLM not explicitly defined

# New dataclass for query tags, aligned with validator output
class QueryTags(BaseModel):
    """Structure for tags used for database querying."""
    positions: List[str] = Field(default_factory=list)
    min_experience_years: Optional[int] = None
    skills_normalized: List[str] = Field(default_factory=list)
    location: Optional[str] = None # 新增：用于查询的地点标签
    certifications: List[str] = Field(default_factory=list) # 新增：用于查询的证书标签 (小写)
    schools: List[str] = Field(default_factory=list) # Added based on validator
    degrees: List[str] = Field(default_factory=list) # Added based on validator
    # Add other searchable tags as needed
    # e.g., education_level_normalized: Optional[str] = None
    #       schools: List[str] = Field(default_factory=list)

    class Config:
        extra = Extra.allow

@dataclass
class Candidate:
    """Main dataclass representing a candidate in the database."""
    # 关键识别信息
    name: Optional[str] = None # 姓名 (关键字段)
    phone: Optional[str] = None # 手机号 (关键字段)
    email: Optional[str] = None # 邮箱
    wxid: Optional[str] = None  # 候选人微信ID (可能需要手动关联或后续补充)
    external_wecom_id: Optional[str] = None # 候选人企业微信外部联系人ID

    # 简历文件信息
    resume_pdf_path: Optional[str] = None # 标准化后的简历文件路径 (关键字段)
    source_file_original_name: Optional[str] = None # (可选) 记录原始文件名

    # LLM 提取的结构化信息 (Stored as Dict for direct MongoDB compatibility)
    extracted_info: Optional[Dict[str, Any]] = None

    # 用于快速检索的标签 (Stored as Dict for direct MongoDB compatibility)
    query_tags: Optional[Dict[str, Any]] = None

    # 元数据
    last_processed_time: Optional[datetime] = None # 最后处理时间

    # MongoDB 自动管理的字段 (Optional, as it's managed by DB)
    _id: Optional[str] = None # MongoDB ObjectId (usually managed by MongoDB)

    # Helper methods remain largely the same, handling dicts for nested fields
    def to_dict(self) -> Dict:
        """将 Candidate 对象转换为可存储到 MongoDB 的字典。"""
        data = {
            "name": self.name,
            "phone": self.phone,
            "email": self.email,
            "wxid": self.wxid,
            "external_wecom_id": self.external_wecom_id,
            "resume_pdf_path": self.resume_pdf_path,
            "source_file_original_name": self.source_file_original_name,
            "extracted_info": self.extracted_info, # Store as dict
            "query_tags": self.query_tags,       # Store as dict
            "last_processed_time": self.last_processed_time,
        }
        # Add _id only if it exists (useful if updating based on existing obj)
        if self._id:
            data['_id'] = self._id
        # 移除值为 None 的字段，避免存入数据库
        return {k: v for k, v in data.items() if v is not None}

    @staticmethod
    def from_dict(data: Dict) -> 'Candidate':
        """从字典创建 Candidate 对象。"""
        # Handle potential ObjectId if using pymongo directly elsewhere
        object_id = data.get('_id')
        _id_str = str(object_id) if object_id else None

        candidate = Candidate(
            _id=_id_str,
            name=data.get('name'),
            phone=data.get('phone'),
            email=data.get('email'),
            wxid=data.get('wxid'),
            external_wecom_id=data.get('external_wecom_id'),
            resume_pdf_path=data.get('resume_pdf_path'),
            source_file_original_name=data.get('source_file_original_name'),
            extracted_info=data.get('extracted_info'), # Get the dict directly
            query_tags=data.get('query_tags'),       # Get the dict directly
            last_processed_time=data.get('last_processed_time')
        )
        return candidate

if __name__ == '__main__':
    # Updated example usage (optional)
    # Create example nested dictionaries
    exp1 = Experience(company='Test Inc.', title='Dev', start_date='2020-01', end_date='2022-12')
    edu1 = Education(school='Test Uni', degree='BS', major='CS')

    extracted_info_dict = {
        'summary': 'Test summary',
        'experience': [{'company': exp1.company, 'title': exp1.title, 'start_date': exp1.start_date, 'end_date': exp1.end_date, 'description': exp1.description}], # List of dicts
        'education': [{'school': edu1.school, 'degree': edu1.degree, 'major': edu1.major, 'start_date': edu1.start_date, 'end_date': edu1.end_date}], # List of dicts
        'skills': ['Testing', 'Python']
    }

    query_tags_dict = {
        'positions': ['Dev'],
        'min_experience_years': 2,
        'skills_normalized': ['testing', 'python'],
        'schools': ['Test Uni'],
        'degrees': ['BS']
    }

    cand_data = {
        'name': "测试员",
        'phone': "13600001111",
        'email': 'test@example.com',
        'resume_pdf_path': "processed_resumes/测试员1111.pdf",
        'extracted_info': extracted_info_dict,
        'query_tags': query_tags_dict,
        'last_processed_time': datetime.now(datetime.now().astimezone().tzinfo)
    }

    candidate_obj = Candidate.from_dict(cand_data)
    print("从字典创建的对象:", candidate_obj)
    print("\nExtracted Info:", candidate_obj.extracted_info)
    print("\nQuery Tags:", candidate_obj.query_tags)

    # Convert back to dictionary for storage
    candidate_dict_for_db = candidate_obj.to_dict()
    print("\n转换回字典 (用于存储):", candidate_dict_for_db)

    # Example of creating Candidate with nested dataclasses (if needed elsewhere)
    # extracted_info_obj = ExtractedInfo(
    #     summary=extracted_info_dict['summary'],
    #     experience=[Experience(**exp) for exp in extracted_info_dict['experience']],
    #     education=[Education(**edu) for edu in extracted_info_dict['education']],
    #     skills=extracted_info_dict['skills']
    # )
    # query_tags_obj = QueryTags(**query_tags_dict)
    # Direct creation like this might be useful for internal logic,
    # but Candidate stores the dict versions. 