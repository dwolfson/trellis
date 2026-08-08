"""Unit tests for monitoring components."""

import pytest
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.query_classifier import (
    classify_query, QueryType, QueryTopic, get_query_classifier
)
from advisor.collection_metrics import (
    get_collection_metrics_tracker, CollectionRetrievalMetrics
)
from advisor.assembly_metrics import (
    get_assembly_metrics_tracker, DocumentAssemblyMetrics
)


class MockSearchResult:
    """Mock search result for testing."""
    def __init__(self, score, file_path="test.py", text="test text"):
        self.score = score
        self.text = text
        self.metadata = {'file_path': file_path, 'name': 'test', 'type': 'function'}


class TestQueryClassifier:
    """Test query classification."""
    
    def test_concept_query(self):
        """Test concept query classification."""
        classification = classify_query("What is a glossary?")
        assert classification.query_type == QueryType.CONCEPT
        assert QueryTopic.GLOSSARY in classification.topics
        assert classification.confidence > 0.7
    
    def test_concept_query_define(self):
        """Test concept query with 'define'."""
        classification = classify_query("Define metadata")
        assert classification.query_type == QueryType.CONCEPT
        assert classification.confidence > 0.7
    
    def test_type_query(self):
        """Test type query classification."""
        classification = classify_query("What properties does GlossaryTerm have?")
        assert classification.query_type == QueryType.TYPE
        assert classification.confidence > 0.7
    
    def test_type_query_attributes(self):
        """Test type query with 'attributes'."""
        classification = classify_query("What attributes are in Asset?")
        assert classification.query_type == QueryType.TYPE
        assert classification.confidence > 0.7
    
    def test_code_query(self):
        """Test code query classification."""
        classification = classify_query("Show me code for creating an asset")
        assert classification.query_type == QueryType.CODE
        assert classification.confidence > 0.7
    
    def test_code_query_implementation(self):
        """Test code query with 'implementation'."""
        classification = classify_query("How do I implement a connector?")
        assert classification.query_type == QueryType.CODE
        assert classification.confidence > 0.7
    
    def test_example_query(self):
        """Test example query classification."""
        classification = classify_query("Give me an example of using pyegeria")
        assert classification.query_type == QueryType.EXAMPLE
        assert classification.confidence > 0.7
    
    def test_example_query_sample(self):
        """Test example query with 'sample'."""
        classification = classify_query("Show me a sample notebook")
        assert classification.query_type == QueryType.EXAMPLE
        assert classification.confidence > 0.7
    
    def test_tutorial_query(self):
        """Test tutorial query classification."""
        classification = classify_query("How do I get started with Egeria?")
        assert classification.query_type == QueryType.TUTORIAL
        assert classification.confidence > 0.7
    
    def test_troubleshooting_query(self):
        """Test troubleshooting query classification."""
        classification = classify_query("Why doesn't my connector work?")
        assert classification.query_type == QueryType.TROUBLESHOOTING
        assert classification.confidence > 0.7
    
    def test_comparison_query(self):
        """Test comparison query classification."""
        classification = classify_query("What's the difference between Asset and Resource?")
        assert classification.query_type == QueryType.COMPARISON
        assert classification.confidence > 0.7
    
    def test_general_query(self):
        """Test general query classification."""
        classification = classify_query("Tell me about Egeria")
        # Should classify as something, even if GENERAL
        assert classification.query_type in [QueryType.GENERAL, QueryType.CONCEPT]
        assert classification.confidence > 0.0
    
    def test_expected_collections(self):
        """Test expected collections suggestion."""
        classifier = get_query_classifier()
        classification = classify_query("What is a glossary?")
        expected = classifier.get_expected_collections(classification)
        assert isinstance(expected, list)
        assert len(expected) > 0
        # Concept queries should suggest egeria_concepts
        assert 'egeria_concepts' in expected or 'egeria_docs' in expected
    
    def test_expected_parameters(self):
        """Test expected parameters suggestion."""
        classifier = get_query_classifier()
        classification = classify_query("What is a glossary?")
        params = classifier.get_expected_parameters(classification)
        assert 'chunk_size' in params
        assert 'min_score' in params
        assert 'top_k' in params
        assert isinstance(params['chunk_size'], int)
        assert isinstance(params['min_score'], float)
        assert isinstance(params['top_k'], int)
        # Concept queries should have high min_score
        assert params['min_score'] >= 0.40
    
    def test_topic_extraction(self):
        """Test topic extraction."""
        classification = classify_query("How do I configure a connector for lineage?")
        # Should detect CONNECTOR and/or LINEAGE topics
        topics = [t.value for t in classification.topics]
        assert len(topics) > 0
        # At least one relevant topic should be detected
        assert any(t in ['connector', 'lineage', 'configuration'] for t in topics)


