#include "main_window.h"

#include <QAccessible>
#include <QAction>
#include <QApplication>
#include <QComboBox>
#include <QCoreApplication>
#include <QDataStream>
#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QFileDialog>
#include <QLabel>
#include <QJsonDocument>
#include <QLineEdit>
#include <QMenuBar>
#include <QDebug>
#include <QPushButton>
#include <QSlider>
#include <QStandardPaths>
#include <QTabWidget>
#include <QTableWidget>
#include <QTemporaryDir>
#include <QThread>
#include <QTimer>

namespace {
bool waitUntil(QApplication& app, const std::function<bool()>& ready) {
    QElapsedTimer elapsed;
    elapsed.start();
    while (elapsed.elapsed() < 10000) {
        app.processEvents();
        if (ready()) return true;
        QThread::msleep(10);
    }
    return false;
}
}

class MainWindowUiTest {
public:
    static bool testSharedTranscriptionControls(MainWindow& window) {
        window.setBusy(false);
        window.hasProject_ = true;
        const auto record = QJsonObject{{"sourceID", "original-audio"}, {"text", "Hello."}};
        const auto previousTranscript = QJsonArray{QJsonObject{{"id", "previous-id"}, {"speaker", "Original speaker"}, {"text", "Saved manual edit."}}};
        const auto warning = QStringLiteral("Some previous manual metadata could not be matched. The previous transcript is retained in project history.");
        window.project_ = QJsonObject{{"transcript_segments", QJsonArray{QJsonObject{
            {"id", "stable-segment"}, {"speaker", "Alice"}, {"text", "Hello."},
            {"words", QJsonArray{QJsonObject{{"id", "stable-word"}, {"text", "Hello."}}}},
            {"opaque_extension", 42},
            {"avid_core", QJsonObject{{"source_id", "source-one"}, {"timing_status", "timed"}, {"transcript", record},
                {"previous_transcript", previousTranscript}, {"reconciliation_warning", warning}}}
        }}}};
        window.loading_ = true;
        window.refreshSegments();
        window.loading_ = false;
        if (window.transcriptWarning_->isHidden() || !window.transcriptWarning_->text().contains(warning)) {
            qWarning() << "persisted reconciliation warning missing";
            return false;
        }
        window.applyTranscriptionStatus(QJsonObject{{"available", true}});
        if (!window.canExportWordCaptions()) { qWarning() << "timed word captions unavailable"; return false; }
        window.segments_->item(0, 0)->setText("Bob");
        auto segment = window.project_.value("transcript_segments").toArray().first().toObject();
        if (segment.value("words").toArray().isEmpty() || segment.value("speaker") != "Bob") { qWarning() << "speaker edit" << segment; return false; }
        window.segments_->item(0, 1)->setText("Corrected text.");
        segment = window.project_.value("transcript_segments").toArray().first().toObject();
        if (!segment.value("words").toArray().isEmpty() || segment.value("id") != "stable-segment" ||
            segment.value("speaker") != "Bob" || segment.value("opaque_extension") != 42) { qWarning() << "text edit" << segment; return false; }
        const auto provenance = segment.value("avid_core").toObject();
        if (provenance.value("timing_status") != "invalidated" || provenance.value("transcript").toObject() != record) { qWarning() << "provenance" << provenance; return false; }
        if (provenance.value("previous_transcript").toArray() != previousTranscript || provenance.value("reconciliation_warning") != warning ||
            window.transcriptWarning_->isHidden()) {
            qWarning() << "reconciliation history changed while editing";
            return false;
        }
        if (window.canExportWordCaptions() || window.wordCaptionSrtButton_->isEnabled() || window.wordCaptionVttButton_->isEnabled()) {
            qWarning() << "invalidated words offered as captions";
            return false;
        }
        auto untimedOrigin = provenance;
        untimedOrigin.insert("timing_status", "untimed");
        segment.insert("avid_core", untimedOrigin);
        window.project_.insert("transcript_segments", QJsonArray{segment});
        window.loading_ = true;
        window.refreshSegments();
        window.loading_ = false;
        window.segments_->item(0, 1)->setText("Edited untimed text.");
        // Exercise the serialized state read by the other host when reopening.
        window.project_ = QJsonDocument::fromJson(QJsonDocument(window.project_).toJson()).object();
        const auto editedUntimed = window.project_.value("transcript_segments").toArray().first().toObject();
        const auto editedUntimedOrigin = editedUntimed.value("avid_core").toObject();
        if (editedUntimedOrigin.value("timing_status") != "untimed" ||
            editedUntimedOrigin.value("transcript").toObject() != record ||
            editedUntimed.value("id") != "stable-segment" || editedUntimed.value("speaker") != "Bob" ||
            !editedUntimed.value("words").toArray().isEmpty() || window.canExportWordCaptions()) {
            qWarning() << "edited untimed text acquired a timing state";
            return false;
        }

        window.setTranscriptionProviders(QJsonArray{
            QJsonObject{{"id", "parakeet-tdt-v3"}, {"name", "Parakeet"}},
            QJsonObject{{"id", "whisper-large-v3"}, {"name", "Whisper full"}}
        });
        if (window.provider_->currentData() != "whisper-large-v3") { qWarning() << "default provider" << window.provider_->currentData(); return false; }
        window.applyTranscriptionStatus(QJsonObject{{"available", true}});
        window.populateModels(QJsonArray{
            QJsonObject{{"id", "aligner"}, {"name", "Qwen alignment"}, {"role", "aligner"},
                {"installed", true}, {"timing_languages", QJsonArray{"en"}}, {"download_allowed", true}}
        });
        if (window.alignmentModel_->count() != 2) { qWarning() << "alignment count"; return false; }
        window.alignmentModel_->setCurrentIndex(1);
        if (!window.realignButton_->isEnabled()) { qWarning() << "realign disabled" << window.busy_ << window.transcriptionAvailable_ << window.hasProject_ << window.alignmentModel_->currentData(); return false; }
        window.project_.insert("transcript_settings", QJsonObject{{"recognition_model_id", "missing-recognizer"}, {"alignment_model_id", "missing-aligner"}});
        window.setTranscriptionProviders(window.providers_);
        window.populateModels(window.models_);
        if (window.provider_->currentIndex() >= 0 || window.alignmentModel_->currentIndex() >= 0 || window.transcribeButton_->isEnabled()) {
            qWarning() << "missing saved model was silently replaced";
            return false;
        }
        window.applyTranscriptionStatus(QJsonObject{{"available", false}, {"reason", "Shared engine is unavailable on this target."}});
        if (window.transcribeButton_->isEnabled() || window.realignButton_->isEnabled() ||
            window.provider_->count() != 0 || window.modelList_->rowCount() != 0 ||
            !window.transcriptionStatus_->text().contains("unavailable")) { qWarning() << "unavailable controls"; return false; }
        window.project_ = QJsonObject{
            {"audio_sources", QJsonArray{QJsonObject{{"id", "retained-audio"}, {"duration_seconds", 60.0}}}},
            {"transcript_segments", QJsonArray{}},
            {"avid_transcript_history", previousTranscript},
            {"avid_reconciliation_warning", warning}
        };
        window.updateTranscriptWarnings();
        if (window.transcriptWarning_->isHidden() || !window.transcriptWarning_->text().contains(warning) ||
            window.project_.value("avid_transcript_history").toArray() != previousTranscript ||
            !window.project_.value("transcript_segments").toArray().isEmpty()) {
            qWarning() << "project-level transcript history warning missing or history mutated";
            return false;
        }
        window.hasProject_ = false;
        window.project_ = {};
        window.updateTranscriptWarnings();
        if (!window.transcriptWarning_->isHidden()) { qWarning() << "stale reconciliation warning"; return false; }
        window.recoveryTimer_.stop();
        return true;
    }
    static bool testBitrateAndChapterRenumbering(MainWindow& window) {
        QComboBox* formatCombo = nullptr;
        QComboBox* channelsCombo = nullptr;
        QComboBox* bitrateCombo = nullptr;
        for (auto* cb : window.findChildren<QComboBox*>()) {
            if (cb->accessibleName() == "Export format") formatCombo = cb;
            else if (cb->accessibleName() == "Audio channels") channelsCombo = cb;
            else if (cb->accessibleName() == "Audio bitrate") bitrateCombo = cb;
        }
        if (!formatCombo || !channelsCombo || !bitrateCombo) return false;

        formatCombo->setCurrentText("mp3");
        channelsCombo->setCurrentText("2");
        window.syncAudioBitrateOptions(false);
        QStringList mp3Bitrates;
        for (int i = 0; i < bitrateCombo->count(); ++i) mp3Bitrates.append(bitrateCombo->itemText(i));
        if (!mp3Bitrates.contains("96k") || !mp3Bitrates.contains("320k")) return false;

        formatCombo->setCurrentText("aac");
        channelsCombo->setCurrentText("2");
        window.syncAudioBitrateOptions(false);
        QStringList aacBitrates;
        for (int i = 0; i < bitrateCombo->count(); ++i) aacBitrates.append(bitrateCombo->itemText(i));
        if (!aacBitrates.contains("64k") || !aacBitrates.contains("320k")) return false;

        window.project_ = QJsonObject{
            {"audio_sources", QJsonArray{
                QJsonObject{{"duration_seconds", 60.0}, {"display_name", "Source 1"}},
                QJsonObject{{"duration_seconds", 40.0}, {"display_name", "Source 2"}},
                QJsonObject{{"duration_seconds", 30.0}, {"display_name", "Source 3"}}
            }},
            {"chapters", QJsonArray{
                QJsonObject{{"id", "c1"}, {"duration_seconds", 30.0}, {"start_time_seconds", 0.0}, {"chapter_number", 1}},
                QJsonObject{{"id", "c2"}, {"duration_seconds", 45.0}, {"start_time_seconds", 30.0}, {"chapter_number", 1}},
                QJsonObject{{"id", "c3"}, {"duration_seconds", 30.0}, {"start_time_seconds", 75.0}, {"chapter_number", 2}}
            }}
        };

        if (window.audioSourceIndexAt(0.0) != 0) return false;
        if (window.audioSourceIndexAt(59.9) != 0) return false;
        if (window.audioSourceIndexAt(60.0) != 1) return false;
        if (window.audioSourceIndexAt(99.9) != 1) return false;
        if (window.audioSourceIndexAt(100.0) != 2) return false;
        if (window.audioSourceIndexAt(150.0) != 2) return false;

        // Test renumberChapters:
        // If chapter c1 was removed, c2 now starts at 0s, and c3 starts at 45.0s (falling into Source 1).
        // Before renumbering, c3 had chapter_number 2.
        window.project_.insert("chapters", QJsonArray{
            QJsonObject{{"id", "c2"}, {"duration_seconds", 45.0}, {"start_time_seconds", 0.0}, {"chapter_number", 1}},
            QJsonObject{{"id", "c3"}, {"duration_seconds", 30.0}, {"start_time_seconds", 45.0}, {"chapter_number", 2}}
        });
        window.renumberChapters();
        auto chapters = window.project_.value("chapters").toArray();
        if (chapters.size() != 2) return false;
        if (chapters[1].toObject().value("chapter_number").toInt() != 1) return false;
        if (chapters[1].toObject().value("start_time_seconds").toDouble() != 45.0) return false;

        // Test audioSourceIndexForChapter with valid and fallback cases:
        QJsonObject validChapter{{"chapter_number", 2}, {"start_time_seconds", 75.0}};
        if (window.audioSourceIndexForChapter(validChapter) != 1) return false;
        QJsonObject invalidChapterMissingNum{{"start_time_seconds", 75.0}};
        if (window.audioSourceIndexForChapter(invalidChapterMissingNum) != 1) return false;
        QJsonObject invalidChapterOutRange{{"chapter_number", 99}, {"start_time_seconds", 10.0}};
        if (window.audioSourceIndexForChapter(invalidChapterOutRange) != 0) return false;

        // Test present purges stale selected_chapter_ids:
        QJsonObject testProject{
            {"working_dir", ""},
            {"audio_sources", QJsonArray{
                QJsonObject{{"duration_seconds", 60.0}, {"display_name", "Source 1"}}
            }},
            {"chapters", QJsonArray{
                QJsonObject{{"id", "valid_c1"}, {"duration_seconds", 30.0}, {"start_time_seconds", 0.0}, {"chapter_number", 1}}
            }},
            {"video", QJsonObject{{"export_settings", QJsonObject{
                {"selected_chapter_ids", QJsonArray{"stale_removed_id", "valid_c1"}},
                {"selection_initialized", true}
            }}}}
        };
        window.present(testProject, false);
        if (window.videoOrder_.contains("stale_removed_id")) return false;
        if (!window.videoOrder_.contains("valid_c1")) return false;
        auto cleanedSelected = window.field({"video", "export_settings", "selected_chapter_ids"}).toArray();
        if (cleanedSelected.size() != 1 || cleanedSelected[0].toString() != "valid_c1") return false;

        // Reset project_ to clean state so subsequent tests run cleanly
        window.project_ = QJsonObject{};
        window.hasProject_ = false;

        return true;
    }
};

