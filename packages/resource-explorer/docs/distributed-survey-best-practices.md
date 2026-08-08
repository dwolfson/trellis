# Distributed Metadata Ingestion: Comparative Analysis & Human-in-the-Loop Best Practices

**Date:** 2026-07-14
**Authors:** Claude, Dan Wolfson
**Status:** Architecture Design Note

This document expands on the distributed orchestration proposal by comparing Resource Explorer's (RE) architecture with other metadata tools (e.g., DataHub, OpenMetadata), defining industry best practices, and proposing a framework for folding human expertise into technical metadata collection.

---

## 1. Comparing Orchestration Models: DataHub, OpenMetadata, and Egeria

How do other modern metadata platforms handle distributed, estate-wide ingestion and surveying?

```mermaid
graph TD
    subgraph DataHub Model (Push/Pull Recipes)
        DH_UI[DataHub Web UI] -->|Schedule| DH_Airflow[Managed Airflow]
        DH_Airflow -->|Run Recipe| DH_Ingest[acryl-datahub Python CLI]
        DH_Ingest -->|Pull| Sources[Database / S3 / Kafka]
        DH_Ingest -->|Push MCEs| DH_GMS[DataHub GMS REST / Kafka]
    end

    subgraph Egeria + RE Target Model (Active Governance)
        RE_UI[RE UI / A2A] -->|Trigger / Def| RE_Exec[RE Survey Executor]
        RE_Exec -->|1. Resolve Target/Credentials| Egeria[(Egeria OMAS)]
        RE_Exec -->|2. Dispatch task| Ext_Orch[Workflow Engine <br> Prefect / Airflow]
        Ext_Orch -->|3. Run Survey| Edge_Worker[Local Surveyor Agent]
        Edge_Worker -->|4. Push Annotations| Egeria
        Egeria -->|5. Open ToDo / RFA| Steward_UI[Enrichment UI]
    end
```

### 1.1 DataHub Ingestion Architecture
* **Ingestion Core:** DataHub uses a modular, recipe-driven Python ingestion package (`acryl-datahub`). A "recipe" is a YAML file specifying `source` (e.g., Snowflake, Postgres), `transformers` (e.g., regex classification, ownership mapping), and `sink` (DataHub GMS REST endpoint or Kafka).
* **Orchestration:** DataHub supports two modes:
  1. **Self-hosted Orchestration:** Users run the ingestion script in their own Airflow, Prefect, or Cron environments.
  2. **Managed Ingestion:** The DataHub UI allows users to schedule ingestion. Under the hood, DataHub provisions and runs these pipelines on a managed **Apache Airflow** instance via REST API.
* **Limitations vs. Egeria:** DataHub is primarily a passive repository of metadata. It lacks a native workflow engine for automated remediation, governance action processes, or stateful guards/completion policies.

### 1.2 OpenMetadata Ingestion Architecture
* **Ingestion Core:** OpenMetadata also uses a Python-based ingestion framework. 
* **Orchestration:** OpenMetadata has a hard dependency on **Apache Airflow** for its pipeline scheduling. The platform bundles an Airflow instance and dynamically writes DAG files based on configuration entered in the OpenMetadata UI.
* **Limitations:** The strict dependency on Airflow makes it heavyweight and difficult to deploy in serverless or highly constrained edge environments.

---

## 2. Ingestion & Orchestration Best Practices

To architect a resilient, secure surveying layer, RE should adopt these industry standards:

1. **Push-Based Metadata Architecture (Edge-Friendly):**
   * *Problem:* A central server cannot connect to databases behind private VPCs or firewalls.
   * *Best Practice:* Deploy lightweight, stateless workers locally near the assets (e.g., Prefect remote workers). These workers pull execution parameters, run the scan, and *push* structured metadata (no raw data) to Egeria/RE over HTTPS.
2. **Metadata Security & Data Privacy (Anonymization):**
   * *Best Practice:* Local surveyors must never send raw rows or sensitive data upstream. Tabular profiles (null counts, histograms, data types) must be summarized and hashed locally.
3. **Declarative Recipes / Specs (Decoupled Execution):**
   * *Best Practice:* Survey definitions (Dr.Egeria or YAML recipes) should be engine-agnostic. The orchestrator (e.g., Prefect) should simply execute the spec; the spec itself should not contain orchestration code.
