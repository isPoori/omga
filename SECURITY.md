# Security Policy

## Supported versions

| Version | Supported |
| ------- | --------- |
| 3.x     | ✅        |
| < 3.0   | ❌        |

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

1. Prefer a [GitHub private security advisory](https://github.com/isPoori/omga/security/advisories/new)
   on this repository.
2. Or contact the maintainer via [pouriahosseini.ir](https://pouriahosseini.ir).

Include:

- Affected version / commit
- Reproduction steps
- Impact assessment (auth bypass, secret leak, RCE, …)

You should receive an acknowledgement within a few days. We will coordinate a
fix and disclosure timeline with you.

## Safe handling of secrets

- API keys live only in `~/.config/omga/secrets.json` (never in git).
- Redact tokens from logs and bug reports.
- Rotate any key that may have been exposed.
