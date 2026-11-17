# EnCAP linked transcription adapter

This package builds `libEnCAPTranscription.dylib` and an optional diagnostic
`avid-transcriber` client of the same service. Production EnCAP loads the library
through [ABI 1](../../include/encap_transcription.h); it never launches the client.
The shared model catalog, download, verification, recognition, alignment and
caption behavior remain in the unmodified Core Swift packages.

The adapter and both upstream packages identify immutable Core `v0.4.0`, commit
`dd112d497b68df6786f49a71b3611f7f32f090e9`. Run
`ruby script/verify_avid_snapshot.rb`; the source archive, file manifest,
`TranscriptWire.swift` source identity and frozen SwiftPM resolution move together.
The complete source is vendored, so a sibling checkout is unnecessary.

`script/build_avid_transcriber.sh DESTINATION` builds the dynamic product with
Swift 6.3+, Xcode and the installed Metal toolchain. It stages a versioned framework, SwiftPM
catalog/SDK/Metal resources, resolved SDK licenses and checksummed receipt, then
loads the relocated module with an empty PATH for a catalog smoke. The smoke
neither downloads a model nor qualifies actual inference. A copied dylib without
its resources is incomplete.

The optional module requires Apple silicon and macOS 14. EnCAP's macOS 13 and
Intel base application does not link it at launch; Rust checks compatibility
before loading it from `Contents/Frameworks/EnCAPTranscription.framework`. Missing or
incompatible optional inference leaves saved transcript editing and subtitle
export available. No deployment minimum is silently raised.

ABI execution blocks an application worker. A request is
`{"schema_version":1,"arguments":["models"]}`; request JSON is at most 4 MiB.
The argument adapter retains the existing explicit operations: `status`, `models`,
`providers`, `install-model`, `verify-model`, `import-model`, `remove-model`,
`transcribe`, `realign`, `captions` and `subtitles`. Transcript inputs use owned
operation files; complete project manifests never enter this media request.
Results own opaque handles with explicit length/copy/release. Invalid handles,
schemas and sizes produce errors. Progress is copied into a bounded queue by
Swift provider tasks and delivered on the executing host worker. Hosts copy each
borrowed callback span before UI dispatch. Cancel the token and await execute;
CoreML/Metal kernels may delay cooperative cancellation. Keep the library loaded
until process exit and drain all work before application shutdown or updates.

Full Whisper large-v3 remains the quality default. Whisper Turbo, Parakeet,
Qwen recognition and Qwen corrected-text alignment retain separate explicit model
selections. Inference uses `RecognitionRequest(installedModel:)` and
`AlignmentRequest(installedModel:)` inside `withInstalledModel`, so the exact
verified model/tokenizer manifest, runtime revisions and exposed build provenance
survive into EnCAP's source-clock record. Loading, inference and awaited provider
unload all remain under the lease. Installation/import/download/removal are
explicit model operations; there is no implicit inference download.

`TranscriptWire` retains original recognition separately from later alignment.
New provenance records include `model_identity`, `runtime_revisions` and, where
exposed, `runtime_build_sha256`, as well as the source bundle and installation
identity. Historical absent identities stay absent. Rust owns EnCAP's single
source-to-episode projection, stable IDs, manual speakers, edit history and
ambiguous-source rejection. Corrected text invalidates affected timing; alignment
preserves corrected text and does not run another recognition pass.

Portable Tiny English is a separate explicit Rust adapter, described in
[the application integration](../../docs/transcription-avid-core.md). It is not
an alias for large-v3 or the Apple catalog. No legacy GGML file, import source or
third-party model cache is deleted, converted or adopted automatically.

The framework embeds the exact compatibility runtime selected by `swift-stdlib-tool` from the selected Xcode toolchain. Developer Xcode/Metal runpaths are removed; only system Swift lookup and direct loader-relative embedded dependencies remain. Original receipts and post-sign raw bindings live outside the framework in `Contents/Resources/EnCAPTranscription`, so binding cannot invalidate the framework resource seal. The installed Apple compiler build, runtime hash and Xcode acknowledgment identify that runtime; an exact matching runtime source Git revision is not exposed by the toolchain and is not invented. Corresponding runtime sources remain a distribution limitation.
