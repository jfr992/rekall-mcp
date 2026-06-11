"""Tests that dead code has been removed (Phase 5).

These assert that specific deprecated artifacts no longer exist.
"""


class TestDeadCodeRemoved:
    """Verify all 6 dead code artifacts have been deleted."""

    def test_no_sanitize_method_on_manager(self):
        from memory.manager import MemoryManager

        assert not hasattr(MemoryManager, "sanitize"), (
            "MemoryManager.sanitize() should be removed (use Sanitizer.sanitize directly)"
        )

    def test_no_qdrant_property_on_manager(self):
        from memory.manager import MemoryManager

        # Check that 'qdrant' is not a defined property on the class
        assert "qdrant" not in dir(MemoryManager) or not isinstance(
            getattr(MemoryManager, "qdrant", None), property
        ), "MemoryManager.qdrant property should be removed"

    def test_no_save_memory_alias_on_manager(self):
        from memory.manager import MemoryManager

        assert not hasattr(MemoryManager, "save_memory"), (
            "MemoryManager.save_memory() alias should be removed"
        )

    def test_no_parameters_field_on_tool_definition(self):
        import dataclasses

        from tools.base import ToolDefinition

        field_names = [f.name for f in dataclasses.fields(ToolDefinition)]
        assert "parameters" not in field_names, "ToolDefinition.parameters field should be removed"

    def test_no_provider_comparison_constant(self):
        import core.embeddings as emb

        assert not hasattr(emb, "PROVIDER_COMPARISON"), (
            "PROVIDER_COMPARISON constant should be removed"
        )

    def test_no_model_compat_property_on_embedder(self):
        from core.embeddings import Embedder

        assert not isinstance(getattr(Embedder, "model", None), property), (
            "Embedder.model compat property should be removed"
        )
