from pathlib import Path
from mistralai import Mistral, DocumentURLChunk
import json
import os
import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from Prompt import master_prompt, refresh_prompt # Assuming Prompt.py exists and is correct
import httpx
import random
import pandas as pd
from datetime import datetime
import openpyxl # Required by pandas for Excel writing
import PyPDF2  # For splitting PDF files
import cv_separator
import tempfile

# Set a custom temp directory for all temp files (fixes Windows permission issues)
# Define the directory path but don't create it yet
CUSTOM_TEMP_DIR = Path(__file__).parent / "temp_chunks"

# Add a function to ensure the temp directory exists
def ensure_temp_dir():
    """
    Ensure the temporary directory exists, creating it if necessary.
    This function can be called any time before creating temp files.
    If the original directory cannot be created, it falls back to alternatives.
    
    Returns:
        Path: The path to the temp directory that was successfully created
    """
    global CUSTOM_TEMP_DIR
    
    try:
        # Try creating the primary temp directory
        os.makedirs(CUSTOM_TEMP_DIR, exist_ok=True)
        # Test write permissions by creating a test file
        test_file = CUSTOM_TEMP_DIR / f"test_write_{time.time()}.tmp"
        try:
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
            # Directory is writable, set it as temp directory
            os.environ['TMP'] = os.environ['TEMP'] = str(CUSTOM_TEMP_DIR)
            return CUSTOM_TEMP_DIR
        except Exception as write_error:
            print(f"Warning: Directory {CUSTOM_TEMP_DIR} exists but is not writable: {write_error}")
            raise  # Re-raise to trigger fallback
    except Exception as e:
        print(f"Warning: Could not create or write to temp directory {CUSTOM_TEMP_DIR}: {e}")
        
        # Try creating a folder in the user's home directory
        try:
            home_dir = Path.home() / "cv_processor_temp"
            os.makedirs(home_dir, exist_ok=True)
            # Test write permissions
            test_file = home_dir / f"test_write_{time.time()}.tmp"
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
            CUSTOM_TEMP_DIR = home_dir  # Update the global variable
            os.environ['TMP'] = os.environ['TEMP'] = str(CUSTOM_TEMP_DIR)
            print(f"Using home directory temp folder: {CUSTOM_TEMP_DIR}")
            return CUSTOM_TEMP_DIR
        except Exception as e2:
            print(f"Warning: Could not create or use home directory: {e2}")
            
            # Try creating a folder in the system temp directory
            try:
                fallback_dir = Path(tempfile.gettempdir()) / "cv_processor_temp"
                os.makedirs(fallback_dir, exist_ok=True)
                # Test write permissions
                test_file = fallback_dir / f"test_write_{time.time()}.tmp"
                with open(test_file, 'w') as f:
                    f.write('test')
                os.remove(test_file)
                CUSTOM_TEMP_DIR = fallback_dir  # Update the global variable
                os.environ['TMP'] = os.environ['TEMP'] = str(CUSTOM_TEMP_DIR)
                print(f"Using system temp directory folder: {CUSTOM_TEMP_DIR}")
                return CUSTOM_TEMP_DIR
            except Exception as e3:
                print(f"Warning: Could not create fallback directory: {e3}")
                
                # Last resort: use the system temp directory directly
                CUSTOM_TEMP_DIR = Path(tempfile.gettempdir())
                os.environ['TMP'] = os.environ['TEMP'] = str(CUSTOM_TEMP_DIR)
                print(f"Using system temp directory: {CUSTOM_TEMP_DIR}")
                return CUSTOM_TEMP_DIR

# Initialize the temp directory when the module is loaded
ensure_temp_dir()

# API key (Keep securely managed - consider environment variables)
API_KEY = ""  # Will be set by the application

# Initialize the Mistral client - will be initialized properly when API key is provided
client = None

# Directory to save output Excel files
OUTPUT_DIR = Path(__file__).parent / "output"
# Ensure the output directory exists
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def initialize_client(new_api_key=None):
    """Initialize or reinitialize the Mistral client with the given API key"""
    global API_KEY, client
    if new_api_key:
        API_KEY = new_api_key
    if API_KEY:  # Only create client if we have an API key
        try:
            client = Mistral(api_key=API_KEY)
            print(f"Mistral client initialized successfully")
            return client
        except Exception as e:
            print(f"Error initializing Mistral client: {e}")
            return None
    else:
        print("Warning: No API key provided for Mistral client initialization")
        return None

# Initialize with environment variable if available
initialize_client(os.environ.get("MISTRAL_API_KEY", ""))

# ========== HELPER FUNCTIONS (Retry Logic - Keep As Is) ==========

def retry_with_backoff(func, max_retries=5, initial_backoff=1, backoff_factor=2, jitter=0.1):
    """
    Enhanced retry mechanism with exponential backoff, jitter, and error-specific handling.
    
    Args:
        func (callable): The function to retry.
        max_retries (int): Maximum number of retry attempts.
        initial_backoff (float): Initial backoff time in seconds.
        backoff_factor (float): Factor by which to increase backoff time on each retry.
        jitter (float): Random factor to add to backoff time (0-1).
        
    Returns:
        callable: Wrapped function with retry logic.
    """
    # Define categorized error types for different handling
    timeout_errors = (httpx.ReadTimeout, httpx.ConnectTimeout)
    connection_errors = (httpx.ConnectError, httpx.ReadError, httpx.NetworkError)
    protocol_errors = (httpx.RemoteProtocolError,)
    
    # All retryable errors
    retryable_errors = timeout_errors + connection_errors + protocol_errors
    
    def wrapper(*args, **kwargs):
        retries = 0
        last_exception = None
        error_counts = {
            'timeout': 0,
            'connection': 0,
            'protocol': 0
        }
        
        while True:
            try:
                return func(*args, **kwargs)
            
            except timeout_errors as e:
                error_counts['timeout'] += 1
                retries += 1
                last_exception = e
                error_category = "timeout"
                # Timeouts need longer backoff
                modifier = 1.5
                
            except connection_errors as e:
                error_counts['connection'] += 1
                retries += 1
                last_exception = e
                error_category = "connection"
                # Connection errors need moderate backoff
                modifier = 1.2
                
            except protocol_errors as e:
                error_counts['protocol'] += 1
                retries += 1
                last_exception = e
                error_category = "protocol"
                # Protocol errors can use standard backoff
                modifier = 1.0
                
            except Exception as e:
                # Non-retryable error
                print(f"Non-retryable error in {func.__name__}: {e}")
                import traceback
                traceback.print_exc()
                raise  # Re-raise immediately for non-retryable errors
            
            # Check if we've exceeded retry limit
            if retries > max_retries:
                print(f"Error persistent after {max_retries} retries:")
                print(f"  - Timeouts: {error_counts['timeout']}")
                print(f"  - Connection errors: {error_counts['connection']}")
                print(f"  - Protocol errors: {error_counts['protocol']}")
                print(f"Last error: {last_exception} ({type(last_exception).__name__})")
                
                # Special handling for connection errors that might require user intervention
                if error_counts['connection'] > 0:
                    print("NETWORK ISSUE: Please check your internet connection.")
                
                raise last_exception
            
            # Calculate backoff with error-specific modifier and jitter
            backoff = initial_backoff * (backoff_factor ** (retries - 1)) * modifier
            backoff_jitter = backoff * jitter * random.uniform(-1, 1)
            sleep_time = max(0.5, backoff + backoff_jitter)  # Ensure minimum sleep time
            
            # Show detailed retry information
            print(f"{error_category.upper()} ERROR: {type(last_exception).__name__}: {last_exception}.")
            print(f"Retry {retries}/{max_retries} in {sleep_time:.2f} seconds...")
            time.sleep(sleep_time)
    
    return wrapper

