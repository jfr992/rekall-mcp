#!/bin/bash
# Verify that tests use isolated Qdrant instance
set -e

echo "=== Test Isolation Verification ==="
echo

# Check production Qdrant count before tests
echo "1. Checking production Qdrant (should have real memories)..."
PROD_COUNT=$(curl -s http://localhost:6333/collections/agent_memory 2>/dev/null | jq -r '.result.points_count // 0')
echo "   Production memories: $PROD_COUNT"
echo

# Start test infrastructure
echo "2. Starting test Qdrant instance..."
docker compose --profile test up -d qdrant-test
sleep 3

# Verify test Qdrant is isolated
echo "3. Checking test Qdrant (should be empty)..."
TEST_COUNT=$(curl -s http://localhost:6334/collections 2>/dev/null | jq -r '.result.collections | length')
echo "   Test collections: $TEST_COUNT (should be 0)"
echo

# Run a quick test
echo "4. Running sample test..."
docker compose --profile test run --rm test pytest tests/test_core.py::TestTelemetry::test_track_context_manager -v
echo

# Check counts after test
echo "5. Verifying isolation after test..."
PROD_COUNT_AFTER=$(curl -s http://localhost:6333/collections/agent_memory 2>/dev/null | jq -r '.result.points_count // 0')
TEST_COUNT_AFTER=$(curl -s http://localhost:6334/collections 2>/dev/null | jq -r '.result.collections | length')

echo "   Production memories: $PROD_COUNT_AFTER (should be $PROD_COUNT)"
echo "   Test collections: $TEST_COUNT_AFTER"
echo

# Cleanup
echo "6. Cleaning up test infrastructure..."
docker compose --profile test down

echo
if [ "$PROD_COUNT" -eq "$PROD_COUNT_AFTER" ]; then
    echo "✓ SUCCESS: Production data unchanged by tests"
    exit 0
else
    echo "✗ FAILURE: Production data was modified ($PROD_COUNT -> $PROD_COUNT_AFTER)"
    exit 1
fi
