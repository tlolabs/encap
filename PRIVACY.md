# Privacy

EnCap processes projects, recordings, transcripts, artwork, and exports locally.
It does not collect or transmit usage analytics, telemetry, or crash reports;
it does not sell or share user data.

## Network activity

- **Optional model download:** When a user selects Download in Manage Models,
  EnCap requests a pinned model from Hugging Face over HTTPS, checks its
  SHA-256 digest, and stores it locally. Hugging Face can see normal request
  metadata such as an IP address. No recording or transcript is uploaded.
- **macOS update check:** A build containing Sparkle may request its appcast
  from GitHub Releases, either during an automatic check or when the user
  chooses Check for Updates. Automatic installation is disabled; accepting
  an update requires user action. GitHub can see normal request metadata.
  No project content is sent.
- **Builds:** Building from source downloads pinned dependencies and tools
  from their upstream hosts. This is build activity, not application telemetry.

The core editing and export functions work offline after installation. Local
speech recognition requires an installed model or a compatible local provider;
obtaining a new model requires network access. Apple on-device Speech is used
only where available. EnCap does not fetch remote fonts or artwork at runtime.

## Local data and logs

Projects and exports are saved where the user chooses. Downloaded models live
in EnCap's platform application-data directory. The Rust engine writes
diagnostic logs in that directory's `logs` subfolder, rotates them daily, and
keeps at most 14 log files. Logs stay local and are not uploaded automatically.
They may include file paths, errors, and operational details useful for
diagnosis; review them before sharing with a public issue. The application
does not set a separate deletion schedule for projects, exports, or models.

Privacy questions: use [GitHub Issues](https://github.com/tlolabs/encap/issues)
for non-sensitive questions. Public project/security email: **TBD**.