@retry_with_backoff
def upload_file_with_retry(client, file_name, file_content, purpose):
    """Upload a file with retry logic"""
    print(f"Uploading file '{file_name}' for purpose '{purpose}'...")
    # Ensure we have a valid client
    if client is None:
        client = initialize_client()
        if client is None:
            raise ValueError("No API key provided. Please set a valid Mistral API key.")
    
    return client.files.upload(
    file={
            "file_name": file_name,
            "content": file_content,
        },
        purpose=purpose,
    )

@retry_with_backoff
def get_signed_url_with_retry(client, file_id, expiry):
    """Get signed URL with retry logic"""
    print(f"Getting signed URL for file ID: {file_id} (expiry: {expiry} min)...")
    # Ensure we have a valid client
    if client is None:
        client = initialize_client()
        if client is None:
            raise ValueError("No API key provided. Please set a valid Mistral API key.")
            
    return client.files.get_signed_url(file_id=file_id, expiry=expiry)

@retry_with_backoff
def process_ocr_with_retry(client, document_url, model, include_image_base64):
    """Process OCR with retry logic"""
    print(f"Sending document URL to OCR model '{model}'...")
    # Ensure we have a valid client
    if client is None:
        client = initialize_client()
        if client is None:
            raise ValueError("No API key provided. Please set a valid Mistral API key.")
            
    return client.ocr.process(
        document=DocumentURLChunk(document_url=document_url),
        model=model,
        include_image_base64=include_image_base64 # Keep False unless images needed later
    )

# ========== CORE OCR PROCESSING (SIMPLIFIED) ==========

def process_pdf(pdf_file: Path):
    """
    Processes the PDF using Mistral OCR API, splitting by 5 CVs per chunk if possible.
    Uses caching to avoid re-processing the same file.

    Args:
        pdf_file (Path): Path to the PDF file.

    Returns:
        str: The extracted text content from all pages.
    """
    # Ensure we have a valid client
    global client
    if client is None:
        client = initialize_client()
        if client is None:
            raise ValueError("No API key provided. Please set a valid Mistral API key first.")
    
    # Ensure temp directory exists before processing
    ensure_temp_dir()
    
    cache_dir = Path("ocr_cache") # Store cache in a sub-directory
    cache_dir.mkdir(exist_ok=True)
    cache_file = cache_dir / f"{pdf_file.stem}_ocr_text_cache.txt"
    backup_file = cache_dir / f"{pdf_file.stem}_extracted_text_backup.txt"

    # 1. Check Cache
    if cache_file.is_file():
        print(f"Cache hit: Loading OCR text from {cache_file}")
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                all_pages_text = f.read()
            if len(all_pages_text) > 100: # Basic check if cache content seems valid
                print(f"Successfully loaded {len(all_pages_text):,} characters from cache.")
                return all_pages_text
            else:
                print("Warning: Cache file seems empty or corrupted. Re-processing...")
        except Exception as e:
            print(f"Warning: Error reading cache file {cache_file}: {e}. Re-processing...")

    # 2. Split PDF by CVs and OCR each chunk
    try:
        chunk_files = split_pdf_by_cv(pdf_file, cv_per_chunk=5)
        print(f"Split PDF into {len(chunk_files)} chunks of up to 5 CVs each.")
        from concurrent.futures import ThreadPoolExecutor, as_completed
        ocr_results = [None] * len(chunk_files)
        def ocr_chunk(idx, chunk_path):
            print(f"Uploading chunk {idx+1}/{len(chunk_files)}: {chunk_path}")
            with open(chunk_path, "rb") as f:
                uploaded_file = upload_file_with_retry(
                    client,
                    file_name=os.path.basename(chunk_path),
                    file_content=f.read(),
                    purpose="ocr"
                )
            signed_url = get_signed_url_with_retry(client, uploaded_file.id, expiry=5)
            pdf_response = process_ocr_with_retry(
                client,
                document_url=signed_url.url,
                model="mistral-ocr-latest",
                include_image_base64=False
            )
            # Extract text from all pages in this chunk
            page_texts = []
            for i, page in enumerate(pdf_response.pages):
                page_texts.append(f"\n\n--- PAGE {i+1} (chunk {idx+1}) ---\n\n{page.markdown}")
            return "".join(page_texts)
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(ocr_chunk, idx, chunk_path): idx for idx, chunk_path in enumerate(chunk_files)}
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    ocr_results[idx] = future.result()
                    print(f"✓ OCR complete for chunk {idx+1}/{len(chunk_files)}")
                except Exception as e:
                    print(f"Error OCR'ing chunk {idx+1}: {e}")
                    ocr_results[idx] = ""
        # Concatenate all chunk results in order
        all_pages_text = "".join(ocr_results)
        print(f"Concatenated OCR text from {len(chunk_files)} chunks.")
        # Clean up temporary files
        for chunk_path in chunk_files:
            try:
                os.remove(chunk_path)
                print(f"Deleted temporary chunk file: {chunk_path}")
            except Exception as e:
                print(f"Warning: Could not delete temp file {chunk_path}: {e}")
        # Save to Cache and Backup
        try:
            print(f"Saving extracted text to cache: {cache_file}")
            with open(cache_file, "w", encoding="utf-8") as f:
                f.write(all_pages_text)
            print(f"Saving backup text file: {backup_file}")
            with open(backup_file, "w", encoding="utf-8") as f:
                f.write(all_pages_text)
        except Exception as e:
            print(f"Warning: Could not write cache or backup file: {e}")
        print("First 500 characters sample:")
        print(all_pages_text[:500] + "..." if len(all_pages_text) > 500 else all_pages_text)
        print("\n===== OCR TEXT EXTRACTION COMPLETE =====\n")
    except Exception as e:
        print(f"[FALLBACK] Error during chunked OCR: {e}. Trying single upload.")
        # Fallback to old logic
        try:
            print(f"Uploading {pdf_file.name} as a single file...")
            uploaded_file = upload_file_with_retry(
                client,
                file_name=pdf_file.name,
                file_content=pdf_file.read_bytes(),
                purpose="ocr"
            )
            signed_url = get_signed_url_with_retry(client, uploaded_file.id, expiry=5)
            pdf_response = process_ocr_with_retry(
                client,
                document_url=signed_url.url,
                model="mistral-ocr-latest",
                include_image_base64=False
            )
            page_texts = []
            for i, page in enumerate(pdf_response.pages):
                page_texts.append(f"\n\n--- PAGE {i+1} ---\n\n{page.markdown}")
            all_pages_text = "".join(page_texts)
            print(f"Extracted text from {len(pdf_response.pages)} pages.")
            try:
                print(f"Saving extracted text to cache: {cache_file}")
                with open(cache_file, "w", encoding="utf-8") as f:
                    f.write(all_pages_text)
                print(f"Saving backup text file: {backup_file}")
                with open(backup_file, "w", encoding="utf-8") as f:
                    f.write(all_pages_text)
            except Exception as e2:
                print(f"\n\nERROR during OCR processing: {e2}")
                import traceback
                traceback.print_exc()
                raise
        except Exception as e2:
            print(f"\n\nERROR during OCR processing: {e2}")
            import traceback
            traceback.print_exc()
            raise
    return all_pages_text


