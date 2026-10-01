# Contributing to EnCap

Outside contributions are welcome. Thomas Lothian is the sole maintainer and
final release authority unless the repository later records a change.

1. Discuss large changes in an issue before investing substantial work.
2. Build and run the relevant checks in [docs/TESTING.md](docs/TESTING.md).
3. Update documentation and third-party notices when behavior or dependencies
   change. Contributed code must be legally compatible with the project's
   current GPL-3.0-only license. The proposed GPL-3.0-or-later transition is
   deferred; see [docs/LICENSING_AUDIT.md](docs/LICENSING_AUDIT.md).
4. Certify each contributed commit with the Developer Certificate of Origin:
   add `Signed-off-by: Your Name <your-address>` using `git commit -s`.
   The sign-off means you have the right to submit the work under this
   project's license. It is separate from cryptographic commit signing.
5. Use a short, descriptive imperative commit subject. Conventional Commit
   prefixes are not required.

Create unsigned Git commits for both maintainer and outside contributions.
Run `git config --local commit.gpgsign false` in each clone and do not pass
`git commit -S`. Keep the DCO `Signed-off-by:` trailers added by
`git commit -s`; these are plain message text and do not require a signing key.
Release-tag authentication and release-artifact signing retain their existing
requirements. A CLA is not required. Pull requests are
reviewed by the maintainer; CI validation does not imply hands-on testing on
every platform.
