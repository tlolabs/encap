#include "engine_client.h"
#include "encap_app.h"

#include <QJsonDocument>
#include <QJsonArray>
#include <QLibrary>
#include <QMap>
#include <QPointer>
#include <QSet>
#include <stdexcept>

struct EngineClient::Library {
    QLibrary library;
    decltype(&encap_app_create_json) create = nullptr;
    decltype(&encap_app_cancel_create) token = nullptr;
    decltype(&encap_app_cancel) cancel = nullptr;
    decltype(&encap_app_release) release = nullptr;
    decltype(&encap_app_buffer_len) length = nullptr;
    decltype(&encap_app_buffer_copy) copy = nullptr;
    decltype(&encap_app_execute_json) execute = nullptr;
    explicit Library(const QString& path) : library(path) {
        library.setLoadHints(QLibrary::ResolveAllSymbolsHint | QLibrary::PreventUnloadHint);
        if (!library.load()) throw std::runtime_error(library.errorString().toStdString());
#define ENCAP_SYMBOL(member, name) member = reinterpret_cast<decltype(member)>(library.resolve(name)); if (!member) throw std::runtime_error("Incomplete EnCap application ABI")
        auto version = reinterpret_cast<decltype(&encap_app_abi_version)>(library.resolve("encap_app_abi_version"));
        auto schema = reinterpret_cast<decltype(&encap_app_schema_version)>(library.resolve("encap_app_schema_version"));
        if (!version || version() != 1 || !schema || schema() != 1) throw std::runtime_error("Unsupported EnCap application ABI/schema");
        ENCAP_SYMBOL(create, "encap_app_create_json");
        ENCAP_SYMBOL(token, "encap_app_cancel_create");
        ENCAP_SYMBOL(cancel, "encap_app_cancel");
        ENCAP_SYMBOL(release, "encap_app_release");
        ENCAP_SYMBOL(length, "encap_app_buffer_len");
        ENCAP_SYMBOL(copy, "encap_app_buffer_copy");
        ENCAP_SYMBOL(execute, "encap_app_execute_json");
#undef ENCAP_SYMBOL
    }
};
struct EngineClient::Job {
    std::shared_ptr<Library> api;
    encap_handle app = 0;
    encap_handle token = 0;
    Job(std::shared_ptr<Library> library, const QString& recovery) : api(std::move(library)) {
        const auto config = QJsonDocument(QJsonObject{{"schema_version", 1}, {"recovery_path", recovery}}).toJson(QJsonDocument::Compact);
        app = api->create(reinterpret_cast<const uint8_t*>(config.constData()), static_cast<size_t>(config.size()));
        token = api->token();
        if (!app || !token) {
            if (app) api->release(app);
            if (token) api->release(token);
            throw std::runtime_error("Could not create linked application operation");
        }
    }
    ~Job() { api->release(token); api->release(app); }
};

EngineClient::EngineClient(const QString& library, const QString& recoveryPath, QObject* parent)
    : QObject(parent), libraryPath_(library), recoveryPath_(recoveryPath) {}
EngineClient::~EngineClient() { shutdown(); }

QJsonValue EngineClient::parseResponse(const QByteArray& output, QString* error) {
    QJsonParseError parseError;
    const auto json = QJsonDocument::fromJson(output, &parseError);
    if (parseError.error != QJsonParseError::NoError || !json.isObject()) {
        if (error) *error = QStringLiteral("The linked application returned invalid JSON.");
        return {};
    }
    const auto envelope = json.object();
    if (envelope.value("schema_version") != 1 || !envelope.value("ok").isBool()) {
        if (error) *error = QStringLiteral("Unsupported application response schema.");
        return {};
    }
    if (!envelope.value("ok").toBool()) {
        if (error) *error = envelope.value("error").toObject().value("detail").toString("The linked application operation failed.");
        return {};
    }
    if (!envelope.contains("result")) {
        if (error) *error = QStringLiteral("The linked application returned no result.");
        return {};
    }
    return envelope.value("result");
}

