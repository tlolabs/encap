#include "main_window.h"
#include "encap_native.h"

#include <QAction>
#include <QActionGroup>
#include <QAccessible>
#include <QApplication>
#include <QCheckBox>
#include <QCloseEvent>
#include <QComboBox>
#include <QDateTime>
#include <QDir>
#include <QDragEnterEvent>
#include <QDropEvent>
#include <QEventLoop>
#include <QFile>
#include <QFileDialog>
#include <QFileInfo>
#include <QFormLayout>
#include <QGroupBox>
#include <QHeaderView>
#include <QHBoxLayout>
#include <QJsonDocument>
#include <QKeyEvent>
#include <QLabel>
#include <QLineEdit>
#include <QMenuBar>
#include <QMessageBox>
#include <QMimeData>
#include <QPlainTextEdit>
#include <QPainter>
#include <QProcess>
#include <QRegularExpression>
#include <QSaveFile>
#include <QProgressBar>
#include <QPushButton>
#include <QScrollArea>
#include <QSettings>
#include <QSlider>
#include <QSpinBox>
#include <QSplitter>
#include <QStandardPaths>
#include <QStatusBar>
#include <QTabWidget>
#include <QTableWidget>
#include <QTemporaryFile>
#include <QUrl>
#include <QUuid>
#include <QVBoxLayout>

#include <algorithm>
#include <cmath>

namespace {
QWidget* row(std::initializer_list<QWidget*> children) {
    auto* widget = new QWidget;
    auto* layout = new QHBoxLayout(widget);
    layout->setContentsMargins(0, 0, 0, 0);
    for (auto* child : children) layout->addWidget(child);
    layout->addStretch();
    return widget;
}
QPushButton* button(const QString& label, const std::function<void()>& action) {
    auto* control = new QPushButton(label);
    QObject::connect(control, &QPushButton::clicked, control, [action] { action(); });
    return control;
}
QComboBox* combo(const QStringList& values) {
    auto* control = new QComboBox;
    control->addItems(values);
    return control;
}
QString shownTime(double seconds) {
    const int whole = std::max(0, static_cast<int>(seconds));
    return QStringLiteral("%1:%2:%3").arg(whole / 3600, 2, 10, QChar('0'))
        .arg((whole / 60) % 60, 2, 10, QChar('0')).arg(whole % 60, 2, 10, QChar('0'));
}
QJsonObject replacePath(QJsonObject object, const QStringList& path, const QJsonValue& value) {
    if (path.size() == 1) object.insert(path.front(), value);
    else object.insert(path.front(), replacePath(object.value(path.front()).toObject(), path.mid(1), value));
    return object;
}
QString pathString(const QJsonObject& object, const QStringList& path) {
    QJsonValue value(object);
    for (const auto& key : path) value = value.toObject().value(key);
    return value.toString();
}
bool isAudioFile(const QString& path) {
    return QStringList{"wav", "wave", "aif", "aiff", "aifc"}.contains(QFileInfo(path).suffix().toLower());
}
} // namespace

MainWindow* MainWindow::mediaOwner_ = nullptr;

MainWindow::MainWindow() {
    QDir().mkpath(dataDirectory());
    QDir().mkpath(QFileInfo(preferencePath("automatic-updates-disabled")).absolutePath());
    QDir().mkpath(QFileInfo(preferencePath("chapter-naming.txt")).absolutePath());
    engine_ = new EngineClient(enginePath(), preferencePath("recovery.json"), this);
    previewEngine_ = new EngineClient(enginePath(), preferencePath("recovery.json"), this);
    waveformEngine_ = new EngineClient(enginePath(), preferencePath("recovery.json"), this);
    buildUi();
    buildMenus();
    QFile naming(preferencePath("chapter-naming.txt"));
    if (naming.open(QIODevice::ReadOnly)) {
        const auto saved = QString::fromUtf8(naming.readAll()).trimmed();
#ifdef Q_OS_LINUX
        const auto match = QRegularExpression("(?:^|\\n)style=([0-3])(?:\\n|$)").match(saved);
        if (match.hasMatch()) naming_->setCurrentIndex(match.captured(1).toInt());
#else
        const auto names = QStringList{"Original", "Numbered", "Time", "Custom"};
        const auto index = names.indexOf(saved);
        if (index >= 0) naming_->setCurrentIndex(index);
#endif
    }
    setAcceptDrops(true);
    setMinimumSize(800, 580);
    resize(1180, 820);
    updateTitle();
    recoveryTimer_.setSingleShot(true);
    recoveryTimer_.setInterval(1000);
    connect(&recoveryTimer_, &QTimer::timeout, this, [this] {
        if (dirty_ && hasProject_ && !busy_)
            engine_->runWithPayload({"save-recovery", "@payload"}, project_, [this](const QJsonValue&, const QString& error) {
                if (!error.isEmpty()) fail(error);
            });
        else if (dirty_ && busy_) recoveryTimer_.start();
    });
    clock_.setInterval(100);
    connect(&clock_, &QTimer::timeout, this, &MainWindow::tick);
    clock_.start();
    updateTimer_.setInterval(60 * 60 * 1000);
    connect(&updateTimer_, &QTimer::timeout, this, [this] { if (automaticUpdates_->isChecked()) checkUpdates(false); });
    updateTimer_.start();
    const auto preference = QFile(preferencePath("appearance.txt"));
    QFile appearance(preference.fileName());
    if (appearance.open(QIODevice::ReadOnly)) setAppearance(QString::fromUtf8(appearance.readAll()).trimmed());
    else setAppearance("system");

#ifdef ENCAP_HAS_MEDIA_SESSION
    QTimer::singleShot(0, this, [this] {
        mediaOwner_ = this;
        if (encap_media_open(reinterpret_cast<void*>(winId()), &MainWindow::mediaAction) != 0)
            setStatus("System media controls are unavailable; playback controls remain available.");
    });
#endif
    runEngine("Loading local engines and recovery…", {"providers"}, [this](const QJsonValue& result) {
        providers_ = result.toArray();
        provider_->clear();
        for (const auto& entry : providers_) provider_->addItem(entry.toObject().value("name").toString(), entry.toObject().value("id"));
        runEngine("Loading video presets…", {"video-presets"}, [this](const QJsonValue& presets) {
            presets_ = presets.toArray();
            preset_->clear();
            for (const auto& entry : presets_) {
                const auto value = entry.toObject();
                preset_->addItem(QStringLiteral("%1 — %2 — %3 × %4").arg(value.value("platform").toString(), value.value("aspect").toString())
                    .arg(value.value("width").toInt()).arg(value.value("height").toInt()));
            }
            runEngine("Loading recovery…", {"load-recovery"}, [this](const QJsonValue& recovery) {
                const auto previous = recovery.toObject().value("project");
                if (previous.isObject()) {
                    present(previous.toObject(), true);
                    setStatus("Recovered unsaved work from the previous session.");
                } else setStatus("Import an audio folder or open a project to begin.");
#ifdef Q_OS_WIN
                const auto acknowledgement = qEnvironmentVariable("ENCAP_UPDATE_STARTUP_ACK");
                if (!acknowledgement.isEmpty()) {
                    QFile ready(acknowledgement);
                    if (ready.open(QIODevice::WriteOnly)) ready.write("ready");
                }
#endif
            });
        });
    });
    if (!internalReference() && automaticUpdates_->isChecked())
        QTimer::singleShot(3000, this, [this] { checkUpdates(false); });
}

bool MainWindow::internalReference() const {
#ifdef Q_OS_MACOS
    return true;
#else
    return false;
#endif
}

QString MainWindow::dataDirectory() const {
#ifdef Q_OS_WIN
    return qEnvironmentVariable("LOCALAPPDATA") + "/com.tlolabs.encap";
#elif defined(Q_OS_LINUX)
    const auto base = qEnvironmentVariable("XDG_DATA_HOME", QDir::homePath() + "/.local/share");
    return base + "/com.tlolabs.encap";
#else
    return QStandardPaths::writableLocation(QStandardPaths::AppLocalDataLocation) + "/qt-reference";
#endif
}
QString MainWindow::preferencePath(const QString& name) const {
#ifdef Q_OS_LINUX
    if (name == "chapter-naming.txt" && !internalReference())
        return qEnvironmentVariable("XDG_CONFIG_HOME", QDir::homePath() + "/.config") + "/encap/chapter-naming.ini";
    if (name == "automatic-updates-disabled" && !internalReference())
        return qEnvironmentVariable("XDG_CONFIG_HOME", QDir::homePath() + "/.config") + "/com.tlolabs.encap/automatic-updates-disabled";
#elif defined(Q_OS_WIN)
    if (name == "chapter-naming.txt")
        return qEnvironmentVariable("LOCALAPPDATA") + "/EnCap/chapter-naming.txt";
#endif
    return dataDirectory() + "/" + name;
}
QString MainWindow::enginePath() const {
    return QCoreApplication::applicationDirPath() + "/encap-engine"
#ifdef Q_OS_WIN
        ".exe"
#endif
        ;
}
QString MainWindow::updaterPath() const {
    return QCoreApplication::applicationDirPath() + "/encap-update"
#ifdef Q_OS_WIN
        ".exe"
#endif
        ;
}

