# Phase 9: Use Case Examples & Code Samples

**Status: unbuilt.** Moved out of `docs/history/` on 2026-09-03 — the document declares itself "Design Phase, Priority: High, Estimated Effort: 2-3 days", which is open work rather than a completion record. `future/` is where open work belongs.

**Status:** Design Phase  
**Priority:** High  
**Estimated Effort:** 2-3 days

## Overview

Extend Egeria Advisor to provide comprehensive coding samples for common pyegeria use cases. This will help users understand how to use the library through practical, working examples.

## Current State

**What We Have:**
- RAG system that retrieves relevant code snippets
- Query processor that understands user intent
- Vector store with 4,601 code elements indexed
- Analytics for quantitative queries
- Relationship queries for dependencies

**What's Missing:**
- Use case categorization
- Multi-file example assembly
- Complete working examples
- Use case templates
- Example validation

## Use Cases to Support

### 1. Connection & Authentication
**Examples:**
- Connect to Egeria platform
- Authenticate with different methods
- Configure SSL/TLS
- Handle connection errors

### 2. Asset Management
**Examples:**
- Create an asset
- Search for assets
- Update asset properties
- Delete an asset
- Bulk asset operations

### 3. Glossary Management
**Examples:**
- Create glossary terms
- Link terms to assets
- Create term relationships
- Search glossary
- Export/import glossary

### 4. Lineage Tracking
**Examples:**
- Query lineage for an asset
- Create lineage relationships
- Visualize lineage graph
- Track data flow

### 5. Governance
**Examples:**
- Create governance zones
- Assign classifications
- Set up governance rules
- Audit trail queries

### 6. Integration
**Examples:**
- Set up connectors
- Configure integration daemon
- Monitor integration status
- Handle integration errors

## Architecture Design

### Component 1: Use Case Detector

```python
class UseCaseDetector:
    """Detect which use case the user is asking about."""
    
    USE_CASES = {
        "connection": ["connect", "authenticate", "login", "platform"],
        "asset": ["asset", "create asset", "find asset", "search"],
        "glossary": ["glossary", "term", "category", "taxonomy"],
        "lineage": ["lineage", "data flow", "provenance", "trace"],
        "governance": ["governance", "zone", "classification", "policy"],
        "integration": ["connector", "integration", "daemon", "sync"]
    }
    
    def detect_use_case(self, query: str) -> Optional[str]:
        """
        Detect use case from query.
        
        Returns:
            Use case name or None
        """
        query_lower = query.lower()
        
        for use_case, keywords in self.USE_CASES.items():
            if any(keyword in query_lower for keyword in keywords):
                return use_case
        
        return None
```

### Component 2: Example Assembler

```python
class ExampleAssembler:
    """Assemble complete code examples from multiple sources."""
    
    def __init__(self, vector_store, code_analyzer):
        self.vector_store = vector_store
        self.code_analyzer = code_analyzer
        self.templates = self._load_templates()
    
    def assemble_example(
        self,
        use_case: str,
        specific_task: str
    ) -> Dict[str, Any]:
        """
        Assemble a complete working example.
        
        Args:
            use_case: High-level use case (e.g., "asset")
            specific_task: Specific task (e.g., "create asset")
        
        Returns:
            {
                "title": "Create an Asset in Egeria",
                "description": "...",
                "imports": ["from pyegeria import ..."],
                "setup": "# Setup code",
                "main_code": "# Main example",
                "error_handling": "# Error handling",
                "complete_example": "# Full working code",
                "explanation": "Step-by-step explanation",
                "related_examples": [...]
            }
        """
        # 1. Get template for use case
        template = self.templates.get(use_case)
        
        # 2. Search for relevant code
        relevant_code = self._search_relevant_code(use_case, specific_task)
        
        # 3. Extract imports
        imports = self._extract_imports(relevant_code)
        
        # 4. Build setup code
        setup = self._build_setup(use_case, relevant_code)
        
        # 5. Build main code
        main_code = self._build_main_code(specific_task, relevant_code)
        
        # 6. Add error handling
        error_handling = self._add_error_handling(use_case)
        
        # 7. Assemble complete example
        complete = self._assemble_complete(
            imports, setup, main_code, error_handling
        )
        
        # 8. Generate explanation
        explanation = self._generate_explanation(complete, use_case)
        
        # 9. Find related examples
        related = self._find_related_examples(use_case, specific_task)
        
        return {
            "title": self._generate_title(use_case, specific_task),
            "description": template.get("description"),
            "imports": imports,
            "setup": setup,
            "main_code": main_code,
            "error_handling": error_handling,
            "complete_example": complete,
            "explanation": explanation,
            "related_examples": related
        }
```

