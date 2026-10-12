#pragma once

#ifdef __cplusplus
extern "C" {
#endif

int encap_audio_open(const char* path);
void encap_audio_play(double rate);
void encap_audio_pause(void);
void encap_audio_seek(double seconds);
double encap_audio_position(void);
int encap_audio_playing(void);
void encap_audio_close(void);
void encap_audio_volume(double volume);

#if defined(_WIN32) || defined(__linux__)
typedef void (*encap_media_action)(int action, double value);
int encap_media_open(void* window, encap_media_action callback);
void encap_media_update(const char* title, double position, double duration,
                        double rate, int playing, int enabled, double volume);
void encap_media_close(void);
#endif

#ifdef __cplusplus
}
#endif