void MainWindow::runEngine(const QString& message, const QStringList& arguments, Result result,
                           const QJsonValue& payload, std::function<void()> failed) {
    if (busy_) return;
    setBusy(true);
    setStatus(message);
    auto completed = [this, result, failed](const QJsonValue& value, const QString& error) {
        setBusy(false);
        if (!error.isEmpty()) { fail(error); if (failed) failed(); return; }
        result(value);
    };
    if (payload.isUndefined() || payload.isNull()) engine_->run(arguments, std::move(completed));
    else engine_->runWithPayload(arguments, payload, std::move(completed));
}
void MainWindow::setBusy(bool busy) {
    busy_ = busy;
    progress_->setVisible(busy);
    if (busy) progress_->setRange(0, 0);
    cancel_->setVisible(busy);
    modes_->setEnabled(!busy);
    if (saveAction_) saveAction_->setEnabled(!busy && hasProject_);
}
void MainWindow::setStatus(const QString& message, bool error) {
    status_->setText(message);
    status_->setStyleSheet(error ? "color: #a11919;" : "");
    status_->setAccessibleDescription(error ? "Error: " + message : message);
    QAccessibleEvent changed(status_, QAccessible::DescriptionChanged);
    QAccessible::updateAccessibility(&changed);
}
void MainWindow::fail(const QString& error) { setStatus(error, true); }
void MainWindow::updateTitle() {
    const QString episode = project_.value("metadata").toObject().value("episode_title").toString();
    setWindowTitle((internalReference() ? "EnCap — INTERNAL Qt Reference" : "EnCap")
                   + (hasProject_ && !episode.isEmpty() ? " — " + episode : "") + (dirty_ ? " *" : ""));
}
QJsonValue MainWindow::field(const QStringList& path) const {
    QJsonValue value(project_);
    for (const auto& key : path) value = value.toObject().value(key);
    return value;
}
void MainWindow::setField(const QStringList& path, const QJsonValue& value) {
    if (loading_ || !hasProject_ || field(path) == value) return;
    project_ = replacePath(project_, path, value);
    markDirty();
}
void MainWindow::markDirty() {
    if (loading_ || !hasProject_) return;
    dirty_ = true;
    updateTitle();
    recoveryTimer_.start();
}
void MainWindow::present(const QJsonObject& project, bool changed) {
    pausePlayback();
    encap_audio_close();
    playingPath_.clear();
    previewIndex_ = 0;
    recoveryTimer_.stop();
    project_ = project;
    ++waveformGeneration_;
    hasProject_ = true;
    dirty_ = changed;
    videoOrder_.clear();
    const auto chapters = project_.value("chapters").toArray();
    const auto selected = field({"video", "export_settings", "selected_chapter_ids"}).toArray();
    for (const auto& value : selected) videoOrder_.append(value.toString());
    for (const auto& value : chapters) {
        const auto id = value.toObject().value("id").toString();
        if (!videoOrder_.contains(id)) videoOrder_.append(id);
    }
    if (!field({"video", "export_settings", "selection_initialized"}).toBool()) {
        QJsonArray all;
        for (const auto& id : videoOrder_) all.append(id);
        project_ = replacePath(project_, {"video", "export_settings", "selected_chapter_ids"}, all);
        project_ = replacePath(project_, {"video", "export_settings", "selection_initialized"}, true);
    }
    refreshUi();
    if (changed) recoveryTimer_.start();
    setStatus(QStringLiteral("Loaded %1 recordings.").arg(project_.value("audio_sources").toArray().size()));
    loadWaveforms();
}
void MainWindow::refreshUi() {
    if (!hasProject_) return;
    loading_ = true;
    const auto metadata = project_.value("metadata").toObject();
    const auto settings = project_.value("export_settings").toObject();
    const auto video = field({"video", "export_settings"}).toObject();
    podcastTitle_->setText(metadata.value("podcast_title").toString());
    episodeTitle_->setText(metadata.value("episode_title").toString());
    summary_->setPlainText(metadata.value("summary").toString());
    const auto artwork = metadata.value("artwork_path").toString();
    if (artwork.isEmpty()) episodeArtwork_->clear();
    else episodeArtwork_->setPixmap(QPixmap(artwork).scaled(160, 160, Qt::KeepAspectRatio, Qt::SmoothTransformation));
    audioFormat_->setCurrentText(settings.value("output_format").toString("mp3"));
    audioBitrate_->setCurrentText(settings.value("quality_preset").toString("320k"));
    audioChannels_->setCurrentText(QString::number(settings.value("channels").toInt(2)));
    wordTimestamps_->setChecked(field({"transcript_settings", "include_word_timestamps"}).toBool());
    codec_->setCurrentText(video.value("codec").toString("h264"));
    encoding_->setCurrentText(video.value("encoding").toString("automatic"));
    videoBitrate_->setCurrentText(video.value("audio_bitrate").toString("128k"));
    videoWidth_->setValue(video.value("width").toInt(1920));
    videoHeight_->setValue(video.value("height").toInt(1080));
    videoFps_->setValue(video.value("fps").toInt(30));
    flipHorizontal_->setChecked(video.value("flip_horizontal").toBool());
    flipVertical_->setChecked(video.value("flip_vertical").toBool());
    previewQuality_->setCurrentText(video.value("preview_quality").toString("automatic"));
    const auto mode = project_.value("active_mode").toString("audio");
    modes_->setCurrentIndex(mode == "video" ? 2 : mode == "transcript" ? 1 : 0);
    refreshSources();
    refreshChapters();
    refreshSegments();
    refreshVideo();
    loading_ = false;
    updateTitle();
    if (saveAction_) saveAction_->setEnabled(!busy_);
}

void MainWindow::refreshSources() {
    const auto list = project_.value("audio_sources").toArray();
    sources_->setRowCount(list.size());
    for (int i = 0; i < list.size(); ++i) {
        const auto source = list[i].toObject();
        const auto path = source.value("source_path").toString();
        const auto name = source.value("display_name").toString(QFileInfo(path).fileName());
        auto* item = new QTableWidgetItem(name + " — " + shownTime(source.value("duration_seconds").toDouble()));
        item->setData(Qt::UserRole, path);
        item->setFlags(item->flags() & ~Qt::ItemIsEditable);
        sources_->setItem(i, 0, item);
        auto* waveform = new QTableWidgetItem("…");
        waveform->setFlags(waveform->flags() & ~Qt::ItemIsEditable);
        sources_->setItem(i, 1, waveform);
    }
}
void MainWindow::refreshChapters() {
    const auto list = project_.value("chapters").toArray();
    chapters_->setRowCount(list.size());
    for (int i = 0; i < list.size(); ++i) {
        const auto chapter = list[i].toObject();
        const QStringList columns = {QString::number(i + 1), chapter.value("title").toString(),
            chapter.value("link_url").toString(), QString::number(chapter.value("duration_seconds").toDouble(), 'f', 3),
            chapter.value("image_path").toString()};
        for (int column = 0; column < columns.size(); ++column) {
            auto* item = new QTableWidgetItem(columns[column]);
            if (column == 0 || column == 4) item->setFlags(item->flags() & ~Qt::ItemIsEditable);
            chapters_->setItem(i, column, item);
        }
    }
}
void MainWindow::refreshSegments() {
    const auto list = project_.value("transcript_segments").toArray();
    segments_->setRowCount(list.size());
    for (int i = 0; i < list.size(); ++i) {
        const auto segment = list[i].toObject();
        segments_->setItem(i, 0, new QTableWidgetItem(segment.value("speaker").toString()));
        segments_->setItem(i, 1, new QTableWidgetItem(segment.value("text").toString()));
    }
}

void MainWindow::refreshVideo() {
    if (!hasProject_) return;
    const bool before = loading_;
    loading_ = true;
    const auto chapters = project_.value("chapters").toArray();
    const auto selected = field({"video", "export_settings", "selected_chapter_ids"}).toArray();
    QStringList selectedIds;
    for (const auto& value : selected) selectedIds.append(value.toString());
    videoChapters_->setRowCount(videoOrder_.size());
    double duration = 0;
    int count = 0;
    for (int row = 0; row < videoOrder_.size(); ++row) {
        QJsonObject chapter;
        for (const auto& value : chapters) if (value.toObject().value("id").toString() == videoOrder_[row]) { chapter = value.toObject(); break; }
        auto* include = new QTableWidgetItem;
        include->setFlags((include->flags() | Qt::ItemIsUserCheckable) & ~Qt::ItemIsEditable);
        const bool enabled = selectedIds.contains(videoOrder_[row]) ||
            !field({"video", "export_settings", "selection_initialized"}).toBool();
        include->setCheckState(enabled ? Qt::Checked : Qt::Unchecked);
        videoChapters_->setItem(row, 0, include);
        videoChapters_->setItem(row, 1, new QTableWidgetItem(chapter.value("title").toString()));
        videoChapters_->setItem(row, 2, new QTableWidgetItem(shownTime(chapter.value("duration_seconds").toDouble())));
        if (enabled) { ++count; duration += chapter.value("duration_seconds").toDouble(); }
    }
    videoSummary_->setText(QStringLiteral("%1 of %2 selected · %3").arg(count).arg(videoOrder_.size()).arg(shownTime(duration)));
    videoSeek_->setMaximum(std::max(1, static_cast<int>(duration)));
    videoArtwork_->setText(project_.value("metadata").toObject().value("artwork_path").toString().isEmpty()
        ? "Episode artwork required" : "Episode artwork ready");
    const auto artwork = previewIndex_ < selected.size() ? [&] {
        for (const auto& value : chapters) if (value.toObject().value("id") == selected[previewIndex_])
            return value.toObject().value("image_path").toString();
        return QString{};
    }() : QString{};
    const auto path = artwork.isEmpty() ? project_.value("metadata").toObject().value("artwork_path").toString() : artwork;
    QPixmap picture(path);
    if (picture.isNull()) videoPreview_->setText("No artwork preview");
    else {
        if (flipHorizontal_->isChecked() || flipVertical_->isChecked())
            picture = picture.transformed(QTransform().scale(flipHorizontal_->isChecked() ? -1 : 1,
                                                           flipVertical_->isChecked() ? -1 : 1));
        videoPreview_->setPixmap(picture.scaled(videoPreview_->size(), Qt::KeepAspectRatio, Qt::SmoothTransformation));
    }
    loading_ = before;
}

