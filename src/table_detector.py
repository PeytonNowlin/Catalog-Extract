"""
Table detection module.
Detects table structures and rebuilds rows from OCR data.
"""
import cv2
import numpy as np
from typing import List, Dict, Tuple, Optional
import logging
from dataclasses import dataclass
from .ocr_handler import OCRWord, OCRLine

logger = logging.getLogger(__name__)


@dataclass
class TableCell:
    """Represents a cell in a detected table."""
    text: str
    bbox: Tuple[int, int, int, int]  # (x, y, width, height)
    confidence: float
    row: int
    col: int
    words: List[OCRWord]


@dataclass
class TableRow:
    """Represents a row in a detected table."""
    cells: List[TableCell]
    row_num: int
    bbox: Tuple[int, int, int, int]
    avg_confidence: float


class TableDetector:
    """Detects and extracts table structures from images."""
    
    def __init__(self, debug_mode: bool = False):
        """
        Initialize table detector.
        
        Args:
            debug_mode: If True, saves debug images
        """
        self.debug_mode = debug_mode
        self.debug_images = {}
    
    def detect_tables(
        self, 
        image: np.ndarray, 
        lines: List[OCRLine],
        page_num: int = 0
    ) -> List[TableRow]:
        """
        Detect table structure and organize into rows.
        
        Args:
            image: Preprocessed image
            lines: OCR lines from the image
            page_num: Page number for tracking
            
        Returns:
            List of table rows
        """
        logger.info(f"Detecting tables on page {page_num}")
        
        # Try to detect table lines
        table_structure = self._detect_table_lines(image, page_num)
        
        if table_structure:
            logger.info("Table structure detected via line detection")
            rows = self._build_rows_from_structure(lines, table_structure)
        else:
            logger.info("No table lines detected, using position-based grouping")
            rows = self._build_rows_from_positions(lines)
        
        logger.info(f"Detected {len(rows)} table rows on page {page_num}")
        return rows
    
    def _detect_table_lines(
        self, 
        image: np.ndarray, 
        page_num: int
    ) -> Optional[Dict]:
        """
        Detect horizontal and vertical lines that form table structure.
        
        Args:
            image: Binary image
            page_num: Page number
            
        Returns:
            Dictionary with horizontal and vertical lines, or None
        """
        # Detect horizontal lines
        horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
        horizontal_lines = cv2.morphologyEx(
            image, cv2.MORPH_OPEN, horizontal_kernel, iterations=2
        )
        
        # Detect vertical lines
        vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40))
        vertical_lines = cv2.morphologyEx(
            image, cv2.MORPH_OPEN, vertical_kernel, iterations=2
        )
        
        # Combine lines
        table_mask = cv2.add(horizontal_lines, vertical_lines)
        
        self._save_debug(f"page_{page_num}_table_horizontal", horizontal_lines)
        self._save_debug(f"page_{page_num}_table_vertical", vertical_lines)
        self._save_debug(f"page_{page_num}_table_mask", table_mask)
        
        # Check if we detected enough lines
        if cv2.countNonZero(table_mask) < 1000:  # Threshold for minimum table structure
            return None
        
        # Find contours of table cells
        contours, _ = cv2.findContours(
            cv2.bitwise_not(table_mask),
            cv2.RETR_TREE,
            cv2.CHAIN_APPROX_SIMPLE
        )
        
        # Filter and sort contours by area
        cells = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            area = w * h
            
            # Filter out very small or very large contours
            if 500 < area < image.shape[0] * image.shape[1] * 0.5:
                cells.append((x, y, w, h))
        
        if len(cells) < 3:  # Need at least a few cells to be a table
            return None
        
        return {
            'horizontal_lines': horizontal_lines,
            'vertical_lines': vertical_lines,
            'cells': cells
        }
    
    def _build_rows_from_structure(
        self, 
        lines: List[OCRLine], 
        structure: Dict
    ) -> List[TableRow]:
        """
        Build table rows using detected table structure.
        
        Args:
            lines: OCR lines
            structure: Detected table structure
            
        Returns:
            List of table rows
        """
        cells_bboxes = structure['cells']
        
        # Match OCR words to cells
        matched_cells = []
        for cell_bbox in cells_bboxes:
            cx, cy, cw, ch = cell_bbox
            cell_words = []
            
            for line in lines:
                for word in line.words:
                    wx, wy, ww, wh = word.bbox
                    
                    # Check if word is inside cell
                    if (wx >= cx and wy >= cy and 
                        wx + ww <= cx + cw and wy + wh <= cy + ch):
                        cell_words.append(word)
            
            if cell_words:
                cell_text = ' '.join(w.text for w in cell_words)
                cell_confidence = np.mean([w.confidence for w in cell_words])
                matched_cells.append({
                    'bbox': cell_bbox,
                    'text': cell_text,
                    'confidence': cell_confidence,
                    'words': cell_words
                })
        
        # Group cells into rows based on y-coordinate
        return self._group_cells_into_rows(matched_cells)
    
    def _build_rows_from_positions(self, lines: List[OCRLine]) -> List[TableRow]:
        """
        Build table rows based on vertical positions of text lines.
        
        Args:
            lines: OCR lines
            
        Returns:
            List of table rows
        """
        if not lines:
            return []
        
        # Sort lines by y-coordinate
        sorted_lines = sorted(lines, key=lambda l: l.bbox[1])
        
        # Group lines that are close vertically (same row)
        rows = []
        current_row_lines = [sorted_lines[0]]
        row_num = 0
        
        for line in sorted_lines[1:]:
            prev_line = current_row_lines[-1]
            
            # Check if lines are on same row (within threshold)
            y_diff = abs(line.bbox[1] - prev_line.bbox[1])
            
            if y_diff < 15:  # Same row threshold
                current_row_lines.append(line)
            else:
                # Process current row
                row = self._create_row_from_lines(current_row_lines, row_num)
                rows.append(row)
                
                # Start new row
                current_row_lines = [line]
                row_num += 1
        
        # Process last row
        if current_row_lines:
            row = self._create_row_from_lines(current_row_lines, row_num)
            rows.append(row)
        
        return rows
    
    def _create_row_from_lines(
        self, 
        lines: List[OCRLine], 
        row_num: int
    ) -> TableRow:
        """
        Create a TableRow from a list of OCR lines.
        
        Args:
            lines: Lines that belong to the same row
            row_num: Row number
            
        Returns:
            TableRow object
        """
        # Sort lines by x-coordinate (left to right)
        sorted_lines = sorted(lines, key=lambda l: l.bbox[0])
        
        # Create cells
        cells = []
        for col_num, line in enumerate(sorted_lines):
            all_words = line.words
            
            cell = TableCell(
                text=line.text,
                bbox=line.bbox,
                confidence=line.confidence,
                row=row_num,
                col=col_num,
                words=all_words
            )
            cells.append(cell)
        
        # Calculate row bounding box
        if cells:
            min_x = min(c.bbox[0] for c in cells)
            min_y = min(c.bbox[1] for c in cells)
            max_x = max(c.bbox[0] + c.bbox[2] for c in cells)
            max_y = max(c.bbox[1] + c.bbox[3] for c in cells)
            row_bbox = (min_x, min_y, max_x - min_x, max_y - min_y)
            avg_confidence = np.mean([c.confidence for c in cells])
        else:
            row_bbox = (0, 0, 0, 0)
            avg_confidence = 0.0
        
        return TableRow(
            cells=cells,
            row_num=row_num,
            bbox=row_bbox,
            avg_confidence=avg_confidence
        )
    
    def _group_cells_into_rows(self, cells: List[Dict]) -> List[TableRow]:
        """
        Group cells into rows based on y-coordinates.
        
        Args:
            cells: List of cell dictionaries
            
        Returns:
            List of TableRow objects
        """
        if not cells:
            return []
        
        # Sort by y-coordinate
        sorted_cells = sorted(cells, key=lambda c: c['bbox'][1])
        
        # Group into rows
        rows = []
        current_row_cells = [sorted_cells[0]]
        row_num = 0
        
        for cell in sorted_cells[1:]:
            prev_cell = current_row_cells[-1]
            y_diff = abs(cell['bbox'][1] - prev_cell['bbox'][1])
            
            if y_diff < 15:
                current_row_cells.append(cell)
            else:
                # Create row
                row = self._finalize_row(current_row_cells, row_num)
                rows.append(row)
                
                current_row_cells = [cell]
                row_num += 1
        
        # Process last row
        if current_row_cells:
            row = self._finalize_row(current_row_cells, row_num)
            rows.append(row)
        
        return rows
    
    def _finalize_row(self, cell_dicts: List[Dict], row_num: int) -> TableRow:
        """Convert cell dictionaries to TableRow."""
        # Sort cells by x-coordinate
        sorted_cells = sorted(cell_dicts, key=lambda c: c['bbox'][0])
        
        cells = []
        for col_num, cell_dict in enumerate(sorted_cells):
            cell = TableCell(
                text=cell_dict['text'],
                bbox=cell_dict['bbox'],
                confidence=cell_dict['confidence'],
                row=row_num,
                col=col_num,
                words=cell_dict['words']
            )
            cells.append(cell)
        
        # Calculate row bbox
        min_x = min(c.bbox[0] for c in cells)
        min_y = min(c.bbox[1] for c in cells)
        max_x = max(c.bbox[0] + c.bbox[2] for c in cells)
        max_y = max(c.bbox[1] + c.bbox[3] for c in cells)
        
        return TableRow(
            cells=cells,
            row_num=row_num,
            bbox=(min_x, min_y, max_x - min_x, max_y - min_y),
            avg_confidence=np.mean([c.confidence for c in cells])
        )
    
    def _save_debug(self, name: str, image: np.ndarray):
        """Save debug image if debug mode is enabled."""
        if self.debug_mode:
            self.debug_images[name] = image.copy()
    
    def get_debug_images(self) -> Dict:
        """Get all saved debug images."""
        return self.debug_images

