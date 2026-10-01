// SPDX-License-Identifier: GPL-3.0-only
// Narrow audio-device adapter. No project, UI, export, or update logic lives here.
#define MINIAUDIO_IMPLEMENTATION
#define MA_NO_ENCODING
#include "../vendor/miniaudio.h"
#include <math.h>
#if defined(_WIN32)
#define API __declspec(dllexport)
#else
#define API __attribute__((visibility("default")))
#endif
#define BLOCK 4096
static ma_device device;
static ma_decoder decoder;
static ma_mutex mutex;
static int initialized, opened, playing;
static double position, rate;
static ma_uint64 length, cached_start, cached_count;
static float samples[BLOCK*2];
static void render(ma_device* dev, void* output, const void* input, ma_uint32 count) {
    (void)dev; (void)input;
    float* out=(float*)output;
    memset(out,0,count*2*sizeof(float));
    ma_mutex_lock(&mutex);
    for(ma_uint32 i=0; i<count && playing && opened; ++i) {
        if(position<0 || position>=(double)length){playing=0;position=position<0?0:(double)length;break;}
        ma_uint64 frame=(ma_uint64)position;
        if(frame<cached_start || frame>=cached_start+cached_count) {
            cached_start=(frame/BLOCK)*BLOCK;
            if(ma_decoder_seek_to_pcm_frame(&decoder,cached_start)!=MA_SUCCESS){playing=0;break;}
            ma_decoder_read_pcm_frames(&decoder,samples,BLOCK,&cached_count);
        }
        if(frame>=cached_start+cached_count){playing=0;break;}
        out[i*2]=samples[(frame-cached_start)*2];out[i*2+1]=samples[(frame-cached_start)*2+1];
        position+=rate;
    }
    ma_mutex_unlock(&mutex);
}
API int encap_audio_open(const char* path) {
    if(!initialized) {
        if(ma_mutex_init(&mutex)!=MA_SUCCESS)return -1;
        ma_device_config config=ma_device_config_init(ma_device_type_playback);
        config.playback.format=ma_format_f32;config.playback.channels=2;config.sampleRate=48000;config.dataCallback=render;
        if(ma_device_init(NULL,&config,&device)!=MA_SUCCESS){ma_mutex_uninit(&mutex);return -2;}
        initialized=1;
        if(ma_device_start(&device)!=MA_SUCCESS){ma_device_uninit(&device);ma_mutex_uninit(&mutex);initialized=0;return -3;}
    }
    ma_mutex_lock(&mutex);playing=0;
    if(opened){ma_decoder_uninit(&decoder);opened=0;}
    ma_decoder_config config=ma_decoder_config_init(ma_format_f32,2,48000);
    ma_result result;
#if defined(_WIN32)
    int count=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,path,-1,NULL,0);
    wchar_t* wide=count>0?(wchar_t*)malloc((size_t)count*sizeof(wchar_t)):NULL;
    if(wide){MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,path,-1,wide,count);result=ma_decoder_init_file_w(wide,&config,&decoder);free(wide);}
    else result=MA_INVALID_ARGS;
#else
    result=ma_decoder_init_file(path,&config,&decoder);
#endif
    if(result==MA_SUCCESS){opened=1;position=0;rate=1;cached_start=cached_count=0;ma_decoder_get_length_in_pcm_frames(&decoder,&length);}
    ma_mutex_unlock(&mutex);return result;
}
API void encap_audio_play(double value){if(!initialized)return;ma_mutex_lock(&mutex);rate=value;if(opened&&position>=length&&rate>0)position=0;playing=opened&&value!=0;ma_mutex_unlock(&mutex);}
API void encap_audio_pause(void){if(!initialized)return;ma_mutex_lock(&mutex);playing=0;ma_mutex_unlock(&mutex);}
API void encap_audio_seek(double seconds){if(!initialized)return;ma_mutex_lock(&mutex);position=fmin((double)length,fmax(0,seconds*48000));ma_mutex_unlock(&mutex);}
API double encap_audio_position(void){if(!initialized)return 0;ma_mutex_lock(&mutex);double result=position/48000;ma_mutex_unlock(&mutex);return result;}
API int encap_audio_playing(void){if(!initialized)return 0;ma_mutex_lock(&mutex);int result=playing;ma_mutex_unlock(&mutex);return result;}
API void encap_audio_close(void){if(!initialized)return;ma_device_uninit(&device);if(opened)ma_decoder_uninit(&decoder);opened=playing=initialized=0;ma_mutex_uninit(&mutex);}

API void encap_audio_volume(double value){if(initialized)ma_device_set_master_volume(&device,(float)value);}
