#!/usr/bin/env bash
# Downloads the LongMemEval dataset from HuggingFace.
set -euo pipefail

DATA_DIR="$(dirname "$0")/data"
mkdir -p "$DATA_DIR"

URL="https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json"
DEST="$DATA_DIR/longmemeval_s_cleaned.json"

if [ -f "$DEST" ]; then
    echo "Dataset already exists: $DEST"
    python3 -c "import json; d=json.load(open('$DEST')); print(f'{len(d)} questions')"
    exit 0
fi

echo "Downloading LongMemEval dataset..."
echo "Source: $URL"
echo "Destination: $DEST"

curl -L --progress-bar "$URL" -o "$DEST"

echo "Done."
python3 -c "import json; d=json.load(open('$DEST')); print(f'{len(d)} questions')"