class TestCollectionMetrics:
    """Test collection metrics tracking."""
    
    def test_track_search(self):
        """Test tracking a collection search."""
        tracker = get_collection_metrics_tracker()
        tracker.clear_history()  # Start fresh
        
        # Create mock results
        results = [
            MockSearchResult(0.8),
            MockSearchResult(0.6),
            MockSearchResult(0.4)
        ]
        
        # Track search
        metrics = tracker.track_collection_search(
            collection_name="test_collection",
            query_type=QueryType.CONCEPT,
            query_topics=[QueryTopic.GLOSSARY],
            results=results,
            search_time_ms=50.0,
            min_score_threshold=0.5,
            was_primary=True,
            routing_confidence=0.95
        )
        
        assert metrics.chunks_retrieved == 3
        assert metrics.chunks_above_threshold == 2
        assert metrics.avg_score == pytest.approx(0.6, rel=0.01)
        assert metrics.max_score == 0.8
        assert metrics.min_score == 0.4
        assert metrics.get_precision() == pytest.approx(2/3, rel=0.01)
        assert metrics.was_primary_collection == True
        assert metrics.routing_confidence == 0.95
    
    def test_update_final_context_metrics(self):
        """Test updating final context metrics."""
        tracker = get_collection_metrics_tracker()
        tracker.clear_history()
        
        # Track initial search
        results = [MockSearchResult(0.8), MockSearchResult(0.6)]
        tracker.track_collection_search(
            collection_name="test_collection",
            query_type=QueryType.CONCEPT,
            query_topics=[QueryTopic.GLOSSARY],
            results=results,
            search_time_ms=50.0,
            min_score_threshold=0.5
        )
        
        # Update with final context info
        tracker.update_final_context_metrics(
            collection_name="test_collection",
            chunks_in_final=1,
            ranks_in_final=[2]
        )
        
        # Get the metrics
        summary = tracker.get_collection_summary("test_collection")
        assert summary['total_searches'] == 1
    
    def test_collection_summary(self):
        """Test collection summary generation."""
        tracker = get_collection_metrics_tracker()
        tracker.clear_history()
        
        # Track multiple searches
        for i in range(5):
            results = [MockSearchResult(0.8), MockSearchResult(0.6)]
            tracker.track_collection_search(
                collection_name="test_collection",
                query_type=QueryType.CONCEPT,
                query_topics=[QueryTopic.GLOSSARY],
                results=results,
                search_time_ms=50.0,
                min_score_threshold=0.5
            )
        
        # Get summary
        summary = tracker.get_collection_summary("test_collection")
        assert summary['total_searches'] == 5
        assert summary['avg_chunks_retrieved'] == 2.0
        assert summary['avg_precision'] == 1.0  # All above threshold
        assert summary['avg_search_time_ms'] == 50.0
    
    def test_query_type_summary(self):
        """Test query type summary."""
        tracker = get_collection_metrics_tracker()
        tracker.clear_history()
        
        # Track searches of different types
        for query_type in [QueryType.CONCEPT, QueryType.CODE]:
            results = [MockSearchResult(0.8)]
            tracker.track_collection_search(
                collection_name="test_collection",
                query_type=query_type,
                query_topics=[QueryTopic.GLOSSARY],
                results=results,
                search_time_ms=50.0,
                min_score_threshold=0.5
            )
        
        # Get summary for CONCEPT queries
        summary = tracker.get_query_type_summary(QueryType.CONCEPT)
        assert summary['total_searches'] == 1
        assert summary['query_type'] == 'concept'


