#!/usr/bin/env bash
set -euo pipefail

MODEL_DIR="./model"
ARCHIVE="model.tar.gz"
S3_URI="s3://asl-hackathon/models/v1/model.tar.gz"

if [[ ! -d "$MODEL_DIR" ]]; then
  echo "ERROR: model directory '$MODEL_DIR' not found. Aborting." >&2
  exit 1
fi

echo "Packaging $MODEL_DIR → $ARCHIVE ..."
tar -czf "$ARCHIVE" -C "$MODEL_DIR" .

echo "Uploading $ARCHIVE → $S3_URI ..."
if ! aws s3 cp "$ARCHIVE" "$S3_URI"; then
  echo "ERROR: aws s3 cp failed." >&2
  rm -f "$ARCHIVE"
  exit 1
fi

rm -f "$ARCHIVE"
echo "SUCCESS: $S3_URI"
