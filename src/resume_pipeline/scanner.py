import os
from typing import List

from ..config import get_paths_config
from ..logger import logger

def scan_data_directory() -> List[str]:
    """
    扫描配置的 data 目录，查找所有 PDF 文件。

    Returns:
        List[str]: 找到的 PDF 文件的绝对路径列表。
    """
    paths_config = get_paths_config()
    data_dir = paths_config.get("data_dir", "data/") # 默认为 "data/"
    
    # 确保我们处理的是绝对路径，以避免歧义
    abs_data_dir = os.path.abspath(data_dir)
    
    pdf_files = []

    if not os.path.exists(abs_data_dir) or not os.path.isdir(abs_data_dir):
        logger.error(f"简历数据目录 '{abs_data_dir}' 不存在或不是一个有效的目录。请检查配置或创建目录。")
        return pdf_files # 返回空列表

    logger.info(f"开始扫描简历目录: {abs_data_dir}")
    try:
        for filename in os.listdir(abs_data_dir):
            # 检查文件是否是 PDF 文件 (忽略大小写)
            if filename.lower().endswith(".pdf"):
                file_path = os.path.join(abs_data_dir, filename)
                # 确保它是一个文件而不是子目录（虽然 listdir 通常不返回 . 和 ..）
                if os.path.isfile(file_path):
                    pdf_files.append(file_path)
                    logger.debug(f"找到待处理 PDF 文件: {file_path}")
    except OSError as e:
        logger.error(f"扫描目录 '{abs_data_dir}' 时发生 OS 错误: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"扫描目录 '{abs_data_dir}' 时发生未知错误: {e}", exc_info=True)

    logger.info(f"在 '{abs_data_dir}' 中找到 {len(pdf_files)} 个 PDF 文件。")
    return pdf_files

if __name__ == '__main__':
    # 运行此示例需要存在 data/ 目录，可以在其中放一些测试 pdf 文件
    # 确保 config.yaml 文件在项目根目录
    print("--- 测试简历目录扫描 --- H")
    # 确保 data 目录存在用于测试
    if not os.path.exists("data"):
        try:
            os.makedirs("data")
            print("创建了 data/ 目录用于测试。请在该目录放入 PDF 文件。")
            # 可以创建一些假的 pdf 文件用于测试
            with open("data/test1.pdf", "w") as f: f.write("dummy pdf")
            with open("data/Test2.PDF", "w") as f: f.write("dummy pdf 2")
            with open("data/not_a_pdf.txt", "w") as f: f.write("text file")
        except Exception as e:
            print(f"创建测试目录或文件失败: {e}")
            
    found_files = scan_data_directory()
    if found_files:
        print("找到的 PDF 文件:")
        for f in found_files:
            print(f"  - {f}")
    else:
        print("未找到 PDF 文件或扫描出错。")

    # 清理测试文件 (可选)
    # import shutil
    # if os.path.exists("data"): 
    #     try: shutil.rmtree("data")
    #     except: pass 