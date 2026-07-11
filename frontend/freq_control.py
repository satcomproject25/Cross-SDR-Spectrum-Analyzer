"""
freq_control.py
----------------
Reusable frequency-value widget: a QDoubleSpinBox paired with a unit
dropdown (Hz / kHz / MHz / GHz). Internally always stores/reports the
value in Hz so backend calls never need to worry about units.

Owner: Developer B (Frontend/GUI)
"""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QDoubleSpinBox, QComboBox

UNIT_MULTIPLIERS = {
    "Hz": 1.0,
    "kHz": 1e3,
    "MHz": 1e6,
    "GHz": 1e9,
}


class FrequencyControl(QWidget):
    # Always emits the value in Hz, regardless of displayed unit
    value_changed_hz = pyqtSignal(float)

    def __init__(self, initial_hz: float = 2440e6, minimum_hz: float = 1e6,
                 maximum_hz: float = 6e9, default_unit: str = "MHz", parent=None):
        super().__init__(parent)

        self._min_hz = minimum_hz
        self._max_hz = maximum_hz
        self._current_hz = initial_hz

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.spin = QDoubleSpinBox()
        self.spin.setDecimals(6)
        self.spin.setSingleStep(0.001)

        self.unit_combo = QComboBox()
        self.unit_combo.addItems(list(UNIT_MULTIPLIERS.keys()))
        self.unit_combo.setCurrentText(default_unit)

        layout.addWidget(self.spin)
        layout.addWidget(self.unit_combo)

        self._updating = False  # re-entrancy guard while converting units

        self._apply_range_for_current_unit()
        self._set_spin_value_from_hz(initial_hz)

        self.spin.valueChanged.connect(self._on_spin_changed)
        self.unit_combo.currentTextChanged.connect(self._on_unit_changed)

    # ------------------------------------------------------------------
    def _current_unit(self) -> str:
        return self.unit_combo.currentText()

    def _multiplier(self) -> float:
        return UNIT_MULTIPLIERS[self._current_unit()]

    def _apply_range_for_current_unit(self):
        mult = self._multiplier()
        self.spin.blockSignals(True)
        self.spin.setRange(self._min_hz / mult, self._max_hz / mult)
        self.spin.blockSignals(False)

    def _set_spin_value_from_hz(self, hz_value: float):
        mult = self._multiplier()
        self.spin.blockSignals(True)
        self.spin.setValue(hz_value / mult)
        self.spin.blockSignals(False)

    # ------------------------------------------------------------------
    def _on_spin_changed(self, value):
        if self._updating:
            return
        self._current_hz = value * self._multiplier()
        self.value_changed_hz.emit(self._current_hz)

    def _on_unit_changed(self, new_unit):
        # Re-range and re-display the SAME underlying Hz value in new unit,
        # without re-triggering _on_spin_changed with a converted (wrong) value.
        self._updating = True
        self._apply_range_for_current_unit()
        self._set_spin_value_from_hz(self._current_hz)
        self._updating = False

    # ------------------------------------------------------------------
    def value_hz(self) -> float:
        return self._current_hz

    def set_value_hz(self, hz_value: float):
        self._current_hz = hz_value
        self._set_spin_value_from_hz(hz_value)

    def set_suffix_visible_unit(self, unit: str):
        """Programmatically switch the displayed unit (e.g. from a preset)."""
        if unit in UNIT_MULTIPLIERS:
            self.unit_combo.setCurrentText(unit)