# ========== CV DATA ANALYSIS (Using Chat API - Cheaper) ==========

@retry_with_backoff # Add retry for chat completions too
def call_chat_api(messages, model="mistral-small-latest", temperature=0.1, max_tokens=4000):
    """Wrapper for chat API call with retry logic."""
    # Ensure we have a valid client
    global client
    if client is None:
        client = initialize_client()
        if client is None:
            raise ValueError("No API key provided. Please set a valid Mistral API key.")
    
    print(f"Calling chat model '{model}' (max_tokens: {max_tokens})...")
    chat_response = client.chat.complete(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens
    )
    return chat_response.choices[0].message.content


def get_cv_data(all_pages_text, custom_prompt=None):
    """
    Extract CV data from the OCR text using Mistral Chat API.
    Handles large documents by chunking the text.

    Args:
        all_pages_text (str): The full text extracted by OCR.
        custom_prompt (str, optional): An alternative prompt to use. Defaults to None.

    Returns:
        str: JSON formatted string containing extracted CV data.
    """
    print("\nAnalyzing document text with Chat API...")

    # Use custom prompt if provided, otherwise refresh the standard prompt
    prompt_text = custom_prompt or refresh_prompt() # Use refreshed master_prompt

    # Estimate token count (very rough estimate: 1 token ≈ 4 chars)
    # Use a conservative estimate to decide on chunking
    estimated_chars = len(all_pages_text)
    estimated_tokens = estimated_chars / 3.5 # Adjust divisor based on language/content

    # Define a chunking threshold (e.g., based on model context window limits)
    # Mistral-small context is large, but processing very large single prompts can be slow/costly.
    # Let's chunk if text is very large (e.g., > 100k characters, roughly 30k tokens)
    chunking_threshold_chars = 100_000

    if estimated_chars > chunking_threshold_chars:
        print(f"Document text is large ({estimated_chars:,} chars, est. {int(estimated_tokens):,} tokens). Processing in chunks...")
        return process_large_document_text(all_pages_text, prompt_text)
    else:
        # Process normally for smaller documents
        print(f"Document text size ({estimated_chars:,} chars, est. {int(estimated_tokens):,} tokens) is within single prompt limit.")
        return process_single_text_prompt(all_pages_text, prompt_text)


def process_single_text_prompt(text, prompt_text):
    """Process the entire text with a single chat API call."""
    question_messages = [
        {
            "role": "user",
            "content": f"Based on the following OCR content, {prompt_text}\n\nDocument Content:\n```\n{text}\n```"
        }
    ]

    response_content = call_chat_api(question_messages)

    print("\n===== CHAT API RESPONSE (SINGLE PROMPT) =====\n")
    print(response_content[:500] + "..." if len(response_content) > 500 else response_content)
    print("\n===== END OF RESPONSE =====\n")
    return response_content


def process_large_document_text(all_pages_text, prompt_text):
    """
    Process a large document by chunking it and sending each chunk to the Chat API.
    
    This function:
    1. Splits the text into pages using page indicators
    2. Groups pages into chunks of reasonable size
    3. Processes each chunk in parallel
    4. Combines the results from all chunks
    
    Args:
        all_pages_text (str): The full text extracted by OCR.
        prompt_text (str): The prompt text to use for CV extraction.
        
    Returns:
        str: JSON string of combined CV data from all chunks.
    """
    # Split text by pages
    pages = split_text_by_pages(all_pages_text)
    print(f"Document split into {len(pages)} pages")
    
    # Check for cancellation
    if check_cancelled():
        print("Processing cancelled")
        return "[]"  # Return empty JSON array
    
    # Group pages into chunks
    chunk_size = 10  # Pages per chunk, adjust based on document density
    chunks = [pages[i:i + chunk_size] for i in range(0, len(pages), chunk_size)]
    print(f"Created {len(chunks)} chunks of approximately {chunk_size} pages each")
    
    # Process chunks in parallel
    results = []
    total_chunks = len(chunks)
    
    # Use ThreadPoolExecutor for parallel processing
    with ThreadPoolExecutor(max_workers=4) as executor:
        # Submit all tasks
        future_to_chunk = {
            executor.submit(process_text_chunk, "".join(chunk), prompt_text, i+1, total_chunks): i 
            for i, chunk in enumerate(chunks)
        }
        
        # Process as they complete
        for future in as_completed(future_to_chunk):
            chunk_idx = future_to_chunk[future]
            try:
                # Check for cancellation
                if check_cancelled():
                    print("Processing cancelled - stopping remaining chunks")
                    break
                    
                result = future.result()
                if result:
                    results.extend(result)
                print(f"✓ Processed chunk {chunk_idx+1}/{total_chunks} - found {len(result) if result else 0} CVs")
            except Exception as e:
                print(f"Error processing chunk {chunk_idx+1}: {e}")
    
    # Check for cancellation before final processing
    if check_cancelled():
        print("Processing cancelled before final results compilation")
        return "[]"  # Return empty JSON array
        
    # Combine results and remove duplicates
    print(f"Total raw CV entries extracted: {len(results)}")
    
    # Filter out likely duplicates (same name and email)
    unique_cvs = []
    seen_keys = set()
    
    for cv in results:
        # Create a key based on name and email if they exist
        if isinstance(cv, dict):  # Ensure it's a dictionary
            first_name = cv.get('FIRST_NAME', '').strip()
            last_name = cv.get('LAST_NAME', '').strip()
            email = cv.get('EMAIL', '').strip()
            
            # Create a unique identifier
            if first_name and last_name:
                key = f"{first_name.lower()}-{last_name.lower()}"
                if email:
                    key += f"-{email.lower()}"
                    
                if key not in seen_keys:
                    seen_keys.add(key)
                    unique_cvs.append(cv)
            else:
                # If no name, just add it (might be malformed)
                unique_cvs.append(cv)
        else:
            # Non-dict elements (shouldn't happen with proper parsing)
            print(f"Warning: Non-dictionary element in results: {cv}")
    
    print(f"Total unique CV entries after deduplication: {len(unique_cvs)}")
    
    # Convert to JSON string
    return json.dumps(unique_cvs, indent=2)


