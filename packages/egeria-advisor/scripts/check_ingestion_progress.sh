#!/bin/bash
# Check ingestion progress for all three collections

echo "=== Collection Ingestion Status ==="
echo ""

# Check egeria_concepts
echo "egeria_concepts:"
python -c "from advisor.vector_store import get_vector_store; vs = get_vector_store(); stats = vs.get_collection_stats('egeria_concepts') if 'egeria_concepts' in vs.list_collections() else {'entity_count': 0}; print(f\"  Entities: {stats.get('entity_count', 0)}\")" 2>/dev/null || echo "  Not yet created"

# Check egeria_types  
echo "egeria_types:"
python -c "from advisor.vector_store import get_vector_store; vs = get_vector_store(); stats = vs.get_collection_stats('egeria_types') if 'egeria_types' in vs.list_collections() else {'entity_count': 0}; print(f\"  Entities: {stats.get('entity_count', 0)}\")" 2>/dev/null || echo "  Not yet created"

# Check egeria_general
echo "egeria_general:"
python -c "from advisor.vector_store import get_vector_store; vs = get_vector_store(); stats = vs.get_collection_stats('egeria_general') if 'egeria_general' in vs.list_collections() else {'entity_count': 0}; print(f\"  Entities: {stats.get('entity_count', 0)}\")" 2>/dev/null || echo "  Not yet created"

echo ""
echo "=== Log Files ==="
echo "egeria_types: tail -f /tmp/egeria_types_ingest.log"
echo "egeria_general: tail -f /tmp/egeria_general_ingest.log"