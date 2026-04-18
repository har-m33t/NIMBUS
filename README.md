# ASL Live Video Caption Interpretation (NIMBUS)

Real-time ASL recognition with facial emotion detection, natural language interpretation, and expressive text-to-speech — integrated with Zoom.

## Overview
This system captures a signer's webcam feed in real-time, recognizes American Sign Language (ASL) signs and facial expressions, translates raw ASL gloss into natural English sentences using an LLM, generates emotionally expressive speech, and delivers both native captions and TTS audio directly into a Zoom meeting.

## Project Structure
We have split the functionality across the `frontend` (local application logic) and `backend` (cloud orchestration):

* **`frontend/`**: Contains the local desktop Python application. Captures the webcam via OpenCV, tracks pose keypoints via MediaPipe Holistic, establishes a WebSocket connection, and loops interpretations into Zoom via its API and local audio tunneling.
* **`backend/`**: Contains the AWS Serverless template bridging Bedrock (Translation), Rekognition (Emotions), and Polly (TTS). Inside `backend/ml_pipeline`, you will find SageMaker specific scripts for training the core Transformer ASL model.
* **`docs/`**: Key architecture diagrams and API definitions.

## Getting Started
1. **Frontend Setup**:
   - `cd frontend/`
   - `pip install -r requirements.txt`
   - Entry point: `src/main.py`
   
2. **Backend Setup**:
   - `cd backend/`
   - `pip install -r requirements.txt` (for individual lambdas)
   - Follow SAM deployment rules in `template.yaml`.

3. **Machine Learning Pipeline**:
   - `cd backend/ml_pipeline/`
   - Use SageMaker Notebook `notebooks/data_preparation.ipynb` to process training vectors.
