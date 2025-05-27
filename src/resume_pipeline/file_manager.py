import os
import shutil
import logging
from pathlib import Path
from src.config import get_paths_config

logger = logging.getLogger(__name__)

class FileManager:
    def __init__(self):
        # Get config directly using the helper function
        paths_config = get_paths_config()
        self.data_dir = Path(paths_config.get('data_dir', 'data'))
        self.processed_dir = Path(paths_config.get('processed_dir', 'processed_resumes'))
        self.error_dir = Path(paths_config.get('error_dir', 'data/error'))
        self.pending_dir = Path(paths_config.get('pending_dir', 'data/pending'))

        # Ensure target directories exist
        self._ensure_dirs_exist()

    def _ensure_dirs_exist(self):
        """Create the target directories if they don't exist."""
        try:
            self.processed_dir.mkdir(parents=True, exist_ok=True)
            self.error_dir.mkdir(parents=True, exist_ok=True)
            self.pending_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Ensured directories exist: {self.processed_dir}, {self.error_dir}, {self.pending_dir}")
        except OSError as e:
            logger.error(f"Error creating directories: {e}", exc_info=True)
            raise  # Re-raise the exception as this is critical

    def move_to_processed(self, original_path: Path, standardized_filename: str) -> Path | None:
        """
        Moves the file to the processed directory with the standardized filename.

        Args:
            original_path: The original path of the resume PDF.
            standardized_filename: The new filename (e.g., '姓名手机号后四位.pdf').

        Returns:
            The new path in the processed directory if successful, None otherwise.
        """
        target_path = self.processed_dir / standardized_filename
        try:
            # Use shutil.move for cross-filesystem compatibility if needed
            shutil.move(str(original_path), str(target_path))
            logger.info(f"Successfully moved '{original_path}' to '{target_path}'")
            return target_path
        except (OSError, shutil.Error) as e:
            logger.error(f"Error moving file '{original_path}' to '{target_path}': {e}", exc_info=True)
            return None

    def move_to_error(self, original_path: Path, reason: str = "Unknown processing error") -> Path | None:
        """
        Moves the file to the error directory. Keeps the original filename.

        Args:
            original_path: The original path of the resume PDF.
            reason: A brief description of why the file is moved to error.

        Returns:
            The new path in the error directory if successful, None otherwise.
        """
        target_path = self.error_dir / original_path.name
        try:
            # Avoid overwriting existing error files with the same name by adding a suffix if necessary
            counter = 1
            base_name = target_path.stem
            suffix = target_path.suffix
            while target_path.exists():
                target_path = self.error_dir / f"{base_name}_err_{counter}{suffix}"
                counter += 1

            shutil.move(str(original_path), str(target_path))
            logger.warning(f"Moved '{original_path}' to error directory '{target_path}' due to: {reason}")
            return target_path
        except (OSError, shutil.Error) as e:
            logger.error(f"Error moving file '{original_path}' to error directory: {e}", exc_info=True)
            return None

    def move_to_pending(self, original_path: Path, reason: str = "Missing critical information") -> Path | None:
        """
        Moves the file to the pending directory. Keeps the original filename.

        Args:
            original_path: The original path of the resume PDF.
            reason: A brief description of why the file needs manual intervention.

        Returns:
            The new path in the pending directory if successful, None otherwise.
        """
        target_path = self.pending_dir / original_path.name
        try:
            # Avoid overwriting existing pending files with the same name
            counter = 1
            base_name = target_path.stem
            suffix = target_path.suffix
            while target_path.exists():
                target_path = self.pending_dir / f"{base_name}_pend_{counter}{suffix}"
                counter += 1

            shutil.move(str(original_path), str(target_path))
            logger.warning(f"Moved '{original_path}' to pending directory '{target_path}' for manual review due to: {reason}")
            return target_path
        except (OSError, shutil.Error) as e:
            logger.error(f"Error moving file '{original_path}' to pending directory: {e}", exc_info=True)
            return None

    def check_file_exists(self, file_path: Path) -> bool:
        """Checks if a file exists and is a file."""
        exists = file_path.is_file()
        if not exists:
            logger.warning(f"File not found or is not a file: {file_path}")
        return exists

