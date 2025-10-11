# Catalog Extractor

A comprehensive Python application for extracting part numbers, prices, and other structured data from PDF catalogs. Supports both text-based and image-based PDFs with OCR capabilities.

## Features

- **Dual PDF Support**: Handles both text-based and image-based PDFs
- **OCR Processing**: Uses Tesseract OCR with advanced preprocessing
- **Image Preprocessing**: 
  - Automatic deskewing
  - Adaptive thresholding
  - Noise reduction
  - Morphological operations
- **Table Detection**: Detects and reconstructs table structures
- **Pattern Extraction**: Regex-based extraction of:
  - Part numbers (multiple formats)
  - Prices (various currency formats)
  - Brand codes
  - Price types (retail, sale, etc.)
- **Validation**: Confidence scoring and data validation
- **CSV Export**: Clean CSV output with all extracted data
- **Debug Mode**: Saves intermediate images with bounding boxes

## Installation

### Prerequisites

1. **Python 3.8+**

2. **Tesseract OCR**
   - **Windows**: Download from [GitHub](https://github.com/UB-Mannheim/tesseract/wiki)
   - **Linux**: `sudo apt-get install tesseract-ocr`
   - **macOS**: `brew install tesseract`

3. **Python Dependencies**

```bash
pip install -r requirements.txt
```

## Usage

### Basic Usage

Extract from entire catalog:
```bash
python catalog_extractor.py SummitRacingCatalog.pdf
```

### Advanced Options

Process specific page range:
```bash
python catalog_extractor.py catalog.pdf --start-page 5 --end-page 10
```

Enable debug mode (saves intermediate images):
```bash
python catalog_extractor.py catalog.pdf --debug
```

Set custom output directory:
```bash
python catalog_extractor.py catalog.pdf --output-dir my_output
```

Adjust DPI for better quality:
```bash
python catalog_extractor.py catalog.pdf --dpi 400
```

Set minimum confidence threshold:
```bash
python catalog_extractor.py catalog.pdf --min-confidence 70
```

Force OCR on text-based PDFs:
```bash
python catalog_extractor.py catalog.pdf --force-ocr
```

### All Options

```
positional arguments:
  pdf_path              Path to PDF catalog

optional arguments:
  -h, --help            Show help message and exit
  -o, --output-dir      Output directory (default: output)
  --start-page          Starting page number (0-indexed, default: 0)
  --end-page            Ending page number (exclusive, default: all pages)
  --debug               Enable debug mode (saves intermediate images)
  --dpi                 DPI for rendering pages (default: 300)
  --min-confidence      Minimum confidence threshold 0-100 (default: 50.0)
  --force-ocr           Force OCR even for text-based PDFs
```

## Output

### CSV Output

The main output is a CSV file with the following columns:

| Column | Description |
|--------|-------------|
| brand_code | Brand/manufacturer code (2-4 letters) |
| part_number | Product part number |
| price_type | Type of price (retail, sale, each, etc.) |
| price_value | Numeric price value |
| currency | Currency code (USD, etc.) |
| page | Page number where item was found |
| confidence | Confidence score (0-100) |
| raw_text | Original text from which data was extracted |

### Summary Report

A text summary is also generated containing:
- Total items extracted
- Items with part numbers/prices/brand codes
- Average confidence scores
- Price statistics (min, max, average)
- List of brand codes found
- Pages processed

### Debug Images (if --debug enabled)

When debug mode is enabled, the following images are saved:

- `page_XXX_original.png` - Original rendered page
- `page_XXX_preprocessed.png` - Final preprocessed image
- `page_XXX_01_grayscale.png` - Grayscale conversion
- `page_XXX_02_deskewed.png` - After deskewing
- `page_XXX_03_denoised.png` - After noise removal
- `page_XXX_04_thresholded.png` - After thresholding
- `page_XXX_05_cleaned.png` - Final cleaned image
- `page_XXX_ocr_boxes.png` - OCR results with bounding boxes
- `page_XXX_table_*.png` - Table detection visualizations

## Architecture

The application is built with a modular pipeline architecture:

```
PDF Input → PDF Handler → Preprocessor → OCR Handler → Table Detector → 
Extractor → Validator → Exporter → CSV Output
```

### Modules

1. **pdf_handler.py**: PDF reading with PyMuPDF and pdfplumber
2. **preprocessor.py**: Image preprocessing with OpenCV
3. **ocr_handler.py**: OCR with Tesseract and pytesseract
4. **table_detector.py**: Table structure detection and row reconstruction
5. **extractor.py**: Regex-based data extraction
6. **validator.py**: Data validation and confidence scoring
7. **exporter.py**: CSV and summary export

## Customization

### Adding Custom Part Number Patterns

Edit `src/extractor.py` and add patterns to the `PATTERNS` dictionary:

```python
'part_number': [
    r'\b([A-Z]{2,4}[-\s]?\d{3,8}[-\s]?[A-Z0-9]{0,4})\b',
    r'YOUR_CUSTOM_PATTERN',
    # ...
]
```

### Adjusting Preprocessing

Modify `src/preprocessor.py` methods:
- `_deskew()`: Skew correction
- `_threshold()`: Binarization
- `_morphological_cleanup()`: Noise removal

### Changing Validation Rules

Edit `src/validator.py` methods:
- `_validate_part_number()`: Part number validation
- `_validate_price()`: Price validation
- `_calculate_confidence()`: Confidence calculation

## Troubleshooting

### Tesseract Not Found

**Error**: `RuntimeError: Tesseract OCR not found`

**Solution**: 
- Ensure Tesseract is installed
- Windows: Add Tesseract to PATH or set: 
  ```python
  pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
  ```

### Low Extraction Quality

**Solutions**:
- Increase DPI: `--dpi 400`
- Enable debug mode to inspect preprocessing: `--debug`
- Lower confidence threshold: `--min-confidence 30`
- Force OCR if text extraction isn't working: `--force-ocr`

### No Items Extracted

**Solutions**:
- Check if PDF is image-based or text-based
- Verify regex patterns match your catalog format
- Enable debug mode to inspect OCR results
- Check log file: `catalog_extraction.log`

### Memory Issues with Large PDFs

**Solutions**:
- Process in chunks: `--start-page 0 --end-page 10`
- Reduce DPI: `--dpi 200`
- Process one page at a time

## Examples

### Example 1: Quick Test on First Page

```bash
python catalog_extractor.py catalog.pdf --end-page 1 --debug
```

Check the debug images to verify OCR quality.

### Example 2: Production Run with High Quality

```bash
python catalog_extractor.py catalog.pdf --dpi 400 --min-confidence 70 --output-dir final_output
```

### Example 3: Process Specific Section

```bash
python catalog_extractor.py catalog.pdf --start-page 20 --end-page 30
```

## Performance

- **Text-based PDFs**: ~1-2 seconds per page
- **Image-based PDFs**: ~5-10 seconds per page (depends on DPI and complexity)
- **Memory usage**: ~200-500 MB per page at 300 DPI



## Contributing

Contributions welcome! Areas for improvement:
- Additional part number patterns
- Multi-language support
- Table detection accuracy
- Price format handling
- Performance optimization

## Support

For issues or questions:
1. Check the troubleshooting section
2. Review `catalog_extraction.log`
3. Run with `--debug` to inspect processing steps
4. Check that your PDF matches expected formats