4. **Stateful Delta Surveying:**
   * *Best Practice:* Avoid running deep scans on every execution. Check database modification timestamps or file-hash differentials first, and only trigger deep profiling on modified tables or folders.

---

## 3. Human-in-the-Loop: Folding in Context & Meaning

Technical analysis only captures *structure* (schemas, counts, types). True governance requires *context* (business meaning, ownership, data lineage, classification). 

We can fold human expertise into Resource Explorer through three key mechanisms:

```
[Technical Survey] 
       │
       ▼ (Discovers anomaly / schema change)
[Create RFA / Egeria ToDo]
       │
       ▼ (Assigned to Steward)
[Enrichment UI / LLM Suggestion] ──(Human Approves/Edits)──► [Egeria Asset Enrichment]
```

### 3.1 The RFA (Request for Action) Lifecycle
When an automated survey encounters an anomaly or undocumented asset, it should generate a `RequestForAction` (Egeria `ToDo` element):
* **Technical Trigger:** A survey detects a column named `usr_ssn` containing 9-digit integers that is not classified, or a database server with no assigned owner.
* **Human Action:** The steward is notified of the `ToDo` and prompted to resolve it.
* **Resolution:** The human provides the missing context (e.g., links a glossary term, confirms the owner, or updates the data classification).

### 3.2 AI-Augmented Human Enrichment (The Enrichment Intent)
Stewards should not have to write documentation or glossary mappings from scratch. RE can use its RAG capabilities to recommend enrichment properties:
* **The Flow:**
  1. Human opens the **Enrichment** panel for an asset with an open RFA.
  2. RE's LLM reads the technical metadata (table names, schemas, column descriptions, and profiling histograms).
  3. The LLM prompts the user: *"Based on naming patterns and column distribution, this table appears to contain Credit Card Details. Would you like to tag this as 'PII-PCI' and map it to the 'Payment Information' glossary term?"*
  4. The human reviews, modifies, and clicks **Approve**, writing the classifications directly to Egeria.

### 3.3 Active Governance Feedback Loops
Human enrichment should dynamically alter future technical surveys.
* **Example:** If a human classifies a database table as "Highly Restricted/PCI", the next automated survey run should read this classification from Egeria and dynamically adjust its execution profile (e.g., skipping data profiling and row sampling to prevent data leakage, or enabling strict audit logging on the survey connection).

---

## 4. Enterprise Case Studies: Regulated Industries (Banking, Insurance, Healthcare)

Highly regulated environments handle distributed surveying under strict security constraints:

### 4.1 Air-Gapped and Zone-Specific Ingestion (Zero-Trust Networks)
* **The Architecture:** Financial institutions and healthcare providers enforce strict segmentations (e.g., separating PCI-DSS zones, HIPAA enclaves, and public-facing subnets). Centralized pull-based catalogs are rejected. 
* **The Solution:** They deploy zone-specific, stateless agent containers (like Collibra Edge or Alation Agent) inside each enclave. These agents run locally and push metadata up via one-way HTTPS proxies to the central governance catalog. Under no circumstances can the central system initiate a network connection into the secure enclave.

### 4.2 Local Data Minimization & Privacy Gates
* **The Architecture:** In Healthcare (HIPAA) and Banking (GDPR/Basel III), raw data cannot cross geographic or logical boundaries.
* **The Solution:** Local edge workers run PII scanners (e.g., scanning for national identifiers, patient IDs, or credit card patterns) and perform **differential privacy profiling** locally. The agent throws away value samples and only sends classification tags (e.g., `has_pii: true`) and column cardinalities/null-rates upstream.

### 4.3 Separation of Duties & Audited Approvals
* **The Architecture:** Regulated enterprises separate technical database administration from business metadata stewardship.
* **The Solution:** When technical surveys detect schema modifications, these are staged in a "pending approval" state. Changes are not published directly to the production catalog until a designated Data Steward approves the RFA or Egeria `ToDo` task, creating a clear audit trail of metadata custody.

---

## 5. Enterprise Case Studies: Big Tech (Google, Netflix, Uber, Airbnb)

Big Tech addresses metadata at massive scale (exabytes, thousands of daily schema changes, decentralized teams):

