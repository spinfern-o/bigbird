"""Cloud project UI: the projects list, and running cloud work off the UI thread."""
from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMessageBox, QProgressDialog, QPushButton,
                               QVBoxLayout)

from . import cloud_projects


class _Signals(QObject):
    done = Signal(object, str)


class _Job(QRunnable):
    def __init__(self, fn, signals):
        super().__init__()
        self.fn, self.signals = fn, signals

    def run(self):
        try:
            result, error = self.fn(), ""
        except cloud_projects.CloudError as e:
            result, error = None, str(e)
        except Exception as e:
            result, error = None, f"{type(e).__name__}: {e}"
        try:
            self.signals.done.emit(result, error)
        except RuntimeError:
            pass


def run_cloud(parent, title, busy_text, fn, on_done):
    """Run a cloud call in the background with a progress dialog; on_done(result) on success."""
    dlg = QProgressDialog(busy_text, None, 0, 0, parent)
    dlg.setWindowTitle(title)
    dlg.setWindowModality(Qt.WindowModal)
    dlg.setMinimumDuration(300)
    dlg.setCancelButton(None)
    sig = _Signals(parent)

    def done(result, error):
        dlg.close()
        if error:
            QMessageBox.warning(parent, title, error)
        else:
            on_done(result)

    sig.done.connect(done)
    QThreadPool.globalInstance().start(_Job(fn, sig))


class _ThumbLoader(QObject):
    """Downloads project previews one by one on a worker thread."""
    loaded = Signal(int, object)

    def __init__(self, parent, api, wanted):
        super().__init__(parent)
        self.api, self.wanted = api, wanted

    def start(self):
        QThreadPool.globalInstance().start(_Job(self._work, _Signals(self)))

    def _work(self):
        for index, path in self.wanted:
            try:
                data = self.api.download_thumb(path)
            except cloud_projects.CloudError:
                continue
            if data:
                self.loaded.emit(index, data)


class CloudProjectsDialog(QDialog):
    """Lists the signed-in user's cloud projects, with previews."""

    def __init__(self, parent, api, rows):
        super().__init__(parent)
        self.setWindowTitle("My Cloud Projects")
        self.resize(560, 480)
        self.api = api
        self.chosen = None
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Your projects are saved to your phrame.tech account, so you can "
                             "open them on any computer you sign in on."))
        self.list = QListWidget()
        self.list.setIconSize(QSize(96, 72))
        self.list.itemDoubleClicked.connect(lambda _: self._open())
        lay.addWidget(self.list, 1)

        row = QHBoxLayout()
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setToolTip("Remove this project from your account")
        self.delete_btn.clicked.connect(self._delete)
        row.addWidget(self.delete_btn)
        row.addStretch(1)
        lay.addLayout(row)

        bb = QDialogButtonBox(QDialogButtonBox.Open | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._open)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.set_rows(rows)

    def set_rows(self, rows):
        self.rows = rows
        self.list.clear()
        for r in rows:
            when = (r.get("updated_at") or "")[:16].replace("T", " ")
            size = f"{(r.get('size_bytes') or 0) / 1048576:.1f} MB"
            item = QListWidgetItem(f"{r['name']}\n{r.get('width', '?')} × {r.get('height', '?')} "
                                   f"px · {size} · {when}")
            item.setData(Qt.UserRole, r)
            self.list.addItem(item)
        if rows:
            self.list.setCurrentRow(0)
        else:
            self.list.addItem(QListWidgetItem("No cloud projects yet. Use File → Save to Cloud."))
        self.delete_btn.setEnabled(bool(rows))

    def load_thumbs(self):
        """Fetch preview images in the background so the window stays responsive."""
        wanted = [(i, self.list.item(i).data(Qt.UserRole)) for i in range(self.list.count())]
        wanted = [(i, r["thumb_path"]) for i, r in wanted if r and r.get("thumb_path")]
        if not wanted:
            return
        self._thumbs = _ThumbLoader(self, self.api, wanted)
        self._thumbs.loaded.connect(self._set_thumb)
        self._thumbs.start()

    def _set_thumb(self, index, data):
        item = self.list.item(index)
        pix = QPixmap()
        if item and data and pix.loadFromData(data):
            item.setIcon(QIcon(pix))

    def _selected(self):
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _open(self):
        row = self._selected()
        if row:
            self.chosen = row
            self.accept()

    def _delete(self):
        row = self._selected()
        if not row:
            return
        if QMessageBox.question(self, "Delete project",
                                f"Delete '{row['name']}' from your account?\n\nThis can't be "
                                "undone.") != QMessageBox.Yes:
            return
        run_cloud(self, "Delete project", "Deleting…", lambda: self.api.delete_project(row),
                  lambda _: self.set_rows([r for r in self.rows if r["id"] != row["id"]]))
