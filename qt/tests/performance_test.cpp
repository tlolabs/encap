#include "main_window.h"
#include "encap_native.h"
#include <QApplication>
#include <QComboBox>
#include <QElapsedTimer>
#include <QFile>
#include <QJsonDocument>
#include <QLabel>
#include <QSlider>
#include <QStandardPaths>
#include <QTableWidget>
#include <QTemporaryDir>
#include <QThread>
#include <cstdio>

// Deterministic playback clock: these tests need no physical audio device.
namespace { bool playing = false; double position = 0; }
extern "C" {
int encap_audio_open(const char*) { return 0; }
void encap_audio_play(double) { playing = true; }
void encap_audio_pause() { playing = false; }
void encap_audio_seek(double value) { position = value; }
double encap_audio_position() { return position; }
int encap_audio_playing() { return playing; }
void encap_audio_close() { playing = false; position = 0; }
void encap_audio_volume(double) {}
}

static bool waitUntil(const std::function<bool()>& ready) {
    QElapsedTimer timer;
    timer.start();
    do {
        QCoreApplication::processEvents();
        if (ready()) return true;
        QThread::msleep(5);
    } while (timer.elapsed() < 5000);
    return false;
}

// Re-execute this test as a controllable engine, including the old Clap error.
static int fakeEngine(const QStringList& args) {
    const auto command = args.value(1);
    const auto mode = qEnvironmentVariable("ENCAP_PERF_MODE");
    QFile log(qEnvironmentVariable("ENCAP_PERF_CALLS"));
    if (log.open(QIODevice::Append)) { log.write(command.toUtf8() + "\n"); log.close(); }
    if (command == "startup") {
        if (mode == "legacy") {
            std::fputs("error: unrecognized subcommand 'startup'\n\nUsage: engine <COMMAND>\n", stderr);
            return 2;
        }
        if (mode == "failure") { std::puts("{\"error\":\"damaged recovery\"}"); return 1; }
        if (mode == "malformed") { std::puts("{\"providers\":42}"); return 0; }
        if (mode == "protocol") { std::puts("not json"); return 0; }
        std::puts("{\"providers\":[],\"presets\":[],\"recovery\":{\"project\":null}}");
    } else if (command == "providers" || command == "video-presets") std::puts("[]");
    else if (command == "load-recovery") std::puts("{\"project\":null}");
    else if (command == "waveform") {
        QThread::msleep(120);
        std::puts(args.last() == "newest" ? "{\"peaks\":[1]}" : "{\"peaks\":[0]}");
    } else std::puts("{}");
    return 0;
}

class MainWindowPerformanceTest {
public:
    static int run(const QString& calls) {
        for (const auto& mode : {"legacy", "failure", "malformed", "protocol", "current"}) {
            QFile::remove(calls);
            qputenv("ENCAP_PERF_MODE", mode);
            MainWindow window;
            if (!waitUntil([&] { return !window.busy_; })) return 1;
            QFile log(calls);
            if (!log.open(QIODevice::ReadOnly)) return 2;
            const auto actual = log.readAll();
            if (QByteArray(mode) == "legacy") {
                if (actual != "startup\nproviders\nvideo-presets\nload-recovery\n") return 3;
            } else if (actual != "startup\n") return 4;
            if (QByteArray(mode) != "legacy" && QByteArray(mode) != "current" &&
                !window.status_->accessibleDescription().startsWith("Error:")) return 5;
        }
        qputenv("ENCAP_PERF_MODE", "current");
        auto window = std::make_unique<MainWindow>();
        if (!waitUntil([&] { return !window->busy_; })) return 6;
        window->setStatus("same message", true);
        window->setStatus("same message", false);
        if (!window->status_->styleSheet().isEmpty() || window->status_->accessibleDescription() != "same message") return 14;
        window->hasProject_ = true;
        window->project_.insert("audio_sources", QJsonArray{QJsonObject{{"source_path", "newest"}, {"duration_seconds", 600}}});
        window->sources_->setRowCount(1);
        auto* item = new QTableWidgetItem("newest");
        item->setData(Qt::UserRole, "newest");
        window->sources_->setItem(0, 0, item);
        window->sources_->setItem(0, 1, new QTableWidgetItem);
        window->sources_->selectRow(0);
        window->playingPath_ = "newest";
        position = 350;
        playing = true;
        window->tick();
        if (window->clock_.interval() != 100 || window->sourceSeek_->value() != 350) return 7;
        window->pausePlayback();
        window->togglePlayback();
        if (window->clock_.interval() != 100) return 13;
        window->pausePlayback();
        if (window->clock_.interval() != 1000) return 8;
        window->seekPlayback(125);
        if (window->sourceSeek_->value() != 125 || !window->sourceTime_->text().startsWith("00:02:05")) return 9;
        int changes = 0;
        QObject::connect(window->sourceSeek_, &QSlider::valueChanged, [&] { ++changes; });
        window->tick(); window->tick();
        if (changes != 0) return 10;
        window->project_.insert("audio_sources", QJsonArray{QJsonObject{{"source_path", "obsolete"}}});
        window->loadWaveforms();
        if (!waitUntil([&] { return window->waveformEngine_->busy(); })) return 11;
        window->project_.insert("audio_sources", QJsonArray{QJsonObject{{"source_path", "middle"}}});
        window->loadWaveforms();
        window->project_.insert("audio_sources", QJsonArray{QJsonObject{{"source_path", "newest"}}});
        window->loadWaveforms();
        if (!waitUntil([&] { return !window->waveformEngine_->busy() && window->sources_->item(0, 1)->text() == QString::fromUtf8("█"); })) return 12;
        window->loadWaveforms();
        window.reset(); // shutdown with pending work must never call the destroyed window
        QCoreApplication::processEvents();
        return 0;
    }
};

int main(int argc, char** argv) {
    if (argc > 1) {
        QStringList args;
        for (int i = 0; i < argc; ++i) args.append(QString::fromLocal8Bit(argv[i]));
        return fakeEngine(args);
    }
    QApplication app(argc, argv);
    QStandardPaths::setTestModeEnabled(true);
    QCoreApplication::setApplicationName("EnCap Performance Test");
    QTemporaryDir temp;
    qputenv("LOCALAPPDATA", temp.path().toUtf8());
    qputenv("XDG_DATA_HOME", temp.path().toUtf8());
    qputenv("XDG_CONFIG_HOME", temp.path().toUtf8());
    qputenv("ENCAP_TEST_ENGINE", QCoreApplication::applicationFilePath().toUtf8());
    const auto calls = temp.filePath("calls");
    qputenv("ENCAP_PERF_CALLS", calls.toUtf8());
    const int result = MainWindowPerformanceTest::run(calls);
    if (result) std::fprintf(stderr, "Performance regression check %d failed\n", result);
    return result;
}
