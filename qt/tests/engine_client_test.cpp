#include "engine_client.h"
#include <QCoreApplication>
#include <QJsonArray>
#include <QJsonObject>
#include <QJsonDocument>
#include <QEventLoop>
#include <QTimer>
#include <cstdio>
#include <cstdlib>

int main(int argc, char** argv) {
    QCoreApplication app(argc, argv);
    if (app.arguments().contains("--fake-transcription")) {
        // Backends can emit huge unterminated diagnostics before normal events.
        const QByteArray diagnostic(2 * 1024 * 1024, 'x');
        std::fwrite(diagnostic.constData(), 1, diagnostic.size(), stderr);
        std::fputc('\n', stderr);
        std::fputs("{\"event\":\"progress\",\"stage\":\"verifying\",\"fraction\":0.5}\n", stderr);
        std::fflush(stderr);
        if (app.arguments().contains("--fail")) {
            std::puts("{\"error\":\"Exact model verification failed\"}");
            return 1;
        }
        const auto bytes = QJsonDocument(QJsonObject{{"text", QString(256 * 1024, 'x')}}).toJson(QJsonDocument::Compact);
        std::fwrite(bytes.constData(), 1, bytes.size(), stdout);
        return 0;
    }
    if (app.arguments().contains("--echo-payload-arguments")) {
        const auto bytes = QJsonDocument(QJsonArray::fromStringList(app.arguments().mid(2))).toJson(QJsonDocument::Compact);
        std::fwrite(bytes.constData(), 1, bytes.size(), stdout);
        return 0;
    }
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
    {
        EngineClient fake(QCoreApplication::applicationFilePath(), "unused-recovery");
        QEventLoop pending;
        QTimer limit;
        limit.setSingleShot(true);
        QObject::connect(&limit, &QTimer::timeout, &pending, &QEventLoop::quit);
        int progress = 0;
        QObject::connect(&fake, &EngineClient::transcriptionProgress, &pending, [&](const QJsonObject& event) {
            if (event.value("stage") == "verifying" && event.value("fraction") == 0.5) ++progress;
        });
        bool finished = false;
        fake.run({"--fake-transcription"}, [&](const QJsonValue& result, const QString& failure) {
            finished = failure.isEmpty() && result.toObject().value("text").toString().size() == 256 * 1024;
            pending.quit();
        });
        limit.start(10000);
        pending.exec();
        if (!finished || fake.busy() || progress != 1) return EXIT_FAILURE;
        finished = false;
        fake.runWithPayload({"--echo-payload-arguments", "@payload", "/tmp/user@payload/export.json"},
                            QJsonObject{{"text", "retained"}}, [&](const QJsonValue& result, const QString& failure) {
            const auto arguments = result.toArray();
            finished = failure.isEmpty() && arguments.size() == 2 &&
                arguments[0].toString() != "@payload" && !arguments[0].toString().isEmpty() &&
                arguments[1].toString() == "/tmp/user@payload/export.json";
            pending.quit();
        });
        limit.start(10000);
        pending.exec();
        if (!finished || fake.busy()) return EXIT_FAILURE;
        finished = false;
        fake.run({"--fake-transcription", "--fail"}, [&](const QJsonValue&, const QString& failure) {
            finished = failure == "Exact model verification failed";
            pending.quit();
        });
        limit.start(10000);
        pending.exec();
        if (!finished || fake.busy() || progress != 2) return EXIT_FAILURE;
    }
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
