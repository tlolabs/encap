#pragma once

#include <QJsonValue>
#include <QJsonObject>
#include <QObject>
#include <QTemporaryFile>
#include <functional>
#include <memory>
#include <thread>

class EngineClient final : public QObject {
    Q_OBJECT
public:
    using Completion = std::function<void(const QJsonValue&, const QString&)>;
    explicit EngineClient(const QString& library, const QString& recoveryPath, QObject* parent = nullptr);
    ~EngineClient() override;
    bool busy() const { return active_ != nullptr; }
    void run(const QStringList& arguments, Completion completed);
    void runWithPayload(const QStringList& arguments, const QJsonValue& payload, Completion completed);
    bool unsupportedStartup() const { return false; }
    void cancel();
    // Cancels cooperatively and joins. A codec/driver may delay its return.
    void shutdown();
    static QJsonValue parseResponse(const QByteArray& output, QString* error);
    static QByteArray applicationRequest(const QStringList& arguments, QString* error);

signals:
    void busyChanged(bool busy);
    void transcriptionProgress(const QJsonObject& event);

private:
    struct Library;
    struct Job;
    QString libraryPath_;
    QString recoveryPath_;
    std::shared_ptr<Library> library_;
    std::shared_ptr<Job> active_;
    std::thread worker_;
    std::unique_ptr<QTemporaryFile> payload_;
    Completion completed_;
    quint64 generation_ = 0;
    bool closing_ = false;
};
