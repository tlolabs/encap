#ifndef ENCAP_TRANSCRIPTION_H
#define ENCAP_TRANSCRIPTION_H
#include <stdint.h>
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Optional Apple ARM64/macOS14 module. Base app retains macOS13 and Intel support.
 * ABI1/schema1. Each request is {schema_version:1,arguments:[operation,...]}.
 * Maximum request 4MiB. Keep transcript/project data in operation-owned files.
 * Execute blocks a worker and returns only after provider cleanup and lease exit.
 * Cancellation is cooperative; the caller must await execute, then release.
 * Callback UTF8 JSON is borrowed only until callback returns; copy before UI dispatch.
 * Opaque handles are owned, invalid handles fail; release each exactly once.
 * Do not unload this Swift module during the process lifetime. */
typedef void (*encap_transcription_event)(void *context,const uint8_t *bytes,size_t length);
uint32_t encap_transcription_abi_version(void);
uint64_t encap_transcription_token_create(void);
int32_t encap_transcription_cancel(uint64_t token);
uint64_t encap_transcription_execute(uint64_t token,const uint8_t *request,size_t length,encap_transcription_event callback,void *context);
size_t encap_transcription_result_size(uint64_t result);
int32_t encap_transcription_result_copy(uint64_t result,uint8_t *destination,size_t capacity);
void encap_transcription_release(uint64_t handle);
#ifdef __cplusplus
}
#endif
#endif
