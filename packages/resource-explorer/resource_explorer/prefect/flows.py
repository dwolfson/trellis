"""Prefect Flow and Task definitions for Resource Explorer distributed surveying."""
from __future__ import annotations

import os
import json
from typing import Any
from prefect import flow, task
from resource_explorer.registry import ProjectRegistry
from resource_explorer.surveyors.survey_definition_executor import get_adapter


@task(name="Run Surveyor Step")
def run_surveyor_step_task(
    entity_type: str,
    slug: str,
    step_name: str,
    runner_kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Execute a single surveyor analysis step inside a Prefect task."""
    registry = ProjectRegistry()
    adapter = get_adapter(entity_type)
    if not adapter:
        raise ValueError(f"No resource type adapter registered for '{entity_type}'")

    entity = adapter.get_entity(registry, slug)
    if not entity:
        raise ValueError(f"Entity '{slug}' of type '{entity_type}' not found in registry")

    # Dynamic routing for pre-integrated workflow quality analyzers
    if step_name == "soda_data_quality":
        if entity_type != "database":
            raise ValueError("soda_data_quality is only supported for entity_type='database'")
        return run_soda_scan_task(
            db_type=entity.db_type,
            host=entity.host,
            port=entity.port,
            database_name=entity.database_name,
            db_user=entity.db_user,
            db_password=entity.db_password,
            sodacl_yaml=runner_kwargs.get("sodacl_yaml", ""),
        )
    elif step_name == "great_expectations_validation":
        if entity_type != "database":
            raise ValueError("great_expectations_validation is only supported for entity_type='database'")
        return run_gx_validation_task(
            db_type=entity.db_type,
            host=entity.host,
            port=entity.port,
            database_name=entity.database_name,
            db_user=entity.db_user,
            db_password=entity.db_password,
            table_name=runner_kwargs.get("table_name", ""),
            expectation_suite=runner_kwargs.get("expectation_suite", {}),
        )

    runner = adapter.re_analysis_steps.get(step_name)
    if not runner:
        raise ValueError(f"Analysis step '{step_name}' not supported for type '{entity_type}'")

    # Run the surveyor step callback
    result = runner(entity, registry, **runner_kwargs)
    return result or {}


@task(name="Soda Core Quality Scan")
def run_soda_scan_task(
    db_type: str,
    host: str,
    port: int,
    database_name: str,
    db_user: str,
    db_password: str,
    sodacl_yaml: str,
) -> dict[str, Any]:
    """Run Soda Core data quality checks on the target PostgreSQL database."""
    from soda.scan import Scan

    # Construct the configuration dictionary for the database
    config_yaml = f"""
data_source postgres:
  type: postgres
  host: {host}
  port: {port}
  username: {db_user}
  password: {db_password}
  database: {database_name}
  schema: public
"""

    scan = Scan()
    scan.set_data_source_name("postgres")
    scan.add_configuration_yaml_str(config_yaml)
    scan.add_sodacl_yaml_str(sodacl_yaml)

    # Execute the scan
    exit_code = scan.execute()
    results = scan.get_scan_results()

    return {
        "exit_code": exit_code,
        "results": results,
        "has_failures": scan.has_check_failures(),
        "has_warnings": scan.has_check_warnings(),
    }


@task(name="Great Expectations Validation")
def run_gx_validation_task(
    db_type: str,
    host: str,
    port: int,
    database_name: str,
    db_user: str,
    db_password: str,
    table_name: str,
    expectation_suite: dict[str, Any],
) -> dict[str, Any]:
    """Run Great Expectations validation checkpoints on a specific database table."""
    import pandas as pd
    import sqlalchemy
    import great_expectations as gx

    # Build connection string
    conn_str = f"postgresql://{db_user}:{db_password}@{host}:{port}/{database_name}"
    engine = sqlalchemy.create_engine(conn_str)

    # Read a sample batch of data
    df = pd.read_sql(f"SELECT * FROM {table_name} LIMIT 10000", engine)

    # Get GX context
    context = gx.get_context(mode="ephemeral")

    # Define an expectation suite
    suite_name = f"{table_name}_suite"
    suite = context.data_assistant.create_expectation_suite(suite_name) if hasattr(context, "data_assistant") else context.add_expectation_suite(suite_name)

    # In Great Expectations, we can convert expectation suite dict representation
    # and validate the Pandas DataFrame
    from great_expectations.dataset import PandasDataset
    dataset = PandasDataset(df, expectation_suite=expectation_suite)
    results = dataset.validate()

    return {
        "success": results.success,
        "statistics": results.statistics,
        "results": results.to_json_dict(),
    }


@flow(name="RE Survey Flow", persist_result=True)
def re_survey_flow(
    entity_type: str,
    slug: str,
    step_name: str,
    runner_kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Prefect orchestration flow managing surveyor step runs."""
    return run_surveyor_step_task(
        entity_type=entity_type,
        slug=slug,
        step_name=step_name,
        runner_kwargs=runner_kwargs,
    )
