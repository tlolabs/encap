#include "engine_client.h"

#include <QJsonDocument>
#include <QJsonArray>
#include <QJsonObject>
#include <QProcessEnvironment>

#ifndef Q_OS_WIN
#include <csignal>
#endif

EngineClient::EngineClient(const QString& executable, const QString& recoveryPath, QObject* parent)
    : QObject(parent), executable_(executable), recoveryPath_(recoveryPath) {}

QJsonValue EngineClient::parseResponse(const QByteArray& output, QString* error) {
    QJsonParseError parseError;
    const auto json = QJsonDocument::fromJson(output, &parseError);
    if (parseError.error != QJsonParseError::NoError || json.isNull()) {
        *error = QStringLiteral("The EnCap engine returned invalid JSON: ") + parseError.errorString();
        return {};
    }
    if (json.isObject()) {
        const auto object = json.object();
        if (object.contains("error")) *error = object.value("error").toString();
        return object;
    }
    if (json.isArray()) return json.array();
    *error = QStringLiteral("The EnCap engine returned an unsupported response.");
    return {};
}

void EngineClient::run(const QStringList& arguments, Completion completed) {
    if (busy()) {
        completed({}, QStringLiteral("Finish the current operation first."));
        return;
    }
    completed_ = std::move(completed);
    process_ = new QProcess(this);
    process_->setProgram(executable_);
    process_->setArguments(arguments);
    auto environment = QProcessEnvironment::systemEnvironment();
    environment.insert("ENCAP_RECOVERY_PATH", recoveryPath_);
    process_->setProcessEnvironment(environment);
    auto* active = process_;
    connect(active, qOverload<int, QProcess::ExitStatus>(&QProcess::finished), this,
            [this, active](int code, QProcess::ExitStatus status) {
        if (process_ != active) return;
        auto* finished = active;
        const QByteArray output = finished->readAllStandardOutput();
        const QString diagnostics = QString::fromUtf8(finished->readAllStandardError()).trimmed();
        QString error;
        QJsonValue result = parseResponse(output, &error);
        if (status != QProcess::NormalExit || code != 0) {
            if (!diagnostics.isEmpty()) error = diagnostics;
            else if (error.isEmpty()) error = QStringLiteral("The EnCap engine failed or was cancelled.");
        }
        process_ = nullptr;
        payload_.reset();
        finished->deleteLater();
        emit busyChanged(false);
        auto callback = std::move(completed_);
        callback(result, error);
    });
    connect(active, &QProcess::errorOccurred, this, [this, active](QProcess::ProcessError code) {
        if (code != QProcess::FailedToStart || process_ != active) return;
        auto* failed = active;
        process_ = nullptr;
        payload_.reset();
        failed->deleteLater();
        emit busyChanged(false);
        auto callback = std::move(completed_);
        callback({}, QStringLiteral("Could not start the EnCap engine."));
    });
    emit busyChanged(true);
    active->start();
}

void EngineClient::runWithPayload(const QStringList& arguments, const QJsonValue& payload, Completion completed) {
    if (busy()) {
        completed({}, QStringLiteral("Finish the current operation first."));
        return;
    }
    payload_ = std::make_unique<QTemporaryFile>();
    if (!payload_->open()) {
        payload_.reset();
        completed({}, QStringLiteral("Could not create the temporary engine payload."));
        return;
    }
    const auto bytes = payload.isArray() ? QJsonDocument(payload.toArray()).toJson(QJsonDocument::Compact)
                                         : QJsonDocument(payload.toObject()).toJson(QJsonDocument::Compact);
    if (payload_->write(bytes) != bytes.size() || !payload_->flush()) {
        payload_.reset();
        completed({}, QStringLiteral("Could not write the temporary engine payload."));
        return;
    }
    QStringList expanded = arguments;
    expanded.replaceInStrings(QStringLiteral("@payload"), payload_->fileName());
    run(expanded, std::move(completed));
}

void EngineClient::cancel() {
    if (!process_) return;
#ifdef Q_OS_WIN
    // taskkill /T closes the complete engine/FFmpeg process tree on Windows.
    QProcess::startDetached(QStringLiteral("taskkill"), {"/T", "/F", "/PID", QString::number(process_->processId())});
#else
    ::kill(static_cast<pid_t>(process_->processId()), SIGINT);
#endif
}

void EngineClient::shutdown() {
    if (!process_) return;
    auto* active = process_;
    disconnect(active, nullptr, this, nullptr);
    cancel();
    process_ = nullptr;
    completed_ = {};
    if (!active->waitForFinished(1000)) {
        active->kill();
        active->waitForFinished(1000);
    }
    delete active;
    payload_.reset();
}
