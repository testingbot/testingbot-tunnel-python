# Changelog

## 0.1.0 (unreleased)

First release, a port of the Node.js [testingbot-tunnel-launcher](https://github.com/testingbot/testingbot-tunnel-launcher) 1.2.0.

- `Tunnel(api_key=None, api_secret=None, **options)` with `start()`, `stop()`, `is_running()` and use as a context manager
- Credentials from the arguments, `TB_KEY`/`TB_SECRET`, `TESTINGBOT_KEY`/`TESTINGBOT_SECRET` or `~/.testingbot`, handed to the tunnel through the environment so they stay out of the process list, and redacted from verbose output
- Downloads the tunnel jar from testingbot.com into the user cache directory (shared with the Node.js launcher, `TESTINGBOT_TUNNEL_CACHE_DIR` overrides it), only following redirects that stay on https, with a timeout for stalled downloads and a temporary file renamed once complete
- Uses the installed Java when it is recent enough (Java 17 for tunnel 5.0 and up, Java 11 before), and otherwise the TestingBot Tunnel download with Java included, checked against its published SHA-256 checksum. `java_runtime` chooses between `auto`, `system` and `bundled`
- Every tunnel gets its own readyfile in a private temporary directory, and is ready once the tunnel touches it
- Reports why a tunnel did not start in the words of the tunnel: wrong credentials, no minutes left, too many tunnels, an API refusal, Java too old, or the exit code with the last lines it wrote
- Checks options before starting: unknown options (with a suggestion), invalid values, and options the tunnel version does not support yet
- Stops tunnels with SIGINT so TestingBot removes them right away, kills them when they do not stop in time, and stops tunnels still running when the interpreter exits
- `doctor()` and `pac_test()` run the tunnel's `--doctor` and `--pac-test` checks
- pytest plugin with a session-wide `testingbot_tunnel` fixture, `--tb-tunnel`, `--tb-tunnel-identifier` and `--tb-tunnel-version`
