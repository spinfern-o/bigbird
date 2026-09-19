from PySide6.QtGui import QColor, QFont, QPalette

ACCENT = "#2f7fe0"

STYLE = f"""
QWidget {{ font-size: 13px; }}
QMainWindow, QDockWidget {{ background: #252528; }}
QToolBar {{ background: #2d2d31; border: none; spacing: 4px; padding: 3px; }}
QToolBar#toolsBar {{ padding: 6px 3px; }}
QToolBar#toolsBar QToolButton {{ min-width: 58px; padding: 6px 2px; border-radius: 8px;
                                 font-size: 11px; color: #cfcfd4; }}
QToolBar#toolsBar QToolButton:hover {{ background: #3a3a40; }}
QToolBar#toolsBar QToolButton:checked {{ background: {ACCENT}; color: white; }}
QToolBar#optionsBar {{ background: #29292d; border-top: 1px solid #1c1c1f;
                       border-bottom: 1px solid #1c1c1f; min-height: 36px; }}
QLabel#optTitle {{ font-weight: bold; color: #6cb4ff; }}
QToolButton {{ padding: 4px 8px; border-radius: 6px; }}
QToolButton:hover {{ background: #3a3a40; }}
QToolButton:checked {{ background: #3d4f66; }}
QPushButton {{ background: #3a3a40; border: 1px solid #48484f; border-radius: 6px;
               padding: 5px 12px; color: #e8e8ec; }}
QPushButton:hover {{ background: #45454c; }}
QPushButton:pressed {{ background: #2f2f35; }}
QPushButton:disabled {{ color: #77777d; background: #2f2f33; }}
QPushButton#accent, QPushButton#bigAccent {{ background: {ACCENT}; border-color: {ACCENT};
                                             color: white; font-weight: bold; }}
QPushButton#accent:hover, QPushButton#bigAccent:hover {{ background: #4a93ea; }}
QPushButton#big, QPushButton#bigAccent {{ font-size: 16px; padding: 14px 28px; border-radius: 10px; }}
QToolButton#preset {{ background: #2f2f34; border: 1px solid #3a3a40; border-radius: 8px;
                      font-size: 11px; padding: 3px; }}
QToolButton#preset:hover {{ border-color: {ACCENT}; background: #34343a; }}
QToolButton#sectionHeader {{ font-weight: bold; font-size: 13px; background: #303035;
                             border-radius: 6px; padding: 7px; text-align: left; }}
QTabWidget::pane {{ border: none; background: #252528; }}
QTabBar::tab {{ background: #2d2d31; color: #bbb; padding: 9px 22px; border: none;
                border-bottom: 2px solid transparent; font-weight: bold; }}
QTabBar::tab:selected {{ color: white; border-bottom: 2px solid {ACCENT}; }}
QSlider::groove:horizontal {{ height: 4px; background: #4a4a52; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: #e8e8ec; width: 14px; height: 14px; margin: -5px 0;
                              border-radius: 7px; }}
QSlider::handle:horizontal:hover {{ background: white; }}
QSlider::sub-page:horizontal {{ background: transparent; }}
QScrollArea {{ border: none; }}
QListWidget {{ background: #1f1f22; border: 1px solid #333; border-radius: 6px; }}
QListWidget::item {{ padding: 4px; border-radius: 4px; }}
QListWidget::item:selected {{ background: #3d4f66; color: white; }}
QStatusBar {{ background: #2d2d31; color: #bdbdc3; }}
QLabel#hintLabel {{ color: #a8a8b0; }}
QLabel#welcomeTitle {{ font-size: 48px; font-weight: 800; color: white; }}
QLabel#welcomeSub {{ font-size: 18px; color: #b8b8c0; }}
QLabel#welcomeHint {{ color: #8a8a92; }}
QLabel#stepCard {{ background: #2e2e33; border: 1px solid #3a3a40; border-radius: 10px;
                   padding: 12px; }}
QMenu {{ background: #2d2d31; border: 1px solid #444; }}
QMenu::item {{ padding: 6px 24px; }}
QMenu::item:selected {{ background: {ACCENT}; }}
QToolTip {{ background: #111; color: #eee; border: 1px solid #555; padding: 6px; }}
"""


def apply(app):
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    p = QPalette()
    for role, c in ((QPalette.Window, "#252528"), (QPalette.WindowText, "#e8e8ec"),
                    (QPalette.Base, "#1f1f22"), (QPalette.AlternateBase, "#2a2a2e"),
                    (QPalette.Text, "#e8e8ec"), (QPalette.Button, "#3a3a40"),
                    (QPalette.ButtonText, "#e8e8ec"), (QPalette.Highlight, ACCENT),
                    (QPalette.HighlightedText, "#ffffff"), (QPalette.ToolTipBase, "#111111"),
                    (QPalette.ToolTipText, "#eeeeee"), (QPalette.PlaceholderText, "#88888f")):
        p.setColor(role, QColor(c))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor("#6a6a70"))
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor("#6a6a70"))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#6a6a70"))
    app.setPalette(p)
    app.setStyleSheet(STYLE)
