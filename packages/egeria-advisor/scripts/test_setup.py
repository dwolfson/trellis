#!/usr/bin/env python3
"""
Test script to verify egeria-advisor setup and dependencies.

Run this after installing dependencies to ensure everything is working.
"""
import sys
from pathlib import Path

def test_imports():
    """Test that all required imports work."""
    print("Testing imports...")
    errors = []
    
    try:
        import pydantic
        print("  ✓ pydantic")
    except ImportError as e:
        errors.append(f"  ✗ pydantic: {e}")
    
    try:
        import loguru
        print("  ✓ loguru")
    except ImportError as e:
        errors.append(f"  ✗ loguru: {e}")
    
    try:
        import yaml
        print("  ✓ pyyaml")
    except ImportError as e:
        errors.append(f"  ✗ pyyaml: {e}")
    
    try:
        from advisor.config import settings
        print("  ✓ advisor.config")
    except ImportError as e:
        errors.append(f"  ✗ advisor.config: {e}")
    
    try:
        from advisor.data_prep import CodeParser
        print("  ✓ advisor.data_prep.CodeParser")
    except ImportError as e:
        errors.append(f"  ✗ advisor.data_prep.CodeParser: {e}")
    
    if errors:
        print("\n❌ Import errors found:")
        for error in errors:
            print(error)
        return False
    else:
        print("\n✅ All imports successful!")
        return True

def test_config():
    """Test configuration loading."""
    print("\nTesting configuration...")
    
    try:
        from advisor.config import settings, load_config
        
        print(f"  ✓ Settings loaded")
        print(f"    - Data path: {settings.advisor_data_path}")
        print(f"    - Cache dir: {settings.advisor_cache_dir}")
        print(f"    - pgvector: {settings.pgvector_host}:{settings.pgvector_port}")
        print(f"    - Ollama: {settings.ollama_base_url}")
        print(f"    - MLflow: {settings.mlflow_tracking_uri}")
        
        # Try loading YAML config
        config_path = Path(__file__).parent.parent / "advisor" / "configdata" / "advisor.yaml"
        if config_path.exists():
            config = load_config(config_path)
            print(f"  ✓ YAML config loaded from {config_path}")
        else:
            print(f"  ⚠ YAML config not found at {config_path}")
        
        return True
    except Exception as e:
        print(f"  ✗ Configuration error: {e}")
        return False

def test_parsers():
    """Test that parsers can be instantiated."""
    print("\nTesting parsers...")
    
    try:
        from advisor.data_prep import (
            CodeParser,
            DocParser,
            ExampleExtractor,
            MetadataExtractor,
            DataPreparationPipeline
        )
        
        code_parser = CodeParser()
        print("  ✓ CodeParser instantiated")
        
        doc_parser = DocParser()
        print("  ✓ DocParser instantiated")
        
        example_extractor = ExampleExtractor()
        print("  ✓ ExampleExtractor instantiated")
        
        metadata_extractor = MetadataExtractor()
        print("  ✓ MetadataExtractor instantiated")
        
        pipeline = DataPreparationPipeline(
            source_path=Path("/tmp"),
            cache_dir=Path("/tmp/cache")
        )
        print("  ✓ DataPreparationPipeline instantiated")
        
        return True
    except Exception as e:
        print(f"  ✗ Parser error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_egeria_python_path():
    """Test that egeria-python path exists."""
    print("\nTesting egeria-python path...")
    
    try:
        from advisor.config import settings
        
        egeria_path = settings.advisor_data_path
        if egeria_path.exists():
            print(f"  ✓ Path exists: {egeria_path}")
            
            # Check for key directories
            pyegeria = egeria_path / "pyegeria"
            commands = egeria_path / "commands"
            tests = egeria_path / "tests"
            examples = egeria_path / "examples"
            
            if pyegeria.exists():
                print(f"    ✓ pyegeria/ found")
            else:
                print(f"    ⚠ pyegeria/ not found")
            
            if commands.exists():
                print(f"    ✓ commands/ found")
            else:
                print(f"    ⚠ commands/ not found")
            
            if tests.exists():
                print(f"    ✓ tests/ found")
            else:
                print(f"    ⚠ tests/ not found")
            
            if examples.exists():
                print(f"    ✓ examples/ found")
            else:
                print(f"    ⚠ examples/ not found")
            
            return True
        else:
            print(f"  ✗ Path does not exist: {egeria_path}")
            print(f"    Update ADVISOR_DATA_PATH in .env file")
            return False
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False

def test_cache_directory():
    """Test that cache directory can be created."""
    print("\nTesting cache directory...")
    
    try:
        from advisor.config import settings
        
        cache_dir = settings.advisor_cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)
        
        if cache_dir.exists():
            print(f"  ✓ Cache directory exists: {cache_dir}")
            return True
        else:
            print(f"  ✗ Could not create cache directory: {cache_dir}")
            return False
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False

def main():
    """Run all tests."""
    print("=" * 80)
    print("Egeria Advisor Setup Test")
    print("=" * 80)
    
    results = []
    
    results.append(("Imports", test_imports()))
    results.append(("Configuration", test_config()))
    results.append(("Parsers", test_parsers()))
    results.append(("Egeria Path", test_egeria_python_path()))
    results.append(("Cache Directory", test_cache_directory()))
    
    print("\n" + "=" * 80)
    print("Test Summary")
    print("=" * 80)
    
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {name}")
    
    all_passed = all(passed for _, passed in results)
    
    if all_passed:
        print("\n🎉 All tests passed! Setup is complete.")
        print("\nNext steps:")
        print("  1. Run the pipeline: python -m advisor.data_prep.pipeline")
        print("  2. Check results in: data/cache/")
        return 0
    else:
        print("\n⚠️  Some tests failed. Please fix the issues above.")
        print("\nCommon fixes:")
        print("  - Install dependencies: pip install -e '.[dev]'")
        print("  - Create .env file: cp .env.example .env")
        print("  - Update paths in .env file")
        return 1

if __name__ == "__main__":
    sys.exit(main())