QByteArray EngineClient::applicationRequest(const QStringList& arguments, QString* error) {
    static const QMap<QString, QStringList> fields{
        {"inspect", {"folder"}}, {"waveform", {"file"}}, {"inspect-files", {"files"}},
        {"edit-audio", {"payload", "edits"}}, {"open", {"project"}},
        {"save", {"payload", "project"}}, {"export", {"payload", "output"}},
        {"export-video", {"payload", "output"}}, {"inspect-artwork", {"image"}},
        {"optimize-artwork", {"payload", "image", "output"}}, {"preview-video", {"payload", "output"}},
        {"export-transcript", {"payload", "output", "format"}}, {"export-captions", {"payload", "output", "format"}},
        {"transcribe", {"payload", "provider"}}, {"realign", {"payload", "model"}},
        {"install-model", {"model"}}, {"remove-model", {"model"}}, {"verify-model", {"model"}}, {"import-model", {"model", "source"}},
        {"save-recovery", {"payload"}}, {"build-info", {}}, {"startup", {}}, {"video-presets", {}},
        {"video-capabilities", {}}, {"transcription-status", {}}, {"providers", {}}, {"models", {}},
        {"load-recovery", {}}, {"clear-recovery", {}}, {"validate-tools", {}}, {"validate-compatibility-tools", {}}
    };
    static const QMap<QString, QSet<QString>> options{
        {"open", {"extraction-parent"}}, {"preview-video", {"chapter-id"}}, {"export-video", {"render-mode"}},
        {"transcribe", {"word-timestamps", "language", "alignment-model"}}, {"realign", {"language"}}
    };
    auto fail = [&] { if (error) *error = QStringLiteral("Invalid application operation or arguments."); return QByteArray{}; };
    if (arguments.isEmpty() || !fields.contains(arguments.first())) return fail();
    const auto operation = arguments.first();
    QJsonObject request{{"schema_version", 1}, {"operation", operation}};
    QStringList positional;
    bool literal = false;
    for (qsizetype i = 1; i < arguments.size(); ++i) {
        const auto argument = arguments[i];
        if (!literal && argument == "--") { literal = true; continue; }
        if (!literal && argument.startsWith("--")) {
            const auto option = argument.mid(2);
            auto key = option;
            key.replace('-', '_');
            if (!options.value(operation).contains(option) || request.contains(key)) return fail();
            if (option == "word-timestamps") request.insert(key, true);
            else {
                if (++i >= arguments.size()) return fail();
                request.insert(key, arguments[i]);
            }
        } else positional.append(argument);
    }
    if (operation == "inspect-files") {
        if (positional.isEmpty()) return fail();
        request.insert("files", QJsonArray::fromStringList(positional));
    } else {
        const auto names = fields.value(operation);
        if (positional.size() != names.size()) return fail();
        for (qsizetype i = 0; i < names.size(); ++i) request.insert(names[i], positional[i]);
    }
    const auto bytes = QJsonDocument(request).toJson(QJsonDocument::Compact);
    if (bytes.size() > 65536) return fail();
    return bytes;
}