def process_text_chunk(chunk_text, prompt_text, chunk_index, total_chunks):
    """
    Process a single chunk of text using the Chat API.
    
    Args:
        chunk_text (str): The text chunk to process.
        prompt_text (str): The prompt text to use for CV extraction.
        chunk_index (int): The index of this chunk (for logging).
        total_chunks (int): Total number of chunks (for logging).
        
    Returns:
        list: List of extracted CV data dictionaries from this chunk.
    """
    # Check for cancellation
    if check_cancelled():
        print(f"Chunk {chunk_index}/{total_chunks} - Processing cancelled")
        return []
        
    print(f"Processing chunk {chunk_index}/{total_chunks} ({len(chunk_text):,} characters)")
    
    # Create messages for the chunk
    question_messages = [
        {
            "role": "user",
            "content": (
                f"{prompt_text}\n\n"
                f"This is chunk {chunk_index} of {total_chunks}.\n"
                f"Only include complete CVs in your response. "
                f"If a CV appears to be cut off or incomplete at the beginning or end of the chunk, skip it entirely.\n\n"
                f"Document Content (Chunk {chunk_index}/{total_chunks}):\n```\n{chunk_text}\n```"
            )
        }
    ]
    
    # Use a slightly higher temperature for verification runs when needed
    temperature = 0.1  # Standard temperature for structured data extraction
    
    try:
        # Call the API with retries
        response_content = call_chat_api(question_messages, temperature=temperature, max_tokens=3500)
        
        # Check for cancellation
        if check_cancelled():
            print(f"Chunk {chunk_index}/{total_chunks} - Processing cancelled after API call")
            return []
            
        # Parse the JSON response
        cv_data = parse_json_response(response_content)
        
        if isinstance(cv_data, list):
            return cv_data
        else:
            print(f"Warning: Expected list response from chunk {chunk_index}, got {type(cv_data).__name__}")
            return []
            
    except Exception as e:
        print(f"Error processing chunk {chunk_index}: {e}")
        return []


def split_text_by_pages(all_pages_text):
    """
    Split OCR text into separate pages based on page markers.
    This helps maintain logical boundaries and improves processing.
    
    Args:
        all_pages_text (str): The full text from OCR.
        
    Returns:
        list: List of page text strings.
    """
    # Look for page markers like "Page X of Y" or "Page X" 
    # Common OCR patterns for page breaks
    page_patterns = [
        r'Page\s+\d+\s+of\s+\d+',  # "Page X of Y"
        r'Page\s+\d+',             # "Page X"
        r'-\s*\d+\s*-',            # "- X -"
        r'\[\s*Page\s+\d+\s*\]',   # "[Page X]"
        r'\(\s*\d+\s*\)',          # "(X)" when it appears consistently as page marker
        r'^\s*\d+\s*$'             # Just a number on its own line
    ]
    
    # Combine patterns
    page_break_pattern = '|'.join(page_patterns)
    
    # Split by page markers, but keep the markers as part of the pages
    # This preserves the context of which page each section belongs to
    pages = []
    
    # Use a less greedy approach to find potential page breaks
    # First, split by newlines to analyze line by line
    lines = all_pages_text.split('\n')
    current_page = []
    
    for line in lines:
        current_page.append(line)
        
        # Check if this line might be a page break
        if re.search(page_break_pattern, line, re.IGNORECASE):
            # Look ahead to see if this is immediately followed by what looks like a header
            # or a new CV start, which would confirm it's a page break
            if len(current_page) > 5:  # Only consider a page break if we have a reasonable amount of content
                pages.append('\n'.join(current_page))
                current_page = []
    
    # Add the last page if not empty
    if current_page:
        pages.append('\n'.join(current_page))
    
    # If no page breaks were found, or if we ended up with just one page,
    # fall back to a simpler size-based approach
    if len(pages) <= 1:
        print("No clear page breaks detected. Using size-based chunking...")
        # Roughly estimate 3000 characters per page
        chars_per_page = 3000
        pages = [all_pages_text[i:i+chars_per_page] 
                 for i in range(0, len(all_pages_text), chars_per_page)]
    
    print(f"Split text into {len(pages)} pages")
    return pages


# ========== EXCEL EXPORT & MERGING FUNCTIONS (Keep As Is) ==========

def parse_json_response(response_text):
    """
    Enhanced JSON response parsing with robust recovery and validation.
    
    Args:
        response_text (str): The JSON response text from the API.
        
    Returns:
        list: List of parsed CV dictionaries.
    """
    if not response_text or not isinstance(response_text, str):
        print("Warning: Received empty or invalid response text for JSON parsing.")
        return []

    # Track the original length for reporting
    original_length = len(response_text)
    
    # Step 1: Clean common issues from the text
    cleaned_text = response_text.strip()
    
    # Remove markdown code blocks (multiple variations)
    code_block_patterns = [
        r"```json\s*", r"```javascript\s*", r"```js\s*", r"```\s*"
    ]
    for pattern in code_block_patterns:
        if re.search(pattern, cleaned_text, re.IGNORECASE):
            # Strip opening code block
            cleaned_text = re.sub(pattern, "", cleaned_text, 1, re.IGNORECASE)
            # Strip closing code block if present
            cleaned_text = re.sub(r"\s*```\s*$", "", cleaned_text)
            break

    # Fix common structural issues
    # Remove trailing commas before closing brackets (invalid JSON)
    cleaned_text = re.sub(r',\s*}', '}', cleaned_text)
    cleaned_text = re.sub(r',\s*]', ']', cleaned_text)
    
    # Add missing array brackets if needed
    if cleaned_text.strip().startswith("{") and not cleaned_text.strip().startswith("[{"):
        cleaned_text = f"[{cleaned_text}]"
    
    # Fix unclosed structures
    if cleaned_text.count("[") > cleaned_text.count("]"):
        cleaned_text += "]" * (cleaned_text.count("[") - cleaned_text.count("]"))
    if cleaned_text.count("{") > cleaned_text.count("}"):
        cleaned_text += "}" * (cleaned_text.count("{") - cleaned_text.count("}"))
    
    # Step 2: Attempt to parse the cleaned text
    try:
        cv_data = json.loads(cleaned_text)
        
        # Ensure we have a list
        if isinstance(cv_data, dict):
            cv_data = [cv_data]  # Wrap single dict in list
        elif not isinstance(cv_data, list):
            print(f"Warning: Parsed JSON is not a list or dict: {type(cv_data).__name__}. Returning empty list.")
            return []
        
        print(f"Successfully parsed JSON data with {len(cv_data)} entries (cleaned {original_length} → {len(cleaned_text)} chars)")
        
        # Step 3: Validate and normalize the parsed data
        valid_cv_data = []
        for i, cv in enumerate(cv_data):
            if not isinstance(cv, dict):
                print(f"Warning: Entry {i} is not a dictionary. Skipping.")
                continue
            
            # Check for required fields
            if not cv.get("FIRST_NAME") and not cv.get("LAST_NAME"):
                print(f"Warning: Entry {i} missing both first and last name. Skipping.")
                continue
            
            # Normalize fields - ensure all fields exist with defaults
            normalized_cv = {}
            for field in ["FIRST_NAME", "LAST_NAME", "EMAIL", "PHONE_NUMBER", 
                         "EDUCATION_LEVEL", "EXPECTED_GRADUATION_YEAR", 
                         "FACULTY", "NATIVE_LANGUAGE", "LINKEDIN_PROFILE_URL", "POTENTIAL_INTEREST"]:
                # Get value, defaulting to N/A if missing
                value = cv.get(field, "N/A")
                # Normalize empty strings to N/A
                normalized_cv[field] = value if value and value.strip() else "N/A"
            
            valid_cv_data.append(normalized_cv)
        
        print(f"After validation: {len(valid_cv_data)} valid CV entries")
        return valid_cv_data
        
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}. Attempting recovery...")
        print(f"--- Sample of text attempted to parse: ---")
        print(cleaned_text[:300] + "..." if len(cleaned_text) > 300 else cleaned_text)
        print(f"--- End sample ---")

        # Step 4: Advanced recovery for parsing failures
        try:
            # Strategy 1: Extract objects with regex
            # This might catch well-formed objects even if the overall JSON is invalid
            print("Attempting regex-based recovery...")
            objects = []
            
            # Try to find complete JSON objects
            object_matches = re.findall(r'\{[^{]*?"FIRST_NAME"[^{]*?}', cleaned_text, re.DOTALL)
            if not object_matches:
                # Try finding objects with any key if FIRST_NAME not found
                object_matches = re.findall(r'\{[^{]*?"[A-Z_]+"[^{]*?}', cleaned_text, re.DOTALL)
            
            # Parse each object individually
            for i, match in enumerate(object_matches):
                try:
                    # Try to fix common issues in individual objects
                    fixed_match = match.replace('""', '"N/A"')  # Replace empty strings with N/A
                    fixed_match = re.sub(r':\s*,', ': "N/A",', fixed_match)  # Fix missing values
                    fixed_match = re.sub(r':\s*}', ': "N/A"}', fixed_match)  # Fix missing final value
                    
                    obj = json.loads(fixed_match)
                    if isinstance(obj, dict) and (obj.get("FIRST_NAME") or obj.get("LAST_NAME")):
                        objects.append(obj)
                except json.JSONDecodeError:
                    print(f"Recovery: Failed to parse object {i+1}")
                    continue
            
            if objects:
                print(f"Recovery succeeded: Found {len(objects)} valid JSON objects")
                
                # Normalize the recovered objects
                normalized_objects = []
                for obj in objects:
                    normalized_obj = {}
                    for field in ["FIRST_NAME", "LAST_NAME", "EMAIL", "PHONE_NUMBER", 
                                 "EDUCATION_LEVEL", "EXPECTED_GRADUATION_YEAR", 
                                 "FACULTY", "NATIVE_LANGUAGE", "LINKEDIN_PROFILE_URL", "POTENTIAL_INTEREST"]:
                        normalized_obj[field] = obj.get(field, "N/A")
                    normalized_objects.append(normalized_obj)
                
                return normalized_objects
            
            # Strategy 2: If regex fails, try more aggressive parsing
            print("Trying more aggressive parsing...")
            
            # Look for any pattern that might be name data
            name_matches = re.findall(r'"FIRST_NAME"\s*:\s*"([^"]*)"\s*,\s*"LAST_NAME"\s*:\s*"([^"]*)"', cleaned_text)
            if name_matches:
                print(f"Found {len(name_matches)} name pairs, constructing minimal objects")
                minimal_objects = []
                for first_name, last_name in name_matches:
                    if first_name or last_name:  # At least one name component should be present
                        minimal_objects.append({
                            "FIRST_NAME": first_name or "N/A",
                            "LAST_NAME": last_name or "N/A",
                            "EMAIL": "N/A",
                            "PHONE_NUMBER": "N/A",
                            "EDUCATION_LEVEL": "N/A",
                            "EXPECTED_GRADUATION_YEAR": "N/A",
                            "FACULTY": "N/A",
                            "NATIVE_LANGUAGE": "N/A",
                            "LINKEDIN_PROFILE_URL": "N/A",
                            "POTENTIAL_INTEREST": "N/A"
                        })
                if minimal_objects:
                    print(f"Recovery succeeded with minimal objects: {len(minimal_objects)} entries")
                    return minimal_objects
            
            print("All recovery attempts failed. Returning empty list.")
            return []
            
        except Exception as recovery_error:
            print(f"Recovery attempt failed critically: {recovery_error}")
            import traceback
            traceback.print_exc()
            return []


