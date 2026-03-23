from __future__ import annotations

import argparse
import bisect
import csv
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPalette, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)


APP_TITLE = "XAUUSD 13-State Puzzle Chart"
DEFAULT_CSV = Path("out.csv")
DEFAULT_RAW = Path("last_400k_prices.csv")
RAW_HEADERS = {"price", "timestamp"}
LABELED_HEADERS = {"current_state_id", "current_state_name", "tick_speed", "regime"}
REGIME_TOKENS = ("EARLY", "CLOCK", "LATE")

STATE_MAP = {
    (0, 0, 0): 0,
    (0, -1, 1): 1,
    (1, -1, 1): 2,
    (1, 1, 1): 3,
    (-1, 0, -1): 4,
    (1, 1, 0): 5,
    (-1, 1, -1): 6,
    (-1, -1, 1): 7,
    (1, 0, 1): 8,
    (0, 1, -1): 9,
    (-1, -1, 0): 10,
    (1, 1, -1): 11,
    (-1, -1, -1): 12,
}
ID_TO_TUPLE = {value: key for key, value in STATE_MAP.items()}
STATE_NAMES = {
    0: "FLATLINE",
    1: "BULL BREAK",
    2: "BULL TREND",
    3: "BULL PULL",
    4: "BEAR PAUSE",
    5: "BULL TRAP",
    6: "BEAR TREND",
    7: "BULL REV",
    8: "BULL PAUSE",
    9: "BEAR BREAK",
    10: "EXACT REC",
    11: "BEAR REV",
    12: "BEAR PULL",
}
STATE_COLORS = {
    0: "#7a97b3",
    1: "#4cc476",
    2: "#28b46a",
    3: "#98cb54",
    4: "#ff9d5a",
    5: "#d3b155",
    6: "#f06767",
    7: "#43c7ad",
    8: "#39b9d8",
    9: "#ff7a7f",
    10: "#7cb6ff",
    11: "#e18cff",
    12: "#d85c85",
}
REGIME_COLORS = {
    "EARLY": "#f3b33d",
    "CLOCK": "#6ec4ff",
    "LATE": "#ff6f91",
}
BOARD_STATE_COLORS = {
    0: "#425565",
    1: "#2f7457",
    2: "#21684e",
    3: "#687533",
    4: "#845b41",
    5: "#765f30",
    6: "#854849",
    7: "#2b7365",
    8: "#2a687c",
    9: "#874852",
    10: "#4c6286",
    11: "#70517f",
    12: "#775164",
}
PUZZLE_LAYOUT = {
    7: (0, 0),
    2: (1, 0),
    8: (2, 0),
    1: (3, 0),
    3: (0, 1),
    10: (1, 1),
    0: (2, 1),
    9: (3, 1),
    11: (4, 1),
    5: (0, 2),
    6: (1, 2),
    4: (2, 2),
    12: (3, 2),
}
BASE_TILE_WIDTH = 154.0
BASE_TILE_HEIGHT = 106.0
BASE_STEP_X = 142.0
BASE_STEP_Y = 94.0
STATE_SCORE = {
    state_id: (ID_TO_TUPLE[state_id][0] - ID_TO_TUPLE[state_id][1] + ID_TO_TUPLE[state_id][2]) / 3.0
    for state_id in range(13)
}


def cmp_price(left: float, right: float) -> int:
    return 1 if left > right else (-1 if left < right else 0)


def classify_gap(delta_seconds: float | None) -> str | None:
    if delta_seconds is None or delta_seconds < 0.20 or delta_seconds > 10.0:
        return None
    if delta_seconds < 0.495:
        return "EARLY"
    if delta_seconds <= 0.505:
        return "CLOCK"
    return "LATE"


def tokenize_regime(value: str) -> list[str]:
    tokens = []
    for part in str(value or "").split():
        token = part.strip().upper()
        if token in REGIME_TOKENS:
            tokens.append(token)
    return tokens


def parse_timestamp(value: str) -> float:
    text = str(value).strip()
    if not text:
        raise ValueError("missing timestamp")
    try:
        return float(text)
    except ValueError:
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        return datetime.fromisoformat(text).timestamp()


def compact_count(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}m"
    if value >= 1_000:
        return f"{value / 1_000:.1f}k"
    return str(value)


def format_clock_label(timestamp: float, synthetic: bool) -> str:
    if synthetic or timestamp < 1_000_000_000:
        return f"t+{timestamp:,.1f}s"
    return datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")


def csv_schema(path: Path | None) -> str:
    if path is None or not path.exists():
        return "missing"
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, [])
    columns = {name.strip() for name in header if name.strip()}
    if RAW_HEADERS.issubset(columns) and LABELED_HEADERS.issubset(columns):
        return "hybrid"
    if RAW_HEADERS.issubset(columns):
        return "raw"
    if LABELED_HEADERS.issubset(columns):
        return "labeled"
    return "unknown"


def qcolor(value: str | QColor) -> QColor:
    return QColor(value) if isinstance(value, str) else QColor(value)


def with_alpha(color: str | QColor, alpha: int) -> QColor:
    result = qcolor(color)
    result.setAlpha(max(0, min(alpha, 255)))
    return result


