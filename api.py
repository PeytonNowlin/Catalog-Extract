#!/usr/bin/env python3
"""
Catalog Extractor API
FastAPI backend for PDF catalog extraction with web UI.
"""
import os
import sys
import shutil
import logging
from pathlib import Path
from typing import Optional, List
import asyncio
from datetime import datetime
import uuid

from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

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
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Catalog Extractor API",
    description="Extract part numbers and prices from PDF catalogs using OCR",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Storage directories
UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("outputs")
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# Job status tracking
jobs = {}


class ExtractionOptions(BaseModel):
    """Options for PDF extraction."""
    start_page: int = 0
    end_page: Optional[int] = None
    force_ocr: bool = False
    debug_mode: bool = False
    dpi: int = 300
    min_confidence: float = 50.0


class JobStatus(BaseModel):
    """Status of an extraction job."""
    job_id: str
    status: str  # 'pending', 'processing', 'completed', 'failed'
    progress: float  # 0-100
    message: str
    pdf_name: str
    total_pages: Optional[int] = None
    current_page: Optional[int] = None
    items_extracted: int = 0
    created_at: str
    completed_at: Optional[str] = None
    csv_file: Optional[str] = None
    summary_file: Optional[str] = None
    error: Optional[str] = None


class ExtractedItemResponse(BaseModel):
    """Response model for extracted item."""
    brand_code: Optional[str]
    part_number: Optional[str]
    price_type: Optional[str]
    price_value: Optional[float]
    currency: str
    page: int
    confidence: float
    raw_text: str


def create_job(pdf_name: str) -> str:
    """Create a new extraction job."""
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        'job_id': job_id,
        'status': 'pending',
        'progress': 0,
        'message': 'Job created',
        'pdf_name': pdf_name,
        'total_pages': None,
        'current_page': None,
        'items_extracted': 0,
        'created_at': datetime.now().isoformat(),
        'completed_at': None,
        'csv_file': None,
        'summary_file': None,
        'error': None
    }
    return job_id


def update_job(job_id: str, **kwargs):
    """Update job status."""
    if job_id in jobs:
        jobs[job_id].update(kwargs)


async def process_pdf_async(
    job_id: str,
    pdf_path: str,
    options: ExtractionOptions
):
    """Process PDF in background."""
    try:
        update_job(job_id, status='processing', message='Initializing...')
        
        # Initialize components
        pdf_handler = PDFHandler(pdf_path)
        preprocessor = ImagePreprocessor(debug_mode=options.debug_mode)
        ocr_handler = OCRHandler()
        table_detector = TableDetector(debug_mode=options.debug_mode)
        extractor = DataExtractor()
        validator = DataValidator(min_confidence=options.min_confidence)
        exporter = DataExporter()
        
        # Determine page range
        start_page = options.start_page
        end_page = options.end_page if options.end_page else pdf_handler.page_count
        total_pages = end_page - start_page
        
        update_job(
            job_id,
            total_pages=total_pages,
            message=f'Processing {total_pages} pages...'
        )
        
        all_items = []
        
        # Process each page
        for page_num in range(start_page, end_page):
            update_job(
                job_id,
                current_page=page_num + 1,
                progress=(page_num - start_page) / total_pages * 80,
                message=f'Processing page {page_num + 1}/{end_page}...'
            )
            
            try:
                # Check if text-based
                is_text_based = pdf_handler.is_text_based(page_num)
                
                if is_text_based and not options.force_ocr:
                    text = pdf_handler.extract_text_direct(page_num)
                    if text:
                        items = extractor.extract_from_text(text, page_num)
                        all_items.extend(items)
                else:
                    # OCR-based extraction
                    image = pdf_handler.render_page_to_image(page_num, dpi=options.dpi)
                    if image is not None:
                        preprocessed = preprocessor.preprocess(image, page_num)
                        full_text, words, lines = ocr_handler.extract_text(preprocessed, page_num)
                        rows = table_detector.detect_tables(preprocessed, lines, page_num)
                        
                        if rows:
                            items = extractor.extract_from_rows(rows, page_num)
                        else:
                            items = extractor.extract_from_text(full_text, page_num, words)
                        
                        all_items.extend(items)
            
            except Exception as e:
                logger.error(f"Error processing page {page_num}: {e}")
                continue
        
        # Validate and deduplicate
        update_job(job_id, progress=85, message='Validating data...')
        validated_items = validator.validate_items(all_items)
        final_items = validator.deduplicate_items(validated_items)
        
        # Export results
        update_job(job_id, progress=90, message='Exporting results...')
        output_dir = OUTPUT_DIR / job_id
        output_dir.mkdir(exist_ok=True)
        
        base_name = Path(pdf_path).stem
        csv_path = output_dir / f'{base_name}_extracted.csv'
        summary_path = output_dir / f'{base_name}_summary.txt'
        
        exporter.export_to_csv(final_items, str(csv_path))
        exporter.export_summary(final_items, str(summary_path))
        
        # Complete job
        update_job(
            job_id,
            status='completed',
            progress=100,
            message=f'Completed! Extracted {len(final_items)} items.',
            items_extracted=len(final_items),
            completed_at=datetime.now().isoformat(),
            csv_file=str(csv_path),
            summary_file=str(summary_path)
        )
        
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}", exc_info=True)
        update_job(
            job_id,
            status='failed',
            message='Processing failed',
            error=str(e),
            completed_at=datetime.now().isoformat()
        )


