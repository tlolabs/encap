// SPDX-License-Identifier: GPL-3.0-only
#include <windows.h>
#include <roapi.h>
#include <SystemMediaTransportControlsInterop.h>
#include <winrt/Windows.Foundation.h>
#include <winrt/Windows.Media.h>
#include <winrt/Windows.Media.Playback.h>
#include <atomic>
using namespace winrt;
using namespace Windows::Media;
using namespace Windows::Foundation;
using callback_t=void(__cdecl*)(int,double);
static SystemMediaTransportControls controls{nullptr};
static std::atomic<callback_t> callback{nullptr};
static event_token buttons,position_request,rate_request;
static bool owns_apartment=false;
extern "C" __declspec(dllexport) int encap_media_open(void* window,callback_t handler){
    // Balance our own WinRT initialization even when Avalonia already owns COM.
    const HRESULT initialized=RoInitialize(RO_INIT_SINGLETHREADED);
    if(FAILED(initialized)&&initialized!=RPC_E_CHANGED_MODE)return -1;
    owns_apartment=SUCCEEDED(initialized);
    try{
        auto factory=get_activation_factory<SystemMediaTransportControls,ISystemMediaTransportControlsInterop>();
        check_hresult(factory->GetForWindow(static_cast<HWND>(window),guid_of<SystemMediaTransportControls>(),put_abi(controls)));
        callback.store(handler);
        controls.IsPlayEnabled(true);controls.IsPauseEnabled(true);controls.IsStopEnabled(true);controls.IsNextEnabled(true);controls.IsPreviousEnabled(true);
        buttons=controls.ButtonPressed([](auto const&,auto const& args){
            int action=0;switch(args.Button()){
                case SystemMediaTransportControlsButton::Play:action=1;break;
                case SystemMediaTransportControlsButton::Pause:action=2;break;
                case SystemMediaTransportControlsButton::Stop:action=3;break;
                case SystemMediaTransportControlsButton::Next:action=4;break;
                case SystemMediaTransportControlsButton::Previous:action=5;break;
                default:break;
            }if(auto cb=callback.load();cb&&action)cb(action,0);
        });
        position_request=controls.PlaybackPositionChangeRequested([](auto const&,auto const& args){if(auto cb=callback.load())cb(6,args.RequestedPlaybackPosition().count()/10000000.0);});
        rate_request=controls.PlaybackRateChangeRequested([](auto const&,auto const& args){if(auto cb=callback.load())cb(8,args.RequestedPlaybackRate());});
        return 0;
    }catch(...){controls=nullptr;callback.store(nullptr);if(owns_apartment){RoUninitialize();owns_apartment=false;}return -1;}
}
extern "C" __declspec(dllexport) void encap_media_update(const char* title,double position,double duration,double rate,int playing,int enabled,double volume){
    (void)volume;if(!controls)return;
    try{
        controls.IsEnabled(enabled!=0);controls.PlaybackStatus(playing?MediaPlaybackStatus::Playing:MediaPlaybackStatus::Paused);
        controls.PlaybackRate(rate);
        auto display=controls.DisplayUpdater();display.Type(MediaPlaybackType::Music);display.MusicProperties().Title(to_hstring(title));display.Update();
        SystemMediaTransportControlsTimelineProperties timeline;
        timeline.StartTime(TimeSpan{0});timeline.MinSeekTime(TimeSpan{0});timeline.MaxSeekTime(TimeSpan{static_cast<int64_t>(duration*10000000)});timeline.EndTime(timeline.MaxSeekTime());timeline.Position(TimeSpan{static_cast<int64_t>(position*10000000)});
        controls.UpdateTimelineProperties(timeline);
    }catch(...){/* Session loss must not interrupt editing or playback. */}
}
extern "C" __declspec(dllexport) void encap_media_close(){
    callback.store(nullptr);
    if(controls)try{controls.ButtonPressed(buttons);controls.PlaybackPositionChangeRequested(position_request);controls.PlaybackRateChangeRequested(rate_request);controls.IsEnabled(false);}catch(...){}
    controls=nullptr;
    if(owns_apartment){RoUninitialize();owns_apartment=false;}
}
