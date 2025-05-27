import logging
import os
from .config import get_logging_config, get_paths_config

# v1.2.1 Define a custom filter for new certificate warnings
class NewCertificateFilter(logging.Filter):
    def filter(self, record):
        # Only allow log records containing this specific phrase
        return "发现待审核证书" in record.getMessage()

def setup_logger(name="hr_bot"):
    """
    Sets up the logger based on configuration.

    Args:
        name (str): The name of the logger.

    Returns:
        logging.Logger: The configured logger instance.
    """
    log_config = get_logging_config()
    log_level_str = log_config.get("level", "INFO").upper()
    log_file_name = log_config.get("file", "app.log")

    # Map string level to logging level constants
    log_level = getattr(logging, log_level_str, logging.INFO)

    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Avoid adding multiple handlers if logger already has them
    if not logger.handlers:
        # Create console handler
        ch = logging.StreamHandler()
        ch.setLevel(log_level)
        ch.setFormatter(formatter)
        logger.addHandler(ch)
        # Also add console handler to root logger to capture logs from all modules
        root_logger = logging.getLogger()
        root_logger.setLevel(log_level)
        root_logger.addHandler(ch)

        # Create file handler if log file is specified
        if log_file_name:
            # Ensure the directory for the log file exists if it's relative to a path
            # Assuming log file path is relative to the workspace root for simplicity
            # For robustness, consider using an absolute path or ensuring the root dir
            log_file_path = os.path.abspath(log_file_name)
            log_dir = os.path.dirname(log_file_path)
            if not os.path.exists(log_dir):
                try:
                    os.makedirs(log_dir)
                except OSError as e:
                    print(f"错误: 无法创建日志目录 {log_dir}: {e}")
                    # Optionally fall back to logging only to console
                    return logger # Return logger with console handler only

            fh = logging.FileHandler(log_file_path, encoding='utf-8')
            fh.setLevel(log_level)
            fh.setFormatter(formatter)
            logger.addHandler(fh)
            # Also add file handler to root logger
            root_logger.addHandler(fh)

        # v1.2.1 Add a dedicated handler for new certificate warnings
        new_cert_log_file = "logs/new_certificates.log" # Store in logs subdirectory
        new_cert_log_path = os.path.abspath(new_cert_log_file)
        new_cert_log_dir = os.path.dirname(new_cert_log_path)

        if not os.path.exists(new_cert_log_dir):
            try:
                os.makedirs(new_cert_log_dir)
                logger.info(f"创建待审核证书日志目录: {new_cert_log_dir}") # Use logger to log this
            except OSError as e:
                # Log error using the already configured main logger
                logger.error(f"无法创建待审核证书日志目录 {new_cert_log_dir}: {e}")
                # Don't add the handler if the directory fails to create
                pass
            except Exception as e: # Catch other potential errors during makedirs
                logger.error(f"创建目录 {new_cert_log_dir} 时发生未知错误: {e}")
                pass
        else:
            # Ensure directory creation check only happens once ideally
            pass # Directory already exists

        # Check again if dir exists before creating handler, in case of creation failure
        if os.path.exists(new_cert_log_dir):
            try:
                nch = logging.FileHandler(new_cert_log_path, encoding='utf-8')
                nch.setLevel(logging.WARNING) # Only capture WARNING level and above
                nch.setFormatter(formatter) # Use the same format
                # Add the custom filter
                nch.addFilter(NewCertificateFilter())
                logger.addHandler(nch)
                logger.info(f"已配置待审核证书日志记录到: {new_cert_log_path}")
            except Exception as e:
                logger.error(f"配置待审核证书日志处理器失败: {e}")

    return logger

# Get a globally accessible logger instance
logger = setup_logger()

if __name__ == '__main__':
    # Example usage:
    logger.debug("这是一条调试信息")
    logger.info("这是一条普通信息")
    logger.warning("这是一条警告信息")
    logger.error("这是一条错误信息")
    logger.critical("这是一条严重错误信息") 