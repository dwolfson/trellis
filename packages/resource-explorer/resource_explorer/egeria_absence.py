"""Is this element absent from Egeria? One shared, strict answer.

Three outcomes, and only the first lets a caller create something:

  absent      Egeria said there is no such element: pyegeria's `NO_ELEMENTS_FOUND` / `NO_ELEMENT_FOUND`
              answer, a `PyegeriaNotFoundException`, or a `PyegeriaAPIException` whose `related_http_code` is
              404 — UNLESS Egeria's message id says the SERVER is not available or not known
              (`OMAG-MULTI-TENANT-404-*`): a stopped or misnamed view server answers every look-up with a
              typed 404 (live probe, 2026-10-13), and that is "could not ask", never "not there".
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
#: pyegeria.core._globals.NO_ELEMENT_FOUND: the singular form the by-GUID / by-unique-name reads return.
NO_ELEMENT_FOUND = "No element found"
MISS_ANSWERS = (NO_ELEMENTS_FOUND, NO_ELEMENT_FOUND)

#: Egeria's message ids for "the server is not available / not known" (OMAGServerPlatform multi-tenant
#: handler). They arrive as a typed 404, but they are about the server, not the element.
SERVER_UNAVAILABLE_MESSAGE_PREFIX = "OMAG-MULTI-TENANT-404"


def is_absent(result_or_exc) -> str:
    """'absent' | 'present' | 'unreadable' for a returned answer or a raised exception."""
    if isinstance(result_or_exc, BaseException):
        return _classify_exception(result_or_exc)
    if isinstance(result_or_exc, str):
        # Exactly pyegeria's sentence, as `native_survey_run.absent_answers` reads it: case-insensitive,
        # a trailing period stripped. Never a substring ("user not found" is a different sentence).
        said = result_or_exc.strip().rstrip(".").strip().lower()
        return ABSENT if said in {m.lower() for m in MISS_ANSWERS} else UNREADABLE
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
    if egeria_message_id(exc).startswith(SERVER_UNAVAILABLE_MESSAGE_PREFIX):   # the message id first
        return UNREADABLE
    if isinstance(exc, PyegeriaNotFoundException):
        return ABSENT
    if isinstance(exc, PyegeriaAPIException) and getattr(exc, "related_http_code", None) == 404:
        return ABSENT
    return UNREADABLE


def egeria_message_id(exc: BaseException) -> str:
    """Egeria's `exceptionErrorMessageId` carried by a pyegeria exception, or ''. Read from the fields
    pyegeria fills (`response_egeria_msg_id`, `additional_info`), never from the exception's text."""
    found = getattr(exc, "response_egeria_msg_id", "") or ""
    if not found:
        info = getattr(exc, "additional_info", None)
        if isinstance(info, dict):
            found = info.get("exceptionErrorMessageId") or ""
    return str(found).strip()


def lookup_could_not_be_made(name: str, cause) -> str:
    """The words for a by-name look-up whose outcome is 'unreadable', for a caller that was about to create.

    `cause` is the raised exception, or None for a call that gave no answer. A look-up that could not be made
    is never "not there": the create is not attempted, and these words say so, in one form every create path
    shares (surveyors, doc sources, the outbox, reference-data proposals)."""
    if cause is None:
        detail = "Egeria gave no answer"
    else:
        detail = f"{type(cause).__name__}: {' '.join(str(cause).split())[:200] or '(no message)'}"
    return (f"the Egeria look-up for {name!r} could not be made ({detail}), so nothing was created: "
            "RE cannot tell whether it already exists")


def lookup_exception_is_absent(exc: BaseException) -> bool:
    """True only when a RAISED look-up is Egeria's own 'no such element' (see `is_absent`)."""
    return is_absent(exc) == ABSENT
