#!/usr/bin/env python3
"""
Catalog Extractor API with Database & Multi-Pass Support
"""
import os
import hashlib
import time
from pathlib import Path
from typing import Optional, List
from datetime import datetime

from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Query, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.database import (
    get_db, Document, ExtractionPass, ExtractedItem, ConsolidatedItem,
    ExtractionStatus, ExtractionMethod
)
from src.pdf_handler import PDFHandler
from src.extraction_strategies import StrategyFactory
from src.validator import DataValidator
from src.exporter import DataExporter
from src.multi_pass_processor import MultiPassProcessor, convert_numpy_types
import csv
import io

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Paths
UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("outputs")
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# Create FastAPI app
app = FastAPI(
    title="Catalog Extractor API",
    description="Multi-pass PDF catalog extraction with database persistence",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Pydantic Models
class ExtractionOptionsModel(BaseModel):
    method: str = "ocr_table"
    start_page: int = 0
    end_page: Optional[int] = None
    dpi: int = 300
    min_confidence: float = 50.0
    force_ocr: bool = False
    debug_mode: bool = False


class DocumentResponse(BaseModel):
    id: int
    filename: str
    file_hash: str
    total_pages: int
    upload_date: str
    extraction_passes: List[dict] = []


class PassResponse(BaseModel):
    id: int
    pass_number: int
    method: str
    status: str
    items_extracted: int
    avg_confidence: Optional[float]
    processing_time: Optional[float]
    created_at: str
    completed_at: Optional[str]


class ItemResponse(BaseModel):
    brand_code: Optional[str]
    part_number: Optional[str]
    price_type: Optional[str]
    price_value: Optional[float]
    currency: str
    page: int
    confidence: float
    extraction_method: str


# Helper Functions
def calculate_file_hash(file_path: str) -> str:
    """Calculate SHA256 hash of file."""
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


async def process_extraction_pass(
    pass_id: int,
    document_id: int,
    pdf_path: str,
    options: ExtractionOptionsModel
):
    """Background task to process an extraction pass."""
    db = next(get_db())
    extraction_pass = None
    
    try:
        # Check if auto multi-pass mode
        if options.method == "auto_multi_pass":
            logger.info(f"Starting auto multi-pass for document {document_id}")
            processor = MultiPassProcessor(db)
            
            # Run auto multi-pass
            pass_ids = await processor.process_auto_multi_pass(
                document_id,
                pdf_path,
                options.dict(),
                progress_callback=None
            )
            
            # Consolidate results
            logger.info(f"Consolidating results for document {document_id}")
            consolidate_document_items(document_id, db)
            
            logger.info(f"Auto multi-pass complete for document {document_id}: {len(pass_ids)} passes")
            return
        
        # Single pass mode (original logic)
        # Get pass from database
        extraction_pass = db.query(ExtractionPass).filter(ExtractionPass.id == pass_id).first()
        if not extraction_pass:
            logger.error(f"Extraction pass {pass_id} not found")
            return
        
        # Update status
        extraction_pass.status = ExtractionStatus.PROCESSING
        extraction_pass.started_at = datetime.utcnow()
        db.commit()
        
        start_time = time.time()
        
        # Initialize components
        pdf_handler = PDFHandler(pdf_path)
        strategy = StrategyFactory.create(options.method, options.debug_mode)
        validator = DataValidator(min_confidence=options.min_confidence)
        
        # Determine page range
        end_page = options.end_page if options.end_page else pdf_handler.page_count
        total_pages = end_page - options.start_page
        
        all_items = []
        
        # Process each page
        for page_num in range(options.start_page, end_page):
            logger.info(f"Pass {pass_id}: Processing page {page_num + 1}/{end_page}")
            
            try:
                # Extract using strategy
                items = strategy.extract(
                    pdf_handler,
                    page_num,
                    {
                        'dpi': options.dpi,
                        'force_ocr': options.force_ocr
                    }
                )
                
                # Store items in database
                for item in items:
                    db_item = ExtractedItem(
                        extraction_pass_id=pass_id,
                        brand_code=item.brand_code,
                        part_number=item.part_number,
                        price_type=item.price_type,
                        price_value=convert_numpy_types(item.price_value),
                        currency=item.currency,
                        page=convert_numpy_types(item.page),
                        confidence=convert_numpy_types(item.confidence),
                        raw_text=item.raw_text,
                        bbox_x=convert_numpy_types(item.bbox[0]) if item.bbox else None,
                        bbox_y=convert_numpy_types(item.bbox[1]) if item.bbox else None,
                        bbox_width=convert_numpy_types(item.bbox[2]) if item.bbox else None,
                        bbox_height=convert_numpy_types(item.bbox[3]) if item.bbox else None,
                        extraction_method=ExtractionMethod(options.method)
                    )
                    db.add(db_item)
                    all_items.append(item)
                
                db.commit()
                
            except Exception as e:
                logger.error(f"Error processing page {page_num}: {e}", exc_info=True)
                db.rollback()
                continue
        
        # Validate items
        validated_items = validator.validate_items(all_items)
        final_items = validator.deduplicate_items(validated_items)
        
        # Update pass status
        processing_time = time.time() - start_time
        extraction_pass.status = ExtractionStatus.COMPLETED
        extraction_pass.completed_at = datetime.utcnow()
        extraction_pass.items_extracted = len(final_items)
        extraction_pass.processing_time = processing_time
        
        if final_items:
            extraction_pass.avg_confidence = float(sum(i.confidence for i in final_items) / len(final_items))
        
        db.commit()
        
        # Trigger consolidation
        consolidate_document_items(document_id, db)
        
        logger.info(f"Pass {pass_id} completed: {len(final_items)} items extracted")
        
    except Exception as e:
        logger.error(f"Extraction failed for document {document_id}, pass {pass_id}: {e}", exc_info=True)
        if extraction_pass:
            extraction_pass.status = ExtractionStatus.FAILED
            extraction_pass.error_message = str(e)
            extraction_pass.completed_at = datetime.utcnow()
            db.commit()
    
    finally:
        db.close()


def consolidate_document_items(document_id: int, db: Session):
    """Consolidate items from all passes for a document."""
    try:
        logger.info(f"[CONSOLIDATE] Starting consolidation for document {document_id}")
        
        # Get all completed passes
        passes = db.query(ExtractionPass).filter(
            ExtractionPass.document_id == document_id,
        ExtractionPass.status == ExtractionStatus.COMPLETED
    ).all()
    
        if not passes:
            logger.info(f"[CONSOLIDATE] No completed passes found for document {document_id}")
            return
        
        logger.info(f"[CONSOLIDATE] Found {len(passes)} completed passes for document {document_id}")
        
        # Get all items from all passes
        all_items = []
        for pass_obj in passes:
            items = db.query(ExtractedItem).filter(
                ExtractedItem.extraction_pass_id == pass_obj.id
            ).all()
            all_items.extend(items)
            logger.info(f"[CONSOLIDATE] Pass {pass_obj.id} ({pass_obj.method.value}): {len(items)} items")
        
        logger.info(f"[CONSOLIDATE] Total items to consolidate: {len(all_items)}")
        
        # Group by (part_number, page) - but handle None part numbers separately
        grouped = {}
        for item in all_items:
            # Skip items without part numbers (likely junk)
            if not item.part_number:
                continue
                
            key = (item.part_number, item.page)
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(item)
        
        logger.info(f"[CONSOLIDATE] Grouped into {len(grouped)} unique items")
        
        # Clear old consolidated items
        deleted_count = db.query(ConsolidatedItem).filter(
            ConsolidatedItem.document_id == document_id
        ).delete()
        logger.info(f"[CONSOLIDATE] Deleted {deleted_count} old consolidated items")
        
        # Create consolidated items (best from each group)
        for (part_number, page), items in grouped.items():
            # Prefer items with both part number AND price (more complete data)
            items_with_price = [i for i in items if i.price_value and i.price_value > 0]
            
            if items_with_price:
                # Choose from items that have prices, by confidence
                best_item = max(items_with_price, key=lambda x: x.confidence or 0)
            else:
                # No prices found, just use highest confidence
                best_item = max(items, key=lambda x: x.confidence or 0)
            
            # Only include if we have meaningful data
            if best_item.part_number:
                consolidated = ConsolidatedItem(
                    document_id=document_id,
                    brand_code=best_item.brand_code,
                    part_number=best_item.part_number,
                    price_type=best_item.price_type,
                    price_value=convert_numpy_types(best_item.price_value),
                    currency=best_item.currency,
                    page=convert_numpy_types(page),
                    avg_confidence=float(sum((i.confidence or 0) for i in items) / len(items)),
                    source_count=len(items)
                )
                db.add(consolidated)
        
        db.commit()
        logger.info(f"[CONSOLIDATE] Successfully consolidated {len(grouped)} unique items for document {document_id}")
        
    except Exception as e:
        logger.error(f"[CONSOLIDATE] Failed for document {document_id}: {e}", exc_info=True)
        db.rollback()
        raise


# API Endpoints

@app.get("/")
async def root():
    """Serve web UI."""
    return FileResponse("static/index.html")


@app.post("/api/documents/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    method: str = Query("ocr_table"),
    start_page: int = Query(0),
    end_page: Optional[int] = Query(None),
    dpi: int = Query(300),
    min_confidence: float = Query(50.0),
    force_ocr: bool = Query(False),
    debug_mode: bool = Query(False),
    db: Session = Depends(get_db)
):
    """Upload PDF and start first extraction pass."""
    
    if not file.filename.endswith('.pdf'):
        raise HTTPException(400, "Only PDF files accepted")
    
    # Save file
    file_id = str(uuid.uuid4())
    upload_path = UPLOAD_DIR / f"{file_id}_{file.filename}"
    
    with open(upload_path, "wb") as f:
        content = await file.read()
        f.write(content)
    
    # Calculate hash
    file_hash = calculate_file_hash(str(upload_path))
    
    # Check if document already exists
    existing_doc = db.query(Document).filter(Document.file_hash == file_hash).first()
    
    if existing_doc:
        document = existing_doc
        logger.info(f"Document already exists: {document.id}")
    else:
        # Get page count
        pdf_handler = PDFHandler(str(upload_path))
        
        # Create document
        document = Document(
            filename=file.filename,
            file_hash=file_hash,
            total_pages=pdf_handler.page_count
        )
        db.add(document)
        db.commit()
        db.refresh(document)
    
    # Create extraction pass
    extraction_pass = ExtractionPass(
        document_id=document.id,
        pass_number=len(document.extraction_passes) + 1,
        method=ExtractionMethod(method),
        start_page=start_page,
        end_page=end_page,
        dpi=dpi,
        min_confidence=min_confidence,
        force_ocr=force_ocr,
        debug_mode=debug_mode
    )
    db.add(extraction_pass)
    db.commit()
    db.refresh(extraction_pass)
    
    # Start processing
    options = ExtractionOptionsModel(
        method=method,
        start_page=start_page,
        end_page=end_page,
        dpi=dpi,
        min_confidence=min_confidence,
        force_ocr=force_ocr,
        debug_mode=debug_mode
    )
    
    background_tasks.add_task(
        process_extraction_pass,
        extraction_pass.id,
        document.id,
        str(upload_path),
        options
    )
    
    return {
        "document_id": document.id,
        "pass_id": extraction_pass.id,
        "filename": file.filename,
        "total_pages": document.total_pages,
        "method": method,
        "status": "processing"
    }


@app.get("/api/documents")
async def list_documents(db: Session = Depends(get_db)):
    """List all documents."""
    docs = db.query(Document).order_by(Document.upload_date.desc()).all()
    
    return [{
        "id": doc.id,
        "filename": doc.filename,
        "total_pages": doc.total_pages,
        "upload_date": doc.upload_date.isoformat(),
        "pass_count": len(doc.extraction_passes)
    } for doc in docs]


@app.get("/api/documents/{document_id}")
async def get_document(document_id: int, db: Session = Depends(get_db)):
    """Get document details."""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    
    passes = [{
        "id": p.id,
        "pass_number": p.pass_number,
        "method": p.method.value,
        "status": p.status.value,
        "items_extracted": p.items_extracted,
        "avg_confidence": p.avg_confidence,
        "processing_time": p.processing_time,
        "created_at": p.created_at.isoformat(),
        "completed_at": p.completed_at.isoformat() if p.completed_at else None
    } for p in doc.extraction_passes]
    
    return {
        "id": doc.id,
        "filename": doc.filename,
        "total_pages": doc.total_pages,
        "upload_date": doc.upload_date.isoformat(),
        "passes": passes
    }


@app.post("/api/documents/{document_id}/passes")
async def create_new_pass(
    document_id: int,
    background_tasks: BackgroundTasks,
    options: ExtractionOptionsModel,
    db: Session = Depends(get_db)
):
    """Create a new extraction pass for existing document."""
    
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    
    # Find uploaded file
    pdf_files = list(UPLOAD_DIR.glob(f"*_{doc.filename}"))
    if not pdf_files:
        raise HTTPException(404, "PDF file not found")
    
    pdf_path = str(pdf_files[0])
    
    # Create extraction pass
    extraction_pass = ExtractionPass(
        document_id=document_id,
        pass_number=len(doc.extraction_passes) + 1,
        method=ExtractionMethod(options.method),
        start_page=options.start_page,
        end_page=options.end_page,
        dpi=options.dpi,
        min_confidence=options.min_confidence,
        force_ocr=options.force_ocr,
        debug_mode=options.debug_mode
    )
    db.add(extraction_pass)
    db.commit()
    db.refresh(extraction_pass)
    
    # Start processing
    background_tasks.add_task(
        process_extraction_pass,
        extraction_pass.id,
        document_id,
        pdf_path,
        options
    )
    
    return {
        "pass_id": extraction_pass.id,
        "pass_number": extraction_pass.pass_number,
        "method": options.method,
        "status": "processing"
    }


@app.get("/api/passes/{pass_id}")
async def get_pass_status(pass_id: int, db: Session = Depends(get_db)):
    """Get pass status and progress."""
    pass_obj = db.query(ExtractionPass).filter(ExtractionPass.id == pass_id).first()
    if not pass_obj:
        raise HTTPException(404, "Pass not found")
    
    # Calculate progress
    progress = 0
    if pass_obj.status == ExtractionStatus.COMPLETED:
        progress = 100
    elif pass_obj.status == ExtractionStatus.PROCESSING:
        # Estimate based on items extracted
        progress = min(90, (pass_obj.items_extracted / 10) * 10)
    
    return {
        "id": pass_obj.id,
        "document_id": pass_obj.document_id,
        "pass_number": pass_obj.pass_number,
        "method": pass_obj.method.value,
        "status": pass_obj.status.value,
        "progress": progress,
        "items_extracted": pass_obj.items_extracted,
        "avg_confidence": pass_obj.avg_confidence,
        "processing_time": pass_obj.processing_time,
        "error_message": pass_obj.error_message
    }


@app.get("/api/passes/{pass_id}/items")
async def get_pass_items(pass_id: int, db: Session = Depends(get_db)):
    """Get items from specific pass."""
    items = db.query(ExtractedItem).filter(
        ExtractedItem.extraction_pass_id == pass_id
    ).all()
    
    return [{
        "brand_code": item.brand_code,
        "part_number": item.part_number,
        "price_type": item.price_type,
        "price_value": item.price_value,
        "currency": item.currency,
        "page": item.page,
        "confidence": item.confidence,
        "raw_text": item.raw_text,
        "extraction_method": item.extraction_method.value
    } for item in items]


@app.get("/api/documents/{document_id}/items/consolidated")
async def get_consolidated_items(document_id: int, db: Session = Depends(get_db)):
    """Get consolidated items for document."""
    items = db.query(ConsolidatedItem).filter(
        ConsolidatedItem.document_id == document_id
    ).order_by(ConsolidatedItem.page, ConsolidatedItem.part_number).all()
    
    return [{
        "brand_code": item.brand_code,
        "part_number": item.part_number,
        "price_type": item.price_type,
        "price_value": item.price_value,
        "currency": item.currency,
        "page": item.page,
        "avg_confidence": item.avg_confidence,
        "source_count": item.source_count
    } for item in items]


@app.get("/api/documents/{document_id}/export/csv")
async def export_csv(document_id: int, db: Session = Depends(get_db)):
    """Export consolidated items to CSV."""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    
    items = db.query(ConsolidatedItem).filter(
        ConsolidatedItem.document_id == document_id
    ).all()
    
    # Create CSV
    output_dir = OUTPUT_DIR / str(document_id)
    output_dir.mkdir(exist_ok=True)
    csv_path = output_dir / f"{doc.filename}_consolidated.csv"
    
    import csv
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'brand_code', 'part_number', 'price_type', 'price_value',
            'currency', 'page', 'avg_confidence', 'source_count'
        ])
        writer.writeheader()
        
        for item in items:
            writer.writerow({
                'brand_code': item.brand_code or '',
                'part_number': item.part_number or '',
                'price_type': item.price_type or '',
                'price_value': f"{item.price_value:.2f}" if item.price_value else '',
                'currency': item.currency,
                'page': item.page,
                'avg_confidence': f"{item.avg_confidence:.2f}",
                'source_count': item.source_count
            })
    
    return FileResponse(csv_path, media_type='text/csv', filename=csv_path.name)


