"""
Validation module.
Validates extracted data and calculates confidence scores.
"""
import re
from typing import List, Tuple
import logging
from .extractor import ExtractedItem

logger = logging.getLogger(__name__)


class DataValidator:
    """Validates extracted data and assigns confidence scores."""
    
    def __init__(self, min_confidence: float = 50.0):
        """
        Initialize validator.
        
        Args:
            min_confidence: Minimum OCR confidence threshold (0-100)
        """
        self.min_confidence = min_confidence
    
    def validate_items(self, items: List[ExtractedItem]) -> List[ExtractedItem]:
        """
        Validate and filter extracted items.
        
        Args:
            items: List of extracted items
            
        Returns:
            List of validated items with updated confidence scores
        """
        logger.info(f"Validating {len(items)} extracted items")
        
        validated = []
        for item in items:
            # Calculate overall confidence
            confidence = self._calculate_confidence(item)
            
            # Update item confidence
            item.confidence = confidence
            
            # Filter by minimum confidence
            if confidence >= self.min_confidence:
                validated.append(item)
            else:
                logger.debug(
                    f"Filtered item due to low confidence ({confidence:.1f}%): "
                    f"{item.part_number} - ${item.price_value}"
                )
        
        logger.info(f"Validated {len(validated)} items (filtered {len(items) - len(validated)})")
        return validated
    
    def _calculate_confidence(self, item: ExtractedItem) -> float:
        """
        Calculate overall confidence score for an item.
        
        Combines OCR confidence with validation checks.
        
        Args:
            item: Extracted item
            
        Returns:
            Confidence score (0-100)
        """
        scores = []
        
        # Base OCR confidence
        scores.append(item.confidence)
        
        # Part number validation
        if item.part_number:
            part_score = self._validate_part_number(item.part_number)
            scores.append(part_score)
        
        # Price validation
        if item.price_value is not None:
            price_score = self._validate_price(item.price_value)
            scores.append(price_score)
        
        # Brand code validation
        if item.brand_code:
            brand_score = self._validate_brand_code(item.brand_code)
            scores.append(brand_score)
        
        # Completeness bonus
        completeness = self._check_completeness(item)
        scores.append(completeness)
        
        # Calculate weighted average
        # Give more weight to OCR confidence
        if len(scores) > 1:
            weighted_score = (scores[0] * 0.4) + (sum(scores[1:]) / len(scores[1:]) * 0.6)
        else:
            weighted_score = scores[0]
        
        return weighted_score
    
    def _validate_part_number(self, part_number: str) -> float:
        """
        Validate part number format.
        
        Args:
            part_number: Part number string
            
        Returns:
            Confidence score (0-100)
        """
        score = 50.0  # Base score
        
        # Length check (typical part numbers are 5-15 chars)
        if 5 <= len(part_number) <= 15:
            score += 20
        elif len(part_number) > 15:
            score -= 10
        
        # Has alphanumeric mix
        has_letters = bool(re.search(r'[A-Za-z]', part_number))
        has_numbers = bool(re.search(r'\d', part_number))
        
        if has_letters and has_numbers:
            score += 20
        elif has_numbers:
            score += 10  # Pure numeric is okay
        
        # Has proper formatting (dashes, etc.)
        if '-' in part_number or ' ' in part_number:
            score += 10
        
        # Not too many special characters
        special_chars = len(re.findall(r'[^A-Za-z0-9\-\s]', part_number))
        if special_chars > 2:
            score -= 20
        
        return max(0, min(100, score))
    
    def _validate_price(self, price: float) -> float:
        """
        Validate price value.
        
        Args:
            price: Price value
            
        Returns:
            Confidence score (0-100)
        """
        score = 50.0
        
        # Reasonable range check
        if 0.10 <= price <= 10000:
            score += 30
        elif 10000 < price <= 100000:
            score += 15
        else:
            score -= 20
        
        # Has cents (more likely to be real price)
        if price % 1 != 0:
            score += 20
        
        # Round numbers are suspicious unless very small/large
        if price % 10 == 0 and 10 < price < 1000:
            score -= 10
        
        return max(0, min(100, score))
    
    def _validate_brand_code(self, brand_code: str) -> float:
        """
        Validate brand code format.
        
        Args:
            brand_code: Brand code string
            
        Returns:
            Confidence score (0-100)
        """
        score = 50.0
        
        # Length check (typically 2-4 uppercase letters)
        if 2 <= len(brand_code) <= 4:
            score += 30
        else:
            score -= 20
        
        # All uppercase
        if brand_code.isupper():
            score += 20
        
        # All letters
        if brand_code.isalpha():
            score += 10
        else:
            score -= 20
        
        return max(0, min(100, score))
    
    def _check_completeness(self, item: ExtractedItem) -> float:
        """
        Check how complete the extracted data is.
        
        Args:
            item: Extracted item
            
        Returns:
            Completeness score (0-100)
        """
        fields_present = 0
        total_fields = 4
        
        if item.brand_code:
            fields_present += 1
        if item.part_number:
            fields_present += 1
        if item.price_value is not None:
            fields_present += 1
        if item.price_type:
            fields_present += 1
        
        return (fields_present / total_fields) * 100
    
    def deduplicate_items(self, items: List[ExtractedItem]) -> List[ExtractedItem]:
        """
        Remove duplicate items, keeping the one with highest confidence.
        
        Args:
            items: List of extracted items
            
        Returns:
            Deduplicated list
        """
        # Group by part number + page
        groups = {}
        
        for item in items:
            key = (item.part_number, item.page)
            
            if key not in groups:
                groups[key] = item
            else:
                # Keep item with higher confidence
                if item.confidence > groups[key].confidence:
                    groups[key] = item
        
        deduplicated = list(groups.values())
        
        if len(deduplicated) < len(items):
            logger.info(f"Removed {len(items) - len(deduplicated)} duplicate items")
        
        return deduplicated