def export_to_excel(cv_data, pdf_file, cv_book_source="", jfws_source="", mode="standard"):
    """
    Export CV data to Excel without highlighting.
    Saves results to the output folder using a PDF-specific filename.
    
    Args:
        cv_data: CV data (list of dicts or JSON string)
        pdf_file (Path or str): Path to the PDF file (for naming)
        cv_book_source (str): CV Book source for metadata
        jfws_source (str): JFWS source for metadata
        mode (str): Mode identifier for filename (standard, run1, run2, etc.)
        
    Returns:
        str: Path to the created Excel file
    """
    print(f"Exporting CV data to Excel ({mode} mode)...")
    
    # Convert to Path if string
    pdf_file = Path(pdf_file) if isinstance(pdf_file, str) else pdf_file
    
    # Convert JSON string to Python object if needed
    if isinstance(cv_data, str):
        try:
            cv_data = json.loads(cv_data)
        except json.JSONDecodeError:
            cv_data = parse_json_response(cv_data)
            
    # Ensure we have a list
    if not isinstance(cv_data, list):
        if isinstance(cv_data, dict):
            cv_data = [cv_data]
        else:
            print(f"Warning: CV data is not a list or dict: {type(cv_data).__name__}")
            cv_data = []
    
    # Create a file with the specific PDF name for reference and save to output folder
    pdf_specific_file_name = f"{pdf_file.stem}_results_{datetime.now().strftime('%H%M%S')}_{mode}.xlsx"
    pdf_specific_file_path = OUTPUT_DIR / pdf_specific_file_name
    
    # Add source information to each entry
    for entry in cv_data:
        if isinstance(entry, dict):
            entry["CV_SOURCE"] = cv_book_source
            entry["JFWS_SOURCE"] = jfws_source
            entry["PDF_SOURCE"] = pdf_file.stem  # Add the source PDF name
    
    try:
        # Convert to DataFrame
        df = pd.DataFrame(cv_data)
        
        # Reorder columns for better readability
        preferred_order = [
            "FIRST_NAME", "LAST_NAME", "EMAIL", "PHONE_NUMBER",
            "EDUCATION_LEVEL", "EXPECTED_GRADUATION_YEAR", "FACULTY",
            "NATIVE_LANGUAGE", "LINKEDIN_PROFILE_URL", "POTENTIAL_INTEREST",
            "CV_SOURCE", "JFWS_SOURCE", "PDF_SOURCE"
        ]
        
        # Only include columns that exist in the data
        ordered_columns = [col for col in preferred_order if col in df.columns]
        
        # Add any remaining columns that weren't in preferred_order
        remaining_columns = [col for col in df.columns if col not in preferred_order]
        ordered_columns.extend(remaining_columns)
        
        # Reorder DataFrame columns
        if ordered_columns:
            df = df[ordered_columns]
            
        # Save results to the PDF-specific Excel file
        df.to_excel(pdf_specific_file_path, index=False)
        print(f"Excel file created: {pdf_specific_file_path}")
        
        # Return the path to the PDF-specific Excel file
        return str(pdf_specific_file_path)
        
    except Exception as e:
        print(f"Error exporting to Excel: {e}")
        import traceback
        traceback.print_exc()
        return f"Error: Failed to export to Excel: {e}"


