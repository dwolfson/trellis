"""Main data preparation pipeline for egeria-python repository."""
import sys
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from loguru import logger
import json
from datetime import datetime

from advisor.data_prep.code_parser import CodeParser, CodeElement
from advisor.data_prep.doc_parser import DocParser, DocumentSection
from advisor.data_prep.example_extractor import ExampleExtractor, CodeExample
from advisor.data_prep.metadata_extractor import MetadataExtractor, FileMetadata


@dataclass
class PipelineResult:
    """Results from running the data preparation pipeline."""
    
    code_elements: List[CodeElement]
    doc_sections: List[DocumentSection]
    examples: List[CodeExample]
    metadata: List[FileMetadata]
    statistics: Dict[str, Any]
    timestamp: datetime
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "code_elements_count": len(self.code_elements),
            "doc_sections_count": len(self.doc_sections),
            "examples_count": len(self.examples),
            "metadata_count": len(self.metadata),
            "statistics": self.statistics,
            "timestamp": self.timestamp.isoformat(),
        }
    
    def save_summary(self, output_path: Path) -> None:
        """Save pipeline summary to JSON file."""
        summary = self.to_dict()
        with open(output_path, 'w') as f:
            json.dump(summary, f, indent=2)
        logger.info(f"Saved pipeline summary to {output_path}")


