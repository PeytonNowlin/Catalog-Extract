"""
Different extraction strategies for multi-pass processing.
"""
import logging
from typing import List, Dict, Any
from abc import ABC, abstractmethod

from .pdf_handler import PDFHandler
from .preprocessor import ImagePreprocessor
from .ocr_handler import OCRHandler
from .table_detector import TableDetector
from .extractor import DataExtractor, ExtractedItem

logger = logging.getLogger(__name__)


class ExtractionStrategy(ABC):
    """Base class for extraction strategies."""
    
    @abstractmethod
    def extract(
        self,
        pdf_handler: PDFHandler,
        page_num: int,
        options: Dict[str, Any]
    ) -> List[ExtractedItem]:
        """Extract items from a page."""
        pass
    
    @abstractmethod
    def get_method_name(self) -> str:
        """Get the method name."""
        pass


class TextDirectStrategy(ExtractionStrategy):
    """Extract directly from text-based PDFs."""
    
    def __init__(self):
        self.extractor = DataExtractor()
    
    def extract(
        self,
        pdf_handler: PDFHandler,
        page_num: int,
        options: Dict[str, Any]
    ) -> List[ExtractedItem]:
        """Extract using direct text extraction."""
        text = pdf_handler.extract_text_direct(page_num)
        if not text:
            return []
        
        items = self.extractor.extract_from_text(text, page_num)
        logger.info(f"Text direct strategy extracted {len(items)} items from page {page_num}")
        return items
    
    def get_method_name(self) -> str:
        return "text_direct"


class OCRTableStrategy(ExtractionStrategy):
    """Extract using OCR with table detection."""
    
    def __init__(self, debug_mode: bool = False):
        self.preprocessor = ImagePreprocessor(debug_mode=debug_mode)
        self.ocr_handler = OCRHandler()
        self.table_detector = TableDetector(debug_mode=debug_mode)
        self.extractor = DataExtractor()
    
    def extract(
        self,
        pdf_handler: PDFHandler,
        page_num: int,
        options: Dict[str, Any]
    ) -> List[ExtractedItem]:
        """Extract using OCR with table detection."""
        dpi = options.get('dpi', 300)
        
        # Render page
        image = pdf_handler.render_page_to_image(page_num, dpi=dpi)
        if image is None:
            return []
        
        # Preprocess
        preprocessed = self.preprocessor.preprocess(image, page_num)
        
        # OCR
        full_text, words, lines = self.ocr_handler.extract_text(preprocessed, page_num)
        
        # Detect tables
        rows = self.table_detector.detect_tables(preprocessed, lines, page_num)
        
        # Extract from rows
        if rows:
            items = self.extractor.extract_from_rows(rows, page_num)
        else:
            items = []
        
        logger.info(f"OCR table strategy extracted {len(items)} items from page {page_num}")
        return items
    
    def get_method_name(self) -> str:
        return "ocr_table"


class OCRPlainStrategy(ExtractionStrategy):
    """Extract using OCR without table detection (plain text)."""
    
    def __init__(self, debug_mode: bool = False):
        self.preprocessor = ImagePreprocessor(debug_mode=debug_mode)
        self.ocr_handler = OCRHandler()
        self.extractor = DataExtractor()
    
    def extract(
        self,
        pdf_handler: PDFHandler,
        page_num: int,
        options: Dict[str, Any]
    ) -> List[ExtractedItem]:
        """Extract using OCR without table detection."""
        dpi = options.get('dpi', 300)
        
        # Render page
        image = pdf_handler.render_page_to_image(page_num, dpi=dpi)
        if image is None:
            return []
        
        # Preprocess
        preprocessed = self.preprocessor.preprocess(image, page_num)
        
        # OCR
        full_text, words, lines = self.ocr_handler.extract_text(preprocessed, page_num)
        
        # Extract from plain text
        items = self.extractor.extract_from_text(full_text, page_num, words)
        
        logger.info(f"OCR plain strategy extracted {len(items)} items from page {page_num}")
        return items
    
    def get_method_name(self) -> str:
        return "ocr_plain"


