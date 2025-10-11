"""
PDF handling module.
Handles both image-based and text-based PDFs.
"""
import os
from typing import List, Tuple, Optional
import logging
import numpy as np
import cv2
from PIL import Image

# PDF libraries
import fitz  # PyMuPDF
import pdfplumber

logger = logging.getLogger(__name__)


class PDFHandler:
    """Handles PDF reading and page extraction."""
    
    def __init__(self, pdf_path: str):
        """
        Initialize PDF handler.
        
        Args:
            pdf_path: Path to PDF file
        """
        self.pdf_path = pdf_path
        self.page_count = 0
        
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        
        # Detect page count
        try:
            with fitz.open(pdf_path) as doc:
                self.page_count = len(doc)
        except Exception as e:
            logger.error(f"Error opening PDF: {e}")
            raise
        
        logger.info(f"Loaded PDF: {pdf_path} ({self.page_count} pages)")
    
    def is_text_based(self, page_num: int = 0) -> bool:
        """
        Check if a page is text-based or image-based.
        
        Args:
            page_num: Page number to check (0-indexed)
            
        Returns:
            True if page contains extractable text, False if image-based
        """
        try:
            with pdfplumber.open(self.pdf_path) as pdf:
                if page_num >= len(pdf.pages):
                    return False
                
                page = pdf.pages[page_num]
                text = page.extract_text()
                
                # If we got substantial text, it's text-based
                if text and len(text.strip()) > 50:
                    logger.info(f"Page {page_num} is text-based")
                    return True
                
                logger.info(f"Page {page_num} is image-based")
                return False
        except Exception as e:
            logger.warning(f"Error checking page type: {e}")
            return False
    
    def extract_text_direct(self, page_num: int) -> Optional[str]:
        """
        Extract text directly from text-based PDF page.
        
        Args:
            page_num: Page number (0-indexed)
            
        Returns:
            Extracted text or None if failed
        """
        try:
            with pdfplumber.open(self.pdf_path) as pdf:
                if page_num >= len(pdf.pages):
                    return None
                
                page = pdf.pages[page_num]
                text = page.extract_text()
                
                logger.info(f"Extracted {len(text)} characters from page {page_num}")
                return text
        except Exception as e:
            logger.error(f"Error extracting text from page {page_num}: {e}")
            return None
    
    def render_page_to_image(
        self, 
        page_num: int, 
        dpi: int = 300
    ) -> Optional[np.ndarray]:
        """
        Render a PDF page to image for OCR.
        
        Args:
            page_num: Page number (0-indexed)
            dpi: Resolution for rendering (higher = better quality)
            
        Returns:
            Image as numpy array (BGR format) or None if failed
        """
        try:
            with fitz.open(self.pdf_path) as doc:
                if page_num >= len(doc):
                    return None
                
                page = doc[page_num]
                
                # Calculate zoom factor for desired DPI
                zoom = dpi / 72  # 72 is default DPI
                mat = fitz.Matrix(zoom, zoom)
                
                # Render page to pixmap
                pix = page.get_pixmap(matrix=mat)
                
                # Convert to PIL Image
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                
                # Convert to numpy array (OpenCV format)
                img_array = np.array(img)
                
                # Convert RGB to BGR for OpenCV
                img_bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
                
                logger.info(
                    f"Rendered page {page_num} to image "
                    f"({img_bgr.shape[1]}x{img_bgr.shape[0]})"
                )
                
                return img_bgr
        except Exception as e:
            logger.error(f"Error rendering page {page_num}: {e}")
            return None
    
    def extract_page_images(self, page_num: int) -> List[np.ndarray]:
        """
        Extract embedded images from a PDF page.
        
        Args:
            page_num: Page number (0-indexed)
            
        Returns:
            List of images as numpy arrays
        """
        images = []
        
        try:
            with fitz.open(self.pdf_path) as doc:
                if page_num >= len(doc):
                    return images
                
                page = doc[page_num]
                image_list = page.get_images()
                
                for img_index, img in enumerate(image_list):
                    xref = img[0]
                    base_image = doc.extract_image(xref)
                    image_bytes = base_image["image"]
                    
                    # Convert to numpy array
                    nparr = np.frombuffer(image_bytes, np.uint8)
                    img_array = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    
                    if img_array is not None:
                        images.append(img_array)
                
                logger.info(f"Extracted {len(images)} embedded images from page {page_num}")
        except Exception as e:
            logger.error(f"Error extracting images from page {page_num}: {e}")
        
        return images
    
    def get_page_info(self, page_num: int) -> dict:
        """
        Get information about a page.
        
        Args:
            page_num: Page number (0-indexed)
            
        Returns:
            Dictionary with page info
        """
        info = {
            'page_num': page_num,
            'width': 0,
            'height': 0,
            'rotation': 0,
            'has_text': False,
            'image_count': 0
        }
        
        try:
            with fitz.open(self.pdf_path) as doc:
                if page_num >= len(doc):
                    return info
                
                page = doc[page_num]
                rect = page.rect
                
                info['width'] = rect.width
                info['height'] = rect.height
                info['rotation'] = page.rotation
                info['image_count'] = len(page.get_images())
                
                # Check for text
                text = page.get_text()
                info['has_text'] = len(text.strip()) > 0
        except Exception as e:
            logger.error(f"Error getting page info: {e}")
        
        return info