int main(int argc, char** argv) {
    QCoreApplication::setAttribute(Qt::AA_DontUseNativeDialogs);
    QApplication app(argc, argv);
    QCoreApplication::setOrganizationName("TLO Labs");
    QCoreApplication::setApplicationName("EnCap Qt Test");
    QStandardPaths::setTestModeEnabled(true);
    MainWindow window;
    window.show();
    app.processEvents();
    auto* modes = window.findChild<QTabWidget*>();
    if (!modes || modes->count() != 3 || !window.menuBar() || window.menuBar()->actions().size() < 3)
        return 1;
    int namedTables = 0;
    for (auto* table : window.findChildren<QTableWidget*>()) {
        if (table->accessibleName().isEmpty()) continue;
        if (!QAccessible::queryAccessibleInterface(table)) return 2;
        ++namedTables;
    }
    if (namedTables < 3) return 3;

    // Verify QSlider accessible names and interfaces (ENC-A01, ENC-A03)
    QSlider* sourceSeek = nullptr;
    QSlider* videoSeek = nullptr;
    for (auto* slider : window.findChildren<QSlider*>()) {
        if (slider->accessibleName() == "Recording position") sourceSeek = slider;
        else if (slider->accessibleName() == "Video timeline position") videoSeek = slider;
        if (!QAccessible::queryAccessibleInterface(slider)) return 20;
    }
    if (!sourceSeek || !videoSeek) return 21;

    // Verify slider responds to keyboard / single-step actions (ENC-A01)
    sourceSeek->setMaximum(100);
    sourceSeek->setValue(10);
    sourceSeek->triggerAction(QAbstractSlider::SliderSingleStepAdd);
    if (sourceSeek->value() != 11) return 22;

    // Verify ComboBox accessible names and interfaces (ENC-A03)
    const QStringList requiredCombos = {
        "Export format", "Audio channels", "Audio bitrate", "Chapter naming style", "Preview quality"
    };
    int foundCombos = 0;
    for (auto* cb : window.findChildren<QComboBox*>()) {
        if (requiredCombos.contains(cb->accessibleName())) {
            if (!QAccessible::queryAccessibleInterface(cb)) return 23;
            ++foundCombos;
        }
    }
    if (foundCombos < requiredCombos.size()) return 24;

    if (!MainWindowUiTest::testBitrateAndChapterRenumbering(window)) return 25;
    if (!MainWindowUiTest::testSharedTranscriptionControls(window)) return 26;

    modes->setCurrentIndex(2);
    app.processEvents();
    if (modes->currentIndex() != 2) return 4;
    if (qEnvironmentVariable("ENCAP_TEST_ENGINE").isEmpty()) return 0;
    QTemporaryDir folder;
    if (!folder.isValid()) return 5;
    QByteArray wav;
    QDataStream stream(&wav, QIODevice::WriteOnly);
    stream.setByteOrder(QDataStream::LittleEndian);
    stream.writeRawData("RIFF", 4);
    stream << quint32(36 + 44100 * 2 * 2);
    stream.writeRawData("WAVEfmt ", 8);
    stream << quint32(16) << quint16(1) << quint16(2) << quint32(44100)
           << quint32(44100 * 2 * 2) << quint16(4) << quint16(16);
    stream.writeRawData("data", 4);
    stream << quint32(44100 * 2 * 2);
    wav.append(QByteArray(44100 * 2 * 2, '\0'));
    QFile recording(folder.path() + "/001.wav");
    if (!recording.open(QIODevice::WriteOnly) || recording.write(wav) != wav.size()) return 6;
    recording.close();
    auto findTable = [&window](const QString& name) {
        for (auto* table : window.findChildren<QTableWidget*>())
            if (table->accessibleName() == name) return table;
        return static_cast<QTableWidget*>(nullptr);
    };
    auto* sources = findTable("Source recordings");
    auto* chapters = findTable("Project chapters");
    if (!sources || !chapters) return 7;
    window.openInitialPath(folder.path());
    if (!waitUntil(app, [&] { return sources->rowCount() == 1 && chapters->rowCount() == 1; })) {
        qWarning() << "Import failed" << sources->rowCount() << chapters->rowCount();
        return 8;
    }
    const auto savePath = folder.path() + "/episode.encap";
    QAction* save = nullptr;
    for (auto* action : window.findChildren<QAction*>())
        if (action->text() == "&Save") { save = action; break; }
    if (!save) return 9;
    QTimer picker;
    QObject::connect(&picker, &QTimer::timeout, &window, [&] {
        for (auto* widget : QApplication::topLevelWidgets()) {
            if (auto* dialog = qobject_cast<QFileDialog*>(widget)) {
                picker.stop();
                dialog->setDirectory(folder.path());
                dialog->selectFile("episode.encap");
                if (auto* filename = dialog->findChild<QLineEdit*>("fileNameEdit"))
                    filename->setText("episode.encap");
                static_cast<QDialog*>(dialog)->accept();
                return;
            }
        }
    });
    picker.start(20);
    QTimer::singleShot(10000, &window, [] {
        for (auto* widget : QApplication::topLevelWidgets())
            if (auto* dialog = qobject_cast<QFileDialog*>(widget)) dialog->reject();
    });
    save->trigger();
    picker.stop();
    if (!waitUntil(app, [&] { return QFile::exists(savePath); })) {
        qWarning() << "Saved folder entries:" << QDir(folder.path()).entryList(QDir::Files);
        for (auto* label : window.findChildren<QLabel*>())
            if (label->accessibleName() == "Application status") qWarning() << "Save failed:" << label->text();
        return 10;
    }
    QLabel* status = nullptr;
    for (auto* label : window.findChildren<QLabel*>())
        if (label->accessibleName() == "Application status") { status = label; break; }
    if (!status) return 11;
    window.openInitialPath(savePath);
    if (!waitUntil(app, [&] {
        return status->text().startsWith("Loaded") &&
            sources->rowCount() == 1 && chapters->rowCount() == 1;
    })) return 12;
    return 0;
}
