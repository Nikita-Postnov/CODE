"""Небольшие диалоги приложения."""

from PySide6.QtWidgets import (
    QApplication,
    QPlainTextEdit,
    QVBoxLayout,
    QFormLayout,
    QPushButton,
    QLineEdit,
    QSpinBox,
    QDialog,
    QDialogButtonBox,
    QComboBox,
    QCheckBox,
)

import random


class NumberGeneratorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Генератор чисел")
        self.setModal(True)
        self.resize(420, 260)
        form = QFormLayout()
        self.start_spin = QSpinBox()
        self.start_spin.setRange(-(10**9), 10**9)
        self.start_spin.setValue(1)
        self.end_spin = QSpinBox()
        self.end_spin.setRange(-(10**9), 10**9)
        self.end_spin.setValue(100)
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 10**6)
        self.count_spin.setValue(10)
        self.base_combo = QComboBox()
        self.base_combo.addItems(["10", "16", "2"])
        self.unique_cb = QCheckBox("Только уникальные")
        self.sort_cb = QCheckBox("Сортировать")
        self.desc_cb = QCheckBox("По убыванию")
        self.desc_cb.setEnabled(False)
        self.sort_cb.toggled.connect(lambda v: self.desc_cb.setEnabled(v))
        self.leading_zeros_cb = QCheckBox("Выровнять нулями (для 10/16/2)")
        self.sep_edit = QLineEdit(", ")
        self.sep_edit.setPlaceholderText("разделитель (по умолчанию: запятая+пробел)")
        form.addRow("Начало:", self.start_spin)
        form.addRow("Конец:", self.end_spin)
        form.addRow("Сколько:", self.count_spin)
        form.addRow("Система счисления:", self.base_combo)
        form.addRow(self.unique_cb)
        form.addRow(self.sort_cb)
        form.addRow(self.desc_cb)
        form.addRow(self.leading_zeros_cb)
        form.addRow("Разделитель:", self.sep_edit)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("Предпросмотр…")
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.btn_generate = QPushButton("Сгенерировать")
        btns.addButton(self.btn_generate, QDialogButtonBox.ActionRole)
        self.btn_copy = QPushButton("Копировать")
        self.btn_copy.setEnabled(False)
        btns.addButton(self.btn_copy, QDialogButtonBox.ActionRole)
        self.btn_generate.clicked.connect(self._on_generate)
        self.btn_copy.clicked.connect(self._on_copy)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addWidget(self.preview, 1)
        root.addWidget(btns)
        self._on_generate()

    def _format_num(self, n: int, base: int, width: int) -> str:
        if base == 10:
            s = str(n)
        elif base == 16:
            s = format(
                n if n >= 0 else (1 << 64) + n, "x"
            )
        else:
            s = format(n if n >= 0 else (1 << 64) + n, "b")
        if self.leading_zeros_cb.isChecked() and width > 0:
            s = s.zfill(width)
        return s

    def _on_generate(self):
        a = self.start_spin.value()
        b = self.end_spin.value()
        if a > b:
            a, b = b, a
        k = self.count_spin.value()
        base = int(self.base_combo.currentText())
        sep = self.sep_edit.text() if self.sep_edit.text() != "" else ", "
        pool_size = b - a + 1
        width = 0
        if self.leading_zeros_cb.isChecked():
            if base == 10:
                width = len(str(max(abs(a), abs(b))))
            elif base == 16:
                width = len(format(max(abs(a), abs(b)), "x"))
            else:
                width = len(format(max(abs(a), abs(b)), "b"))

        rng = range(a, b + 1)
        numbers = []
        if self.unique_cb.isChecked():
            if k > pool_size:
                k = pool_size
            numbers = random.sample(list(rng), k)
        else:
            numbers = [random.randint(a, b) for _ in range(k)]

        if self.sort_cb.isChecked():
            numbers.sort(reverse=self.desc_cb.isChecked())

        formatted = [self._format_num(n, base, width) for n in numbers]
        text = sep.join(formatted)
        self.preview.setPlainText(text)
        self.btn_copy.setEnabled(bool(text))

    def _on_copy(self):
        text = self.preview.toPlainText()
        if text:
            QApplication.clipboard().setText(text)

    def result_text(self) -> str:
        return self.preview.toPlainText()
