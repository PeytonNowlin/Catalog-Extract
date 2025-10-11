"""
Image preprocessing module for OCR optimization.
Handles deskewing, thresholding, and noise reduction.
"""
import cv2
import numpy as np
from typing import Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class ImagePreprocessor:
    """Preprocesses images for optimal OCR performance."""
    
    def __init__(self, debug_mode: bool = False):
        """
        Initialize the preprocessor.
        
        Args:
            debug_mode: If True, saves intermediate debug images
        """
        self.debug_mode = debug_mode
        self.debug_images = {}
    
    def preprocess(self, image: np.ndarray, page_num: int = 0) -> np.ndarray:
        """
        Apply full preprocessing pipeline to an image.
        
        Args:
            image: Input image as numpy array
            page_num: Page number for debug naming
            
        Returns:
            Preprocessed image ready for OCR
        """
        logger.info(f"Preprocessing image for page {page_num}")
        
        # Convert to grayscale if needed
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()
        
        self._save_debug(f"page_{page_num}_01_grayscale", gray)
        
        # Deskew the image
        deskewed = self._deskew(gray)
        self._save_debug(f"page_{page_num}_02_deskewed", deskewed)
        
        # Denoise
        denoised = cv2.fastNlMeansDenoising(deskewed, h=10)
        self._save_debug(f"page_{page_num}_03_denoised", denoised)
        
        # Apply adaptive thresholding
        thresholded = self._threshold(denoised)
        self._save_debug(f"page_{page_num}_04_thresholded", thresholded)
        
        # Morphological operations to clean up
        cleaned = self._morphological_cleanup(thresholded)
        self._save_debug(f"page_{page_num}_05_cleaned", cleaned)
        
        return cleaned
    
    def _deskew(self, image: np.ndarray) -> np.ndarray:
        """
        Detect and correct skew in the image.
        
        Args:
            image: Grayscale image
            
        Returns:
            Deskewed image
        """
        # Detect edges
        edges = cv2.Canny(image, 50, 150, apertureSize=3)
        
        # Detect lines using Hough transform
        lines = cv2.HoughLines(edges, 1, np.pi / 180, 200)
        
        if lines is None:
            logger.warning("No lines detected for deskewing")
            return image
        
        # Calculate angles
        angles = []
        for rho, theta in lines[:, 0]:
            angle = np.rad2deg(theta) - 90
            if -45 < angle < 45:
                angles.append(angle)
        
        if not angles:
            return image
        
        # Use median angle for deskewing
        median_angle = np.median(angles)
        
        # Only deskew if angle is significant
        if abs(median_angle) < 0.5:
            return image
        
        logger.info(f"Deskewing by {median_angle:.2f} degrees")
        
        # Rotate image
        h, w = image.shape
        center = (w // 2, h // 2)
        matrix = cv2.getRotationMatrix2D(center, median_angle, 1.0)
        deskewed = cv2.warpAffine(
            image, matrix, (w, h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE
        )
        
        return deskewed
    
    def _threshold(self, image: np.ndarray) -> np.ndarray:
        """
        Apply adaptive thresholding to binarize the image.
        
        Args:
            image: Grayscale image
            
        Returns:
            Binary image
        """
        # Apply adaptive Gaussian thresholding
        binary = cv2.adaptiveThreshold(
            image, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            blockSize=11,
            C=2
        )
        
        return binary
    
    def _morphological_cleanup(self, image: np.ndarray) -> np.ndarray:
        """
        Apply morphological operations to clean up noise.
        
        Args:
            image: Binary image
            
        Returns:
            Cleaned binary image
        """
        # Remove small noise with opening
        kernel = np.ones((2, 2), np.uint8)
        opened = cv2.morphologyEx(image, cv2.MORPH_OPEN, kernel, iterations=1)
        
        # Close small gaps
        kernel = np.ones((1, 1), np.uint8)
        closed = cv2.morphologyEx(opened, cv2.MORPH_CLOSE, kernel, iterations=1)
        
        return closed
    
    def _save_debug(self, name: str, image: np.ndarray):
        """Save debug image if debug mode is enabled."""
        if self.debug_mode:
            self.debug_images[name] = image.copy()
    
    def get_debug_images(self) -> dict:
        """Get all saved debug images."""
        return self.debug_images
    
    def save_debug_images(self, output_dir: str):
        """
        Save all debug images to disk.
        
        Args:
            output_dir: Directory to save debug images
        """
        import os
        os.makedirs(output_dir, exist_ok=True)
        
        for name, image in self.debug_images.items():
            output_path = os.path.join(output_dir, f"{name}.png")
            cv2.imwrite(output_path, image)
            logger.info(f"Saved debug image: {output_path}")

