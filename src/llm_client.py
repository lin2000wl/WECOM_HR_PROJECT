from openai import OpenAI, APIError, RateLimitError, APITimeoutError, APIConnectionError, AuthenticationError
import json
import time
from typing import List, Dict
import re

from src import config_ew # 修改导入
from .logger import logger # 假设 logger 在同级目录的 logger.py 中，或者调整为 from src.logger import logger

class LLMClient:
    """封装对 DeepSeek LLM API 的调用。"""

    def __init__(self):
        self.api_key = config_ew.DEEPSEEK_API_KEY
        self.base_url = config_ew.DEEPSEEK_API_BASE
        self.query_model = config_ew.LLM_QUERY_MODEL
        self.resume_model = config_ew.LLM_RESUME_MODEL
        self.summary_model = config_ew.LLM_SUMMARY_MODEL # 新增摘要模型配置
        
        if not self.api_key or self.api_key == "YOUR_DEEPSEEK_API_KEY": # 兼容旧的硬编码检查，尽管现在不太可能出现
            logger.critical("DeepSeek API Key 未配置或无效！请检查 .env 文件和 src/config_ew.py。")
            self.client = None
        else:
            try:
                self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
                logger.info(f"LLMClient 初始化成功，API Base: {self.base_url}, Models: query='{self.query_model}', resume='{self.resume_model}', summary='{self.summary_model}'")
            except Exception as e:
                logger.critical(f"初始化 OpenAI 客户端失败: {e}", exc_info=True)
                self.client = None

    def _call_llm(self, model: str, messages: list, max_retries: int = 3, initial_delay: float = 1.0) -> str | None:
        """调用 LLM API 的私有方法，包含重试逻辑。"""
        if not self.client:
            logger.error("LLM Client 未初始化，无法调用 API。")
            return None

        retries = 0
        delay = initial_delay
        while retries < max_retries:
            try:
                logger.debug(f"向模型 '{model}' 发送请求: {messages}")
                response = self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    stream=False, # PRD 要求结构化数据，非流式更方便
                    temperature=0.1, # 可以调整 temperature 以获得更确定性的输出
                )
                content = response.choices[0].message.content
                logger.debug(f"收到模型 '{model}' 的响应: {content}")
                return content
            except RateLimitError as e:
                retries += 1
                logger.warning(f"API 速率限制，第 {retries}/{max_retries} 次重试将在 {delay:.2f} 秒后进行... Error: {e}")
                time.sleep(delay)
                delay *= 2 # 指数退避
            except (APITimeoutError, APIConnectionError) as e:
                retries += 1
                logger.warning(f"API 连接或超时错误，第 {retries}/{max_retries} 次重试将在 {delay:.2f} 秒后进行... Error: {e}")
                time.sleep(delay)
                delay *= 2
            except AuthenticationError as e:
                logger.error(f"API 认证失败: {e}")
                return None
            except APIError as e:
                logger.error(f"API 返回错误 (非速率/连接/认证问题): {e}")
                return None
            except Exception as e:
                logger.error(f"调用 LLM API 时发生未知错误: {e}", exc_info=True)
                return None
        
        logger.error(f"调用 LLM API 达到最大重试次数 ({max_retries}) 后仍然失败。")
        return None

    def parse_query_intent(self, user_query: str) -> dict | None:
        """
        使用 LLM 解析用户查询意图，提取结构化信息。

        Args:
            user_query (str): 用户的原始查询文本。

        Returns:
            dict | None: 包含提取信息的字典，如果解析失败则返回 None。
                         预期字典结构: {
                             "position": "xxx",
                             "experience_years_min": 5,
                             "experience_years_max": 10,
                             "skills": ["a", "b"],
                             "location": "xxx",
                             "education": "xxx",
                             "certifications": [{"name": "xxx", "level_keyword": "xxx", "modifier": "xxx"}, ...]
                         }
                         (具体字段根据 Prompt 设计)
        """
        # --- New Enhanced Prompt (v3.2 for v1.2 common level update) ---
        # Use triple quotes instead of parentheses for the multi-line string
        system_prompt = """你是一个智能招聘助手，负责解析招聘人员输入的自然语言查询指令。

任务：从用户输入的消息中，提取招聘职位的关键要求，并以 JSON 格式返回。你需要识别以下字段：
- position: 职位名称 (字符串)。如果未明确提及，返回 null。
- experience_years_min: 最低工作年限要求 (整数)。如果未提及，返回 null。
- experience_years_max: 最高工作年限要求 (整数)。如果未提及，返回 null。
- skills: 技能关键词列表 (字符串列表)。如果未提及，返回空列表 []。
- location: 工作地点 (字符串)。如果未提及，返回 null。
- education_levels: 学历要求列表 (字符串列表)。可能的学历等级（从低到高）：大专, 本科, 硕士, 博士。
  - 如果用户指定单个等级（如"硕士"），列表中只包含该等级 ["硕士"]。
  - 如果用户指定范围（如"本科及以上"、"至少本科"），则包含所有符合条件的等级，例如 ["本科", "硕士", "博士"]。
  - 如果用户指定范围（如"硕士及以下"），则包含所有符合条件的等级，例如 ["大专", "本科", "硕士"]。
  - 如果未提及，返回空列表 []。
- certifications: 要求的资格证书列表 (**对象列表**)。每个对象应包含:
    - 'name': 证书的**基础名称** (字符串, 例如 "工程师", "建造师", "PMP")。
    - 'level_keyword': **等级关键词** (字符串, 例如 "中级", "二级", "高级", "助理")。如果证书没有明确的等级或无法识别，返回 null。
    - 'modifier': **等级范围修饰符** (字符串: 'ge' 表示 >=, 'gt' 表示 >, 'eq' 表示 ==)。如果用户未明确指定等级范围或证书无等级，通常返回 'eq' 或 null。
  如果未提及任何证书，返回空列表 []。
- previous_companies: 曾在哪些公司工作过 (字符串列表)。如果未提及，返回空列表 []。
- design_category: 设计专业领域 (字符串)。请识别用户是否明确提到了 ['建筑设计', '电气设计', '给排水设计'] 中的一个。如果提及，返回对应的类别名称；如果没有提及，返回 null。

**重要提示关于证书解析：**
*   请尽力将证书名称拆分为 **基础名称** 和 **等级关键词**。例如，"中级建筑师" 应该解析为 `name: "建筑师", level_keyword: "中级"`。
*   如果证书名称本身不包含明确的等级关键词（如 "PMP", "注册安全工程师"），则 `level_keyword` 应为 `null`。
*   常见的等级关键词包括：助理, 初级, 中级, 高级, 一级, 二级, 三级。

- previous_companies: 曾在哪些公司工作过 (字符串列表)。如果未提及，返回空列表 []。
- design_category: 设计专业领域 (字符串)。请识别用户是否明确提到了 ['建筑设计', '电气设计', '给排水设计'] 中的一个。如果提及，返回对应的类别名称；如果没有提及，返回 null。

请严格按照以下 JSON 格式输出，即使某个字段未提取到，也要保留该字段，值为 null 或 []。
{
  "position": "...",
  "experience_years_min": ...,
  "experience_years_max": ...,
  "skills": [...],
  "location": "...",
  "education_levels": [...],
  "certifications": [{"name": "...", "level_keyword": "...", "modifier": "..."}, ...],
  "previous_companies": [...],
  "design_category": "..."
}

只输出 JSON 对象，不要包含任何额外的解释或说明文字。

下面是一些例子：

用户输入: "找一个上海地区的 Java 开发，至少 3 年经验，要会 Spring Boot 和 MySQL，有 PMP 证书优先"
助手输出:
{
  "position": "Java 开发",
  "experience_years_min": 3,
  "experience_years_max": null,
  "skills": ["Spring Boot", "MySQL"],
  "location": "上海",
  "education_levels": [],
  "certifications": [{"name": "PMP", "level_keyword": null, "modifier": "eq"}],
  "previous_companies": [],
  "design_category": null
}

用户输入: "有没有 5 到 8 年经验的 UI 设计师，北京的，本科以上，需要注册设计师证"
助手输出:
{
  "position": "UI 设计师",
  "experience_years_min": 5,
  "experience_years_max": 8,
  "skills": [],
  "location": "北京",
  "education_levels": ["本科", "硕士", "博士"],
  "certifications": [{"name": "注册设计师证", "level_keyword": null, "modifier": "eq"}],
  "previous_companies": [],
  "design_category": null
}

用户输入: "硕士学历，做过恒大项目的电气工程师，要求中级工程师及以上"
助手输出:
{
  "position": "电气工程师",
  "experience_years_min": null,
  "experience_years_max": null,
  "skills": [],
  "location": null,
  "education_levels": ["硕士"],
  "certifications": [{"name": "工程师", "level_keyword": "中级", "modifier": "ge"}],
  "previous_companies": ["恒大"],
  "design_category": "电气设计"
}

用户输入: "帮我找个建筑设计的，三年以上经验，要一级建造师"
助手输出:
{
  "position": null,
  "experience_years_min": 3,
  "experience_years_max": null,
  "skills": [],
  "location": null,
  "education_levels": [],
  "certifications": [{"name": "建造师", "level_keyword": "一级", "modifier": "eq"}],
  "previous_companies": [],
  "design_category": "建筑设计"
}
""" # End triple quotes

        messages = [
            {"role": "system", "content": system_prompt},
            # Add the user query placeholder to the prompt itself for clarity
            {"role": "user", "content": f"用户输入: {user_query}\n助手输出:"}
        ]

        response_content = self._call_llm(self.query_model, messages)

        if not response_content:
            return None

        try:
            # 尝试解析 JSON
            parsed_json = json.loads(response_content)
            # 基本校验：确保是字典，且包含预期的键 (或者为空字典)
            if not isinstance(parsed_json, dict):
                 logger.error(f"LLM 返回的不是有效的 JSON 对象: {response_content}")
                 return None
            if not parsed_json: # 处理空字典 {} 的情况
                logger.info("LLM 判断用户输入与招聘无关或无法解析有效信息。")
                return {} # 返回空字典表示未解析出有效信息
            
            # 可选：进一步校验字段类型
            # ... 
            
            logger.info(f"成功解析用户查询 '{user_query}' 为: {parsed_json}")
            return parsed_json
        except json.JSONDecodeError:
            logger.error(f"无法解析 LLM 返回的 JSON: {response_content}")
            return None
        except Exception as e:
             logger.error(f"处理 LLM 响应时发生错误: {e}", exc_info=True)
             return None

    def parse_resume(self, resume_text: str) -> dict | None:
        """
        使用 LLM 从简历文本中提取结构化信息。

        Args:
            resume_text (str): 从 PDF 中提取的简历文本。

        Returns:
            dict | None: 包含提取信息的字典，如果解析失败则返回 None。
                         预期字典结构 (参考 architecture.mdc):
                         {
                             "name": "...",
                             "phone": "...",
                             "email": "...",
                             "design_category": "...", // v1.2 新增
                             "extracted_info": {
                                 "summary": "...",
                                 "current_location": "...", // v1.2 新增
                                 "experience": [...],
                                 "education": [...],
                                 "skills": [...],
                                 "certifications": [{"name": "...", "level_keyword": "..."}, ...] // v1.2 修改结构
                             }
                         }
                         (具体字段根据 Prompt 设计)
        """
        # --- New Enhanced Resume Parsing Prompt --- 
        # --- Prompt v2 for v1.2 common level update ---
        # Use triple quotes for easier multi-line string definition
        system_prompt = """你是一个高度精确的简历解析引擎。你的任务是从提供的简历文本中提取详细的结构化信息，并严格按照指定的 JSON 格式返回。

**首要目标：** 提取候选人的核心信息和详细履历。
**新增目标：** 根据简历内容判断候选人的主要专业领域，具体分类为 '建筑设计', '电气设计', '给排水设计'。

**输出 JSON 结构：**
请务必按照以下结构组织你的输出。如果某项信息在简历中未找到，请将对应字段的值设为 `null` (对于字符串/对象) 或空列表 `[]` (对于数组)。

{
  "name": "...",           // 字符串，候选人姓名。必须提取。找不到则为 null。
  "phone": "...",          // 字符串，候选人手机号码。必须提取。找不到则为 null。
  "email": "...",          // 字符串，候选人邮箱。找不到则为 null。
  "design_category": "...", // 新增: 字符串，候选人主要专业领域。请从 ['建筑设计', '电气设计', '给排水设计'] 中选择一个。如果无法判断或不属于这三类，返回 null。
  "extracted_info": {
    "summary": "...",      // 字符串，个人评价、职业目标或技能总结。找不到则为 null。
    "current_location": "...", // 新增：字符串，候选人当前所在城市或地址。找不到则为 null。
    "experience": [        // JSON 数组，包含所有工作经历。找不到则为 []。
      {
        "company": "...",  // 字符串，公司名称。
        "title": "...",    // 字符串，职位名称。
        "start_date": "...", // 字符串，开始日期。优先使用 YYYY-MM 格式。若只有年份，使用 YYYY。找不到则为 null。
        "end_date": "...",   // 字符串，结束日期。优先使用 YYYY-MM 格式。若只有年份，使用 YYYY。如果写的是"至今"或类似，也返回 "至今"。找不到则为 null。
        "description": "..." // 字符串，工作职责描述。
      }
      // ... 更多工作经历对象
    ],
    "education": [         // JSON 数组，包含所有教育背景。找不到则为 []。
      {
        "school": "...",   // 字符串，学校名称。
        "degree": "...",   // 字符串，学位 (例如 "本科", "硕士", "博士")。
        "major": "...",    // 字符串，专业名称。
        "start_date": "...", // 字符串，开始日期。优先使用 YYYY-MM 格式。若只有年份，使用 YYYY。找不到则为 null。
        "end_date": "..."    // 字符串，结束日期。优先使用 YYYY-MM 格式。若只有年份，使用 YYYY。找不到则为 null。
      }
      // ... 更多教育背景对象
    ],
    "skills": [...],        // 字符串数组，包含简历中明确提到的所有技能关键词。找不到则为 []。
    "certifications": [    // **v1.2 修改**: 对象数组，包含证书基础名称和等级关键词。
      {
        "name": "...",       // 字符串，证书的**基础名称** (例如 "工程师", "建造师", "PMP")。
        "level_keyword": "..." // 字符串，识别出的**等级关键词** (例如 "中级", "二级", "高级")。如果无等级或无法识别，为 null。
      }
      // ... 更多证书对象
    ]
    // 可以考虑未来增加其他字段，如 "projects", "languages", "awards" 等
  }
}

**重要指令：**
1. **姓名 (`name`) 和手机号 (`phone`) 是最关键的信息，必须尽力提取。**
2. 当前地址 (`current_location`) 请提取简历中明确提到的候选人所在地信息，通常是城市。
3. **资格证书 (`certifications`)**: 请尽力将每个证书拆分为 **基础名称 (`name`)** 和 **等级关键词 (`level_keyword`)**。如果证书本身不包含等级（如 PMP）或无法识别等级，`level_keyword` 应为 `null`。常见的等级关键词有：助理, 初级, 中级, 高级, 一级, 二级, 三级。
4. 日期尽量标准化为 "YYYY-MM" 或 "YYYY"。对于当前仍在进行的工作或学习，结束日期用 "至今"。
5. 工作经历和教育背景应包含所有在简历中找到的条目。
6. 技能列表应包含所有明确提及的技术、工具、语言或其他专业技能。
7. **只输出 JSON 对象，不要包含任何 JSON 代码块标记 (```json ... ```) 或其他解释性文字。**

**示例：**

**输入简历片段:**
```
王五
联系电话: 13912345678
邮箱: wangwu@email.com

教育背景
2010年9月 - 2014年6月  XX大学  计算机科学与技术  学士

工作经验
2017.03 - 至今  ABC 科技有限公司  高级后端开发工程师
负责支付网关开发，使用 Python (Flask), Docker, MySQL。
持有 PMP 证书。

2014/07 - 2017/02  DEF 软件公司  软件工程师 (中级)
参与开发 CRM 系统，技术栈 Java, Spring。

技能: Python, Flask, Docker, MySQL, Java, Spring, Git
证书: PMP, 中级软件工程师认证
```

**助手输出:**
```json
{
  "name": "王五",
  "phone": "13912345678",
  "email": "wangwu@email.com",
  "design_category": null, // 假设无法判断
  "extracted_info": {
    "summary": null,
    "current_location": null, // 假设简历未提供
    "experience": [
      {
        "company": "ABC 科技有限公司",
        "title": "高级后端开发工程师", // 职位名称保持原文
        "start_date": "2017-03",
        "end_date": "至今",
        "description": "负责支付网关开发，使用 Python (Flask), Docker, MySQL。持有 PMP 证书。"
      },
      {
        "company": "DEF 软件公司",
        "title": "软件工程师 (中级)", // 职位名称保持原文
        "start_date": "2014-07",
        "end_date": "2017-02",
        "description": "参与开发 CRM 系统，技术栈 Java, Spring。"
      }
    ],
    "education": [
      {
        "school": "XX大学",
        "degree": "学士",
        "major": "计算机科学与技术",
        "start_date": "2010-09",
        "end_date": "2014-06"
      }
    ],
    "skills": ["Python", "Flask", "Docker", "MySQL", "Java", "Spring", "Git"],
    "certifications": [
      {"name": "PMP", "level_keyword": null},
      {"name": "软件工程师认证", "level_keyword": "中级"} // LLM 尝试拆分
    ]
  }
}
```

**现在，请处理以下简历文本：**
"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": resume_text} # Pass the resume text directly
        ]

        response_content = self._call_llm(self.resume_model, messages)

        if not response_content:
            return None

        # --- Added cleanup for potential markdown code block --- 
        cleaned_content = response_content.strip()
        if cleaned_content.startswith("```json"):
            # Remove ```json prefix
            cleaned_content = cleaned_content[len("```json"):].strip()
        if cleaned_content.startswith("```"):
            # Remove ``` prefix (in case language wasn't specified)
            cleaned_content = cleaned_content[len("```"):].strip()
        if cleaned_content.endswith("```"):
            # Remove ``` suffix
            cleaned_content = cleaned_content[:-len("```")].strip()
        # --- End cleanup --- 
            
        try:
            # Parse the cleaned content
            parsed_json = json.loads(cleaned_content)
            
            # Basic validation (ensure it's a dictionary)
            if not isinstance(parsed_json, dict):
                 logger.error(f"LLM 返回的不是有效的 JSON 对象 (清理后): {cleaned_content}")
                 return None
            
            # Crucial check: Ensure name and phone are extracted
            # This check might be redundant if validator handles it, but good for early exit
            name = parsed_json.get("name")
            phone = parsed_json.get("phone")
            if not name or not isinstance(name, str) or not name.strip() \
               or not phone or not isinstance(phone, str) or not phone.strip():
                 logger.warning(f"LLM 解析结果缺少有效的姓名或手机号。Name: '{name}', Phone: '{phone}'. 原始响应 (清理后): {cleaned_content}")
                 # Return None to indicate failure to the pipeline trigger
                 return None 

            logger.info(f"成功解析简历。姓名: {name}") # Use extracted name
            return parsed_json
        except json.JSONDecodeError as e:
            logger.error(f"无法解析 LLM 返回的 JSON (清理后): {cleaned_content}。错误: {e}")
            return None
        except Exception as e:
             logger.error(f"处理 LLM 简历响应时发生错误: {e}", exc_info=True)
             return None

    # --- New method for Brief Comparison Summary --- 
    def get_brief_comparison_summary(self, query_criteria: dict, candidates_info: List[Dict]) -> str | None:
        """
        为当前批次的候选人生成简要的对比分析摘要。

        Args:
            query_criteria (dict): 用户原始查询解析后的条件。
            candidates_info (List[Dict]): 候选人关键信息列表 (例如，从 extracted_info 中提取)。

        Returns:
            str | None: 生成的摘要文本，如果失败则返回 None。
        """
        if not self.client:
            logger.error("LLM Client 未初始化，无法生成摘要。")
            return None
        if not candidates_info:
            logger.info("候选人列表为空，无需生成摘要。")
            return ""

        # 构建 Prompt
        # Example: query_criteria might be {'position': '软件工程师', 'skills': ['Python', 'FastAPI']}
        # Example: candidates_info might be [{'name':'张三', 'summary':'经验丰富...'}, {'name':'李四', 'summary':'技术栈匹配...'}]
        
        query_details = f"招聘目标：\n"
        if query_criteria.get('position'):
            query_details += f"  职位: {query_criteria.get('position')}\n"
        if query_criteria.get('experience_years_min') is not None:
            query_details += f"  最低经验: {query_criteria.get('experience_years_min')}年\n"
        if query_criteria.get('skills'):
            query_details += f"  关键技能: {', '.join(query_criteria.get('skills'))}\n"
        if query_criteria.get('education_levels'):
            query_details += f"  学历要求: {', '.join(query_criteria.get('education_levels'))}\n"
        if query_criteria.get('certifications'):
            certs = [c.get('name','') + (' (' + c.get('level_keyword','') + ')' if c.get('level_keyword') else '') 
                     for c in query_criteria.get('certifications')]
            query_details += f"  证书要求: {', '.join(filter(None, certs))}\n"
        if query_criteria.get('previous_companies'):
            query_details += f"  公司经验: {', '.join(query_criteria.get('previous_companies'))}\n"

        candidates_summary_text = "\n候选人列表：\n"
        for i, candidate in enumerate(candidates_info, 1):
            # 安全获取候选人基本信息
            cand_name = candidate.get('name', f'候选人{i}')
            info = candidate.get('extracted_info') or {}  # 避免 None 导致的属性错误
            cand_summary = info.get('summary') or '暂无摘要'
            cand_skills = info.get('skills') or []
            cand_experience_detail = info.get('experience') or []
            total_experience_years = 0 # This would need a utility to calculate from experience list
            # For simplicity, we might just list titles or key experiences here
            
            candidates_summary_text += f"{i}. {cand_name}:\n"
            candidates_summary_text += f"   摘要: {cand_summary[:100] + '...' if len(cand_summary) > 100 else cand_summary}\n" # 限制摘要长度
            if cand_skills:
                candidates_summary_text += f"   技能: {', '.join(cand_skills[:5])}\n" # 最多显示5个技能
            # Add more relevant fields if needed

        system_prompt = """你是一位资深的招聘顾问。