def compare_and_merge_results(cv_data1, cv_data2, pdf_file, cv_book_source="", jfws_source=""):
    """
    Compare and merge CV data from two analysis runs, highlighting differences.
    
    Args:
        cv_data1: CV data from first run (list of dicts or JSON string)
        cv_data2: CV data from second run (list of dicts or JSON string)
        pdf_file (Path): PDF file path (for naming output)
        cv_book_source (str): Source of the CV book for metadata
        jfws_source (str): Source of JFWS for metadata
        
    Returns:
        str: Path to the Excel file with merged results
    """
    print(f"Comparing and merging results from two analysis runs...")
    
    # Check for cancellation
    if check_cancelled():
        print("Processing cancelled during merge")
        return "Processing cancelled during merge"
    
    # Convert JSON strings to Python objects if needed
    if isinstance(cv_data1, str):
        try:
            cv_data1 = json.loads(cv_data1)
        except json.JSONDecodeError:
            cv_data1 = parse_json_response(cv_data1)
            
    if isinstance(cv_data2, str):
        try:
            cv_data2 = json.loads(cv_data2)
        except json.JSONDecodeError:
            cv_data2 = parse_json_response(cv_data2)
    
    # Ensure we have lists
    if not isinstance(cv_data1, list):
        if isinstance(cv_data1, dict):
            cv_data1 = [cv_data1]
        else:
            print(f"Warning: First run data is not a list or dict: {type(cv_data1).__name__}")
            cv_data1 = []
            
    if not isinstance(cv_data2, list):
        if isinstance(cv_data2, dict):
            cv_data2 = [cv_data2]
        else:
            print(f"Warning: Second run data is not a list or dict: {type(cv_data2).__name__}")
            cv_data2 = []
    
    # Create a mapping of CV data from run 2 for faster lookup
    cv_data2_map = {}
    
    def create_match_key(cv):
        """Create a matching key for a CV entry"""
        if not isinstance(cv, dict):
            return None
            
        first_name = str(cv.get('FIRST_NAME', '')).strip().lower()
        last_name = str(cv.get('LAST_NAME', '')).strip().lower()
        
        if not first_name and not last_name:
            return None
            
        # Create key from name combination
        return f"{first_name}|{last_name}"
            
    # Build lookup map for run 2 data
    for cv in cv_data2:
        if not isinstance(cv, dict):
            continue
            
        key = create_match_key(cv)
        if key:
            cv_data2_map[key] = cv
            
    # Prepare merged data and highlighting info
    merged_data = []
    highlighting = {}  # Maps row index to fields that should be highlighted
    processed_keys_from_run2 = set()
    
    # Check for cancellation
    if check_cancelled():
        print("Processing cancelled during merge")
        return "Processing cancelled during merge"
    
    # Iterate through Run 1, merging with Run 2
    for i, cv1 in enumerate(cv_data1):
        if not isinstance(cv1, dict):
            print(f"Skipping non-dict item in Run 1: {cv1}")
            continue
            
        key1 = create_match_key(cv1)
        if not key1:
            print(f"Skipping CV in Run 1 with no valid key")
            continue
            
        merged_cv = cv1.copy()  # Start with cv1 data
        highlighting[len(merged_data)] = {}  # Index in the merged list
        
        if key1 in cv_data2_map:
            cv2 = cv_data2_map[key1]
            processed_keys_from_run2.add(key1)  # Mark as processed
            
            # Compare fields and merge/highlight
            for field in ["FIRST_NAME", "LAST_NAME", "EMAIL", "PHONE_NUMBER",
                         "EDUCATION_LEVEL", "EXPECTED_GRADUATION_YEAR",
                         "FACULTY", "NATIVE_LANGUAGE", "LINKEDIN_PROFILE_URL", "POTENTIAL_INTEREST"]:
                value1 = cv1.get(field, "N/A")
                value2 = cv2.get(field, "N/A")
                
                # Normalize "N/A" and empty strings for comparison
                norm_val1 = "" if value1 == "N/A" else str(value1).strip()
                norm_val2 = "" if value2 == "N/A" else str(value2).strip()
                
                if norm_val1 != norm_val2:
                    if norm_val1 and norm_val2:  # Conflict
                        print(f"Conflict for {key1}, Field '{field}': Run1='{value1}', Run2='{value2}'. Using Run1.")
                        highlighting[len(merged_data)][field] = True
                        # Keep value1 (already in merged_cv)
                    elif not norm_val1 and norm_val2:  # Fill from Run 2
                        print(f"Filling N/A for {key1}, Field '{field}' with Run2 value: '{value2}'")
                        merged_cv[field] = value2  # Update merged data
        
        # Add metadata
        merged_cv["CV_SOURCE"] = cv_book_source
        merged_cv["JFWS_SOURCE"] = jfws_source
        merged_cv["PDF_SOURCE"] = pdf_file.stem
        merged_cv["RUN"] = "1" if key1 not in cv_data2_map else "1+2"  # Track which runs found this CV
            
        merged_data.append(merged_cv)
        
    # Check for cancellation
    if check_cancelled():
        print("Processing cancelled during merge")
        return "Processing cancelled during merge"
    
    # Add CVs found only in Run 2
    for key2, cv2 in cv_data2_map.items():
        if key2 not in processed_keys_from_run2:
            # Only found in Run 2
            print(f"CV found only in Run 2: {key2}")
            merged_cv = cv2.copy()
            
            # Add metadata
            merged_cv["CV_SOURCE"] = cv_book_source
            merged_cv["JFWS_SOURCE"] = jfws_source
            merged_cv["PDF_SOURCE"] = pdf_file.stem
            merged_cv["RUN"] = "2"  # Only found in Run 2
            
            merged_data.append(merged_cv)
    
    # Check for empty results
    if not merged_data:
        print("Warning: No data after merging runs!")
        return "Error: No data found after merging runs"
    
    # Create a file with the specific PDF name for reference
    pdf_specific_file_name = f"{pdf_file.stem}_merged_results_{datetime.now().strftime('%H%M%S')}.xlsx"
    pdf_specific_file_path = OUTPUT_DIR / pdf_specific_file_name
    
    try:
        # Convert to DataFrame
        df = pd.DataFrame(merged_data)
    
        # Reorder columns for better readability
        preferred_order = [
            "FIRST_NAME", "LAST_NAME", "EMAIL", "PHONE_NUMBER",
            "EDUCATION_LEVEL", "EXPECTED_GRADUATION_YEAR", "FACULTY",
            "NATIVE_LANGUAGE", "LINKEDIN_PROFILE_URL", "POTENTIAL_INTEREST",
            "RUN", "CV_SOURCE", "JFWS_SOURCE", "PDF_SOURCE"
        ]
    
        # Only include columns that exist in the data
        ordered_columns = [col for col in preferred_order if col in df.columns]
    
        # Add any remaining columns that weren't in preferred_order
        remaining_columns = [col for col in df.columns if col not in preferred_order]
        ordered_columns.extend(remaining_columns)
    
        # Reorder DataFrame columns
        if ordered_columns:
            df = df[ordered_columns]
        
        # Export to Excel with highlighting
        with pd.ExcelWriter(pdf_specific_file_path, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="CV Data")
            
            # Apply highlighting where needed
            workbook = writer.book
            worksheet = writer.sheets["CV Data"]
            
            # Define highlight style (light yellow background)
            highlight_fill = PatternFill(start_color="FFFF99", end_color="FFFF99", fill_type="solid")
            
            # Adjust column width for better readability
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = (max_length + 2) if max_length < 50 else 50
                worksheet.column_dimensions[column_letter].width = adjusted_width
            
            # Add highlighting based on the highlighting dict
            for row_idx, field_dict in highlighting.items():
                # Add 2 to row_idx (1 for header, 1 for 0-indexing)
                excel_row = row_idx + 2
                
                for field, should_highlight in field_dict.items():
                    if should_highlight:
                        # Find column index for this field
                        try:
                            col_idx = ordered_columns.index(field) + 1  # Add 1 for Excel's 1-based indexing
                            cell = worksheet.cell(row=excel_row, column=col_idx)
                            cell.fill = highlight_fill
                        except ValueError:
                            print(f"Warning: Could not find column for field '{field}'")
            
        print(f"Merged Excel file created: {pdf_specific_file_path}")
        return str(pdf_specific_file_path)
    
    except Exception as e:
        print(f"Error creating merged Excel file: {e}")
        import traceback
        traceback.print_exc()
        return f"Error creating merged Excel file: {e}"


