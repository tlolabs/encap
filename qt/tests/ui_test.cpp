#include "main_window.h"

#include <QAccessible>
#include <QAction>
#include <QApplication>
#include <QCoreApplication>
#include <QDataStream>
#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QFileDialog>
#include <QLabel>
#include <QLineEdit>
#include <QMenuBar>
#include <QDebug>
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