### 5.1 Decentralized Ingestion & Data Mesh
* **The Architecture:** Manual curation by centralized stewards does not scale. 
* **The Solution:** Big Tech adopts a "Data Mesh" model. Metadata is treated as a product owned by the software team that produces the data. Ingestion and cataloging schemas are defined alongside code in Git repositories (e.g., using Protobuf or JSON schema specs). When a service is deployed, its CI/CD pipeline pushes the metadata specs to a central catalog (like Netflix's Metacat or Google's Dataplex).

### 5.2 Query Log Parsing for Automated Lineage
* **The Architecture:** Manually tracking lineage across thousands of datasets is impossible.
* **The Solution:** Instead of surveying database tables to map relationships, they run automated SQL parser engines over database query history logs. By parsing `SELECT INTO` and `JOIN` operations from query logs, the catalog dynamically reconstructs data lineage charts without querying the tables themselves.

### 5.3 Social Signals & Algorithmic Relevance
* **The Architecture:** Finding the right database among millions of tables is a major discovery hurdle.
* **The Solution:** Big Tech catalogs (e.g., Airbnb's Dataportal or Uber's DataBook) analyze usage telemetry to rank assets. They track search popularity, query frequency, Slack mentions, and which pipelines read the asset to compute a "relevance score." This helps users quickly discover high-trust "gold" datasets and avoid deprecated tables.

---

## 6. AI-Era Curation: Sourcing, Profiling, and Cataloging LLM Training Data

For front-tier AI companies (OpenAI, Anthropic, Google DeepMind, Meta), metadata cataloging is a critical engineering prerequisite to model pre-training, fine-tuning, and RAG:

### 6.1 Ray/Spark Data Lake Pipelines for Ingestion
* **The Challenge:** Ingesting and cleaning multi-petabyte datasets spanning Common Crawl dumps, book libraries, scientific papers, code repos, and image/video archives.
* **The Solution:** AI companies build massive, distributed ETL pipelines (running on **Ray** or **Apache Spark** across thousands of CPU nodes) to run cleaning heuristics. They do not just index schemas; they index **token counts, document length distributions, and language composition**.

### 6.2 Semantic Profiling & Quality Filtering
* **The Challenge:** Filtering out low-quality web spam, toxicity, and duplicate documents that degrade model performance.
* **The Solution:** They profile data at the semantic and statistical level:
  * **MinHash/LSH Deduplication:** Local workers cluster document signatures to filter out near-identical boilerplate text.
  * **Perplexity Profiling:** They run small, fast reference language models over incoming text. Documents with unusually high perplexity (nonsense) or unusually low perplexity (highly repetitive text) are flagged and filtered.
  * **Embedding Centroids:** They compute dense vector embeddings for documents and index them in vector stores. Researchers query this metadata catalog by semantic clusters to ensure the training run has a balanced, diverse mix of domains (e.g., code, math, history, creative writing).

### 6.3 Human-in-the-Loop SFT and RLHF Tracking
* **The Challenge:** Managing high-quality instruction-tuning datasets (Supervised Fine-Tuning) and human preference data (RLHF/RLAIF) containing thousands of multi-turn conversation trees.
* **The Solution:** Their metadata catalogs track human annotation lineages. Every prompt-response pair is logged with:
  * Annotator demographics/ID and quality scores.
  * Model version that generated the response.
  * Human ranking scores, safety classification flags, and prompt diversity tags.
  * License permissions and opt-out tracking (ensuring no copyrighted/restricted data goes into the training buffer).

### 6.4 Synthetic Data Orchestration & Lineage
* **The Challenge:** Managing and profiling vast amounts of AI-generated synthetic data (e.g., code execution traces, chain-of-thought reasonings) to avoid model collapse.
* **The Solution:** They model synthetic data generation as a multi-step data pipeline. The metadata catalog stores the **prompt template, the generation model, the verification tool output** (e.g., did the generated python script execute and pass unit tests?), and the filtering thresholds. This allows researchers to audit which synthetic runs successfully enriched the model's training catalog.

---

## 7. How AI Labs Locate and Evaluate Potential Training Data

Before running multi-million-dollar ingestion pipelines, AI labs must first **discover** potential data sources and **evaluate** their suitability. They approach this through an exploratory, tiered discovery funnel:

```
[Broad Scouting & Crawling] 
       │
       ▼ (Discovers web domains, registries, partner enclaves)
[Lightweight Sourcing Assessment] (Filters by size, language, licensing, and FastText score)
       │
       ▼ (Staged for Pilot Sampling)
[Pilot Profiling & Clustering] (Analyzes semantic centroids, perplexity, and PII density)
       │
       ▼ (Deemed suitable)
[Full Scale Ingestion & Clean]
```