def apply_dark_palette(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#05080c"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#edf4f8"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#071018"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#0b141d"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#e5eef5"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#0c1721"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#ecf3f8"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#0f1720"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#f1f6fa"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#19425a"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#f5fafc"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#7990a3"))
    app.setPalette(palette)


def build_tabs() -> dict[int, dict[str, int]]:
    reverse = {position: state_id for state_id, position in PUZZLE_LAYOUT.items()}
    tabs: dict[int, dict[str, int]] = {
        state_id: {"top": 0, "right": 0, "bottom": 0, "left": 0}
        for state_id in PUZZLE_LAYOUT
    }
    for state_id, (column, row) in PUZZLE_LAYOUT.items():
        right_neighbor = reverse.get((column + 1, row))
        if right_neighbor is not None:
            direction = 1 if (column + row) % 2 == 0 else -1
            tabs[state_id]["right"] = direction
            tabs[right_neighbor]["left"] = -direction
        bottom_neighbor = reverse.get((column, row + 1))
        if bottom_neighbor is not None:
            direction = 1 if (column + row) % 2 == 1 else -1
            tabs[state_id]["bottom"] = direction
            tabs[bottom_neighbor]["top"] = -direction
    return tabs


PUZZLE_TABS = build_tabs()


@dataclass
class StateStats:
    count: int
    avg_speed: float
    dominant_regime: str
    top_next: list[tuple[int, int, float]]


@dataclass
class ChartDataset:
    name: str
    source_note: str
    price_note: str
    prices: list[float]
    timestamps: list[float]
    raw_indices: list[int]
    state_ids: list[int]
    tick_speeds: list[float]
    regime_tokens: list[str]
    regime_triplets: list[str]
    state_occurrences: dict[int, list[int]]
    state_stats: dict[int, StateStats]
    transitions: dict[int, dict[int, int]]
    synthetic_price: bool
    reference_name: str | None
    min_price: float
    max_price: float
    min_speed: float
    max_speed: float

    def __len__(self) -> int:
        return len(self.state_ids)

    def next_state_id(self, index: int) -> int | None:
        if 0 <= index < len(self.state_ids) - 1:
            return self.state_ids[index + 1]
        return None

    def price_delta(self, index: int) -> float:
        if 0 <= index < len(self.prices) - 1:
            return self.prices[index + 1] - self.prices[index]
        if 0 < index < len(self.prices):
            return self.prices[index] - self.prices[index - 1]
        return 0.0


def finalize_dataset(
    *,
    name: str,
    source_note: str,
    price_note: str,
    prices: list[float],
    timestamps: list[float],
    raw_indices: list[int],
    state_ids: list[int],
    tick_speeds: list[float],
    regime_tokens: list[str],
    regime_triplets: list[str],
    synthetic_price: bool,
    reference_name: str | None = None,
) -> ChartDataset:
    if not state_ids:
        raise ValueError("No usable state rows were found for the chart app.")

    state_occurrences = {state_id: [] for state_id in range(13)}
    speed_totals = {state_id: 0.0 for state_id in range(13)}
    regime_counts = {state_id: defaultdict(int) for state_id in range(13)}
    transitions: dict[int, dict[int, int]] = {state_id: defaultdict(int) for state_id in range(13)}

    for index, state_id in enumerate(state_ids):
        state_occurrences[state_id].append(index)
        speed_totals[state_id] += tick_speeds[index]
        regime_counts[state_id][regime_tokens[index]] += 1
        if index + 1 < len(state_ids):
            transitions[state_id][state_ids[index + 1]] += 1

    state_stats: dict[int, StateStats] = {}
    for state_id in range(13):
        count = len(state_occurrences[state_id])
        avg_speed = speed_totals[state_id] / count if count else 0.0
        dominant_regime = "--"
        if regime_counts[state_id]:
            dominant_regime = max(regime_counts[state_id].items(), key=lambda item: item[1])[0]
        outgoing = transitions[state_id]
        total_outgoing = sum(outgoing.values())
        top_next = []
        if total_outgoing:
            ordered = sorted(outgoing.items(), key=lambda item: (-item[1], item[0]))
            top_next = [
                (next_state, hit_count, hit_count / total_outgoing)
                for next_state, hit_count in ordered[:3]
            ]
        state_stats[state_id] = StateStats(
            count=count,
            avg_speed=avg_speed,
            dominant_regime=dominant_regime,
            top_next=top_next,
        )

    return ChartDataset(
        name=name,
        source_note=source_note,
        price_note=price_note,
        prices=prices,
        timestamps=timestamps,
        raw_indices=raw_indices,
        state_ids=state_ids,
        tick_speeds=tick_speeds,
        regime_tokens=regime_tokens,
        regime_triplets=regime_triplets,
        state_occurrences=state_occurrences,
        state_stats=state_stats,
        transitions={state_id: dict(neighbors) for state_id, neighbors in transitions.items()},
        synthetic_price=synthetic_price,
        reference_name=reference_name,
        min_price=min(prices),
        max_price=max(prices),
        min_speed=min(tick_speeds),
        max_speed=max(tick_speeds),
    )


def build_dataset_from_raw(path: Path, reference_name: str | None = None) -> ChartDataset:
    raw_prices: list[float] = []
    raw_timestamps: list[float] = []

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            try:
                raw_prices.append(float(row["price"]))
                raw_timestamps.append(parse_timestamp(row["timestamp"]))
            except (KeyError, TypeError, ValueError):
                continue

    if len(raw_prices) < 6:
        raise ValueError(f"{path.name} does not contain enough valid raw ticks.")

    prices: list[float] = []
    timestamps: list[float] = []
    raw_indices: list[int] = []
    state_ids: list[int] = []
    tick_speeds: list[float] = []
    regime_tokens: list[str] = []

    for index in range(2, len(raw_prices) - 1):
        key = (
            cmp_price(raw_prices[index - 1], raw_prices[index - 2]),
            cmp_price(raw_prices[index - 1], raw_prices[index]),
            cmp_price(raw_prices[index], raw_prices[index - 2]),
        )
        state_id = STATE_MAP.get(key)
        if state_id is None:
            continue
        tick_speed = raw_timestamps[index + 1] - raw_timestamps[index]
        regime = classify_gap(tick_speed)
        if regime is None:
            continue

        prices.append(raw_prices[index])
        timestamps.append(raw_timestamps[index])
        raw_indices.append(index)
        state_ids.append(state_id)
        tick_speeds.append(tick_speed)
        regime_tokens.append(regime)

    regime_triplets = [
        " ".join(regime_tokens[max(0, index - 2) : index + 1])
        for index in range(len(regime_tokens))
    ]
    source_note = f"Real prices derived from {path.name}"
    if reference_name:
        source_note += f" with {reference_name} kept as the labeled reference"

    return finalize_dataset(
        name=path.name,
        source_note=source_note,
        price_note="Price chart is synced to the raw tick stream.",
        prices=prices,
        timestamps=timestamps,
        raw_indices=raw_indices,
        state_ids=state_ids,
        tick_speeds=tick_speeds,
        regime_tokens=regime_tokens,
        regime_triplets=regime_triplets,
        synthetic_price=False,
        reference_name=reference_name,
    )


def build_dataset_from_labeled(path: Path) -> ChartDataset:
    prices: list[float] = []
    timestamps: list[float] = []
    raw_indices: list[int] = []
    state_ids: list[int] = []
    tick_speeds: list[float] = []
    regime_tokens: list[str] = []
    regime_triplets: list[str] = []

    schema = csv_schema(path)
    has_real_price = schema == "hybrid"
    synthetic_anchor_price = 100.0
    synthetic_time = 0.0

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row_index, row in enumerate(reader):
            try:
                state_id = int(row["current_state_id"])
                tick_speed = float(row["tick_speed"])
            except (KeyError, TypeError, ValueError):
                continue

            tokens = tokenize_regime(row.get("regime", ""))
            primary_regime = tokens[-1] if tokens else classify_gap(tick_speed) or "CLOCK"
            regime_triplet = " ".join(tokens) if tokens else primary_regime

            if has_real_price:
                try:
                    price = float(row["price"])
                    timestamp = parse_timestamp(row["timestamp"])
                except (KeyError, TypeError, ValueError):
                    continue

            if not has_real_price:
                synthetic_anchor_price += (STATE_SCORE[state_id] * 0.055)
                synthetic_anchor_price += {"EARLY": -0.018, "CLOCK": 0.0, "LATE": 0.018}.get(primary_regime, 0.0)
                synthetic_anchor_price += math.sin(row_index / 13.0) * 0.004
                synthetic_time += max(tick_speed, 0.001)
                price = synthetic_anchor_price
                timestamp = synthetic_time
                raw_index = row_index
            else:
                try:
                    raw_index = int(float(row.get("raw_tick_index", row_index)))
                except (TypeError, ValueError):
                    raw_index = row_index

            prices.append(price)
            timestamps.append(timestamp)
            raw_indices.append(raw_index)
            state_ids.append(state_id)
            tick_speeds.append(tick_speed)
            regime_tokens.append(primary_regime)
            regime_triplets.append(regime_triplet)

    price_note = "Price chart is synced to labeled rows with real price columns."
    if not has_real_price:
        price_note = "Price chart is reconstructed from state pressure because the labeled CSV has no price column."

    return finalize_dataset(
        name=path.name,
        source_note=f"State examples loaded from {path.name}",
        price_note=price_note,
        prices=prices,
        timestamps=timestamps,
        raw_indices=raw_indices,
        state_ids=state_ids,
        tick_speeds=tick_speeds,
        regime_tokens=regime_tokens,
        regime_triplets=regime_triplets,
        synthetic_price=not has_real_price,
        reference_name=None,
    )


def load_dataset(csv_path: Path, raw_path: Path | None) -> ChartDataset:
    primary_schema = csv_schema(csv_path)
    raw_schema = csv_schema(raw_path)

    if primary_schema == "raw":
        return build_dataset_from_raw(csv_path)
    if primary_schema == "hybrid":
        return build_dataset_from_labeled(csv_path)
    if raw_schema == "raw":
        reference_name = csv_path.name if primary_schema == "labeled" else None
        return build_dataset_from_raw(raw_path, reference_name=reference_name)
    if primary_schema == "labeled":
        return build_dataset_from_labeled(csv_path)

    candidates = [str(path.name) for path in (csv_path, raw_path) if path is not None]
    raise FileNotFoundError(
        "Could not find a usable CSV. Expected raw tick columns "
        f"{sorted(RAW_HEADERS)} or labeled columns {sorted(LABELED_HEADERS)} in: {', '.join(candidates)}"
    )


def nearest_index(values: list[int], target: int) -> int:
    if not values:
        raise ValueError("No values to search.")
    position = bisect.bisect_left(values, target)
    if position <= 0:
        return values[0]
    if position >= len(values):
        return values[-1]
    before = values[position - 1]
    after = values[position]
    return before if abs(before - target) <= abs(after - target) else after


def puzzle_piece_path(rect: QRectF, tabs: dict[str, int], depth: float) -> QPainterPath:
    stem = min(rect.width(), rect.height()) * 0.18
    left = rect.left()
    right = rect.right()
    top = rect.top()
    bottom = rect.bottom()
    middle_x = rect.center().x()
    middle_y = rect.center().y()

    path = QPainterPath(QPointF(left, top))
    path.lineTo(middle_x - stem, top)
    if tabs["top"]:
        offset = -depth * tabs["top"]
        path.cubicTo(middle_x - stem * 0.55, top, middle_x - stem * 0.55, top + offset, middle_x, top + offset)
        path.cubicTo(middle_x + stem * 0.55, top + offset, middle_x + stem * 0.55, top, middle_x + stem, top)
    path.lineTo(right, top)
    path.lineTo(right, middle_y - stem)
    if tabs["right"]:
        offset = depth * tabs["right"]
        path.cubicTo(right, middle_y - stem * 0.55, right + offset, middle_y - stem * 0.55, right + offset, middle_y)
        path.cubicTo(right + offset, middle_y + stem * 0.55, right, middle_y + stem * 0.55, right, middle_y + stem)
    path.lineTo(right, bottom)
    path.lineTo(middle_x + stem, bottom)
    if tabs["bottom"]:
        offset = depth * tabs["bottom"]
        path.cubicTo(middle_x + stem * 0.55, bottom, middle_x + stem * 0.55, bottom + offset, middle_x, bottom + offset)
        path.cubicTo(middle_x - stem * 0.55, bottom + offset, middle_x - stem * 0.55, bottom, middle_x - stem, bottom)
    path.lineTo(left, bottom)
    path.lineTo(left, middle_y + stem)
    if tabs["left"]:
        offset = -depth * tabs["left"]
        path.cubicTo(left, middle_y + stem * 0.55, left + offset, middle_y + stem * 0.55, left + offset, middle_y)
        path.cubicTo(left + offset, middle_y - stem * 0.55, left, middle_y - stem * 0.55, left, middle_y - stem)
    path.lineTo(left, top)
    path.closeSubpath()
    return path


class PriceChartWidget(QWidget):
    indexHovered = pyqtSignal(int)
    zoomRequested = pyqtSignal(int)

    def __init__(self) -> None:
        super().__init__()
        self.dataset: ChartDataset | None = None
        self.start_index = 0
        self.end_index = 0
        self.current_index = 0
        self._plot_rect = QRectF()

    def minimumSizeHint(self) -> QSize:
        return QSize(720, 430)

    def set_view(self, dataset: ChartDataset, start_index: int, end_index: int, current_index: int) -> None:
        self.dataset = dataset
        self.start_index = start_index
        self.end_index = end_index
        self.current_index = current_index
        self.update()

    def _content_rect(self) -> QRectF:
        return QRectF(18.0, 12.0, max(10.0, self.width() - 96.0), max(10.0, self.height() - 28.0))

    def _index_at_position(self, position: QPointF) -> int | None:
        if not self.dataset or self.end_index <= self.start_index or not self._plot_rect.contains(position):
            return None
        count = self.end_index - self.start_index
        if count == 1:
            return self.start_index
        ratio = (position.x() - self._plot_rect.left()) / max(1.0, self._plot_rect.width())
        local = round(ratio * (count - 1))
        local = max(0, min(count - 1, local))
        return self.start_index + local

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        super().mousePressEvent(event)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        event.ignore()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#0c151d"))

        if not self.dataset or self.end_index <= self.start_index:
            painter.setPen(QColor("#9ab0c1"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No price data to draw.")
            return

        plot = self._content_rect()
        self._plot_rect = plot
        visible_prices = self.dataset.prices[self.start_index : self.end_index]
        visible_states = self.dataset.state_ids[self.start_index : self.end_index]
        count = len(visible_prices)
        if count == 0:
            return

        price_low = min(visible_prices)
        price_high = max(visible_prices)
        span = price_high - price_low
        pad = span * 0.14 if span else max(abs(price_high) * 0.0004, 0.01)
        min_y_value = price_low - pad
        max_y_value = price_high + pad
        y_span = max(max_y_value - min_y_value, 1e-9)

        strip_width = plot.width() / max(count, 1)
        for local_index, state_id in enumerate(visible_states):
            band = QRectF(plot.left() + local_index * strip_width, plot.top(), strip_width + 1.0, plot.height())
            painter.fillRect(band, with_alpha(STATE_COLORS[state_id], 24))

        painter.setPen(QPen(QColor("#1f3342"), 1.0))
        for grid_line in range(5):
            ratio = grid_line / 4.0
            y = plot.top() + ratio * plot.height()
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            price_value = max_y_value - ratio * y_span
            painter.setPen(QColor("#7f96a8"))
            painter.drawText(
                QRectF(plot.right() + 10.0, y - 10.0, 60.0, 18.0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"{price_value:.3f}",
            )
            painter.setPen(QPen(QColor("#1f3342"), 1.0))

        def point_for(local_index: int, price: float) -> QPointF:
            if count == 1:
                x = plot.center().x()
            else:
                x = plot.left() + (local_index / (count - 1)) * plot.width()
            y = plot.bottom() - ((price - min_y_value) / y_span) * plot.height()
            return QPointF(x, y)

        price_path = QPainterPath(point_for(0, visible_prices[0]))
        for local_index, price in enumerate(visible_prices[1:], start=1):
            price_path.lineTo(point_for(local_index, price))

        shadow_pen = QPen(QColor("#081018"), 5.0)
        shadow_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        shadow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(shadow_pen)
        painter.drawPath(price_path)

        glow_pen = QPen(QColor("#7fe2d5") if not self.dataset.synthetic_price else QColor("#f2c36c"), 2.4)
        glow_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        glow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(glow_pen)
        painter.drawPath(price_path)

        step = max(1, count // 48)
        for local_index in range(0, count, step):
            state_id = visible_states[local_index]
            point = point_for(local_index, visible_prices[local_index])
            painter.setBrush(qcolor(STATE_COLORS[state_id]))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(point, 2.4, 2.4)

        if self.start_index <= self.current_index < self.end_index:
            local_index = self.current_index - self.start_index
            current_point = point_for(local_index, visible_prices[local_index])
            painter.setPen(QPen(QColor("#f6d89a"), 1.5, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(current_point.x(), plot.top()), QPointF(current_point.x(), plot.bottom()))
            painter.setBrush(QColor("#f6d89a"))
            painter.setPen(QPen(QColor("#081018"), 1.4))
            painter.drawEllipse(current_point, 5.5, 5.5)

            label = f"{visible_prices[local_index]:.3f}  S{visible_states[local_index]} {STATE_NAMES[visible_states[local_index]]}"
            metrics = self.fontMetrics()
            box_width = metrics.horizontalAdvance(label) + 18
            box_height = 24
            box_x = min(plot.right() - box_width, current_point.x() + 12.0)
            if box_x < plot.left():
                box_x = plot.left()
            box_y = max(plot.top() + 8.0, current_point.y() - 34.0)
            box = QRectF(box_x, box_y, box_width, box_height)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(with_alpha("#071015", 224))
            painter.drawRoundedRect(box, 8.0, 8.0)
            painter.setPen(QColor("#eef4f8"))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, label)


class TickSpeedWidget(QWidget):
    indexHovered = pyqtSignal(int)
    zoomRequested = pyqtSignal(int)

    def __init__(self) -> None:
        super().__init__()
        self.dataset: ChartDataset | None = None
        self.start_index = 0
        self.end_index = 0
        self.current_index = 0
        self._plot_rect = QRectF()

    def minimumSizeHint(self) -> QSize:
        return QSize(640, 145)

    def set_view(self, dataset: ChartDataset, start_index: int, end_index: int, current_index: int) -> None:
        self.dataset = dataset
        self.start_index = start_index
        self.end_index = end_index
        self.current_index = current_index
        self.update()

    def _content_rect(self) -> QRectF:
        return QRectF(18.0, 16.0, max(10.0, self.width() - 78.0), max(10.0, self.height() - 34.0))

    def _index_at_position(self, position: QPointF) -> int | None:
        if not self.dataset or self.end_index <= self.start_index or not self._plot_rect.contains(position):
            return None
        count = self.end_index - self.start_index
        if count == 1:
            return self.start_index
        ratio = (position.x() - self._plot_rect.left()) / max(1.0, self._plot_rect.width())
        local = round(ratio * (count - 1))
        local = max(0, min(count - 1, local))
        return self.start_index + local

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        super().mousePressEvent(event)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        event.ignore()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#0c151d"))

        if not self.dataset or self.end_index <= self.start_index:
            painter.setPen(QColor("#9ab0c1"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No speed data to draw.")
            return

        plot = self._content_rect()
        self._plot_rect = plot
        speeds = self.dataset.tick_speeds[self.start_index : self.end_index]
        regimes = self.dataset.regime_tokens[self.start_index : self.end_index]
        count = len(speeds)
        if count == 0:
            return

        visible_min = min(speeds)
        visible_max = max(speeds)
        span = max(visible_max - visible_min, 0.002)
        pad_bottom = max(span * 0.10, 0.002)
        pad_top = max(span * 0.03, 0.001)
        speed_low = min(visible_min, 0.495, 0.505) - pad_bottom
        speed_high = max(visible_max, 0.495, 0.505) + pad_top
        speed_span = max(speed_high - speed_low, 1e-9)

        painter.setPen(QPen(QColor("#203243"), 1.0))
        for threshold in (0.495, 0.505):
            y = plot.bottom() - ((threshold - speed_low) / speed_span) * plot.height()
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(QColor("#8aa0b1"))
            painter.drawText(
                QRectF(plot.right() + 10.0, y - 10.0, 54.0, 18.0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"{threshold:.3f}",
            )
            painter.setPen(QPen(QColor("#203243"), 1.0))

        bar_width = plot.width() / max(count, 1)
        for local_index, speed in enumerate(speeds):
            left = plot.left() + local_index * bar_width
            right = left + max(2.0, bar_width - 1.5)
            top = plot.bottom() - ((speed - speed_low) / speed_span) * plot.height()
            bar = QRectF(left, top, max(2.0, right - left), plot.bottom() - top)
            color = qcolor(REGIME_COLORS.get(regimes[local_index], "#7f96a8"))
            painter.fillRect(bar, with_alpha(color, 210))

        if self.start_index <= self.current_index < self.end_index:
            local_index = self.current_index - self.start_index
            x = plot.left() + (local_index + 0.5) * bar_width
            current_speed = speeds[local_index]
            top = plot.bottom() - ((current_speed - speed_low) / speed_span) * plot.height()
            painter.setPen(QPen(QColor("#f6d89a"), 1.4, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            painter.setPen(QPen(QColor("#081018"), 1.1))
            painter.setBrush(QColor("#f6d89a"))
            painter.drawRoundedRect(QRectF(x - 3.5, top - 3.5, 7.0, 7.0), 3.0, 3.0)

        painter.setPen(QColor("#7f96a8"))
        painter.drawText(
            QRectF(plot.left(), plot.bottom() + 4.0, plot.width(), 18.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"EARLY < 0.495   CLOCK 0.495-0.505   LATE > 0.505   Window rows: {count}",
        )


class StatePuzzleBoard(QWidget):
    stateActivated = pyqtSignal(int)

    def __init__(self) -> None:
        super().__init__()
        self.dataset: ChartDataset | None = None
        self.active_state = 0
        self._paths: dict[int, QPainterPath] = {}
        self._centers: dict[int, QPointF] = {}
        self.setMouseTracking(True)

    def minimumSizeHint(self) -> QSize:
        return QSize(560, 520)

    def set_state(self, dataset: ChartDataset, active_state: int) -> None:
        self.dataset = dataset
        self.active_state = active_state
        self.update()

    def _layout(self) -> tuple[dict[int, QRectF], float]:
        content = QRectF(16.0, 16.0, max(10.0, self.width() - 32.0), max(10.0, self.height() - 32.0))
        board_width = BASE_STEP_X * 4 + BASE_TILE_WIDTH
        board_height = BASE_STEP_Y * 2 + BASE_TILE_HEIGHT
        scale = min(content.width() / board_width, content.height() / board_height)
        scale = max(0.42, scale)
        offset_x = content.left() + (content.width() - board_width * scale) / 2.0
        offset_y = content.top() + (content.height() - board_height * scale) / 2.0
        rectangles: dict[int, QRectF] = {}
        for state_id, (column, row) in PUZZLE_LAYOUT.items():
            x = offset_x + column * BASE_STEP_X * scale
            y = offset_y + row * BASE_STEP_Y * scale
            rectangles[state_id] = QRectF(x, y, BASE_TILE_WIDTH * scale, BASE_TILE_HEIGHT * scale)
        return rectangles, scale

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        point = event.position()
        for state_id, path in self._paths.items():
            if path.contains(point):
                self.stateActivated.emit(state_id)
                return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#0c151d"))

        if not self.dataset:
            painter.setPen(QColor("#9ab0c1"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No state board data.")
            return

        rectangles, scale = self._layout()
        tab_depth = 13.0 * scale
        self._paths.clear()
        self._centers.clear()
        for state_id, rect in rectangles.items():
            self._paths[state_id] = puzzle_piece_path(rect, PUZZLE_TABS[state_id], tab_depth)
            self._centers[state_id] = rect.center()

        current_stats = self.dataset.state_stats[self.active_state]
        target_states = {next_state for next_state, _, _ in current_stats.top_next}

        for rank, (next_state, _, probability) in enumerate(current_stats.top_next):
            start = self._centers[self.active_state]
            end = self._centers[next_state]
            control_lift = 38.0 * scale + rank * 10.0 * scale
            path = QPainterPath(start)
            path.cubicTo(
                QPointF(start.x(), start.y() - control_lift),
                QPointF(end.x(), end.y() - control_lift),
                end,
            )
            pen = QPen(with_alpha(BOARD_STATE_COLORS[next_state], 175), 2.2 + (probability * 10.0))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

        for state_id, path in self._paths.items():
            base = qcolor(BOARD_STATE_COLORS[state_id])
            gradient = QLinearGradient(path.boundingRect().topLeft(), path.boundingRect().bottomRight())
            gradient.setColorAt(0.0, base.lighter(110))
            gradient.setColorAt(1.0, base.darker(118))

            shadow = QPainterPath(path)
            shadow.translate(0.0, 3.0 * scale)
            painter.fillPath(shadow, with_alpha("#05080b", 120))
            painter.fillPath(path, gradient)

            if state_id == self.active_state:
                outline = QPen(QColor("#e6bf7d"), 3.0)
            elif state_id in target_states:
                outline = QPen(QColor("#d7e1e9"), 2.0)
            else:
                outline = QPen(with_alpha("#0b1117", 220), 1.45)
            outline.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(outline)
            painter.drawPath(path)

            rect = path.boundingRect().adjusted(10.0 * scale, 8.0 * scale, -10.0 * scale, -10.0 * scale)
            id_font = QFont("Bahnschrift SemiBold", max(9, int(10 * scale)))
            name_font = QFont("Bahnschrift SemiBold", max(10, int(13 * scale)))
            count_font = QFont("Bahnschrift", max(8, int(8.5 * scale)))
            badge_font = QFont("Bahnschrift SemiBold", max(7, int(7.5 * scale)))

            stats = self.dataset.state_stats[state_id]
            regime_color = qcolor(REGIME_COLORS.get(stats.dominant_regime, "#9ab0c1"))
            regime_fill = regime_color.darker(165)
            state_badge = QRectF(rect.left(), rect.top(), 34.0 * scale, 18.0 * scale)
            regime_badge = QRectF(rect.right() - 58.0 * scale, rect.top(), 58.0 * scale, 18.0 * scale)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(with_alpha("#05080c", 220))
            painter.drawRoundedRect(state_badge, 7.0 * scale, 7.0 * scale)
            painter.setBrush(with_alpha(regime_fill, 225))
            painter.drawRoundedRect(regime_badge, 7.0 * scale, 7.0 * scale)

            painter.setFont(id_font)
            painter.setPen(QColor("#f5f8fb"))
            painter.drawText(state_badge, Qt.AlignmentFlag.AlignCenter, f"S{state_id}")

            painter.setFont(badge_font)
            painter.setPen(QColor("#f2f7fa"))
            painter.drawText(regime_badge, Qt.AlignmentFlag.AlignCenter, stats.dominant_regime)

            name_text = STATE_NAMES[state_id]
            if len(name_text) > 10 and " " in name_text:
                first, rest = name_text.split(" ", 1)
                name_text = f"{first}\n{rest}"

            painter.setPen(QColor("#eef4f7"))
            painter.setFont(name_font)
            painter.drawText(
                QRectF(rect.left(), rect.top() + 24.0 * scale, rect.width(), 36.0 * scale),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                name_text,
            )

            painter.setPen(QColor("#f0d69d") if state_id == self.active_state else QColor("#c7d3db"))
            painter.setFont(count_font)
            painter.drawText(
                QRectF(rect.left(), rect.bottom() - 20.0 * scale, rect.width(), 16.0 * scale),
                Qt.AlignmentFlag.AlignCenter,
                f"{compact_count(stats.count)} rows  |  {stats.avg_speed:.3f}s",
            )


class PuzzleChartWindow(QMainWindow):
    def __init__(self, dataset: ChartDataset) -> None:
        super().__init__()
        self.dataset = dataset
        self.current_index = min(len(dataset) - 1, max(0, len(dataset) // 2))
        self.play_timer = QTimer(self)
        self.play_timer.setInterval(80)
        self.play_timer.timeout.connect(self._advance_playback)

        self.price_chart = PriceChartWidget()
        self.speed_chart = TickSpeedWidget()
        self.board = StatePuzzleBoard()
        self.examples_box = QPlainTextEdit()
        self.examples_box.setReadOnly(True)
        self.examples_box.setFont(QFont("Cascadia Mono", 10))
        self.examples_box.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        self.state_title = QLabel()
        self.state_meta = QLabel()
        self.state_metrics = QLabel()
        self.next_paths = QLabel()
        self.mode_badge = QLabel()
        self.source_label = QLabel()
        self.index_label = QLabel()

        self.play_button = QPushButton("Play")
        self.play_button.setCheckable(True)
        self.play_button.clicked.connect(self._toggle_playback)
        self.zoom_in_button = QPushButton("Zoom In")
        self.zoom_in_button.clicked.connect(lambda: self._adjust_window(1))
        self.zoom_out_button = QPushButton("Zoom Out")
        self.zoom_out_button.clicked.connect(lambda: self._adjust_window(-1))

        self.window_spin = QSpinBox()
        self.window_spin.setRange(40, min(1500, len(dataset)))
        self.window_spin.setValue(min(180, len(dataset)))
        self.window_spin.setSuffix(" rows")
        self.window_spin.valueChanged.connect(self._refresh_view)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, len(dataset) - 1)
        self.slider.setValue(self.current_index)
        self.slider.valueChanged.connect(self._on_slider_changed)

        self._build_ui()
        self._wire_signals()
        self._refresh_view()

    def _build_ui(self) -> None:
        self.setWindowTitle(APP_TITLE)
        self.resize(1780, 1060)
        self.setMinimumSize(1420, 880)
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #05080c;
                color: #ecf3f8;
                font-family: "Bahnschrift";
                font-size: 10pt;
            }
            QFrame#Card {
                background: #0b1117;
                border: 1px solid #162633;
                border-radius: 20px;
            }
            QLabel#Hero {
                font-family: "Bahnschrift SemiBold";
                font-size: 24pt;
                color: #f7fbfd;
            }
            QLabel#Subtle {
                color: #7f98ab;
                font-size: 9.5pt;
            }
            QLabel#CardTitle {
                font-family: "Bahnschrift SemiBold";
                font-size: 12pt;
                color: #eef6fb;
            }
            QLabel#StateTitle {
                font-family: "Bahnschrift SemiBold";
                font-size: 18pt;
                color: #f5f9fc;
            }
            QLabel#Badge {
                background: #0f1d29;
                border: 1px solid #1e394d;
                border-radius: 12px;
                padding: 6px 10px;
                color: #d6e6f2;
                font-family: "Bahnschrift SemiBold";
            }
            QLabel#MetricLine {
                background: #071018;
                border: 1px solid #153042;
                border-radius: 12px;
                padding: 8px 10px;
                color: #eef4f8;
                font-family: "Cascadia Mono";
                font-size: 10pt;
            }
            QLabel#FlowLine {
                background: #071018;
                border: 1px solid #163346;
                border-radius: 12px;
                padding: 8px 10px;
                color: #eff5f9;
                font-size: 10pt;
            }
            QLabel#SourceNote {
                color: #7f98ab;
                font-size: 9.5pt;
            }
            QPushButton {
                background: #0f2434;
                border: 1px solid #1f4258;
                border-radius: 11px;
                padding: 8px 12px;
                color: #ecf3f8;
                font-family: "Bahnschrift SemiBold";
                min-height: 34px;
            }
            QPushButton:hover {
                background: #153247;
            }
            QPushButton:checked {
                background: #cfaa62;
                color: #05080c;
                border-color: #e4c78b;
            }
            QSpinBox, QPlainTextEdit {
                background: #071018;
                border: 1px solid #153042;
                border-radius: 12px;
                color: #dbe8f2;
                padding: 6px 8px;
            }
            QPlainTextEdit {
                background: #060d14;
                selection-background-color: #1c465f;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #122737;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                width: 18px;
                margin: -6px 0;
                border-radius: 9px;
                background: #e4bd78;
            }
            QSlider {
                min-height: 26px;
            }
            QSplitter::handle {
                background: #060c12;
                width: 8px;
            }
            QStatusBar {
                background: #05080c;
                color: #90a8ba;
            }
            """
        )

        outer = QWidget()
        self.setCentralWidget(outer)
        root = QVBoxLayout(outer)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        hero = QLabel(APP_TITLE)
        hero.setObjectName("Hero")
        subtitle = QLabel("Price, state machine, and tick speed all stay locked to one moving cursor.")
        subtitle.setObjectName("Subtle")
        source = QLabel(self.dataset.source_note)
        source.setObjectName("SourceNote")
        source.setWordWrap(True)
        root.addWidget(hero)
        root.addWidget(subtitle)
        root.addWidget(source)

        controls_card = QFrame()
        controls_card.setObjectName("Card")
        controls_layout = QHBoxLayout(controls_card)
        controls_layout.setContentsMargins(14, 12, 14, 12)
        controls_layout.setSpacing(10)

        prev_button = QPushButton("<")
        prev_button.clicked.connect(lambda: self._step_index(-1))
        next_button = QPushButton(">")
        next_button.clicked.connect(lambda: self._step_index(1))

        window_label = QLabel("Window")
        window_label.setObjectName("Subtle")
        self.index_label.setObjectName("Badge")

        controls_layout.addWidget(prev_button)
        controls_layout.addWidget(self.play_button)
        controls_layout.addWidget(next_button)
        controls_layout.addSpacing(8)
        controls_layout.addWidget(window_label)
        controls_layout.addWidget(self.window_spin)
        controls_layout.addWidget(self.zoom_in_button)
        controls_layout.addWidget(self.zoom_out_button)
        controls_layout.addSpacing(8)
        controls_layout.addWidget(self.slider, 1)
        controls_layout.addWidget(self.index_label)
        root.addWidget(controls_card)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)
        root.addWidget(splitter, 1)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        price_card = self._card("Price Track", self.dataset.price_note)
        price_card.layout().addWidget(self.price_chart, 1)  # type: ignore[union-attr]
        speed_card = self._card("Tick Speed Strip", "Same window, same cursor, same point index.")
        speed_card.layout().addWidget(self.speed_chart, 1)  # type: ignore[union-attr]

        left_splitter = QSplitter(Qt.Orientation.Vertical)
        left_splitter.setChildrenCollapsible(False)
        left_splitter.setHandleWidth(8)
        left_splitter.addWidget(price_card)
        left_splitter.addWidget(speed_card)
        left_splitter.setStretchFactor(0, 8)
        left_splitter.setStretchFactor(1, 1)
        left_splitter.setSizes([820, 150])
        left_layout.addWidget(left_splitter, 1)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        board_card = self._card("13-State Puzzle Board", "Click a piece to jump to the nearest real example.")
        board_card.layout().addWidget(self.board, 1)  # type: ignore[union-attr]

        info_card = self._card("Current State", None)
        self.state_title.setObjectName("StateTitle")
        self.state_meta.setObjectName("Subtle")
        self.state_meta.setWordWrap(True)
        self.state_metrics.setObjectName("MetricLine")
        self.state_metrics.setWordWrap(True)
        self.next_paths.setObjectName("FlowLine")
        self.next_paths.setWordWrap(True)
        self.mode_badge.setObjectName("Badge")
        self.source_label.setObjectName("SourceNote")
        self.source_label.setWordWrap(True)
        info_layout = info_card.layout()  # type: ignore[assignment]
        info_layout.addWidget(self.state_title)
        info_layout.addWidget(self.state_meta)
        info_layout.addWidget(self.state_metrics)
        info_layout.addWidget(self.next_paths)
        info_layout.addWidget(self.mode_badge)
        info_layout.addWidget(self.source_label)

        examples_card = self._card("Real Examples", "Samples cluster around the active puzzle piece and current cursor.")
        examples_card.layout().addWidget(self.examples_box, 1)  # type: ignore[union-attr]

        right_splitter = QSplitter(Qt.Orientation.Vertical)
        right_splitter.setChildrenCollapsible(False)
        right_splitter.setHandleWidth(8)
        right_splitter.addWidget(board_card)
        right_splitter.addWidget(info_card)
        right_splitter.addWidget(examples_card)
        right_splitter.setSizes([430, 220, 300])
        right_layout.addWidget(right_splitter, 1)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 11)
        splitter.setStretchFactor(1, 5)
        splitter.setSizes([1220, 560])

    def _card(self, title: str, subtitle: str | None) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(8)

        title_label = QLabel(title)
        title_label.setObjectName("CardTitle")
        layout.addWidget(title_label)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("Subtle")
            subtitle_label.setWordWrap(True)
            layout.addWidget(subtitle_label)
        return frame

    def _wire_signals(self) -> None:
        self.price_chart.indexHovered.connect(self._jump_to_index)
        self.speed_chart.indexHovered.connect(self._jump_to_index)
        self.price_chart.zoomRequested.connect(self._adjust_window)
        self.speed_chart.zoomRequested.connect(self._adjust_window)
        self.board.stateActivated.connect(self._jump_to_state)

    def _toggle_playback(self, checked: bool) -> None:
        if checked:
            if self.current_index >= len(self.dataset) - 1:
                self.current_index = 0
            self.play_button.setText("Pause")
            self.play_timer.start()
        else:
            self.play_button.setText("Play")
            self.play_timer.stop()

    def _advance_playback(self) -> None:
        if self.current_index >= len(self.dataset) - 1:
            self.play_timer.stop()
            self.play_button.setChecked(False)
            self.play_button.setText("Play")
            return
        self._jump_to_index(self.current_index + 1)

    def _on_slider_changed(self, value: int) -> None:
        self._jump_to_index(value)

    def _jump_to_index(self, index: int) -> None:
        self.current_index = max(0, min(len(self.dataset) - 1, index))
        self._refresh_view()

    def _step_index(self, delta: int) -> None:
        self._jump_to_index(self.current_index + delta)

    def _adjust_window(self, direction: int) -> None:
        current = self.window_spin.value()
        delta = max(8, current // 9)
        new_value = current - delta if direction > 0 else current + delta
        new_value = max(self.window_spin.minimum(), min(self.window_spin.maximum(), new_value))
        if new_value != current:
            self.window_spin.setValue(new_value)

    def _jump_to_state(self, state_id: int) -> None:
        occurrences = self.dataset.state_occurrences[state_id]
        if not occurrences:
            return
        current_state = self.dataset.state_ids[self.current_index]
        if state_id == current_state:
            position = bisect.bisect_right(occurrences, self.current_index)
            target = occurrences[0] if position >= len(occurrences) else occurrences[position]
        else:
            target = nearest_index(occurrences, self.current_index)
        self.play_timer.stop()
        self.play_button.setChecked(False)
        self.play_button.setText("Play")
        self._jump_to_index(target)

    def _format_examples(self, state_id: int) -> str:
        stats = self.dataset.state_stats[state_id]
        occurrences = self.dataset.state_occurrences[state_id]
        if not occurrences:
            return "No examples available for this state."

        nearby: list[int] = []
        position = bisect.bisect_left(occurrences, self.current_index)
        left = position - 1
        right = position
        while len(nearby) < 6 and (left >= 0 or right < len(occurrences)):
            if left < 0:
                nearby.append(occurrences[right])
                right += 1
                continue
            if right >= len(occurrences):
                nearby.append(occurrences[left])
                left -= 1
                continue
            left_value = occurrences[left]
            right_value = occurrences[right]
            if abs(left_value - self.current_index) <= abs(right_value - self.current_index):
                nearby.append(left_value)
                left -= 1
            else:
                nearby.append(right_value)
                right += 1

        nearby.sort()
        lines = [
            f"State S{state_id} {STATE_NAMES[state_id]}",
            f"Rows: {stats.count:,}   Avg speed: {stats.avg_speed:.3f}s   Dominant regime: {stats.dominant_regime}",
        ]
        if stats.top_next:
            top_line = "Top paths: " + ", ".join(
                f"S{next_state} {STATE_NAMES[next_state]} {probability * 100:.1f}%"
                for next_state, _, probability in stats.top_next
            )
            lines.append(top_line)
        lines.append("")

        for index in nearby:
            current_marker = ">" if index == self.current_index else " "
            next_state = self.dataset.next_state_id(index)
            next_label = f"S{next_state} {STATE_NAMES[next_state]}" if next_state is not None else "--"
            timestamp = format_clock_label(self.dataset.timestamps[index], self.dataset.synthetic_price)
            lines.append(
                f"{current_marker} #{index + 1:>7,}  "
                f"p {self.dataset.prices[index]:>9.3f}  "
                f"d {self.dataset.price_delta(index):>+7.3f}  "
                f"speed {self.dataset.tick_speeds[index]:>5.3f}s  "
                f"{self.dataset.regime_triplets[index]:<17}  "
                f"{timestamp:>10}  "
                f"-> {next_label}"
            )

        return "\n".join(lines)

    def _refresh_view(self) -> None:
        total_rows = len(self.dataset)
        window = min(total_rows, self.window_spin.value())
        half_window = window // 2
        start_index = max(0, min(self.current_index - half_window, total_rows - window))
        end_index = min(total_rows, start_index + window)

        self.price_chart.set_view(self.dataset, start_index, end_index, self.current_index)
        self.speed_chart.set_view(self.dataset, start_index, end_index, self.current_index)

        state_id = self.dataset.state_ids[self.current_index]
        stats = self.dataset.state_stats[state_id]
        price = self.dataset.prices[self.current_index]
        price_delta = self.dataset.price_delta(self.current_index)
        tick_speed = self.dataset.tick_speeds[self.current_index]
        regime_triplet = self.dataset.regime_triplets[self.current_index]
        raw_index = self.dataset.raw_indices[self.current_index]
        time_label = format_clock_label(self.dataset.timestamps[self.current_index], self.dataset.synthetic_price)
        next_state = self.dataset.next_state_id(self.current_index)
        next_label = f"S{next_state} {STATE_NAMES[next_state]}" if next_state is not None else "--"

        self.board.set_state(self.dataset, state_id)
        self.state_title.setText(f"S{state_id}  {STATE_NAMES[state_id]}")
        self.state_meta.setText(
            f"{stats.count:,} matching rows   |   avg speed {stats.avg_speed:.3f}s   |   "
            f"point {self.current_index + 1:,}/{total_rows:,}   |   raw {raw_index:,}   |   {time_label}"
        )
        self.state_metrics.setText(
            f"Price {price:.3f}   |   Delta {price_delta:+.3f}   |   Tick {tick_speed:.3f}s   |   Regime {regime_triplet}"
        )
        if stats.top_next:
            self.next_paths.setText(
                "Top outgoing paths: "
                + ", ".join(
                    f"S{next_state_id} {STATE_NAMES[next_state_id]} {probability * 100:.1f}%"
                    for next_state_id, _, probability in stats.top_next
                )
                + f"   |   next on cursor {next_label}"
            )
        else:
            self.next_paths.setText(f"Next on cursor {next_label}")

        mode_text = "REAL PRICE MODE" if not self.dataset.synthetic_price else "SYNTHETIC PRICE FALLBACK"
        self.mode_badge.setText(mode_text)
        source_bits = [self.dataset.price_note]
        if self.dataset.reference_name:
            source_bits.append(f"Reference labels: {self.dataset.reference_name}")
        self.source_label.setText("   ".join(source_bits))

        self.slider.blockSignals(True)
        self.slider.setValue(self.current_index)
        self.slider.blockSignals(False)
        self.index_label.setText(f"S{state_id}  |  {self.current_index + 1:,}/{total_rows:,}")
        self.examples_box.setPlainText(self._format_examples(state_id))
        self.statusBar().showMessage(
            f"{self.dataset.name}  |  state S{state_id} {STATE_NAMES[state_id]}  |  "
            f"price {price:.3f}  |  speed {tick_speed:.3f}s  |  next {next_label}"
        )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PyQt6 state puzzle chart app")
    parser.add_argument(
        "--csv",
        default=str(DEFAULT_CSV),
        help="Primary CSV. Labeled CSVs like out.csv are supported; raw tick CSVs work too.",
    )
    parser.add_argument(
        "--raw",
        default=str(DEFAULT_RAW),
        help="Raw tick CSV used for real price sync when --csv is a labeled state file.",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Construct the window and exit immediately. Useful for headless verification.",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    csv_path = Path(args.csv)
    raw_path = Path(args.raw) if args.raw else None
    dataset = load_dataset(csv_path, raw_path)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    apply_dark_palette(app)
    window = PuzzleChartWindow(dataset)
    window.show()

    if args.smoke_test:
        QTimer.singleShot(0, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
