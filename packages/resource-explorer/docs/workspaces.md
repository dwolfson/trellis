# Egeria Workspaces — component reference notes

**Status:** hand-authored reference outline describing runtime and deployment
components. Sibling to `egeria.md` and `trellis.md`. **Not the scoring fixture** — the pre-registered
ground-truth partitions used to score architecture recovery live in
`tests/fixtures/architecture-ground-truth/` and are richer; these three are
descriptive notes, and the two sets deliberately differ.

## egeria-workspaces

## Runtime Components

### Egeria QuickStart - a preconfigured sample environment 
#### quickstart-egeria-main
- egeria-platform which is a single java runtime running several egeria servers (not standalone processes)
#### quickstart-egeria-watchdog

#### quickstart-jupyter-work-full
- jupyter server
#### quickstart-web-server
- apache web server
#### quickstart-pyegeria-web
- pyegeriaWebHandler is a complex python module using FastAPI to support both MCP commands and Egeria Portal and can be configured to run in local mode or demo mode.
  - The portal provides many single page applications over egeria data and services written in javascript with backends in python
  - MCP provides services both to execute reports and Dr.Egeria Commands
#### quickstart-my-profile
- A textual application that allows users to manage their environment

#### obsidian-quickstart
- An obsidian client configured with a vault over the Coco Workbooks - can author and issue Dr.Egeria mcp calls.


### Egeria Freshstart - an unconfigured egeria environment ready for customization
#### freshstart-egeria-main
- egeria-platform which is a single java runtime running several egeria servers (not standalone processes)

#### freshstart-jupyter-work-full
- jupyter server
#### freshstart-web-server
- apache web server
#### freshstart-pyegeria-web
- pyegeriaWebHandler is a complex python module supporting both MCP commands and Egeria Portal - nothing pre-configured.
  - The portal provides many single page applications over egeria data and services
  - MCP provides services both to execute reports and Dr.Egeria Commands

### Shared Infra
#### egeria-shared-kafka

#### egeria-shared-kroki
helper for mermaid graphs
#### egeria-shared-kroki-mermaid
helper for mermaid graphs
#### egeria-shared-openlineage-proxy-backend
common proxy supporting openlineage integration
#### egeria-shared-postgres
A pgvector enhanced postgres supporting all egeria-workspaces runtimes.

### Optional Runtimes
#### Airflow & Marquez - used for demonstrating Open Lineage and other metadata integrations.
#### Dagster - used for orchestrating pipelines and metadata harvesting with Egeria and OpenLineage.
#### Prefect - used for workflow automation and Egeria catalog integrations.
#### Apache Atlas - an Atlas/Hadoop/Hive stack for demonstrating Egeria's integration with Apache Atlas.
#### MLflow - a machine learning lifecycle tool, with a MinIO artifact store, for experimenting with Egeria integrations.
#### Milvus - a vector database used in AI workloads.
#### DuckDB - a federation server used for querying across multiple data sources like Postgres, S3, and Iceberg.
#### Superset—an analytics and reporting dashboard that we use to present Egeria survey results.
#### Unity Catalog—The Open Source version of Unity Catalog—we use for demonstrating Egeria's integration with other catalogs.
  * Two deployments - one using Postgres and one native.
#### Ollama - a local LLM runtime, for experimenting with local model inference alongside Egeria (no dedicated README yet).
#### Deltalake-Spark - a data lake framework for storing and processing data - this is a small sandbox configuration but includes
        other components that may be useful for additional experiments such as:
  * Spark - a distributed computing framework for processing large datasets
  * Delta Lake - a storage layer for Apache Spark that provides ACID transactions, scalable metadata handling, and more
  * Minio - an S3 compatible object store
  * Hive metastore - a metadata store for managing tables and databases


### coco-workbooks
Samples and Tutorials written in Jupyter and Dr.Egeria

### exchange-freshstart
Shared folders across freshstart ecosystem

### exchange-quickstart
Shared folders across quickstart ecosystem

### obsidian-plugins
This is shared source for the dr egeria obsidian plug-ins

### portal-docs
Documentation on the environment in general and the Portal apps specifically - launched from the portal

### runtime-volumes
Local runtime state maintained outside of the containers for the different runtimes

### templates
Dr.Egeria template files used by many of the components

### work
This is an unmanaged area for local user work

### workboks & workspaces - will be deprecated shortly



