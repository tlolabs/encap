#include "engine_client.h"
#include <QCoreApplication>
#include <QJsonArray>
#include <QJsonObject>
#include <QEventLoop>
#include <QTimer>
#include <cstdlib>

int main(int argc, char** argv) {
    QCoreApplication app(argc, argv);
    QString error;
    const auto value = EngineClient::parseResponse("{\"path\":\"sample.encap\"}", &error);
    if (!error.isEmpty() || value.toObject().value("path") != "sample.encap") return EXIT_FAILURE;
    error.clear();
    EngineClient::parseResponse("{\"error\":\"invalid project\"}", &error);
    if (error != "invalid project") return EXIT_FAILURE;
    error.clear();
    EngineClient::parseResponse("not json", &error);
    if (error.isEmpty()) return EXIT_FAILURE;
    const auto nullErrVal = EngineClient::parseResponse("{\"path\":\"sample.encap\"}", nullptr);
    if (nullErrVal.toObject().value("path") != "sample.encap") return EXIT_FAILURE;
    const auto invalidNullErr = EngineClient::parseResponse("not json", nullptr);
    if (!invalidNullErr.isNull()) return EXIT_FAILURE;
    const auto executable = qEnvironmentVariable("ENCAP_TEST_ENGINE");
    if (executable.isEmpty()) return EXIT_SUCCESS;
    EngineClient client(executable, QCoreApplication::applicationDirPath() + "/test-recovery.json");
    client.cancel(); // Regress safe idle cancellation (must not signal process group)
    QEventLoop loop;
    QTimer timeout;
    timeout.setSingleShot(true);
    QObject::connect(&timeout, &QTimer::timeout, &loop, &QEventLoop::quit);
    int called = 0;
    QJsonValue result;
    client.run({"build-info"}, [&](const QJsonValue& reply, const QString& failure) {
        ++called;
        result = reply;
        error = failure;
        loop.quit();
    });
    timeout.start(10000);
    loop.exec();
    if (called != 1 || client.busy() || !error.isEmpty() ||
        result.toObject().value("encap_version").toString().isEmpty()) return EXIT_FAILURE;
    return EXIT_SUCCESS;
}
