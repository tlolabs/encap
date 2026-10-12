#pragma once

#include "engine_client.h"
#include <QJsonArray>
#include <QJsonObject>
#include <QMainWindow>
#include <QTimer>
#include <QSet>
#include <functional>

class QAction;
class QCheckBox;
class QComboBox;
class QLabel;
class QLineEdit;
class QListWidget;
class QPlainTextEdit;
class QProcess;
class QProgressBar;
class QPushButton;
class QSlider;
class QSpinBox;
class QDoubleSpinBox;
class QTabWidget;
class QTableWidget;
class QWidget;

class MainWindow final : public QMainWindow {
public:
    MainWindow();
    ~MainWindow() override;
    void openInitialPath(const QString& path);

protected:
    void closeEvent(QCloseEvent* event) override;
    void dragEnterEvent(QDragEnterEvent* event) override;
    void dropEvent(QDropEvent* event) override;
    void keyPressEvent(QKeyEvent* event) override;
    void keyReleaseEvent(QKeyEvent* event) override;
    bool eventFilter(QObject* watched, QEvent* event) override;

private:
    using Result = std::function<void(const QJsonValue&)>;
    void buildUi();
    QWidget* buildAudioPage();
    QWidget* buildTranscriptPage();
    QWidget* buildVideoPage();
    void buildMenus();
    void runEngine(const QString& status, const QStringList& arguments, Result result,
                   const QJsonValue& payload = {}, std::function<void()> failed = {});
    void fail(const QString& error);
    void setStatus(const QString& status, bool error = false);
    void setBusy(bool busy);
    void present(const QJsonObject& project, bool changed);
    void refreshUi();
    void refreshSources();
    void refreshChapters();
    void refreshSegments();
    void refreshVideo();
    void refreshPlayback();
    void markDirty();
    void setField(const QStringList& path, const QJsonValue& value);
    QJsonValue field(const QStringList& path) const;
    void updateTitle();
    bool confirmReplace(bool modeSwitch = false);
    void importFolder(const QString& requested = {});
    void openProject(const QString& path = {});
    void addFiles(const QStringList& files = {});
    void removeSources();
    void saveProject(bool saveAs = false, std::function<void(bool)> completed = {});
    void switchMode(int index);
    void chooseArtwork(bool chapter);
    void addChapter();
    void removeChapter();
    void applyChapterNames();
    void exportFile(const QString& kind);
    void transcribe();
    void refreshModels();
    void changeModel(bool remove);
    void syncVideoSelection();
    void moveVideo(int delta);
    void moveVideoTo(int destination);
    void loadWaveforms();
    void loadWaveformAt(const QJsonArray& paths, int row, int generation);
    void togglePlayback();
    void openPlayback(const QString& path, std::function<void(bool)> completed);
    void pausePlayback();
    void seekPlayback(double seconds, bool play = false);
    void adjacent(int delta);
    void tick();
    void setAppearance(const QString& preference);
    void checkUpdates(bool manual);
    void updateResult(const QJsonValue& result, bool manual);
    static void mediaAction(int action, double value);
    QString dataDirectory() const;
    QString preferencePath(const QString& name) const;
    QString enginePath() const;
    QString updaterPath() const;
    bool internalReference() const;

    EngineClient* engine_ = nullptr;
    EngineClient* previewEngine_ = nullptr;
    EngineClient* waveformEngine_ = nullptr;
    QJsonObject project_;
    QJsonArray providers_, models_, presets_;
    QTimer recoveryTimer_, clock_, updateTimer_;
    bool hasProject_ = false, dirty_ = false, busy_ = false, loading_ = false;
    bool closing_ = false, videoPlaying_ = false, updateRunning_ = false;
    int previewIndex_ = 0;
    double rate_ = 1, volume_ = 1;
    QString playingPath_, temporaryPreview_;
    QProcess* decoder_ = nullptr;
    QSet<int> heldKeys_;
    bool slow_ = false;
    QStringList videoOrder_;
    int waveformGeneration_ = 0;
    QTabWidget* modes_ = nullptr;
    QLabel* status_ = nullptr;
    QProgressBar* progress_ = nullptr;
    QPushButton* cancel_ = nullptr;
    QTableWidget* sources_ = nullptr;
    QSlider* sourceSeek_ = nullptr;
    QLabel* sourceTime_ = nullptr;
    QPushButton* sourcePlay_ = nullptr;
    QLineEdit* podcastTitle_ = nullptr;
    QLineEdit* episodeTitle_ = nullptr;
    QPlainTextEdit* summary_ = nullptr;
    QLabel* episodeArtwork_ = nullptr;
    QComboBox* audioFormat_ = nullptr;
    QComboBox* audioBitrate_ = nullptr;
    QComboBox* audioChannels_ = nullptr;
    QComboBox* naming_ = nullptr;
    QTableWidget* chapters_ = nullptr;
    QComboBox* provider_ = nullptr;
    QCheckBox* wordTimestamps_ = nullptr;
    QTableWidget* segments_ = nullptr;
    QTableWidget* modelList_ = nullptr;
    QTableWidget* videoChapters_ = nullptr;
    QComboBox* preset_ = nullptr;
    QComboBox* codec_ = nullptr;
    QComboBox* encoding_ = nullptr;
    QComboBox* previewQuality_ = nullptr;
    QComboBox* videoBitrate_ = nullptr;
    QSpinBox* videoWidth_ = nullptr;
    QSpinBox* videoHeight_ = nullptr;
    QSpinBox* videoFps_ = nullptr;
    QCheckBox* flipHorizontal_ = nullptr;
    QCheckBox* flipVertical_ = nullptr;
    QLabel* videoArtwork_ = nullptr;
    QLabel* videoSummary_ = nullptr;
    QLabel* videoPreview_ = nullptr;
    QSlider* videoSeek_ = nullptr;
    QLabel* videoTime_ = nullptr;
    QPushButton* videoPlay_ = nullptr;
    QAction* saveAction_ = nullptr;
    QAction* automaticUpdates_ = nullptr;
    QAction* appearanceSystem_ = nullptr;
    QAction* appearanceLight_ = nullptr;
    QAction* appearanceDark_ = nullptr;
    static MainWindow* mediaOwner_;
};
