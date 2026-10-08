"""Is this element absent from Egeria? One shared, strict answer.

Three outcomes, and only the first lets a caller create something:

  absent      Egeria said there is no such element: pyegeria's `NO_ELEMENTS_FOUND` answer, a
              `PyegeriaNotFoundException`, or a `PyegeriaAPIException` whose `related_http_code` is 404.
  present     a populated answer.
  unreadable  everything else: unauthorised (401/403, even though that class subclasses the API
              exception), transport and timeout failures, validation errors, any other exception, text we do
              not recognise, an empty or missing answer. NEVER a reason to create or to forget a cached GUID.

It deliberately does not read exception TEXT: a GUID containing "404" inside a timeout message, or a "user
not found" error, must not read as a missing element (a duplicate blueprint would follow).
"""
from __future__ import annotations

ABSENT = "absent"
PRESENT = "present"
UNREADABLE = "unreadable"

#: pyegeria.core._globals.NO_ELEMENTS_FOUND, repeated so this module imports without pyegeria.
NO_ELEMENTS_FOUND = "No elements found"


def is_absent(result_or_exc) -> str:
    """'absent' | 'present' | 'unreadable' for a returned answer or a raised exception."""
    if isinstance(result_or_exc, BaseException):
        return _classify_exception(result_or_exc)
    if isinstance(result_or_exc, str):
        return ABSENT if result_or_exc.strip() == NO_ELEMENTS_FOUND else UNREADABLE
    if isinstance(result_or_exc, (dict, list, tuple)):
        return PRESENT if result_or_exc else UNREADABLE
    return UNREADABLE


def _classify_exception(exc: BaseException) -> str:
    try:
        from pyegeria.core._exceptions import (
            PyegeriaAPIException,
            PyegeriaNotFoundException,
            PyegeriaUnauthorizedException,
        )
    except ImportError:                                   # no pyegeria: nothing here can be a not-found
        return UNREADABLE
    if isinstance(exc, PyegeriaUnauthorizedException):    # before the API exception it subclasses
        return UNREADABLE
    if isinstance(exc, PyegeriaNotFoundException):
        return ABSENT
    if isinstance(exc, PyegeriaAPIException) and getattr(exc, "related_http_code", None) == 404:
        return ABSENT
    return UNREADABLE
