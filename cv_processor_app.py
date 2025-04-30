import sys
import os
import re  # Add import for regular expressions
from pathlib import Path
from PyQt6.QtWidgets import (QApplication, QMainWindow, QPushButton, QVBoxLayout, QHBoxLayout,
                           QWidget, QFileDialog, QLabel, QComboBox, QCheckBox, QProgressBar,
                           QTextEdit, QSplitter, QMessageBox, QGroupBox, QFrame, QSizePolicy,
                           QLineEdit, QInputDialog, QDialog, QGridLayout, QDialogButtonBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QSettings
from PyQt6.QtGui import QFont, QIcon, QColor, QPalette, QPixmap

# Import the OCR functionality from the existing script
# These functions now operate differently (OCR once, analyze based on text)
from OCR import process_cvs_with_verification, process_pdf, get_cv_data, export_to_excel

# Define a modern color palette with updated colors
COLORS = {
    'primary': '#1E3A8A',      # Deep blue
    'secondary': '#3B82F6',    # Bright blue
    'accent': '#10B981',       # Green
    'light': '#E5E7EB',        # Light gray
    'dark': '#1F2937',         # Dark gray
    'success': '#059669',      # Green
    'warning': '#F59E0B',      # Orange
    'error': '#EF4444',        # Red
    'light_bg': '#F9FAFB',      # Very light background
    'primary_dark': '#1A3275',  # Darker version of primary
    'primary_darker': '#172B60' # Even darker version of primary
}

class ApiKeyDialog(QDialog):
    """Dialog for inputting API key"""
    def __init__(self, parent=None, current_key=None):
        super().__init__(parent)
        self.setWindowTitle("Mistral API Key")
        self.setMinimumWidth(400)
        
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        # Explanation label
        info_label = QLabel("Please enter your Mistral API key. This key will be stored securely on your device.")
        info_label.setWordWrap(True)
        info_label.setStyleSheet(f"color: {COLORS['dark']}; font-size: 13px;")
        layout.addWidget(info_label)
        
        # API key input field
        key_layout = QHBoxLayout()
        key_label = QLabel("API Key:")
        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)  # Hide the key as it's typed
        if current_key:
            self.key_input.setText(current_key)
        
        key_layout.addWidget(key_label)
        key_layout.addWidget(self.key_input)
        layout.addLayout(key_layout)
        
        # Link to get API key
        link_label = QLabel("<a href='https://mistral.ai/'>Don't have an API key? Get one from Mistral AI</a>")
        link_label.setOpenExternalLinks(True)
        layout.addWidget(link_label)
        
        # Buttons
        button_box = QDialogButtonBox()
        
        # Create styled OK button using the primary button style
        ok_button = create_primary_button("OK")
        ok_button.setCursor(Qt.CursorShape.PointingHandCursor)
        button_box.addButton(ok_button, QDialogButtonBox.ButtonRole.AcceptRole)
        
        # Create styled Cancel button using the secondary button style
        cancel_button = create_secondary_button("Cancel")
        cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        button_box.addButton(cancel_button, QDialogButtonBox.ButtonRole.RejectRole)
        
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        
        layout.addWidget(button_box)
    
    def get_api_key(self):
        return self.key_input.text().strip()

