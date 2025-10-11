"""
Export module.
Exports extracted data to CSV and other formats.
"""
import csv
import os
from typing import List
import logging
from .extractor import ExtractedItem

logger = logging.getLogger(__name__)


class DataExporter:
    """Exports extracted data to various formats."""
    
    def export_to_csv(
        self, 
        items: List[ExtractedItem], 
        output_path: str,
        include_raw_text: bool = True
    ):
        """
        Export items to CSV file.
        
        Args:
            items: List of extracted items
            output_path: Path to output CSV file
            include_raw_text: Whether to include raw text column
        """
        logger.info(f"Exporting {len(items)} items to CSV: {output_path}")
        
        # Define CSV columns
        fieldnames = [
            'brand_code',
            'part_number',
            'price_type',
            'price_value',
            'currency',
            'page',
            'confidence',
        ]
        
        if include_raw_text:
            fieldnames.append('raw_text')
        
        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        
        # Write CSV
        with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for item in items:
                row = {
                    'brand_code': item.brand_code or '',
                    'part_number': item.part_number or '',
                    'price_type': item.price_type or '',
                    'price_value': f"{item.price_value:.2f}" if item.price_value is not None else '',
                    'currency': item.currency,
                    'page': item.page,
                    'confidence': f"{item.confidence:.2f}",
                }
                
                if include_raw_text:
                    row['raw_text'] = item.raw_text.replace('\n', ' ').strip()
                
                writer.writerow(row)
        
        logger.info(f"Successfully exported to {output_path}")
    
    def export_summary(self, items: List[ExtractedItem], output_path: str):
        """
        Export summary statistics to text file.
        
        Args:
            items: List of extracted items
            output_path: Path to output text file
        """
        logger.info(f"Exporting summary to: {output_path}")
        
        # Calculate statistics
        total_items = len(items)
        items_with_prices = sum(1 for item in items if item.price_value is not None)
        items_with_part_numbers = sum(1 for item in items if item.part_number)
        items_with_brand = sum(1 for item in items if item.brand_code)
        
        avg_confidence = sum(item.confidence for item in items) / total_items if total_items > 0 else 0
        
        pages = set(item.page for item in items)
        
        # Get price statistics
        prices = [item.price_value for item in items if item.price_value is not None]
        if prices:
            min_price = min(prices)
            max_price = max(prices)
            avg_price = sum(prices) / len(prices)
        else:
            min_price = max_price = avg_price = 0
        
        # Get unique brand codes
        brands = set(item.brand_code for item in items if item.brand_code)
        
        # Write summary
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("=" * 60 + "\n")
            f.write("CATALOG EXTRACTION SUMMARY\n")
            f.write("=" * 60 + "\n\n")
            
            f.write(f"Total Items Extracted: {total_items}\n")
            f.write(f"Items with Part Numbers: {items_with_part_numbers}\n")
            f.write(f"Items with Prices: {items_with_prices}\n")
            f.write(f"Items with Brand Codes: {items_with_brand}\n\n")
            
            f.write(f"Average Confidence: {avg_confidence:.2f}%\n")
            f.write(f"Pages Processed: {len(pages)}\n\n")
            
            if prices:
                f.write("Price Statistics:\n")
                f.write(f"  Min Price: ${min_price:.2f}\n")
                f.write(f"  Max Price: ${max_price:.2f}\n")
                f.write(f"  Avg Price: ${avg_price:.2f}\n\n")
            
            if brands:
                f.write(f"Brand Codes Found ({len(brands)}):\n")
                for brand in sorted(brands):
                    count = sum(1 for item in items if item.brand_code == brand)
                    f.write(f"  {brand}: {count} items\n")
            
            f.write("\n" + "=" * 60 + "\n")
        
        logger.info(f"Summary exported to {output_path}")