### 7.1 Automated Discovery & Crawling Hubs (Broad Scouting)
* **The Process:** AI labs run broad web-scraping agents (or analyze indexed web domains like Common Crawl) to find potential content hubs. They also monitor public dataset registries (Hugging Face, Kaggle, OpenML, Zenodo, and government portals) and scraping hubs.
* **Crawl-Edge Filtering:** To avoid the massive storage and compute costs of downloading junk, web crawlers run lightweight, real-time classifier models (like FastText) at the crawl boundary. As a page is fetched, it is classified on the fly: *"Is this actual natural language/code, or is it navigation links/SEO spam?"* If it is junk, it is discarded immediately.

### 7.2 Lightweight Sourcing Assessment (Suitability Gates)
Once a potential repository, web domain, or partnership dataset is located, it goes through a metadata suitability filter:
* **Licensing & Policy Audit:** Automated scripts scan for `robots.txt` rules, `ai.txt` files, and HTML metadata tags (such as `noai`/`noimage`). The source URL is cross-referenced against a legal compliance blacklist. If a domain is marked as restricted, it is skipped.
* **Size & Language Feasibility:** They calculate the estimated volume (tokens/gigabytes) and language distribution of the source. If a database contains mostly duplicate or low-density text, the source is rejected before ingestion.

### 7.3 Pilot Profiling & Semantic Clustering
For private data partnerships (e.g., licensing stack archives, forum histories, or perimeter libraries), AI labs run a **pilot profile** using lightweight scouting agents:
* **Random Sampling:** Instead of ingesting the whole dataset, they download a random 0.1% to 1% subset.
* **Semantic Analysis:** They generate embeddings for the pilot sample and map them onto their existing dataset topology. This tells researchers: *"Does this dataset cover empty areas in our knowledge graph (e.g., specialized medical terminology, rare coding languages), or does it duplicate what we already have?"*
* **PII & Toxicity Density Checks:** They run a pilot scanner to measure the density of personal identifiers (SSNs, phone numbers, emails, addresses) and toxic content. If the density of unsafe content is above a threshold, the source is classified as "unsuitable" or marked for expensive pre-filtering.

---

## 8. Enterprise Data Discovery: Locating and Qualifying Assets in Chaotic Estates

In large, legacy enterprises (Banking, Retail, Manufacturing), data is highly fragmented across on-prem mainframes, cloud-native lakes, department-specific databases ("shadow IT"), and unstructured network file shares. To locate and qualify these assets, enterprises employ an automated, phased discovery pipeline:

```
[Network & Cloud Auto-Discovery]
       │
       ▼ (Identifies open ports, S3 buckets, server nodes)
[Lightweight Connection & Schema Sweep] (Reads table counts, schemas, and usage activity)
       │
       ▼ (Filters out temporary, duplicate, or test data)
[Staged Metadata Registry] (Enters catalog as 'Unclassified Candidate')
       │
       ▼ (PII scans, ownership attribution, compliance audits)
[Governance Suitability Gate] (Assigns classification and owner; promotes to 'Certified Catalog')
```

### 8.1 Active Network and Cloud Auto-Discovery (Locating)
* **On-Prem Port & Server Scanning:** Security and platform teams run automated network scanners (e.g., Qualys, Shodan, or custom network agents) across IP ranges to detect open database ports (e.g., `5432` for Postgres, `1521` for Oracle, `1433` for MSSQL, `445` for SMB shares).
* **Cloud Resource Listeners:** In cloud environments, they deploy event-driven serverless listeners (e.g., AWS Systems Manager, Azure Resource Graph, GCP Asset Inventory) that trigger as soon as a database instance (RDS), object store (S3/Blob), or data warehouse is spun up.

### 8.2 Sourcing and Quality Filtering (The Intake Funnel)
Not everything discovered on a network is suitable for cataloging. Scanners run lightweight metadata checks to separate production data from noise:
* **Discarding Test and Temp Data:** System tools inspect table names, schemas, and sizes. Tables carrying names like `test_`, `_temp`, `backup_old`, or containing fewer than 10 rows are flagged as scratchpads. These are excluded from the main catalog to prevent clutter.
* **Detecting Orphaned Assets:** The scanner queries database activity logs and connection statistics. If a database has had zero active connections or query history in the last 180 days, it is tagged as "Orphaned/Inactive" and queued for archiving rather than cataloging.

