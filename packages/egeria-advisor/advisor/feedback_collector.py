"""
User feedback collection system for continuous improvement.

This module captures user feedback on query responses to improve
routing accuracy and response quality over time.
"""

from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
import json
from loguru import logger

# Import sentiment analyzer
try:
    from advisor.sentiment_analysis import get_sentiment_analyzer
    SENTIMENT_AVAILABLE = True
except ImportError:
    SENTIMENT_AVAILABLE = False
    logger.warning("Sentiment analysis not available")


@dataclass
class FeedbackEntry:
    """Single feedback entry."""
    timestamp: str
    query: str
    query_type: str
    collections_searched: List[str]
    response_length: int
    rating: str  # "positive", "negative", "neutral"
    feedback_text: Optional[str] = None  # User's free-text comment
    suggested_collection: Optional[str] = None  # Better collection suggestion
    session_id: Optional[str] = None
    user_comment: Optional[str] = None  # Additional user comment/explanation
    # Phase 1 enhancements
    star_rating: Optional[int] = None  # 1-5 star rating
    category: Optional[str] = None  # accuracy, completeness, clarity, relevance
    # Phase 2 enhancements
    perspective: Optional[str] = None   # active role: developer, data_steward, etc.
    routing_agent: Optional[str] = None # agent that handled: doc_agent, examples_agent, rag_fallback, etc.
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    def get_normalized_rating(self) -> float:
        """
        Get normalized rating score (0-1).
        
        Returns:
            Normalized rating between 0 and 1
        """
        if self.star_rating is not None:
            return self.star_rating / 5.0
        elif self.rating == "positive":
            return 1.0
        elif self.rating == "negative":
            return 0.0
        else:  # neutral
            return 0.5