class OCRWorker(QThread):
    """Worker thread to run OCR processing in the background"""
    # Enhanced signals to communicate with the main thread
    progress = pyqtSignal(str)  # General progress messages
    progress_detail = pyqtSignal(str)  # More detailed progress information
    progress_percentage = pyqtSignal(int, int)  # Current, total values for progress bar
    stage_changed = pyqtSignal(str)  # Major processing stage changes
    file_saved = pyqtSignal(str)  # When a file is successfully saved
    finished = pyqtSignal(str)  # Processing completed successfully
    error = pyqtSignal(str)  # Error occurred during processing

    def __init__(self, pdf_file, cv_book_source, jfws_source, run_analysis_twice, api_key):
        super().__init__()
        self.pdf_file = pdf_file
        self.cv_book_source = cv_book_source
        self.jfws_source = jfws_source
        # Renamed for clarity: this flag controls analysis, not OCR runs
        self.run_analysis_twice = run_analysis_twice
        self.api_key = api_key
        
        # Flag for cancellation support
        self.cancelled = False
        
    def cancel(self):
        """Signal the worker to cancel processing"""
        self.cancelled = True
        self.progress.emit("Cancellation requested. Stopping after current operation completes...")

    def run(self):
        try:
            self.stage_changed.emit("Initializing")
            self.progress.emit("Starting CV processing...")
            
            # Import OCR module here to ensure it's accessible in the thread
            import OCR
            
            # Set up output redirection to capture all prints from the OCR module
            import io
            import sys
            import contextlib
            import re
            import builtins
            import traceback
            
            # Create a custom print function that emits to our progress signal
            # and also parses it for progress information
            original_print = print
            def custom_print(*args, **kwargs):
                # Get the string representation
                output_buffer = io.StringIO()
                with contextlib.redirect_stdout(output_buffer):
                    original_print(*args, **kwargs)
                output = output_buffer.getvalue().strip()
                
                if output:  # Only emit non-empty strings
                    # Try to extract progress information
                    if "===== STEP " in output:
                        # Extract and emit stage information
                        stage_match = re.search(r"===== STEP \d+: (.+?) =====", output)
                        if stage_match:
                            self.stage_changed.emit(stage_match.group(1))
                    
                    # Extract chunk processing information
                    chunk_match = re.search(r"[Cc]hunk (\d+)/(\d+)", output)
                    if chunk_match:
                        current = int(chunk_match.group(1))
                        total = int(chunk_match.group(2))
                        self.progress_percentage.emit(current, total)
                        self.progress_detail.emit(f"Processing chunk {current} of {total}")
                    
                    # Extract page processing information
                    page_match = re.search(r"Extracted text from (\d+) pages", output)
                    if page_match:
                        pages = int(page_match.group(1))
                        self.progress_detail.emit(f"Extracted {pages} pages")
                    
                    # Extract CV count information
                    cv_match = re.search(r"Total CVs extracted: (\d+)", output)
                    if cv_match:
                        cv_count = int(cv_match.group(1))
                        self.progress_detail.emit(f"Found {cv_count} CVs")
                    
                    # Extract file saving information
                    file_match = re.search(r"(Exported|saved).+?to: (.+\.xlsx)", output)
                    if file_match:
                        file_path = file_match.group(2).strip()
                        self.file_saved.emit(file_path)
                    
                    # Always emit the full message
                    self.progress.emit(output)
                    
                # Also print to the original stdout for console debugging
                original_print(*args, **kwargs)
            
            # Replace the built-in print with our custom version
            builtins.print = custom_print
            
            # Install cancellation check hook in OCR module if possible
            def check_cancelled():
                if self.cancelled:
                    raise Exception("Processing cancelled by user")
                return False
                
            try:
                # Attach cancellation checker to OCR module
                OCR.check_cancelled = check_cancelled
                
                # Use the proper initialization function
                OCR.initialize_client(self.api_key)
                
                # Process based on selected mode
                if self.cancelled:
                    raise Exception("Processing cancelled by user before starting")
                    
                if self.run_analysis_twice:
                    # Use the dual analysis verification process
                    self.stage_changed.emit("Running verification workflow")
                    self.progress.emit("Running OCR once, then analysis twice for verification...")
                    excel_file = self._run_with_verification(OCR)
                else:
                    # Run OCR once and analysis once
                    self.stage_changed.emit("Running standard workflow")
                    self.progress.emit("Running OCR once, then analysis once...")
                    excel_file = self._run_once(OCR)
                
                if self.cancelled:
                    self.progress.emit("Processing was cancelled. Partial results may have been saved.")
                else:
                    self.finished.emit(f"Processing complete! Results saved to: {excel_file}")
            finally:
                # Restore the original print function
                builtins.print = original_print
                
        except Exception as e:
            error_details = traceback.format_exc()
            
            if self.cancelled:
                self.error.emit("Processing was cancelled by user.")
            else:
                self.error.emit(f"Error during processing: {str(e)}\n\n{error_details}")

    def _run_with_verification(self, OCR):
        """Run OCR once, then analyze twice with verification and merging"""
        self.progress.emit("Performing OCR (if not cached)...")
        self.progress_detail.emit("Extracting text from PDF")
        self.progress_percentage.emit(0, 4)  # 4 major steps in verification
        
        # This function now handles the single OCR + dual analysis internally
        excel_file = OCR.process_cvs_with_verification(
            self.pdf_file,
            cv_book_source=self.cv_book_source,
            jfws_source=self.jfws_source
        )
        
        return excel_file

    def _run_once(self, OCR):
        """Run OCR once, then analyze once"""
        self.progress.emit("Performing OCR (if not cached)...")
        self.progress_detail.emit("Extracting text from PDF")
        self.progress_percentage.emit(0, 3)  # 3 major steps in standard workflow
        
        # Check for cancellation
        if self.cancelled:
            raise Exception("Processing cancelled by user")
            
        all_pages_text = OCR.process_pdf(self.pdf_file)  # Simplified call
        self.progress_percentage.emit(1, 3)  # OCR completed

        self.progress.emit("Analyzing CV data...")
        self.progress_detail.emit("Extracting structured data from text")
        
        # Check for cancellation
        if self.cancelled:
            raise Exception("Processing cancelled by user")
            
        response_content = OCR.get_cv_data(all_pages_text)
        self.progress_percentage.emit(2, 3)  # Analysis completed

        self.progress.emit("Exporting results to Excel...")
        self.progress_detail.emit("Creating Excel spreadsheet")
        
        # Check for cancellation
        if self.cancelled:
            raise Exception("Processing cancelled by user")
            
        excel_file = OCR.export_to_excel(
            response_content,
            self.pdf_file,
            cv_book_source=self.cv_book_source,
            jfws_source=self.jfws_source
        )
        self.progress_percentage.emit(3, 3)  # Export completed

        return excel_file