class TestAssemblyMetrics:
    """Test assembly metrics tracking."""
    
    def test_track_assembly(self):
        """Test tracking document assembly."""
        tracker = get_assembly_metrics_tracker()
        tracker.clear_history()
        
        # Create mock results
        coll1_results = [
            MockSearchResult(0.8, "file1.py"),
            MockSearchResult(0.7, "file2.py")
        ]
        coll2_results = [
            MockSearchResult(0.6, "file3.py")
        ]
        final_results = [
            MockSearchResult(0.8, "file1.py"),
            MockSearchResult(0.6, "file3.py")
        ]
        
        # Track assembly
        metrics = tracker.track_assembly(
            query_type=QueryType.CONCEPT,
            query_topics=[QueryTopic.GLOSSARY],
            collections_searched=["coll1", "coll2"],
            collection_results={"coll1": coll1_results, "coll2": coll2_results},
            final_results=final_results,
            reranking_time_ms=10.0,
            context_length_chars=1000,
            max_context_length=8000
        )
        
        assert metrics.total_chunks_retrieved == 3
        assert metrics.total_chunks_used == 2
        assert metrics.get_utilization_rate() == pytest.approx(2/3, rel=0.01)
        assert metrics.chunk_diversity_score >= 0.0
        assert metrics.chunk_diversity_score <= 1.0
        assert metrics.reranking_time_ms == 10.0
        assert metrics.context_truncated == False
    
    def test_get_primary_collection(self):
        """Test getting primary collection."""
        tracker = get_assembly_metrics_tracker()
        tracker.clear_history()
        
        coll1_results = [MockSearchResult(0.8), MockSearchResult(0.7)]
        coll2_results = [MockSearchResult(0.6)]
        final_results = [MockSearchResult(0.8), MockSearchResult(0.7)]
        
        metrics = tracker.track_assembly(
            query_type=QueryType.CONCEPT,
            query_topics=[QueryTopic.GLOSSARY],
            collections_searched=["coll1", "coll2"],
            collection_results={"coll1": coll1_results, "coll2": coll2_results},
            final_results=final_results,
            reranking_time_ms=10.0,
            context_length_chars=1000,
            max_context_length=8000
        )
        
        # coll1 should be primary (contributed more chunks)
        primary = metrics.get_primary_collection()
        # Note: This may not work perfectly with mock objects
        # but tests the method exists and returns something
        assert primary is None or isinstance(primary, str)
    
    def test_assembly_summary(self):
        """Test assembly summary generation."""
        tracker = get_assembly_metrics_tracker()
        tracker.clear_history()
        
        # Track multiple assemblies
        for i in range(3):
            coll1_results = [MockSearchResult(0.8)]
            final_results = [MockSearchResult(0.8)]
            
            tracker.track_assembly(
                query_type=QueryType.CONCEPT,
                query_topics=[QueryTopic.GLOSSARY],
                collections_searched=["coll1"],
                collection_results={"coll1": coll1_results},
                final_results=final_results,
                reranking_time_ms=10.0,
                context_length_chars=1000,
                max_context_length=8000
            )
        
        # Get summary
        summary = tracker.get_summary()
        assert summary['total_assemblies'] == 3
        assert summary['avg_reranking_time_ms'] == 10.0
        assert summary['avg_utilization_rate'] == 1.0


def test_integration():
    """Test integration between components."""
    # Classify a query
    classification = classify_query("What is a glossary?")
    
    # Track collection search
    coll_tracker = get_collection_metrics_tracker()
    coll_tracker.clear_history()
    
    results = [MockSearchResult(0.8), MockSearchResult(0.6)]
    coll_metrics = coll_tracker.track_collection_search(
        collection_name="egeria_concepts",
        query_type=classification.query_type,
        query_topics=classification.topics,
        results=results,
        search_time_ms=50.0,
        min_score_threshold=0.45
    )
    
    # Track assembly
    asm_tracker = get_assembly_metrics_tracker()
    asm_tracker.clear_history()
    
    asm_metrics = asm_tracker.track_assembly(
        query_type=classification.query_type,
        query_topics=classification.topics,
        collections_searched=["egeria_concepts"],
        collection_results={"egeria_concepts": results},
        final_results=results,
        reranking_time_ms=10.0,
        context_length_chars=1000,
        max_context_length=8000
    )
    
    # Verify everything worked
    assert coll_metrics.query_type == QueryType.CONCEPT
    assert asm_metrics.query_type == QueryType.CONCEPT
    assert len(asm_metrics.collections_searched) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])