class FeedbackCollector:
    """Collects and stores user feedback."""
    
    def __init__(self, feedback_file: Optional[Path] = None):
        """
        Initialize feedback collector.
        
        Args:
            feedback_file: Path to feedback JSON file
        """
        if feedback_file is None:
            feedback_file = Path("data/feedback/user_feedback.jsonl")
        
        self.feedback_file = feedback_file
        self.feedback_file.parent.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Initialized feedback collector: {self.feedback_file}")
    
    def record_feedback(
        self,
        query: str,
        query_type: str,
        collections_searched: List[str],
        response_length: int,
        rating: str,
        feedback_text: Optional[str] = None,
        suggested_collection: Optional[str] = None,
        session_id: Optional[str] = None,
        user_comment: Optional[str] = None,
        star_rating: Optional[int] = None,
        category: Optional[str] = None,
        perspective: Optional[str] = None,
        routing_agent: Optional[str] = None,
    ) -> bool:
        """
        Record user feedback.
        
        Args:
            query: User's query
            query_type: Detected query type
            collections_searched: Collections that were searched
            response_length: Length of response in characters
            rating: "positive", "negative", or "neutral"
            feedback_text: Optional free-text feedback
            suggested_collection: User's suggested collection (if routing was wrong)
            session_id: Optional session identifier
            user_comment: Optional user comment
            star_rating: Optional 1-5 star rating
            category: Optional category (accuracy, completeness, clarity, relevance)
            
        Returns:
            True if feedback was recorded successfully
        """
        try:
            # Validate star rating if provided
            if star_rating is not None and not (1 <= star_rating <= 5):
                logger.warning(f"Invalid star rating {star_rating}, must be 1-5")
                star_rating = None
            
            # Validate category if provided
            valid_categories = {"accuracy", "completeness", "clarity", "relevance"}
            if category is not None and category not in valid_categories:
                logger.warning(f"Invalid category {category}, must be one of {valid_categories}")
                category = None
            
            entry = FeedbackEntry(
                timestamp=datetime.utcnow().isoformat(),
                query=query,
                query_type=query_type,
                collections_searched=collections_searched,
                response_length=response_length,
                rating=rating,
                feedback_text=feedback_text,
                suggested_collection=suggested_collection,
                session_id=session_id,
                user_comment=user_comment,
                star_rating=star_rating,
                category=category,
                perspective=perspective,
                routing_agent=routing_agent,
            )
            
            # Perform sentiment analysis on comments if available
            sentiment_result = None
            if SENTIMENT_AVAILABLE and user_comment:
                try:
                    analyzer = get_sentiment_analyzer()
                    sentiment_result = analyzer.analyze(user_comment)
                    logger.debug(f"Sentiment analysis: {sentiment_result.sentiment} ({sentiment_result.confidence:.2f})")
                except Exception as e:
                    logger.warning(f"Sentiment analysis failed: {e}")
            
            # Append to JSONL file
            entry_dict = entry.to_dict()
            if sentiment_result:
                entry_dict['sentiment'] = sentiment_result.sentiment
                entry_dict['sentiment_confidence'] = sentiment_result.confidence
                entry_dict['sentiment_emotion'] = sentiment_result.emotion
                entry_dict['sentiment_keywords'] = sentiment_result.keywords_found
            
            with open(self.feedback_file, 'a') as f:
                f.write(json.dumps(entry_dict) + '\n')
            
            # Log to MLflow if available
            self.log_feedback_to_mlflow(entry, sentiment_result)
            
            # Update query_metrics in Postgres
            try:
                from advisor.db_consolidated import get_db_manager
                db_manager = get_db_manager()
                success_val = rating != "negative"
                update_sql = """
                    UPDATE query_metrics
                    SET success = %s,
                        rating = %s,
                        star_rating = %s,
                        suggested_collection = %s,
                        feedback_text = %s
                    WHERE id = (
                        SELECT id FROM query_metrics
                        WHERE query_text = %s
                        ORDER BY timestamp DESC
                        LIMIT 1
                    )
                """
                db_manager.execute_update(update_sql, (
                    success_val,
                    rating,
                    star_rating,
                    suggested_collection,
                    feedback_text or user_comment,
                    query
                ))
                logger.info(f"Updated query_metrics in Postgres with rating '{rating}' for query: {query[:50]}")
            except Exception as db_err:
                logger.warning(f"Failed to update query_metrics in Postgres with feedback: {db_err}")
            
            logger.info(f"Recorded {rating} feedback for query: {query[:50]}...")
            return True
            
        except Exception as e:
            logger.error(f"Failed to record feedback: {e}")
            return False
    
    def get_feedback_stats(self) -> Dict[str, Any]:
        """
        Get feedback statistics.
        
        Returns:
            Dictionary with feedback statistics
        """
        if not self.feedback_file.exists():
            return {
                "total": 0,
                "positive": 0,
                "negative": 0,
                "neutral": 0,
                "satisfaction_rate": 0.0
            }
        
        stats = {
            "total": 0,
            "positive": 0,
            "negative": 0,
            "neutral": 0,
            "by_query_type": {},
            "by_collection": {},
            "routing_corrections": [],
            # Phase 1 enhancements
            "star_ratings": [],
            "avg_star_rating": 0.0,
            "by_category": {},
            "category_star_ratings": {},
            # Phase 2 enhancements
            "by_perspective": {},
            "by_routing_agent": {},
        }
        
        try:
            with open(self.feedback_file, 'r') as f:
                for line in f:
                    entry = json.loads(line)
                    stats["total"] += 1
                    
                    # Count by rating
                    rating = entry.get("rating", "neutral")
                    stats[rating] = stats.get(rating, 0) + 1
                    
                    # Track star ratings
                    star_rating = entry.get("star_rating")
                    if star_rating is not None:
                        stats["star_ratings"].append(star_rating)
                    
                    # Track by category
                    category = entry.get("category")
                    if category:
                        if category not in stats["by_category"]:
                            stats["by_category"][category] = {
                                "total": 0, "positive": 0, "neutral": 0, "negative": 0, "star_ratings": []
                            }
                        stats["by_category"][category]["total"] += 1
                        stats["by_category"][category][rating] = \
                            stats["by_category"][category].get(rating, 0) + 1
                        if star_rating is not None:
                            stats["by_category"][category]["star_ratings"].append(star_rating)
                    
                    # Count by query type
                    query_type = entry.get("query_type", "unknown")
                    if query_type not in stats["by_query_type"]:
                        stats["by_query_type"][query_type] = {
                            "total": 0, "positive": 0, "neutral": 0, "negative": 0
                        }
                    stats["by_query_type"][query_type]["total"] += 1
                    stats["by_query_type"][query_type][rating] = \
                        stats["by_query_type"][query_type].get(rating, 0) + 1
                    
                    # Count by collection
                    for collection in entry.get("collections_searched", []):
                        if collection not in stats["by_collection"]:
                            stats["by_collection"][collection] = {
                                "total": 0, "positive": 0, "neutral": 0, "negative": 0
                            }
                        stats["by_collection"][collection]["total"] += 1
                        stats["by_collection"][collection][rating] = \
                            stats["by_collection"][collection].get(rating, 0) + 1
                    
                    # Track routing corrections
                    if entry.get("suggested_collection"):
                        stats["routing_corrections"].append({
                            "query": entry["query"],
                            "searched": entry["collections_searched"],
                            "suggested": entry["suggested_collection"]
                        })
 
                    # Phase 2: by_perspective
                    persp = entry.get("perspective") or "none"
                    if persp not in stats["by_perspective"]:
                        stats["by_perspective"][persp] = {"total": 0, "positive": 0, "neutral": 0, "negative": 0}
                    stats["by_perspective"][persp]["total"] += 1
                    stats["by_perspective"][persp][rating] = \
                        stats["by_perspective"][persp].get(rating, 0) + 1
 
                    # Phase 2: by_routing_agent
                    agent = entry.get("routing_agent") or "unknown"
                    if agent not in stats["by_routing_agent"]:
                        stats["by_routing_agent"][agent] = {"total": 0, "positive": 0, "neutral": 0, "negative": 0}
                    stats["by_routing_agent"][agent]["total"] += 1
                    stats["by_routing_agent"][agent][rating] = \
                        stats["by_routing_agent"][agent].get(rating, 0) + 1
            
            # Calculate satisfaction rate (weighted: positive = 1.0, neutral = 0.5)
            if stats["total"] > 0:
                stats["satisfaction_rate"] = (stats.get("positive", 0) + 0.5 * stats.get("neutral", 0)) / stats["total"]
            else:
                stats["satisfaction_rate"] = 0.0
            
            # Calculate average star rating
            if stats["star_ratings"]:
                stats["avg_star_rating"] = sum(stats["star_ratings"]) / len(stats["star_ratings"])
            
            # Calculate average star rating by category
            for category, data in stats["by_category"].items():
                if data["star_ratings"]:
                    stats["category_star_ratings"][category] = \
                        sum(data["star_ratings"]) / len(data["star_ratings"])
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get feedback stats: {e}")
            return stats
    
    def get_routing_improvements(self) -> List[Dict[str, Any]]:
        """
        Analyze feedback to suggest routing improvements.
        
        Returns:
            List of suggested routing improvements
        """
        improvements = []
        stats = self.get_feedback_stats()
        
        # Analyze routing corrections
        for correction in stats.get("routing_corrections", []):
            improvements.append({
                "type": "routing_correction",
                "query": correction["query"],
                "current_routing": correction["searched"],
                "suggested_routing": correction["suggested"],
                "action": f"Add domain term or boost {correction['suggested']} for similar queries"
            })
        
        # Analyze low-satisfaction collections
        for collection, data in stats.get("by_collection", {}).items():
            if data["total"] >= 5:  # Minimum sample size
                satisfaction = data.get("positive", 0) / data["total"]
                if satisfaction < 0.5:
                    improvements.append({
                        "type": "low_satisfaction",
                        "collection": collection,
                        "satisfaction_rate": satisfaction,
                        "total_queries": data["total"],
                        "action": f"Review prompt template for {collection} collection"
                    })
        
        # Analyze low-satisfaction query types
        for query_type, data in stats.get("by_query_type", {}).items():
            if data["total"] >= 5:
                satisfaction = data.get("positive", 0) / data["total"]
                if satisfaction < 0.5:
                    improvements.append({
                        "type": "low_satisfaction_query_type",
                        "query_type": query_type,
                        "satisfaction_rate": satisfaction,
                        "total_queries": data["total"],
                        "action": f"Review query-type instructions for {query_type}"
                    })
        
        return improvements

    def get_gap_analysis(self) -> Dict[str, Any]:
        """
        Identify queries that are underserved — negative feedback combined with
        RAG fallback routing, or perspectives with consistently low satisfaction.

        Returns a dict with:
          - rag_fallback_negatives: queries that fell to RAG and got thumbs-down
          - low_satisfaction_perspectives: perspectives below 50% satisfaction (≥5 samples)
          - low_satisfaction_agents: routing agents below 50% satisfaction (≥5 samples)
          - unhandled_intents: query types with high negative rate (≥5 samples)
        """
        gap: Dict[str, Any] = {
            "rag_fallback_negatives": [],
            "low_satisfaction_perspectives": [],
            "low_satisfaction_agents": [],
            "unhandled_intents": [],
        }
        if not self.feedback_file.exists():
            return gap

        rag_agents = {"rag_fallback", "general", "unknown"}
        try:
            with open(self.feedback_file, "r") as f:
                for line in f:
                    entry = json.loads(line)
                    if entry.get("rating") == "negative":
                        agent = entry.get("routing_agent") or "unknown"
                        if agent in rag_agents:
                            gap["rag_fallback_negatives"].append({
                                "query": entry["query"][:120],
                                "query_type": entry.get("query_type"),
                                "perspective": entry.get("perspective"),
                                "timestamp": entry.get("timestamp"),
                            })
        except Exception as exc:
            logger.error(f"get_gap_analysis: {exc}")
            return gap

        stats = self.get_feedback_stats()

        for persp, data in stats.get("by_perspective", {}).items():
            if data["total"] >= 5:
                sat = data.get("positive", 0) / data["total"]
                if sat < 0.5:
                    gap["low_satisfaction_perspectives"].append({
                        "perspective": persp,
                        "satisfaction_rate": round(sat, 2),
                        "total": data["total"],
                    })

        for agent, data in stats.get("by_routing_agent", {}).items():
            if data["total"] >= 5:
                sat = data.get("positive", 0) / data["total"]
                if sat < 0.5:
                    gap["low_satisfaction_agents"].append({
                        "routing_agent": agent,
                        "satisfaction_rate": round(sat, 2),
                        "total": data["total"],
                    })

        for qt, data in stats.get("by_query_type", {}).items():
            if data["total"] >= 5:
                neg_rate = data.get("negative", 0) / data["total"]
                if neg_rate > 0.5:
                    gap["unhandled_intents"].append({
                        "query_type": qt,
                        "negative_rate": round(neg_rate, 2),
                        "total": data["total"],
                    })

        return gap

    def log_feedback_to_mlflow(self, entry: FeedbackEntry, sentiment_result=None):
        """
        Log feedback entry to MLflow for tracking and analysis.
        
        Args:
            entry: Feedback entry to log
            sentiment_result: Optional sentiment analysis result
        """
        try:
            import mlflow
            from advisor.config import settings
            
            # Only log if MLflow tracking is enabled
            if not settings.mlflow_enable_tracking:
                return
            
            # Check if we're in an active run
            active_run = mlflow.active_run()
            if active_run is None:
                # Start a new run for feedback logging
                with mlflow.start_run(run_name=f"feedback_{entry.timestamp}", nested=True):
                    self._log_feedback_data(entry, sentiment_result)
            else:
                # Log to active run
                self._log_feedback_data(entry, sentiment_result)
                
        except Exception as e:
            logger.warning(f"Failed to log feedback to MLflow: {e}")
    
    def _log_feedback_data(self, entry: FeedbackEntry, sentiment_result=None):
        """
        Internal method to log feedback data to MLflow.
        
        Args:
            entry: Feedback entry to log
            sentiment_result: Optional sentiment analysis result
        """
        import mlflow
        
        # Log as metrics
        metrics = {
            "feedback_rating_normalized": entry.get_normalized_rating(),
            "feedback_response_length": float(entry.response_length),
        }
        
        if entry.star_rating is not None:
            metrics["feedback_star_rating"] = float(entry.star_rating)
        
        # Add sentiment metrics if available
        if sentiment_result:
            metrics["feedback_sentiment_confidence"] = sentiment_result.confidence
        
        mlflow.log_metrics(metrics)
        
        # Log as parameters
        params = {
            "feedback_query_type": entry.query_type,
            "feedback_rating": entry.rating,
            "feedback_collections_count": str(len(entry.collections_searched)),
        }
        
        if entry.category:
            params["feedback_category"] = entry.category

        if entry.perspective:
            params["feedback_perspective"] = entry.perspective

        if entry.routing_agent:
            params["feedback_routing_agent"] = entry.routing_agent

        if entry.session_id:
            params["feedback_session_id"] = entry.session_id
        
        # Add sentiment parameters if available
        if sentiment_result:
            params["feedback_sentiment"] = sentiment_result.sentiment
            params["feedback_sentiment_confidence"] = f"{sentiment_result.confidence:.2f}"
            if sentiment_result.emotions:
                params["feedback_emotions"] = ", ".join(sentiment_result.emotions)
        
        mlflow.log_params(params)
        
        # Log collections as tags for easy filtering
        for i, collection in enumerate(entry.collections_searched):
            mlflow.set_tag(f"collection_{i}", collection)
        
        # Log the full feedback as a JSON artifact with sentiment data
        feedback_dict = entry.to_dict()
        if sentiment_result:
            feedback_dict["sentiment"] = {
                "sentiment": sentiment_result.sentiment,
                "confidence": sentiment_result.confidence,
                "emotions": sentiment_result.emotions,
                "keywords_found": sentiment_result.keywords_found
            }
        mlflow.log_dict(feedback_dict, f"feedback_{entry.timestamp}.json")
        
        logger.debug(f"Logged feedback to MLflow: {entry.rating} rating for {entry.query_type}")
    
    def export_feedback(self, output_file: Path) -> bool:
        """
        Export feedback to a different format.
        
        Args:
            output_file: Path to output file (JSON or CSV)
            
        Returns:
            True if export was successful
        """
        try:
            if not self.feedback_file.exists():
                logger.warning("No feedback file to export")
                return False
            
            feedback_entries = []
            with open(self.feedback_file, 'r') as f:
                for line in f:
                    feedback_entries.append(json.loads(line))
            
            if output_file.suffix == '.json':
                with open(output_file, 'w') as f:
                    json.dump(feedback_entries, f, indent=2)
            elif output_file.suffix == '.csv':
                import csv
                if feedback_entries:
                    keys = feedback_entries[0].keys()
                    with open(output_file, 'w', newline='') as f:
                        writer = csv.DictWriter(f, fieldnames=keys)
                        writer.writeheader()
                        writer.writerows(feedback_entries)
            else:
                logger.error(f"Unsupported export format: {output_file.suffix}")
                return False
            
            logger.info(f"Exported {len(feedback_entries)} feedback entries to {output_file}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to export feedback: {e}")
    
            return False