# --- StyledGroupBox and StyledButton remain the same ---
class StyledGroupBox(QGroupBox):
    """Custom styled group box with rounded corners and border"""
    def __init__(self, title="", parent=None):
        super().__init__(title, parent)
        self.setStyleSheet(f"""
            QGroupBox {{
                background-color: white;
                border: 1px solid {COLORS['light']};
                border-radius: 8px;
                margin-top: 1em;
                font-weight: bold;
                color: {COLORS['primary']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }}
        """)

class StyledButton(QPushButton):
    """Custom styled button with hover effects"""
    def __init__(self, text="", icon=None, is_primary=True, parent=None):
        super().__init__(text, parent)

        if icon:
            self.setIcon(icon)
            self.setIconSize(QSize(18, 18))

        color = COLORS['primary'] if is_primary else COLORS['secondary']
        hover_color = COLORS['dark'] if is_primary else COLORS['accent']
        text_color = "white"

        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                color: {text_color};
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {hover_color};
            }}
            QPushButton:pressed {{
                background-color: {COLORS['dark']};
            }}
            QPushButton:disabled {{
                background-color: {COLORS['light']};
                color: #95a5a6;
            }}
        """)

        self.setCursor(Qt.CursorShape.PointingHandCursor)
# --- End of unchanged styled widgets ---


class CVProcessorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("CVProcessor", "MistralAPI")
        self.api_key = self.settings.value("api_key", "")
        self.init_ui()
        
        # Set even smaller window size
        self.setMinimumSize(800, 480)
        self.resize(850, 550)

    def init_ui(self):
        """Initialize the user interface in a clean grid layout."""
        # Paths for resources
        logo_path = os.path.join(os.path.dirname(__file__), 'resources', 'ormittalentV3.png')
        icon_path = os.path.join(os.path.dirname(__file__), 'resources', 'assessmentReport.ico')
        self.setWindowTitle("CV Processor App")
        self.setWindowIcon(QIcon(icon_path))

        # Main container with padding
        main_container = QWidget()
        main_container.setStyleSheet(f"""
            QWidget {{
                background-color: {COLORS['light_bg']};
                border-radius: 8px;
            }}
        """)
        main_layout = QVBoxLayout(main_container)
        main_layout.setContentsMargins(15, 15, 15, 15)  # Further reduced padding
        main_layout.setSpacing(10)  # Further reduced spacing
        
        # Header with logo
        header = QHBoxLayout()
        logo_label = QLabel()
        pixmap = QPixmap(logo_path).scaledToHeight(45, Qt.TransformationMode.SmoothTransformation)  # Smaller logo
        logo_label.setPixmap(pixmap)
        header.addWidget(logo_label, alignment=Qt.AlignmentFlag.AlignLeft)
        header.addStretch()
        main_layout.addLayout(header)
        
        # Create content layout
        content = QVBoxLayout()
        content.setSpacing(10)
        
        # API Key section
        api_section = QGroupBox("API Configuration")
        api_section.setStyleSheet(f"""
            QGroupBox {{
                background-color: white;
                border: 1px solid {COLORS['light']};
                border-radius: 8px;
                margin-top: 0.8em;
                padding: 15px;
                font-weight: bold;
                color: {COLORS['primary']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px;
                font-size: 13px;
            }}
        """)
        api_layout = QGridLayout(api_section)
        api_layout.setContentsMargins(10, 15, 10, 10)
        api_layout.setSpacing(8)
        
        api_key_label = QLabel("API Key:")
        api_key_label.setStyleSheet("font-size: 12px;")
        api_layout.addWidget(api_key_label, 0, 0)
        
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setText(self.api_key)
        self.api_key_input.setMinimumHeight(28)
        
        # Set a darker background for password field to create contrast with the dots
        self.api_key_input.setStyleSheet(f"""
            QLineEdit {{
                border: 1px solid {COLORS['light']};
                border-radius: 5px;
                padding: 4px 8px;
                background-color: #F1F5F9; /* Slightly darker background */
                font-size: 13px; /* Larger text */
                color: black; /* Black text for maximum contrast */
                font-weight: bold; /* Bold makes dots more visible */
            }}
            QLineEdit:focus {{
                border: 2px solid {COLORS['secondary']};
            }}
        """)
        api_layout.addWidget(self.api_key_input, 0, 1)
        
        save_btn = QPushButton("Save Key")
        save_btn.setMinimumHeight(28)  # Even smaller height
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['secondary']};
                color: white;
                border: none;
                border-radius: 5px;
                padding: 4px 10px;
                font-weight: bold;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: #2563EB;
            }}
            QPushButton:pressed {{
                background-color: #1D4ED8;
            }}
        """)
        save_btn.clicked.connect(self.save_api_key)
        api_layout.addWidget(save_btn, 0, 2)
        
        content.addWidget(api_section)
        
        # File selection section
        file_section = QGroupBox("Document Selection")
        file_section.setStyleSheet(f"""
            QGroupBox {{
                background-color: white;
                border: 1px solid {COLORS['light']};
                border-radius: 8px;
                margin-top: 0.8em;
                padding: 15px;
                font-weight: bold;
                color: {COLORS['primary']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px;
                font-size: 13px;
            }}
        """)
        file_layout = QGridLayout(file_section)
        file_layout.setContentsMargins(10, 15, 10, 10)  # Further reduced padding
        file_layout.setSpacing(8)  # Further reduced spacing
        
        cv_file_label = QLabel("CV File:")
        cv_file_label.setStyleSheet("font-size: 12px;")
        file_layout.addWidget(cv_file_label, 0, 0)
        
        self.file_input = QLineEdit()
        self.file_input.setReadOnly(True)
        self.file_input.setMinimumHeight(28)
        
        # Use darker background color and ensure text has high contrast
        self.file_input.setStyleSheet(f"""
            QLineEdit {{
                border: 1px solid {COLORS['light']};
                border-radius: 5px;
                padding: 4px 8px;
                background-color: #F1F5F9; /* Slightly darker background */
                font-size: 12px;
                color: black; /* Black text for maximum contrast */
                font-weight: bold;
            }}
        """)
        file_layout.addWidget(self.file_input, 0, 1)
        
        self.file_btn = QPushButton("Select CV File")
        self.file_btn.setMinimumHeight(28)  # Even smaller height
        self.file_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.file_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['primary']};
                color: white;
                border: none;
                border-radius: 5px;
                padding: 4px 10px;
                font-weight: bold;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['primary_dark']};
            }}
            QPushButton:pressed {{
                background-color: {COLORS['primary_darker']};
            }}
        """)
        self.file_btn.clicked.connect(self.select_file)
        file_layout.addWidget(self.file_btn, 0, 2)
        
        # Source selection - CV Book
        source_label = QLabel("CV Book Source:")
        source_label.setStyleSheet("font-size: 12px;")
        file_layout.addWidget(source_label, 1, 0)
        
        self.cv_book_combo = QComboBox()
        self.cv_book_combo.setEditable(True)  # Allow manual input
        self.cv_book_combo.setMinimumHeight(28)  # Even smaller height
        self.cv_book_combo.setStyleSheet(f"""
            QComboBox {{
                border: 1px solid {COLORS['light']};
                border-radius: 5px;
                padding: 4px 8px;
                background-color: white;
                font-size: 12px;
                color: {COLORS['dark']};
            }}
            QComboBox:focus {{
                border: 2px solid {COLORS['secondary']};
            }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                border: none;
                width: 20px;
                background-color: #F3F4F6;
                border-left: 1px solid #E5E7EB;
                border-top-right-radius: 5px;
                border-bottom-right-radius: 5px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid {COLORS['dark']};
                width: 0;
                height: 0;
                margin-right: 6px;
            }}
            QComboBox QAbstractItemView {{
                background-color: white;
                border: 1px solid {COLORS['light']};
                border-radius: 0px 0px 5px 5px;
                selection-background-color: {COLORS['light_bg']};
                selection-color: {COLORS['primary']};
                color: {COLORS['dark']};  /* Text color for dropdown items */
            }}
            QComboBox QLineEdit {{
                border: none;
                background-color: white;
                selection-background-color: {COLORS['secondary']};
                selection-color: white;
                padding: 0px 3px;
                color: {COLORS['dark']};  /* Text color for the editable field */
            }}
        """)
        cv_books = ['', 'CV Book AMS', 'CV Book Ekonomika', 'CV Book HEC Liège',
                   'CV Book Inisol', 'CV Book KEPS', 'CV Book LSM', 'CV Book UA',
                   'CV Book UCL Mons', 'CV Book VEK', 'CV Book ICHEC', 'CV Book AFC Leuven',
                   'CV Book AFC Gent', 'CV Book ABSOC', 'CV Book UHasselt', 'CV Book Vlerick',
                   'CV Book Solvay', 'CV Book UGent', 'CV Book UCL Mons', 'CV Book AFD',
                   'CV Book Groep T', 'CV Book Jobhappen Kortrijk']
        self.cv_book_combo.addItems(cv_books)
        file_layout.addWidget(self.cv_book_combo, 1, 1, 1, 2)
        
        # Job Fair / Workshop
        jfws_label = QLabel("Job Fair / Workshop:")
        jfws_label.setStyleSheet("font-size: 12px;")
        file_layout.addWidget(jfws_label, 2, 0)
        
        self.jfws_combo = QComboBox()
        self.jfws_combo.setEditable(True)  # Allow manual input
        self.jfws_combo.setMinimumHeight(28)  # Even smaller height
        self.jfws_combo.setStyleSheet(f"""
            QComboBox {{
                border: 1px solid {COLORS['light']};
                border-radius: 5px;
                padding: 4px 8px;
                background-color: white;
                font-size: 12px;
                color: {COLORS['dark']};
            }}
            QComboBox:focus {{
                border: 2px solid {COLORS['secondary']};
            }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                border: none;
                width: 20px;
                background-color: #F3F4F6;
                border-left: 1px solid #E5E7EB;
                border-top-right-radius: 5px;
                border-bottom-right-radius: 5px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid {COLORS['dark']};
                width: 0;
                height: 0;
                margin-right: 6px;
            }}
            QComboBox QAbstractItemView {{
                background-color: white;
                border: 1px solid {COLORS['light']};
                border-radius: 0px 0px 5px 5px;
                selection-background-color: {COLORS['light_bg']};
                selection-color: {COLORS['primary']};
                color: {COLORS['dark']};  /* Text color for dropdown items */
            }}
            QComboBox QLineEdit {{
                border: none;
                background-color: white;
                selection-background-color: {COLORS['secondary']};
                selection-color: white;
                padding: 0px 3px;
                color: {COLORS['dark']};  /* Text color for the editable field */
            }}
        """)
        jfws_list = ['', 'BG Ekonomika', 'Enactus', 'JF ABSOC', 'JF AMS', 'JF Ekonomika',
                    'JF Ekonomika Kiesweek', 'JF HEC', 'JF HEC Liège', 'JF ICHEC',
                    'JF Inisol', 'JF IT Ekonomika', 'JF KUL', 'JF LSM', 'JF Solvay',
                    'JF UAntwerpen', 'JF UGent', 'JF UHasselt', 'JF VEK', 'JF Vlerick',
                    'JF VUB', 'JF Kortrijk', 'JF UCL Mons', 'JF UHasselt', 'Unamur Career center',
                    'WS AFC Gent', 'WS AFC Leuven', 'WS AMS', 'WS Ekonomika', 'WS HEC Liège',
                    'WS ICHEC', 'WS UAntwerpen', 'WS UGent', 'WS VEK', 'WS NHiTec',
                    'WS Le Wagon', 'WS Junior Consulting Louvain', 'WS LSM']
        self.jfws_combo.addItems(jfws_list)
        file_layout.addWidget(self.jfws_combo, 2, 1, 1, 2)
        
        content.addWidget(file_section)
        
        # Progress section
        progress_section = QGroupBox("Progress")
        progress_section.setStyleSheet(f"""
            QGroupBox {{
                background-color: white;
                border: 1px solid {COLORS['light']};
                border-radius: 8px;
                margin-top: 0.8em;
                padding: 15px;
                font-weight: bold;
                color: {COLORS['primary']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px;
                font-size: 13px;
            }}
        """)
        progress_layout = QVBoxLayout(progress_section)
        progress_layout.setContentsMargins(10, 15, 10, 10)  # Further reduced padding
        progress_layout.setSpacing(8)  # Further reduced spacing
        
        # Stage and detail
        self.progress_stage = QLabel("Ready")
        self.progress_stage.setStyleSheet(f"font-weight: bold; color: {COLORS['primary']}; font-size: 14px;")
        progress_layout.addWidget(self.progress_stage)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")  # Show percentage
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setMinimumHeight(18)  # Smaller height
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: none;
                border-radius: 9px;
                text-align: center;
                height: 18px;
                background-color: {COLORS['light_bg']};
                margin-top: 3px;
                margin-bottom: 3px;
                font-weight: bold;
                font-size: 11px;
            }}
            QProgressBar::chunk {{
                background-color: {COLORS['secondary']};
                border-radius: 9px;
            }}
        """)
        self.progress_bar.hide()
        progress_layout.addWidget(self.progress_bar)
        
        self.progress_detail = QLabel("")
        self.progress_detail.setStyleSheet(f"color: {COLORS['dark']}; font-size: 14px;")  # Larger font
        self.progress_detail.setWordWrap(True)  # Allow text wrapping for long messages
        progress_layout.addWidget(self.progress_detail)
        
        content.addWidget(progress_section)
        
        # Action buttons 
        action_layout = QHBoxLayout()
        action_layout.setSpacing(8)  # Further reduced spacing
        action_layout.setContentsMargins(0, 5, 0, 5)  # Minimal vertical padding

        self.process_button = QPushButton("Process CV File")
        self.process_button.setMinimumHeight(36)  # Even smaller height
        self.process_button.setMinimumWidth(140)  # Smaller width
        self.process_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.process_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['accent']};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: bold;
                font-size: 13px;
                letter-spacing: 0.5px;
            }}
            QPushButton:hover {{
                background-color: #0D9488;
            }}
            QPushButton:pressed {{
                background-color: #047857;
            }}
            QPushButton:disabled {{
                background-color: #9CA3AF;
                color: white;
            }}
        """)
        self.process_button.setEnabled(False)
        self.process_button.clicked.connect(self.process_file)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setMinimumHeight(36)  # Even smaller height
        self.cancel_button.setMinimumWidth(80)  # Smaller width
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.setStyleSheet(f"""
            QPushButton {{
                background-color: white;
                color: {COLORS['dark']};
                border: 2px solid {COLORS['light']};
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: bold;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: #F3F4F6;
                border-color: #D1D5DB;
            }}
            QPushButton:pressed {{
                background-color: #E5E7EB;
            }}
            QPushButton:disabled {{
                background-color: #E5E7EB;
                color: #6B7280;
                border-color: #D1D5DB;
            }}
        """)
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_processing)

        # Center the buttons for better appearance
        action_layout.addStretch(1)  # Add stretch before buttons
        action_layout.addWidget(self.process_button)
        action_layout.addWidget(self.cancel_button)
        action_layout.addStretch(1)  # Add stretch after buttons
        
        content.addLayout(action_layout)
        content.addStretch()
        
        main_layout.addLayout(content)

        # Set central widget
        self.setCentralWidget(main_container)

    def save_api_key(self):
        """Save API key from the input field and persist it."""
        key = self.api_key_input.text().strip()
        if key:
            self.api_key = key
            self.settings.setValue("api_key", key)
        else:
            QMessageBox.warning(self, "API Key Error", "API key cannot be empty.")

    def select_file(self):
        """Open file dialog to select a PDF file"""
        file_dialog = QFileDialog()
        file_path, _ = file_dialog.getOpenFileName(
            self, "Select CV PDF File", "", "PDF Files (*.pdf)"
        )

        if file_path:
            self.pdf_file_path = Path(file_path)
            self.file_input.setText(self.pdf_file_path.name)
            self.process_button.setEnabled(True)

    def process_file(self):
        """Process the selected CSV file"""
        if not self.file_input.text():
            QMessageBox.warning(self, "Missing File", "Please select a CV file first.")
            return
            
        if not self.api_key:
            QMessageBox.warning(self, "Missing API Key", "Please set your API key first.")
            return

        # Update UI state
        self.process_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.file_btn.setEnabled(False)
        self.progress_bar.show()
        self.progress_bar.setValue(0)
        
        # Get selected CV book source
        cv_book_source = self.cv_book_combo.currentText()
        jfws_source = self.jfws_combo.currentText()

        # Start the OCR worker with proper parameters
        self.worker = OCRWorker(
            pdf_file=self.pdf_file_path,
            cv_book_source=cv_book_source,
            jfws_source=jfws_source,
            run_analysis_twice=False,  # Standard single analysis
            api_key=self.api_key
        )
        
        # Connect signals
        self.worker.progress.connect(self.update_progress)
        self.worker.progress_detail.connect(self.update_progress_detail)
        self.worker.progress_percentage.connect(self.update_progress_percentage)
        self.worker.stage_changed.connect(self.update_stage)
        self.worker.file_saved.connect(self.on_file_saved)
        self.worker.finished.connect(self.on_processing_finished)
        self.worker.error.connect(self.on_processing_error)
        
        # Start the worker thread
        self.worker.start()

    def update_progress(self, progress_message):
        """Update the progress detail text"""
        self.progress_detail.setText(progress_message)
        
    def update_progress_percentage(self, current, total):
        """Update the progress bar with new values"""
        if total > 0:
            # Convert to percentage for display (0-100)
            percentage = min(round((current / total) * 100), 100)
            self.progress_bar.setValue(percentage)
            
            # Add a human-friendly message about progress
            if percentage < 100:
                self.progress_detail.setText(f"Processing: {percentage}% complete ({current} of {total})")
            else:
                self.progress_detail.setText("Processing complete!")
        
    def update_stage(self, stage):
        """Update the processing stage indicator with user-friendly labels"""
        # Make the stage name more user-friendly
        friendly_stage = stage
        
        # Map technical stage names to more user-friendly ones
        stage_map = {
            "Initializing": "Getting ready...",
            "Running verification workflow": "Starting CV analysis with verification",
            "Running standard workflow": "Starting CV analysis",
            "OCR Processing": "Reading text from PDF",
            "Text Extraction": "Extracting text from pages",
            "Analyzing": "Understanding CV content",
            "Data Extraction": "Extracting information from CVs",
            "Exporting": "Saving results to Excel"
        }
        
        if stage in stage_map:
            friendly_stage = stage_map[stage]
            
        self.progress_stage.setText(friendly_stage)
        
    def on_file_saved(self, file_path):
        """Handle notification that a file was saved"""
        pass  # No logging needed

    def toggle_ui(self, enabled):
        """Toggle UI elements enabled/disabled state"""
        # Main controls
        self.file_btn.setEnabled(enabled)
        self.process_button.setEnabled(enabled and hasattr(self, 'pdf_file_path'))
        self.cv_book_combo.setEnabled(enabled)
        self.jfws_combo.setEnabled(enabled)
        
        # Cancel button is enabled when processing (not enabled)
        self.cancel_button.setEnabled(not enabled and hasattr(self, 'worker') and self.worker.isRunning())
        
        # Progress indicators
        if enabled:
            self.progress_bar.hide()
            self.progress_stage.setText("Ready")
            self.progress_detail.setText("")
        else:
            self.progress_bar.show()

    def on_processing_finished(self, message):
        """Handle completion of processing"""
        self.toggle_ui(True)

        # Extract the file path from the message
        file_path = ""
        if "Results saved to:" in message:
            file_path = message.split("Results saved to: ")[-1].strip()
        elif "saved to:" in message:
            file_path = message.split("saved to: ")[-1].strip()
            
        if not file_path or not os.path.exists(file_path):
            QMessageBox.warning(self, "Warning", "Could not determine the output file path from the message.")
            file_path = ""

        msgBox = QMessageBox(self)
        msgBox.setWindowTitle('Processing Complete')
        msgBox.setText("Processing completed successfully!")
        
        if file_path:
            msgBox.setInformativeText("Would you like to open the Excel file?")
            msgBox.setDetailedText(f"File: {file_path}")
        else:
            msgBox.setInformativeText("The data has been processed, but the file path could not be determined.")
        
        msgBox.setIcon(QMessageBox.Icon.Information)
        msgBox.setStyleSheet(f"""
            QMessageBox {{ background-color: white; color: {COLORS['dark']}; }}
            QLabel {{ color: {COLORS['dark']}; }}
            QPushButton {{ background-color: {COLORS['secondary']}; color: white; border: none; border-radius: 4px; padding: 6px 12px; min-width: 80px; font-weight: bold; }}
            QPushButton:hover {{ background-color: {COLORS['primary']}; }}
        """)
        
        if file_path:
            yes_button = msgBox.addButton("Open Excel File", QMessageBox.ButtonRole.YesRole)
            no_button = msgBox.addButton("Close", QMessageBox.ButtonRole.NoRole)
            msgBox.exec()

            if msgBox.clickedButton() == yes_button and file_path:
                try:
                    if sys.platform == 'win32':
                        os.startfile(file_path)
                    elif sys.platform == 'darwin': # macOS
                        subprocess.call(('open', file_path))
                    else: # Linux
                        subprocess.call(('xdg-open', file_path))
                except Exception as e:
                    QMessageBox.warning(self, "Open File Error", 
                                       f"Could not automatically open the file:\n{file_path}\n\nPlease open it manually.\nError: {e}")
        else:
            close_button = msgBox.addButton("Close", QMessageBox.ButtonRole.NoRole)
            msgBox.exec()

    def on_processing_error(self, error_message):
        """Handle error during processing"""
        self.toggle_ui(True)

        error_box = QMessageBox(self)
        error_box.setWindowTitle('Processing Error')
        error_box.setText("An error occurred during CV processing.")
        
        # Use setDetailedText for long tracebacks if needed, keep InformativeText short
        if len(error_message) > 300:
             error_box.setInformativeText(error_message[:300] + "...")
             error_box.setDetailedText(error_message)
        else:
            error_box.setInformativeText(error_message)
            
        error_box.setIcon(QMessageBox.Icon.Critical)
        error_box.setStyleSheet(f"""
            QMessageBox {{ background-color: white; }}
            QLabel {{ color: {COLORS['dark']}; }}
            QTextEdit {{ background-color: {COLORS['light_bg']}; border: 1px solid {COLORS['light']}; border-radius: 4px; padding: 8px; color: {COLORS['error']}; font-family: monospace; min-width: 400px; }}
            QPushButton {{ background-color: {COLORS['secondary']}; color: white; border: none; border-radius: 4px; padding: 6px 12px; min-width: 80px; font-weight: bold; }}
            QPushButton:hover {{ background-color: {COLORS['primary']}; }}
        """)
        error_box.exec()

    def cancel_processing(self):
        """Cancel the current processing task"""
        if hasattr(self, 'worker') and self.worker.isRunning():
            reply = QMessageBox.question(
                self, 'Confirm Cancellation', 
                "Are you sure you want to cancel processing?\nAny progress will be lost.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.worker.cancel()
                self.progress_stage.setText("Cancelling...")
                self.progress_detail.setText("Waiting for operations to complete safely...")

    def update_progress_detail(self, detail_message):
        """Update the progress detail text"""
        self.progress_detail.setText(detail_message)

def create_primary_button(text):
    """Create a primary styled button"""
    button = QPushButton(text)
    button.setStyleSheet(f"""
        QPushButton {{
            background-color: {COLORS['primary']};
            color: white;
            border: none;
            padding: 8px 16px;
            font-weight: bold;
            border-radius: 6px;
        }}
        QPushButton:hover {{
            background-color: {COLORS['primary_dark']};
        }}
        QPushButton:pressed {{
            background-color: {COLORS['primary_darker']};
        }}
        QPushButton:disabled {{
            background-color: {COLORS['light']};
            color: #9CA3AF;
        }}
    """)
    return button

def create_secondary_button(text):
    """Create a secondary styled button"""
    button = QPushButton(text)
    button.setStyleSheet(f"""
        QPushButton {{
            background-color: white;
            color: {COLORS['primary']};
            border: 1px solid {COLORS['primary']};
            padding: 8px 16px;
            font-weight: bold;
            border-radius: 6px;
        }}
        QPushButton:hover {{
            background-color: {COLORS['light_bg']};
        }}
        QPushButton:pressed {{
            background-color: {COLORS['light']};
        }}
        QPushButton:disabled {{
            background-color: white;
            color: {COLORS['light']};
            border: 1px solid {COLORS['light']};
        }}
    """)
    return button

def set_application_style(app):
    """Apply a modern style to the application"""
    # Set application font
    font = QFont("Segoe UI", 10)
    app.setFont(font)
    
    # Set application stylesheet
    app.setStyleSheet(f"""
        QWidget {{
            font-family: 'Segoe UI', 'Arial', sans-serif;
        }}
        
        QMainWindow {{
            background-color: {COLORS['light_bg']};
        }}
        
        QLabel {{
            color: {COLORS['dark']};
        }}
        
        QGroupBox {{
            font-weight: bold;
            border: 1px solid {COLORS['light']};
            border-radius: 8px;
            margin-top: 1.5ex;
            padding-top: 1.5ex;
        }}
        
        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top center;
            padding: 0 5px;
            color: {COLORS['primary']};
        }}
        
        QLineEdit, QComboBox, QSpinBox {{
            border: 1px solid {COLORS['light']};
            border-radius: 6px;
            padding: 8px;
            background-color: white;
            selection-background-color: {COLORS['secondary']};
        }}
        
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
            border: 1px solid {COLORS['secondary']};
        }}
        
        QComboBox::drop-down {{
            border: none;
            width: 30px;
        }}
        
        QComboBox::down-arrow {{
            image: none;
            width: 0;
        }}
        
        QComboBox::drop-down:hover {{
            background-color: {COLORS['light']};
        }}
        
        QPushButton {{
            border-radius: 6px;
            padding: 8px 16px;
            font-weight: bold;
        }}
        
        QPushButton:disabled {{
            background-color: {COLORS['light']};
            color: #9CA3AF;
        }}
        
        QProgressBar {{
            border: 1px solid {COLORS['light']};
            border-radius: 5px;
            text-align: center;
            background-color: white;
        }}
        
        QProgressBar::chunk {{
            background-color: {COLORS['accent']};
            border-radius: 5px;
        }}
        
        QScrollBar {{
            background-color: {COLORS['light_bg']};
            border-radius: 5px;
            width: 12px;
        }}
        
        QScrollBar::handle {{
            background-color: {COLORS['light']};
            border-radius: 5px;
            min-height: 30px;
        }}
        
        QScrollBar::handle:hover {{
            background-color: {COLORS['secondary']};
        }}
        
        QScrollBar::add-line, QScrollBar::sub-line {{
            height: 0px;
        }}
    """)

if __name__ == "__main__":
    # Import subprocess if needed for opening files
    import subprocess
    # Create the application
    app = QApplication(sys.argv)
    app.setApplicationName("CV Processor")
    
    # Apply modern application style
    set_application_style(app)

    # Ensure resource directories exist
    resources_dir = os.path.join(os.path.dirname(__file__), 'resources')
    os.makedirs(resources_dir, exist_ok=True)
    
    # Set window attributes to create modern look (Windows)
    if sys.platform == "win32":
        try:
            app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps)
            app.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling)
        except Exception as e:
            print(f"Could not set high DPI settings: {e}")

    # Create and show the main window
    window = CVProcessorApp()
    window.show()

    # Start the event loop
    sys.exit(app.exec())