@app.get("/api/methods")
async def get_available_methods():
    """Get list of available extraction methods."""
    return {
        "methods": [
            {
                "id": "auto_multi_pass",
                "name": "Auto Multi-Pass",
                "description": "3 OCR passes with different DPI settings (300→400→450) - recommended for image catalogs"
            },
            {
                "id": "text_direct",
                "name": "Text Direct",
                "description": "Fast extraction from text-based PDFs"
            },
            {
                "id": "ocr_table",
                "name": "OCR + Tables",
                "description": "OCR with table detection (best for structured data)"
            },
            {
                "id": "ocr_plain",
                "name": "OCR Plain",
                "description": "OCR without table detection"
            },
            {
                "id": "ocr_aggressive",
                "name": "OCR Aggressive",
                "description": "High-DPI OCR with multiple attempts"
            },
            {
                "id": "hybrid",
                "name": "Hybrid",
                "description": "Combines multiple methods (most comprehensive)"
            }
        ]
    }


@app.get("/api/health")
async def health_check(db: Session = Depends(get_db)):
    """Health check."""
    doc_count = db.query(Document).count()
    pass_count = db.query(ExtractionPass).count()
    
    return {
        "status": "healthy",
        "database": "connected",
        "documents": doc_count,
        "passes": pass_count,
        "version": "2.0.0"
    }


