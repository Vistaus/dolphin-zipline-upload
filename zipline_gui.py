#!/usr/bin/env python3
"""Windowed settings GUI (PySide6) for Zipline Upload for Dolphin.

Launched by `zipline-upload.py --configure`, either in-process (when PySide6
is importable) or via the addon's venv interpreter
(~/.local/share/zipline-upload/venv/bin/python). All settings logic — config
loading/saving, script import, connection test — comes from the worker module
(zipline-upload.py), which this file loads by path.

Visual language: dark green-black base, single teal accent family, rounded
cards, sidebar navigation (see planning/ui-inspiration/).

Exit codes: 0 settings saved, 1 cancelled/closed without saving.

Extra modes (mainly for development):
    --screenshot PATH   render every page offscreen and save PNGs
    --demo              show the window for 4 seconds, then close
"""

import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "zu", os.path.join(_HERE, "zipline-upload.py"))
zu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(zu)

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

APP_NAME = "Zipline Upload"
GREEN = '<span style="color:#34d399">{}</span>'
RED = '<span style="color:#f87171">{}</span>'

# --------------------------------------------------------------------------- #
#  Theme — dark green-black + teal accent (QSS; applied app-wide)
# --------------------------------------------------------------------------- #

THEME_QSS = """
QDialog, QStackedWidget { background: #0d1210; color: #f5f7f6; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical {
    background: #232d29; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #2a3531; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 2px; }
QScrollBar::handle:horizontal {
    background: #232d29; border-radius: 4px; min-width: 30px; }
QScrollBar::handle:horizontal:hover { background: #2a3531; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QFrame#sidebar { background: #0a0e0d; border-right: 1px solid #232d29; }
QFrame#card { background: #141b18; border: 1px solid #232d29; border-radius: 14px; }
QLabel { color: #9ca8a3; }
QLabel#brandName { color: #f5f7f6; font-size: 15px; font-weight: 700; }
QLabel#brandSub  { color: #6b7a74; font-size: 11px; }
QLabel#chip {
    background: #12201c; border: 1px solid #1f4a3d; border-radius: 8px;
    color: #2dd4a8; font-size: 10px; font-weight: 600; padding: 1px 8px;
}
QLabel#sectionTitle { color: #6b7a74; font-size: 11px; font-weight: 600; }
QLabel#urlHint, QLabel#historyHint { color: #6b7a74; }
QLabel#sidebarFoot { color: #4a564f; font-size: 10px; }

QPushButton#navButton {
    background: transparent; border: none; border-radius: 10px;
    padding: 9px 12px; text-align: left; color: #9ca8a3;
    font-weight: 600; font-size: 13px;
}
QPushButton#navButton:hover { background: #141b18; }
QPushButton#navButton:checked {
    background: #1b2420; border-left: 3px solid #2dd4a8; color: #f5f7f6;
}

QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {
    background: #101614; border: 1px solid #2a3531; border-radius: 8px;
    padding: 6px 8px; color: #f5f7f6; selection-background-color: #2dd4a8;
    selection-color: #04211b;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus {
    border: 1px solid #2dd4a8;
}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {
    color: #6b7a74; background: #0d1210;
}
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow {
    image: none; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-top: 5px solid #6b7a74;
    margin-right: 8px;
}
QComboBox QAbstractItemView {
    background: #161e1b; border: 1px solid #2a3531; color: #f5f7f6;
    selection-background-color: #1c2622; selection-color: #f5f7f6;
    border-radius: 8px; padding: 4px;
}
QSpinBox::up-button, QSpinBox::down-button {
    background: #141b18; border: none; width: 18px; }
QSpinBox::up-arrow { border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-bottom: 5px solid #6b7a74; }
QSpinBox::down-arrow { border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-top: 5px solid #6b7a74; }

QGroupBox {
    background: #101614; border: 1px solid #2a3531; border-radius: 10px;
    margin-top: 12px; color: #9ca8a3; font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 12px; padding: 0 4px; color: #9ca8a3;
}
QCheckBox { color: #f5f7f6; spacing: 8px; }
QCheckBox:disabled { color: #6b7a74; }
QCheckBox::indicator {
    width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid #2a3531; background: #101614;
}
QCheckBox::indicator:checked { background: #2dd4a8; border-color: #2dd4a8; }
QGroupBox::indicator {
    width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid #2a3531; background: #101614;
}
QGroupBox::indicator:checked { background: #2dd4a8; border-color: #2dd4a8; }

QPushButton {
    background: #1a2320; border: 1px solid #2a3531; border-radius: 10px;
    padding: 8px 16px; color: #f5f7f6; font-weight: 600;
}
QPushButton:hover { border-color: #2dd4a8; color: #2dd4a8; }
QPushButton:disabled { color: #4a564f; background: #141b18; }
QPushButton#primaryButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 #1fbf9a, stop:1 #2dd4a8);
    color: #04211b; border: none; font-weight: 700;
}
QPushButton#primaryButton:hover { color: #04211b; background:
    qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2dd4a8, stop:1 #4ce4bd); }
QToolButton {
    background: transparent; border: 1px solid #2a3531; border-radius: 6px;
    padding: 4px 10px; color: #9ca8a3; font-weight: 600;
}
QToolButton:hover { border-color: #2dd4a8; color: #2dd4a8; }
QToolButton:checked { border-color: #2dd4a8; color: #2dd4a8; }

QTableWidget {
    background: #101614; alternate-background-color: #141b18;
    border: 1px solid #2a3531; border-radius: 10px; gridline-color: #232d29;
    color: #f5f7f6; selection-background-color: #1c2622;
    selection-color: #f5f7f6;
}
QHeaderView::section {
    background: #161e1b; color: #6b7a74; border: none;
    border-bottom: 1px solid #232d29; border-radius: 0px; padding: 6px;
    font-weight: 600;
}
QTableWidget::item { padding: 4px; }
QTableCornerButton::section { background: #161e1b; border: none; }
"""

