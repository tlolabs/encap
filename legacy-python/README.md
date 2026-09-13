# Legacy Python reference implementation

The Python/Qt implementation is intentionally preserved during the Rust rewrite.
Its runnable source remains under `src/encap/`, with the historical PyInstaller
entry points and specifications at the repository root. Keeping those paths in
place avoids breaking comparison builds while the native replacements are being
verified.

The immutable pre-rewrite baseline is commit `bcddf71` on `main`. To run the
legacy UI from the current checkout:

```sh
.venv-packaging/bin/python -m encap.gui
```

The Rust engine and native applications are the primary implementation from
version 0.2 onward. Do not delete this reference implementation until the owner
has completed manual parity verification.