bool MainWindow::confirmReplace(bool modeSwitch) {
    if (busy_) return false;
    if (!dirty_) return true;
    QMessageBox dialog(this);
    dialog.setWindowTitle("Save changes?");
    dialog.setText("Save your project before continuing. Original recordings are never removed.");
    auto* save = dialog.addButton("Save Project", QMessageBox::AcceptRole);
    auto* discard = dialog.addButton(modeSwitch ? "Continue Without Saving" : "Discard Changes", QMessageBox::DestructiveRole);
    dialog.addButton("Cancel", QMessageBox::RejectRole);
    dialog.exec();
    if (dialog.clickedButton() == discard) return true;
    if (dialog.clickedButton() != save) return false;
    bool saved = false;
    QEventLoop loop;
    saveProject(false, [&loop, &saved](bool result) { saved = result; loop.quit(); });
    if (busy_) loop.exec();
    return saved;
}

void MainWindow::importFolder(const QString& requested) {
    if (!confirmReplace()) return;
    const auto path = requested.isEmpty() ? QFileDialog::getExistingDirectory(this, "Import recordings") : requested;
    if (path.isEmpty()) return;
    runEngine("Reading recordings…", {"inspect", path}, [this](const QJsonValue& value) {
        present(value.toObject(), true);
        applyChapterNames();
    });
}
void MainWindow::openInitialPath(const QString& path) {
    if (busy_) { QTimer::singleShot(250, this, [this, path] { openInitialPath(path); }); return; }
    if (QFileInfo(path).isDir()) importFolder(path);
    else if (QFile::exists(path)) openProject(path);
}
void MainWindow::openProject(const QString& requested) {
    if (!confirmReplace()) return;
    const auto path = requested.isEmpty()
        ? QFileDialog::getOpenFileName(this, "Open EnCap project", {}, "EnCap projects (*.encap)") : requested;
    if (path.isEmpty()) return;
    runEngine("Opening project…", {"open", path}, [this](const QJsonValue& value) {
        const auto document = value.toObject();
        runEngine("Finishing project recovery…", {"clear-recovery"}, [this, document](const QJsonValue&) {
            present(document, false);
        });
    });
}
void MainWindow::addFiles(const QStringList& requested) {
    if (!hasProject_ || busy_) return;
    const auto files = requested.isEmpty() ? QFileDialog::getOpenFileNames(this, "Add recordings", {},
        "Audio files (*.wav *.wave *.aif *.aiff *.aifc)") : requested;
    if (files.isEmpty()) return;
    auto edits = std::make_shared<QTemporaryFile>();
    if (!edits->open()) { fail("Could not stage recording edits."); return; }
    QJsonArray additions;
    for (const auto& path : files) additions.append(path);
    edits->write(QJsonDocument(QJsonObject{{"add_files", additions}, {"remove_files", QJsonArray{}}}).toJson());
    edits->flush();
    QStringList previous;
    for (const auto& value : project_.value("chapters").toArray()) previous.append(value.toObject().value("id").toString());
    runEngine("Adding recordings…", {"edit-audio", "@payload", edits->fileName()},
              [this, edits, previous](const QJsonValue& value) {
        present(value.toObject(), true);
        if (naming_->currentIndex() != 3) {
            auto chapters = project_.value("chapters").toArray();
            for (int i = 0; i < chapters.size(); ++i) {
                const auto entry = chapters[i].toObject();
                if (previous.contains(entry.value("id").toString())) continue;
                auto changed = entry;
                const int sourceIndex = entry.value("chapter_number").toInt() - 1;
                const auto sources = project_.value("audio_sources").toArray();
                const auto source = sourceIndex >= 0 && sourceIndex < sources.size() ? sources[sourceIndex].toObject() : QJsonObject{};
                const auto name = source.value("display_name").toString();
                if (naming_->currentIndex() == 0) changed.insert("title", name);
                if (naming_->currentIndex() == 1) changed.insert("title", QStringLiteral("Chapter %1").arg(i + 1));
                if (naming_->currentIndex() == 2) {
                    const auto stamp = QDateTime::fromString(QFileInfo(name).fileName().left(14), "MMddyyyyHHmmss");
                    changed.insert("title", stamp.isValid() ? stamp.addSecs(stamp.time().second() >= 30 ? 60 - stamp.time().second() : -stamp.time().second()).toString("h:mm AP") : name);
                }
                chapters[i] = changed;
            }
            project_.insert("chapters", chapters);
            refreshChapters();
            refreshVideo();
            markDirty();
        }
    }, project_);
}
void MainWindow::removeSources() {
    if (!hasProject_ || busy_) return;
    QJsonArray removals;
    for (const auto& range : sources_->selectedRanges()) {
        for (int i = range.topRow(); i <= range.bottomRow(); ++i) {
            const auto path = sources_->item(i, 0)->data(Qt::UserRole).toString();
            if (!removals.contains(path)) removals.append(path);
        }
    }
    if (removals.isEmpty()) return;
    if (QMessageBox::question(this, "Remove recordings?",
        "Remove these recordings and their chapters from the project? Original files stay on disk.") != QMessageBox::Yes) return;
    pausePlayback();
    auto edits = std::make_shared<QTemporaryFile>();
    if (!edits->open()) { fail("Could not stage recording edits."); return; }
    edits->write(QJsonDocument(QJsonObject{{"add_files", QJsonArray{}}, {"remove_files", removals}}).toJson());
    edits->flush();
    runEngine("Removing recordings…", {"edit-audio", "@payload", edits->fileName()},
              [this, edits](const QJsonValue& value) { present(value.toObject(), true); }, project_);
}

void MainWindow::saveProject(bool saveAs, std::function<void(bool)> completed) {
    if (!hasProject_ || busy_) { if (completed) completed(false); return; }
    QString path = saveAs ? QString{} : project_.value("project_path").toString();
    if (path.isEmpty()) path = QFileDialog::getSaveFileName(this, "Save EnCap project",
        project_.value("metadata").toObject().value("episode_title").toString() + ".encap", "EnCap projects (*.encap)");
    if (path.isEmpty()) { if (completed) completed(false); return; }
    auto onFailure = [completed] { if (completed) completed(false); };
    runEngine("Saving project…", {"save", "@payload", path}, [this, completed, onFailure](const QJsonValue& result) {
        project_.insert("project_path", result.toObject().value("path").toString());
        dirty_ = false;
        recoveryTimer_.stop();
        updateTitle();
        runEngine("Clearing recovery…", {"clear-recovery"}, [this, completed](const QJsonValue&) {
            setStatus("Project saved.");
            if (completed) completed(true);
        }, {}, [completed] { if (completed) completed(true); });
    }, project_, onFailure);
}
void MainWindow::switchMode(int index) {
    if (index < 0 || index > 2 || busy_) return;
    const int current = project_.value("active_mode").toString("audio") == "video" ? 2 :
        project_.value("active_mode").toString("audio") == "transcript" ? 1 : 0;
    if (index == current) return;
    loading_ = true;
    modes_->setCurrentIndex(current);
    loading_ = false;
    pausePlayback();
    if (hasProject_) {
        const QStringList names = {"audio", "transcript", "video"};
        const bool wasDirty = dirty_;
        project_.insert("active_mode", names[index]);
        markDirty();
        if (!project_.value("project_path").toString().isEmpty()) {
            saveProject(false, [this, index, current](bool saved) {
                if (!saved) { project_.insert("active_mode", QStringList{"audio", "transcript", "video"}[current]); return; }
                loading_ = true; modes_->setCurrentIndex(index); loading_ = false; refreshVideo();
            });
            return;
        }
        if (wasDirty && !confirmReplace(true)) {
            project_.insert("active_mode", names[current]);
            return;
        }
    }
    loading_ = true;
    modes_->setCurrentIndex(index);
    loading_ = false;
    refreshVideo();
}
void MainWindow::chooseArtwork(bool chapter) {
    if (!hasProject_) return;
    const auto path = QFileDialog::getOpenFileName(this, "Choose artwork", {},
        "Image files (*.png *.jpg *.jpeg *.webp *.tif *.tiff)");
    if (path.isEmpty()) return;
    if (chapter) {
        const int row = chapters_->currentRow();
        auto values = project_.value("chapters").toArray();
        if (row < 0 || row >= values.size()) return;
        auto entry = values[row].toObject();
        entry.insert("image_path", path);
        values[row] = entry;
        project_.insert("chapters", values);
        refreshChapters();
    } else setField({"metadata", "artwork_path"}, path);
    markDirty();
    refreshUi();
}
void MainWindow::addChapter() {
    if (!hasProject_) return;
    auto values = project_.value("chapters").toArray();
    const auto sources = project_.value("audio_sources").toArray();
    double start = 0;
    for (const auto& value : values) start += value.toObject().value("duration_seconds").toDouble();
    int sourceNumber = 1;
    double end = 0;
    for (int i = 0; i < sources.size(); ++i) {
        end += sources[i].toObject().value("duration_seconds").toDouble();
        if (start < end) { sourceNumber = i + 1; break; }
    }
    values.append(QJsonObject{{"id", QUuid::createUuid().toString(QUuid::WithoutBraces).remove('-')},
        {"chapter_number", sourceNumber}, {"title", QStringLiteral("Chapter %1").arg(values.size() + 1)},
        {"start_time_seconds", start}, {"duration_seconds", 30.0}});
    project_.insert("chapters", values);
    videoOrder_.append(values.last().toObject().value("id").toString());
    refreshChapters();
    refreshVideo();
    markDirty();
}
void MainWindow::removeChapter() {
    if (!hasProject_) return;
    const int row = chapters_->currentRow();
    auto values = project_.value("chapters").toArray();
    if (row < 0 || row >= values.size()) return;
    videoOrder_.removeAll(values[row].toObject().value("id").toString());
    values.removeAt(row);
    double start = 0;
    for (int i = 0; i < values.size(); ++i) {
        auto chapter = values[i].toObject();
        chapter.insert("start_time_seconds", start);
        start += chapter.value("duration_seconds").toDouble();
        values[i] = chapter;
    }
    project_.insert("chapters", values);
    refreshChapters();
    refreshVideo();
    markDirty();
}
void MainWindow::applyChapterNames() {
    if (!hasProject_) return;
    const int style = naming_->currentIndex();
    if (style == 3) return;
    auto values = project_.value("chapters").toArray();
    const auto sources = project_.value("audio_sources").toArray();
    for (int i = 0; i < values.size(); ++i) {
        auto chapter = values[i].toObject();
        const int sourceIndex = chapter.value("chapter_number").toInt() - 1;
        const auto source = sourceIndex >= 0 && sourceIndex < sources.size() ? sources[sourceIndex].toObject() : QJsonObject{};
        const auto name = source.value("display_name").toString();
        if (style == 0 && !name.isEmpty()) chapter.insert("title", name);
        if (style == 1) chapter.insert("title", QStringLiteral("Chapter %1").arg(i + 1));
        if (style == 2 && !name.isEmpty()) {
            const auto stamp = QDateTime::fromString(QFileInfo(name).fileName().left(14), "MMddyyyyHHmmss");
            chapter.insert("title", stamp.isValid() ? stamp.addSecs(stamp.time().second() >= 30 ? 60 - stamp.time().second() : -stamp.time().second()).toString("h:mm AP") : name);
        }
        values[i] = chapter;
    }
    project_.insert("chapters", values);
    refreshChapters();
    refreshVideo();
    markDirty();
}