void EngineClient::run(const QStringList& arguments, Completion completed) {
    if (busy() || closing_) { completed({}, QStringLiteral("Finish the current operation first.")); return; }
    QString error;
    const auto request = applicationRequest(arguments, &error);
    if (request.isEmpty()) { payload_.reset(); completed({}, error); return; }
    std::shared_ptr<Job> job;
    try {
        // Cache a successful load per client, keeping failures retryable and
        // configuration/cancellation handles scoped to each operation.
        if (!library_) library_ = std::make_shared<Library>(libraryPath_);
        job = std::make_shared<Job>(library_, recoveryPath_);
    }
    catch (const std::exception& failure) { payload_.reset(); completed({}, QString::fromUtf8(failure.what())); return; }
    if (worker_.joinable()) worker_.join();
    active_ = job;
    completed_ = std::move(completed);
    const auto generation = ++generation_;
    QPointer<EngineClient> receiver(this);
    emit busyChanged(true);
    // A subscriber may synchronously destroy/shut down this client before a
    // worker exists; never launch native work after that lifecycle boundary.
    if (!receiver || closing_ || !active_ || generation_ != generation) return;
    worker_ = std::thread([this, job, request, generation] {
        struct Context { EngineClient* receiver; quint64 generation; } context{this, generation};
        const auto result = job->api->execute(job->app, job->token,
            reinterpret_cast<const uint8_t*>(request.constData()), static_cast<size_t>(request.size()),
            [](void* raw, const uint8_t* bytes, size_t count) {
                if (!bytes || count == 0 || count > 1024 * 1024) return;
                const auto* context = static_cast<Context*>(raw);
                // Callback memory is borrowed. Copy before queued dispatch.
                const QByteArray copy(reinterpret_cast<const char*>(bytes), static_cast<qsizetype>(count));
                const auto event = QJsonDocument::fromJson(copy).object();
                QMetaObject::invokeMethod(context->receiver, [receiver = context->receiver, generation = context->generation, event] {
                    if (receiver->active_ && receiver->generation_ == generation) emit receiver->transcriptionProgress(event);
                }, Qt::QueuedConnection);
            }, &context);
        QByteArray output;
        QString failure;
        if (!result) failure = QStringLiteral("The linked application failed to allocate a result.");
        else {
            const auto size = job->api->length(result);
            if (size == 0 || size > 64 * 1024 * 1024) failure = QStringLiteral("Invalid linked application result size.");
            else {
                output.resize(static_cast<qsizetype>(size));
                if (job->api->copy(result, reinterpret_cast<uint8_t*>(output.data()), size) != size)
                    failure = QStringLiteral("Could not copy the linked application result.");
            }
            job->api->release(result);
        }
        QMetaObject::invokeMethod(this, [this, generation, output, failure] {
            if (!active_ || generation_ != generation) return;
            QString error = failure;
            const auto value = error.isEmpty() ? parseResponse(output, &error) : QJsonValue{};
            if (worker_.joinable()) worker_.join();
            auto callback = std::move(completed_);
            active_.reset();
            payload_.reset();
            QPointer<EngineClient> receiver(this);
            emit busyChanged(false);
            // Signals may destroy this client or start the next generation.
            // The completed operation owns its callback; never steal the next one.
            if (!receiver) return;
            if (callback) callback(value, error);
        }, Qt::QueuedConnection);
    });
}

void EngineClient::runWithPayload(const QStringList& arguments, const QJsonValue& payload, Completion completed) {
    if (busy() || closing_) { completed({}, QStringLiteral("Finish the current operation first.")); return; }
    payload_ = std::make_unique<QTemporaryFile>();
    if (!payload_->open()) { payload_.reset(); completed({}, "Could not create the temporary application payload."); return; }
    const auto bytes = payload.isArray() ? QJsonDocument(payload.toArray()).toJson(QJsonDocument::Compact)
                                         : QJsonDocument(payload.toObject()).toJson(QJsonDocument::Compact);
    if (payload_->write(bytes) != bytes.size() || !payload_->flush()) {
        payload_.reset(); completed({}, "Could not write the temporary application payload."); return;
    }
    QStringList expanded = arguments;
    for (auto& argument : expanded) if (argument == "@payload") argument = payload_->fileName();
    run(expanded, std::move(completed));
}

void EngineClient::cancel() { if (active_) active_->api->cancel(active_->token); }
void EngineClient::shutdown() {
    closing_ = true;
    ++generation_;
    cancel();
    if (worker_.joinable()) worker_.join();
    active_.reset();
    completed_ = {};
    payload_.reset();
}
