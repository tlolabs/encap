#include "main_window.h"
#include <QApplication>
#include <QCoreApplication>
#include <QFileInfo>
#include <QIcon>

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    QCoreApplication::setOrganizationName(QStringLiteral("TLO Labs"));
    QCoreApplication::setApplicationName(QStringLiteral("EnCap"));
#ifdef Q_OS_MACOS
    QCoreApplication::setApplicationName(QStringLiteral("EnCap INTERNAL Qt Reference"));
#endif
    app.setWindowIcon(QIcon(QStringLiteral(":/icons/EnCap.png")));
    MainWindow window;
    window.show();
    if (argc > 1) window.openInitialPath(QFileInfo(QString::fromLocal8Bit(argv[1])).absoluteFilePath());
    return app.exec();
}