@app.get("/")
async def root():
    """Serve the web UI."""
    return FileResponse("static/index.html")


@app.post("/api/upload", response_model=JobStatus)
async def upload_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    start_page: int = Query(0, ge=0),
    end_page: Optional[int] = Query(None, ge=1),
    force_ocr: bool = Query(False),
    debug_mode: bool = Query(False),
    dpi: int = Query(300, ge=72, le=600),
    min_confidence: float = Query(50.0, ge=0, le=100)
):
    """
    Upload a PDF and start extraction job.
    
    - **file**: PDF file to process
    - **start_page**: Starting page (0-indexed)
    - **end_page**: Ending page (exclusive), None for all
    - **force_ocr**: Force OCR even for text-based PDFs
    - **debug_mode**: Save debug images
    - **dpi**: Resolution for rendering (72-600)
    - **min_confidence**: Minimum confidence threshold (0-100)
    """
    # Validate file
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")
    
    # Create job
    job_id = create_job(file.filename)
    
    # Save uploaded file
    upload_path = UPLOAD_DIR / f"{job_id}_{file.filename}"
    with open(upload_path, "wb") as f:
        content = await file.read()
        f.write(content)
    
    # Create options
    options = ExtractionOptions(
        start_page=start_page,
        end_page=end_page,
        force_ocr=force_ocr,
        debug_mode=debug_mode,
        dpi=dpi,
        min_confidence=min_confidence
    )
    
    # Start background processing
    background_tasks.add_task(process_pdf_async, job_id, str(upload_path), options)
    
    return JobStatus(**jobs[job_id])


@app.get("/api/jobs/{job_id}", response_model=JobStatus)
async def get_job_status(job_id: str):
    """Get status of an extraction job."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return JobStatus(**jobs[job_id])


@app.get("/api/jobs", response_model=List[JobStatus])
async def list_jobs(limit: int = Query(50, ge=1, le=100)):
    """List all jobs (most recent first)."""
    sorted_jobs = sorted(
        jobs.values(),
        key=lambda x: x['created_at'],
        reverse=True
    )
    return [JobStatus(**job) for job in sorted_jobs[:limit]]


@app.get("/api/jobs/{job_id}/results")
async def get_results(job_id: str):
    """Get extracted items from a completed job."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[job_id]
    
    if job['status'] != 'completed':
        raise HTTPException(status_code=400, detail="Job not completed yet")
    
    if not job['csv_file']:
        raise HTTPException(status_code=404, detail="Results not found")
    
    # Read CSV and return as JSON
    import csv
    results = []
    
    with open(job['csv_file'], 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            results.append({
                'brand_code': row['brand_code'],
                'part_number': row['part_number'],
                'price_type': row['price_type'],
                'price_value': float(row['price_value']) if row['price_value'] else None,
                'currency': row['currency'],
                'page': int(row['page']),
                'confidence': float(row['confidence']),
                'raw_text': row['raw_text']
            })
    
    return results


@app.get("/api/jobs/{job_id}/download/csv")
async def download_csv(job_id: str):
    """Download CSV file for a completed job."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[job_id]
    
    if job['status'] != 'completed':
        raise HTTPException(status_code=400, detail="Job not completed yet")
    
    if not job['csv_file'] or not os.path.exists(job['csv_file']):
        raise HTTPException(status_code=404, detail="CSV file not found")
    
    return FileResponse(
        job['csv_file'],
        media_type='text/csv',
        filename=os.path.basename(job['csv_file'])
    )


@app.get("/api/jobs/{job_id}/download/summary")
async def download_summary(job_id: str):
    """Download summary file for a completed job."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[job_id]
    
    if job['status'] != 'completed':
        raise HTTPException(status_code=400, detail="Job not completed yet")
    
    if not job['summary_file'] or not os.path.exists(job['summary_file']):
        raise HTTPException(status_code=404, detail="Summary file not found")
    
    return FileResponse(
        job['summary_file'],
        media_type='text/plain',
        filename=os.path.basename(job['summary_file'])
    )


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str):
    """Delete a job and its associated files."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[job_id]
    
    # Delete uploaded PDF
    upload_files = list(UPLOAD_DIR.glob(f"{job_id}_*"))
    for f in upload_files:
        f.unlink()
    
    # Delete output files
    output_dir = OUTPUT_DIR / job_id
    if output_dir.exists():
        shutil.rmtree(output_dir)
    
    # Remove from jobs dict
    del jobs[job_id]
    
    return {"message": "Job deleted successfully"}


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "jobs_count": len(jobs),
        "version": "1.0.0"
    }


# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")


if __name__ == "__main__":
    print("=" * 60)
    print("Catalog Extractor API Server")
    print("=" * 60)
    print("\nServer starting at http://localhost:8000")
    print("API docs available at http://localhost:8000/docs")
    print("\nPress CTRL+C to stop the server\n")
    
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

