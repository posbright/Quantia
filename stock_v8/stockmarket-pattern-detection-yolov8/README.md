---
tags:
- ultralyticsplus
- yolov8
- ultralytics
- yolo
- vision
- object-detection
- pytorch
- finance
- stock market
- candlesticks
- pattern recognition
- option trading
- chart reader
library_name: ultralytics
library_version: 8.3.94
inference: false
model-index:
- name: foduucom/stockmarket-pattern-detection-yolov8
  results:
  - task:
      type: object-detection
    metrics:
    - type: precision
      value: 0.61355
      name: mAP@0.5(box)
language:
- en
pipeline_tag: object-detection
---

<div align="center">
  <img width="500" alt="foduucom/stockmarket-pattern-detection-yolov8" src="https://huggingface.co/foduucom/stockmarket-pattern-detection-yolov8/resolve/main/thumbnail.jpg">
</div>

# Model Card for YOLOv8s Stock Market Real Time Pattern Detection from Live Screen Capture

## Model Summary

The YOLOv8s Stock Market Pattern Detection model is an object detection model based on the YOLO (You Only Look Once) framework. It is designed to detect various chart patterns in real-time from screen-captured stock market trading data. The model aids traders and investors by automating the analysis of chart patterns, providing timely insights for informed decision-making. The model has been fine-tuned on a diverse dataset and achieves high accuracy in detecting and classifying stock market patterns in live trading scenarios.

## Model Details

### Model Description
The YOLOv8s Stock Market Pattern Detection model enables real-time detection of crucial chart patterns within stock market screen captures. As stock markets evolve rapidly, this model's capabilities empower users with timely insights, allowing them to make informed decisions with speed and accuracy.

The model is designed to work with screen capture of stock market trading charts. It can detect patterns such as 'Head and shoulders bottom,' 'Head and shoulders top,' 'M_Head,' 'StockLine,' 'Triangle,' and 'W_Bottom.' Traders can optimize their strategies, automate trading decisions, and respond to market trends in real-time.

To integrate this model into live trading systems or for customization inquiries, please contact us at info@foduu.com.

- **Developed by:** FODUU AI
- **Model type:** Object Detection
- **Task:** Stock Market Pattern Detection from Screen Capture

### Supported Labels

```
['Head and shoulders bottom', 'Head and shoulders top', 'M_Head', 'StockLine', 'Triangle', 'W_Bottom']
```

## Uses

### Direct Use
The model can be used for real-time pattern detection on screen-captured stock market charts. It can log detected patterns, annotate detected images, save results in an Excel file, and generate a video of detected patterns over time.

### Downstream Use
The model's real-time capabilities can be leveraged to automate trading strategies, generate alerts for specific patterns, and enhance overall trading performance.

### Training Data
The Stock Market model was trained on a custom dataset consisting of 9000 training images and 800 validation images.

### Out-of-Scope Use
The model is not designed for unrelated object detection tasks or scenarios outside the scope of stock market pattern detection from screen-captured data.

## Bias, Risks, and Limitations

- Performance may be affected by variations in chart styles, screen resolution, and market conditions.
- Rapid market fluctuations and noise in trading data may impact accuracy.
- Market-specific patterns not well-represented in the training data may pose challenges for detection.

### Recommendations
Users should be aware of the model's limitations and potential biases. Testing and validation with historical data and live market conditions are advised before deploying the model for real trading decisions.

## How to Get Started with the Model

To begin using the YOLOv8s Stock Market Real Time Pattern Detection model, install the necessary libraries:
```bash
pip install mss==10.0.0 opencv-python==4.11.0.86 numpy ultralytics==8.3.94 openpyxl==3.1.5
```