### Component 3: Example Templates

```python
# templates/use_case_templates.yaml

connection:
  description: "Connect to an Egeria platform and authenticate"
  imports:
    - "from pyegeria import EgeriaClient"
    - "from pyegeria.exceptions import ConnectionError"
  setup: |
    # Configuration
    platform_url = "https://localhost:9443"
    user_id = "erinoverview"
    password = "secret"
  main_pattern: |
    # Create client and connect
    client = EgeriaClient(platform_url, user_id, password)
    client.connect()
  error_handling: |
    try:
        client.connect()
    except ConnectionError as e:
        print(f"Failed to connect: {e}")

asset:
  description: "Work with assets in Egeria"
  imports:
    - "from pyegeria import AssetManager"
    - "from pyegeria.models import Asset"
  setup: |
    # Initialize asset manager
    asset_mgr = AssetManager(client)
  main_pattern: |
    # Create an asset
    asset = Asset(
        name="My Dataset",
        type="DataSet",
        description="Example dataset"
    )
    asset_guid = asset_mgr.create_asset(asset)
```

### Component 4: Example Validator

```python
class ExampleValidator:
    """Validate that examples are syntactically correct."""
    
    def validate_example(self, code: str) -> Dict[str, Any]:
        """
        Validate example code.
        
        Returns:
            {
                "valid": True/False,
                "errors": [...],
                "warnings": [...],
                "suggestions": [...]
            }
        """
        result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "suggestions": []
        }
        
        # 1. Check syntax
        try:
            compile(code, '<string>', 'exec')
        except SyntaxError as e:
            result["valid"] = False
            result["errors"].append(f"Syntax error: {e}")
        
        # 2. Check imports
        imports = self._extract_imports(code)
        for imp in imports:
            if not self._is_valid_import(imp):
                result["warnings"].append(f"Import may not exist: {imp}")
        
        # 3. Check for common issues
        if "password" in code and "secret" in code.lower():
            result["warnings"].append("Example contains hardcoded password")
        
        # 4. Suggest improvements
        if "try:" not in code:
            result["suggestions"].append("Consider adding error handling")
        
        return result
```

## Query Types for Examples

### 1. "Show me how to..." Queries
```
"Show me how to connect to Egeria"
"Show me how to create an asset"
"Show me how to search the glossary"
```

**Response:**
- Complete working example
- Step-by-step explanation
- Common variations
- Error handling

### 2. "Give me an example of..." Queries
```
"Give me an example of creating a glossary term"
"Give me an example of querying lineage"
```

**Response:**
- Focused code snippet
- Minimal setup
- Clear comments
- Link to full example

### 3. "What's the best way to..." Queries
```
"What's the best way to bulk import assets?"
"What's the best way to handle authentication?"
```

**Response:**
- Recommended approach
- Complete example
- Alternative approaches
- Performance considerations

## Implementation Plan

### Phase 1: Foundation (Day 1)

**Tasks:**
1. Create `UseCaseDetector` class
2. Define use case categories
3. Create example templates
4. Add use case detection to query processor

**Deliverables:**
- `advisor/use_case_detector.py`
- `templates/use_case_templates.yaml`
- Updated query processor

