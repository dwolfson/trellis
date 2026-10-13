# -*- coding: utf-8 -*-
"""Bootstrap script to register standard PII Data Classes and Valid Value reference sets in Egeria's catalog."""
from __future__ import annotations

import os
import sys
import logging

from resource_explorer.surveyors.survey_definition_reader import _as_guid
from resource_explorer.config import egeria_platform_url, egeria_view_server  # noqa: E402,F401

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

#: The type the keyword sets and keywords are created as, and looked up by. Egeria's Reference Data
#: view defaults its type to ReferenceDataValue, so a plain ValidValueDefinition is looked up TYPED.
VVD_TYPE = "ValidValueDefinition"


class CouldNotCheck(RuntimeError):
    """An existence lookup raised. Never read as "absent": nothing is created on a failed check."""


def _existing_guid(client, qualified_name: str, type_name: str | None = None) -> str | None:
    """The element's GUID, None when Egeria answers that it holds none, `CouldNotCheck` when the
    lookup itself failed.

    Exact qualifiedName only. With `type_name`, the lookup is restricted to that type (a plain
    ValidValueDefinition is not resolved through the Reference Data view's default type).
    pyegeria's "No elements found" miss sentinel goes through `_as_guid` (a truthy string, not a
    GUID); a raise (including pyegeria's "Multiple elements found") is `CouldNotCheck`.
    """
    try:
        if type_name:
            raw = client.get_guid_for_name(qualified_name, property_name=["qualifiedName"],
                                           type_name=type_name)
        else:
            raw = client.get_guid_for_name(qualified_name)
    except Exception as exc:  # noqa: BLE001 - re-raised as the one "could not check" outcome
        raise CouldNotCheck(f"could not check '{qualified_name}': {exc}") from exc
    return _as_guid(raw)


# Standard PII Data Classes and keywords to register
STANDARD_DATA_CLASSES = [
    {
        "name": "EmailAddress",
        "displayName": "Email Address",
        "description": "Electronic mail address identifier.",
        "dataPatterns": ["email", "email_address", "mail_addr", "emailaddr"],
    },
    {
        "name": "PhoneNumber",
        "displayName": "Phone Number",
        "description": "Telephone contact number.",
        "dataPatterns": ["phone", "phone_number", "telephone", "mobile", "tel_num"],
    },
    {
        "name": "SocialSecurityNumber",
        "displayName": "Social Security Number",
        "description": "Government issued social security identification number.",
        "dataPatterns": ["ssn", "socialsec", "social_security", "ssn_num"],
    },
    {
        "name": "CreditCardNumber",
        "displayName": "Credit Card Number",
        "description": "Financial credit or debit card identifier.",
        "dataPatterns": ["creditcard", "credit_card", "cc_num", "card_number"],
    },
    {
        "name": "Password",
        "displayName": "Password",
        "description": "Credential or secret authentication passkey.",
        "dataPatterns": ["password", "passkey", "passwd", "pwd"],
    },
    {
        "name": "DateOfBirth",
        "displayName": "Date of Birth",
        "description": "Individual date or anniversary of birth.",
        "dataPatterns": ["dob", "dateofbirth", "birth_date", "birthdate"],
    },
]


