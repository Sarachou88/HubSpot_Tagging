# CV Processor App

**A desktop application to automatically process PDF CV files**

---

## 📝 Simple Overview

The CV Processor App lets you:

1. **Enter your Mistral API key** for AI-powered CV analysis.
2. **Select a PDF file** containing multiple CVs.
3. **Choose a CV Book Source** and **Job Fair/Workshop** label (or type your own).
4. **Process** the file to extract structured CV data.
5. **Export** results to an Excel spreadsheet.

All of this happens in a clean, intuitive graphical interface powered by PyQt6.

---

## 🔑 Getting Your Mistral API Key

1. Visit **https://mistral.ai/** and sign up for a free account.
2. In your dashboard, find **API Keys**.
3. Copy your key (it looks like a long alphanumeric string).
4. Paste it into the **API Key** field in the app and click **Save Key**.

Your key is stored securely on your local machine.

---

## 🚀 Quick Start (Step by Step)

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Run the application:
   ```bash
   python cv_processor_app.py
   ```
3. In the **API Configuration** box:
   - Paste your Mistral API key.
   - Click **Save Key**.
4. In **Document Selection**:
   - Click **Select CV File** and open a PDF containing CVs.
   - (Optional) Choose or type a **CV Book Source**.
   - (Optional) Choose or type a **Job Fair / Workshop**.
5. Click **Process CV File**:
   - Watch the progress bar go from 0% to 100%.
   - Read user-friendly messages in the **Progress** and **Log** sections.
6. When finished, choose to open or export the Excel file with your results.

---

## 🔍 Detailed Explanation

### Architecture
- **PyQt6 GUI**: Handles the window, layouts, and user interaction.
- **OCRWorker** (`QThread`): Runs the heavy lifting in background to keep the UI responsive.
- **Signals & Slots**: Communicate progress, stage changes, errors, and completion between thread and main window.
- **Mistral API**: Called to analyze extracted text and identify structured CV fields.

### Workflow Internals
1. **File Import**:
   - The PDF is split into pages.
   - Pages are grouped into chunks to stay within token limits.
2. **Text Extraction**:
   - PyPDF (via OCR module) extracts plain text from each chunk.
3. **Analysis**:
   - The text chunks are sent to the Mistral AI model via API calls.
   - The model returns JSON with parsed CV fields (e.g. name, email, experience).
4. **Progress Updates**:
   - The app parses console output to update the progress bar and logs in plain English.
5. **Error Handling & Cancellation**:
   - You can click **Cancel** anytime; the worker finishes the current chunk and stops.
   - Errors show a dialog with a simple message and optional detailed traceback.
6. **Export**:
   - All parsed CV rows are combined into a DataFrame and saved to an Excel file.
   - The app automatically generates a filename based on the source PDF and timestamp.
   - When processing is complete, a dialog appears asking if you want to open the file.
   - The Excel file is saved in the same directory as the input PDF.

### Code Highlights
- `cv_processor_app.py`: Main window and UI logic
- `OCRWorker` class: Background thread with custom print redirection to capture progress.
- Styled buttons/groups: Reusable functions for consistent theming.
- `requirements.txt`: Lists key dependencies (PyQt6, pandas, openpyxl, etc.)

---

Now you're ready to use, customize, and extend the CV Processor App! If you run into issues, check the logs in-app, or open an issue on GitHub. 