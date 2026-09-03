# Egeria & pyegeria Feature Wish List

**Status: upstream-facing, not Egeria Advisor design.** This lists feature gaps
and model-alignment requests for **Egeria and pyegeria themselves**, identified
while integrating against them — it is not a backlog of this application's own
work, which lives in `BACKLOG.md`.

It is complementary to `egeria-python`'s `PYEGERIA_ISSUES.md`, which is the
canonical tracker for **bugs**. This is the place for *"the API could do X"*
rather than *"the API does X wrong"*. Kept in `design/` because the gaps it names
shape what this application can be designed to do.


This document lists design gaps, improvements, and enhancements identified during the integration of Egeria's Area 5 (Data Classes / Value Specifications) and Area 6 (Governance Actions) into the Resource Explorer.

---

## 1. pyegeria API Feature Gaps

### Governance Action Process Chaining (Area 6)
* **Observation**: Egeria's Area 6 type system allows linking process steps sequentially using governance action process steps, but the relationship structure in OMRS returns a flat node map and a separate edge list (`processStepLinks` keyed by GUID).
* **Wish List Item**: Expose a simplified client-side utility in `pyegeria` to traverse process chains and resolve step sequences sequentially, reducing graph-walk logic overhead in client applications.
* **Component Affected**: **pyegeria** (client library utility) & **Egeria-Advisor** (to validate and execute process step plans).

---

## 2. Egeria Metadata Model alignment (Area 5 & Area 6)

### Static Schema / Column Name Match Patterns in `DataClass`
* **Observation**: In Egeria's Area 5 model [0541 Data Classes and Data Grains](https://egeria-project.org/types/5/0541-Data-Classes-and-Data-Grains/), a `DataClass` defines a logical data type. Its `dataPatterns` attribute is intended for regular expressions matching *data values* (e.g., matching a string of digits for a Credit Card). However, there is no first-class metadata property for matching *schema attributes / column names* during static analysis (when actual data values are not yet ingested).
* **Alignment Resolution**: Rather than using non-standard `additionalProperties` (which violates model purity), we represent column name regexes directly within the first-class `dataPatterns` list. If a discovery engine operates in "static schema-only mode", it matches column names against the regexes in `dataPatterns`.
* **Wish List Item**: Clarify or extend Egeria's [0540 Data Value Specification](https://egeria-project.org/types/5/0540-Data-Value-Specification/) model to formally support static name-matching patterns alongside value-matching patterns.
* **Component Affected**: **Combination** of **pyegeria** (adding convenience filters) & **Egeria-Advisor** (leveraging first-class patterns, no Egeria core changes required).

### Valid Value Sets for Classification Keywords (Area 5 & Area 545)
* **Observation**: Classification keywords used to match schema columns (e.g. "email", "phone", "ssn") are reference data. Storing them as a raw list of strings inside a text attribute (like `dataPatterns`) or as a comma-separated string is a modeling shortcut.
* **Alignment Resolution**: Egeria's Reference Data model [0545 Reference Data](https://egeria-project.org/types/5/0545-Reference-Data/) defines `ValidValuesSet` and `ValidValueDefinition` to model lists of authoritative values. We should create a `ValidValuesSet` for each data class's keywords (e.g. `EmailAddressKeywordsSet`), add each keyword as a `ValidValueDefinition` member, and link the set to the `DataClass`.
* **Relationship Mapping**: In Egeria's OMRS type system, because both `DataClass` and `ValidValuesSet` (via `ValidValueDefinition`) inherit from the base `DataValueSpecification` type, they are connected natively. We can associate the `ValidValuesSet` to the `DataClass` using Egeria's link/attach relationships (such as those managed under the OMAS `/data-value-specification-definition` attach endpoint).
* **Wish List Item**: Provide built-in templates or governance patterns in Egeria/pyegeria to easily associate a `ValidValuesSet` as a classifier matching rule for a `DataClass`.
* **Component Affected**: **pyegeria** (adding relationship builder helpers) & **Egeria-Advisor** (defining/executing plans to provision reference value sets, no Egeria core changes required).

