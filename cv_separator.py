import re
from PyPDF2 import PdfReader

def detect_and_separate_cvs(pdf_path):
    """
    Detect and separate multiple CVs in a single PDF file.
    Refined logic to detect boundaries based on keywords, white pages, and name headers.
    Returns a list of dictionaries, each containing the text and page numbers of a CV.
    """
    try:
        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)
        if total_pages == 0:
            return []
        if total_pages == 1:
            text = reader.pages[0].extract_text() or ""
            return [{'text': text, 'pages': [0]}]
        page_texts = []
        for i in range(total_pages):
            try:
                page_texts.append(reader.pages[i].extract_text() or "")
            except Exception as e:
                print(f"Warning: Could not extract text from page {i}: {e}. Using empty string.")
                page_texts.append("")
        cv_markers = ["cv", "curriculum vitae", "resume", "profile"]
        name_pattern = re.compile(r"^([A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ\'-]+(?:\s+[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ\'-]+){1,3})$") # 2 to 4 capitalized words
        cv_boundaries = {0}  # Always start with the first page (use a set for auto-deduplication)
        for i in range(total_pages):
            current_page_text = page_texts[i]
            current_page_lower = current_page_text.lower()
            # Check first 100 chars for keywords
            if any(marker in current_page_lower[:100] for marker in cv_markers):
                cv_boundaries.add(i)
            # Check for white page (minimal text)
            if len(current_page_text.strip()) < 20 and (i + 1) < total_pages:
                cv_boundaries.add(i + 1) # Assume next page starts a new CV
            # Check top lines for name pattern
            lines = current_page_text.strip().split('\n')
            for line_num, line in enumerate(lines[:5]): # Check first 5 lines
                if name_pattern.match(line.strip()):
                    # Heuristic: if a name is found very early, it's likely a new CV start
                    cv_boundaries.add(i)
                    break # Found a name, no need to check other lines on this page
        sorted_boundaries = sorted(list(cv_boundaries))
        # Filter out boundaries that are too close together (e.g., page 5 and 6 found)
        final_boundaries = []
        if sorted_boundaries:
            final_boundaries.append(sorted_boundaries[0])
            for j in range(1, len(sorted_boundaries)):
                if sorted_boundaries[j] > final_boundaries[-1]: # Only add if it's a later page
                     # Optional: Add minimum page distance heuristic if needed
                     # if sorted_boundaries[j] - final_boundaries[-1] > 1:
                     final_boundaries.append(sorted_boundaries[j])
        if len(final_boundaries) <= 1:
            print("Separator: Only found start boundary or none. Treating as single CV.")
            full_text = "\n".join(page_texts)
            return [{'text': full_text, 'pages': list(range(total_pages))}]
        # Create separate CVs
        final_boundaries.append(total_pages)  # Add end boundary
        separated_cvs = []
        for i in range(len(final_boundaries) - 1):
            start_page = final_boundaries[i]
            end_page = final_boundaries[i+1] # This boundary is the start of the *next* CV
            pages_in_cv = list(range(start_page, end_page))
            if not pages_in_cv: # Skip if start and end are the same page
                 continue
            text = "\n".join(page_texts[start_page:end_page])
            separated_cvs.append({'text': text, 'pages': pages_in_cv})
            print(f"Separator: Detected CV from page {start_page} to {end_page-1}")
        return separated_cvs
    except Exception as e:
        print(f"Error separating CVs: {e}")
        try:
            reader = PdfReader(pdf_path)
            total_pages = len(reader.pages)
            def extract_text_from_pdf(pdf_path):
                try:
                    reader = PdfReader(pdf_path)
                    text = ""
                    for page in reader.pages:
                         try:
                             text += page.extract_text() + "\n"
                         except Exception:
                             text += "\n" # Add newline even if page extraction fails
                    return text
                except Exception as e:
                    print(f"Error extracting text from PDF {pdf_path}: {e}")
                    return ""
            text = extract_text_from_pdf(pdf_path)
            print("Separator: Fallback to single CV due to error.")
            return [{'text': text, 'pages': list(range(total_pages))}]
        except Exception as ex:
            print(f"Ultimate fallback due to: {ex}")
            return [{'text': '', 'pages': [0]}]
