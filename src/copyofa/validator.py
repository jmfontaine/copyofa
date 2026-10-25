"""Check a Report against the JSON Schema published for its format (see ADR 0004)."""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from dataclasses import dataclass
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any, NoReturn

import jsonschema
import jsonschema.exceptions
import jsonschema.protocols

import copyofa
from copyofa.errors import CopyOfAError

VALID = "valid"
INVALID = "invalid"
UNSUPPORTED = "unsupported"

LIMITATIONS = (
    (
        "A valid Report is well formed: it has the fields its format defines, with "
        "values of the right type. Validation establishes nothing more."
    ),
    "Validation does not establish that the findings in the Report are true.",
    "Validation does not establish who produced the Report.",
    "Validation does not establish anything about the audio the Report describes.",
)

# One schema per Report kind and format version; a new format version adds one line.
_SCHEMAS = {
    ("copyofa.verification", 1): "verification-report-1.schema.json",
    ("copyofa.inspection", 1): "inspection-report-1.schema.json",
    ("copyofa.comparison", 1): "comparison-report-1.schema.json",
    ("copyofa.comparison", 2): "comparison-report-2.schema.json",
}

# The longest a message of a problem gets: a message can quote a value of the document.
_MESSAGE_LIMIT = 300


class UnreadableReportError(CopyOfAError):
    """A Report file that cannot be read."""


@dataclass(frozen=True)
class Validation:
    """What validating one file found."""

    result: dict[str, Any]
    """The validation result document that `--json` prints."""
    document: Any
    """The parsed JSON when the file parsed, else None."""


class _MalformedError(Exception):
    """JSON text that is not strict JSON, with the reason."""


