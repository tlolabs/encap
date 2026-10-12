// SPDX-License-Identifier: GPL-3.0-only
#define MINIAUDIO_IMPLEMENTATION
#define MA_NO_ENCODING
#include "../vendor/miniaudio.h"

int main(void)
{
    size_t sizeInBytes;
    float sample;
    ma_noise noise;
    ma_noise_config noiseConfig;
    ma_pcm_rb ringBuffer;
    ma_uint64 totalPCMFrames;
    ma_result result;

    if (!ma_size_mul(1024, sizeof(float), &sizeInBytes) || sizeInBytes != 1024 * sizeof(float)) {
        return 1;
    }
    if (ma_size_mul(MA_SIZE_MAX, 2, &sizeInBytes)) {
        return 2;
    }
    if (ma_size_mul3(MA_SIZE_MAX, 2, sizeof(float), &sizeInBytes)) {
        return 3;
    }

    totalPCMFrames = ma_dr_mp3_calculate_total_pcm_frame_count(0x40000000, 1152);
    if (totalPCMFrames != 1236950581248ULL) {
        return 4;
    }

    result = ma_pcm_rb_init(ma_format_f32, 2, 0x20000001, NULL, NULL, &ringBuffer);
    if (result == MA_SUCCESS) {
        ma_pcm_rb_uninit(&ringBuffer);
        return 5;
    }
    if (result != MA_INVALID_ARGS) {
        return 6;
    }

    noiseConfig = ma_noise_config_init(ma_format_f32, 1, ma_noise_type_white, 0, 1.0);
    if (ma_noise_init(&noiseConfig, NULL, &noise) != MA_SUCCESS) {
        return 7;
    }
    result = ma_noise_read_pcm_frames(&noise, &sample, (ma_uint64)MA_SIZE_MAX / sizeof(float) + 1, NULL);
    ma_noise_uninit(&noise, NULL);
    if (result != MA_INVALID_ARGS) {
        return 8;
    }

    return 0;
}