### Phase 2: Example Assembly (Day 2)

**Tasks:**
1. Create `ExampleAssembler` class
2. Implement code search for examples
3. Build import extraction
4. Create example formatting

**Deliverables:**
- `advisor/example_assembler.py`
- Example assembly logic
- Template rendering

### Phase 3: Integration (Day 2-3)

**Tasks:**
1. Integrate with RAG system
2. Add example query type
3. Create example formatter
4. Test end-to-end

**Deliverables:**
- Updated RAG system
- Example responses in CLI
- Test suite

### Phase 4: Validation & Polish (Day 3)

**Tasks:**
1. Create `ExampleValidator`
2. Add syntax checking
3. Validate all templates
4. Create documentation

**Deliverables:**
- `advisor/example_validator.py`
- Validated templates
- User documentation

## Example Output Format

### CLI Output:
```
Query: "Show me how to create an asset"

╭─────────────────────────────────────────────────────────╮
│ Example: Create an Asset in Egeria                      │
╰─────────────────────────────────────────────────────────╯

Description:
This example shows how to create a new asset in Egeria using
the AssetManager class.

Complete Example:
───────────────────────────────────────────────────────────
from pyegeria import EgeriaClient, AssetManager
from pyegeria.models import Asset
from pyegeria.exceptions import AssetError

# 1. Connect to Egeria
client = EgeriaClient(
    platform_url="https://localhost:9443",
    user_id="erinoverview",
    password="secret"
)
client.connect()

# 2. Initialize asset manager
asset_mgr = AssetManager(client)

# 3. Create asset
try:
    asset = Asset(
        name="Customer Database",
        type="DataSet",
        description="Main customer database",
        properties={
            "database": "customers_db",
            "schema": "public"
        }
    )
    
    asset_guid = asset_mgr.create_asset(asset)
    print(f"Created asset: {asset_guid}")
    
except AssetError as e:
    print(f"Failed to create asset: {e}")
───────────────────────────────────────────────────────────

Step-by-Step Explanation:
1. Import required classes from pyegeria
2. Create and connect EgeriaClient
3. Initialize AssetManager with the client
4. Create Asset object with properties
5. Call create_asset() to persist
6. Handle potential errors

Related Examples:
• Search for assets
• Update asset properties
• Delete an asset
• Bulk asset operations

Try it: Copy this code and replace the connection details
        with your Egeria platform configuration.
```

## Success Metrics

1. **Coverage**: Support 6 major use cases
2. **Quality**: All examples syntactically valid
3. **Completeness**: Examples include error handling
4. **Usability**: Clear explanations and comments
5. **Discoverability**: Easy to find relevant examples

## Testing Strategy

### Unit Tests
- Test use case detection
- Test example assembly
- Test template rendering
- Test validation

### Integration Tests
- Test end-to-end example generation
- Test with real queries
- Test error handling

### Manual Testing
- Try each use case
- Verify examples work
- Check explanations are clear

## Future Enhancements

1. **Interactive Examples**: Allow users to customize parameters
2. **Example Library**: Build searchable example database
3. **Video Tutorials**: Link examples to video walkthroughs
4. **Jupyter Notebooks**: Generate notebook versions
5. **API Documentation**: Link to API docs
6. **Community Examples**: Allow user-contributed examples

## Questions to Resolve

1. Should examples be stored in templates or generated dynamically?
2. How do we keep examples up-to-date with pyegeria changes?
3. Should we validate examples against a running Egeria instance?
4. How do we handle version-specific examples?
5. Should we support multiple programming styles (functional vs OOP)?

## Next Steps

1. Review and approve design
2. Create example templates for top 3 use cases
3. Implement UseCaseDetector
4. Build basic ExampleAssembler
5. Test with sample queries
6. Iterate based on feedback

---

*Created: 2026-02-18*  
*Status: Design phase - ready for implementation*