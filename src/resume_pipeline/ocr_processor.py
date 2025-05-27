import pytesseract
from pdf2image import convert_from_path
from PIL import Image
import os
from typing import Optional
import io
from pathlib import Path
import sys

from ..logger import logger
from ..config import get_ocr_config # Import the getter

# --- Tesseract 配置 (如果 Tesseract 不在 PATH 中) ---
# try:
#     # 尝试从环境变量获取路径 (如果用户设置了)
#     tesseract_cmd_path = os.environ.get("TESSERACT_CMD")
#     if tesseract_cmd_path:
#         pytesseract.pytesseract.tesseract_cmd = tesseract_cmd_path
#         logger.info(f"使用环境变量 TESSERACT_CMD 指定的路径: {tesseract_cmd_path}")
#     else:
#         # 在 Windows 上的默认安装路径示例，需要根据实际情况修改
#         default_path = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
#         if os.path.exists(default_path):
#             pytesseract.pytesseract.tesseract_cmd = default_path
#             logger.info(f"自动检测到 Tesseract 路径: {default_path}")
#         # else: logger.warning("无法自动检测 Tesseract 路径，请确保 Tesseract 在系统 PATH 中或设置 TESSERACT_CMD 环境变量。")
# except Exception as e:
#     logger.error(f"配置 Tesseract 路径时出错: {e}")
# -----------------------------------------------------

# --- Poppler 配置 (如果 Poppler 不在 PATH 中) ---
# try:
#     poppler_path_env = os.environ.get("POPPLER_PATH") # 例如 C:\path\to\poppler-x.y.z\bin
#     if poppler_path_env:
#         logger.info(f"使用环境变量 POPPLER_PATH: {poppler_path_env}")
#     else:
#         # 如果不设置，pdf2image 会尝试在 PATH 中查找
#         logger.info("未设置 POPPLER_PATH 环境变量，将尝试从系统 PATH 中查找 Poppler。")
# except Exception as e:
#     logger.error(f"检查 Poppler 配置时出错: {e}")
# -----------------------------------------------------

class OcrProcessor:
    """Handles OCR processing for PDF files using Tesseract and pdf2image."""
    def __init__(self):
        ocr_config = get_ocr_config()
        self.tesseract_cmd = ocr_config.get('tesseract_cmd')
        self.poppler_path = ocr_config.get('poppler_path') # Get poppler_path from config
        self.ocr_languages = ocr_config.get('ocr_languages', 'chi_sim+eng')
        self.ocr_dpi = ocr_config.get('ocr_dpi', 300)
        
        self._configure_tesseract()
        
    def _configure_tesseract(self):
        """Configures the pytesseract command path if provided in config."""
        if self.tesseract_cmd and os.path.exists(self.tesseract_cmd):
            try:
                pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd
                logger.info("使用配置文件中指定的 Tesseract 路径: %s", self.tesseract_cmd)
            except Exception as e:
                logger.error("根据配置设置 Tesseract 路径时出错: %s", e)
        else:
             # Check if it's available in PATH
             try:
                 # Try getting version, if it fails, Tesseract is likely not in PATH
                 pytesseract.get_tesseract_version()
                 logger.info("Tesseract 在系统 PATH 中可用。")
             except pytesseract.TesseractNotFoundError:
                 logger.warning('配置文件中未指定 Tesseract 路径，并且无法在系统 PATH 中找到。OCR 功能可能不可用。')
             except Exception as e:
                 logger.error("检查 Tesseract 版本时出错: %s", e)

    def is_available(self) -> bool:
        """Checks if Tesseract seems to be configured and available."""
        try:
            # A simple check by getting the version string
            pytesseract.get_tesseract_version()
            # Additionally, check if pdf2image prerequisite (poppler) might be available
            # This is a basic check; poppler path is used directly in convert_from_path
            return True
        except pytesseract.TesseractNotFoundError:
            return False
        except Exception as e:
             logger.error('检查 Tesseract 可用性时出错: %s', e)
             return False

    def ocr_pdf(self, pdf_path: str) -> Optional[str]:
        """
        Performs OCR on a PDF file to extract text.
        Converts PDF pages to images and then uses Tesseract.

        Args:
            pdf_path (str): Absolute path to the PDF file.

        Returns:
            Optional[str]: Extracted text content, or None if failed.
        """
        logger.info("开始对 PDF 文件进行 OCR: %s", pdf_path)

        if not os.path.exists(pdf_path):
            logger.error("PDF 文件不存在，无法进行 OCR: %s", pdf_path)
            return None
            
        extracted_text = io.StringIO()
        images = []
        try:
            # Use configured poppler_path if available
            poppler_info = self.poppler_path or '从 PATH 查找'
            logger.debug("尝试使用 pdf2image 将 PDF 转换为图片 (DPI: %s, Poppler: %s)...", self.ocr_dpi, poppler_info)
            images = convert_from_path(pdf_path, dpi=self.ocr_dpi, poppler_path=self.poppler_path)
            logger.debug("成功将 PDF 转换为 %s 张图片。", len(images))

        except Exception as e:
            logger.error("使用 pdf2image 转换 PDF 时失败: %s。错误: %s", pdf_path, e, exc_info=True)
            poppler_path_msg = self.poppler_path or ''
            logger.error("请确保 Poppler 已安装并配置在系统 PATH 或 config.yaml 的 ocr.poppler_path ('%s') 中。", poppler_path_msg)
            return None
            
        if not images:
             logger.warning("pdf2image 未能从 %s 转换出任何图片。", pdf_path)
             return None

        logger.debug("开始使用 Tesseract 对 %s 张图片进行 OCR (语言: %s)...", len(images), self.ocr_languages)
        page_count = 0
        try:
            for i, image in enumerate(images):
                page_count = i + 1
                logger.debug("处理第 %s 页图片...", page_count)
                # Use configured languages
                page_text = pytesseract.image_to_string(image, lang=self.ocr_languages)
                if page_text:
                    extracted_text.write(page_text)
                    extracted_text.write("\n--- OCR Page Break ---\n")
                logger.debug("第 %s 页 OCR 完成。", page_count)
                image.close()
                
        except pytesseract.TesseractNotFoundError:
            tesseract_cmd_path = pytesseract.pytesseract.tesseract_cmd
            logger.critical("Tesseract 未安装或未在系统 PATH ('%s') 找到！请安装 Tesseract 并配置路径。", tesseract_cmd_path)
            return None
        except Exception as e:
            logger.error("执行 Tesseract OCR 时出错 (在第 %s 页): %s。错误: %s", page_count, pdf_path, e, exc_info=True)
        finally:
             for img in images: 
                 try: img.close() 
                 except: pass

        ocr_result = extracted_text.getvalue()
        extracted_text.close()

        if not ocr_result.strip():
            logger.warning("OCR 未能从 PDF 文件 '%s' 提取到任何文本。", pdf_path)
            return None

        logger.info("成功通过 OCR 从 PDF 文件 '%s' 提取文本 (长度: %s)。", pdf_path, len(ocr_result))
        return ocr_result

