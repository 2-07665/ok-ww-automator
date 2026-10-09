"""Black overlays owned by the launcher; no system display settings are changed."""

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QWidget


class BlackScreen(QWidget):
    dismissed = Signal()

    def __init__(self, screen):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setScreen(screen)
        self.setGeometry(screen.geometry())
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("black"))
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        self.setCursor(Qt.CursorShape.BlankCursor)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.dismissed.emit()
        event.accept()

    def mousePressEvent(self, event):
        self.dismissed.emit()
        event.accept()

    def closeEvent(self, event):
        self.dismissed.emit()
        event.accept()


class ScreenSaver(QObject):
    def __init__(self, launcher):
        super().__init__(launcher)
        self.launcher = launcher
        self.windows = []
        QGuiApplication.instance().screenAdded.connect(self._screen_added)
        QGuiApplication.instance().screenRemoved.connect(self.hide)

    def show(self):
        if self.windows:
            return
        for screen in QGuiApplication.screens():
            self._add_screen(screen)
        if self.windows:
            self.windows[0].activateWindow()
            self.windows[0].setFocus()

    def _add_screen(self, screen):
        window = BlackScreen(screen)
        window.dismissed.connect(self.hide)
        self.windows.append(window)
        window.showFullScreen()

    def _screen_added(self, screen):
        if self.windows:
            self._add_screen(screen)

    def hide(self):
        if not self.windows:
            return
        windows, self.windows = self.windows, []
        for window in windows:
            window.hide()
            window.deleteLater()
        self.launcher.raise_()
        self.launcher.activateWindow()