def bootstrap_data_classes() -> int:
    platform_url = egeria_platform_url()
    view_server = egeria_view_server()

    if not platform_url:
        log.error("EGERIA_PLATFORM_URL environment variable is not set. Cannot connect to Egeria.")
        return 1

    try:
        from pyegeria.omvs.data_designer import DataDesigner
        from pyegeria.omvs.reference_data import ReferenceDataManager
    except ImportError:
        log.error("pyegeria is not installed. Please install it to run Egeria bootstraps.")
        return 1

    try:
        log.info(f"Connecting to Egeria View Server '{view_server}' at {platform_url}...")
        from resource_explorer.egeria_clients import Daemon, DaemonReason, egeria_client

        # A one-shot bootstrap of reference data: RE's daemon identity (Brief I), from the one
        # daemon loader — no longer EGERIA_USER/EGERIA_USER_PASSWORD with a "steward" default.
        clients = egeria_client(Daemon(DaemonReason.BOOTSTRAP), purpose="bootstrap data classes",
                                view_server=view_server, platform_url=platform_url)
        designer = clients.of(DataDesigner)
        ref_manager = clients.of(ReferenceDataManager)
    except Exception as e:
        log.error(f"Failed to connect to Egeria: {e}")
        return 1

    created_count = 0
    skipped_count = 0

    for dc_spec in STANDARD_DATA_CLASSES:
        qualified_name = f"DataClass::{dc_spec['name']}"
        log.info(f"Checking if DataClass '{qualified_name}' exists...")
        
        # pyegeria's get_guid_for_name returns the literal string "No elements found" (not
        # None/""/an exception) on a miss; _existing_guid rejects it. A lookup that RAISES is
        # "could not check": stop, never create (the 6.2.2 audit's finding).
        try:
            data_class_guid = _existing_guid(designer, qualified_name)
        except CouldNotCheck as e:
            log.error(f"{e}. Nothing created for it; stopping.")
            return 1

        # 1. Create DataClass if it does not exist
        if not data_class_guid:
            log.info(f"Creating DataClass '{qualified_name}'...")
            body = {
                "class": "NewElementRequestBody",
                "isOwnAnchor": True,
                "properties": {
                    # Live-verified 2026-09-22: omitting "class" here (as this
                    # body did until now) makes Egeria reject the create with
                    # a 400 CLIENT_ERROR_400 — pyegeria's
                    # `_async_create_element_body_request` needs
                    # `properties.class` to resolve the DTO shape.
                    # `egeria_reference_catalog.build_proposed_data_class_body`
                    # already carried both this field and `isOwnAnchor`; this
                    # was the exact gap its own docstring names as "a bug
                    # this deliberately does not copy" — now fixed here too.
                    "class": "DataClassProperties",
                    "qualifiedName": qualified_name,
                    "displayName": dc_spec["displayName"],
                    "description": dc_spec["description"],
                    "dataPatterns": dc_spec["dataPatterns"]
                }
            }
            try:
                data_class_guid = designer.create_data_class(body)
                log.info(f"Successfully created DataClass '{qualified_name}' (GUID: {data_class_guid})")
                created_count += 1
            except Exception as e:
                log.error(f"Failed to create DataClass '{qualified_name}': {e}")
                return 1
        else:
            log.info(f"DataClass '{qualified_name}' already exists (GUID: {data_class_guid}).")
            skipped_count += 1

        # 2. Check and Create ValidValuesSet for match keywords
        set_qname = f"ValidValuesSet::{dc_spec['name']}Keywords"
        try:
            set_guid = _existing_guid(ref_manager, set_qname, type_name=VVD_TYPE)
        except CouldNotCheck as e:
            log.error(f"{e}. Nothing created for it; stopping.")
            return 1

        if not set_guid:
            log.info(f"Creating ValidValuesSet '{set_qname}'...")
            set_body = {
                "class": "NewElementRequestBody",
                "isOwnAnchor": True,
                "properties": {
                    "class": "ValidValueDefinitionProperties",
                    "qualifiedName": set_qname,
                    "displayName": f"{dc_spec['displayName']} Keywords",
                    "description": f"Valid keyword list to match {dc_spec['displayName']} columns.",
                    "dataType": "string",
                    "scope": "ResourceExplorer"
                }
            }
            try:
                set_guid = ref_manager.create_valid_value_definition(set_body)
                log.info(f"Successfully created ValidValuesSet '{set_qname}' (GUID: {set_guid})")
            except Exception as e:
                log.error(f"Failed to create ValidValuesSet '{set_qname}': {e}")
                return 1
        else:
            log.info(f"ValidValuesSet '{set_qname}' already exists (GUID: {set_guid}).")

        # 3. Create individual keyword ValidValueDefinitions and link them
        for kw in dc_spec["dataPatterns"]:
            kw_qname = f"ValidValueDefinition::{dc_spec['name']}Keyword::{kw}"
            try:
                kw_guid = _existing_guid(ref_manager, kw_qname, type_name=VVD_TYPE)
            except CouldNotCheck as e:
                log.error(f"{e}. Nothing created for it; stopping.")
                return 1

            if not kw_guid:
                log.info(f"Creating ValidValueDefinition '{kw_qname}'...")
                kw_body = {
                    "class": "NewElementRequestBody",
                    "isOwnAnchor": True,
                    "properties": {
                        "class": "ValidValueDefinitionProperties",
                        "qualifiedName": kw_qname,
                        "displayName": kw,
                        "preferredValue": kw,
                        "dataType": "string",
                        "scope": "ResourceExplorer"
                    }
                }
                try:
                    kw_guid = ref_manager.create_valid_value_definition(kw_body)
                    log.info(f"Successfully created ValidValueDefinition '{kw_qname}' (GUID: {kw_guid})")
                except Exception as e:
                    log.error(f"Failed to create ValidValueDefinition '{kw_qname}': {e}")
                    return 1

                # Link valid value definition as member of the ValidValuesSet.
                # An explicit body, not the no-body call this used to make —
                # egeria_reference_catalog.py's publish_proposed_valid_value_set
                # docstring already named this exact gap ("makes pyegeria
                # synthesise one and POST it un-serialised — a live bug this
                # does not copy"); fixed here to match that module's body shape.
                log.info(f"Linking ValidValueDefinition '{kw}' to ValidValuesSet...")
                try:
                    ref_manager.link_valid_value_definition(
                        set_guid, kw_guid,
                        body={
                            "class": "NewRelationshipRequestBody",
                            "properties": {
                                "class": "ValidValueMemberProperties",
                                "isDefaultValue": False,
                                "label": kw,
                                "description": "Standard keyword for this Data Class.",
                            },
                        },
                    )
                    log.info(f"Linked '{kw}' successfully.")
                except Exception as e:
                    log.error(f"Failed to link ValidValueDefinition to set: {e}")
                    return 1
            else:
                log.info(f"ValidValueDefinition '{kw_qname}' already exists (GUID: {kw_guid}).")

        # 4. Link the ValidValuesSet to the DataClass definition
        log.info(f"Linking ValidValuesSet to DataClass '{qualified_name}'...")
        try:
            designer.link_data_class_definition(data_definition_guid=set_guid, data_class_guid=data_class_guid)
            log.info("Linked ValidValuesSet to DataClass successfully.")
        except Exception as e:
            # Catching duplicate link exception gracefully, as OMRS throws error if relationship already exists
            log.info(f"Relationship link already exists or skipped: {e}")

    log.info(f"Bootstrap complete. Created Data Classes: {created_count}, Skipped: {skipped_count}.")
    return 0


if __name__ == "__main__":
    sys.exit(bootstrap_data_classes())