void MainWindow::exportFile(const QString& kind) {
    if (!hasProject_ || busy_) return;
    if (kind == "video") {
        syncVideoSelection();
        if (field({"video", "export_settings", "selected_chapter_ids"}).toArray().isEmpty() ||
            field({"metadata", "artwork_path"}).toString().isEmpty()) {
            fail("Select chapters and add episode artwork before exporting video.");
            return;
        }
    }
    const QString extension = kind == "audio" ? (field({"export_settings", "output_format"}).toString() == "aac" ? "m4a" : "mp3")
        : kind == "video" ? "mp4" : kind;
    const auto path = QFileDialog::getSaveFileName(this, "Export " + kind,
        field({"metadata", "episode_title"}).toString() + "." + extension,
        QStringLiteral("%1 files (*.%2)").arg(extension.toUpper(), extension));
    if (path.isEmpty()) return;
    QStringList arguments;
    if (kind == "audio") arguments = {"export", "@payload", path};
    else if (kind == "video") arguments = {"export-video", "@payload", path};
    else arguments = {"export-transcript", "@payload", path, kind};
    runEngine("Exporting " + kind + "…", arguments, [this](const QJsonValue& value) {
        setStatus("Exported " + QFileInfo(value.toObject().value("path").toString()).fileName() + ".");
    }, project_);
}
void MainWindow::transcribe() {
    if (!hasProject_ || provider_->currentIndex() < 0) return;
    QStringList arguments = {"transcribe", "@payload", provider_->currentData().toString()};
    if (wordTimestamps_->isChecked()) arguments.append("--word-timestamps");
    runEngine("Transcribing locally…", arguments, [this](const QJsonValue& result) {
        project_.insert("transcript_segments", result.toArray());
        loading_ = true;
        refreshSegments();
        loading_ = false;
        markDirty();
        setStatus("Transcription ready.");
    }, project_);
}
void MainWindow::refreshModels() {
    runEngine("Loading local models…", {"models"}, [this](const QJsonValue& result) {
        models_ = result.toArray();
        modelList_->setRowCount(models_.size());
        for (int row = 0; row < models_.size(); ++row) {
            const auto model = models_[row].toObject();
            modelList_->setItem(row, 0, new QTableWidgetItem(model.value("name").toString()));
            modelList_->setItem(row, 1, new QTableWidgetItem(model.value("download_size").toString()));
            modelList_->setItem(row, 2, new QTableWidgetItem(model.value("languages").toString()));
            modelList_->setItem(row, 3, new QTableWidgetItem(model.value("installed").toBool() ? "Yes" : "No"));
        }
        setStatus("Select a model to download or remove.");
    });
}
void MainWindow::changeModel(bool remove) {
    const int row = modelList_->currentRow();
    if (row < 0 || row >= models_.size()) return;
    const auto model = models_[row].toObject();
    if (!remove && !model.value("download_allowed").toBool()) { fail("This compatible model is managed by another application."); return; }
    runEngine(remove ? "Removing model…" : "Downloading and verifying model…",
              {remove ? "remove-model" : "install-model", model.value("id").toString()},
              [this](const QJsonValue&) {
        runEngine("Refreshing providers…", {"providers"}, [this](const QJsonValue& result) {
            providers_ = result.toArray();
            provider_->clear();
            for (const auto& value : providers_) provider_->addItem(value.toObject().value("name").toString(), value.toObject().value("id"));
            refreshModels();
        });
    });
}
void MainWindow::syncVideoSelection() {
    if (loading_ || !hasProject_) return;
    QJsonArray selected;
    double duration = 0;
    int count = 0;
    const auto chapters = project_.value("chapters").toArray();
    for (int row = 0; row < videoChapters_->rowCount() && row < videoOrder_.size(); ++row) {
        if (videoChapters_->item(row, 0)->checkState() != Qt::Checked) continue;
        selected.append(videoOrder_[row]);
        ++count;
        for (const auto& value : chapters) if (value.toObject().value("id").toString() == videoOrder_[row]) {
            duration += value.toObject().value("duration_seconds").toDouble(); break;
        }
    }
    setField({"video", "export_settings", "selected_chapter_ids"}, selected);
    setField({"video", "export_settings", "selection_initialized"}, true);
    videoSummary_->setText(QStringLiteral("%1 of %2 selected · %3").arg(count).arg(videoOrder_.size()).arg(shownTime(duration)));
    videoSeek_->setMaximum(std::max(1, static_cast<int>(duration)));
}
void MainWindow::moveVideo(int delta) {
    const int row = videoChapters_->currentRow();
    moveVideoTo(row + delta);
}
void MainWindow::moveVideoTo(int next) {
    const int row = videoChapters_->currentRow();
    if (row < 0 || next < 0 || next >= videoOrder_.size()) return;
    videoOrder_.move(row, next);
    auto selected = field({"video", "export_settings", "selected_chapter_ids"}).toArray();
    QStringList enabled;
    for (const auto& value : selected) enabled.append(value.toString());
    selected = {};
    for (const auto& id : videoOrder_) if (enabled.contains(id)) selected.append(id);
    setField({"video", "export_settings", "selected_chapter_ids"}, selected);
    refreshVideo();
    videoChapters_->selectRow(next);
    markDirty();
}
void MainWindow::loadWaveforms() {
    if (!hasProject_ || waveformEngine_->busy()) return;
    loadWaveformAt(project_.value("audio_sources").toArray(), 0, waveformGeneration_);
}
void MainWindow::loadWaveformAt(const QJsonArray& paths, int row, int generation) {
    if (generation != waveformGeneration_ || row >= paths.size()) return;
    const auto path = paths[row].toObject().value("source_path").toString();
    waveformEngine_->run({"waveform", "--", path}, [this, paths, path, row, generation](const QJsonValue& result, const QString& error) {
        if (generation != waveformGeneration_) return;
        if (!error.isEmpty()) { setStatus(error, true); return; }
        if (row < sources_->rowCount() && sources_->item(row, 0)->data(Qt::UserRole).toString() == path) {
            const auto peaks = result.toObject().value("peaks").toArray();
            QString bars;
            const QString symbols = QString::fromUtf8("▁▂▃▄▅▆▇█");
            const int stride = std::max(1, static_cast<int>(peaks.size() / 48));
            for (int i = 0; i < peaks.size(); i += stride)
                bars.append(symbols.at(std::clamp(static_cast<int>(peaks[i].toDouble() * 8), 0, 7)));
            sources_->item(row, 1)->setText(bars);
            sources_->item(row, 1)->setToolTip("Recording waveform");
        }
        loadWaveformAt(paths, row + 1, generation);
    });
}

MainWindow::~MainWindow() {
    clock_.stop();
    updateTimer_.stop();
    engine_->shutdown();
    previewEngine_->shutdown();
    waveformEngine_->shutdown();
    if (decoder_) {
        decoder_->kill();
        decoder_->waitForFinished(1000);
        delete decoder_;
        decoder_ = nullptr;
    }
    encap_audio_close();
    if (!temporaryPreview_.isEmpty()) QFile::remove(temporaryPreview_);
#ifdef ENCAP_HAS_MEDIA_SESSION
    if (mediaOwner_ == this) { encap_media_close(); mediaOwner_ = nullptr; }
#endif
}

void MainWindow::buildUi() {
    auto* central = new QWidget(this);
    auto* vertical = new QVBoxLayout(central);
    vertical->addWidget(row({button("Import Folder…", [this] { importFolder(); }),
                             button("Open Project…", [this] { openProject(); }),
                             button("Save", [this] { saveProject(); }),
                             button("Audio", [this] { switchMode(0); }),
                             button("Transcript", [this] { switchMode(1); }),
                             button("Video", [this] { switchMode(2); })}));
    modes_ = new QTabWidget;
    modes_->addTab(buildAudioPage(), "Audio");
    modes_->addTab(buildTranscriptPage(), "Transcript");
    modes_->addTab(buildVideoPage(), "Video");
    connect(modes_, &QTabWidget::currentChanged, this, [this](int index) { if (!loading_) switchMode(index); });
    vertical->addWidget(modes_, 1);
    progress_ = new QProgressBar;
    progress_->setVisible(false);
    progress_->setAccessibleName("Operation in progress");
    status_ = new QLabel("Import an audio folder or open a project to begin.");
    status_->setAccessibleName("Application status");
    status_->setWordWrap(true);
    cancel_ = button("Cancel", [this] {
        setStatus("Cancelling safely…");
        engine_->cancel();
        previewEngine_->cancel();
        if (decoder_) decoder_->kill();
    });
    cancel_->setVisible(false);
    vertical->addWidget(row({status_, cancel_}));
    vertical->addWidget(progress_);
    setCentralWidget(central);
}