NAV_ITEMS = [  # (key, icon theme name, label)
    ("server", "network-server", "Server"),
    ("options", "settings-configure", "Upload Options"),
    ("behaviour", "system-run", "Behaviour"),
    ("history", "view-history", "History"),
]


class TestWorker(QtCore.QThread):
    """Runs the connection test off the GUI thread."""

    message = QtCore.Signal(str)

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self._cfg = cfg

    def run(self):  # executed in the worker thread
        self.message.emit(zu.run_connection_test(self._cfg))


class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = dict(cfg)
        self.saved = False
        self._test_worker = None

        self.setWindowTitle("Zipline Upload — Settings[*]")
        self.setWindowIcon(QtGui.QIcon.fromTheme("cloud-upload"))
        self.setMinimumSize(660, 560)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        body = QtWidgets.QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_sidebar())

        self.stack = QtWidgets.QStackedWidget()
        for builder in (self._build_server_page, self._build_options_page,
                        self._build_behaviour_page, self._build_history_page):
            self.stack.addWidget(self._wrap_in_card(builder))
        body.addWidget(self.stack, 1)

        outer.addLayout(body, 1)
        outer.addLayout(self._build_button_row())

        self.populate()
        self.setWindowModified(False)
        self._wire_dirty_tracking()
        self._size_to_screen()

    def _size_to_screen(self):
        """Open at a comfortable size for the screen it lands on: large
        enough that pages don't need internal scrollbars with real system
        fonts, but never more than a fraction of the available desktop."""
        width, height = 840, 740
        screen = self.screen() or QtWidgets.QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            width = min(width, max(self.minimumWidth(),
                                  int(available.width() * 0.44)))
            height = min(height, max(self.minimumHeight(),
                                     int(available.height() * 0.80)))
        self.layout().activate()
        target = QtCore.QSize(width, height).expandedTo(self.minimumSizeHint())
        self.resize(target)

    def _wire_dirty_tracking(self):
        """Flag the window as modified when any setting actually changes,
        so the unsaved-changes guard in closeEvent() has something to check."""
        def mark(*_):
            if not self.saved:
                self.setWindowModified(True)

        pairs = (
            (self.url_edit, "textChanged"),
            (self.token_edit, "textChanged"),
            (self.env_token_check, "toggled"),
            (self.format_combo, "currentIndexChanged"),
            (self.original_check, "toggled"),
            (self.compress_group, "toggled"),
            (self.compress_spin, "valueChanged"),
            (self.compress_type, "currentIndexChanged"),
            (self.password_edit, "textChanged"),
            (self.views_spin, "valueChanged"),
            (self.expires_edit, "textChanged"),
            (self.extless_check, "toggled"),
            (self.extra_edit, "textChanged"),
            (self.action_combo, "currentIndexChanged"),
            (self.clipboard_combo, "currentIndexChanged"),
            (self.notify_check, "toggled"),
            (self.progress_combo, "currentIndexChanged"),
            (self.timeout_spin, "valueChanged"),
        )
        for widget, signal_name in pairs:
            getattr(widget, signal_name).connect(mark)

    # ------------------------------------------------------------------ #
    #  Chrome: sidebar + pages + buttons
    # ------------------------------------------------------------------ #

    def _build_sidebar(self):
        sidebar = QtWidgets.QFrame(objectName="sidebar")
        sidebar.setFixedWidth(190)
        column = QtWidgets.QVBoxLayout(sidebar)
        column.setContentsMargins(14, 16, 14, 14)
        column.setSpacing(6)

        brand = QtWidgets.QHBoxLayout()
        tile = QtWidgets.QLabel()
        tile.setFixedSize(30, 30)
        tile.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        tile.setPixmap(QtGui.QIcon.fromTheme("cloud-upload").pixmap(18, 18))
        tile.setStyleSheet(
            "background: rgba(45, 212, 168, 0.15); border-radius: 9px;"
            "border: 1px solid #1f4a3d;")
        names = QtWidgets.QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(QtWidgets.QLabel("Zipline Upload",
                                         objectName="brandName"))
        names.addWidget(QtWidgets.QLabel("Settings", objectName="brandSub"))
        brand.addWidget(tile)
        brand.addSpacing(8)
        brand.addLayout(names)
        brand.addStretch(1)
        column.addLayout(brand)

        chip = QtWidgets.QLabel(f"v{zu.VERSION}", objectName="chip")
        chip.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        chip.setFixedWidth(52)
        column.addWidget(chip, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
        column.addSpacing(12)

        self._nav_buttons = []
        group = QtWidgets.QButtonGroup(self)
        group.setExclusive(True)
        for index, (_key, icon_name, label) in enumerate(NAV_ITEMS):
            button = QtWidgets.QPushButton(
                QtGui.QIcon.fromTheme(icon_name), label,
                objectName="navButton")
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            group.addButton(button, index)
            button.clicked.connect(
                lambda _=False, i=index: self._goto_page(i))
            column.addWidget(button)
            self._nav_buttons.append(button)
        column.addStretch(1)

        foot = QtWidgets.QLabel(
            "Right-click any file in Dolphin\n→ Upload to Zipline",
            objectName="sidebarFoot")
        foot.setWordWrap(True)
        column.addWidget(foot)
        return sidebar

    def _wrap_in_card(self, builder):
        page, title = builder()

        header = QtWidgets.QLabel(title.upper(), objectName="sectionTitle")
        font = header.font()
        font.setLetterSpacing(QtGui.QFont.SpacingType.AbsoluteSpacing, 1.6)
        header.setFont(font)

        card = QtWidgets.QFrame(objectName="card")
        card_layout = QtWidgets.QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(12)
        card_layout.addWidget(header)
        card_layout.addWidget(page, 1)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        # Pages adapt their width; never crop them horizontally.
        scroll.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QtWidgets.QWidget()
        host_layout = QtWidgets.QVBoxLayout(host)
        host_layout.setContentsMargins(18, 16, 18, 16)
        host_layout.addWidget(card)
        scroll.setWidget(host)
        return scroll

    def _build_button_row(self):
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(18, 12, 18, 14)
        self.reset_btn = QtWidgets.QPushButton("&Reset Defaults")
        self.cancel_btn = QtWidgets.QPushButton("Cancel")
        self.save_btn = QtWidgets.QPushButton("&Save")
        self.save_btn.setObjectName("primaryButton")
        self.save_btn.setDefault(True)
        self.save_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.reset_btn.clicked.connect(self.on_reset_defaults)
        self.cancel_btn.clicked.connect(self.reject)
        self.save_btn.clicked.connect(self.on_save)
        row.addStretch(1)
        row.addWidget(self.reset_btn)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.save_btn)
        return row

    # ------------------------------------------------------------------ #
    #  Pages
    # ------------------------------------------------------------------ #

    def _build_server_page(self):
        tab = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(tab)
        form.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        form.setFormAlignment(QtCore.Qt.AlignmentFlag.AlignTop)

        self.url_edit = QtWidgets.QLineEdit()
        self.url_edit.setPlaceholderText("https://zipline.example.com")
        self.url_hint = QtWidgets.QLabel(objectName="urlHint")
        self.url_edit.textChanged.connect(self._update_url_hint)
        url_block = QtWidgets.QVBoxLayout()
        url_block.setContentsMargins(0, 0, 0, 0)
        url_block.addWidget(self.url_edit)
        url_block.addWidget(self.url_hint)
        form.addRow("Server URL:", url_block)

        self.token_edit = QtWidgets.QLineEdit()
        self.token_edit.setEchoMode(
            QtWidgets.QLineEdit.EchoMode.Password)
        self.token_show = QtWidgets.QToolButton()
        self.token_show.setText("Show")
        self.token_show.setCheckable(True)
        self.token_show.toggled.connect(
            lambda on: self.token_edit.setEchoMode(
                QtWidgets.QLineEdit.EchoMode.Normal if on
                else QtWidgets.QLineEdit.EchoMode.Password))
        token_row = QtWidgets.QHBoxLayout()
        token_row.setContentsMargins(0, 0, 0, 0)
        token_row.addWidget(self.token_edit, 1)
        token_row.addWidget(self.token_show)
        self.env_token_check = QtWidgets.QCheckBox(
            "Read token from $ZIPLINE_TOKEN at runtime")
        self.env_token_check.setToolTip(
            "The token is read from the $ZIPLINE_TOKEN environment variable\n"
            "on every run — nothing is stored on disk.")
        self.env_token_check.toggled.connect(
            lambda on: (self.token_edit.setEnabled(not on),
                        self.token_show.setEnabled(not on)))
        token_block = QtWidgets.QVBoxLayout()
        token_block.setContentsMargins(0, 0, 0, 0)
        token_block.addLayout(token_row)
        token_block.addWidget(self.env_token_check)
        form.addRow("Token:", token_block)

        self.import_btn = QtWidgets.QPushButton(
            QtGui.QIcon.fromTheme("document-import"),
            "&Import from Zipline script…")
        self.test_btn = QtWidgets.QPushButton(
            QtGui.QIcon.fromTheme("network-connect"), "&Test connection")
        self.import_btn.clicked.connect(self.on_import)
        self.test_btn.clicked.connect(self.on_test)
        actions = QtWidgets.QHBoxLayout()
        actions.addWidget(self.import_btn)
        actions.addWidget(self.test_btn)
        actions.addStretch(1)
        form.addRow("", actions)

        self.server_status = QtWidgets.QLabel("")
        self.server_status.setWordWrap(True)
        self.server_status.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.server_status.setMinimumHeight(48)
        form.addRow("", self.server_status)

        return tab, "Server"

    def _build_options_page(self):
        tab = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(tab)
        form.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        form.setFormAlignment(QtCore.Qt.AlignmentFlag.AlignTop)

        self.format_combo = QtWidgets.QComboBox()
        for value, label in zu.FORMAT_CHOICES:
            self.format_combo.addItem(label, value)
        form.addRow("Filename format:", self.format_combo)

        self.original_check = QtWidgets.QCheckBox(
            "Keep original name for downloads")
        form.addRow("", self.original_check)

        self.compress_group = QtWidgets.QGroupBox(
            "Compress images server-side")
        self.compress_group.setCheckable(True)
        compress_form = QtWidgets.QFormLayout(self.compress_group)
        compress_form.setContentsMargins(12, 4, 12, 4)
        compress_form.setVerticalSpacing(2)
        self.compress_spin = QtWidgets.QSpinBox()
        self.compress_spin.setRange(1, 100)
        self.compress_spin.setSuffix("%")
        self.compress_spin.setValue(80)
        self.compress_type = QtWidgets.QComboBox()
        for ctype in zu.COMPRESSION_TYPES:
            self.compress_type.addItem(ctype.upper(), ctype)
        compress_form.addRow("&Quality:", self.compress_spin)
        compress_form.addRow("&Target format:", self.compress_type)
        form.addRow("", self.compress_group)

        self.password_edit = QtWidgets.QLineEdit()
        self.password_edit.setEchoMode(
            QtWidgets.QLineEdit.EchoMode.Password)
        self.password_show = QtWidgets.QToolButton()
        self.password_show.setText("Show")
        self.password_show.setCheckable(True)
        self.password_show.toggled.connect(
            lambda on: self.password_edit.setEchoMode(
                QtWidgets.QLineEdit.EchoMode.Normal if on
                else QtWidgets.QLineEdit.EchoMode.Password))
        pw_row = QtWidgets.QHBoxLayout()
        pw_row.setContentsMargins(0, 0, 0, 0)
        pw_row.addWidget(self.password_edit, 1)
        pw_row.addWidget(self.password_show)
        form.addRow("&Password protect:", pw_row)

        self.views_spin = QtWidgets.QSpinBox()
        self.views_spin.setRange(0, 1_000_000)
        self.views_spin.setSpecialValueText("Unlimited")
        form.addRow("&Max views:", self.views_spin)

        self.expires_edit = QtWidgets.QLineEdit()
        self.expires_edit.setPlaceholderText(
            "1d, 12h, 7d or date=2026-12-31T00:00:00Z — empty = never")
        form.addRow("&Auto-delete after:", self.expires_edit)

        self.extless_check = QtWidgets.QCheckBox(
            "Extensionless URLs (server must allow it)")
        form.addRow("", self.extless_check)

        self.extra_edit = QtWidgets.QPlainTextEdit()
        self.extra_edit.setPlaceholderText(
            "Additional x-zipline-* headers, one key=value per line,\n"
            "e.g. x-zipline-folder=3")
        self.extra_edit.setFixedHeight(72)
        form.addRow("E&xtra headers:", self.extra_edit)

        return tab, "Upload Options"

    def _build_behaviour_page(self):
        tab = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(tab)
        form.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        form.setFormAlignment(QtCore.Qt.AlignmentFlag.AlignTop)

        self.action_combo = QtWidgets.QComboBox()
        for value, label in zu.POST_ACTIONS:
            self.action_combo.addItem(label, value)
        form.addRow("&After upload:", self.action_combo)

        self.clipboard_combo = QtWidgets.QComboBox()
        for value, label in zu.CLIPBOARD_TOOLS:
            self.clipboard_combo.addItem(label, value)
        form.addRow("Clip&board tool:", self.clipboard_combo)

        self.notify_check = QtWidgets.QCheckBox(
            "Show a desktop notification when an upload finishes")
        form.addRow("", self.notify_check)

        self.progress_combo = QtWidgets.QComboBox()
        for value, label in zu.PROGRESS_MODES:
            self.progress_combo.addItem(label, value)
        form.addRow("Pr&ogress display:", self.progress_combo)

        self.timeout_spin = QtWidgets.QSpinBox()
        self.timeout_spin.setRange(5, 600)
        self.timeout_spin.setSuffix(" s")
        form.addRow("Connection &timeout:", self.timeout_spin)

        return tab, "Behaviour"

    def _build_history_page(self):
        tab = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(tab)

        self.history_table = QtWidgets.QTableWidget(0, 3)
        self.history_table.setHorizontalHeaderLabels(["When", "File", "URL"])
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.history_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.history_table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        self.history_table.doubleClicked.connect(self.on_history_copy)
        outer.addWidget(self.history_table)

        row = QtWidgets.QHBoxLayout()
        refresh = QtWidgets.QPushButton(QtGui.QIcon.fromTheme("view-refresh"),
                                        "&Refresh")
        copy_btn = QtWidgets.QPushButton(
            QtGui.QIcon.fromTheme("edit-copy"), "Copy &URL")
        open_btn = QtWidgets.QPushButton(
            QtGui.QIcon.fromTheme("internet-web-browser"), "&Open")
        copy_all = QtWidgets.QPushButton("Copy &All URLs")
        refresh.clicked.connect(self.refresh_history)
        copy_btn.clicked.connect(self.on_history_copy)
        open_btn.clicked.connect(self.on_history_open)
        copy_all.clicked.connect(self.on_history_copy_all)
        for btn in (refresh, copy_btn, open_btn, copy_all):
            row.addWidget(btn)
        row.addStretch(1)
        outer.addLayout(row)

        self.history_status = QtWidgets.QLabel(
            "Double-click a row to copy its URL.", objectName="historyHint")
        outer.addWidget(self.history_status)
        return tab, "History"

    # ------------------------------------------------------------------ #
    #  Config <-> widgets
    # ------------------------------------------------------------------ #

    def populate(self):
        cfg = self.cfg
        self.url_edit.setText(cfg.get("url", ""))
        self._update_url_hint()
        self.token_edit.setText(cfg.get("token", ""))
        self.env_token_check.setChecked(bool(cfg.get("use_env_token")))
        self.token_edit.setEnabled(not cfg.get("use_env_token"))
        self.token_show.setEnabled(not cfg.get("use_env_token"))

        self.format_combo.setCurrentIndex(
            max(0, self.format_combo.findData(cfg.get("format", ""))))
        self.original_check.setChecked(bool(cfg.get("original_name")))
        self.compress_group.setChecked(bool(cfg.get("compress")))
        self.compress_spin.setValue(int(cfg.get("compress_percent", 80)))
        self.compress_type.setCurrentIndex(max(
            0, self.compress_type.findData(cfg.get("compress_type", "jpg"))))
        self.password_edit.setText(cfg.get("password", ""))
        self.views_spin.setValue(int(cfg.get("max_views") or 0))
        self.expires_edit.setText(cfg.get("deletes_at", ""))
        self.extless_check.setChecked(bool(cfg.get("extensionless")))
        extras = cfg.get("extra_headers") or {}
        self.extra_edit.setPlainText(
            "\n".join(f"{k}={v}" for k, v in sorted(extras.items())))

        self.action_combo.setCurrentIndex(max(
            0, self.action_combo.findData(cfg.get("post_action", "copy"))))
        self.clipboard_combo.setCurrentIndex(max(
            0, self.clipboard_combo.findData(cfg.get("clipboard_tool", "auto"))))
        self.notify_check.setChecked(bool(cfg.get("notify_done", True)))
        self.progress_combo.setCurrentIndex(max(
            0, self.progress_combo.findData(cfg.get("progress_ui", "progressbar"))))
        self.timeout_spin.setValue(int(cfg.get("timeout", 30)))

    def collect(self) -> dict:
        cfg = dict(self.cfg)  # keep any keys the GUI doesn't expose
        cfg["url"] = self.url_edit.text().strip()
        cfg["token"] = self.token_edit.text().strip()
        cfg["use_env_token"] = self.env_token_check.isChecked()

        cfg["format"] = self.format_combo.currentData() or ""
        cfg["original_name"] = self.original_check.isChecked()
        cfg["compress"] = self.compress_group.isChecked()
        cfg["compress_percent"] = self.compress_spin.value()
        cfg["compress_type"] = self.compress_type.currentData() or "jpg"
        cfg["password"] = self.password_edit.text()
        cfg["max_views"] = self.views_spin.value() or None
        cfg["deletes_at"] = self.expires_edit.text().strip()
        cfg["extensionless"] = self.extless_check.isChecked()
        extras = {}
        for line in self.extra_edit.toPlainText().splitlines():
            line = line.strip()
            if "=" in line:
                key, value = line.split("=", 1)
                if key.strip():
                    extras[key.strip().lower()] = value.strip()
        cfg["extra_headers"] = extras

        cfg["post_action"] = self.action_combo.currentData() or "copy"
        cfg["clipboard_tool"] = self.clipboard_combo.currentData() or "auto"
        cfg["notify_done"] = self.notify_check.isChecked()
        cfg["progress_ui"] = self.progress_combo.currentData() or "progressbar"
        cfg["timeout"] = self.timeout_spin.value()
        return cfg

    # ------------------------------------------------------------------ #
    #  Actions
    # ------------------------------------------------------------------ #

    def _set_status(self, text, ok=None):
        if ok is True:
            text = GREEN.format(text)
        elif ok is False:
            text = RED.format(text)
        self.server_status.setText(text)

    def _update_url_hint(self):
        text = self.url_edit.text().strip()
        if not text:
            self.url_hint.setText("Uploads POST to  <server>/api/upload")
            return
        try:
            endpoint = zu.normalize_endpoint(text)
            if endpoint == text:
                self.url_hint.setText("✓ uploads will use this endpoint")
            else:
                self.url_hint.setText(f"→ {endpoint}")
        except zu.ZiplineError as exc:
            self.url_hint.setText(str(exc))

    def _goto_page(self, index):
        self.stack.setCurrentIndex(index)
        if 0 <= index < len(self._nav_buttons):
            self._nav_buttons[index].setChecked(True)

    def on_import(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Import Zipline script",
            os.path.expanduser("~/Downloads"),
            "Zipline scripts (*.sh *.bash);;All files (*)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                parsed = zu.parse_zipline_script(fh.read())
        except (OSError, zu.ZiplineError) as exc:
            QtWidgets.QMessageBox.warning(self, "Zipline — Import",
                                          f"Could not import {path}:\n\n{exc}")
            return
        self.cfg = zu.reconcile_import(self.cfg, parsed)
        self.populate()
        self._goto_page(0)
        options = ", ".join(f"{k}={v}" for k, v in sorted(parsed["headers"].items())) \
            or "no extra options"
        self._set_status(
            f"Imported {os.path.basename(path)} — token {zu.mask(parsed['token'])}, "
            f"{options}.<br>Review the pages, then press Save.", ok=True)

    def on_test(self):
        cfg = self.collect()
        if not zu.config_is_valid(zu.effective_config(cfg)):
            self._set_status("Set the server URL and token first.", ok=False)
            return
        self.test_btn.setEnabled(False)
        self._set_status("Testing — uploading a tiny file…")
        self._test_worker = TestWorker(cfg)
        self._test_worker.message.connect(self._test_done)
        self._test_worker.start()

    def _test_done(self, message):
        self.test_btn.setEnabled(True)
        self._set_status(message.replace("\n", "<br>"),
                         ok=message.startswith("Connection test OK"))

    def on_save(self):
        cfg = self.collect()
        try:
            endpoint = zu.normalize_endpoint(cfg.get("url", ""))
        except zu.ZiplineError as exc:
            QtWidgets.QMessageBox.warning(self, "Zipline — Settings", str(exc))
            self._goto_page(0)
            self.url_edit.setFocus()
            self.url_edit.selectAll()
            return
        if not cfg.get("token") and not cfg.get("use_env_token"):
            QtWidgets.QMessageBox.warning(
                self, "Zipline — Settings",
                "A token is required (enter one, or tick the "
                "$ZIPLINE_TOKEN option).")
            self._goto_page(0)
            self.token_edit.setFocus()
            return
        cfg["url"] = endpoint
        zu.save_config(cfg)
        self.cfg = cfg
        self.saved = True
        self.setWindowModified(False)
        self.accept()

    def on_reset_defaults(self):
        answer = QtWidgets.QMessageBox.question(
            self, "Reset defaults",
            "Reset every setting to its default?\n"
            "(Nothing is written to disk until you press Save.)")
        if answer == QtWidgets.QMessageBox.Yes:
            self.cfg = dict(zu.DEFAULTS)
            self.populate()

    # -- history ------------------------------------------------------------

    def refresh_history(self):
        records = zu.read_history(100)
        table = self.history_table
        table.setRowCount(0)
        for record in records:
            row = table.rowCount()
            table.insertRow(row)
            when = str(record.get("time", ""))[:16].replace("T", " ")
            name = ", ".join(record.get("files", [])) or "—"
            urls = record.get("urls", [])
            url = urls[0] if urls else "—"
            if len(urls) > 1:
                url = f"{url} (+{len(urls) - 1} more)"
            table.setItem(row, 0, QtWidgets.QTableWidgetItem(when))
            table.setItem(row, 1, QtWidgets.QTableWidgetItem(name))
            table.setItem(row, 2, QtWidgets.QTableWidgetItem(url))
        if table.rowCount() and table.currentRow() < 0:
            table.selectRow(0)
            table.setCurrentCell(0, 0)
        self.history_status.setText(
            f"{len(records)} upload{'s' if len(records) != 1 else ''} "
            f"(newest first). Double-click a row to copy its URL.")

    def _selected_record(self):
        row = self.history_table.currentRow()
        if row < 0:
            return None
        records = zu.read_history(100)
        return records[row] if row < len(records) else None

    def on_history_copy(self):
        record = self._selected_record()
        if not record or not record.get("urls"):
            return
        ok, _, _ = zu.copy_to_clipboard("\n".join(record["urls"]), "auto")
        self.history_status.setText(
            "URL copied to clipboard." if ok else
            "Copy failed — no clipboard tool available.")

    def on_history_copy_all(self):
        urls = [u for record in zu.read_history(100)
                for u in record.get("urls", [])]
        if not urls:
            self.history_status.setText("No uploads recorded yet.")
            return
        ok, _, _ = zu.copy_to_clipboard("\n".join(urls), "auto")
        self.history_status.setText(
            f"Copied {len(urls)} URLs." if ok else "Copy failed.")

    def on_history_open(self):
        record = self._selected_record()
        if record and record.get("urls"):
            zu.open_urls(record["urls"])

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_history()  # first show and every re-show

    # ------------------------------------------------------------------ #
    #  Unsaved-changes guard
    # ------------------------------------------------------------------ #

    def closeEvent(self, event):
        if self.saved or not self.isWindowModified():
            super().closeEvent(event)
            return
        answer = QtWidgets.QMessageBox.question(
            self, "Unsaved changes",
            "Save settings before closing?",
            QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Discard |
            QtWidgets.QMessageBox.Cancel)
        if answer == QtWidgets.QMessageBox.Save:
            self.on_save()
            # on_save() accepted this dialog only if validation passed;
            # if it popped a warning instead, keep the window open.
            event.ignore() if not self.saved else event.accept()
        elif answer == QtWidgets.QMessageBox.Discard:
            event.accept()
        else:
            event.ignore()


def _new_app(argv=None):
    app = (QtWidgets.QApplication.instance()
           or QtWidgets.QApplication(
               argv if argv is not None else sys.argv[:1]))
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(QtGui.QIcon.fromTheme("cloud-upload"))
    app.setStyleSheet(THEME_QSS)
    return app


def run() -> bool:
    """In-process entry point used by zipline-upload.py (PySide6 present)."""
    app = _new_app()
    dialog = SettingsDialog(zu.load_config())
    dialog.show()
    app.exec()
    return dialog.saved


def _screenshot(path: str) -> int:
    app = _new_app([])
    cfg = dict(zu.DEFAULTS, url="https://zipline.example.com/api/upload",
               token="example-token", format="name", original_name=True)
    dialog = SettingsDialog(cfg)
    dialog.show()  # true default size from _size_to_screen()
    stem, ext = os.path.splitext(path)
    ext = ext or ".png"
    saved = 0
    for index in range(dialog.stack.count()):
        dialog._goto_page(index)
        app.processEvents()
        out = f"{stem}-{index}{ext}"
        if dialog.grab().save(out):
            print("screenshot saved:", out)
            saved += 1
    return 0 if saved else 1


def main(argv) -> int:
    if "--screenshot" in argv:
        try:
            path = argv[argv.index("--screenshot") + 1]
        except IndexError:
            print("usage: zipline_gui.py --screenshot PATH", file=sys.stderr)
            return 2
        return _screenshot(path)
    app = _new_app(argv)
    dialog = SettingsDialog(zu.load_config())
    dialog.show()
    if "--demo" in argv:
        QtCore.QTimer.singleShot(4000, dialog.close)
    app.exec()
    return 0 if dialog.saved else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
