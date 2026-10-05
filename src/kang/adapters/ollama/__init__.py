"""Ollama ModelProvider implementation.

Layer: adapters.
Constitutional home: 04_ARCHITECTURE D010 (built at Phase 5 local-model migration).

Dated correction (2026-10-05, ADR-054 D7; built by ADR-055 D2): the line
above is true of `private`/`routine` text generation only — that is what
03_ROADMAP's Phase 5 objective (:117) and RESERVED row "Local-model migration
per task class" (:162) gate, and neither trigger has fired. It was never true
of `embedding`: D010 routes that class to a local-preferred provider from
inception, and 03 §3 puts embeddings in Phase 2. `provider.py` implements
`embed` for the `embedding` task class only; its `call` (text generation)
refuses, exactly as RESERVED as before.
"""

__all__: list[str] = []
