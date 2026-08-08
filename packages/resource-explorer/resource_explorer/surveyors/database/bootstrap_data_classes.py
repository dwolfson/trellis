# -*- coding: utf-8 -*-
"""Bootstrap script to register standard PII Data Classes and Valid Value reference sets in Egeria's catalog."""
from __future__ import annotations

import os
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

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
    platform_url = os.getenv("EGERIA_PLATFORM_URL")
    view_server = os.getenv("EGERIA_VIEW_SERVER", "view-server")
    user_id = os.getenv("EGERIA_USER", "steward")
    user_pwd = os.getenv("EGERIA_USER_PASSWORD", "steward")

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
        designer = DataDesigner(view_server, platform_url, user_id, user_pwd)
        designer.create_egeria_bearer_token(user_id, user_pwd)

        ref_manager = ReferenceDataManager(view_server, platform_url, user_id, user_pwd)
        ref_manager.create_egeria_bearer_token(user_id, user_pwd)
    except Exception as e:
        log.error(f"Failed to connect to Egeria: {e}")
        return 1

    created_count = 0
    skipped_count = 0

    for dc_spec in STANDARD_DATA_CLASSES:
        qualified_name = f"DataClass::{dc_spec['name']}"
        log.info(f"Checking if DataClass '{qualified_name}' exists...")
        
        data_class_guid = None
        try:
            data_class_guid = designer.get_guid_for_name(qualified_name)
        except Exception as e:
            log.debug(f"Lookup failed for '{qualified_name}': {e}")

        # 1. Create DataClass if it does not exist
        if not data_class_guid:
            log.info(f"Creating DataClass '{qualified_name}'...")
            body = {
                "class": "NewElementRequestBody",
                "properties": {
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
        set_guid = None
        try:
            set_guid = ref_manager.get_guid_for_name(set_qname)
        except Exception as e:
            log.debug(f"Lookup failed for ValidValuesSet '{set_qname}': {e}")

        if not set_guid:
            log.info(f"Creating ValidValuesSet '{set_qname}'...")
            set_body = {
                "class": "NewElementRequestBody",
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
            kw_guid = None
            try:
                kw_guid = ref_manager.get_guid_for_name(kw_qname)
            except Exception as e:
                log.debug(f"Lookup failed for ValidValueDefinition '{kw_qname}': {e}")

            if not kw_guid:
                log.info(f"Creating ValidValueDefinition '{kw_qname}'...")
                kw_body = {
                    "class": "NewElementRequestBody",
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

                # Link valid value definition as member of the ValidValuesSet
                log.info(f"Linking ValidValueDefinition '{kw}' to ValidValuesSet...")
                try:
                    ref_manager.link_valid_value_definition(vv_set_guid=set_guid, vv_member_guid=kw_guid)
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
