#include "engine_client.h"
#include <QCoreApplication>
#include <QJsonArray>
#include <QJsonObject>
#include <QJsonDocument>
#include <QEventLoop>
#include <QFile>
#include <QTimer>
#include <cstdlib>

int main(int argc,char** argv) {
    QCoreApplication app(argc,argv);
    QString error;
    const auto value=EngineClient::parseResponse(R"({"schema_version":1,"ok":true,"result":{"path":"sample.encap"}})",&error);
    if(!error.isEmpty()||value.toObject().value("path")!="sample.encap")return 1;
    for(const auto& bytes:{QByteArray{"not json"},QByteArray{R"({"schema_version":2,"ok":true,"result":{}})"},QByteArray{R"({"schema_version":1,"ok":true})"}}) {
        error.clear();EngineClient::parseResponse(bytes,&error);if(error.isEmpty())return 2;
    }
    error.clear();EngineClient::parseResponse(R"({"schema_version":1,"ok":false,"error":{"code":"native","detail":"invalid project"}})",&error);
    if(error!="invalid project")return 3;
    if(EngineClient::parseResponse("not json",nullptr).isObject())return 4;
    auto request=QJsonDocument::fromJson(EngineClient::applicationRequest({"transcribe","/tmp/project.json","whisper-large-v3","--word-timestamps","--language","日本語","--alignment-model","aligner"},&error)).object();
    if(request.value("schema_version")!=1||request.value("provider")!="whisper-large-v3"||request.value("word_timestamps")!=true||request.value("language")!=QString::fromUtf8("日本語"))return 5;
    request=QJsonDocument::fromJson(EngineClient::applicationRequest({"inspect-files","--","--literal.wav","/音声.wav"},&error)).object();
    if(request.value("files").toArray()!=QJsonArray{"--literal.wav","/音声.wav"})return 6;
    for(const auto& args:{QStringList{"save","only"},QStringList{"build-info","--language","en"},QStringList{"transcribe","p","m","--language","en","--language","fr"}}) {
        error.clear();if(!EngineClient::applicationRequest(args,&error).isEmpty()||error.isEmpty())return 7;
    }
    EngineClient fake(QString::fromUtf8(ENCAP_FAKE_APP_PATH),"unused-recovery");
    QEventLoop pending;QTimer limit;limit.setSingleShot(true);
    QObject::connect(&limit,&QTimer::timeout,&pending,&QEventLoop::quit);
    int progress=0;
    QObject::connect(&fake,&EngineClient::transcriptionProgress,&pending,[&](const QJsonObject& event) {
        if(event.value("stage")=="verifying"&&event.value("fraction")==0.5&&event.value("message")==QString::fromUtf8("Vérification 日本語"))++progress;
    });
    bool finished=false;
    fake.run({"models"},[&](const QJsonValue& result,const QString& failure) {finished=failure.isEmpty()&&result.toObject().value("text").toString().size()==256*1024;pending.quit();});
    limit.start(10000);pending.exec();if(!finished||fake.busy()||progress!=1)return 8;
    QString payloadPath;
    finished=false;
    fake.runWithPayload({"save","@payload","/tmp/user@payload/export.json"},QJsonObject{{"text","retained"}},[&](const QJsonValue& result,const QString& failure) {
        const auto reply=result.toObject();payloadPath=reply.value("payload").toString();
        finished=failure.isEmpty()&&!payloadPath.isEmpty()&&payloadPath!="@payload"&&reply.value("project")=="/tmp/user@payload/export.json"&&reply.value("payload_exists")==true&&reply.value("text").toString().contains("retained");pending.quit();
    });
    limit.start(10000);pending.exec();if(!finished||fake.busy()||QFile::exists(payloadPath))return 9;
    qputenv("ENCAP_FAKE_FAILURE","1");finished=false;
    fake.run({"models"},[&](const QJsonValue&,const QString& failure) {finished=failure=="Exact model verification failed";pending.quit();});
    limit.start(10000);pending.exec();qunsetenv("ENCAP_FAKE_FAILURE");if(!finished||fake.busy()||progress!=2)return 10;
    qputenv("ENCAP_FAKE_OVERSIZED","1");finished=false;
    fake.run({"build-info"},[&](const QJsonValue&,const QString& failure) {finished=failure.contains("result size");pending.quit();});
    limit.start(10000);pending.exec();qunsetenv("ENCAP_FAKE_OVERSIZED");if(!finished||fake.busy())return 11;
    int called=0;
    fake.run({"waveform","newest"},[&](const QJsonValue&,const QString& failure) {++called;finished=failure=="Cancelled safely";pending.quit();});
    fake.cancel();limit.start(10000);pending.exec();if(!finished||fake.busy()||called!=1)return 12;
    // A cached module must still create fresh cancellation/application handles.
    finished=false;
    fake.run({"build-info"},[&](const QJsonValue& result,const QString& failure) {finished=failure.isEmpty()&&result.toObject().value("encap_version")=="test-fixture";pending.quit();});
    limit.start(10000);pending.exec();if(!finished||fake.busy())return 17;
    // Cache successful loads only: an incompatible module can be repaired and retried
    // on the same client without poisoning other clients or paths.
    EngineClient retry(QString::fromUtf8(ENCAP_FAKE_APP_PATH),"unused-recovery");
    qputenv("ENCAP_FAKE_BAD_ABI","1");
    bool loadFailed=false;
    retry.run({"build-info"},[&](const QJsonValue&,const QString& failure) {loadFailed=!failure.isEmpty();});
    qunsetenv("ENCAP_FAKE_BAD_ABI");
    if(!loadFailed||retry.busy())return 18;
    finished=false;
    retry.run({"build-info"},[&](const QJsonValue& result,const QString& failure) {finished=failure.isEmpty()&&result.toObject().value("encap_version")=="test-fixture";pending.quit();});
    limit.start(10000);pending.exec();if(!finished||retry.busy())return 19;
    bool destroyedCallback=false;
    {
        EngineClient closing(QString::fromUtf8(ENCAP_FAKE_APP_PATH),"unused-recovery");
        closing.run({"waveform","newest"},[&](const QJsonValue&,const QString&) {destroyedCallback=true;});
    }
    QCoreApplication::processEvents();if(destroyedCallback)return 13;
    auto* deletedOnStart=new EngineClient(QString::fromUtf8(ENCAP_FAKE_APP_PATH),"unused-recovery");
    bool deletedStartCallback=false;
    QObject::connect(deletedOnStart,&EngineClient::busyChanged,&pending,[&](bool busy) {
        if(busy) {auto* old=deletedOnStart;deletedOnStart=nullptr;delete old;}
    });
    deletedOnStart->run({"waveform","newest"},[&](const QJsonValue&,const QString&) {deletedStartCallback=true;});
    QCoreApplication::processEvents();if(deletedOnStart||deletedStartCallback)return 16;
    EngineClient reentrant(QString::fromUtf8(ENCAP_FAKE_APP_PATH),"unused-recovery");
    int completions=0;
    bool launchedNext=false;
    QObject::connect(&reentrant,&EngineClient::busyChanged,&pending,[&](bool busy) {
        if(!busy&&!launchedNext) {
            launchedNext=true;
            reentrant.run({"build-info"},[&](const QJsonValue& result,const QString& failure) {
                if(failure.isEmpty()&&result.toObject().value("encap_version")=="test-fixture")++completions;
                if(completions==2)pending.quit();
            });
        }
    });
    reentrant.run({"build-info"},[&](const QJsonValue& result,const QString& failure) {
        if(failure.isEmpty()&&result.toObject().value("encap_version")=="test-fixture")++completions;
        if(completions==2)pending.quit();
    });
    limit.start(10000);pending.exec();if(completions!=2||reentrant.busy())return 15;
    const auto library=qEnvironmentVariable("ENCAP_TEST_LIBRARY");
    if(library.isEmpty())return EXIT_SUCCESS;
    EngineClient client(library,QCoreApplication::applicationDirPath()+"/test-recovery.json");
    client.cancel();called=0;finished=false;
    client.run({"build-info"},[&](const QJsonValue& result,const QString& failure) {++called;finished=failure.isEmpty()&&!result.toObject().value("encap_version").toString().isEmpty();pending.quit();});
    limit.start(10000);pending.exec();if(called!=1||client.busy()||!finished)return 14;
    return EXIT_SUCCESS;
}
