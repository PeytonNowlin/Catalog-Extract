# Docker Setup & Multi-Pass Extraction

## Quick Start with Docker

### 1. Start the Database

```bash
# Start PostgreSQL and pgAdmin
docker-compose up -d

# Check status
docker-compose ps
```

**Services:**
- PostgreSQL: `localhost:5432`
- pgAdmin: `http://localhost:5050`
  - Email: `admin@catalog.local`
  - Password: `admin`

### 2. Initialize Database

```bash
# Install Python dependencies (if not already installed)
pip install sqlalchemy psycopg2-binary alembic

# Initialize database tables
python -c "from src.database import init_db; init_db()"
```

### 3. Start the Application

```bash
python main.py
```

Visit: **http://localhost:8000**

## Multi-Pass Extraction

The application now supports multiple extraction passes with different strategies:

### Extraction Methods

1. **text_direct** - Direct text extraction (fastest, for text-based PDFs)
2. **ocr_table** - OCR with table detection (best for structured tables)
3. **ocr_plain** - OCR without table detection (good for unstructured text)
4. **ocr_aggressive** - High-DPI OCR with multiple attempts (most thorough)
5. **hybrid** - Combines multiple methods (most comprehensive)

### How Multi-Pass Works

1. **First Pass**: Quick extraction using preferred method
2. **Second Pass**: Different method to catch missed items
3. **Third Pass**: Aggressive method for difficult pages
4. **Consolidation**: Merge results, remove duplicates, keep best confidence

### Example Workflow

```python
# Pass 1: Try text extraction first
POST /api/upload?method=text_direct

# Pass 2: Use OCR on pages that had poor results
POST /api/passes/{document_id}/new?method=ocr_table&pages=5,7,12

# Pass 3: Aggressive extraction on difficult pages
POST /api/passes/{document_id}/new?method=ocr_aggressive&pages=7
```

## Database Schema

### Tables

- **documents** - PDF files uploaded
- **extraction_passes** - Each extraction attempt
- **extracted_items** - Raw extracted data (all passes)
- **consolidated_items** - Merged/best items from all passes

### Viewing Data

**pgAdmin:**
1. Open http://localhost:5050
2. Login with `admin@catalog.local` / `admin`
3. Add Server:
   - Name: `Catalog Extractor`
   - Host: `postgres`
   - Port: `5432`
   - Database: `catalog_extractor`
   - Username: `catalog_user`
   - Password: `catalog_pass_2024`

## API Endpoints

### New Endpoints

**Start new extraction pass:**
```
POST /api/documents/{doc_id}/passes
Body: {
  "method": "ocr_table",
  "start_page": 0,
  "end_page": 10,
  "dpi": 400
}
```

**Get all passes for document:**
```
GET /api/documents/{doc_id}/passes
```

**Get consolidated items:**
```
GET /api/documents/{doc_id}/items/consolidated
```

**Compare passes:**
```
GET /api/documents/{doc_id}/passes/compare
```

## Docker Commands

```bash
# Start services
docker-compose up -d

# Stop services
docker-compose down

# View logs
docker-compose logs -f postgres

# Restart
docker-compose restart

# Stop and remove volumes (clears database!)
docker-compose down -v

# Backup database
docker exec catalog-extractor-db pg_dump -U catalog_user catalog_extractor > backup.sql

# Restore database
cat backup.sql | docker exec -i catalog-extractor-db psql -U catalog_user catalog_extractor
```

## Environment Variables

Create `.env` file:

```env
DATABASE_URL=postgresql://catalog_user:catalog_pass_2024@localhost:5432/catalog_extractor
DEBUG_MODE=false
MAX_PASSES=5
```

## Benefits of Multi-Pass

✅ **Better Accuracy** - Multiple methods catch different patterns  
✅ **Confidence Scoring** - Track which method works best  
✅ **Iterative Improvement** - Refine extraction on difficult pages  
✅ **Data Persistence** - All results stored and queryable  
✅ **Comparison** - Compare results between passes  
✅ **No Data Loss** - Keep all raw extractions  

## Troubleshooting

**Database connection error:**
```bash
# Check if PostgreSQL is running
docker-compose ps

# Restart database
docker-compose restart postgres
```

**Port already in use:**
```bash
# Change ports in docker-compose.yml
ports:
  - "5433:5432"  # Use 5433 instead of 5432
```

**Clear all data:**
```bash
docker-compose down -v
docker-compose up -d
python -c "from src.database import init_db; init_db()"
```