### 8.3 Staging and the Governance Suitability Gate
Once a data asset is deemed a viable candidate, it is placed in a **Staging Registry** (similar to RE's local cache) rather than being published directly to the enterprise catalog of record (like Egeria):
* **PII & Risk Classification:** Automated scanners run pattern matching and machine learning classifiers (e.g., Microsoft Purview or BigID) over a small sample of columns. If the scanner detects sensitive data, the asset is tagged as "Restricted" and isolated.
* **Ownership Attribution & Metadata Enrichment:** The staging system checks query history and creation logs to identify the most active user or the creator. It then issues an automated `ToDo` task (Request for Action) asking them to claim ownership, specify the business purpose, and define the data lifecycle.
* **Certification & Promotion:** Once ownership is confirmed, licensing is cleared, and PII constraints are registered, the asset is promoted from the Staging Registry to Egeria's **Certified Catalog**, making it discoverable and suitable for use by enterprise analysts or AI pipelines.

---

## 9. The AI & Human Collaboration Matrix

Data governance in a chaotic estate cannot rely on automated AI or manual human effort alone. It requires a defined allocation of labor across four layers of intelligence:

| Technique | Core Capability | Role in the Ingestion Funnel | Collaboration Pattern |
| :--- | :--- | :--- | :--- |
| **Deterministic Heuristics** | Regex, SQL parsers, file signature sniffing, hash calculations. | **Intake & Filtering:** Discarding scratch files, temp tables, and dead schemas. | **Automated:** Runs autonomously at the crawl edge. No human review. |
| **Classical ML & Stats** | Clustering, Outlier Detection (Z-score), TF-IDF, Random Forests. | **Anomaly Detection:** Outlining schema drift, identifying changes in connection/query volumes, clustering directories. | **Steward Alerted:** Highlights statistical anomalies for human inspection. |
| **Tabular Foundation Models** | Pre-trained tabular network inference (e.g., TabPFN, FT-Transformer). | **Zero-Shot Column Profiling:** Predicting semantic types (SSN, credit card, patient ID) based on actual data value distributions and ranges. | **Steward Suggestion:** Presents predicted tags to the steward in the Enrichment phase. |
| **Large Language Models (LLMs)** | Generative semantic reasoning, schema summarization, doc-parsing. | **Semantic Synthesis:** Reading unstructured documentation files to find API endpoints, summarizing schemas, suggesting glossary links. | **Interactive Copilot:** Steward approves, edits, or rejects the generated mappings in the Enrichment UI. |
| **Human Judgement** | Policy design, architectural alignment, business certification, legal audits. | **Certified Promotion:** Validating owner assignments, resolving complex classification conflicts, and taking formal stewardship accountability. | **Human-Only:** The final decision gate before promoting staged assets to Egeria's Certified Catalog. |

---

## 10. Temporal Visual Analysis & Human Judgement

To exercise sound judgment, human stewards must analyze how data assets behave **over time**, rather than just inspecting single static snapshots. 

### 10.1 Egeria's Native Temporal Model
Egeria provides a robust foundation for temporal metadata:
* **System Time (Transaction Time):** Records when metadata was actually written to the repository. This allows **As-Of Queries** (e.g., *"What did our schema catalog look like on March 15th, 2026?"*).
* **Effective Time (Validity Time):** Records when a metadata relationship, classification, or glossary assignment is active in the business domain. This allows future-dating or retro-dating policies.

### 10.2 Visualizing Metadata Trends in Resource Explorer
RE exposes Egeria's temporal capabilities through interactive visual charts to aid human assessment:
* **Schema Drift Visualizers:** Visual timeline graphs mapping schema modifications (added columns, renamed tables, changed data types). This alerts stewards to unexpected, unapproved API or DB structure shifts.
* **Asset Growth and Activity Diffs:** Plots demonstrating database row-count growth, transaction log write frequencies, and file-share volumes. If a database is growing exponentially but has zero queries, it flags a structural storage risk.
* **Governance Lifecycle Timelines:** Charts tracking the average duration an asset spends in the staging funnel (`Unclassified` $\rightarrow$ `Enriched` $\rightarrow$ `Certified`). This helps identify bottlenecks where stewards need automated AI suggestions to speed up cataloging.