@app.post("/api/extract-raw-text")
async def extract_raw_text(file: UploadFile = File(...)):
    """
    Extract raw text from PDF using PDFplumber - NO regex, NO database.
    Returns CSV with all extracted text directly.
    """
    try:
        # Save uploaded file temporarily
        upload_path = UPLOAD_DIR / f"temp_raw_{int(time.time())}_{file.filename}"
        with open(upload_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        logger.info(f"[RAW TEXT] Processing: {file.filename}")
        
        # Initialize PDF handler
        pdf_handler = PDFHandler(str(upload_path))
        
        # Prepare CSV in memory
        csv_buffer = io.StringIO()
        csv_writer = csv.writer(csv_buffer)
        csv_writer.writerow(['Page', 'Line_Number', 'Text', 'Character_Count'])
        
        total_lines = 0
        total_chars = 0
        
        # Extract text from each page
        for page_num in range(pdf_handler.page_count):
            text = pdf_handler.extract_text_direct(page_num)
            
            if text:
                # Split into lines
                lines = text.split('\n')
                for line_num, line in enumerate(lines, 1):
                    line = line.strip()
                    if line:  # Skip empty lines
                        csv_writer.writerow([
                            page_num + 1,  # 1-indexed for user display
                            line_num,
                            line,
                            len(line)
                        ])
                        total_lines += 1
                        total_chars += len(line)
        
        # Clean up temp file
        upload_path.unlink(missing_ok=True)
        
        # Prepare response
        csv_content = csv_buffer.getvalue()
        csv_buffer.close()
        
        # Create output filename
        output_filename = f"raw_text_{Path(file.filename).stem}_{int(time.time())}.csv"
        
        logger.info(f"[RAW TEXT] Extracted {total_lines} lines ({total_chars} chars) from {file.filename}")
        
        # Return CSV as downloadable file
        from fastapi.responses import Response
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={output_filename}",
                "X-Total-Lines": str(total_lines),
                "X-Total-Characters": str(total_chars),
                "X-Pages": str(pdf_handler.page_count)
            }
        )
        
    except Exception as e:
        logger.error(f"[RAW TEXT] Error: {e}", exc_info=True)
        if upload_path.exists():
            upload_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=str(e))


# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")


# Add missing import
import uuid

