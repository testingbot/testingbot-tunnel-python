"""Finding the TestingBot key and secret."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple

from .errors import CredentialsError

# Environment variables looked at, in order
ENVIRONMENT_VARIABLES = (("TB_KEY", "TB_SECRET"), ("TESTINGBOT_KEY", "TESTINGBOT_SECRET"))


def credentials_file() -> Path:
    """``~/.testingbot``, holding ``key:secret``, the file the tunnel itself reads too."""
    return Path.home() / ".testingbot"


def read_credentials_file(path: Optional[Path] = None) -> Optional[Tuple[str, str]]:
    path = path or credentials_file()
    try:
        contents = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    key, separator, secret = contents.partition(":")
    key, secret = key.strip(), secret.strip()
    if not separator or not key or not secret:
        raise CredentialsError(f"{path} must hold your TestingBot key and secret as key:secret")
    return key, secret


def resolve_credentials(api_key: Optional[str] = None, api_secret: Optional[str] = None) -> Tuple[str, str]:
    """The key and secret to use.

    Taken from the arguments, then ``TB_KEY``/``TB_SECRET``, then
    ``TESTINGBOT_KEY``/``TESTINGBOT_SECRET``, then ``~/.testingbot``. A key and a secret always
    come from the same place, so a key from one source is never paired with another's secret.

    :raises CredentialsError: when no complete pair is found
    """
    if api_key or api_secret:
        if not (api_key and api_secret):
            missing = "api_secret" if api_key else "api_key"
            raise CredentialsError(f"{missing} is missing, pass both api_key and api_secret")
        return api_key, api_secret

    for key_variable, secret_variable in ENVIRONMENT_VARIABLES:
        key, secret = os.environ.get(key_variable), os.environ.get(secret_variable)
        if key and secret:
            return key, secret

    from_file = read_credentials_file()
    if from_file:
        return from_file

    raise CredentialsError(
        "No TestingBot credentials found. Pass api_key and api_secret, set TB_KEY and TB_SECRET "
        "(or TESTINGBOT_KEY and TESTINGBOT_SECRET), or create ~/.testingbot holding key:secret. "
        "Your key and secret are listed at https://testingbot.com/members"
    )