class OCRAggressiveStrategy(ExtractionStrategy):
    """Aggressive OCR with multiple preprocessing attempts."""
    
    def __init__(self, debug_mode: bool = False):
        self.preprocessor = ImagePreprocessor(debug_mode=debug_mode)
        self.ocr_handler = OCRHandler()
        self.table_detector = TableDetector(debug_mode=debug_mode)
        self.extractor = DataExtractor()
    
    def extract(
        self,
        pdf_handler: PDFHandler,
        page_num: int,
        options: Dict[str, Any]
    ) -> List[ExtractedItem]:
        """Extract using aggressive OCR (higher DPI, multiple attempts)."""
        # Use higher DPI
        dpi = options.get('dpi', 300)
        aggressive_dpi = max(dpi, 400)
        
        # Render page at higher resolution
        image = pdf_handler.render_page_to_image(page_num, dpi=aggressive_dpi)
        if image is None:
            return []
        
        all_items = []
        
        # Try with standard preprocessing
        preprocessed = self.preprocessor.preprocess(image, page_num)
        full_text, words, lines = self.ocr_handler.extract_text(preprocessed, page_num)
        
        # Try table detection
        rows = self.table_detector.detect_tables(preprocessed, lines, page_num)
        if rows:
            items = self.extractor.extract_from_rows(rows, page_num)
            all_items.extend(items)
        
        # Also try plain text
        items = self.extractor.extract_from_text(full_text, page_num, words)
        all_items.extend(items)
        
        logger.info(f"OCR aggressive strategy extracted {len(all_items)} items from page {page_num}")
        return all_items
    
    def get_method_name(self) -> str:
        return "ocr_aggressive"


class HybridStrategy(ExtractionStrategy):
    """Combine multiple strategies."""
    
    def __init__(self, debug_mode: bool = False):
        self.text_strategy = TextDirectStrategy()
        self.ocr_table_strategy = OCRTableStrategy(debug_mode)
        self.ocr_plain_strategy = OCRPlainStrategy(debug_mode)
    
    def extract(
        self,
        pdf_handler: PDFHandler,
        page_num: int,
        options: Dict[str, Any]
    ) -> List[ExtractedItem]:
        """Extract using multiple strategies and combine results."""
        all_items = []
        
        # Try text extraction first
        if not options.get('force_ocr', False):
            try:
                items = self.text_strategy.extract(pdf_handler, page_num, options)
                all_items.extend(items)
            except Exception as e:
                logger.debug(f"Text strategy failed: {e}")
        
        # Try OCR with tables
        try:
            items = self.ocr_table_strategy.extract(pdf_handler, page_num, options)
            all_items.extend(items)
        except Exception as e:
            logger.debug(f"OCR table strategy failed: {e}")
        
        # Try OCR plain
        try:
            items = self.ocr_plain_strategy.extract(pdf_handler, page_num, options)
            all_items.extend(items)
        except Exception as e:
            logger.debug(f"OCR plain strategy failed: {e}")
        
        logger.info(f"Hybrid strategy extracted {len(all_items)} items from page {page_num}")
        return all_items
    
    def get_method_name(self) -> str:
        return "hybrid"


# Strategy factory
class StrategyFactory:
    """Factory for creating extraction strategies."""
    
    @staticmethod
    def create(method: str, debug_mode: bool = False) -> ExtractionStrategy:
        """Create a strategy by method name."""
        strategies = {
            'text_direct': TextDirectStrategy,
            'ocr_table': lambda: OCRTableStrategy(debug_mode),
            'ocr_plain': lambda: OCRPlainStrategy(debug_mode),
            'ocr_aggressive': lambda: OCRAggressiveStrategy(debug_mode),
            'hybrid': lambda: HybridStrategy(debug_mode),
        }
        
        strategy_class = strategies.get(method)
        if not strategy_class:
            raise ValueError(f"Unknown extraction method: {method}")
        
        if callable(strategy_class):
            return strategy_class()
        return strategy_class
    
    @staticmethod
    def get_available_methods() -> List[str]:
        """Get list of available extraction methods."""
        return [
            'text_direct',
            'ocr_table',
            'ocr_plain',
            'ocr_aggressive',
            'hybrid'
        ]

