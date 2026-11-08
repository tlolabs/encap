# Transcription model sources and notices

AVID does not host these models. The catalog contains only immutable source
references, sizes, checksums, capability metadata, and these notices. Installation
downloads selected files directly from public Hugging Face repositories; inference
runs on the user's machine. Model weights are not included in this source tree.

The package exposes each catalog entry's `license` notice so hosts can show it in
the model selector, installed-model details, and application acknowledgments.
Keep these notices with redistributed source/catalog copies. The SDK licenses and
the downloaded weights' licenses are separate.

## Whisper large-v3 and large-v3 Turbo

- Original model family and tokenizer: OpenAI, [Whisper](https://github.com/openai/whisper).
- Apple Core ML conversion: Argmax, Inc., [WhisperKit model collection](https://huggingface.co/argmaxinc/whisperkit-coreml).
- Converted model repository pin: `0f63a7800b00dd0226abd051b906c246e1907482`.
- Full model directory: `openai_whisper-large-v3`.
- Turbo model directory: `openai_whisper-large-v3-v20240930`.
- Tokenizer source: [openai/whisper-large-v3](https://huggingface.co/openai/whisper-large-v3), pin `06f233fe06e710322aca913c1bc4249a0d71fce1`.

The Argmax model collection declares MIT. The pinned OpenAI large-v3 model card
and tokenizer source declare Apache-2.0. Preserve both sets of terms and notices;
the catalog identifies the combined installation as `MIT AND Apache-2.0`.
Original [large-v3 Turbo](https://huggingface.co/openai/whisper-large-v3-turbo)
weights are separately published under MIT. The shared downloaded tokenizer remains
from the Apache-2.0 large-v3 source. No audio or text is sent to OpenAI or Argmax.

## Parakeet TDT 0.6B v3

- Original model: NVIDIA, [nvidia/parakeet-tdt-0.6b-v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3).
- Core ML conversion: FluidInference, [parakeet-tdt-0.6b-v3-coreml](https://huggingface.co/FluidInference/parakeet-tdt-0.6b-v3-coreml).
- Converted repository pin: `7dd20fe6b1797d35f5e3307e8b1732d9a178edfe`.
- Selected variation: the SDK's int8 encoder (`Encoder_v2.mlmodelc`), with its
  preprocessor, decoder, v3 joint decision model, and vocabulary.

Original weights are licensed under [Creative Commons Attribution 4.0
International](https://creativecommons.org/licenses/by/4.0/). Attribute NVIDIA and
FluidInference, link that license, and indicate conversion and quantization changes.
The converted model card contains an inconsistent Apache-2.0 sentence; AVID retains
the upstream CC-BY-4.0 attribution obligations rather than treating the FluidAudio
SDK's Apache-2.0 license as a license for the original weights. No audio or text is
sent to NVIDIA or FluidInference.

## Qwen3-ASR and Qwen3-ForcedAligner

- Original models: Qwen Team, Alibaba Cloud,
  [Qwen3-ASR-1.7B](https://huggingface.co/Qwen/Qwen3-ASR-1.7B) and
  [Qwen3-ForcedAligner-0.6B](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B).
- MLX conversion and 4-bit quantization: MLX Community.
- [ASR conversion](https://huggingface.co/mlx-community/Qwen3-ASR-1.7B-4bit),
  pin `78a389c776a5483b2d0d4ea5494e11012e0d6159`.
- [Aligner conversion](https://huggingface.co/mlx-community/Qwen3-ForcedAligner-0.6B-4bit),
  pin `2f652af86ae0c73fe189b9429225c908ce4bf020`.

Models and converted repositories declare [Apache License
2.0](https://www.apache.org/licenses/LICENSE-2.0). Retain license, copyright, and any
upstream NOTICE files, and indicate conversion/quantization changes. No audio or
text is sent to Alibaba Cloud, Qwen, or MLX Community.

Qwen recognition supports 30 languages plus Chinese dialects; the aligner supports
only 11 languages. The catalog deliberately gives the ASR entry no native timing
languages. Installing an ASR model alone must not promise timed captions.

## Provenance and catalog maintenance

`script/update_transcription_catalog.py` selects fixed source repositories and
40-character commit pins. For LFS files it records SHA-256 object identities from
metadata at those pins. For ordinary files it fetches the pinned bytes, verifies
the Git blob identity, and computes SHA-256. It does not fetch multi-gigabyte model
weights. The runtime verifies every downloaded file's size and SHA-256 before
using an installation.

These upstream repositories were public and ungated when this catalog was built.
Availability and upstream license/card updates remain external dependencies;
pinned downloaded installations remain usable offline. A catalog refresh is a
reviewable source change, not a silent model replacement.