def validate(path: str) -> Validation:
    """Validate the Report file at path against the schema of its kind and version.

    Reads the file and writes nothing. Raises UnreadableReportError when the file
    cannot be read; anything wrong with its content is a problem of the result.
    """
    data = _read(path)
    result: dict[str, Any] = {
        "outcome": INVALID,
        "report": str(Path(path).absolute()),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    document: Any = None
    try:
        document = _parse(data)
    except _MalformedError as error:
        problems = [_problem("", str(error))]
    else:
        outcome, problems = check(document)
        result["outcome"] = outcome
        if isinstance(document, dict):
            kind = document.get("report_kind")
            version = document.get("format_version")
            if isinstance(kind, str):
                result["report_kind"] = kind
            if _is_version(version):
                result["format_version"] = version
    result["problems"] = problems
    result["copyofa_version"] = copyofa.__version__
    result["limitations"] = list(LIMITATIONS)
    return Validation(result, document)


def check(document: Any) -> tuple[str, list[dict[str, str]]]:
    """Check a parsed document; return its outcome and its problems.

    The document's `report_kind` and `format_version` select the schema.
    """
    if not isinstance(document, dict):
        return INVALID, [
            _problem(
                "",
                f"A Report is a JSON object, not {_describe(document)}.",
            )
        ]
    problems = []
    kind = document.get("report_kind")
    version = document.get("format_version")
    if "report_kind" not in document:
        problems.append(_problem("", "The document has no report_kind."))
    elif not isinstance(kind, str):
        problems.append(_problem("/report_kind", "report_kind must be a string."))
    if "format_version" not in document:
        problems.append(_problem("", "The document has no format_version."))
    elif not _is_version(version):
        problems.append(
            _problem("/format_version", "format_version must be a positive integer.")
        )
    if problems:
        return INVALID, problems
    assert isinstance(kind, str)
    assert isinstance(version, int)
    if (kind, version) not in _SCHEMAS:
        return UNSUPPORTED, [_problem("", _unsupported(kind, version))]
    try:
        errors = sorted(
            _validator(kind, version).iter_errors(document), key=_error_order
        )
    except RecursionError:
        return INVALID, [_problem("", "The document is nested too deeply to check.")]
    if not errors:
        return VALID, []
    return INVALID, [
        _problem(_pointer(error), _sentence(error.message)) for error in errors
    ]


def load_schema(report_kind: str, format_version: int) -> dict[str, Any] | None:
    """Return the JSON Schema for a Report kind and format version, if there is one."""
    name = _SCHEMAS.get((report_kind, format_version))
    return None if name is None else _load(name)


def _read(path: str) -> bytes:
    try:
        # Non-blocking, so a named pipe in place of a Report cannot hang validate.
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except (FileNotFoundError, NotADirectoryError):
        raise UnreadableReportError(f"{path} does not exist.") from None
    except OSError as error:
        raise UnreadableReportError(
            f"{path} cannot be read: {error.strerror}."
        ) from None
    try:
        mode = os.fstat(fd).st_mode
        if stat.S_ISDIR(mode):
            raise UnreadableReportError(f"{path} is a directory, not a Report file.")
        if not stat.S_ISREG(mode):
            raise UnreadableReportError(f"{path} is not a regular file.")
        with os.fdopen(os.dup(fd), "rb") as file:
            return file.read()
    except OSError as error:
        raise UnreadableReportError(
            f"{path} cannot be read: {error.strerror}."
        ) from None
    finally:
        os.close(fd)


def _parse(data: bytes) -> Any:
    """Parse strict JSON: UTF-8 only, no NaN or infinity, no repeated member name."""
    if not data:
        raise _MalformedError("The file is empty.")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise _MalformedError(
            f"The file is not valid UTF-8: byte {error.start} cannot be decoded."
        ) from None
    try:
        return json.loads(
            text,
            object_pairs_hook=_object,
            parse_int=_integer,
            parse_float=_float,
            parse_constant=_constant,
        )
    except json.JSONDecodeError as error:
        raise _MalformedError(
            f"The file is not JSON: {error.msg} at line {error.lineno}, "
            f"column {error.colno}."
        ) from None
    except RecursionError:
        raise _MalformedError(
            "The file nests arrays or objects too deeply to read."
        ) from None


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise _MalformedError(f"An object repeats the member name {_quote(name)}.")
        result[name] = value
    return result


def _integer(text: str) -> int:
    try:
        return int(text)
    except ValueError:
        raise _MalformedError("A number has too many digits to read.") from None


def _float(text: str) -> float:
    number = float(text)
    if not math.isfinite(number):
        raise _MalformedError(f"The number {_quote(text)} is too large to read.")
    return number


def _constant(name: str) -> NoReturn:
    raise _MalformedError(f"The file holds {name}, which JSON does not allow.")


def _is_version(value: Any) -> bool:
    """Tell whether a value is a positive integer; a boolean is not."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _describe(document: Any) -> str:
    if document is None:
        return "null"
    if isinstance(document, bool):
        return "a boolean"
    if isinstance(document, int | float):
        return "a number"
    if isinstance(document, str):
        return "a string"
    return "an array"


def _unsupported(kind: str, version: int) -> str:
    known = {known_kind for known_kind, _ in _SCHEMAS}
    if kind not in known:
        return (
            f"This version of CopyOfA does not know the Report kind {_quote(kind)}. "
            "A newer version may."
        )
    return (
        f"This version of CopyOfA has no schema for format version {version} of "
        f"{kind} Reports. A newer version may."
    )


def _quote(text: str) -> str:
    """Quote untrusted text, cut short, with every unprintable character escaped."""
    return _shorten(repr(text))


def _shorten(text: str) -> str:
    if len(text) <= _MESSAGE_LIMIT:
        return text
    return f"{text[: _MESSAGE_LIMIT - 1]}…"


def _sentence(message: str) -> str:
    """End a jsonschema message, which has no full stop, as a sentence."""
    message = _shorten(message)
    return message if message.endswith((".", "…")) else f"{message}."


def _problem(location: str, message: str) -> dict[str, str]:
    return {"location": location, "message": _shorten(message)}


def _pointer(error: jsonschema.exceptions.ValidationError) -> str:
    """Return the JSON Pointer (RFC 6901) of the part of the document in error."""
    return "".join(
        f"/{str(part).replace('~', '~0').replace('/', '~1')}"
        for part in error.absolute_path
    )


def _error_order(error: jsonschema.exceptions.ValidationError) -> list[tuple[int, Any]]:
    """Order errors by location, array items by index."""
    return [
        (0, part) if isinstance(part, int) else (1, part)
        for part in error.absolute_path
    ]


@cache
def _load(name: str) -> dict[str, Any]:
    text = resources.files("copyofa").joinpath("schemas", name).read_text("utf-8")
    schema = json.loads(text)
    assert isinstance(schema, dict)
    return schema


@cache
def _validator(kind: str, version: int) -> jsonschema.protocols.Validator:
    schema = load_schema(kind, version)
    assert schema is not None
    return jsonschema.Draft202012Validator(schema)
