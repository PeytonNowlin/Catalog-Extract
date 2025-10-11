"""
Automatic Multi-Pass Processor
Intelligently runs multiple extraction passes and consolidates results.
"""
import logging
from typing import List, Dict, Optional
from sqlalchemy.orm import Session

from .database import Document, ExtractionPass, ExtractedItem, ExtractionStatus, ExtractionMethod
from .pdf_handler import PDFHandler
from .extraction_strategies import StrategyFactory

logger = logging.getLogger(__name__)


class MultiPassProcessor:
    """Handles automatic multi-pass extraction."""
    
    def __init__(self, db: Session):
        self.db = db
        self.low_confidence_threshold = 60.0
        self.min_items_per_page = 1
    
    async def process_auto_multi_pass(
        self,
        document_id: int,
        pdf_path: str,
        options: Dict,
        progress_callback=None
    ) -> List[int]:
        """
        Run automatic multi-pass extraction.
        
        Returns list of pass IDs created.
        """
        logger.info(f"[AUTO-MULTI-PASS] Starting for document {document_id}")
        
        doc = self.db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            raise ValueError("Document not found")
        
        pdf_handler = PDFHandler(pdf_path)
        pass_ids = []
        
        # PASS 1: OCR + Tables (standard DPI, table detection)
        logger.info(f"[AUTO-MULTI-PASS] Document {document_id} - Pass 1: OCR + Tables (DPI: {options.get('dpi', 300)})")
        try:
            pass1_options = options.copy()
            pass1_options['force_ocr'] = True
            pass1_id = await self._run_pass(
                document_id, "ocr_table", pdf_path, pass1_options, pass_number=1
            )
            pass_ids.append(pass1_id)
            logger.info(f"[AUTO-MULTI-PASS] Document {document_id} - Pass 1 completed: Pass ID {pass1_id}")
        except Exception as e:
            logger.error(f"[AUTO-MULTI-PASS] Document {document_id} - Pass 1 failed: {e}", exc_info=True)
            raise
        
        if progress_callback:
            progress_callback(33, "Pass 1 complete, analyzing results...")
        
        # Analyze Pass 1 results
        pass1_stats = self._analyze_pass_results(pass1_id)
        logger.info(f"[AUTO-MULTI-PASS] Pass 1 stats: {pass1_stats}")
        
        # PASS 2: OCR Aggressive (higher DPI, more preprocessing)
        logger.info(f"[AUTO-MULTI-PASS] Document {document_id} - Pass 2: OCR Aggressive (high DPI, enhanced preprocessing)")
        try:
            pass2_options = options.copy()
            pass2_options['dpi'] = 400  # Higher DPI
            pass2_options['force_ocr'] = True
            
            pass2_id = await self._run_pass(
                document_id, "ocr_aggressive", pdf_path, pass2_options, pass_number=2
            )
            pass_ids.append(pass2_id)
            logger.info(f"[AUTO-MULTI-PASS] Document {document_id} - Pass 2 completed: Pass ID {pass2_id}")
        except Exception as e:
            logger.error(f"[AUTO-MULTI-PASS] Document {document_id} - Pass 2 failed: {e}", exc_info=True)
            # Continue anyway with what we have
        
        if progress_callback:
            progress_callback(66, "Pass 2 complete, checking for gaps...")
        
        # Analyze Pass 2 results
        pass2_stats = self._analyze_pass_results(pass2_id)
        logger.info(f"[AUTO-MULTI-PASS] Pass 2 stats: {pass2_stats}")
        
        # PASS 3: Target low confidence pages with OCR Plain (different approach)
        low_confidence_pages = self._find_low_confidence_pages(document_id)
        
        if low_confidence_pages and len(low_confidence_pages) > 0:
            logger.info(f"[AUTO-MULTI-PASS] Document {document_id} - Pass 3: OCR Plain on {len(low_confidence_pages)} low-confidence pages")
            
            try:
                # Create targeted pass for specific pages
                pass3_options = options.copy()
                pass3_options['dpi'] = 450  # Even higher DPI
                pass3_options['force_ocr'] = True
                
                pass3_id = await self._run_pass(
                    document_id, "ocr_plain", pdf_path, pass3_options, 
                    pass_number=3, target_pages=low_confidence_pages
                )
                pass_ids.append(pass3_id)
                logger.info(f"[AUTO-MULTI-PASS] Document {document_id} - Pass 3 completed: Pass ID {pass3_id}")
            except Exception as e:
                logger.error(f"[AUTO-MULTI-PASS] Document {document_id} - Pass 3 failed: {e}", exc_info=True)
                # Continue anyway with what we have
        else:
            logger.info(f"[AUTO-MULTI-PASS] Document {document_id} - No low confidence pages found, skipping Pass 3")
        
        if progress_callback:
            progress_callback(100, "All passes complete, consolidating...")
        
        logger.info(f"[AUTO-MULTI-PASS] Document {document_id} - Complete: {len(pass_ids)} passes created")
        return pass_ids
    
    async def _run_pass(
        self,
        document_id: int,
        method: str,
        pdf_path: str,
        options: Dict,
        pass_number: int,
        target_pages: Optional[List[int]] = None
    ) -> int:
        """Run a single extraction pass."""
        from .validator import DataValidator
        import time
        
        # Create pass record
        extraction_pass = ExtractionPass(
            document_id=document_id,
            pass_number=pass_number,
            method=ExtractionMethod(method),
            start_page=options.get('start_page', 0),
            end_page=options.get('end_page'),
            dpi=options.get('dpi', 300),
            min_confidence=options.get('min_confidence', 50.0),
            force_ocr=options.get('force_ocr', False),
            debug_mode=options.get('debug_mode', False),
            status=ExtractionStatus.PROCESSING
        )
        self.db.add(extraction_pass)
        self.db.commit()
        self.db.refresh(extraction_pass)
        
        pass_id = extraction_pass.id
        start_time = time.time()
        
        try:
            # Initialize components
            pdf_handler = PDFHandler(pdf_path)
            strategy = StrategyFactory.create(method, options.get('debug_mode', False))
            validator = DataValidator(min_confidence=options.get('min_confidence', 50.0))
            
            # Determine pages to process
            if target_pages:
                pages_to_process = target_pages
            else:
                start_page = options.get('start_page', 0)
                end_page = options.get('end_page') or pdf_handler.page_count
                pages_to_process = range(start_page, end_page)
            
            all_items = []
            
            # Process pages
            for page_num in pages_to_process:
                try:
                    items = strategy.extract(
                        pdf_handler,
                        page_num,
                        {
                            'dpi': options.get('dpi', 300),
                            'force_ocr': options.get('force_ocr', False)
                        }
                    )
                    
                    # Store items
                    for item in items:
                        db_item = ExtractedItem(
                            extraction_pass_id=pass_id,
                            brand_code=item.brand_code,
                            part_number=item.part_number,
                            price_type=item.price_type,
                            price_value=item.price_value,
                            currency=item.currency,
                            page=item.page,
                            confidence=item.confidence,
                            raw_text=item.raw_text,
                            bbox_x=item.bbox[0] if item.bbox else None,
                            bbox_y=item.bbox[1] if item.bbox else None,
                            bbox_width=item.bbox[2] if item.bbox else None,
                            bbox_height=item.bbox[3] if item.bbox else None,
                            extraction_method=ExtractionMethod(method)
                        )
                        self.db.add(db_item)
                        all_items.append(item)
                    
                    self.db.commit()
                    
                except Exception as e:
                    logger.error(f"Error processing page {page_num}: {e}")
                    continue
            
            # Validate and deduplicate
            validated_items = validator.validate_items(all_items)
            final_items = validator.deduplicate_items(validated_items)
            
            # Update pass status
            processing_time = time.time() - start_time
            extraction_pass.status = ExtractionStatus.COMPLETED
            extraction_pass.items_extracted = len(final_items)
            extraction_pass.processing_time = processing_time
            
            if final_items:
                extraction_pass.avg_confidence = sum(i.confidence for i in final_items) / len(final_items)
            
            self.db.commit()
            
            logger.info(f"Pass {pass_id} ({method}) complete: {len(final_items)} items")
            return pass_id
            
        except Exception as e:
            logger.error(f"Pass {pass_id} failed: {e}", exc_info=True)
            extraction_pass.status = ExtractionStatus.FAILED
            extraction_pass.error_message = str(e)
            self.db.commit()
            raise
    
    def _analyze_pass_results(self, pass_id: int) -> Dict:
        """Analyze results from a pass."""
        extraction_pass = self.db.query(ExtractionPass).filter(
            ExtractionPass.id == pass_id
        ).first()
        
        if not extraction_pass:
            return {'avg_confidence': 0, 'items_per_page': 0}
        
        items = self.db.query(ExtractedItem).filter(
            ExtractedItem.extraction_pass_id == pass_id
        ).all()
        
        if not items:
            return {'avg_confidence': 0, 'items_per_page': 0}
        
        avg_confidence = sum(item.confidence for item in items) / len(items)
        
        # Calculate items per page
        pages = set(item.page for item in items)
        items_per_page = len(items) / len(pages) if pages else 0
        
        return {
            'avg_confidence': avg_confidence,
            'items_per_page': items_per_page,
            'total_items': len(items),
            'pages_with_items': len(pages)
        }
    
    def _find_low_confidence_pages(self, document_id: int) -> List[int]:
        """Find pages with low confidence across all passes."""
        # Get all items for this document
        passes = self.db.query(ExtractionPass).filter(
            ExtractionPass.document_id == document_id,
            ExtractionPass.status == ExtractionStatus.COMPLETED
        ).all()
        
        page_confidences = {}
        
        for pass_obj in passes:
            items = self.db.query(ExtractedItem).filter(
                ExtractedItem.extraction_pass_id == pass_obj.id
            ).all()
            
            for item in items:
                page = item.page
                if page not in page_confidences:
                    page_confidences[page] = []
                page_confidences[page].append(item.confidence)
        
        # Find pages with low average confidence
        low_confidence_pages = []
        for page, confidences in page_confidences.items():
            avg_conf = sum(confidences) / len(confidences)
            if avg_conf < self.low_confidence_threshold:
                low_confidence_pages.append(page)
        
        return low_confidence_pages

