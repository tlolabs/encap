#include "main_window.h"
#include "encap_native.h"
#include <QApplication>
#include <QComboBox>
#include <QElapsedTimer>
#include <QFile>
#include <QJsonDocument>
#include <QImage>
#include <QLabel>
#include <QSlider>
#include <QStandardPaths>
#include <QTableWidget>
#include <QTabWidget>
#include <QTemporaryDir>
#include <QThread>
#include <cstdio>

// Deterministic playback clock: these tests need no physical audio device.
namespace { bool playing = false; double position = 0; int openCalls = 0; }
extern "C" {
int encap_audio_open(const char*) { ++openCalls; return 0; }
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

class MainWindowPerformanceTest {
public:
    static bool testChapterLookup(MainWindow& window) {
        window.hasProject_ = true;
        window.project_ = QJsonObject{{"chapters", QJsonArray{
            QJsonObject{{"id", "a"}, {"title", "First A"}, {"duration_seconds", 3}},
            QJsonObject{{"id", "b"}, {"title", "B"}, {"duration_seconds", 4}},
            QJsonObject{{"id", "a"}, {"title", "Duplicate A"}, {"duration_seconds", 99}},
            QJsonObject{{"id", "c"}, {"title", "C"}, {"duration_seconds", 5}}
        }}, {"video", QJsonObject{{"export_settings", QJsonObject{
            {"selected_chapter_ids", QJsonArray{"c", "missing", "a"}},
            {"selection_initialized", true}
        }}}}};
        window.videoOrder_ = {"a", "b", "c", "missing"};
        window.previewIndex_ = 2;
        window.tick();
        if (window.videoSeek_->maximum() != 8 || window.videoSeek_->value() != 5) return false;
        window.refreshVideo();
        if (window.videoChapters_->item(0, 1)->text() != "First A" ||
            window.videoChapters_->item(0, 2)->text() != "00:00:03" ||
            window.videoChapters_->item(0, 0)->checkState() != Qt::Checked ||
            window.videoChapters_->item(1, 0)->checkState() != Qt::Unchecked ||
            window.videoChapters_->item(2, 1)->text() != "C" ||
            !window.videoChapters_->item(3, 1)->text().isEmpty() ||
            !window.videoSummary_->text().startsWith("3 of 4 selected")) return false;
        window.previewIndex_ = 1;
        window.tick();
        if (window.videoSeek_->maximum() != 8 || window.videoSeek_->value() != 0) return false;
        window.setField({"video", "export_settings", "selected_chapter_ids"}, QJsonArray{});
        window.tick();
        if (window.videoSeek_->maximum() != 1 || window.videoSeek_->value() != 0) return false;
        window.recoveryTimer_.stop();
        window.dirty_ = false;
        window.project_ = {};
        window.videoOrder_.clear();
        window.hasProject_ = false;
        window.previewIndex_ = 0;
        return true;
    }

    static int run(const QString& calls) {
        for (const auto& mode : {"legacy", "failure", "malformed", "protocol", "current"}) {
            QFile::remove(calls);
            qputenv("ENCAP_PERF_MODE", mode);
            MainWindow window;
            if (!waitUntil([&] { return !window.busy_; })) return 1;
            QFile log(calls);
            if (!log.open(QIODevice::ReadOnly)) return 2;
            const auto actual = log.readAll();
            if (actual != "startup\n") return 4;
            if (QByteArray(mode) != "current" &&
                !window.status_->accessibleDescription().startsWith("Error:")) return 5;
        }
        qputenv("ENCAP_PERF_MODE", "current");
        auto window = std::make_unique<MainWindow>();
        if (!waitUntil([&] { return !window->busy_; })) return 6;
        if (!testChapterLookup(*window)) return 29;
        // Recovery owns the same client as Save/Open. Reserve the UI before
        // its queued completion, so these actions cannot collide with autosave.
        window->hasProject_ = true;
        window->dirty_ = true;
        QMetaObject::invokeMethod(&window->recoveryTimer_, "timeout", Qt::DirectConnection);
        if (!window->engine_->busy() || !window->busy_ || window->modes_->isEnabled()) return 30;
        bool saved = true;
        window->saveProject(false, [&](bool value) { saved = value; });
        if (saved) return 31;
        if (!waitUntil([&] { return !window->engine_->busy(); }) ||
            window->busy_ || !window->modes_->isEnabled()) return 32;
        window->dirty_ = false;
        window->hasProject_ = false;
        window->recoveryTimer_.stop();
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
        window->project_.insert("metadata", QJsonObject{{"artwork_path", "cover.png"}});
        window->project_.insert("chapters", QJsonArray{QJsonObject{{"id", "one"}, {"chapter_number", 1},
            {"duration_seconds", 1}, {"title", "Intro"}}});
        window->project_.insert("video", QJsonObject{{"export_settings", QJsonObject{
            {"selected_chapter_ids", QJsonArray{"one"}}, {"selection_initialized", true}}}});
        window->loading_ = true;
        window->modes_->setCurrentIndex(2);
        window->loading_ = false;
        window->refreshVideo();
        if (!waitUntil([&] { return window->artworkEngine_->busy(); })) return 15;
        window->setField({"video", "export_settings", "flip_horizontal"}, true);
        window->refreshVideo();
        if (!waitUntil([&] { return !window->artworkEngine_->busy() && !window->videoPreviewPath_.isEmpty(); })) return 16;
        const auto previewPath = window->videoPreviewPath_;
        if (QImage(previewPath).isNull()) return 17;
        window->refreshVideo(); window->refreshVideo();
        if (window->artworkEngine_->busy() || window->videoPreviewPath_ != previewPath) return 18;
        window->setField({"video", "export_settings", "selected_chapter_ids"}, QJsonArray{});
        window->refreshVideo(); window->refreshVideo();
        if (!window->videoPreview_->pixmap().isNull()) return 19;
        window->setField({"video", "export_settings", "selected_chapter_ids"}, QJsonArray{"one"});
        window->refreshVideo();
        window->setField({"video", "export_settings", "flip_horizontal"}, false);
        window->refreshVideo();
        window->setField({"video", "export_settings", "flip_horizontal"}, true);
        window->refreshVideo();
        if (!waitUntil([&] { return !window->artworkEngine_->busy(); })) return 20;
        if (window->videoPreview_->pixmap().isNull()) return 21;
        qputenv("ENCAP_PREVIEW_FAIL", "1");
        window->setField({"video", "export_settings", "flip_vertical"}, true);
        window->refreshVideo(); window->refreshVideo();
        if (!waitUntil([&] { return !window->artworkEngine_->busy(); })) return 22;
        window->refreshVideo();
        if (!window->videoPreviewPath_.isEmpty() || !window->videoPreview_->text().contains("injected preview failure")) return 23;
        qunsetenv("ENCAP_PREVIEW_FAIL");
        window->setField({"video", "export_settings", "flip_vertical"}, false);
        window->refreshVideo();
        if (!waitUntil([&] { return !window->artworkEngine_->busy() && !window->videoPreviewPath_.isEmpty(); })) return 24;
        // Delayed preview/waveform/autosave and native playback entry points
        // must not start work after the updater reserved its exclusion period.
        if (!waitUntil([&] { return !window->linkedWorkActive(); })) return 25;
        QFile::remove(calls);
        const auto priorOpens = openCalls;
        window->updateRunning_ = true;
        window->setField({"video", "export_settings", "flip_vertical"}, true);
        window->refreshVideo();
        QTimer::singleShot(0,window.get(),[&] { window->requestVideoPreview(); });
        window->loadWaveforms();
        window->loadWaveformAt(window->project_.value("audio_sources").toArray(),0,window->waveformGeneration_);
        bool playbackCalled = false, playbackReady = true;
        window->openPlayback("blocked-during-update",[&](bool ready) {playbackCalled=true;playbackReady=ready;});
        playing = false;
        window->togglePlayback();
        window->seekPlayback(0,true);
        window->adjacent(1);
        window->dirty_ = true;
        QMetaObject::invokeMethod(&window->recoveryTimer_,"timeout",Qt::DirectConnection);
        QCoreApplication::processEvents();
        if (!playbackCalled || playbackReady || playing || openCalls != priorOpens || window->linkedWorkActive() || QFile::exists(calls)) return 26;
        playing = true;
        window->togglePlayback(); // Pause remains usable during updater exclusion.
        if (playing) return 27;
        window->dirty_ = false;
        window->recoveryTimer_.stop();
        window->updateRunning_ = false;
        window->refreshVideo();
        if (!waitUntil([&] { return !window->artworkEngine_->busy() && !window->videoPreviewPath_.isEmpty(); })) return 28;
        window->setField({"video", "export_settings", "flip_vertical"}, false);
        window->refreshVideo();
        window.reset(); // shutdown with pending work must never call the destroyed window
        QCoreApplication::processEvents();
        return 0;
    }
};

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    QStandardPaths::setTestModeEnabled(true);
    QCoreApplication::setApplicationName("EnCap Performance Test");
    QTemporaryDir temp;
    qputenv("LOCALAPPDATA", temp.path().toUtf8());
    qputenv("XDG_DATA_HOME", temp.path().toUtf8());
    qputenv("XDG_CONFIG_HOME", temp.path().toUtf8());
    qputenv("ENCAP_TEST_LIBRARY", ENCAP_FAKE_APP_PATH);
    const auto calls = temp.filePath("calls");
    qputenv("ENCAP_PERF_CALLS", calls.toUtf8());
    const int result = MainWindowPerformanceTest::run(calls);
    if (result) std::fprintf(stderr, "Performance regression check %d failed\n", result);
    return result;
}
