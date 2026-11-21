# testingbot-tunnel

[![PyPI](https://img.shields.io/pypi/v/testingbot-tunnel.svg)](https://pypi.org/project/testingbot-tunnel/)
[![Tests](https://github.com/testingbot/testingbot-tunnel-python/actions/workflows/test.yml/badge.svg)](https://github.com/testingbot/testingbot-tunnel-python/actions/workflows/test.yml)

Download and launch [TestingBot Tunnel](https://testingbot.com/support/tunnel) from Python, so
browsers on the TestingBot cloud can reach sites on your machine, your CI runner or your
private network. Comes with a pytest plugin.

- No dependencies beyond the standard library, Python 3.9 and up.
- Downloads the tunnel when needed and keeps it in a cache. Uses the installed Java when it is
  recent enough, and otherwise the TestingBot Tunnel download with Java included, so nothing
  needs to be installed.
- Waits until the tunnel is really ready, and explains why when it does not start: wrong
  credentials, no minutes left, too many tunnels, Java too old, ...
- Stops the tunnel cleanly, so TestingBot removes it right away.

This is the Python counterpart of the Node.js
[testingbot-tunnel-launcher](https://github.com/testingbot/testingbot-tunnel-launcher).

## Installation

```sh
pip install testingbot-tunnel
```

## Usage

```python
from testingbot_tunnel import Tunnel

with Tunnel(tunnel_identifier="my-build") as tunnel:
    ...  # run your tests, the tunnel is ready here
# the tunnel is stopped here
```

Or start and stop it yourself:

```python
tunnel = Tunnel(api_key="key", api_secret="secret", tunnel_identifier="my-build")
tunnel.start()  # blocks until the tunnel is ready
print(tunnel.is_running())
tunnel.stop()  # blocks until the tunnel process has exited
```

### Credentials

Your key and secret are listed in the [TestingBot member area](https://testingbot.com/members).
When they are not passed as `api_key` and `api_secret`, they are taken from, in this order:

1. `TB_KEY` and `TB_SECRET`
2. `TESTINGBOT_KEY` and `TESTINGBOT_SECRET`
3. `~/.testingbot`, holding `key:secret`

The credentials are handed to the tunnel through the `TESTINGBOT_KEY` and `TESTINGBOT_SECRET`
environment variables instead of its command line, so they do not show up in the process list.
They are redacted from the output when `verbose` is enabled.

### Selenium

Route a test through the tunnel with the `tunnel-identifier` capability:

```python
from selenium import webdriver
from testingbot_tunnel import Tunnel

with Tunnel(tunnel_identifier="my-build") as tunnel:
    options = webdriver.ChromeOptions()
    options.browser_version = "latest"
    options.platform_name = "WIN11"
    options.set_capability(
        "tb:options",
        {
            "key": "key",
            "secret": "secret",
            "name": "Through the tunnel",
            "tunnel-identifier": tunnel.tunnel_identifier,
        },
    )
    driver = webdriver.Remote("https://hub.testingbot.com/wd/hub", options=options)
    try:
        driver.get("http://localhost:8000")  # a site on your machine
        assert driver.title == "My local site"
    finally:
        driver.quit()
```

### pytest

Installing the package adds a pytest plugin. Ask for the `testingbot_tunnel` fixture and a tunnel
is started the first time a test needs it, shared by the whole session and stopped at the end:

```python
# test_site.py
import os
import pytest
from selenium import webdriver


@pytest.fixture
def driver(testingbot_tunnel):
    options = webdriver.ChromeOptions()
    options.set_capability(
        "tb:options",
        {
            "key": os.environ["TB_KEY"],
            "secret": os.environ["TB_SECRET"],
            "tunnel-identifier": testingbot_tunnel.tunnel_identifier,
        },
    )
    driver = webdriver.Remote("https://hub.testingbot.com/wd/hub", options=options)
    yield driver
    driver.quit()


def test_homepage(driver):
    driver.get("http://localhost:8000")
    assert driver.title == "My local site"
```

```sh
pytest --tb-tunnel-identifier "build-$CI_PIPELINE_ID"
```

| Option | |
| --- | --- |
| `--tb-tunnel` | Start the tunnel when the session starts, also when no test asks for the fixture. |
| `--tb-tunnel-identifier ID` | The `tunnel_identifier` option. |
| `--tb-tunnel-version VERSION` | The `tunnel_version` option, e.g. `5.2`. |

Any other option is passed by overriding the `testingbot_tunnel_options` fixture in your `conftest.py`:

```python
import pytest


@pytest.fixture(scope="session")
def testingbot_tunnel_options(pytestconfig):
    return {"tunnel_identifier": "my-build", "no_bump": True, "fast_fail_regexps": ".*google-analytics.*"}
```

With [pytest-xdist](https://pypi.org/project/pytest-xdist/) every worker is its own session and
would start its own tunnel, which clash over the local ports. Start one tunnel around the
whole run instead, for example with `python -c` in CI or a `with Tunnel():` in a wrapper script.

## Options

Options are passed as keyword arguments, in snake_case. They are checked before the tunnel
starts: a misspelled option raises a `TypeError` that suggests the right one, and an option the
tunnel version does not support yet raises a `ValueError` saying which version it needs.

Options of the launcher itself:

| Option | |
| --- | --- |
| `api_key`, `api_secret` | Your TestingBot credentials, see [Credentials](#credentials). |
| `tunnel_version` | Run this [tunnel version](https://testingbot.com/support/tunnel/changelog), e.g. `"5.2"`. Default: the latest. |
| `timeout` | Seconds to wait for the tunnel to become ready. Default 90. |
| `verbose` | Log what the tunnel writes (to the `testingbot_tunnel` logger, or stderr when logging is not configured). |
| `java_runtime` | `"auto"` (default), `"system"` or `"bundled"`, see [Java](#java). |
| `extra_args` | A list of arguments passed to the tunnel as they are, for options this launcher does not know about yet. |

Options of the tunnel, see the [tunnel command line reference](https://testingbot.com/support/tunnel/commandline):

| Option | Tunnel flag | |
| --- | --- | --- |
| `tunnel_identifier` | `--tunnel-identifier` | Name the tunnel, to pick it with the `tunnel-identifier` capability. |
| `shared` | `--shared` | Share the tunnel with your team. |
| `se_port` | `--se-port` | Local Selenium port. Default 4445. |
| `localproxy` | `--localproxy` | Port of the local proxy. Default 8087. |
| `hubport` | `--hubport` | Hub port: 80 (default) or 4444. |
| `no_proxy` | `--noproxy` | Do not start the local proxy. |
| `no_cache` | `--nocache` | Bypass the caching proxy on the tunnel VM. |
| `no_bump` | `--nobump` | Do not perform SSL bumping. |
| `web` | `--web` | Serve a local directory. |
| `fast_fail_regexps` | `--fast-fail-regexps` | Hosts the tunnel refuses straight away. |
| `dns` | `--dns` | DNS servers to use. |
| `auth` | `--auth` | Basic authentication for hosts, `host:port:user:passwd`. |
| `extra_headers` | `--extra-headers` | Request headers to add, as JSON. |
| `pac` | `--pac` | PAC URL for the remote browser. |
| `proxy`, `proxy_userpwd` | `--proxy`, `--proxy-userpwd` | Upstream proxy and its credentials. |
| `logfile` | `--logfile` | Write the log to a file as well. |
| `debug` | `--debug` | Debug logging. |
| `metrics_port`, `metrics_auth` | `--metrics-port`, `--metrics-auth` | Metrics and health endpoint. |

Tunnel 5.0 and up also take `config`, `bind_address`, `allow_hosts`, `localhost_policy`,
`connect_to`, `dns_round_robin`, `dns_timeout`, `http_dial_timeout`, `http_idle_timeout`,
`header`, `response_header`, `request_id_header`, `cacert_file`, `no_bump_domains`,
`proxy_auth_scheme`, `proxy_spn`, `krb5_hosts`, `krb5_keytab`, `krb5_principal`,
`proxy_testingbot`, `proxy_testingbot_userpwd`, `pac_local`, `pac_local_sha256`,
`ssh_host_key`, `ssh_host_key_policy`, `ws_proxy_mode`, `log_level`, `log_format` and `log_http`.
Tunnel 5.1 adds `ssh_connections` (1 to 8).

`True` passes a flag without a value, `False` and `None` leave the option out, and a list
passes the option once for every value (for `header`, `response_header`, `cacert_file` and
`ssh_host_key`):

```python
Tunnel(
    tunnel_identifier="staging",
    allow_hosts="example.com,*.example.com",
    header=["X-Test: 1", "-Cookie"],
    cacert_file=["/etc/ssl/corporate.pem"],
    ssh_connections=4,
)
```

Tunnel 5.0 and up read nearly every option from a `TESTINGBOT_` environment variable as well,
such as `TESTINGBOT_SE_PORT` for `--se-port`. The tunnel inherits the environment of your
process, so those apply here too. Options you pass take precedence.

## Java

The tunnel is a Java program. TestingBot Tunnel 5.0 and up need Java 17 or higher, older
tunnels Java 11.

TestingBot also publishes the tunnel with Java included, for Linux and macOS (x64 and arm64)
and Windows (x64). When Java is not installed, or the installed Java is too old for the tunnel,
that download is used instead (about 30 MB, once per version). It is checked against the
SHA-256 checksum TestingBot publishes next to it.

Choose with `java_runtime`:

- `"auto"` (default): the installed Java when it is recent enough, the download with Java included otherwise
- `"system"`: always the `java` on your `PATH`
- `"bundled"`: always the download with Java included

Set `TESTINGBOT_TUNNEL_RELEASES_URL` to download it from a mirror of the
[TestingBot Tunnel releases](https://github.com/testingbot/Testingbot-Tunnel/releases), laid out
the same way (`latest` redirecting to `tag/v<version>`, files in `download/v<version>/`).

## Errors

Everything the launcher raises derives from `testingbot_tunnel.TunnelError`:

| Exception | |
| --- | --- |
| `CredentialsError` | No key and secret were found. |
| `JavaError` | No suitable Java, and no download with Java included for this platform or tunnel version. |
| `DownloadError` | The tunnel could not be downloaded, or does not match its checksum. |
| `TunnelStartError` | The tunnel stopped before it was ready. The message says why, in the tunnel's words, or holds the last lines it wrote. |
| `TunnelTimeoutError` | The tunnel was not ready within `timeout` seconds. It is stopped. |

```python
from testingbot_tunnel import Tunnel, TunnelStartError

try:
    tunnel = Tunnel().start()
except TunnelStartError as error:
    print(error)  # e.g. "You already have 2 tunnels active - please close another tunnel first"
```

## Running more than one tunnel

Every `Tunnel` keeps its own state and its own readyfile, so several can run next to each other.
Give each its own `tunnel_identifier` and local ports:

```python
from testingbot_tunnel import Tunnel, stop_all

first = Tunnel(tunnel_identifier="first").start()
second = Tunnel(tunnel_identifier="second", se_port=4446, localproxy=8088, metrics_port=8004).start()

first.stop()
stop_all()  # stops every tunnel this process started
```

Tunnels that are still running when the interpreter exits are stopped as well.

## Checking the configuration

`doctor` lets the tunnel check whether it can work with your options, without starting a
tunnel: whether TestingBot can be reached, the local ports can be opened, the upstream proxy
accepts the credentials, and so on. It takes the same options as `Tunnel`.

```python
from testingbot_tunnel import doctor

report = doctor(proxy="proxy.example.com:3128")
for check in report.checks:
    print(check.status, check.message)  # status is ok, warn, fail or info
```

`pac_test` asks TestingBot Tunnel 5.0 and up which way it would send a URL with a PAC file:

```python
from testingbot_tunnel import pac_test

result = pac_test("https://intranet.example.com/", pac_local="/etc/proxy.pac")
print(result.result, result.egress, result.direct)
```

## Where the tunnel is stored

In the cache directory of the user: `~/.cache/testingbot-tunnel-launcher` on Linux,
`~/Library/Caches/testingbot-tunnel-launcher` on macOS and `%LOCALAPPDATA%\testingbot-tunnel-launcher`
on Windows. That is the directory the Node.js launcher uses too, so both share their downloads.
Set `TESTINGBOT_TUNNEL_CACHE_DIR` to store it somewhere else.

Downloads only follow redirects that stay on https, time out when they stall, and are written
to a temporary file first, so an interrupted download never ends up being run.

## Development

```sh
python -m venv .venv && . .venv/bin/activate
pip install -e '.[test]' ruff mypy
ruff check . && ruff format --check . && mypy --strict src
pytest
```

The live test starts a real tunnel and a Selenium session on TestingBot. It runs when
`TESTINGBOT_LIVE=1` is set and credentials are available:

```sh
pip install -e '.[live]'
TESTINGBOT_LIVE=1 pytest tests/live -v
```

## License

MIT, see [LICENSE](LICENSE).
