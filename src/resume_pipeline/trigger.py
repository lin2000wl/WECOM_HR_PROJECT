import logging
import sys
from pathlib import Path
import time

# Add src directory to sys.path to allow absolute imports
# This might be necessary depending on how the script is run
# sys.path.append(str(Path(__file__).resolve().parents[1])) # No longer needed if using python -m

from src.config import get_paths_config, get_ocr_config # Import specific getters
from src.logger import logger # Use already setup logger from __main__ typically
from src.db_interface import db_interface # Use global db instance
from src.llm_client import LLMClient # Instantiate if needed, or use a global one

from src.resume_pipeline.scanner import scan_data_directory # Import the function directly
from src.resume_pipeline.text_extractor import extract_text_from_pdf # Import the function directly
from src.resume_pipeline.ocr_processor import OcrProcessor # Optional
from src.resume_pipeline.resume_parser import parse_resume_pdf # Import the function directly
from src.resume_pipeline.validator_standardizer import validate_and_standardize # Import the function directly
from src.resume_pipeline.file_manager import FileManager
from src.resume_pipeline.db_updater import DbUpdater

# Initialize logging first (this might be redundant if logger is configured elsewhere)
# setup_logging()
# logger = logging.getLogger(__name__)

def run_pipeline():
    """Runs the full resume processing pipeline manually."""
    start_time = time.time()
    logger.info("--- Starting Resume Processing Pipeline --- ")

    try:
        # 1. Initialization
        logger.info("Initializing components...")
        # Components now get their config directly or use global instances
        # config = Config() # Removed
        # db_interface = DbInterface(config) # Use global db_interface
        llm_client = LLMClient() # Instantiate LLM client
        file_manager = FileManager() # FileManager now gets config internally
        db_updater = DbUpdater(db_interface) # Use global db_interface

        # Instantiate pipeline components that are classes
        # scanner = Scanner() # Removed: Scanner is now a function
        # text_extractor = TextExtractor() # Removed: TextExtractor is now a function
        ocr_processor = OcrProcessor()
        # resume_parser = ResumeParser(llm_client) # Removed: resume_parser is now a function
        # validator_standardizer = ValidatorStandardizer() # Removed: validator is now a function

        processed_count = 0
        error_count = 0
        pending_count = 0
        skipped_count = 0 # Files that might be non-PDF or already processed implicitly

        # 2. Scan for files by calling the function
        data_dir = get_paths_config().get("data_dir", "data/") # Get data_dir for logging
        logger.info(f"Scanning for PDF files in '{data_dir}'...")
        pdf_files_paths = scan_data_directory() # Call the function directly
        pdf_files = [Path(p) for p in pdf_files_paths] # Convert strings to Path objects

        if not pdf_files:
            logger.info("No new PDF files found to process.")
            return

        logger.info(f"Found {len(pdf_files)} PDF files to process.")

        # 3. Process each file (Path object)
        for pdf_path in pdf_files:
            logger.info(f"--- Processing file: {pdf_path.name} ---")
            # original_path_str = str(pdf_path) # No longer needed if pdf_path is Path

            try:
                # a. Extract Text (with OCR fallback) by calling the function directly
                text = extract_text_from_pdf(str(pdf_path)) # Pass path string to the function
                if not text or len(text.strip()) < 50: # Basic check if text is too short
                    logger.warning(f"Text extraction yielded little/no text for {pdf_path.name}. Attempting OCR.")
                    # Ensure OCR is configured and available
                    if ocr_processor.is_available():
                         text = ocr_processor.ocr_pdf(str(pdf_path)) # ocr_pdf might expect string path
                         if not text or len(text.strip()) < 50:
                             logger.error(f"OCR also yielded little/no text for {pdf_path.name}. Moving to error.")
                             file_manager.move_to_error(pdf_path, reason="Text extraction and OCR failed")
                             error_count += 1
                             continue # Skip to next file
                         else:
                             logger.info(f"Successfully extracted text using OCR for {pdf_path.name}.")
                    else:
                         logger.error(f"OCR is not available or configured. Cannot process image-based PDF: {pdf_path.name}. Moving to error.")
                         file_manager.move_to_error(pdf_path, reason="OCR needed but not available")
                         error_count += 1
                         continue # Skip to next file
                else:
                    logger.info(f"Successfully extracted text from {pdf_path.name}.")

                # b. Parse Resume using LLM by calling the function
                logger.info(f"Parsing resume content for {pdf_path.name} using LLM...")
                # Note: parse_resume_pdf internal logic handles text extraction/OCR
                # We might need to decide if we pass the path OR the extracted text
                # Based on resume_parser.py's function, it expects the path and handles extraction internally.
                # However, the current trigger logic extracts text first. Let's adapt trigger for now.
                # If text extraction failed before OCR, text will be None here.
                # If text extraction ok, text has content.
                # If text extraction failed -> OCR ok, text has content.
                # If text extraction failed -> OCR failed, text is None.
                
                if text is None:
                     logger.error(f"Text extraction (including OCR attempt) failed for {pdf_path.name}. Cannot parse.")
                     file_manager.move_to_error(pdf_path, reason="Text extraction failed")
                     error_count += 1
                     continue # Skip to next file
                 
                # Call the LLM client directly with the extracted text
                extracted_data = llm_client.parse_resume(text)
                # extracted_data = parse_resume_pdf(str(pdf_path)) # Old way if parser handled extraction
                
                if not extracted_data:
                    logger.error(f"LLM parsing failed for {pdf_path.name}. Moving to error.")
                    file_manager.move_to_error(pdf_path, reason="LLM Parsing failed")
                    error_count += 1
                    continue
                extracted_data['source_file_original_name'] = pdf_path.name # Add original name
                logger.info(f"LLM parsing successful for {pdf_path.name}. Extracted keys: {list(extracted_data.keys())}")

                # c. Validate and Standardize by calling the function
                logger.info(f"Validating and standardizing data for {pdf_path.name}...")
                is_valid, standardized_filename, processed_data, validation_reason = validate_and_standardize(extracted_data, pdf_path.name)

                if not is_valid:
                    logger.warning(f"Validation failed for {pdf_path.name}: {validation_reason}. Moving to pending.")
                    # Pass the processed_data (with tags) to file_manager if needed for context
                    file_manager.move_to_pending(pdf_path, reason=validation_reason)
                    pending_count += 1
                    continue
                logger.info(f"Validation successful for {pdf_path.name}. Standardized filename: {standardized_filename}")

                # d. Move to Processed Directory
                logger.info(f"Moving {pdf_path.name} to processed directory as {standardized_filename}...")
                processed_path = file_manager.move_to_processed(pdf_path, standardized_filename)
                if not processed_path:
                    logger.error(f"Failed to move {pdf_path.name} to processed directory. Skipping DB update.")
                    # File might still be in data/ or partially moved. Requires manual check.
                    error_count += 1 # Consider this an error state
                    continue
                logger.info(f"Successfully moved file to: {processed_path}")

                # e. Update Database (use processed_data which includes query_tags)
                logger.info(f"Updating database for {standardized_filename}...")
                success = db_updater.upsert_candidate(processed_data, processed_path)
                if success:
                    logger.info(f"Database update successful for {standardized_filename}.")
                    processed_count += 1
                else:
                    logger.error(f"Database update failed for {standardized_filename}. File is in processed dir, but DB entry may be missing/outdated.")
                    # This is a critical error state - data inconsistency
                    error_count += 1 # Count as error, needs investigation

            except Exception as e:
                logger.error(f"An unexpected error occurred while processing {pdf_path.name}: {e}", exc_info=True)
                # Try to move the file to error directory in case of unexpected failure
                try:
                    file_manager.move_to_error(pdf_path, reason=f"Unexpected processing error: {e}")
                except Exception as move_err:
                    logger.error(f"Failed to move {pdf_path.name} to error directory after unexpected error: {move_err}", exc_info=True)
                error_count += 1

    except Exception as pipeline_init_error:
        logger.critical(f"Failed to initialize or run the pipeline: {pipeline_init_error}", exc_info=True)

    finally:
        # 4. Log Summary
        end_time = time.time()
        duration = end_time - start_time
        logger.info("--- Resume Processing Pipeline Finished ---")
        logger.info(f"Total time taken: {duration:.2f} seconds")
        logger.info(f"Summary: Processed={processed_count}, Errors={error_count}, Pending={pending_count}, Skipped/Not Found={skipped_count+len(pdf_files)-(processed_count+error_count+pending_count)}")
        logger.info("-------------------------------------------")

if __name__ == "__main__":
    run_pipeline() 