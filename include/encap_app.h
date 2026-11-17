/* EnCAP application ABI 1 / JSON schema 1. SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef ENCAP_APP_H
#define ENCAP_APP_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
typedef uint64_t encap_handle;
typedef void (*encap_event_callback)(void *context, const uint8_t *json, size_t length);
uint32_t encap_app_abi_version(void);
uint32_t encap_app_schema_version(void);
encap_handle encap_app_create(void);
/* Optional per-application configuration: {"schema_version":1,"recovery_path":"..."}.
 * No environment mutation. Invalid schema/configuration returns zero. */
encap_handle encap_app_create_json(const uint8_t *request, size_t length);
encap_handle encap_app_cancel_create(void);
int32_t encap_app_cancel(encap_handle cancellation);
int32_t encap_app_release(encap_handle handle);
size_t encap_app_buffer_len(encap_handle result);
size_t encap_app_buffer_copy(encap_handle result, uint8_t *output, size_t capacity);
/* Blocking call: use a host worker and retain input/context until return. No
 * detached job survives return. Separate token per operation; cancellation is
 * cooperative and callers must join, never terminate the worker or unload the
 * library while any call is active. Opaque handles are owned; release once.
 * Releasing a handle cannot cancel an executing call, whose references survive.
 *
 * Request maximum: 64 KiB, not Core's media schema. Example:
 * {"schema_version":1,"operation":"save","payload":"/tmp/project.json",
 *  "project":"/dest/project.encap"}. Project payloads are separate local files
 * bounded at the existing 8 MiB manifest limit; no transcript is truncated.
 * Results: {schema_version:1,ok:true,result:...} or
 * {schema_version:1,ok:false,error:{code,detail}}, maximum 64 MiB. Zero result
 * means an ABI panic/allocation failure. Callers must enforce this bound before
 * allocating, copy the complete buffer, then release it. Too-short copies fail.
 *
 * Callback JSON is borrowed only during the callback on the calling worker.
 * Copy before dispatch, return promptly, never unwind or wait for this operation.
 * The callback context is not retained after return. Complete follows successful
 * publication; no false percentage or process-style hard timeout is promised.
 * All foreign buffers must be valid for declared lengths; pointers cannot be
 * validated against arbitrary host memory. Return codes: 0 success, -1 invalid.
 */
encap_handle encap_app_execute_json(encap_handle application, encap_handle cancellation,
    const uint8_t *request, size_t length, encap_event_callback callback, void *context);
#ifdef __cplusplus
}
#endif
#endif
