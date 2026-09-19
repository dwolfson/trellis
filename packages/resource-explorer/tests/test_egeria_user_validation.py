"""Regression test for the 2026-09-19 incident: two registered databases
(`localhost_docker_coco_ods`, `localhost_docker_coco_pharma`) had
`egeria_user` stored as `"peter profile"` — a display name typed into the
field instead of a technical Egeria login ID. Nothing caught this at
registration time, so it surfaced later as a cryptic pyegeria
`VALIDATION_ERROR_1` deep inside a publish call instead of an immediate,
actionable error at the point the bad value was actually entered.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from resource_explorer.web.routes._validation import validate_egeria_user


class TestValidateEgeriaUser:
    def test_a_display_name_with_a_space_is_rejected(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_egeria_user("peter profile")
        assert exc_info.value.status_code == 400
        assert "peter profile" in exc_info.value.detail
        assert "erinoverview" in exc_info.value.detail  # names a real example

    def test_a_plain_technical_id_is_accepted(self):
        validate_egeria_user("erinoverview")  # must not raise

    def test_empty_string_is_accepted_as_use_the_default(self):
        validate_egeria_user("")  # must not raise — means "use configured default"

    def test_a_slash_is_also_rejected(self):
        with pytest.raises(HTTPException):
            validate_egeria_user("peter/profile")

    def test_the_field_name_is_reported_when_given(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_egeria_user("bad user", field_name="egeria_user (filesystem)")
        assert "egeria_user (filesystem)" in exc_info.value.detail