class DataPreparationPipeline:
    """
    Main pipeline for preparing data from egeria-python repository.
    
    This pipeline:
    1. Parses Python code files to extract functions, classes, methods
    2. Parses markdown documentation to extract sections
    3. Extracts code examples from tests and example files
    4. Extracts metadata from all files
    5. Prepares data for embedding generation and vector store ingestion
    """
    
    def __init__(
        self,
        source_path: Path,
        cache_dir: Optional[Path] = None,
        exclude_patterns: Optional[List[str]] = None
    ):
        """
        Initialize the data preparation pipeline.
        
        Parameters
        ----------
        source_path : Path
            Path to egeria-python repository
        cache_dir : Path, optional
            Directory for caching intermediate results
        exclude_patterns : List[str], optional
            Patterns to exclude from processing
        """
        self.source_path = Path(source_path)
        self.cache_dir = Path(cache_dir) if cache_dir else Path("./data/cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        if exclude_patterns is None:
            exclude_patterns = [
                "**/__pycache__/**",
                "**/deprecated/**",
                "**/.git/**",
                "**/.venv/**",
                "**/node_modules/**",
                "**/.pytest_cache/**",
            ]
        self.exclude_patterns = exclude_patterns
        
        # Initialize parsers
        self.code_parser = CodeParser()
        self.doc_parser = DocParser()
        self.example_extractor = ExampleExtractor()
        self.metadata_extractor = MetadataExtractor(root_path=source_path)
        
        logger.info(f"Initialized pipeline for {source_path}")
    
    def run(
        self,
        parse_code: bool = True,
        parse_docs: bool = True,
        extract_examples: bool = True,
        extract_metadata: bool = True,
        save_cache: bool = True
    ) -> PipelineResult:
        """
        Run the complete data preparation pipeline.
        
        Parameters
        ----------
        parse_code : bool, default True
            Whether to parse Python code files
        parse_docs : bool, default True
            Whether to parse documentation files
        extract_examples : bool, default True
            Whether to extract code examples
        extract_metadata : bool, default True
            Whether to extract file metadata
        save_cache : bool, default True
            Whether to save results to cache
        
        Returns
        -------
        PipelineResult
            Results from the pipeline execution
        """
        logger.info("=" * 80)
        logger.info("Starting Data Preparation Pipeline")
        logger.info("=" * 80)
        
        start_time = datetime.now()
        
        # Parse code
        code_elements = []
        if parse_code:
            logger.info("\n[1/4] Parsing Python code files...")
            code_elements = self._parse_code()
            logger.info(f"✓ Extracted {len(code_elements)} code elements")
        
        # Parse documentation
        doc_sections = []
        if parse_docs:
            logger.info("\n[2/4] Parsing documentation files...")
            doc_sections = self._parse_docs()
            logger.info(f"✓ Extracted {len(doc_sections)} documentation sections")
        
        # Extract examples
        examples = []
        if extract_examples:
            logger.info("\n[3/4] Extracting code examples...")
            examples = self._extract_examples()
            logger.info(f"✓ Extracted {len(examples)} code examples")
        
        # Extract metadata
        metadata = []
        if extract_metadata:
            logger.info("\n[4/4] Extracting file metadata...")
            metadata = self._extract_metadata()
            logger.info(f"✓ Extracted metadata from {len(metadata)} files")
        
        # Compile statistics
        statistics = self._compile_statistics(
            code_elements, doc_sections, examples, metadata
        )
        
        # Create result
        result = PipelineResult(
            code_elements=code_elements,
            doc_sections=doc_sections,
            examples=examples,
            metadata=metadata,
            statistics=statistics,
            timestamp=datetime.now()
        )
        
        # Save to cache
        if save_cache:
            self._save_to_cache(result)
        
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info("\n" + "=" * 80)
        logger.info(f"Pipeline completed in {elapsed:.2f} seconds")
        logger.info("=" * 80)
        
        self._print_summary(result)
        
        return result
    
    def _parse_code(self) -> List[CodeElement]:
        """Parse Python code files."""
        pyegeria_path = self.source_path / "pyegeria"
        commands_path = self.source_path / "commands"
        
        elements = []
        
        # Parse pyegeria package
        if pyegeria_path.exists():
            logger.info(f"Parsing {pyegeria_path}...")
            elements.extend(
                self.code_parser.parse_directory(
                    pyegeria_path,
                    recursive=True,
                    exclude_patterns=self.exclude_patterns
                )
            )
        
        # Parse commands package
        if commands_path.exists():
            logger.info(f"Parsing {commands_path}...")
            elements.extend(
                self.code_parser.parse_directory(
                    commands_path,
                    recursive=True,
                    exclude_patterns=self.exclude_patterns
                )
            )
        
        return elements
    
    def _parse_docs(self) -> List[DocumentSection]:
        """Parse documentation files."""
        sections = []
        
        # Parse root-level docs
        logger.info(f"Parsing documentation in {self.source_path}...")
        sections.extend(
            self.doc_parser.parse_directory(
                self.source_path,
                recursive=True,
                exclude_patterns=self.exclude_patterns
            )
        )
        
        return sections
    
    def _extract_examples(self) -> List[CodeExample]:
        """Extract code examples."""
        examples_path = self.source_path / "examples"
        tests_path = self.source_path / "tests"
        
        examples = []
        
        # Extract from examples directory
        if examples_path.exists():
            logger.info(f"Extracting examples from {examples_path}...")
            examples.extend(
                self.example_extractor.extract_from_directory(
                    examples_path,
                    recursive=True,
                    include_tests=False,
                    include_examples=True,
                    exclude_patterns=self.exclude_patterns
                )
            )
        
        # Extract from tests directory
        if tests_path.exists():
            logger.info(f"Extracting examples from {tests_path}...")
            examples.extend(
                self.example_extractor.extract_from_directory(
                    tests_path,
                    recursive=True,
                    include_tests=True,
                    include_examples=False,
                    exclude_patterns=self.exclude_patterns
                )
            )
        
        return examples
    
    def _extract_metadata(self) -> List[FileMetadata]:
        """Extract file metadata."""
        metadata = self.metadata_extractor.extract_from_directory(
            self.source_path,
            recursive=True,
            file_patterns=['*.py', '*.md'],
            exclude_patterns=self.exclude_patterns
        )
        
        return metadata
    
    def _compile_statistics(
        self,
        code_elements: List[CodeElement],
        doc_sections: List[DocumentSection],
        examples: List[CodeExample],
        metadata: List[FileMetadata]
    ) -> Dict[str, Any]:
        """Compile comprehensive statistics."""
        
        # Code statistics
        code_stats = {
            "total": len(code_elements),
            "by_type": {},
            "public_elements": 0,
            "with_docstrings": 0,
            "avg_complexity": 0,
        }
        
        total_complexity = 0
        for elem in code_elements:
            code_stats["by_type"][elem.type] = code_stats["by_type"].get(elem.type, 0) + 1
            if elem.is_public:
                code_stats["public_elements"] += 1
            if elem.docstring:
                code_stats["with_docstrings"] += 1
            total_complexity += elem.complexity
        
        if code_elements:
            code_stats["avg_complexity"] = total_complexity / len(code_elements)
        
        # Documentation statistics
        doc_stats = {
            "total": len(doc_sections),
            "by_level": {},
            "with_code": 0,
            "total_words": 0,
        }
        
        for section in doc_sections:
            doc_stats["by_level"][section.level] = doc_stats["by_level"].get(section.level, 0) + 1
            if section.has_code:
                doc_stats["with_code"] += 1
            doc_stats["total_words"] += section.word_count
        
        # Example statistics
        example_stats = {
            "total": len(examples),
            "by_type": {},
            "with_apis": 0,
        }
        
        for example in examples:
            example_stats["by_type"][example.example_type] = example_stats["by_type"].get(example.example_type, 0) + 1
            if example.related_apis:
                example_stats["with_apis"] += 1
        
        # Metadata statistics
        metadata_stats = self.metadata_extractor.get_statistics()
        
        return {
            "code": code_stats,
            "documentation": doc_stats,
            "examples": example_stats,
            "metadata": metadata_stats,
            "parsers": {
                "code_parser": self.code_parser.get_statistics(),
                "doc_parser": self.doc_parser.get_statistics(),
                "example_extractor": self.example_extractor.get_statistics(),
            }
        }
    
    def _save_to_cache(self, result: PipelineResult) -> None:
        """Save results to cache."""
        logger.info("\nSaving results to cache...")
        
        # Save code elements
        code_cache = self.cache_dir / "code_elements.json"
        with open(code_cache, 'w') as f:
            json.dump([elem.to_dict() for elem in result.code_elements], f, indent=2)
        logger.info(f"✓ Saved code elements to {code_cache}")
        
        # Save doc sections
        doc_cache = self.cache_dir / "doc_sections.json"
        with open(doc_cache, 'w') as f:
            json.dump([sec.to_dict() for sec in result.doc_sections], f, indent=2)
        logger.info(f"✓ Saved doc sections to {doc_cache}")
        
        # Save examples
        examples_cache = self.cache_dir / "examples.json"
        with open(examples_cache, 'w') as f:
            json.dump([ex.to_dict() for ex in result.examples], f, indent=2)
        logger.info(f"✓ Saved examples to {examples_cache}")
        
        # Save metadata
        metadata_cache = self.cache_dir / "metadata.json"
        with open(metadata_cache, 'w') as f:
            json.dump([m.to_dict() for m in result.metadata], f, indent=2)
        logger.info(f"✓ Saved metadata to {metadata_cache}")
        
        # Save summary
        summary_cache = self.cache_dir / "pipeline_summary.json"
        result.save_summary(summary_cache)
    
    def _print_summary(self, result: PipelineResult) -> None:
        """Print pipeline summary."""
        stats = result.statistics
        
        print("\n" + "=" * 80)
        print("PIPELINE SUMMARY")
        print("=" * 80)
        
        print(f"\n📝 Code Elements: {stats['code']['total']}")
        print(f"   - Functions: {stats['code']['by_type'].get('function', 0)}")
        print(f"   - Classes: {stats['code']['by_type'].get('class', 0)}")
        print(f"   - Methods: {stats['code']['by_type'].get('method', 0)}")
        print(f"   - Public: {stats['code']['public_elements']}")
        print(f"   - With docstrings: {stats['code']['with_docstrings']}")
        print(f"   - Avg complexity: {stats['code']['avg_complexity']:.2f}")
        
        print(f"\n📚 Documentation: {stats['documentation']['total']} sections")
        print(f"   - With code blocks: {stats['documentation']['with_code']}")
        print(f"   - Total words: {stats['documentation']['total_words']:,}")
        
        print(f"\n💡 Examples: {stats['examples']['total']}")
        for ex_type, count in stats['examples']['by_type'].items():
            print(f"   - {ex_type}: {count}")
        
        print(f"\n📁 Files: {stats['metadata']['total_files']}")
        print(f"   - Python: {stats['metadata']['by_type'].get('python', 0)}")
        print(f"   - Markdown: {stats['metadata']['by_type'].get('markdown', 0)}")
        print(f"   - Total size: {stats['metadata']['total_size_bytes']:,} bytes")
        print(f"   - Total lines: {stats['metadata']['total_lines']:,}")
        
        # Print errors if any
        total_errors = (
            stats['parsers']['code_parser']['errors'] +
            stats['parsers']['doc_parser']['errors'] +
            stats['parsers']['example_extractor']['errors']
        )
        if total_errors > 0:
            print(f"\n⚠️  Errors: {total_errors}")
            print(f"   - Code parser: {stats['parsers']['code_parser']['errors']}")
            print(f"   - Doc parser: {stats['parsers']['doc_parser']['errors']}")
            print(f"   - Example extractor: {stats['parsers']['example_extractor']['errors']}")
        
        print("\n" + "=" * 80)


def main():
    """Run the pipeline from command line."""
    import sys
    import argparse
    from advisor.config import settings

    parser = argparse.ArgumentParser(description="Run data preparation pipeline")
    parser.add_argument(
        "source_path",
        nargs="?",
        default=str(settings.advisor_data_path),
        help="Path to egeria-python repository"
    )
    parser.add_argument(
        "--cache-dir",
        default="./data/cache",
        help="Directory for caching results"
    )
    parser.add_argument(
        "--no-code",
        action="store_true",
        help="Skip code parsing"
    )
    parser.add_argument(
        "--no-docs",
        action="store_true",
        help="Skip documentation parsing"
    )
    parser.add_argument(
        "--no-examples",
        action="store_true",
        help="Skip example extraction"
    )
    parser.add_argument(
        "--no-metadata",
        action="store_true",
        help="Skip metadata extraction"
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Don't save results to cache"
    )
    
    args = parser.parse_args()
    
    # Initialize pipeline
    pipeline = DataPreparationPipeline(
        source_path=Path(args.source_path),
        cache_dir=Path(args.cache_dir)
    )
    
    # Run pipeline
    result = pipeline.run(
        parse_code=not args.no_code,
        parse_docs=not args.no_docs,
        extract_examples=not args.no_examples,
        extract_metadata=not args.no_metadata,
        save_cache=not args.no_cache
    )
    
    return 0


if __name__ == "__main__":
    sys.exit(main())