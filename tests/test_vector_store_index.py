"""Tests for VectorStore index creation."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def reset_telemetry():
    from core.telemetry import Telemetry
    Telemetry.reset()
    yield
    Telemetry.reset()


def test_create_index_supports_integer_type():
    """create_index should pass 'integer' field_type to Qdrant."""
    with patch("core.vector_store.QdrantClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.get_collections.return_value = MagicMock(
            collections=[MagicMock(name="memories")]
        )

        from core.vector_store import VectorStore

        store = VectorStore(collection="memories")
        store.create_index("date_epoch", field_type="integer")

        mock_client.create_payload_index.assert_called_once_with(
            collection_name="memories",
            field_name="date_epoch",
            field_schema="integer",
        )
