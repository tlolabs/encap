# Contributing to EnCap

Contributions are welcome. Authorized maintainers may commit and push directly
to `main`; pull requests and reviews are optional. Automated checks report
failures but are not required for a commit or merge. See [AGENTS.md](AGENTS.md)
for the repository's nonblocking development and release policy.

Run the relevant checks in [docs/development.md](docs/development.md) and state
which platforms you verified. Update documentation and third-party notices
when behavior or dependencies change. Original EnCap contributions must be
compatible with the repository's GPL-3.0-only license.

Use a concise, descriptive commit subject. DCO `Signed-off-by:` trailers are
encouraged; `git commit -s` adds one. They are not enforced. Cryptographic
commit signing is optional. Never publish an artifact that has not passed its
target-platform functional verification, and record unresolved failures in the
consolidated CI/CD issue.