QWidget* MainWindow::buildAudioPage() {
    auto* split = new QSplitter;
    auto* sourcePanel = new QWidget;
    auto* left = new QVBoxLayout(sourcePanel);
    left->addWidget(new QLabel("Recordings"));
    sources_ = new QTableWidget(0, 2);
    sources_->setHorizontalHeaderLabels({"Recording", "Waveform"});
    sources_->horizontalHeader()->setStretchLastSection(true);
    sources_->setSelectionBehavior(QAbstractItemView::SelectRows);
    sources_->setSelectionMode(QAbstractItemView::ExtendedSelection);
    sources_->setAccessibleName("Source recordings");
    sources_->installEventFilter(this);
    sources_->viewport()->installEventFilter(this);
    connect(sources_, &QTableWidget::cellDoubleClicked, this, [this] { togglePlayback(); });
    left->addWidget(sources_, 1);
    left->addWidget(row({button("Add…", [this] { addFiles(); }), button("Remove…", [this] { removeSources(); })}));
    sourceSeek_ = new QSlider(Qt::Horizontal);
    sourceSeek_->setAccessibleName("Recording position");
    connect(sourceSeek_, &QSlider::sliderReleased, this, [this] { seekPlayback(sourceSeek_->value()); });
    left->addWidget(sourceSeek_);
    sourcePlay_ = button("Play", [this] { togglePlayback(); });
    sourceTime_ = new QLabel("00:00:00 / 00:00:00");
    left->addWidget(row({button("Previous", [this] { adjacent(-1); }), sourcePlay_,
                          button("Next", [this] { adjacent(1); }), sourceTime_}));
    left->addWidget(new QLabel("Space: play/pause · J/K/L: shuttle · Hold K with J/L: half speed"));
    split->addWidget(sourcePanel);

    auto* editor = new QWidget;
    auto* right = new QVBoxLayout(editor);
    auto* episode = new QGroupBox("Episode");
    auto* episodeForm = new QFormLayout(episode);
    podcastTitle_ = new QLineEdit;
    episodeTitle_ = new QLineEdit;
    summary_ = new QPlainTextEdit;
    podcastTitle_->setAccessibleName("Podcast title");
    episodeTitle_->setAccessibleName("Episode title");
    summary_->setAccessibleName("Episode summary");
    summary_->setMaximumHeight(90);
    episodeArtwork_ = new QLabel;
    episodeArtwork_->setFixedSize(160, 160);
    episodeArtwork_->setAlignment(Qt::AlignCenter);
    episodeArtwork_->setAccessibleName("Episode artwork");
    episodeForm->addRow("Podcast title", podcastTitle_);
    episodeForm->addRow("Episode title", episodeTitle_);
    episodeForm->addRow("Summary", summary_);
    episodeForm->addRow("Artwork", row({episodeArtwork_, button("Artwork…", [this] { chooseArtwork(false); })}));
    right->addWidget(episode);
    audioFormat_ = combo({"mp3", "aac"});
    audioBitrate_ = combo({"64k", "96k", "128k", "160k", "192k", "256k", "320k"});
    audioChannels_ = combo({"1", "2"});
    right->addWidget(row({new QLabel("Format"), audioFormat_, new QLabel("Channels"), audioChannels_,
                          new QLabel("Bitrate"), audioBitrate_, button("Export Audio…", [this] { exportFile("audio"); })}));
    right->addWidget(new QLabel("Chapters"));
    naming_ = combo({"Original", "Numbered", "Time", "Custom"});
    right->addWidget(row({naming_, button("Apply Names", [this] { applyChapterNames(); }),
                          button("Add", [this] { addChapter(); }), button("Remove", [this] { removeChapter(); }),
                          button("Chapter Artwork…", [this] { chooseArtwork(true); })}));
    chapters_ = new QTableWidget(0, 5);
    chapters_->setHorizontalHeaderLabels({"#", "Title", "Link", "Duration (s)", "Artwork"});
    chapters_->horizontalHeader()->setStretchLastSection(true);
    chapters_->setAccessibleName("Project chapters");
    right->addWidget(chapters_, 1);
    split->addWidget(editor);
    split->setStretchFactor(1, 2);

    connect(podcastTitle_, &QLineEdit::textEdited, this, [this](const QString& text) { setField({"metadata", "podcast_title"}, text); });
    connect(episodeTitle_, &QLineEdit::textEdited, this, [this](const QString& text) { setField({"metadata", "episode_title"}, text); updateTitle(); });
    connect(summary_, &QPlainTextEdit::textChanged, this, [this] { if (!loading_) setField({"metadata", "summary"}, summary_->toPlainText()); });
    connect(audioFormat_, &QComboBox::currentTextChanged, this, [this](const QString& value) {
        setField({"export_settings", "output_format"}, value);
        setField({"export_settings", "encoder"}, "ffmpeg");
    });
    connect(audioBitrate_, &QComboBox::currentTextChanged, this, [this](const QString& value) { setField({"export_settings", "quality_preset"}, value); });
    connect(audioChannels_, &QComboBox::currentTextChanged, this, [this](const QString& value) { setField({"export_settings", "channels"}, value.toInt()); });
    connect(naming_, &QComboBox::currentIndexChanged, this, [this](int index) {
        if (loading_) return;
        QSaveFile file(preferencePath("chapter-naming.txt"));
        if (!file.open(QIODevice::WriteOnly)) { fail("Could not save chapter naming preference."); return; }
#ifdef Q_OS_LINUX
        file.write(QByteArray("[Chapters]\nstyle=") + QByteArray::number(index) + '\n');
#else
        file.write(naming_->itemText(index).toUtf8());
#endif
        if (!file.commit()) fail("Could not save chapter naming preference.");
    });
    connect(chapters_, &QTableWidget::cellChanged, this, [this](int row, int column) {
        if (loading_ || !hasProject_ || column == 0 || column == 4) return;
        auto list = project_.value("chapters").toArray();
        if (row >= list.size()) return;
        auto chapter = list[row].toObject();
        const auto value = chapters_->item(row, column)->text();
        if (column == 1) { chapter.insert("title", value); naming_->setCurrentIndex(3); }
        if (column == 2) chapter.insert("link_url", value);
        if (column == 3) chapter.insert("duration_seconds", std::max(0.001, value.toDouble()));
        list[row] = chapter;
        if (column == 3) {
            double start = 0;
            for (int i = 0; i < list.size(); ++i) {
                auto entry = list[i].toObject();
                entry.insert("start_time_seconds", start);
                start += entry.value("duration_seconds").toDouble();
                list[i] = entry;
            }
        }
        project_.insert("chapters", list);
        markDirty();
        refreshVideo();
    });
    return split;
}

QWidget* MainWindow::buildTranscriptPage() {
    auto* page = new QWidget;
    auto* layout = new QVBoxLayout(page);
    layout->addWidget(new QLabel("Transcript"));
    provider_ = new QComboBox;
    provider_->setAccessibleName("Local transcription engine");
    wordTimestamps_ = new QCheckBox("Word timestamps");
    layout->addWidget(row({provider_, button("Transcribe Locally", [this] { transcribe(); }),
                           button("Refresh Models", [this] { refreshModels(); }), wordTimestamps_,
                           button("Export Text…", [this] { exportFile("txt"); }),
                           button("Export SRT…", [this] { exportFile("srt"); })}));
    auto* models = new QGroupBox("Local transcription models");
    auto* modelLayout = new QVBoxLayout(models);
    modelLayout->addWidget(new QLabel("Models use the existing verified local model catalog."));
    modelList_ = new QTableWidget(0, 4);
    modelList_->setHorizontalHeaderLabels({"Model", "Size", "Languages", "Installed"});
    modelList_->horizontalHeader()->setStretchLastSection(true);
    modelList_->setSelectionBehavior(QAbstractItemView::SelectRows);
    modelList_->setAccessibleName("Local models");
    modelLayout->addWidget(modelList_);
    modelLayout->addWidget(row({button("Download Selected", [this] { changeModel(false); }),
                                button("Remove Selected", [this] { changeModel(true); })}));
    layout->addWidget(models);
    layout->addWidget(new QLabel("Segments"));
    segments_ = new QTableWidget(0, 2);
    segments_->setHorizontalHeaderLabels({"Speaker", "Text"});
    segments_->horizontalHeader()->setStretchLastSection(true);
    segments_->setAccessibleName("Transcript segments");
    layout->addWidget(segments_, 1);
    connect(wordTimestamps_, &QCheckBox::toggled, this, [this](bool value) { setField({"transcript_settings", "include_word_timestamps"}, value); });
    connect(segments_, &QTableWidget::cellChanged, this, [this](int row, int column) {
        if (loading_ || !hasProject_) return;
        auto values = project_.value("transcript_segments").toArray();
        if (row >= values.size()) return;
        auto segment = values[row].toObject();
        segment.insert(column == 0 ? "speaker" : "text", segments_->item(row, column)->text());
        values[row] = segment;
        project_.insert("transcript_segments", values);
        markDirty();
    });
    return page;
}

