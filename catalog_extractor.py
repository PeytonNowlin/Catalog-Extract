#!/usr/bin/env python3
"""
Catalog Extractor - Main orchestrator script.
Extracts part numbers and prices from PDF catalogs.
"""
import argparse
import logging
import os
import sys
from typing import List
import cv2

from src.pdf_handler import PDFHandler
from src.preprocessor import ImagePreprocessor
from src.ocr_handler import OCRHandler
from src.table_detector import TableDetector
from src.extractor import DataExtractor, ExtractedItem
from src.validator import DataValidator
from src.exporter import DataExporter


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('catalog_extraction.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class CatalogExtractor:
    """Main orchestrator for catalog extraction pipeline."""
    
    def __init__(
        self,
        pdf_path: str,
        output_dir: str = 'output',
        debug_mode: bool = False,
        dpi: int = 300,
        min_confidence: float = 50.0
    ):
        """
        Initialize catalog extractor.
        
        Args:
            pdf_path: Path to PDF catalog
            output_dir: Directory for output files
            debug_mode: Enable debug images and verbose logging
            dpi: DPI for rendering PDF pages
            min_confidence: Minimum confidence threshold
        """
        self.pdf_path = pdf_path
        self.output_dir = output_dir
        self.debug_mode = debug_mode
        self.dpi = dpi
        self.min_confidence = min_confidence
        
        # Create output directories
        os.makedirs(output_dir, exist_ok=True)
        if debug_mode:
            os.makedirs(os.path.join(output_dir, 'debug'), exist_ok=True)
        
        # Initialize pipeline components
        logger.info("Initializing extraction pipeline...")
        self.pdf_handler = PDFHandler(pdf_path)
        self.preprocessor = ImagePreprocessor(debug_mode=debug_mode)
        self.ocr_handler = OCRHandler()
        self.table_detector = TableDetector(debug_mode=debug_mode)
        self.extractor = DataExtractor()
        self.validator = DataValidator(min_confidence=min_confidence)
        self.exporter = DataExporter()
        
        logger.info("Pipeline initialized successfully")
    
    def process_catalog(
        self, 
        start_page: int = 0, 
        end_page: int = None,
        force_ocr: bool = False
    ) -> List[ExtractedItem]:
        """
        Process the entire catalog or a range of pages.
        
        Args:
            start_page: Starting page number (0-indexed)
            end_page: Ending page number (exclusive), None for all pages
            force_ocr: Force OCR even for text-based PDFs
            
        Returns:
            List of all extracted items
        """
        if end_page is None:
            end_page = self.pdf_handler.page_count
        
        logger.info(f"Processing pages {start_page} to {end_page - 1}")
        
        all_items = []
        
        for page_num in range(start_page, end_page):
            logger.info(f"\n{'='*60}")
            logger.info(f"Processing page {page_num + 1}/{end_page}")
            logger.info(f"{'='*60}")
            
            try:
                items = self.process_page(page_num, force_ocr=force_ocr)
                all_items.extend(items)
                
                logger.info(f"Extracted {len(items)} items from page {page_num}")
            except Exception as e:
                logger.error(f"Error processing page {page_num}: {e}", exc_info=True)
                continue
        
        logger.info(f"\nTotal items extracted: {len(all_items)}")
        
        # Validate and deduplicate
        logger.info("Validating extracted data...")
        validated_items = self.validator.validate_items(all_items)
        
        logger.info("Removing duplicates...")
        final_items = self.validator.deduplicate_items(validated_items)
        
        logger.info(f"Final item count: {len(final_items)}")
        
        return final_items
    
    def process_page(
        self, 
        page_num: int, 
        force_ocr: bool = False
    ) -> List[ExtractedItem]:
        """
        Process a single page.
        
        Args:
            page_num: Page number (0-indexed)
            force_ocr: Force OCR even for text-based PDFs
            
        Returns:
            List of extracted items from this page
        """
        # Check if page is text-based
        is_text_based = self.pdf_handler.is_text_based(page_num)
        
        if is_text_based and not force_ocr:
            # Text-based PDF - extract directly
            logger.info("Using direct text extraction (text-based PDF)")
            items = self._process_text_page(page_num)
        else:
            # Image-based PDF - use OCR
            logger.info("Using OCR extraction (image-based PDF)")
            items = self._process_image_page(page_num)
        
        return items
    
    def _process_text_page(self, page_num: int) -> List[ExtractedItem]:
        """
        Process text-based PDF page.
        
        Args:
            page_num: Page number
            
        Returns:
            List of extracted items
        """
        # Extract text directly
        text = self.pdf_handler.extract_text_direct(page_num)
        
        if not text:
            logger.warning(f"No text extracted from page {page_num}")
            return []
        
        # Extract data from text
        items = self.extractor.extract_from_text(text, page_num)
        
        return items
    
    def _process_image_page(self, page_num: int) -> List[ExtractedItem]:
        """
        Process image-based PDF page with OCR.
        
        Args:
            page_num: Page number
            
        Returns:
            List of extracted items
        """
        # Render page to image
        image = self.pdf_handler.render_page_to_image(page_num, dpi=self.dpi)
        
        if image is None:
            logger.error(f"Failed to render page {page_num}")
            return []
        
        # Save original image if debug mode
        if self.debug_mode:
            debug_path = os.path.join(
                self.output_dir, 'debug', f'page_{page_num:03d}_original.png'
            )
            cv2.imwrite(debug_path, image)
        
        # Preprocess image
        logger.info("Preprocessing image...")
        preprocessed = self.preprocessor.preprocess(image, page_num)
        
        # Save preprocessed image if debug mode
        if self.debug_mode:
            debug_path = os.path.join(
                self.output_dir, 'debug', f'page_{page_num:03d}_preprocessed.png'
            )
            cv2.imwrite(debug_path, preprocessed)
            
            # Save all debug images from preprocessor
            self.preprocessor.save_debug_images(
                os.path.join(self.output_dir, 'debug')
            )
        
        # Perform OCR
        logger.info("Performing OCR...")
        full_text, words, lines = self.ocr_handler.extract_text(preprocessed, page_num)
        
        # Save OCR visualization if debug mode
        if self.debug_mode:
            bbox_image = self.ocr_handler.draw_bounding_boxes(
                image, words, min_confidence=50.0
            )
            debug_path = os.path.join(
                self.output_dir, 'debug', f'page_{page_num:03d}_ocr_boxes.png'
            )
            cv2.imwrite(debug_path, bbox_image)
        
        # Detect tables
        logger.info("Detecting tables...")
        rows = self.table_detector.detect_tables(preprocessed, lines, page_num)
        
        # Extract data from rows
        logger.info("Extracting data...")
        if rows:
            items = self.extractor.extract_from_rows(rows, page_num)
        else:
            # Fallback to plain text extraction
            logger.info("No tables detected, using plain text extraction")
            items = self.extractor.extract_from_text(full_text, page_num, words)
        
        return items
    
    def export_results(self, items: List[ExtractedItem]):
        """
        Export results to CSV and summary.
        
        Args:
            items: List of extracted items
        """
        # Generate output filenames
        base_name = os.path.splitext(os.path.basename(self.pdf_path))[0]
        csv_path = os.path.join(self.output_dir, f'{base_name}_extracted.csv')
        summary_path = os.path.join(self.output_dir, f'{base_name}_summary.txt')
        
        # Export to CSV
        self.exporter.export_to_csv(items, csv_path, include_raw_text=True)
        
        # Export summary
        self.exporter.export_summary(items, summary_path)
        
        logger.info(f"\nResults exported:")
        logger.info(f"  CSV: {csv_path}")
        logger.info(f"  Summary: {summary_path}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Extract part numbers and prices from PDF catalogs',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process entire catalog
  python catalog_extractor.py catalog.pdf
  
  # Process specific pages with debug output
  python catalog_extractor.py catalog.pdf --start-page 5 --end-page 10 --debug
  
  # Force OCR on text-based PDF
  python catalog_extractor.py catalog.pdf --force-ocr
  
  # Set minimum confidence threshold
  python catalog_extractor.py catalog.pdf --min-confidence 70
        """
    )
    
    parser.add_argument(
        'pdf_path',
        help='Path to PDF catalog'
    )
    
    parser.add_argument(
        '-o', '--output-dir',
        default='output',
        help='Output directory (default: output)'
    )
    
    parser.add_argument(
        '--start-page',
        type=int,
        default=0,
        help='Starting page number (0-indexed, default: 0)'
    )
    
    parser.add_argument(
        '--end-page',
        type=int,
        default=None,
        help='Ending page number (exclusive, default: all pages)'
    )
    
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug mode (saves intermediate images)'
    )
    
    parser.add_argument(
        '--dpi',
        type=int,
        default=300,
        help='DPI for rendering pages (default: 300)'
    )
    
    parser.add_argument(
        '--min-confidence',
        type=float,
        default=50.0,
        help='Minimum confidence threshold 0-100 (default: 50.0)'
    )
    
    parser.add_argument(
        '--force-ocr',
        action='store_true',
        help='Force OCR even for text-based PDFs'
    )
    
    args = parser.parse_args()
    
    # Validate PDF path
    if not os.path.exists(args.pdf_path):
        logger.error(f"PDF file not found: {args.pdf_path}")
        sys.exit(1)
    
    try:
        # Create extractor
        extractor = CatalogExtractor(
            pdf_path=args.pdf_path,
            output_dir=args.output_dir,
            debug_mode=args.debug,
            dpi=args.dpi,
            min_confidence=args.min_confidence
        )
        
        # Process catalog
        items = extractor.process_catalog(
            start_page=args.start_page,
            end_page=args.end_page,
            force_ocr=args.force_ocr
        )
        
        # Export results
        if items:
            extractor.export_results(items)
            logger.info("\n✓ Extraction completed successfully!")
        else:
            logger.warning("\n⚠ No items extracted from catalog")
    
    except KeyboardInterrupt:
        logger.info("\n\nExtraction interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n✗ Extraction failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()

