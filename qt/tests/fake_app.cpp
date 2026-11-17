// Test-only shared ABI fixture. Never linked into an application package.
#include "encap_app.h"
#include <QFile>
#include <QImage>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QThread>
#include <atomic>
#include <cstring>
#include <cstdio>
#include <map>
#include <memory>
#include <mutex>
namespace {
struct Value { enum Kind { App, Token, Buffer } kind; std::atomic<bool> cancelled{false}; QByteArray bytes; explicit Value(Kind type):kind(type) {} };
std::mutex mutex;
std::map<uint64_t,std::shared_ptr<Value>> values;
uint64_t next=1;
uint64_t put(std::shared_ptr<Value> value) {std::lock_guard<std::mutex> lock(mutex); const auto id=next++;values[id]=std::move(value);return id;}
std::shared_ptr<Value> get(uint64_t id) {std::lock_guard<std::mutex> lock(mutex);const auto found=values.find(id);return found==values.end()?nullptr:found->second;}
uint64_t bytes(QByteArray bytes) {auto value=std::make_shared<Value>(Value::Buffer);value->bytes=std::move(bytes);return put(std::move(value));}
uint64_t reply(QJsonValue result) {return bytes(QJsonDocument(QJsonObject{{"schema_version",1},{"ok",true},{"result",result}}).toJson(QJsonDocument::Compact));}
uint64_t fail(QString detail,QString code="fixture") {return bytes(QJsonDocument(QJsonObject{{"schema_version",1},{"ok",false},{"error",QJsonObject{{"code",code},{"detail",detail}}}}).toJson(QJsonDocument::Compact));}
void event(encap_event_callback callback,void* context,QJsonObject value) {if(!callback)return;auto copy=QJsonDocument(value).toJson(QJsonDocument::Compact);callback(context,reinterpret_cast<const uint8_t*>(copy.constData()),static_cast<size_t>(copy.size()));copy.fill('x');}
}
extern "C" {
uint32_t encap_app_abi_version(void) {return qEnvironmentVariableIsSet("ENCAP_FAKE_BAD_ABI")?2:1;}
uint32_t encap_app_schema_version(void) {return 1;}
uint64_t encap_app_create(void) {return put(std::make_shared<Value>(Value::App));}
uint64_t encap_app_create_json(const uint8_t* input,size_t length) {if(!input||length>65536)return 0;const auto config=QJsonDocument::fromJson(QByteArray(reinterpret_cast<const char*>(input),static_cast<int>(length))).object();return config.value("schema_version")==1?encap_app_create():0;}
uint64_t encap_app_cancel_create(void) {return put(std::make_shared<Value>(Value::Token));}
int32_t encap_app_cancel(uint64_t token) {auto value=get(token);if(!value||value->kind!=Value::Token)return -1;value->cancelled=true;return 0;}
int32_t encap_app_release(uint64_t handle) {std::lock_guard<std::mutex> lock(mutex);return values.erase(handle)?0:-1;}
size_t encap_app_buffer_len(uint64_t handle) {const auto value=get(handle);if(!value||value->kind!=Value::Buffer)return 0;if(qEnvironmentVariableIsSet("ENCAP_FAKE_OVERSIZED"))return 64*1024*1024+1;return static_cast<size_t>(value->bytes.size());}
size_t encap_app_buffer_copy(uint64_t handle,uint8_t* output,size_t capacity) {const auto value=get(handle);if(!value||value->kind!=Value::Buffer||!output||capacity<static_cast<size_t>(value->bytes.size()))return 0;std::memcpy(output,value->bytes.constData(),static_cast<size_t>(value->bytes.size()));return static_cast<size_t>(value->bytes.size());}
uint64_t encap_app_execute_json(uint64_t application,uint64_t cancellation,const uint8_t* input,size_t length,encap_event_callback callback,void* context) {
    const auto app=get(application),token=get(cancellation);
    if(!app||app->kind!=Value::App||!token||token->kind!=Value::Token)return fail("Invalid fixture handle");
    if(!input||length>65536)return fail("Invalid fixture request");
    const auto request=QJsonDocument::fromJson(QByteArray(reinterpret_cast<const char*>(input),static_cast<int>(length))).object();
    const auto command=request.value("operation").toString();
    QFile log(qEnvironmentVariable("ENCAP_PERF_CALLS"));
    if(log.open(QIODevice::Append)) {log.write(command.toUtf8()+"\n");log.close();}
    if(command=="startup") {
        const auto mode=qEnvironmentVariable("ENCAP_PERF_MODE");
        if(mode=="legacy")return fail("Unsupported application operation","unsupported_operation");
        if(mode=="failure")return fail("damaged recovery");
        if(mode=="malformed")return reply(QJsonObject{{"providers",42}});
        if(mode=="protocol")return bytes("not json");
        return reply(QJsonObject{{"providers",QJsonArray{}},{"presets",QJsonArray{}},{"recovery",QJsonObject{{"project",QJsonValue::Null}}}});
    }
    if(command=="providers"||command=="video-presets")return reply(QJsonArray{});
    if(command=="load-recovery")return reply(QJsonObject{{"project",QJsonValue::Null}});
    if(command=="waveform"||command=="preview-video") {
        if(qEnvironmentVariableIsSet("ENCAP_FAKE_CHATTER")) {std::puts("SDK diagnostic must stay off JSON stdout");std::fflush(stdout);}
        QThread::msleep(120);
        if(token->cancelled)return fail("Cancelled safely","cancelled");
        if(command=="waveform")return reply(QJsonObject{{"peaks",QJsonArray{request.value("file")=="newest"?1:0}}});
        if(qEnvironmentVariableIsSet("ENCAP_PREVIEW_FAIL"))return fail("injected preview failure");
        QImage image(160,90,QImage::Format_RGB32);image.fill(Qt::red);
        if(!image.save(request.value("output").toString(),"PNG"))return fail("Could not save fixture preview");
        return reply(QJsonObject{});
    }
    if(command=="models") {
        // A borrowed callback buffer is overwritten immediately after return.
        event(callback,context,QJsonObject{{"event","progress"},{"stage","verifying"},{"fraction",0.5},{"message",QString::fromUtf8("Vérification 日本語")}});
        if(qEnvironmentVariableIsSet("ENCAP_FAKE_FAILURE"))return fail("Exact model verification failed");
        return reply(QJsonObject{{"text",QString(256*1024,'x')}});
    }
    if(command=="save") {
        QFile payload(request.value("payload").toString());const bool opened=payload.open(QIODevice::ReadOnly);
        return reply(QJsonObject{{"payload",request.value("payload")},{"project",request.value("project")},{"payload_exists",opened},{"text",opened?QString::fromUtf8(payload.readAll()):QString{}}});
    }
    if(token->cancelled)return fail("Cancelled safely","cancelled");
    if(command=="build-info")return reply(QJsonObject{{"encap_version","test-fixture"}});
    return reply(QJsonObject{});
}
}