QWidget* MainWindow::buildVideoPage() {
    auto* page = new QWidget;
    auto* outer = new QVBoxLayout(page);
    auto* scroll = new QScrollArea;
    scroll->setWidgetResizable(true);
    auto* body = new QWidget;
    auto* layout = new QVBoxLayout(body);
    layout->addWidget(new QLabel("Create an MP4 from the project's original chapter audio and artwork."));

    auto* selection = new QGroupBox("Chapter selection");
    auto* selectionLayout = new QVBoxLayout(selection);
    videoSummary_ = new QLabel;
    selectionLayout->addWidget(videoSummary_);
    selectionLayout->addWidget(row({button("Select All", [this] {
        for (int i = 0; i < videoChapters_->rowCount(); ++i) videoChapters_->item(i, 0)->setCheckState(Qt::Checked);
        syncVideoSelection();
    }), button("Select None", [this] {
        for (int i = 0; i < videoChapters_->rowCount(); ++i) videoChapters_->item(i, 0)->setCheckState(Qt::Unchecked);
        syncVideoSelection();
    }), button("Move Up", [this] { moveVideo(-1); }), button("Move Down", [this] { moveVideo(1); })}));
    videoChapters_ = new QTableWidget(0, 3);
    videoChapters_->setHorizontalHeaderLabels({"Include", "Chapter", "Duration"});
    videoChapters_->horizontalHeader()->setStretchLastSection(true);
    videoChapters_->setSelectionBehavior(QAbstractItemView::SelectRows);
    videoChapters_->setDragDropMode(QAbstractItemView::InternalMove);
    videoChapters_->viewport()->installEventFilter(this);
    videoChapters_->setAccessibleName("Video chapter order and selection");
    selectionLayout->addWidget(videoChapters_);
    layout->addWidget(selection);

    auto* settings = new QGroupBox("Video format");
    auto* form = new QFormLayout(settings);
    preset_ = new QComboBox;
    preset_->setAccessibleName("Social video preset");
    codec_ = combo({"h264", "hevc"});
    encoding_ = combo({"automatic", "hardware", "software"});
    videoBitrate_ = combo({"64k", "96k", "128k", "160k", "192k", "256k", "320k"});
    videoWidth_ = new QSpinBox;
    videoHeight_ = new QSpinBox;
    videoFps_ = new QSpinBox;
    for (auto* control : {videoWidth_, videoHeight_}) { control->setRange(2, 8192); control->setSingleStep(2); }
    videoFps_->setRange(1, 120);
    form->addRow("Social preset", preset_);
    form->addRow("Codec", codec_);
    form->addRow("Encoding", encoding_);
    form->addRow("Width", videoWidth_);
    form->addRow("Height", videoHeight_);
    form->addRow("FPS", videoFps_);
    form->addRow("Audio bitrate", videoBitrate_);
    layout->addWidget(settings);

    auto* artwork = new QGroupBox("Artwork and preview options");
    auto* artworkLayout = new QVBoxLayout(artwork);
    videoArtwork_ = new QLabel;
    artworkLayout->addWidget(videoArtwork_);
    flipHorizontal_ = new QCheckBox("Flip horizontally");
    flipVertical_ = new QCheckBox("Flip vertically");
    previewQuality_ = combo({"automatic", "low", "medium", "high"});
    artworkLayout->addWidget(row({flipHorizontal_, flipVertical_, new QLabel("Preview quality"), previewQuality_}));
    layout->addWidget(artwork);

    videoPreview_ = new QLabel;
    videoPreview_->setMinimumSize(320, 180);
    videoPreview_->setMaximumHeight(300);
    videoPreview_->setAlignment(Qt::AlignCenter);
    videoPreview_->setStyleSheet("background: black; color: white;");
    videoPreview_->setAccessibleName("Video chapter artwork preview");
    layout->addWidget(videoPreview_);
    videoSeek_ = new QSlider(Qt::Horizontal);
    videoSeek_->setAccessibleName("Video timeline position");
    layout->addWidget(videoSeek_);
    videoPlay_ = button("Play", [this] { togglePlayback(); });
    videoTime_ = new QLabel("00:00:00 / 00:00:00");
    layout->addWidget(row({button("Previous", [this] { adjacent(-1); }), videoPlay_,
                           button("Next", [this] { adjacent(1); }), videoTime_}));
    layout->addWidget(row({button("Select All Chapters", [this] {
        for (int i = 0; i < videoChapters_->rowCount(); ++i) videoChapters_->item(i, 0)->setCheckState(Qt::Checked);
        syncVideoSelection();
    }), button("Episode Artwork…", [this] { chooseArtwork(false); }),
                           button("Export MP4…", [this] { exportFile("video"); })}));
    layout->addStretch();
    scroll->setWidget(body);
    outer->addWidget(scroll);

    connect(videoChapters_, &QTableWidget::cellChanged, this, [this] { if (!loading_) syncVideoSelection(); });
    connect(videoChapters_, &QTableWidget::cellDoubleClicked, this, [this](int row) {
        const auto selected = field({"video", "export_settings", "selected_chapter_ids"}).toArray();
        double start = 0;
        for (const auto& id : selected) {
            if (id.toString() == videoOrder_.value(row)) { seekPlayback(start); return; }
            for (const auto& value : project_.value("chapters").toArray())
                if (value.toObject().value("id") == id) { start += value.toObject().value("duration_seconds").toDouble(); break; }
        }
    });
    connect(videoSeek_, &QSlider::sliderReleased, this, [this] { seekPlayback(videoSeek_->value()); });
    connect(preset_, &QComboBox::currentIndexChanged, this, [this](int index) {
        if (loading_ || !hasProject_ || index < 0 || index >= presets_.size()) return;
        const auto selected = presets_[index].toObject();
        for (const auto& key : {"platform", "aspect", "width", "height", "fps"})
            setField({"video", "export_settings", key}, selected.value(key));
        refreshUi();
    });
    connect(codec_, &QComboBox::currentTextChanged, this, [this](const QString& value) { setField({"video", "export_settings", "codec"}, value); });
    connect(encoding_, &QComboBox::currentTextChanged, this, [this](const QString& value) { setField({"video", "export_settings", "encoding"}, value); });
    connect(videoBitrate_, &QComboBox::currentTextChanged, this, [this](const QString& value) { setField({"video", "export_settings", "audio_bitrate"}, value); });
    connect(videoWidth_, qOverload<int>(&QSpinBox::valueChanged), this, [this](int value) { setField({"video", "export_settings", "width"}, value); });
    connect(videoHeight_, qOverload<int>(&QSpinBox::valueChanged), this, [this](int value) { setField({"video", "export_settings", "height"}, value); });
    connect(videoFps_, qOverload<int>(&QSpinBox::valueChanged), this, [this](int value) { setField({"video", "export_settings", "fps"}, value); });
    connect(flipHorizontal_, &QCheckBox::toggled, this, [this](bool value) { setField({"video", "export_settings", "flip_horizontal"}, value); refreshVideo(); });
    connect(flipVertical_, &QCheckBox::toggled, this, [this](bool value) { setField({"video", "export_settings", "flip_vertical"}, value); refreshVideo(); });
    connect(previewQuality_, &QComboBox::currentTextChanged, this, [this](const QString& value) { setField({"video", "export_settings", "preview_quality"}, value); });
    return page;
}

void MainWindow::buildMenus() {
    auto* file = menuBar()->addMenu("&File");
    auto add = [this](QMenu* menu, const QString& name, const QKeySequence& shortcut, const std::function<void()>& action) {
        auto* entry = menu->addAction(name);
        entry->setShortcut(shortcut);
        connect(entry, &QAction::triggered, this, [action] { action(); });
        return entry;
    };
    add(file, "&Import Folder…", QKeySequence("Ctrl+I"), [this] { importFolder(); });
    add(file, "&Open Project…", QKeySequence("Ctrl+O"), [this] { openProject(); });
    saveAction_ = add(file, "&Save", QKeySequence("Ctrl+S"), [this] { saveProject(); });
    add(file, "Save &As…", QKeySequence("Ctrl+Shift+S"), [this] { saveProject(true); });
    file->addSeparator();
    add(file, "Export Audio…", {}, [this] { exportFile("audio"); });
    add(file, "Export Text…", {}, [this] { exportFile("txt"); });
    add(file, "Export SRT…", {}, [this] { exportFile("srt"); });
    add(file, "Export MP4…", {}, [this] { exportFile("video"); });
    auto* mode = menuBar()->addMenu("&Mode");
    add(mode, "&Audio", QKeySequence("Ctrl+1"), [this] { switchMode(0); });
    add(mode, "&Transcript", QKeySequence("Ctrl+2"), [this] { switchMode(1); });
    add(mode, "&Video", QKeySequence("Ctrl+3"), [this] { switchMode(2); });
    auto* application = menuBar()->addMenu("&Application");
    add(application, "Check for Updates…", {}, [this] { checkUpdates(true); })->setEnabled(!internalReference());
    automaticUpdates_ = application->addAction("Automatically Check for Updates");
    automaticUpdates_->setCheckable(true);
    automaticUpdates_->setChecked(!QFile::exists(preferencePath("automatic-updates-disabled")));
    automaticUpdates_->setEnabled(!internalReference());
    connect(automaticUpdates_, &QAction::toggled, this, [this](bool enabled) {
        const auto path = preferencePath("automatic-updates-disabled");
        if (enabled) QFile::remove(path);
        else { QFile file(path); if (file.open(QIODevice::WriteOnly)) file.write("disabled"); }
    });
    auto* appearance = application->addMenu("&Appearance");
    auto* group = new QActionGroup(this);
    appearanceSystem_ = appearance->addAction("&System");
    appearanceLight_ = appearance->addAction("&Light");
    appearanceDark_ = appearance->addAction("&Dark");
    for (auto* action : {appearanceSystem_, appearanceLight_, appearanceDark_}) { action->setCheckable(true); group->addAction(action); }
    connect(appearanceSystem_, &QAction::triggered, this, [this] { setAppearance("system"); });
    connect(appearanceLight_, &QAction::triggered, this, [this] { setAppearance("light"); });
    connect(appearanceDark_, &QAction::triggered, this, [this] { setAppearance("dark"); });
}

