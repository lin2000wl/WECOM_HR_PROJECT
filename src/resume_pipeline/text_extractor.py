import PyPDF2
from typing import Optional
import io
import os

from ..logger import logger

def extract_text_from_pdf(pdf_path: str) -> Optional[str]:
    """
    使用 PyPDF2 从 PDF 文件中提取文本。

    Args:
        pdf_path (str): PDF 文件的绝对路径。

    Returns:
        Optional[str]: 提取到的文本内容，如果失败则返回 None。
    """
    logger.info(f"开始从 PDF 文件提取文本: {pdf_path}")
    
    if not os.path.exists(pdf_path):
        logger.error(f"PDF 文件不存在: {pdf_path}")
        return None
        
    text_content = io.StringIO()
    try:
        with open(pdf_path, 'rb') as pdf_file:
            reader = PyPDF2.PdfReader(pdf_file)
            
            # 检查 PDF 是否被加密
            if reader.is_encrypted:
                try:
                    # 尝试使用空密码解密（常见的弱加密）
                    reader.decrypt('')
                    logger.info(f"PDF 文件 '{pdf_path}' 已使用空密码解密。")
                except Exception as decrypt_err:
                    logger.warning(f"无法解密受密码保护的 PDF 文件: {pdf_path}。错误: {decrypt_err}")
                    return None # 无法处理加密文件

            num_pages = len(reader.pages)
            logger.debug(f"PDF 文件共有 {num_pages} 页。")

            for page_num in range(num_pages):
                page = reader.pages[page_num]
                try:
                    page_text = page.extract_text()
                    # Strip the text before checking if it's empty or adding it
                    stripped_page_text = page_text.strip() if page_text else ""
                    if stripped_page_text:
                        # Write the original (unstripped) text + page break
                        text_content.write(page_text) 
                        text_content.write("\n--- Page Break ---\n") # 添加分页符
                except Exception as page_extract_err:
                    logger.warning(f"提取 PDF 文件 '{pdf_path}' 第 {page_num + 1} 页时出错: {page_extract_err}")
                    # 选择继续处理其他页面
                    continue 
                    
    except PyPDF2.errors.PdfReadError as e:
        logger.error(f"读取 PDF 文件时出错 (可能已损坏或格式不支持): {pdf_path}。错误: {e}")
        return None
    except OSError as e:
         logger.error(f"打开或读取 PDF 文件时发生 OS 错误: {pdf_path}。错误: {e}")
         return None
    except Exception as e:
        logger.error(f"提取 PDF 文本时发生未知错误: {pdf_path}。错误: {e}", exc_info=True)
        return None

    extracted_text = text_content.getvalue()
    text_content.close()
    
    if not extracted_text.strip():
        logger.warning(f"从 PDF 文件 '{pdf_path}' 提取到的文本为空或只包含空白符。可能需要 OCR。")
        # 返回空字符串，让后续步骤决定是否使用 OCR
        return "" 
    
    logger.info(f"成功从 PDF 文件 '{pdf_path}' 提取文本 (长度: {len(extracted_text)})。")
    return extracted_text

if __name__ == '__main__':
    # --- 运行此示例需要一个名为 sample.pdf 的 PDF 文件在当前目录 --- 
    print("--- 测试 PDF 文本提取 --- H")
    sample_pdf_path = "sample.pdf"

    # 创建一个简单的测试 PDF (如果不存在)
    if not os.path.exists(sample_pdf_path):
        try:
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import letter
            
            c = canvas.Canvas(sample_pdf_path, pagesize=letter)
            c.drawString(100, 750, "This is page 1 of the sample PDF.")
            c.drawString(100, 730, "Used for testing text extraction.")
            c.showPage() # 创建第二页
            c.drawString(100, 750, "This is page 2.")
            c.drawString(100, 730, "Hello, World!")
            c.save()
            print(f"创建了测试文件: {sample_pdf_path}")
            # 确保 reportlab 在 requirements.txt 中或已安装: pip install reportlab
        except ImportError:
             print("无法导入 reportlab 来创建测试 PDF。请手动创建 sample.pdf 或安装 reportlab。")
        except Exception as e:
            print(f"创建测试 PDF 时出错: {e}")

    if os.path.exists(sample_pdf_path):
        text = extract_text_from_pdf(os.path.abspath(sample_pdf_path))
        if text is not None:
            print("\n--- 提取到的文本 --- H")
            # 只打印前 500 个字符以避免过长输出
            print(text[:500] + ("..." if len(text) > 500 else ""))
            print("--- 文本结束 --- H")
        else:
            print("\n文本提取失败。")
        # 清理测试文件 (可选)
        # os.remove(sample_pdf_path)
    else:
        print(f"测试文件 {sample_pdf_path} 不存在，无法进行测试。") 