# Singleton instance
_feedback_collector: Optional[FeedbackCollector] = None


def get_feedback_collector() -> FeedbackCollector:
    """Get singleton feedback collector instance."""
    global _feedback_collector
    if _feedback_collector is None:
        _feedback_collector = FeedbackCollector()
    return _feedback_collector


def record_positive_feedback(
    query: str,
    query_type: str,
    collections_searched: List[str],
    response_length: int,
    feedback_text: Optional[str] = None,
    session_id: Optional[str] = None
) -> bool:
    """Convenience function to record positive feedback."""
    collector = get_feedback_collector()
    return collector.record_feedback(
        query=query,
        query_type=query_type,
        collections_searched=collections_searched,
        response_length=response_length,
        rating="positive",
        feedback_text=feedback_text,
        session_id=session_id
    )


def record_negative_feedback(
    query: str,
    query_type: str,
    collections_searched: List[str],
    response_length: int,
    feedback_text: Optional[str] = None,
    suggested_collection: Optional[str] = None,
    session_id: Optional[str] = None
) -> bool:
    """Convenience function to record negative feedback."""
    collector = get_feedback_collector()
    return collector.record_feedback(
        query=query,
        query_type=query_type,
        collections_searched=collections_searched,
        response_length=response_length,
        rating="negative",
        feedback_text=feedback_text,
        suggested_collection=suggested_collection,
        session_id=session_id
    )