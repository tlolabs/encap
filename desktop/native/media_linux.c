// SPDX-License-Identifier: GPL-3.0-only
// Linux desktop session integration, independent of widgets and audio decoding.
#include <gio/gio.h>
#include <unistd.h>
#include <math.h>
#define API __attribute__((visibility("default")))
typedef void(*action_callback)(int,double);
static GMutex gate;
static GCond ready;
static gboolean thread_ready;
static GThread* thread;
static GMainContext* context;
static GMainLoop* loop;
static GDBusConnection* bus;
static guint owner, registrations[2];
static GDBusNodeInfo* info;
static action_callback action;
static gchar* title;
static double position,duration,rate,volume;
static int playing,enabled;
static const char* media_path="/org/mpris/MediaPlayer2";
static const char* player_interface="org.mpris.MediaPlayer2.Player";
static const gchar *media_xml =
  "<node><interface name='org.mpris.MediaPlayer2'>"
  "<method name='Raise'/><method name='Quit'/>"
  "<property name='CanQuit' type='b' access='read'/><property name='CanRaise' type='b' access='read'/>"
  "<property name='HasTrackList' type='b' access='read'/><property name='Identity' type='s' access='read'/>"
  "<property name='DesktopEntry' type='s' access='read'/><property name='SupportedUriSchemes' type='as' access='read'/>"
  "<property name='SupportedMimeTypes' type='as' access='read'/></interface>"
  "<interface name='org.mpris.MediaPlayer2.Player'>"
  "<method name='Next'/><method name='Previous'/><method name='Pause'/><method name='PlayPause'/><method name='Stop'/><method name='Play'/>"
  "<method name='Seek'><arg type='x' direction='in' name='Offset'/></method>"
  "<method name='SetPosition'><arg type='o' direction='in' name='TrackId'/><arg type='x' direction='in' name='Position'/></method>"
  "<method name='OpenUri'><arg type='s' direction='in' name='Uri'/></method>"
  "<signal name='Seeked'><arg type='x' name='Position'/></signal>"
  "<property name='PlaybackStatus' type='s' access='read'/><property name='Rate' type='d' access='readwrite'/>"
  "<property name='Metadata' type='a{sv}' access='read'/><property name='Volume' type='d' access='readwrite'/>"
  "<property name='Position' type='x' access='read'/><property name='MinimumRate' type='d' access='read'/>"
  "<property name='MaximumRate' type='d' access='read'/><property name='CanGoNext' type='b' access='read'/>"
  "<property name='CanGoPrevious' type='b' access='read'/><property name='CanPlay' type='b' access='read'/>"
  "<property name='CanPause' type='b' access='read'/><property name='CanSeek' type='b' access='read'/>"
  "<property name='CanControl' type='b' access='read'/></interface></node>";


