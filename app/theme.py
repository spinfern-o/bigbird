from PySide6.QtGui import QColor, QFont, QPalette

ACCENT = "#2f7fe0"

STYLE = f"""
QWidget {{ font-size: 12px; }}
QMainWindow, QDockWidget {{ background: #252528; }}
QWidget#editorWorkspace {{ background: #141416; }}
QMenuBar {{ background: #252528; color: #cfcfd4; border-bottom: 1px solid #34343a; }}
QMenuBar::item {{ padding: 6px 9px; background: transparent; }}
QMenuBar::item:selected {{ background: #333338; }}
QToolBar {{ background: #2d2d31; border: none; spacing: 4px; padding: 3px; }}
QToolBar#mainBar {{ background: #252528; border-bottom: 1px solid #34343a; min-height: 40px; }}
QLabel#brandMark {{ background: {ACCENT}; color: white; border-radius: 5px; font-weight: 700; }}
QLabel#brandName {{ color: #e8e8ec; font-size: 14px; font-weight: 650; padding: 0 8px 0 6px; }}
QLabel#documentMeta {{ color: #8a8a92; font-size: 11px; padding-right: 8px; }}
QToolBar#toolsBar {{ padding: 6px 7px; background: #232326; border-right: 1px solid #46464e; }}
QToolBar#toolsBar QToolButton {{ min-width: 56px; max-width: 56px; min-height: 48px;
                                 padding: 3px 0; border-radius: 4px;
                                 font-size: 9px; color: #afafb6; }}
QToolBar#toolsBar QToolButton:hover {{ background: #3a3a40; }}
QToolBar#toolsBar QToolButton:checked {{ background: #244e7d; color: white; border: 1px solid #2f7fe0; }}
QToolBar#optionsBar {{ background: #2d2d31; border-top: 1px solid #34343a;
                       border-bottom: 1px solid #46464e; min-height: 34px; }}
QLabel#optTitle {{ font-weight: 650; color: #e8e8ec; }}
QToolButton {{ padding: 4px 8px; border-radius: 3px; }}
QToolButton:hover {{ background: #3a3a40; }}
QToolButton:checked {{ background: #3d4f66; }}
QPushButton {{ background: #202024; border: 1px solid #46464e; border-radius: 4px;
               padding: 5px 12px; color: #e8e8ec; }}
QPushButton:hover {{ background: #45454c; }}
QPushButton:pressed {{ background: #2f2f35; }}
QPushButton:disabled {{ color: #77777d; background: #2f2f33; }}
QPushButton#accent, QPushButton#bigAccent {{ background: {ACCENT}; border-color: {ACCENT};
                                             color: white; font-weight: bold; }}
QPushButton#accent:hover, QPushButton#bigAccent:hover {{ background: #4a93ea; }}
QPushButton#big, QPushButton#bigAccent {{ font-size: 16px; padding: 14px 28px; border-radius: 10px; }}
QToolButton#preset {{ background: #2f2f34; border: 1px solid #3a3a40; border-radius: 4px;
                      font-size: 11px; padding: 3px; }}
QToolButton#preset:hover {{ border-color: {ACCENT}; background: #34343a; }}
QToolButton#sectionHeader {{ font-weight: bold; font-size: 12px; background: #303035;
                             border-radius: 3px; padding: 7px; text-align: left; }}
QTabWidget::pane {{ border: none; background: #252528; }}
QDockWidget#inspectorDock {{ border-left: 1px solid #46464e; }}
QTabBar::tab {{ background: #252528; color: #8a8a92; min-width: 58px; padding: 11px 6px;
                border: none; border-bottom: 2px solid transparent; font-size: 10px; }}
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
QStatusBar {{ background: #252528; color: #8a8a92; border-top: 1px solid #46464e; }}
QStatusBar QLabel {{ font-size: 10px; padding: 0 6px; }}
QLabel#localStatus {{ color: #6fb0ff; }}
QFrame#filmstrip {{ background: #202024; border-top: 1px solid #46464e; }}
QWidget#filmstripHeader {{ background: #202024; border-bottom: 1px solid #34343a; }}
QLabel#filmstripTitle {{ color: #e8e8ec; font-size: 11px; font-weight: 650; }}
QLabel#filmstripCount, QLabel#filmstripEmpty {{ color: #8a8a92; font-size: 10px; }}
QPushButton#filmstripAction, QPushButton#filmstripActionAccent {{ background: transparent;
  border: none; padding: 3px 7px; font-size: 10px; }}
QPushButton#filmstripAction {{ color: #a8a8b0; }}
QPushButton#filmstripActionAccent {{ color: #6fb0ff; }}
QScrollArea#filmstripScroll, QWidget#filmstripItems {{ background: #202024; }}
QToolButton#filmThumb {{ width: 116px; height: 82px; padding: 2px; border-radius: 2px;
  color: #a8a8b0; font-size: 9px; background: #17171a; border: 1px solid #46464e; }}
QToolButton#filmThumb:hover {{ border-color: #6fb0ff; }}
QToolButton#filmThumb:checked {{ border: 2px solid #4a93ea; color: white; }}
QLabel#hintLabel {{ color: #a8a8b0; }}
QLabel#welcomeTitle {{ font-size: 48px; font-weight: 800; color: white; }}
QLabel#welcomeSub {{ font-size: 18px; color: #b8b8c0; }}
QLabel#welcomeHint {{ color: #8a8a92; }}
QLabel#stepCard {{ background: #2e2e33; border: 1px solid #3a3a40; border-radius: 10px;
                   padding: 12px; }}
QFrame#aiCard {{ background: #2e2e33; border: 1px solid #3a3a40; border-radius: 10px; }}
QFrame#maskBox {{ background: #2b2b30; border: 1px solid #3a3a40; border-radius: 6px; }}
QLabel#maskThumb {{ background: #1c1c1e; border: 1px solid #3a3a40; border-radius: 4px; }}
QLabel#aiCardTitle {{ font-weight: bold; font-size: 14px; color: white; }}
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
