#include "main_window.h"
#include "engine_client.h"
#include <QApplication>
#include <QCoreApplication>
#include <QDir>
#include <QFileInfo>
#include <QIcon>
#include <QJsonArray>
#include <QJsonDocument>
#include <QStandardPaths>
#include <QTimer>
#include <cstdio>
#include <csignal>
#include <cstring>

#ifdef Q_OS_WIN
#include <io.h>
#define ENCAP_CLOSE _close
#define ENCAP_DUP _dup
#define ENCAP_DUP2 _dup2
#define ENCAP_FILENO _fileno
#define ENCAP_FDOPEN _fdopen
#else
#include <unistd.h>
#define ENCAP_CLOSE close
#define ENCAP_DUP dup
#define ENCAP_DUP2 dup2
#define ENCAP_FILENO fileno
#define ENCAP_FDOPEN fdopen
#endif
// Diagnostic mode alone reserves stdout for its final JSON; provider SDK output
// is directed to stderr without changing normal linked UI process descriptors.
class DiagnosticOutput {
public:
    DiagnosticOutput() {
        std::fflush(stdout);
        const auto descriptor=ENCAP_DUP(ENCAP_FILENO(stdout));
        if(descriptor>=0) {output=ENCAP_FDOPEN(descriptor,"w");if(!output)ENCAP_CLOSE(descriptor);}
        if(output&&ENCAP_DUP2(ENCAP_FILENO(stderr),ENCAP_FILENO(stdout))<0) {std::fclose(output);output=nullptr;}
    }
    ~DiagnosticOutput() {if(output) {std::fflush(stdout);ENCAP_DUP2(ENCAP_FILENO(output),ENCAP_FILENO(stdout));std::fclose(output);}}
    FILE* output=nullptr;
};
namespace { volatile std::sig_atomic_t diagnosticCancelled=0; void requestCancellation(int) {diagnosticCancelled=1;} }
static void identifyApplication() {
    QCoreApplication::setOrganizationName(QStringLiteral("TLO Labs"));
    QCoreApplication::setApplicationName(QStringLiteral("EnCap"));
#ifdef Q_OS_MACOS
    QCoreApplication::setApplicationName(QStringLiteral("EnCap INTERNAL Qt Reference"));
#endif
}
static QString applicationLibrary() {
#ifndef QT_NO_DEBUG
    const auto development=qEnvironmentVariable("ENCAP_APP_LIBRARY");
    if(QFileInfo(development).isAbsolute())return development;
#endif
#ifdef Q_OS_WIN
    return QCoreApplication::applicationDirPath()+"/encap_app.dll";
#elif defined(Q_OS_MACOS)
    return QCoreApplication::applicationDirPath()+"/../Frameworks/libencap_app.dylib";
#else
    return QCoreApplication::applicationDirPath()+"/libencap_app.so";
#endif
}
static QByteArray responseBytes(const QJsonValue& value) {
    if(value.isObject())return QJsonDocument(value.toObject()).toJson(QJsonDocument::Compact);
    if(value.isArray())return QJsonDocument(value.toArray()).toJson(QJsonDocument::Compact);
    auto bytes=QJsonDocument(QJsonArray{value}).toJson(QJsonDocument::Compact);
    return bytes.mid(1,bytes.size()-2);
}
int main(int argc,char** argv) {
    if(argc>1&&std::strcmp(argv[1],"--linked-operation")==0) {
        DiagnosticOutput diagnostic;
        if(!diagnostic.output)return 1;
        QCoreApplication app(argc,argv);
        identifyApplication();
        const auto recovery=QDir(QStandardPaths::writableLocation(QStandardPaths::AppLocalDataLocation)).filePath("recovery.json");
        EngineClient client(applicationLibrary(),recovery);
        const auto previousInterrupt=std::signal(SIGINT,requestCancellation);
        const auto previousTerminate=std::signal(SIGTERM,requestCancellation);
        QTimer cancellation;
        QObject::connect(&cancellation,&QTimer::timeout,&app,[&] {if(diagnosticCancelled)client.cancel();});
        cancellation.start(20);
        QTimer::singleShot(0,&app,[&] {
            client.run(app.arguments().mid(2),[&](const QJsonValue& result,const QString& failure) {
                auto bytes=responseBytes(failure.isEmpty()?result:QJsonValue(QJsonObject{{"error",failure}}));
                bytes.append('\n');
                const auto written=std::fwrite(bytes.constData(),1,static_cast<size_t>(bytes.size()),diagnostic.output);
                const bool valid=written==static_cast<size_t>(bytes.size())&&std::fflush(diagnostic.output)==0;
                app.exit(failure.isEmpty()&&valid?0:1);
            });
        });
        const auto status=app.exec();
        client.shutdown();
        std::signal(SIGINT,previousInterrupt); std::signal(SIGTERM,previousTerminate);
        return status;
    }
    QApplication app(argc,argv);
    identifyApplication();
    app.setWindowIcon(QIcon(QStringLiteral(":/icons/EnCap.png")));
    MainWindow window;
    window.show();
    if(argc>1)window.openInitialPath(QFileInfo(QString::fromLocal8Bit(argv[1])).absoluteFilePath());
    return app.exec();
}