### Screen Capture and Pattern Detection Implementation
```python


import os
import mss # type: ignore
import cv2
import numpy as np
import time
import glob
from ultralytics import YOLO
from openpyxl import Workbook

# Get the user's home directory
home_dir = os.path.expanduser("~")

# Define dynamic paths
save_path = os.path.join(home_dir, "yolo_detection")
screenshots_path = os.path.join(save_path, "screenshots")
detect_path = os.path.join(save_path, "runs", "detect")

# Ensure necessary directories exist
os.makedirs(screenshots_path, exist_ok=True)
os.makedirs(detect_path, exist_ok=True)

# Define pattern classes
classes = ['Head and shoulders bottom', 'Head and shoulders top', 'M_Head', 'StockLine', 'Triangle', 'W_Bottom']

# Load YOLOv8 model
model_path = "model.pt"
if not os.path.exists(model_path):
    raise FileNotFoundError(f"Model file not found: {model_path}")
model = YOLO(model_path)

# Define screen capture region
monitor = {"top": 0, "left": 683, "width": 683, "height": 768}

# Create an Excel file
excel_file = os.path.join(save_path, "classification_results.xlsx")
wb = Workbook()
ws = wb.active
ws.append(["Timestamp", "Predicted Image Path", "Label"])  # Headers

# Initialize video writer
video_path = os.path.join(save_path, "annotated_video.mp4")
fourcc = cv2.VideoWriter_fourcc(*"mp4v")
fps = 0.5  # Adjust frames per second as needed
video_writer = None

with mss.mss() as sct:
    start_time = time.time()
    last_capture_time = start_time  # Track the last capture time
    frame_count = 0
    
    while True:
        # Continuously capture the screen
        sct_img = sct.grab(monitor)
        img = np.array(sct_img)
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

        # Check if 60 seconds have passed since last YOLO prediction
        current_time = time.time()
        if current_time - last_capture_time >= 60:
            # Take screenshot for YOLO prediction
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            image_name = f"predicted_images_{timestamp}_{frame_count}.png"
            image_path = os.path.join(screenshots_path, image_name)
            cv2.imwrite(image_path, img)

            # Run YOLO model and get save directory
            results = model(image_path, save=True)
            predict_path = results[0].save_dir if results else None

            # Find the latest annotated image inside predict_path
            if predict_path and os.path.exists(predict_path):
                annotated_images = sorted(glob.glob(os.path.join(predict_path, "*.jpg")), key=os.path.getmtime, reverse=True)
                final_image_path = annotated_images[0] if annotated_images else image_path
            else:
                final_image_path = image_path  # Fallback to original image

            # Determine predicted label
            if results and results[0].boxes:
                class_indices = results[0].boxes.cls.tolist()
                predicted_label = classes[int(class_indices[0])]
            else:
                predicted_label = "No pattern detected"

            # Insert data into Excel (store path instead of image)
            ws.append([timestamp, final_image_path, predicted_label])

            # Read the image for video processing
            annotated_img = cv2.imread(final_image_path)
            if annotated_img is not None:
                # Add timestamp and label text to the image
                font = cv2.FONT_HERSHEY_SIMPLEX
                cv2.putText(annotated_img, f"{timestamp}", (10, 30), font, 0.7, (0, 255, 0), 2, cv2.LINE_AA)
                cv2.putText(annotated_img, f"{predicted_label}", (10, 60), font, 0.7, (0, 255, 255), 2, cv2.LINE_AA)
                
                # Initialize video writer if not already initialized
                if video_writer is None:
                    height, width, layers = annotated_img.shape
                    video_writer = cv2.VideoWriter(video_path, fourcc, fps, (width, height))
                
                video_writer.write(annotated_img)

            print(f"Frame {frame_count}: {final_image_path} -> {predicted_label}")
            frame_count += 1

            # Update the last capture time
            last_capture_time = current_time

        # Save the Excel file periodically
        wb.save(excel_file)

        # If you want to continuously display the screen, you can add this line
        cv2.imshow("Screen Capture", img)

        # Break if 'q' is pressed (you can exit the loop this way)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

# Release video writer
if video_writer is not None:
    video_writer.release()
    print(f"Video saved at {video_path}")

# Remove all files in screenshots directory
for file in os.scandir(screenshots_path):
    os.remove(file.path)
os.rmdir(screenshots_path)

print(f"Results saved to {excel_file}")

# Close OpenCV window
cv2.destroyAllWindows()

```

## Model Contact
For inquiries and contributions, please contact us at info@foduu.com.

```bibtex
@ModelCard{
  author    = {Nehul Agrawal,
               Pranjal Singh Thakur, Priyal Mehta and Arjun Singh},
  title     = {YOLOv8s Stock Market Pattern Detection from Live Screen Capture},
  year      = {2023}
}
```

