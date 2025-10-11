"""
Data extraction module.
Extracts part numbers, prices, and other structured data using regex patterns.
"""
import re
from typing import List, Dict, Optional, Tuple
import logging
from dataclasses import dataclass
from .table_detector import TableRow, TableCell
from .ocr_handler import OCRWord

logger = logging.getLogger(__name__)


@dataclass
class ExtractedItem:
    """Represents an extracted catalog item."""
    brand_code: Optional[str]
    part_number: Optional[str]
    price_type: Optional[str]  # e.g., 'retail', 'sale', 'each'
    price_value: Optional[float]
    currency: str
    page: int
    confidence: float
    raw_text: str
    bbox: Optional[Tuple[int, int, int, int]]


class DataExtractor:
    """Extracts structured data from OCR results."""
    
    # Regex patterns for different data types
    PATTERNS = {
        # Part numbers: specific catalog formats only
        'part_number': [
            r'\b(\d{2}[-]\d{3,4}[A-Z0-9]{0,6}(?:[-]\d+)?)\b',     # 41-3525, 28-9313PT, 11-1413P6, 35-133P-16, 36-9313PT-1
            r'\b(\d{2}[A-Z][-]?\d{4})\b',                          # 43D7276, 36U-9332
            r'\b([A-Z]{2,4}[-]\d{4,6}[-]?[A-Z0-9]{0,6})\b',       # ABC-12345, SUM-715030
            r'\b([A-Z]{3}\d{4,6})\b',                              # SUM715030, EXG1181
            r'\b(\d{2}[-]\d{3,4}[A-Z])\b',                         # 45-517A, 45-417A, 45-2280
        ],
        
        # Prices: $X.XX, $X,XXX.XX, etc.
        'price': [
            r'\$\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)',              # $1,234.56
            r'USD\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)',            # USD 1234.56
            r'(\d{1,3}(?:,\d{3})*\.\d{2})\s*(?:USD|\$)?',         # 1234.56 USD
        ],
        
        # Brand codes: 2-4 uppercase letters
        'brand_code': [
            r'\b([A-Z]{2,4})\b',
        ],
        
        # Price types
        'price_type': [
            r'\b(retail|sale|each|per\s*unit|list\s*price|your\s*price)\b',
        ],
    }
    
    def __init__(self):
        """Initialize data extractor."""
        self.compiled_patterns = {}
        for key, patterns in self.PATTERNS.items():
            self.compiled_patterns[key] = [
                re.compile(p, re.IGNORECASE) for p in patterns
            ]
    
    def extract_from_rows(
        self, 
        rows: List[TableRow], 
        page_num: int
    ) -> List[ExtractedItem]:
        """
        Extract structured data from table rows.
        
        Args:
            rows: List of detected table rows
            page_num: Page number
            
        Returns:
            List of extracted items
        """
        logger.info(f"Extracting data from {len(rows)} rows on page {page_num}")
        
        extracted_items = []
        
        for row in rows:
            items = self._extract_from_row(row, page_num)
            extracted_items.extend(items)
        
        logger.info(f"Extracted {len(extracted_items)} items from page {page_num}")
        return extracted_items
    
    def _extract_from_row(self, row: TableRow, page_num: int) -> List[ExtractedItem]:
        """
        Extract data from a single table row.
        
        Args:
            row: Table row
            page_num: Page number
            
        Returns:
            List of extracted items (usually 0 or 1)
        """
        # Combine all text from the row
        row_text = ' '.join(cell.text for cell in row.cells)
        
        # Try to find part number
        part_numbers = self._extract_pattern(row_text, 'part_number')
        
        # Try to find prices
        prices = self._extract_prices(row_text)
        
        # If we have neither part number nor price, skip this row
        if not part_numbers and not prices:
            return []
        
        # Try to find brand code
        brand_codes = self._extract_pattern(row_text, 'brand_code')
        brand_code = brand_codes[0] if brand_codes else None
        
        # Try to find price type
        price_types = self._extract_pattern(row_text, 'price_type')
        price_type = price_types[0] if price_types else 'retail'
        
        # Create items for each part number/price combination
        items = []
        
        # Case 1: Have both part numbers and prices
        if part_numbers and prices:
            # Pair them up (assume same length or use first of each)
            for part_num in part_numbers:
                for price_val in prices[:1]:  # Use first price for each part
                    item = ExtractedItem(
                        brand_code=brand_code,
                        part_number=part_num,
                        price_type=price_type,
                        price_value=price_val,
                        currency='USD',
                        page=page_num,
                        confidence=row.avg_confidence,
                        raw_text=row_text,
                        bbox=row.bbox
                    )
                    items.append(item)
        
        # Case 2: Only part numbers (no price)
        elif part_numbers:
            for part_num in part_numbers:
                item = ExtractedItem(
                    brand_code=brand_code,
                    part_number=part_num,
                    price_type=None,
                    price_value=None,
                    currency='USD',
                    page=page_num,
                    confidence=row.avg_confidence,
                    raw_text=row_text,
                    bbox=row.bbox
                )
                items.append(item)
        
        # Case 3: Only prices (no part number)
        elif prices:
            for price_val in prices:
                item = ExtractedItem(
                    brand_code=brand_code,
                    part_number=None,
                    price_type=price_type,
                    price_value=price_val,
                    currency='USD',
                    page=page_num,
                    confidence=row.avg_confidence,
                    raw_text=row_text,
                    bbox=row.bbox
                )
                items.append(item)
        
        return items
    
    def _extract_pattern(self, text: str, pattern_type: str) -> List[str]:
        """
        Extract matches for a specific pattern type.
        
        Args:
            text: Text to search
            pattern_type: Type of pattern to search for
            
        Returns:
            List of matched strings
        """
        matches = []
        
        for pattern in self.compiled_patterns.get(pattern_type, []):
            found = pattern.findall(text)
            matches.extend(found)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_matches = []
        for match in matches:
            if match not in seen:
                seen.add(match)
                unique_matches.append(match)
        
        return unique_matches
    
    def _extract_prices(self, text: str) -> List[float]:
        """
        Extract and parse price values.
        
        Args:
            text: Text to search
            
        Returns:
            List of price values as floats
        """
        price_strings = self._extract_pattern(text, 'price')
        
        prices = []
        for price_str in price_strings:
            try:
                # Remove commas and convert to float
                price_val = float(price_str.replace(',', ''))
                # Sanity check: price should be reasonable
                if 0.01 <= price_val <= 1_000_000:
                    prices.append(price_val)
            except ValueError:
                logger.warning(f"Could not parse price: {price_str}")
                continue
        
        return prices
    
    def extract_from_text(
        self, 
        text: str, 
        page_num: int,
        words: List[OCRWord] = None
    ) -> List[ExtractedItem]:
        """
        Extract data from plain text (fallback for non-table PDFs).
        
        Args:
            text: Full text from page
            page_num: Page number
            words: Optional list of OCR words for confidence
            
        Returns:
            List of extracted items
        """
        logger.info(f"Extracting data from plain text on page {page_num}")
        
        # Split into lines
        lines = text.split('\n')
        
        items = []
        for line_num, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            
            # Extract data from line
            part_numbers = self._extract_pattern(line, 'part_number')
            prices = self._extract_prices(line)
            
            if not part_numbers and not prices:
                continue
            
            brand_codes = self._extract_pattern(line, 'brand_code')
            brand_code = brand_codes[0] if brand_codes else None
            
            price_types = self._extract_pattern(line, 'price_type')
            price_type = price_types[0] if price_types else 'retail'
            
            # Calculate average confidence from words in this line
            confidence = 80.0  # Default for text-based PDFs
            if words:
                line_words = [w for w in words if w.text in line]
                if line_words:
                    confidence = sum(w.confidence for w in line_words) / len(line_words)
            
            # Create items
            if part_numbers and prices:
                for part_num in part_numbers:
                    for price_val in prices[:1]:
                        item = ExtractedItem(
                            brand_code=brand_code,
                            part_number=part_num,
                            price_type=price_type,
                            price_value=price_val,
                            currency='USD',
                            page=page_num,
                            confidence=confidence,
                            raw_text=line,
                            bbox=None
                        )
                        items.append(item)
            elif part_numbers:
                for part_num in part_numbers:
                    item = ExtractedItem(
                        brand_code=brand_code,
                        part_number=part_num,
                        price_type=None,
                        price_value=None,
                        currency='USD',
                        page=page_num,
                        confidence=confidence,
                        raw_text=line,
                        bbox=None
                    )
                    items.append(item)
            elif prices:
                for price_val in prices:
                    item = ExtractedItem(
                        brand_code=brand_code,
                        part_number=None,
                        price_type=price_type,
                        price_value=price_val,
                        currency='USD',
                        page=page_num,
                        confidence=confidence,
                        raw_text=line,
                        bbox=None
                    )
                    items.append(item)
        
        logger.info(f"Extracted {len(items)} items from plain text on page {page_num}")
        return items

