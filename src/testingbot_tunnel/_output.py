"""Reading what the tunnel writes: its errors, log records and diagnostics."""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Sequence

# The tunnel writes everything the TestingBot API refuses behind this prefix,
# spelled the way the tunnel spells it
TUNNEL_ERROR_PREFIX = "An error ocurred:"

# What TestingBot Tunnel 5.0 and up write when Java is too old for them
JAVA_REQUIREMENT = re.compile(r"TestingBot Tunnel requires Java \d+ or higher")

# How tunnel 5.0 and up report the TestingBot API refusing to create a tunnel,
# e.g. 'Failed : HTTP error code : 401 - {"error":"401 Unauthorized. ..."}'
HTTP_ERROR = re.compile(r"HTTP error code : (\d+)(?: - (.*))?$")

# How many lines of tunnel output to keep for a tunnel that fails to start
MAX_REMEMBERED_LINES = 5

INVALID_CREDENTIALS = "Invalid credentials. Please supply the correct key/secret obtained from TestingBot.com"
NO_MINUTES = "You do not have any minutes left. Please upgrade your account at TestingBot.com"


def describe_api_refusal(status_code: str, body: Optional[str]) -> str:
    """The reason the TestingBot API gave for not creating a tunnel."""
    if body:
        try:
            answer = json.loads(body)
        except ValueError:
            answer = None
        if isinstance(answer, dict) and isinstance(answer.get("error"), str) and answer["error"].strip():
            return str(answer["error"]).strip()
        return body.strip()
    return f"TestingBot refused to create the tunnel, HTTP status {status_code}"


def classify_tunnel_error(line: str) -> Optional[str]:
    """Turn a line the tunnel wrote into the reason it could not start, None when it is not an error.

    Everything the TestingBot API refuses is reported by the tunnel with the same prefix, so its
    own wording is used for the cases without a friendlier message: too many tunnels, a
    suspended account, ...
    """
    if "401 Unauthorized" in line:
        return INVALID_CREDENTIALS
    if "minutes left" in line:
        return NO_MINUTES
    if line.startswith(TUNNEL_ERROR_PREFIX):
        return line[len(TUNNEL_ERROR_PREFIX) :].strip() or line
    http_error = HTTP_ERROR.search(line)
    if http_error:
        return describe_api_refusal(http_error.group(1), http_error.group(2))
    # Reported without the prefix when the tunnel can not reach TestingBot at all.
    # Tunnel 5.0 and up write this first and the reason on a later line, which replaces it.
    if line.startswith("Creating a new tunnel failed"):
        return line
    if JAVA_REQUIREMENT.search(line):
        return line
    return None


def parse_log_line(line: str) -> List[str]:
    """The lines of a message the tunnel wrote.

    With ``log_format="json"`` tunnel 5.0 and up write every message as a JSON object, which can
    hold several lines. Other output is a line of its own.
    """
    if not line.startswith("{"):
        return [line]
    try:
        record = json.loads(line)
    except ValueError:
        return [line]
    if isinstance(record, dict) and isinstance(record.get("message"), str):
        return [entry.strip() for entry in re.split(r"\r?\n", record["message"])]
    return [line]


def describe_startup_failure(error: Optional[str], code: Optional[int], output: Sequence[str] = ()) -> str:
    """Why the tunnel did not start: the reason we recognised, or the exit code and its last lines."""
    if error:
        return error
    message = f"Could not start TestingBot Tunnel. Exit code {code}"
    lines = [line for line in output if line]
    return message if not lines else message + "\n" + "\n".join(lines)


# How java.util.logging starts the line before every message, in text format:
# "Nov 05, 2026 11:03:51 AM com.testingbot.tunnel.Doctor performCheck"
_JUL_HEADER = re.compile(r"^\S+ \d{1,2}, \d{4} \d{1,2}:\d{2}:\d{2}(?: [AP]M)? \S+")
# The level and message that follow it: "INFO: OK - Proxy port 8087 can be opened"
_JUL_MESSAGE = re.compile(r"^(SEVERE|WARNING|INFO|CONFIG|FINE|FINER|FINEST): (.*)$")


def parse_log_records(lines: Sequence[str]) -> List[Dict[str, str]]:
    """The messages the tunnel logged, in either log format, as ``{"level", "message"}``."""
    records: List[Dict[str, str]] = []
    last: Optional[Dict[str, str]] = None
    for line in lines:
        if line.startswith("{"):
            try:
                record = json.loads(line)
            except ValueError:
                record = None
            if isinstance(record, dict) and isinstance(record.get("message"), str):
                last = {"level": str(record.get("level") or "INFO").upper(), "message": record["message"].strip()}
                records.append(last)
                continue
        if _JUL_HEADER.match(line):
            last = None
            continue
        message = _JUL_MESSAGE.match(line)
        if message:
            last = {"level": message.group(1), "message": message.group(2).strip()}
            records.append(last)
        elif last is not None and line != "":
            # A message of more than one line
            last["message"] += "\n" + line
    return records
