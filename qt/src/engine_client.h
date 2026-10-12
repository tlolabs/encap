#pragma once

#include <QJsonValue>
#include <QObject>
#include <QProcess>
#include <QTemporaryFile>
#include <functional>
#include <memory>

class EngineClient final : public QObject {
    Q_OBJECT
public:
    using Completion = std::function<void(const QJsonValue&, const QString&)>;
    explicit EngineClient(const QString& executable, const QString& recoveryPath, QObject* parent = nullptr);
    bool busy() const { return process_ != nullptr; }
    void run(const QStringList& arguments, Completion completed);
    void runWithPayload(const QStringList& arguments, const QJsonValue& payload, Completion completed);
    void cancel();
    void shutdown();
    static QJsonValue parseResponse(const QByteArray& output, QString* error);

signals:
    void busyChanged(bool busy);

private:
    QString executable_;
    QString recoveryPath_;
    QProcess* process_ = nullptr;
    std::unique_ptr<QTemporaryFile> payload_;
    Completion completed_;
};
