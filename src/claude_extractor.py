"""
Claude Vision API Integration for Catalog Extraction
Uses Anthropic's Claude 3 Sonnet for intelligent part number and price extraction.
"""
import logging
import base64
import json
import io
import os
import numpy as np
from typing import List, Dict, Optional
from dataclasses import dataclass
from anthropic import Anthropic
from dotenv import load_dotenv
from PIL import Image

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


@dataclass
class ExtractedItem:
    """Data structure for extracted catalog items."""
    brand_code: Optional[str]
    part_number: Optional[str]
    price_type: Optional[str]
    price_value: Optional[float]
    currency: str
    page: int
    confidence: float
    raw_text: Optional[str]
    bbox: Optional[tuple] = None


class ClaudeExtractor:
    """Extracts catalog data using Claude Vision API."""
    
    # Pricing constants
    SONNET_INPUT_COST = 0.003  # per 1k tokens
    SONNET_OUTPUT_COST = 0.015  # per 1k tokens
    AVG_IMAGE_TOKENS = 1500  # Average tokens per catalog page image
    AVG_OUTPUT_TOKENS = 500  # Average response tokens
    
    def __init__(self):
        """Initialize Claude API client."""
        api_key = os.getenv('ANTHROPIC_API_KEY')
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY not found in environment. "
                "Please add it to your .env file."
            )
        
        self.client = Anthropic(api_key=api_key)
        self.model = "claude-3-5-sonnet-20241022"  # Latest Sonnet model
        self.total_cost = 0.0
        logger.info(f"Claude Vision initialized with model: {self.model}")
    
    def extract_from_page(
        self,
        pdf_handler,
        page_num: int,
        options: Dict
    ) -> tuple[List[ExtractedItem], float]:
        """
        Extract catalog data from a PDF page using Claude Vision.
        
        Returns:
            tuple: (list of ExtractedItem objects, API cost in USD)
        """
        try:
            # Render page to image
            dpi = options.get('dpi', 300)
            image = pdf_handler.render_page_to_image(page_num, dpi=dpi)
            
            # Convert to base64
            image_data = self._image_to_base64(image)
            
            # Create prompt
            prompt = self._create_extraction_prompt(options)
            
            # Call Claude API
            logger.info(f"Sending page {page_num + 1} to Claude Vision API...")
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": image_data,
                                },
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ],
                    }
                ],
            )
            
            # Calculate cost
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            cost = self._calculate_cost(input_tokens, output_tokens)
            self.total_cost += cost
            
            logger.info(
                f"Claude API response: {input_tokens} input tokens, "
                f"{output_tokens} output tokens, ${cost:.4f}"
            )
            
            # Parse response
            items = self._parse_response(response.content[0].text, page_num)
            
            logger.info(f"Extracted {len(items)} items from page {page_num + 1}")
            return items, cost
            
        except Exception as e:
            logger.error(f"Claude extraction failed for page {page_num}: {e}", exc_info=True)
            return [], 0.0
    
    def _image_to_base64(self, image) -> str:
        """Convert image (numpy array or PIL Image) to base64 string."""
        # Convert numpy array to PIL Image if needed
        if isinstance(image, np.ndarray):
            image = Image.fromarray(image)
        
        buffered = io.BytesIO()
        # Convert to RGB if needed (remove alpha channel)
        if image.mode in ('RGBA', 'LA', 'P'):
            image = image.convert('RGB')
        image.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode('utf-8')
    
    def _create_extraction_prompt(self, options: Dict) -> str:
        """Create optimized prompt for catalog extraction."""
        enhanced = options.get('enhanced_prompt', False)
        
        base_prompt = """You are analyzing an automotive/product catalog page. Extract ALL part numbers (SKUs/item codes) and prices.

CRITICAL: A "part_number" is a SHORT alphanumeric SKU/item code, NOT a product name or description.

Examples of CORRECT part numbers:
- "ABC-123", "12345-XYZ", "SUM-715030", "EXG-1181", "HRC-HCL188"
- Short codes with letters, numbers, dashes (usually 5-15 characters)

Examples of WRONG part numbers (these are product names, DO NOT use):
- "BedRug-Classic-Bed-Liners" (this is a product name)
- "DEE-ZEE-GUARDIAN" (this is a model/product name)
- "RETRAX-ONE-MX" (this is a product line name)

For each product, extract:
- part_number: The SHORT SKU/item code (look near prices, in small text, in tables)
- price_value: Numeric price only (29.99, not $29.99)
- currency: Usually USD
- brand_code: Brand abbreviation (2-4 letters like "SUM", "EGR", "DEE")
- price_type: "retail", "from", "each", "sale", etc.

Return ONLY valid JSON (no markdown):
[
  {
    "part_number": "SUM-715030",
    "price_value": 29.99,
    "currency": "USD",
    "brand_code": "SUM",
    "price_type": "retail"
  }
]

Rules:
- Part numbers are usually NEAR the price, in tables, or in small print
- IGNORE product names, titles, and marketing descriptions
- If you only see a product name but no SKU code, SKIP that item
- Extract ONLY items where you can find an actual part number code
- Return empty array [] if no valid part numbers found
- ONLY return the JSON array, nothing else"""

        if enhanced:
            base_prompt += """

ENHANCED MODE: This page had low confidence in previous extraction.
- Look extra carefully for small text and SKU codes near prices
- Check table cells, corners, headers, and footers
- Part numbers may be in smaller font than product names
- Look for format like: XXX-####, ####-XX, brand codes + numbers
- Some part numbers may be partially visible at page edges"""
        
        return base_prompt
    
    def _parse_response(self, response_text: str, page_num: int) -> List[ExtractedItem]:
        """Parse Claude's JSON response into ExtractedItem objects."""
        try:
            # Clean response (remove markdown if present)
            cleaned = response_text.strip()
            if cleaned.startswith('```'):
                # Extract JSON from markdown code block
                lines = cleaned.split('\n')
                cleaned = '\n'.join(lines[1:-1]) if len(lines) > 2 else cleaned
                cleaned = cleaned.replace('```json', '').replace('```', '').strip()
            
            # Parse JSON
            data = json.loads(cleaned)
            
            if not isinstance(data, list):
                logger.warning(f"Expected array, got {type(data)}")
                return []
            
            items = []
            for idx, item_data in enumerate(data):
                try:
                    # Validate required fields
                    part_number = item_data.get('part_number')
                    if not part_number:
                        continue
                    
                    # Extract price
                    price_value = item_data.get('price_value')
                    if price_value is not None:
                        try:
                            price_value = float(price_value)
                        except (ValueError, TypeError):
                            price_value = None
                    
                    # Claude Vision is typically 85-95% confident
                    # Adjust based on completeness of data
                    confidence = 90.0
                    if not price_value:
                        confidence -= 10
                    if not item_data.get('brand_code'):
                        confidence -= 5
                    
                    item = ExtractedItem(
                        brand_code=item_data.get('brand_code'),
                        part_number=part_number,
                        price_type=item_data.get('price_type', 'retail'),
                        price_value=price_value,
                        currency=item_data.get('currency', 'USD'),
                        page=page_num,
                        confidence=confidence,
                        raw_text=json.dumps(item_data),
                        bbox=None  # Claude doesn't provide bounding boxes
                    )
                    items.append(item)
                    
                except Exception as e:
                    logger.warning(f"Failed to parse item {idx}: {e}")
                    continue
            
            return items
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude response as JSON: {e}")
            logger.debug(f"Response text: {response_text[:500]}")
            return []
        except Exception as e:
            logger.error(f"Error parsing Claude response: {e}", exc_info=True)
            return []
    
    def _calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Calculate API cost in USD."""
        input_cost = (input_tokens / 1000) * self.SONNET_INPUT_COST
        output_cost = (output_tokens / 1000) * self.SONNET_OUTPUT_COST
        return input_cost + output_cost
    
    def get_total_cost(self) -> float:
        """Get total API cost for this session."""
        return self.total_cost