# ========== MAIN WORKFLOW FUNCTIONS ==========

def process_cvs_with_verification(pdf_file, cv_book_source="", jfws_source=""):
    """
    Process CVs with verification - performs OCR once, then analyzes twice and merges results.
    This optimized approach avoids duplicating the OCR step while still providing verification benefits.
    
    Args:
        pdf_file (str or Path): Path to the PDF file.
        cv_book_source (str): Source of the CV book.
        jfws_source (str): Source of the JFWS.
        
    Returns:
        str: Path to the Excel file with merged results.
    """
    # Ensure temp directory exists before processing
    ensure_temp_dir()
    
    # Check for cancellation before starting
    if check_cancelled():
        print("Processing cancelled before starting")
        return "Processing cancelled"
        
    print("\n===== STEP 1: PDF EXTRACTION (OCR) =====")
    pdf_file = Path(pdf_file)  # Convert to Path object if it's a string
    
    # Perform OCR only once
    try:
        # Perform OCR or load from cache
        all_pages_text = process_pdf(pdf_file)
        if not all_pages_text:
            return "Error: Failed to extract text from PDF"
            
        # Check for cancellation before analysis
        if check_cancelled():
            print("Processing cancelled after OCR")
            return "Processing cancelled after OCR"
            
        print("\n===== STEP 2: FIRST ANALYSIS RUN =====")
        # First analysis run
        print("Running first analysis pass...")
        cv_data1 = get_cv_data(all_pages_text)  # Use regular prompt
        
        # Check for cancellation before second run
        if check_cancelled():
            print("Processing cancelled after first analysis")
            # Still save what we have
            excel_file = export_to_excel(cv_data1, pdf_file, cv_book_source, jfws_source, "single_run")
            return f"Processing cancelled after first analysis. Partial results saved to: {excel_file}"
            
        print("\n===== STEP 3: SECOND ANALYSIS RUN (VERIFICATION) =====")
        # Second analysis run with a different prompt style for verification
        print("Running second analysis pass for verification...")
        # Create a slightly different verification prompt
        verification_prompt = refresh_prompt(verification_mode=True)
        cv_data2 = get_cv_data(all_pages_text, custom_prompt=verification_prompt)
        
        # Check for cancellation before merging
        if check_cancelled():
            print("Processing cancelled after second analysis")
            # Save both results separately
            excel_file1 = export_to_excel(cv_data1, pdf_file, cv_book_source, jfws_source, "run1")
            excel_file2 = export_to_excel(cv_data2, pdf_file, cv_book_source, jfws_source, "run2")
            return f"Processing cancelled before merging. Results saved to: {excel_file1} and {excel_file2}"
        
        print("\n===== STEP 4: MERGING RESULTS =====")
        # Merge results from both runs
        print("Comparing and merging results from both analysis runs...")
        excel_file = compare_and_merge_results(cv_data1, cv_data2, pdf_file, cv_book_source, jfws_source)
        
        return excel_file
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"\n[ERROR] Verification workflow failed: {e}\n{error_details}")
        return f"Error: {str(e)}"

def process_cvs(pdf_file, cv_book_source="", jfws_source=""):
    """
    Process CVs without verification - performs OCR once, then analyzes once.
    This is a simpler and faster approach than the verification workflow.
    
    Args:
        pdf_file (str or Path): Path to the PDF file.
        cv_book_source (str): Source of the CV book.
        jfws_source (str): Source of the JFWS.
        
    Returns:
        str: Path to the Excel file with results.
    """
    # Ensure temp directory exists before processing
    ensure_temp_dir()
    
    # Check for cancellation
    if check_cancelled():
        print("Processing cancelled before starting")
        return "Processing cancelled"
        
    print("\n===== STARTING STANDARD WORKFLOW =====")
    pdf_file = Path(pdf_file)  # Convert to Path object if it's a string
    
    try:
        # STEP 1: Perform OCR (or load from cache)
        print("\n===== STEP 1: PDF EXTRACTION (OCR) =====")
        all_pages_text = process_pdf(pdf_file)
        if not all_pages_text:
            return "Error: Failed to extract text from PDF"
            
        # Check for cancellation
        if check_cancelled():
            print("Processing cancelled after OCR")
            return "Processing cancelled after OCR"
            
        # STEP 2: Analyze the extracted text
        print("\n===== STEP 2: CV DATA EXTRACTION =====")
        cv_data = get_cv_data(all_pages_text)
        
        # Check for cancellation
        if check_cancelled():
            print("Processing cancelled after analysis")
            return "Processing cancelled after analysis"
            
        # STEP 3: Export to Excel
        print("\n===== STEP 3: EXPORTING RESULTS =====")
        excel_file = export_to_excel(cv_data, pdf_file, cv_book_source, jfws_source)
        
        return excel_file
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"\n[ERROR] Standard workflow failed: {e}\n{error_details}")
        return f"Error: {str(e)}"

# ========== MAIN EXECUTION (for testing script directly) ==========

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        pdf_arg = Path(sys.argv[1])
        if pdf_arg.is_file():
             test_pdf_file = pdf_arg
        else:
             print(f"Error: File not found at '{sys.argv[1]}'")
             sys.exit(1)
    else:
        # Default test file if none provided
        test_pdf_file = Path("CV_Book_Small.pdf") # Use a smaller file for quicker testing

    if not test_pdf_file.is_file():
        print(f"Error: Default test PDF file not found: {test_pdf_file}")
        print("Please provide a valid PDF path as a command-line argument or place 'CV_Book_Small.pdf' here.")
        sys.exit(1)

    print(f"--- Running Test on: {test_pdf_file.name} ---")

    # Simulate running the verification workflow
    print("\n--- Testing Dual Analysis (Verification) Workflow ---")
    try:
        result_excel = process_cvs_with_verification(
            test_pdf_file,
            cv_book_source="Test Book",
            jfws_source="Test Fair"
        )
        if result_excel:
            print(f"\n[SUCCESS] Verification workflow finished. Output: {result_excel}")
        else:
             print("\n[FAILURE] Verification workflow finished but export failed.")
    except Exception as e:
        print(f"\n[ERROR] Verification workflow failed: {e}")


    # Simulate running the single analysis workflow (for comparison)
    # print("\n--- Testing Single Analysis Workflow ---")
    # try:
    #     print("Performing OCR (if needed)...")
    #     single_text = process_pdf(test_pdf_file)
    #     if single_text:
    #          print("Analyzing CV data...")
    #          single_response = get_cv_data(single_text)
    #          print("Exporting results...")
    #          single_excel = export_to_excel(
    #               single_response, test_pdf_file, "Test Book Single", "Test Fair Single"
    #          )
    #          if single_excel:
    #               print(f"\n[SUCCESS] Single analysis workflow finished. Output: {single_excel}")
    #          else:
    #               print("\n[FAILURE] Single analysis workflow finished but export failed.")
    #     else:
    #          print("[FAILURE] OCR failed in single analysis workflow.")
    # except Exception as e:
    #     print(f"\n[ERROR] Single analysis workflow failed: {e}")