你的任务是根据招聘目标和候选人列表，为招聘人员提供一份简明扼要的对比分析摘要。
请重点突出每位候选人与招聘目标的核心匹配点或显著差异。
摘要应该帮助招聘人员快速判断哪些候选人值得优先关注。
语言风格应专业、客观、精炼。总字数控制在200字以内。"""
        
        user_content = f"{query_details}\n{candidates_summary_text}\n请为以上候选人生成一份对比分析摘要："

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]

        summary_text = self._call_llm(self.summary_model, messages) # 使用 summary_model

        if summary_text:
            logger.info(f"成功为查询生成了对比分析摘要。")
            return summary_text.strip()
        else:
            logger.warning(f"未能为查询生成对比分析摘要。")
            return "无法自动生成候选人对比摘要。"

# 创建全局 LLMClient 实例
llm_client = LLMClient()

if __name__ == '__main__':
    # --- 运行此示例前，请确保 config.yaml 中配置了有效的 DeepSeek API Key --- 
    if not llm_client.client:
        logger.error("LLM Client 未成功初始化，无法运行示例。请检查 API Key 配置和网络连接。")
    else:
        logger.info("运行 LLMClient 示例...")

        # 示例 1: 解析招聘查询
        print("\n--- 测试查询解析 --- H")
        query1 = "找一个有3年工作经验的Python后端开发，会Django和Flask" 
        result1 = llm_client.parse_query_intent(query1)
        print(f"查询: {query1}\n解析结果: {result1}")
        
        query2 = "有没有高级产品经理的机会，需要带过团队"
        result2 = llm_client.parse_query_intent(query2)
        print(f"查询: {query2}\n解析结果: {result2}")

        query3 = "今天天气怎么样"
        result3 = llm_client.parse_query_intent(query3)
        print(f"查询: {query3}\n解析结果: {result3}")

        # 示例 2: 解析简历文本 (需要一段模拟的简历文本)
        print("\n--- 测试简历解析 --- H")
        sample_resume_text = """
        张三
        手机：13800138000 | 邮箱：zhangsan@example.com

        个人总结
        资深软件工程师，拥有超过8年的后端开发经验，熟悉分布式系统设计。

        工作经历
        2018.07 - 至今    某某科技有限公司    高级软件工程师
        * 负责核心交易系统的设计与开发。
        * 使用 Java, Spring Boot, Kafka, MySQL 等技术。
        * 带领小组完成多个项目。

        2015.03 - 2018.06  某互联网公司    软件工程师
        * 参与电商后台模块开发。
        * 技术栈：Python, Django, PostgreSQL。

        教育背景
        2011.09 - 2015.06  某某大学    计算机科学与技术    学士

        技能
        编程语言：Java, Python
        框架：Spring Boot, Django
        数据库：MySQL, PostgreSQL, Redis
        其他：Kafka, Docker, Git
        """
        resume_result = llm_client.parse_resume(sample_resume_text)
        # 为了清晰，只打印部分结果
        if resume_result:
             print(f"简历解析姓名: {resume_result.get('name')}")
             print(f"简历解析手机: {resume_result.get('phone')}")
             print(f"简历解析技能: {resume_result.get('skills')}")
             print(f"简历解析第一份工作公司: {resume_result.get('experience')[0].get('company') if resume_result.get('experience') else 'N/A'}")
        else:
            print("简历解析失败。") 