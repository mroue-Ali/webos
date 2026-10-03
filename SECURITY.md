# Security policy

webos controls a server's containers, and later milestones add a terminal. Treat any
weakness in it as a path to root on the host.

## Reporting a vulnerability

Use GitHub's **private vulnerability reporting** on this repository (Security tab →
"Report a vulnerability"). Please don't open a public issue. You'll get an answer within a
week.

## What is in scope

- Bypassing authentication, the TOTP check, the login throttle or session expiry
- Cross-site request forgery or cross-site WebSocket hijacking against `/api`
- Script injection, including through container names, labels or log lines
- Making the panel reach Docker endpoints the socket proxy should refuse, or passing
  crafted ids or paths through to the Docker API
- Leaking project secrets (container environment, `.env` files) through the API or the
  audit log
- Anything that lets the panel change SSH, firewall or systemd configuration

## Design assumptions

- The panel is reachable only from the operator's machines (an SSH tunnel or a private
  network). Exposing it publicly is possible, but it isn't the default.
- Whoever has a shell on the host as root, or as a user in the `docker` group, already
  controls everything. The audit log records actions; it isn't tamper-proof against them.

The full threat model is in [docs/PLAN.md](docs/PLAN.md).