static GVariant* property(GDBusConnection* c,const gchar* sender,const gchar* path,const gchar* iface,const gchar* name,GError** error,gpointer data){
    (void)c;(void)sender;(void)path;(void)iface;(void)data;
    GVariant* result=NULL;g_mutex_lock(&gate);
    if(g_str_equal(name,"Identity"))result=g_variant_new_string("EnCap");
    else if(g_str_equal(name,"DesktopEntry"))result=g_variant_new_string("com.tlolabs.encap");
    else if(g_str_equal(name,"CanQuit")||g_str_equal(name,"HasTrackList"))result=g_variant_new_boolean(FALSE);
    else if(g_str_equal(name,"CanRaise")||g_str_equal(name,"CanControl"))result=g_variant_new_boolean(TRUE);
    else if(g_str_has_prefix(name,"Can"))result=g_variant_new_boolean(enabled);
    else if(g_str_equal(name,"SupportedUriSchemes")||g_str_equal(name,"SupportedMimeTypes"))result=g_variant_new_strv(NULL,0);
    else if(g_str_equal(name,"PlaybackStatus"))result=g_variant_new_string(!enabled?"Stopped":playing?"Playing":"Paused");
    else if(g_str_equal(name,"Position"))result=g_variant_new_int64((gint64)(position*G_USEC_PER_SEC));
    else if(g_str_equal(name,"Rate"))result=g_variant_new_double(rate);
    else if(g_str_equal(name,"MinimumRate"))result=g_variant_new_double(-32);
    else if(g_str_equal(name,"MaximumRate"))result=g_variant_new_double(32);
    else if(g_str_equal(name,"Volume"))result=g_variant_new_double(volume);
    else if(g_str_equal(name,"Metadata")){
        GVariantBuilder b;g_variant_builder_init(&b,G_VARIANT_TYPE("a{sv}"));
        gchar* hash=g_compute_checksum_for_string(G_CHECKSUM_SHA256,title?title:"",-1);
        gchar* id=g_strconcat("/org/mpris/MediaPlayer2/track_",hash,NULL);
        g_variant_builder_add(&b,"{sv}","mpris:trackid",g_variant_new_object_path(id));g_free(hash);g_free(id);
        g_variant_builder_add(&b,"{sv}","xesam:title",g_variant_new_string(title?title:""));
        g_variant_builder_add(&b,"{sv}","mpris:length",g_variant_new_int64((gint64)(duration*G_USEC_PER_SEC)));
        result=g_variant_builder_end(&b);
    }else g_set_error(error,G_DBUS_ERROR,G_DBUS_ERROR_UNKNOWN_PROPERTY,"Unknown property");
    g_mutex_unlock(&gate);return result;
}
static void invoke(int code,double value){g_mutex_lock(&gate);action_callback cb=enabled?action:NULL;g_mutex_unlock(&gate);if(cb)cb(code,value);}
static void method(GDBusConnection* c,const gchar* sender,const gchar* path,const gchar* iface,const gchar* name,GVariant* parameters,GDBusMethodInvocation* invocation,gpointer data){
    (void)c;(void)sender;(void)path;(void)iface;(void)data;
    int code=0;double value=0;
    if(g_str_equal(name,"Play"))code=1;else if(g_str_equal(name,"Pause"))code=2;
    else if(g_str_equal(name,"Stop"))code=3;else if(g_str_equal(name,"Next"))code=4;
    else if(g_str_equal(name,"Previous"))code=5;else if(g_str_equal(name,"Raise"))code=7;
    else if(g_str_equal(name,"PlayPause"))code=10;
    else if(g_str_equal(name,"Seek")){gint64 offset;g_variant_get(parameters,"(x)",&offset);g_mutex_lock(&gate);value=CLAMP(position+offset/(double)G_USEC_PER_SEC,0,duration);g_mutex_unlock(&gate);code=6;}
    else if(g_str_equal(name,"SetPosition")){
        const gchar* id;gint64 requested;g_variant_get(parameters,"(&ox)",&id,&requested);
        GVariant* metadata=g_variant_ref_sink(property(NULL,NULL,NULL,NULL,"Metadata",NULL,NULL));
        const gchar* expected=NULL;g_variant_lookup(metadata,"mpris:trackid","&o",&expected);
        g_mutex_lock(&gate);gboolean valid=g_strcmp0(id,expected)==0&&requested>=0&&requested/(double)G_USEC_PER_SEC<=duration;g_mutex_unlock(&gate);g_variant_unref(metadata);
        if(valid){code=6;value=requested/(double)G_USEC_PER_SEC;}
        else{g_dbus_method_invocation_return_value(invocation,NULL);return;}
    }
    if(!code){g_dbus_method_invocation_return_error(invocation,G_DBUS_ERROR,G_DBUS_ERROR_NOT_SUPPORTED,"Action unavailable");return;}
    invoke(code,value);g_dbus_method_invocation_return_value(invocation,NULL);
    if(code==6)g_dbus_connection_emit_signal(bus,NULL,media_path,player_interface,"Seeked",g_variant_new("(x)",(gint64)(value*G_USEC_PER_SEC)),NULL);
}
static gboolean set_property(GDBusConnection* c,const gchar* sender,const gchar* path,const gchar* iface,const gchar* name,GVariant* v,GError** error,gpointer data){
    (void)c;(void)sender;(void)path;(void)iface;(void)data;
    double value=g_variant_get_double(v);
    if(isfinite(value)&&g_str_equal(name,"Rate")&&value>=-32&&value<=32){invoke(value==0?2:8,value);return TRUE;}
    if(isfinite(value)&&g_str_equal(name,"Volume")&&value>=0&&value<=1){invoke(9,value);return TRUE;}
    g_set_error(error,G_DBUS_ERROR,G_DBUS_ERROR_NOT_SUPPORTED,"Value unavailable");return FALSE;
}
static const GDBusInterfaceVTable vtable={.method_call=method,.get_property=property,.set_property=set_property};
static void acquired(GDBusConnection* connection,const gchar* name,gpointer data){(void)name;(void)data;bus=g_object_ref(connection);for(int i=0;i<2;i++)registrations[i]=g_dbus_connection_register_object(bus,media_path,info->interfaces[i],&vtable,NULL,NULL,NULL);}
static gpointer serve(gpointer data){
    (void)data;g_main_context_push_thread_default(context);
    g_mutex_lock(&gate);thread_ready=TRUE;g_cond_signal(&ready);g_mutex_unlock(&gate);
    gchar* name=g_strdup_printf("org.mpris.MediaPlayer2.encap.instance%u",(guint)getpid());
    owner=g_bus_own_name(G_BUS_TYPE_SESSION,name,G_BUS_NAME_OWNER_FLAGS_NONE,acquired,NULL,NULL,NULL,NULL);g_free(name);
    g_main_loop_run(loop);g_bus_unown_name(owner);
    if(bus){for(int i=0;i<2;i++)if(registrations[i])g_dbus_connection_unregister_object(bus,registrations[i]);g_clear_object(&bus);}
    g_main_context_pop_thread_default(context);return NULL;
}
API int encap_media_open(void* window,action_callback cb){
    (void)window;g_mutex_init(&gate);g_cond_init(&ready);thread_ready=FALSE;action=cb;info=g_dbus_node_info_new_for_xml(media_xml,NULL);if(!info)return -1;
    context=g_main_context_new();loop=g_main_loop_new(context,FALSE);thread=g_thread_new("encap-mpris",serve,NULL);g_mutex_lock(&gate);while(!thread_ready)g_cond_wait(&ready,&gate);g_mutex_unlock(&gate);return 0;
}
static gboolean changed(gpointer data){
    (void)data;if(!bus)return G_SOURCE_REMOVE;
    GVariantBuilder b;g_variant_builder_init(&b,G_VARIANT_TYPE("a{sv}"));
    const gchar* names[]={"PlaybackStatus","Metadata","Rate","Volume","CanPlay","CanPause","CanSeek","CanGoNext","CanGoPrevious",NULL};
    for(int i=0;names[i];i++)g_variant_builder_add(&b,"{sv}",names[i],property(NULL,NULL,NULL,NULL,names[i],NULL,NULL));
    g_dbus_connection_emit_signal(bus,NULL,media_path,"org.freedesktop.DBus.Properties","PropertiesChanged",g_variant_new("(sa{sv}as)",player_interface,&b,NULL),NULL);return G_SOURCE_REMOVE;
}
API void encap_media_update(const char* text,double p,double d,double r,int active,int available,double v){
    if(!thread)return;g_mutex_lock(&gate);gboolean notify=g_strcmp0(title,text)!=0||playing!=active||enabled!=available||rate!=r||volume!=v;
    g_free(title);title=g_strdup(text);position=p;duration=d;rate=r;playing=active;enabled=available;volume=v;g_mutex_unlock(&gate);
    if(notify)g_main_context_invoke(context,changed,NULL);
}
static gboolean quit(gpointer data){(void)data;g_main_loop_quit(loop);return G_SOURCE_REMOVE;}
API void encap_media_close(void){if(!thread)return;g_mutex_lock(&gate);action=NULL;g_mutex_unlock(&gate);g_main_context_invoke(context,quit,NULL);g_thread_join(thread);thread=NULL;g_main_loop_unref(loop);g_main_context_unref(context);g_dbus_node_info_unref(info);g_free(title);title=NULL;g_cond_clear(&ready);g_mutex_clear(&gate);}
