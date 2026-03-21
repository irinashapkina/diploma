from __future__ import annotations

import cv2
import numpy as np
from PIL import Image


def preprocess_for_ocr(image: Image.Image) -> Image.Image:
    arr = np.array(image.convert("RGB"))
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)

    denoised = cv2.fastNlMeansDenoising(gray, h=10)

    h, w = denoised.shape[:2]
    if max(h, w) < 1400:
        scale = 1400.0 / float(max(h, w))
        denoised = cv2.resize(denoised, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    thresholded = cv2.adaptiveThreshold(
        denoised,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        8,
    )
    return Image.fromarray(thresholded)

