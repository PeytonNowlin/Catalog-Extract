"""
OCR handler module using Tesseract.
Extracts text with confidence scores and bounding boxes.
"""
import cv2
import numpy as np
import pytesseract
from typing import List, Dict, Tuple, Optional
import logging
import os
import platform
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class OCRWord:
    """Represents a word detected by OCR."""
    text: str
    confidence: float
    bbox: Tuple[int, int, int, int]  # (x, y, width, height)
    page_num: int


@dataclass
class OCRLine:
    """Represents a line of text detected by OCR."""
    text: str
    words: List[OCRWord]
    bbox: Tuple[int, int, int, int]
    confidence: float
    page_num: int


class OCRHandler:
    """Handles OCR operations using Tesseract."""
    
    def __init__(self, tesseract_config: str = "--oem 3 --psm 6"):
        """
        Initialize OCR handler.
        
        Args:
            tesseract_config: Tesseract configuration string
                PSM modes:
                  6 = Assume a single uniform block of text
                  11 = Sparse text. Find as much text as possible
                OEM modes:
                  3 = Default, based on what is available
        """
        self.config = tesseract_config
        self._verify_tesseract()
    
    def _verify_tesseract(self):
        """Verify that Tesseract is installed and accessible."""
        # Auto-detect Tesseract on Windows
        if platform.system() == 'Windows':
            self._setup_windows_tesseract()
        
        try:
            version = pytesseract.get_tesseract_version()
            logger.info(f"Tesseract version: {version}")
        except Exception as e:
            logger.error(f"Tesseract not found: {e}")
            raise RuntimeError(
                "Tesseract OCR not found. Please install it:\n"
                "Windows: https://github.com/UB-Mannheim/tesseract/wiki\n"
                "Linux: sudo apt-get install tesseract-ocr\n"
                "Mac: brew install tesseract"
            )
    
    def _setup_windows_tesseract(self):
        """Auto-detect Tesseract installation on Windows."""
        possible_paths = [
            r'C:\Program Files\Tesseract-OCR\tesseract.exe',
            r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
            r'C:\Tesseract-OCR\tesseract.exe',
            r'C:\ProgramData\chocolatey\bin\tesseract.exe',
            r'C:\ProgramData\chocolatey\lib\tesseract\tools\tesseract.exe',
        ]
        
        # Check if already configured
        current_path = getattr(pytesseract.pytesseract, 'tesseract_cmd', None)
        if current_path and os.path.exists(current_path):
            logger.info(f"Using configured Tesseract path: {current_path}")
            return
        
        # Try to find Tesseract
        for path in possible_paths:
            if os.path.exists(path):
                pytesseract.pytesseract.tesseract_cmd = path
                logger.info(f"Found Tesseract at: {path}")
                return
        
        # Try to find in Chocolatey lib directory (version-specific)
        choco_lib = r'C:\ProgramData\chocolatey\lib'
        if os.path.exists(choco_lib):
            for item in os.listdir(choco_lib):
                if item.startswith('tesseract'):
                    tesseract_dir = os.path.join(choco_lib, item, 'tools')
                    tesseract_exe = os.path.join(tesseract_dir, 'tesseract.exe')
                    if os.path.exists(tesseract_exe):
                        pytesseract.pytesseract.tesseract_cmd = tesseract_exe
                        logger.info(f"Found Tesseract at: {tesseract_exe}")
                        return
        
        logger.warning("Could not auto-detect Tesseract location on Windows")
    
    def extract_text(self, image: np.ndarray, page_num: int = 0) -> Tuple[str, List[OCRWord], List[OCRLine]]:
        """
        Extract text from image with detailed information.
        
        Args:
            image: Preprocessed image
            page_num: Page number for tracking
            
        Returns:
            Tuple of (full_text, words_list, lines_list)
        """
        logger.info(f"Performing OCR on page {page_num}")
        
        # Get detailed OCR data
        data = pytesseract.image_to_data(
            image, 
            config=self.config, 
            output_type=pytesseract.Output.DICT
        )
        
        words = []
        lines_dict = {}
        
        # Process each detected word
        n_boxes = len(data['text'])
        for i in range(n_boxes):
            text = data['text'][i].strip()
            if not text:
                continue
            
            confidence = float(data['conf'][i])
            if confidence < 0:  # Tesseract returns -1 for no confidence
                confidence = 0.0
            
            x, y, w, h = (
                data['left'][i],
                data['top'][i],
                data['width'][i],
                data['height'][i]
            )
            
            word = OCRWord(
                text=text,
                confidence=confidence,
                bbox=(x, y, w, h),
                page_num=page_num
            )
            words.append(word)
            
            # Group words by line
            line_num = data['line_num'][i]
            if line_num not in lines_dict:
                lines_dict[line_num] = []
            lines_dict[line_num].append(word)
        
        # Create line objects
        lines = []
        for line_num, line_words in sorted(lines_dict.items()):
            if not line_words:
                continue
            
            # Calculate line bounding box
            min_x = min(w.bbox[0] for w in line_words)
            min_y = min(w.bbox[1] for w in line_words)
            max_x = max(w.bbox[0] + w.bbox[2] for w in line_words)
            max_y = max(w.bbox[1] + w.bbox[3] for w in line_words)
            
            line_text = ' '.join(w.text for w in line_words)
            line_confidence = np.mean([w.confidence for w in line_words])
            
            line = OCRLine(
                text=line_text,
                words=line_words,
                bbox=(min_x, min_y, max_x - min_x, max_y - min_y),
                confidence=line_confidence,
                page_num=page_num
            )
            lines.append(line)
        
        # Get full text
        full_text = pytesseract.image_to_string(image, config=self.config)
        
        logger.info(f"Extracted {len(words)} words in {len(lines)} lines from page {page_num}")
        
        return full_text, words, lines
    
    def draw_bounding_boxes(
        self, 
        image: np.ndarray, 
        words: List[OCRWord],
        min_confidence: float = 0.0
    ) -> np.ndarray:
        """
        Draw bounding boxes on image for visualization.
        
        Args:
            image: Original image
            words: List of OCR words
            min_confidence: Minimum confidence to draw (0-100)
            
        Returns:
            Image with bounding boxes drawn
        """
        output = image.copy()
        if len(output.shape) == 2:
            output = cv2.cvtColor(output, cv2.COLOR_GRAY2BGR)
        
        for word in words:
            if word.confidence < min_confidence:
                continue
            
            x, y, w, h = word.bbox
            
            # Color based on confidence (green = high, red = low)
            confidence_ratio = word.confidence / 100.0
            color = (
                int(255 * (1 - confidence_ratio)),  # Blue
                int(255 * confidence_ratio),         # Green
                0                                     # Red
            )
            
            # Draw rectangle
            cv2.rectangle(output, (x, y), (x + w, y + h), color, 2)
            
            # Draw confidence score
            label = f"{word.confidence:.0f}%"
            cv2.putText(
                output, label, (x, y - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1
            )
        
        return output

