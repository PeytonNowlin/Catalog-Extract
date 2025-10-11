"""
Database models and connection management.
"""
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey, Enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import enum
import os

# Database URL
DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'postgresql://catalog_user:catalog_pass_2024@localhost:5432/catalog_extractor'
)

# Create engine
engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class ExtractionStatus(enum.Enum):
    """Status of extraction job."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ExtractionMethod(enum.Enum):
    """Extraction method used."""
    AUTO_MULTI_PASS = "auto_multi_pass"
    CLAUDE_VISION = "claude_vision"
    TEXT_DIRECT = "text_direct"
    OCR_TABLE = "ocr_table"
    OCR_PLAIN = "ocr_plain"
    OCR_AGGRESSIVE = "ocr_aggressive"
    HYBRID = "hybrid"


# Database Models
class Document(Base):
    """Represents a PDF document."""
    __tablename__ = "documents"
    
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    file_hash = Column(String(64), unique=True, index=True)
    total_pages = Column(Integer)
    upload_date = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    extraction_passes = relationship("ExtractionPass", back_populates="document", cascade="all, delete-orphan")


class ExtractionPass(Base):
    """Represents a single extraction pass on a document."""
    __tablename__ = "extraction_passes"
    
    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    pass_number = Column(Integer, default=1)
    method = Column(Enum(ExtractionMethod), nullable=False)
    status = Column(Enum(ExtractionStatus), default=ExtractionStatus.PENDING)
    
    # Configuration
    start_page = Column(Integer, default=0)
    end_page = Column(Integer, nullable=True)
    dpi = Column(Integer, default=300)
    min_confidence = Column(Float, default=50.0)
    force_ocr = Column(Boolean, default=False)
    debug_mode = Column(Boolean, default=False)
    
    # Results
    items_extracted = Column(Integer, default=0)
    avg_confidence = Column(Float, nullable=True)
    processing_time = Column(Float, nullable=True)  # seconds
    api_cost = Column(Float, nullable=True)  # USD cost for API-based methods
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    
    # Relationships
    document = relationship("Document", back_populates="extraction_passes")
    extracted_items = relationship("ExtractedItem", back_populates="extraction_pass", cascade="all, delete-orphan")


class ExtractedItem(Base):
    """Represents an extracted item from the catalog."""
    __tablename__ = "extracted_items"
    
    id = Column(Integer, primary_key=True, index=True)
    extraction_pass_id = Column(Integer, ForeignKey("extraction_passes.id"), nullable=False)
    
    # Extracted data
    brand_code = Column(String(10), index=True)
    part_number = Column(String(100), index=True)
    price_type = Column(String(50))
    price_value = Column(Float)
    currency = Column(String(10), default="USD")
    
    # Context
    page = Column(Integer, nullable=False, index=True)
    confidence = Column(Float)
    raw_text = Column(Text)
    bbox_x = Column(Integer)
    bbox_y = Column(Integer)
    bbox_width = Column(Integer)
    bbox_height = Column(Integer)
    
    # Metadata
    extraction_method = Column(Enum(ExtractionMethod), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    extraction_pass = relationship("ExtractionPass", back_populates="extracted_items")


class ConsolidatedItem(Base):
    """Consolidated/merged items from multiple passes."""
    __tablename__ = "consolidated_items"
    
    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    
    # Best extracted data (from all passes)
    brand_code = Column(String(10), index=True)
    part_number = Column(String(100), index=True)
    price_type = Column(String(50))
    price_value = Column(Float)
    currency = Column(String(10), default="USD")
    
    # Aggregated confidence
    avg_confidence = Column(Float)
    source_count = Column(Integer)  # How many passes found this
    
    # Context
    page = Column(Integer, nullable=False)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# Database helper functions
def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize database tables."""
    Base.metadata.create_all(bind=engine)


def reset_db():
    """Drop and recreate all tables (for development)."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