# Example usage (for testing or integration):
if __name__ == '__main__':
    # This requires a config.yaml or equivalent setup
    # Example usage needs adjustment as it no longer takes config
    # You might need to ensure config is loaded globally before this runs
    # For simplicity, we comment out the old dummy config approach
    # class DummyConfig:
    #     def get(self, key, default=None):
    #         if key == 'data_dir': return 'temp_data'
    #         if key == 'processed_dir': return 'temp_processed'
    #         if key == 'error_dir': return 'temp_data/error'
    #         if key == 'pending_dir': return 'temp_data/pending'
    #         return default

    # config = DummyConfig()
    # fm = FileManager(config) # Old way
    
    # New way assumes global config is loaded via src.config import
    # Ensure config.yaml exists or create a dummy one for this test
    if not Path('config.yaml').exists():
        print("Creating dummy config.yaml for FileManager test...")
        with open('config.yaml', 'w') as f:
            f.write('''
paths:
  data_dir: temp_data
  processed_dir: temp_processed
  error_dir: temp_data/error
  pending_dir: temp_data/pending
''')
    
    # Now instantiate FileManager, it will load config internally
    fm = FileManager()

    # Create dummy directories and files for testing
    temp_data = fm.data_dir # Use fm internal paths
    temp_data.mkdir(parents=True, exist_ok=True)
    (temp_data / "resume1.pdf").touch()
    (temp_data / "resume2.pdf").touch()
    (temp_data / "resume3.pdf").touch()
    (temp_data / "resume4.pdf").touch() # For error handling test
    (temp_data / "resume5.pdf").touch() # For pending handling test
    fm.error_dir.mkdir(parents=True, exist_ok=True)
    fm.pending_dir.mkdir(parents=True, exist_ok=True)
    fm.processed_dir.mkdir(parents=True, exist_ok=True)

    print(f"Testing FileManager with paths: Data={fm.data_dir}, Processed={fm.processed_dir}, Error={fm.error_dir}, Pending={fm.pending_dir}")

    # Test moving to processed
    processed_path = fm.move_to_processed(temp_data / "resume1.pdf", "张三1234.pdf")
    if processed_path:
        print(f"Moved to processed: {processed_path}")
        assert processed_path.name == "张三1234.pdf"
        assert processed_path.parent.name == 'temp_processed'
        assert not (temp_data / "resume1.pdf").exists()

    # Test handling collision in processed (implicitly handled by shutil.move overwriting)
    (temp_data / "another_resume.pdf").touch()
    processed_path_collision = fm.move_to_processed(temp_data / "another_resume.pdf", "张三1234.pdf")
    if processed_path_collision:
         print(f"Overwrote processed file: {processed_path_collision}")
         assert processed_path_collision.name == "张三1234.pdf"

    # Test moving to error
    error_path = fm.move_to_error(temp_data / "resume2.pdf", "Failed OCR")
    if error_path:
        print(f"Moved to error: {error_path}")
        assert error_path.name == "resume2.pdf"
        assert error_path.parent.name == 'error'
        assert not (temp_data / "resume2.pdf").exists()

    # Test handling collision in error
    (temp_data / "resume2_again.pdf").touch() # Create a new file to move
    error_path_collision = fm.move_to_error(temp_data / "resume2_again.pdf", "Duplicate error")
    if error_path_collision:
        print(f"Moved to error with collision handling: {error_path_collision}")
        assert error_path_collision.name == "resume2_err_1.pdf" # Expecting suffix
        assert not (temp_data / "resume2_again.pdf").exists()


    # Test moving to pending
    pending_path = fm.move_to_pending(temp_data / "resume3.pdf", "Missing phone number")
    if pending_path:
        print(f"Moved to pending: {pending_path}")
        assert pending_path.name == "resume3.pdf"
        assert pending_path.parent.name == 'pending'
        assert not (temp_data / "resume3.pdf").exists()

     # Test handling collision in pending
    (temp_data / "resume3_again.pdf").touch() # Create a new file to move
    pending_path_collision = fm.move_to_pending(temp_data / "resume3_again.pdf", "Duplicate pending")
    if pending_path_collision:
        print(f"Moved to pending with collision handling: {pending_path_collision}")
        assert pending_path_collision.name == "resume3_pend_1.pdf" # Expecting suffix
        assert not (temp_data / "resume3_again.pdf").exists()


    # Test moving non-existent file (should log warning/error but not crash)
    print("\nTesting non-existent file move:")
    fm.move_to_processed(Path("non_existent.pdf"), "non_existent_processed.pdf")
    fm.move_to_error(Path("non_existent.pdf"), "Doesn't exist")
    fm.move_to_pending(Path("non_existent.pdf"), "Doesn't exist")

    # Clean up dummy files/dirs
    shutil.rmtree(temp_data)
    shutil.rmtree(fm.processed_dir)
    if Path('config.yaml').exists(): # Clean up dummy config if created
        # Check if it's the dummy one before deleting (optional, basic check here)
        with open('config.yaml', 'r') as f:
            content = f.read()
            if 'temp_data' in content:
                 os.remove('config.yaml')
                 print("Removed dummy config.yaml") 