# Function for external cancellation checks
def check_cancelled():
    """Function that can be overridden by external code to check for cancellation"""
    # Default implementation returns False (no cancellation)
    # This will be replaced by the OCRWorker to provide cancellation functionality
    return False

def refresh_prompt(verification_mode=False):
    """
    Refresh the prompt from Prompt.py, optionally modified for verification.
    
    Args:
        verification_mode (bool): Whether to modify the prompt for verification runs
        
    Returns:
        str: The prompt text
    """
    # Import the master_prompt afresh to ensure latest version
    from importlib import reload
    import Prompt
    reload(Prompt)
    
    # Get the base prompt
    base_prompt = Prompt.master_prompt
    
    if verification_mode:
        # Modify the prompt slightly for verification runs to promote diversity in parsing
        verification_prompt = (
            f"{base_prompt}\n\n"
            "IMPORTANT VERIFICATION GUIDELINES:\n"
            "1. This is a verification run to cross-check previously analyzed data.\n"
            "2. Pay special attention to fields that might be ambiguous or incomplete.\n"
            "3. Try alternative interpretations for fields that could be parsed differently.\n"
            "4. Focus on accuracy rather than speed for this verification pass.\n"
            "5. Consider different ways to normalize or extract data that might have been missed."
        )
        return verification_prompt
    else:
        return base_prompt

def find_cv_boundaries(pdf_file):
    """
    Heuristic: Find the start page of each CV by looking for:
    - Keywords (CV, Resume, Curriculum Vitae)
    - White pages (very little or no text)
    - Headers that look like names (lines with two or more capitalized words)
    Returns a list of page indices (0-based) where each CV starts.
    """
    keywords = ["cv", "resume", "curriculum vitae"]
    boundaries = []
    reader = PyPDF2.PdfReader(str(pdf_file))
    num_pages = len(reader.pages)
    for i in range(num_pages):
        try:
            text = reader.pages[i].extract_text() or ""
            text_lower = text.lower()
            # 1. Keyword-based boundary
            if any(kw in text_lower for kw in keywords):
                boundaries.append(i)
            # 2. White page (very little or no text)
            if len(text.strip()) < 20:
                boundaries.append(i+1)  # Assume next page is a new CV
            # 3. Header with likely name (two or more capitalized words)
            lines = text.splitlines()
            for line in lines[:5]:  # Only check the first few lines
                if re.match(r"^([A-Z][a-z]+\s+){1,}[A-Z][a-z]+$", line.strip()):
                    boundaries.append(i)
                    break
        except Exception as e:
            print(f"Warning: Could not extract text from page {i}: {e}")
    # Always include the first page if not found
    if 0 not in boundaries:
        boundaries = [0] + boundaries
    # Remove duplicates and sort
    boundaries = sorted(set(boundaries))
    return boundaries

def split_pdf_by_cv(pdf_file, cv_per_chunk=5):
    """
    Split the PDF into chunks, each containing up to cv_per_chunk CVs.
    Uses cv_separator to detect CV boundaries, then pikepdf for robust splitting (fallback to PyPDF2).
    Returns a list of temporary PDF file paths.
    """
    # Ensure the temporary directory exists before proceeding
    temp_dir = ensure_temp_dir()
    print(f"Using temporary directory: {temp_dir}")
    
    import tempfile
    import pikepdf
    chunk_files = []
    # Use cv_separator to get CV boundaries (list of dicts with 'pages')
    cv_chunks = cv_separator.detect_and_separate_cvs(str(pdf_file))
    print(f"cv_separator found {len(cv_chunks)} potential CV chunks:")
    for i, chunk_info in enumerate(cv_chunks):
        print(f"  - Chunk {i+1}: Pages {chunk_info.get('pages')}")
    if not cv_chunks or len(cv_chunks) == 0:
        print("cv_separator did not find any CVs, falling back to single chunk.")
        try:
            # Need to determine total pages even for fallback
            num_pages = len(pikepdf.open(str(pdf_file)).pages)
        except Exception:
             num_pages = 0 # Cannot determine pages, chunking will likely fail
        cv_chunks = [{'pages': list(range(num_pages))}]
    # Group CVs into chunks of cv_per_chunk
    grouped = [cv_chunks[i:i+cv_per_chunk] for i in range(0, len(cv_chunks), cv_per_chunk)]
    try:
        print("Attempting PDF split using pikepdf...")
        with pikepdf.open(str(pdf_file)) as pdf:
            for idx, group in enumerate(grouped):
                # Flatten all pages in this group
                pages = [p for cv in group for p in cv['pages']]
                if not pages:
                    print(f"Skipping empty group {idx+1}")
                    continue
                try:
                    new_pdf = pikepdf.Pdf.new()
                    for page_num in pages:
                        new_pdf.pages.append(pdf.pages[page_num])
                        
                    # Generate a unique filename with a timestamp to avoid conflicts
                    chunk_filename = f"chunk_{idx+1}_{int(time.time())}_{random.randint(1000, 9999)}.pdf"
                    output_path = temp_dir / chunk_filename
                    
                    # Save directly to the final path without temp file intermediate step
                    new_pdf.save(str(output_path))
                    chunk_files.append(str(output_path))
                    print(f"[pikepdf] Successfully wrote chunk {idx+1} to {output_path}")
                except Exception as e:
                    print(f"[pikepdf] Error writing chunk {idx+1}: {e}. Skipping this chunk.")
    except Exception as e:
        print(f"[pikepdf] Error opening PDF: {e}. Falling back to PyPDF2.")
        import PyPDF2
        try:
            reader = PyPDF2.PdfReader(str(pdf_file))
            print("Attempting PDF split using PyPDF2 fallback...")
            for idx, group in enumerate(grouped):
                pages = [p for cv in group for p in cv['pages']]
                if not pages:
                    print(f"Skipping empty group {idx+1}")
                    continue
                writer = PyPDF2.PdfWriter()
                for page_num in pages:
                    try:
                        writer.add_page(reader.pages[page_num])
                    except Exception as page_e:
                        print(f"[PyPDF2] Error adding page {page_num} to chunk {idx+1}: {page_e}. Skipping this page.")
                try:
                    # Generate a unique filename with a timestamp to avoid conflicts
                    chunk_filename = f"chunk_{idx+1}_{int(time.time())}_{random.randint(1000, 9999)}.pdf"
                    output_path = temp_dir / chunk_filename
                    
                    # Write directly to the final path
                    with open(output_path, 'wb') as f:
                        writer.write(f)
                    chunk_files.append(str(output_path))
                    print(f"[PyPDF2] Successfully wrote chunk {idx+1} to {output_path}")
                except Exception as write_e:
                    print(f"[PyPDF2] Error writing chunk {idx+1}: {write_e}. Skipping this chunk.")
        except Exception as pypdf_e:
             print(f"[PyPDF2] Fallback failed entirely: {pypdf_e}")
    print(f"split_pdf_by_cv finished, created {len(chunk_files)} chunk files.")
    return chunk_files