void MainWindow::openPlayback(const QString& path, std::function<void(bool)> completed) {
    if (decoder_) { decoder_->kill(); decoder_->deleteLater(); decoder_ = nullptr; }
    encap_audio_close();
    if (!temporaryPreview_.isEmpty()) { QFile::remove(temporaryPreview_); temporaryPreview_.clear(); }
    if (encap_audio_open(path.toUtf8().constData()) == 0) {
        encap_audio_volume(volume_);
        playingPath_ = path;
        completed(true);
        return;
    }
    encap_audio_close();
    setStatus("Opening recording preview…");
    previewEngine_->run({"validate-tools"}, [this, path, completed](const QJsonValue&, const QString& error) {
        if (!error.isEmpty()) { fail(error); completed(false); return; }
        QTemporaryFile staged(QDir::tempPath() + "/encap-preview-XXXXXX.wav");
        staged.setAutoRemove(false);
        if (!staged.open()) { fail("Could not stage audio preview."); completed(false); return; }
        temporaryPreview_ = staged.fileName();
        staged.close();
        decoder_ = new QProcess(this);
        decoder_->setProgram(QCoreApplication::applicationDirPath() + "/ffmpeg"
#ifdef Q_OS_WIN
            ".exe"
#endif
        );
        decoder_->setArguments({"-nostdin", "-v", "error", "-i", path, "-vn", "-ac", "2", "-ar", "48000",
                                "-c:a", "pcm_f32le", "-y", temporaryPreview_});
        auto* active = decoder_;
        connect(active, qOverload<int, QProcess::ExitStatus>(&QProcess::finished), this,
                [this, active, path, completed](int code, QProcess::ExitStatus status) {
            if (decoder_ != active) return;
            const auto details = QString::fromUtf8(active->readAllStandardError());
            active->deleteLater(); decoder_ = nullptr;
            if (status != QProcess::NormalExit || code != 0 || encap_audio_open(temporaryPreview_.toUtf8().constData()) != 0) {
                encap_audio_close();
                fail(details.isEmpty() ? "Could not decode or open this recording." : details);
                completed(false);
                return;
            }
            encap_audio_volume(volume_);
            playingPath_ = path;
            setStatus("Recording preview ready.");
            completed(true);
        });
        connect(active, &QProcess::errorOccurred, this, [this, active, completed](QProcess::ProcessError error) {
            if (error != QProcess::FailedToStart || decoder_ != active) return;
            decoder_ = nullptr;
            active->deleteLater();
            fail("Could not start the bundled FFmpeg preview decoder.");
            completed(false);
        });
        active->start();
    });
}
void MainWindow::pausePlayback() {
    videoPlaying_ = false;
    encap_audio_pause();
    refreshPlayback();
}
void MainWindow::togglePlayback() {
    if (!hasProject_ || busy_) return;
    const bool video = modes_->currentIndex() == 2;
    if (encap_audio_playing()) { pausePlayback(); return; }
    if (video) {
        const auto selected = field({"video", "export_settings", "selected_chapter_ids"}).toArray();
        if (selected.isEmpty()) return;
        previewIndex_ = std::clamp(previewIndex_, 0, static_cast<int>(selected.size()) - 1);
        const auto id = selected[previewIndex_].toString();
        for (const auto& value : project_.value("chapters").toArray()) {
            const auto chapter = value.toObject();
            if (chapter.value("id").toString() != id) continue;
            const int source = chapter.value("chapter_number").toInt() - 1;
            const auto sources = project_.value("audio_sources").toArray();
            if (source < 0 || source >= sources.size()) { fail("Chapter refers to a missing recording."); return; }
            const auto path = sources[source].toObject().value("source_path").toString();
            if (path == playingPath_) { encap_audio_play(1); videoPlaying_ = true; }
            else openPlayback(path, [this](bool ready) { if (ready) { encap_audio_play(1); videoPlaying_ = true; refreshPlayback(); } });
            break;
        }
    } else {
        const int row = sources_->currentRow();
        if (row < 0) return;
        const auto path = sources_->item(row, 0)->data(Qt::UserRole).toString();
        if (path == playingPath_) encap_audio_play(rate_);
        else openPlayback(path, [this](bool ready) { if (ready) encap_audio_play(1); });
    }
    refreshPlayback();
}
void MainWindow::seekPlayback(double seconds, bool play) {
    if (!hasProject_) return;
    if (modes_->currentIndex() != 2) {
        encap_audio_seek(seconds);
        refreshPlayback();
        return;
    }
    const auto selected = field({"video", "export_settings", "selected_chapter_ids"}).toArray();
    const auto chapters = project_.value("chapters").toArray();
    double start = 0;
    for (int index = 0; index < selected.size(); ++index) {
        QJsonObject chapter;
        for (const auto& value : chapters) if (value.toObject().value("id") == selected[index]) { chapter = value.toObject(); break; }
        const double duration = chapter.value("duration_seconds").toDouble();
        if (seconds >= start + duration && index + 1 < selected.size()) { start += duration; continue; }
        previewIndex_ = index;
        const auto sources = project_.value("audio_sources").toArray();
        const int source = chapter.value("chapter_number").toInt() - 1;
        if (source < 0 || source >= sources.size()) return;
        const auto path = sources[source].toObject().value("source_path").toString();
        const bool resume = play || encap_audio_playing();
        if (path == playingPath_) {
            encap_audio_seek(seconds - start);
            if (resume) { encap_audio_play(1); videoPlaying_ = true; }
        } else openPlayback(path, [this, seconds, start, resume](bool ready) {
            if (!ready) return;
            encap_audio_seek(seconds - start);
            if (resume) { encap_audio_play(1); videoPlaying_ = true; }
            refreshPlayback();
        });
        refreshVideo();
        break;
    }
}
void MainWindow::adjacent(int delta) {
    if (!hasProject_) return;
    if (modes_->currentIndex() == 2) {
        const auto selected = field({"video", "export_settings", "selected_chapter_ids"}).toArray();
        if (selected.isEmpty()) return;
        previewIndex_ = std::clamp(previewIndex_ + delta, 0, static_cast<int>(selected.size()) - 1);
        double start = 0;
        for (int i = 0; i < previewIndex_; ++i) {
            for (const auto& value : project_.value("chapters").toArray())
                if (value.toObject().value("id") == selected[i]) { start += value.toObject().value("duration_seconds").toDouble(); break; }
        }
        seekPlayback(start, true);
    } else {
        if (!sources_->rowCount()) return;
        const int next = std::clamp(sources_->currentRow() + delta, 0, sources_->rowCount() - 1);
        sources_->selectRow(next);
        encap_audio_close();
        playingPath_.clear();
        togglePlayback();
    }
}
void MainWindow::refreshPlayback() {
    const bool playing = encap_audio_playing();
    sourcePlay_->setText(playing ? "Pause" : "Play");
    videoPlay_->setText(playing ? "Pause" : "Play");
}
void MainWindow::tick() {
    if (!hasProject_) return;
    const auto sourceList = project_.value("audio_sources").toArray();
    double duration = 0;
    for (int i = 0; i < sourceList.size(); ++i) {
        const auto source = sourceList[i].toObject();
        if (source.value("source_path").toString() == playingPath_ ||
            (playingPath_.isEmpty() && i == sources_->currentRow())) {
            duration = source.value("duration_seconds").toDouble(); break;
        }
    }
    const double position = encap_audio_position();
    if (!sourceSeek_->isSliderDown()) sourceSeek_->setValue(static_cast<int>(position));
    sourceSeek_->setMaximum(std::max(1, static_cast<int>(duration)));
    sourceTime_->setText(shownTime(position) + " / " + shownTime(duration));
    double videoDuration = 0, offset = 0, chapterDuration = 0;
    QString title = "EnCap";
    const auto selected = field({"video", "export_settings", "selected_chapter_ids"}).toArray();
    for (int i = 0; i < selected.size(); ++i) {
        for (const auto& value : project_.value("chapters").toArray()) if (value.toObject().value("id") == selected[i]) {
            const auto chapter = value.toObject();
            const double length = chapter.value("duration_seconds").toDouble();
            if (i == previewIndex_) { offset = videoDuration; chapterDuration = length; title = chapter.value("title").toString(); }
            videoDuration += length;
            break;
        }
    }
    const double videoPosition = offset + std::min(position, chapterDuration);
    if (!videoSeek_->isSliderDown()) videoSeek_->setValue(static_cast<int>(videoPosition));
    videoTime_->setText(shownTime(videoPosition) + " / " + shownTime(videoDuration));
    if (videoPlaying_ && chapterDuration > 0 && (position >= chapterDuration || (!encap_audio_playing() && position > 0))) {
        videoPlaying_ = false;
        encap_audio_pause();
        if (previewIndex_ + 1 < selected.size()) adjacent(1);
    }
    refreshPlayback();
#ifdef ENCAP_HAS_MEDIA_SESSION
    if (mediaOwner_ == this) {
        if (modes_->currentIndex() != 2) title = sources_->currentRow() >= 0 ? sources_->item(sources_->currentRow(), 0)->text() : "EnCap";
        encap_media_update(title.toUtf8().constData(), modes_->currentIndex() == 2 ? videoPosition : position,
            modes_->currentIndex() == 2 ? videoDuration : duration, rate_, encap_audio_playing(), !busy_, volume_);
    }
#endif
}
void MainWindow::mediaAction(int action, double value) {
    auto* owner = mediaOwner_;
    if (!owner) return;
    QMetaObject::invokeMethod(owner, [owner, action, value] {
        if (owner->busy_) return;
        switch (action) {
        case 1: if (!encap_audio_playing()) owner->togglePlayback(); break;
        case 2: owner->pausePlayback(); break;
        case 3: owner->pausePlayback(); owner->seekPlayback(0); break;
        case 4: owner->adjacent(1); break;
        case 5: owner->adjacent(-1); break;
        case 6: owner->seekPlayback(value); break;
        case 7: owner->activateWindow(); break;
        case 8: encap_audio_play(value); owner->rate_ = value; break;
        case 9: encap_audio_volume(value); owner->volume_ = value; break;
        case 10: owner->togglePlayback(); break;
        }
    }, Qt::QueuedConnection);
}
void MainWindow::closeEvent(QCloseEvent* event) {
    if (closing_) { event->accept(); return; }
    event->ignore();
    if (!confirmReplace()) return;
    recoveryTimer_.stop();
    auto finish = [this] {
        closing_ = true;
        close();
    };
    runEngine("Clearing recovery…", {"clear-recovery"}, [finish](const QJsonValue&) { finish(); }, {}, finish);
}
void MainWindow::dragEnterEvent(QDragEnterEvent* event) {
    if (event->mimeData()->hasUrls()) event->acceptProposedAction();
}
void MainWindow::dropEvent(QDropEvent* event) {
    if (busy_) return;
    QStringList audio;
    for (const auto& url : event->mimeData()->urls()) {
        const auto path = url.toLocalFile();
        if (path.endsWith(".encap", Qt::CaseInsensitive)) { openProject(path); event->acceptProposedAction(); return; }
        if (QFileInfo(path).isDir()) { importFolder(path); event->acceptProposedAction(); return; }
        if (isAudioFile(path)) audio.append(path);
    }
    if (!audio.isEmpty()) { addFiles(audio); event->acceptProposedAction(); }
}
bool MainWindow::eventFilter(QObject* watched, QEvent* event) {
    if (videoChapters_ && watched == videoChapters_->viewport() && event->type() == QEvent::Drop) {
        auto* dropped = static_cast<QDropEvent*>(event);
        if (dropped->source() != videoChapters_) return false;
        const int target = videoChapters_->rowAt(dropped->position().toPoint().y());
        moveVideoTo(target < 0 ? videoChapters_->rowCount() - 1 : target);
        dropped->acceptProposedAction();
        return true;
    }
    if ((watched == sources_ || watched == sources_->viewport()) && event->type() == QEvent::KeyPress) {
        auto* key = static_cast<QKeyEvent*>(event);
        if (key->isAutoRepeat() || heldKeys_.contains(key->key())) return true;
        if (key->key() == Qt::Key_Space || key->key() == Qt::Key_J || key->key() == Qt::Key_K || key->key() == Qt::Key_L) {
            heldKeys_.insert(key->key());
            keyPressEvent(key);
            return true;
        }
        if (key->key() == Qt::Key_Delete || key->key() == Qt::Key_Backspace) { removeSources(); return true; }
    }
    if ((watched == sources_ || watched == sources_->viewport()) && event->type() == QEvent::KeyRelease) {
        auto* key = static_cast<QKeyEvent*>(event);
        heldKeys_.remove(key->key());
        keyReleaseEvent(key);
        if (key->key() == Qt::Key_K || key->key() == Qt::Key_J || key->key() == Qt::Key_L) return true;
    }
    return QMainWindow::eventFilter(watched, event);
}
void MainWindow::keyPressEvent(QKeyEvent* event) {
    if (event->key() == Qt::Key_Space) { togglePlayback(); return; }
    if (event->key() == Qt::Key_K) { slow_ = true; pausePlayback(); return; }
    if (event->key() == Qt::Key_J || event->key() == Qt::Key_L) {
        if (modes_->currentIndex() != 0 || sources_->currentRow() < 0) return;
        const int direction = event->key() == Qt::Key_J ? -1 : 1;
        const double next = slow_ ? direction * 0.5 : direction * (rate_ * direction > 0 ? std::min(32.0, std::max(1.0, std::abs(rate_) * 2)) : 1.0);
        const auto path = sources_->item(sources_->currentRow(), 0)->data(Qt::UserRole).toString();
        if (path == playingPath_) { rate_ = next; encap_audio_play(rate_); }
        else openPlayback(path, [this, next](bool ready) { if (ready) { rate_ = next; encap_audio_play(rate_); } });
        return;
    }
    QMainWindow::keyPressEvent(event);
}
void MainWindow::keyReleaseEvent(QKeyEvent* event) {
    if (event->key() == Qt::Key_K) { slow_ = false; pausePlayback(); return; }
    if (slow_ && (event->key() == Qt::Key_J || event->key() == Qt::Key_L)) { pausePlayback(); return; }
    QMainWindow::keyReleaseEvent(event);
}
void MainWindow::setAppearance(const QString& preference) {
    const auto selected = QStringList{"light", "dark"}.contains(preference) ? preference : "system";
    static const QPalette systemPalette = QApplication::palette();
    if (selected == "system") QApplication::setPalette(systemPalette);
    else {
        QPalette palette;
        const bool dark = selected == "dark";
        palette.setColor(QPalette::Window, dark ? QColor("#20232a") : QColor("#f6f7fa"));
        palette.setColor(QPalette::WindowText, dark ? Qt::white : Qt::black);
        palette.setColor(QPalette::Base, dark ? QColor("#181b20") : Qt::white);
        palette.setColor(QPalette::AlternateBase, dark ? QColor("#292d35") : QColor("#eceff5"));
        palette.setColor(QPalette::Text, dark ? Qt::white : Qt::black);
        palette.setColor(QPalette::Button, dark ? QColor("#303640") : QColor("#e7eaf0"));
        palette.setColor(QPalette::ButtonText, dark ? Qt::white : Qt::black);
        palette.setColor(QPalette::Highlight, QColor("#3b82f6"));
        palette.setColor(QPalette::HighlightedText, Qt::white);
        QApplication::setPalette(palette);
    }
    if (appearanceSystem_) appearanceSystem_->setChecked(selected == "system");
    if (appearanceLight_) appearanceLight_->setChecked(selected == "light");
    if (appearanceDark_) appearanceDark_->setChecked(selected == "dark");
    QFile file(preferencePath("appearance.txt"));
    if (file.open(QIODevice::WriteOnly)) file.write(selected.toUtf8());
}
void MainWindow::checkUpdates(bool manual) {
    if (internalReference() || updateRunning_ || busy_ || dirty_) return;
    updateRunning_ = true;
    auto* process = new QProcess(this);
    process->setProgram(updaterPath());
    process->setArguments({manual ? "check" : "check-auto"});
    connect(process, qOverload<int, QProcess::ExitStatus>(&QProcess::finished), this,
            [this, process, manual](int code, QProcess::ExitStatus status) {
        const auto stdoutBytes = process->readAllStandardOutput();
        const auto stderrText = QString::fromUtf8(process->readAllStandardError());
        process->deleteLater();
        updateRunning_ = false;
        if (status != QProcess::NormalExit || code != 0) {
            if (manual) fail(stderrText.isEmpty() ? "Update check failed." : stderrText);
            return;
        }
        QString error;
        const auto result = EngineClient::parseResponse(stdoutBytes, &error);
        if (!error.isEmpty()) { if (manual) fail(error); return; }
        updateResult(result, manual);
    });
    connect(process, &QProcess::errorOccurred, this, [this, process, manual](QProcess::ProcessError error) {
        if (error == QProcess::FailedToStart) {
            updateRunning_ = false;
            if (manual) fail("Could not start the authenticated update helper.");
            process->deleteLater();
        }
    });
    process->start();
}
void MainWindow::updateResult(const QJsonValue& result, bool manual) {
    const auto update = result.toObject();
    if (!update.value("available").toBool()) {
        if (manual) setStatus("No newer compatible stable update is available.");
        return;
    }
    if (update.value("manual_migration").toBool()) {
        setStatus("This update requires manual migration: " + update.value("release_notes_url").toString());
        return;
    }
    if (QMessageBox::question(this, "EnCap " + update.value("version").toString() + " is available",
        "Download and install this authenticated update? Save your project first.") != QMessageBox::Yes) return;
    if (dirty_ || busy_) { setStatus("Save your work and finish the current operation before updating."); return; }
    auto* download = new QProcess(this);
    download->setProgram(updaterPath());
#ifdef Q_OS_LINUX
    const bool appimage = !qEnvironmentVariable("APPIMAGE").isEmpty();
    download->setArguments({appimage ? "install-appimage" : "download"});
#else
    download->setArguments({"download"});
#endif
    updateRunning_ = true;
    connect(download, qOverload<int, QProcess::ExitStatus>(&QProcess::finished), this,
            [this, download](int code, QProcess::ExitStatus status) {
        const auto bytes = download->readAllStandardOutput();
        const auto errors = QString::fromUtf8(download->readAllStandardError());
        download->deleteLater();
        updateRunning_ = false;
        if (status != QProcess::NormalExit || code != 0) { fail(errors.isEmpty() ? "Authenticated update failed." : errors); return; }
#ifdef Q_OS_LINUX
        if (!qEnvironmentVariable("APPIMAGE").isEmpty()) {
            setStatus("Update installed. Save and restart EnCap when ready; the previous AppImage is retained.");
            return;
        }
#endif
        QString parseError;
        const auto artifact = EngineClient::parseResponse(bytes, &parseError).toObject();
        if (!parseError.isEmpty()) { fail(parseError); return; }
#ifdef Q_OS_WIN
        if (dirty_ || busy_) { setStatus("Update downloaded. Save your work before installing."); return; }
        const auto temporary = QDir::tempPath() + "/encap-portable-helper-" + QUuid::createUuid().toString(QUuid::WithoutBraces);
        if (!QDir().mkpath(temporary)) { fail("Could not stage the portable updater."); return; }
        const auto helper = temporary + "/encap-portable-update.exe";
        if (!QFile::copy(QCoreApplication::applicationDirPath() + "/encap-portable-update.exe", helper)) {
            fail("Could not stage the portable updater."); return;
        }
        const auto ready = temporary + "/ready";
        const QStringList arguments = {artifact.value("path").toString(), artifact.value("sha256").toString(),
            QCoreApplication::applicationDirPath(), QString::number(QCoreApplication::applicationPid()),
            artifact.value("target").toString(), artifact.value("version").toString(), ready};
        qint64 helperPid = 0;
        if (!QProcess::startDetached(helper, arguments, temporary, &helperPid)) {
            fail("Could not start portable update verification."); return;
        }
        auto* timer = new QTimer(this);
        auto attempts = std::make_shared<int>(0);
        connect(timer, &QTimer::timeout, this, [this, timer, attempts, ready, helperPid] {
            if (QFile::exists(ready)) {
                timer->stop(); timer->deleteLater();
                if (dirty_ || busy_) {
                    QProcess::startDetached("taskkill", {"/T", "/F", "/PID", QString::number(helperPid)});
                    setStatus("Installation cancelled because the project changed. Save and retry.");
                    return;
                }
                closing_ = true;
                close();
            } else if (++*attempts >= 1200) {
                timer->stop(); timer->deleteLater();
                QProcess::startDetached("taskkill", {"/T", "/F", "/PID", QString::number(helperPid)});
                fail("Installer verification timed out; EnCap remains open.");
            }
        });
        timer->start(100);
#else
        setStatus("Verified update downloaded to " + artifact.value("path").toString() + ". Replace your AppImage after quitting.");
#endif
    });
    download->start();
}