### Semantic Assignment Propagation via Lineage (Area 3 & Area 5)
* **Observation**: Purely lexical column-name heuristic matching is fragile (e.g. `address` could refer to `IP Address` or `Delivery Address`, which have different classifications). A more robust mechanism is to leverage [0370 Semantic Assignment](https://egeria-project.org/types/3/0370-Semantic-Assignment/) linking base columns to glossary terms (e.g., `GlossaryTerm::DeliveryAddress`), which are in turn classified/mapped to a `DataClass`.
* **Alignment Resolution**: Rather than re-classifying derived view columns from scratch via heuristics, the surveyor uses static column lineage to trace back to physical source columns. If a source column has a `SemanticAssignment` to a glossary term, the surveyor automatically propagates this logical relationship forward and publishes a new `SemanticAssignment` or `DataClassAnnotation` for the derived view column.
* **Benefit**: This shifts the heavy lifting (which requires data profiling or manual steward assignment) to the base/physical schema level. Once defined there, static column lineage scales the classification transitively through all view layers.
* **Wish List Item**: Define a standard Egeria Governance Action Service pattern that propagates semantic assignments and data classifications transitively along column-level lineage relationships.
* **Component Affected**: **Egeria-Advisor** (orchestrating plan workflows) & **pyegeria** (handling transitive link propagation client-side, Egeria changes deferred).

### Decoupled Annotation/Analytic Types Library
* **Observation**: Currently, annotations are statically mapped within specific resource-type code adapters (e.g. `re_analysis_step_info` in `survey_definition_adapter.py`). decoulping the library of annotation types from resource/technology types allows reuse across different systems (e.g. databases, file systems, API endpoints).
* **Alignment Resolution**: Create a decoupled, schema-driven registry (`annotation_registry.json`) detailing the schema, description, and Egeria mappings for standard annotation types (e.g. `SchemaAnalysis`, `RelationshipLineage`, `QualityComplexity`, `DataClassPII`, `GovernanceActionWarning`). 
* **Shared Usage**:
  * **Egeria-Advisor**: Uses this registry as a library when authoring Survey Definitions (giving users tooltips and metric choices).
  * **Resource Explorer**: Uses this registry to validate incoming metadata and build explainability components in UI results tabs.
* **Component Affected**: **Combination** of **Egeria-Advisor** (UI builder / template engine) and **Resource Explorer** (run-time validation & results visualizer).

### Cataloging Connector Capabilities via Specification Properties (Area 6)
* **Observation**: When Egeria-Advisor authors Survey Definitions, it needs to know what steps are supported by our Survey Action Services, and what annotations they produce, without relying on hardcoded client-side listings.
* **Alignment Resolution**: Egeria's Open Discovery Framework (ODF) defines `SpecificationPropertyType` definitions that declare connector capabilities. We map:
  1. **Surveyor Steps** (e.g. `postgres_schema_and_stats`, `sql_analysis`) to Egeria's standard **`SupportedAnalysisStep`** specification properties.
  2. **Annotation Types** (e.g. `SchemaAnalysisAnnotation`, `DataClassAnnotation`) to Egeria's standard **`ProducedAnnotationType`** specification properties.
* **Usage**: When cataloging/registering our custom surveyor connector definitions in Egeria's Governance Engine configuration, we attach these specification property attributes. Egeria-Advisor can then dynamically query Egeria for available `SupportedAnalysisStep` and `ProducedAnnotationType` values on the network, removing the need for a hardcoded registry in the advisor client.
* **Component Affected**: **Combination** of **pyegeria** (exposing Valid Metadata OMAS getSpecificationPropertyTypes APIs) & **Egeria-Advisor** (dynamically discovering capability options, no Egeria core schema changes required).