# Keep the __main__ block for standalone testing if needed
# Note: Standalone testing now requires a proper config.yaml or mocking get_ocr_config
if __name__ == '__main__':
    # Simplified __main__ for testing OcrProcessor instance
    print('--- Testing OcrProcessor ---')
    
    # Ensure config.yaml exists or create a dummy one for testing
    config_path = Path(__file__).resolve().parents[2] / 'config.yaml'
    if not config_path.exists():
         print(f"创建临时的 config.yaml 用于 OcrProcessor 测试...")
         with open(config_path, 'w', encoding='utf-8') as f:
             f.write('''
ocr:
  # tesseract_cmd: 'C:/Program Files/Tesseract-OCR/tesseract.exe' # 取消注释并修改为你的路径
  # poppler_path: 'C:/path/to/poppler-x.y.z/bin' # 取消注释并修改为你的路径
  ocr_languages: 'chi_sim+eng'
  ocr_dpi: 300
             ''')
    
    # Now we can instantiate OcrProcessor
    try:
         processor = OcrProcessor()
         print(f"OcrProcessor initialized. Tesseract available: {processor.is_available()}")
         print(f"Tesseract cmd: {pytesseract.pytesseract.tesseract_cmd}")
         print(f"Poppler path from config: {processor.poppler_path}")
         print(f"OCR Languages: {processor.ocr_languages}")
         print(f"OCR DPI: {processor.ocr_dpi}")

         if processor.is_available():
             # --- 测试 OCR 功能 --- 
             sample_pdf_path = "sample.pdf" # Needs a test PDF
             if not Path(sample_pdf_path).exists():
                 print(f"测试文件 '{sample_pdf_path}' 不存在。请准备一个 PDF 文件用于测试。")
             else:
                 print(f"\n对 '{sample_pdf_path}' 执行 OCR 测试...")
                 ocr_text = processor.ocr_pdf(os.path.abspath(sample_pdf_path))
                 if ocr_text:
                     print("\n--- OCR 提取到的文本 --- H")
                     print(ocr_text[:500] + ('...' if len(ocr_text) > 500 else '') )
                     print("--- OCR 文本结束 --- H")
                 else:
                     print("\nOCR 提取失败。请检查 Tesseract 和 Poppler 安装与配置。")
         else:
             print("Tesseract 不可用，跳过 OCR 功能测试。")
             
    except Exception as e:
         print(f"测试 OcrProcessor 时出错: {e}", file=sys.stderr)
         
    # Clean up dummy config if created?
    # Be careful not to delete user's actual config
    # if config_path.exists():
    #     with open(config_path, 'r') as f:
    #         content = f.read()
    #         if 'poppler-x.y.z' in content: # Heuristic check for dummy
    #              os.remove(config_path)
    #              print("Removed dummy config.yaml") 