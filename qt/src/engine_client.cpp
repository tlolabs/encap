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

void EngineClient::drainDiagnostics(QProcess* process, bool finished) {
    pendingDiagnostics_.append(process->readAllStandardError());
    while (pendingDiagnostics_.contains('\n') || (finished && !pendingDiagnostics_.isEmpty())) {
        const auto end = pendingDiagnostics_.indexOf('\n');
        const auto line = end >= 0 ? pendingDiagnostics_.left(end) : pendingDiagnostics_;
        pendingDiagnostics_.remove(0, end >= 0 ? end + 1 : pendingDiagnostics_.size());
        const auto value = QJsonDocument::fromJson(line);
        if (!discardingDiagnosticLine_ && value.isObject() && value.object().value("event") == "progress") {
            emit transcriptionProgress(value.object());
        } else {
            diagnostics_.append(QString::fromUtf8(line) + '\n');
            // Retain useful bounded diagnostics even if a backend is unusually verbose.
            if (diagnostics_.size() > 1024 * 1024) diagnostics_ = diagnostics_.right(1024 * 1024);
        }
        discardingDiagnosticLine_ = false;
    }
    // An SDK may write an arbitrarily long line without a newline. Bound that
    // partial line too, and never interpret its truncated suffix as an event.
    constexpr qsizetype limit = 1024 * 1024;
    if (pendingDiagnostics_.size() > limit) {
        pendingDiagnostics_ = pendingDiagnostics_.right(limit);
        discardingDiagnosticLine_ = true;
    }
}

QJsonValue EngineClient::parseResponse(const QByteArray& output, QString* error) {
    QJsonParseError parseError;
    const auto json = QJsonDocument::fromJson(output, &parseError);
    if (parseError.error != QJsonParseError::NoError || json.isNull()) {
        if (error) *error = QStringLiteral("The EnCap engine returned invalid JSON: ") + parseError.errorString();
        return {};
    }
    if (json.isObject()) {
        const auto object = json.object();
        if (object.contains("error")) {
            if (error) *error = object.value("error").toString();
        }
        return object;
    }
    if (json.isArray()) return json.array();
    if (error) *error = QStringLiteral("The EnCap engine returned an unsupported response.");
    return {};
}

bool EngineClient::isUnsupportedStartup(int code, QProcess::ExitStatus status, const QString& diagnostics) {
    return status == QProcess::NormalExit && code == 2 &&
        diagnostics.startsWith(QStringLiteral("error: unrecognized subcommand 'startup'\n"));
}

void EngineClient::run(const QStringList& arguments, Completion completed) {
    if (busy()) {
        completed({}, QStringLiteral("Finish the current operation first."));
        return;
    }
    unsupportedStartup_ = false;
    pendingDiagnostics_.clear();
    discardingDiagnosticLine_ = false;
    diagnostics_.clear();
    completed_ = std::move(completed);
    process_ = new QProcess(this);
    process_->setProgram(executable_);
    process_->setArguments(arguments);
    auto environment = QProcessEnvironment::systemEnvironment();
    environment.insert("ENCAP_RECOVERY_PATH", recoveryPath_);
    process_->setProcessEnvironment(environment);
    auto* active = process_;
    connect(active, &QProcess::readyReadStandardError, this, [this, active] {
        if (process_ == active) drainDiagnostics(active);
    });
    connect(active, qOverload<int, QProcess::ExitStatus>(&QProcess::finished), this,
            [this, active, arguments](int code, QProcess::ExitStatus status) {
        if (process_ != active) return;
        auto* finished = active;
        const QByteArray output = finished->readAllStandardOutput();
        drainDiagnostics(finished, true);
        const QString diagnostics = diagnostics_.trimmed();
        unsupportedStartup_ = arguments == QStringList{"startup"} && isUnsupportedStartup(code, status, diagnostics);
        QString error;
        QJsonValue result = parseResponse(output, &error);
        if (status != QProcess::NormalExit || code != 0) {
            if (result.isObject() && result.toObject().value("error").isString()) {
                error = result.toObject().value("error").toString();
            } else if (!diagnostics.isEmpty()) error = diagnostics;
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
    // Only the protocol placeholder is substituted. User paths may legally
    // contain @payload and must reach the engine unchanged.
    for (auto& argument : expanded) {
        if (argument == QStringLiteral("@payload")) argument = payload_->fileName();
    }
    run(expanded, std::move(completed));
}

void EngineClient::cancel() {
    if (!process_ || process_->state() == QProcess::NotRunning) return;
    const auto pid = process_->processId();
    if (pid <= 0) return;
#ifdef Q_OS_WIN
    // taskkill /T closes the complete engine/FFmpeg process tree on Windows.
    QProcess::startDetached(QStringLiteral("taskkill"), {"/T", "/F", "/PID", QString::number(pid)});
#else
    ::kill(static_cast<pid_t>(pid), SIGINT);
#endif
}

void EngineClient::shutdown() {
    if (!process_) return;
    auto* active = process_;
    disconnect(active, nullptr, this, nullptr);
    cancel();
    process_ = nullptr;
    completed_ = {};
    // The engine allows its owned AVID child up to 15 seconds for cooperative
    // cancellation/Metal cleanup before forcing exit. Let that cleanup complete.
    if (!active->waitForFinished(17000)) {
        active->kill();
        active->waitForFinished(1000);
    }
    delete active;
    payload_.reset();
}
