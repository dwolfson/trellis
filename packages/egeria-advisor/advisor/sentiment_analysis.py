"""
Simple sentiment analysis for user feedback comments.

Uses keyword-based analysis for lightweight, fast sentiment detection
without requiring external NLP libraries.
"""

from typing import Dict, List, Tuple
from dataclasses import dataclass


@dataclass
class SentimentResult:
    """Sentiment analysis result."""
    sentiment: str  # "positive", "negative", "neutral", "frustrated", "enthusiastic"
    confidence: float  # 0.0 to 1.0
    keywords_found: List[str]
    emotion: str  # "happy", "frustrated", "confused", "satisfied", "disappointed"


class SimpleSentimentAnalyzer:
    """
    Lightweight sentiment analyzer using keyword matching.
    
    Fast and dependency-free, suitable for real-time feedback analysis.
    """
    
    # Sentiment keywords
    POSITIVE_KEYWORDS = {
        "excellent", "great", "perfect", "amazing", "helpful", "clear",
        "good", "nice", "thanks", "thank", "love", "awesome", "fantastic",
        "wonderful", "brilliant", "exactly", "precisely", "spot on"
    }
    
    NEGATIVE_KEYWORDS = {
        "bad", "poor", "wrong", "incorrect", "useless", "terrible", "awful",
        "horrible", "disappointing", "disappointed", "frustrating", "confused",
        "confusing", "unclear", "incomplete", "missing", "failed", "broken"
    }
    
    FRUSTRATION_KEYWORDS = {
        "frustrating", "frustrated", "annoying", "annoyed", "irritating",
        "why", "still", "again", "always", "never works", "doesn't work",
        "not working", "broken", "waste of time"
    }
    
    ENTHUSIASM_KEYWORDS = {
        "love", "amazing", "fantastic", "brilliant", "perfect", "exactly",
        "finally", "wow", "awesome", "incredible", "outstanding"
    }
    
    CONFUSION_KEYWORDS = {
        "confused", "confusing", "unclear", "don't understand", "what",
        "how", "why", "makes no sense", "doesn't make sense"
    }
    
    def analyze(self, text: str) -> SentimentResult:
        """
        Analyze sentiment of text.
        
        Args:
            text: Text to analyze
            
        Returns:
            SentimentResult with sentiment classification
        """
        if not text or not text.strip():
            return SentimentResult(
                sentiment="neutral",
                confidence=0.0,
                keywords_found=[],
                emotion="neutral"
            )
        
        text_lower = text.lower()
        words = set(text_lower.split())
        
        # Count keyword matches
        positive_matches = self._count_matches(words, self.POSITIVE_KEYWORDS)
        negative_matches = self._count_matches(words, self.NEGATIVE_KEYWORDS)
        frustration_matches = self._count_matches(words, self.FRUSTRATION_KEYWORDS)
        enthusiasm_matches = self._count_matches(words, self.ENTHUSIASM_KEYWORDS)
        confusion_matches = self._count_matches(words, self.CONFUSION_KEYWORDS)
        
        # Determine primary sentiment
        total_matches = positive_matches + negative_matches
        
        if total_matches == 0:
            sentiment = "neutral"
            confidence = 0.5
            emotion = "neutral"
            keywords = []
        elif enthusiasm_matches > 0:
            sentiment = "enthusiastic"
            confidence = min(0.9, 0.6 + (enthusiasm_matches * 0.1))
            emotion = "enthusiastic"
            keywords = self._get_matched_keywords(text_lower, self.ENTHUSIASM_KEYWORDS)
        elif frustration_matches > 0:
            sentiment = "frustrated"
            confidence = min(0.9, 0.6 + (frustration_matches * 0.1))
            emotion = "frustrated"
            keywords = self._get_matched_keywords(text_lower, self.FRUSTRATION_KEYWORDS)
        elif confusion_matches > 0:
            sentiment = "negative"
            confidence = min(0.8, 0.5 + (confusion_matches * 0.1))
            emotion = "confused"
            keywords = self._get_matched_keywords(text_lower, self.CONFUSION_KEYWORDS)
        elif positive_matches > negative_matches:
            sentiment = "positive"
            confidence = positive_matches / total_matches
            emotion = "satisfied"
            keywords = self._get_matched_keywords(text_lower, self.POSITIVE_KEYWORDS)
        elif negative_matches > positive_matches:
            sentiment = "negative"
            confidence = negative_matches / total_matches
            emotion = "disappointed"
            keywords = self._get_matched_keywords(text_lower, self.NEGATIVE_KEYWORDS)
        else:
            sentiment = "neutral"
            confidence = 0.5
            emotion = "neutral"
            keywords = []
        
        return SentimentResult(
            sentiment=sentiment,
            confidence=confidence,
            keywords_found=keywords[:5],  # Top 5 keywords
            emotion=emotion
        )
    
    def _count_matches(self, words: set, keyword_set: set) -> int:
        """Count how many keywords match."""
        return len(words.intersection(keyword_set))
    
    def _get_matched_keywords(self, text: str, keyword_set: set) -> List[str]:
        """Get list of matched keywords."""
        return [kw for kw in keyword_set if kw in text]
    
    def analyze_feedback_batch(self, feedback_entries: List[Dict]) -> Dict[str, any]:
        """
        Analyze sentiment for a batch of feedback entries.
        
        Args:
            feedback_entries: List of feedback entry dictionaries
            
        Returns:
            Dictionary with aggregated sentiment statistics
        """
        results = {
            "total": len(feedback_entries),
            "positive": 0,
            "negative": 0,
            "neutral": 0,
            "frustrated": 0,
            "enthusiastic": 0,
            "emotions": {},
            "common_keywords": {},
            "avg_confidence": 0.0
        }
        
        if not feedback_entries:
            return results
        
        total_confidence = 0.0
        all_keywords = []
        
        for entry in feedback_entries:
            comment = entry.get("user_comment") or entry.get("feedback_text") or ""
            if not comment:
                continue
            
            analysis = self.analyze(comment)
            
            # Count sentiments
            results[analysis.sentiment] = results.get(analysis.sentiment, 0) + 1
            
            # Count emotions
            results["emotions"][analysis.emotion] = \
                results["emotions"].get(analysis.emotion, 0) + 1
            
            # Collect keywords
            all_keywords.extend(analysis.keywords_found)
            total_confidence += analysis.confidence
        
        # Calculate averages
        if results["total"] > 0:
            results["avg_confidence"] = total_confidence / results["total"]
        
        # Count keyword frequency
        from collections import Counter
        keyword_counts = Counter(all_keywords)
        results["common_keywords"] = dict(keyword_counts.most_common(10))
        
        return results


# Singleton instance
_analyzer: SimpleSentimentAnalyzer = None


def get_sentiment_analyzer() -> SimpleSentimentAnalyzer:
    """Get or create sentiment analyzer singleton."""
    global _analyzer
    if _analyzer is None:
        _analyzer = SimpleSentimentAnalyzer()
    return _analyzer