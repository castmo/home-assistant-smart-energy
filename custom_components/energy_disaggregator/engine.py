"""Core Disaggregation Engine for 3-Phase NILM and Active Learning."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import logging
import math
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid

from .const import (
    CONSUMER_BOILER,
    CONSUMER_CAR_CHARGER,
    CONSUMER_DISHWASHER,
    CONSUMER_DRYER,
    CONSUMER_HEAT_PUMP,
    CONSUMER_OVEN,
    CONSUMER_STOVE,
    CONSUMER_UNKNOWN,
    CONSUMER_WASHER,
    DEFAULT_CONSUMER_CATALOG,
    DEFAULT_MIN_STEP_WATTS,
)

_LOGGER = logging.getLogger(__name__)


def current_iso_time() -> str:
    """Return current UTC time in ISO format."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PhaseReading:
    """A single 3-phase power reading snapshot."""

    p1: float
    p2: float
    p3: float
    total: float
    timestamp: float


@dataclass
class StepEdge:
    """A detected step change in active power."""

    edge_id: str
    edge_type: str  # 'positive' (ON) or 'negative' (OFF)
    delta_l1: float
    delta_l2: float
    delta_l3: float
    delta_total: float
    phase_pattern: str  # '1_phase_l1', '2_phase_l1_l2', '3_phase_balanced', etc.
    symmetry_ratio: float
    timestamp: float

    def to_dict(self) -> Dict[str, Any]:
        """Convert edge to dictionary."""
        return asdict(self)


class ConsumerProfile:
    """Represents a monitored high-load appliance and its learned signature."""

    def __init__(
        self,
        consumer_id: str,
        name: str,
        icon: str = "mdi:power-plug",
        phase_type: str = "any",
        nominal_power: float = 2000.0,
        nominal_l1: float = 0.0,
        nominal_l2: float = 0.0,
        nominal_l3: float = 0.0,
        tolerance: float = 500.0,
    ) -> None:
        self.id = consumer_id
        self.name = name
        self.icon = icon
        self.phase_type = phase_type  # '1_phase', '2_phase', '3_phase', 'any'
        self.active_phase: str = "any"  # specific learned phase: 'l1', 'l2', 'l3', 'l1_l2', 'balanced'

        # Learned statistical signature (means and standard deviations in Watts)
        self.nominal_power = float(nominal_power)
        self.mean_total = float(nominal_power)
        self.mean_l1 = float(nominal_l1)
        self.mean_l2 = float(nominal_l2)
        self.mean_l3 = float(nominal_l3)
        self.std_total = float(tolerance)
        self.std_l1 = float(max(100.0, tolerance / 2.0))
        self.std_l2 = float(max(100.0, tolerance / 2.0))
        self.std_l3 = float(max(100.0, tolerance / 2.0))

        # Confirmation count
        self.confirmations: int = 0

        # Real-time running state
        self.is_active: bool = False
        self.current_power: float = 0.0
        self.current_l1: float = 0.0
        self.current_l2: float = 0.0
        self.current_l3: float = 0.0

        # Energy tracking
        self.session_start_time: Optional[float] = None
        self.session_energy_kwh: float = 0.0
        self.lifetime_energy_kwh: float = 0.0
        self.last_energy_calc_time: Optional[float] = None

        # Event timestamps
        self.last_turned_on: Optional[str] = None
        self.last_turned_off: Optional[str] = None

    def update_signature(
        self, delta_l1: float, delta_l2: float, delta_l3: float, delta_total: float
    ) -> None:
        """Update signature with confirmed sample using Welford's online update."""
        n = self.confirmations + 1
        self.confirmations = n

        # Adaptive learning rate (faster at start, stable later)
        alpha = 1.0 / n if n <= 10 else 0.1

        # Update means
        old_mean_total = self.mean_total
        self.mean_total += alpha * (delta_total - self.mean_total)
        self.mean_l1 += alpha * (delta_l1 - self.mean_l1)
        self.mean_l2 += alpha * (delta_l2 - self.mean_l2)
        self.mean_l3 += alpha * (delta_l3 - self.mean_l3)

        # Update variance/std estimate
        diff = abs(delta_total - old_mean_total)
        self.std_total = max(150.0, (1 - alpha) * self.std_total + alpha * diff)

        # Classify and remember primary phase
        if delta_total > 0:
            f1 = delta_l1 / delta_total
            f2 = delta_l2 / delta_total
            f3 = delta_l3 / delta_total
            if f1 > 0.7:
                self.active_phase = "l1"
                self.phase_type = "1_phase"
            elif f2 > 0.7:
                self.active_phase = "l2"
                self.phase_type = "1_phase"
            elif f3 > 0.7:
                self.active_phase = "l3"
                self.phase_type = "1_phase"
            elif f1 > 0.3 and f2 > 0.3 and f3 < 0.2:
                self.active_phase = "l1_l2"
                self.phase_type = "2_phase"
            elif f2 > 0.3 and f3 > 0.3 and f1 < 0.2:
                self.active_phase = "l2_l3"
                self.phase_type = "2_phase"
            elif f1 > 0.2 and f2 > 0.2 and f3 > 0.2:
                self.active_phase = "balanced"
                self.phase_type = "3_phase"

    def activate(
        self,
        delta_l1: float,
        delta_l2: float,
        delta_l3: float,
        delta_total: float,
        now_ts: Optional[float] = None,
        iso_str: Optional[str] = None,
    ) -> None:
        """Mark consumer as active and initialize energy session."""
        now = now_ts or time.time()
        self.is_active = True
        self.current_power = max(0.0, delta_total)
        self.current_l1 = max(0.0, delta_l1)
        self.current_l2 = max(0.0, delta_l2)
        self.current_l3 = max(0.0, delta_l3)
        self.session_start_time = now
        self.session_energy_kwh = 0.0
        self.last_energy_calc_time = now
        self.last_turned_on = iso_str or current_iso_time()

    def integrate_energy(self, now_ts: Optional[float] = None) -> float:
        """Accumulate Riemann sum trapezoidal energy in kWh while active."""
        if not self.is_active or self.current_power <= 0:
            return 0.0

        now = now_ts or time.time()
        if self.last_energy_calc_time is None:
            self.last_energy_calc_time = now
            return 0.0

        dt_seconds = now - self.last_energy_calc_time
        if dt_seconds <= 0.0:
            return 0.0

        # Cap dt to max 300s in case of system sleep/pause
        dt_seconds = min(dt_seconds, 300.0)

        # kWh = Watts * seconds / (3600 * 1000)
        delta_kwh = (self.current_power * dt_seconds) / 3600000.0
        self.session_energy_kwh += delta_kwh
        self.lifetime_energy_kwh += delta_kwh
        self.last_energy_calc_time = now
        return delta_kwh

    def deactivate(
        self, now_ts: Optional[float] = None, iso_str: Optional[str] = None
    ) -> None:
        """Mark consumer as idle and finalize session."""
        self.integrate_energy(now_ts)
        self.is_active = False
        self.current_power = 0.0
        self.current_l1 = 0.0
        self.current_l2 = 0.0
        self.current_l3 = 0.0
        self.session_start_time = None
        self.last_energy_calc_time = None
        self.last_turned_off = iso_str or current_iso_time()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize consumer profile to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "icon": self.icon,
            "phase_type": self.phase_type,
            "active_phase": self.active_phase,
            "nominal_power": self.nominal_power,
            "mean_total": self.mean_total,
            "mean_l1": self.mean_l1,
            "mean_l2": self.mean_l2,
            "mean_l3": self.mean_l3,
            "std_total": self.std_total,
            "std_l1": self.std_l1,
            "std_l2": self.std_l2,
            "std_l3": self.std_l3,
            "confirmations": self.confirmations,
            "is_active": self.is_active,
            "current_power": self.current_power,
            "current_l1": self.current_l1,
            "current_l2": self.current_l2,
            "current_l3": self.current_l3,
            "session_start_time": self.session_start_time,
            "session_energy_kwh": self.session_energy_kwh,
            "lifetime_energy_kwh": self.lifetime_energy_kwh,
            "last_turned_on": self.last_turned_on,
            "last_turned_off": self.last_turned_off,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ConsumerProfile:
        """Restore consumer profile from dictionary."""
        consumer = cls(
            consumer_id=data["id"],
            name=data.get("name", data["id"]),
            icon=data.get("icon", "mdi:power-plug"),
            phase_type=data.get("phase_type", "any"),
            nominal_power=data.get("nominal_power", 2000.0),
        )
        consumer.active_phase = data.get("active_phase", "any")
        consumer.mean_total = float(data.get("mean_total", consumer.nominal_power))
        consumer.mean_l1 = float(data.get("mean_l1", 0.0))
        consumer.mean_l2 = float(data.get("mean_l2", 0.0))
        consumer.mean_l3 = float(data.get("mean_l3", 0.0))
        consumer.std_total = float(data.get("std_total", 500.0))
        consumer.std_l1 = float(data.get("std_l1", 250.0))
        consumer.std_l2 = float(data.get("std_l2", 250.0))
        consumer.std_l3 = float(data.get("std_l3", 250.0))
        consumer.confirmations = int(data.get("confirmations", 0))
        consumer.is_active = bool(data.get("is_active", False))
        consumer.current_power = float(data.get("current_power", 0.0))
        consumer.current_l1 = float(data.get("current_l1", 0.0))
        consumer.current_l2 = float(data.get("current_l2", 0.0))
        consumer.current_l3 = float(data.get("current_l3", 0.0))
        consumer.session_start_time = data.get("session_start_time")
        consumer.session_energy_kwh = float(data.get("session_energy_kwh", 0.0))
        consumer.lifetime_energy_kwh = float(data.get("lifetime_energy_kwh", 0.0))
        consumer.last_turned_on = data.get("last_turned_on")
        consumer.last_turned_off = data.get("last_turned_off")
        return consumer


@dataclass
class PendingEvent:
    """An unconfirmed detected load change event waiting for user input."""

    event_id: str
    edge: StepEdge
    proposed_consumer: str
    confidence: float
    ranked_candidates: List[Tuple[str, float]]
    timestamp: float
    iso_timestamp: str
    status: str  # 'pending', 'confirmed', 'unknown', 'auto_confirmed'

    def to_dict(self) -> Dict[str, Any]:
        """Convert pending event to dictionary."""
        return {
            "event_id": self.event_id,
            "edge": self.edge.to_dict(),
            "proposed_consumer": self.proposed_consumer,
            "confidence": round(self.confidence, 1),
            "ranked_candidates": [
                {"consumer": c, "confidence": round(p, 1)}
                for c, p in self.ranked_candidates
            ],
            "timestamp": self.timestamp,
            "iso_timestamp": self.iso_timestamp,
            "status": self.status,
        }


class DisaggregationEngine:
    """Non-Intrusive Load Monitoring (NILM) Engine for 3-Phase HomeWizard Data."""

    def __init__(
        self,
        min_step_watts: float = DEFAULT_MIN_STEP_WATTS,
        auto_confirm_threshold: int = 0,
    ) -> None:
        self.min_step_watts = float(min_step_watts)
        self.auto_confirm_threshold = int(auto_confirm_threshold)

        # Monitored consumer profiles
        self.consumers: Dict[str, ConsumerProfile] = {}
        self._init_default_consumers()

        # Sliding window buffer of recent readings
        self._readings_buffer: List[PhaseReading] = []
        self._max_buffer_size = 20

        # Pending event awaiting user interaction
        self.pending_event: Optional[PendingEvent] = None

        # History of recent events
        self.recent_events: List[Dict[str, Any]] = []
        self.unknown_events_log: List[Dict[str, Any]] = []

        # Last confirmed edge timestamp to prevent double triggers
        self._last_edge_time: float = 0.0

    def _init_default_consumers(self) -> None:
        """Initialize default catalog consumers."""
        for cid, cfg in DEFAULT_CONSUMER_CATALOG.items():
            self.consumers[cid] = ConsumerProfile(
                consumer_id=cid,
                name=cfg["name"],
                icon=cfg["icon"],
                phase_type=cfg["phase_type"],
                nominal_power=cfg["nominal_power"],
                nominal_l1=cfg["nominal_l1"],
                nominal_l2=cfg["nominal_l2"],
                nominal_l3=cfg["nominal_l3"],
                tolerance=cfg["tolerance"],
            )

    def add_reading(
        self,
        p1: float,
        p2: float,
        p3: float,
        total: Optional[float] = None,
        timestamp: Optional[float] = None,
    ) -> Optional[PendingEvent]:
        """Process incoming 3-phase power reading and detect ON/OFF edges."""
        now = timestamp or time.time()
        p1 = float(max(0.0, p1))
        p2 = float(max(0.0, p2))
        p3 = float(max(0.0, p3))
        tot = float(total) if total is not None else (p1 + p2 + p3)

        reading = PhaseReading(p1=p1, p2=p2, p3=p3, total=tot, timestamp=now)
        self._readings_buffer.append(reading)
        if len(self._readings_buffer) > self._max_buffer_size:
            self._readings_buffer.pop(0)

        # Real-time Riemann integration for all currently running consumers
        for consumer in self.consumers.values():
            if consumer.is_active:
                consumer.integrate_energy(now)

        # Need at least 4 readings to detect a stable step change
        if len(self._readings_buffer) < 4:
            return None

        # Debounce: minimum 3 seconds between edge triggers
        if (now - self._last_edge_time) < 3.0:
            return None

        # Detect edge step
        edge = self._detect_edge()
        if edge is None:
            return None

        self._last_edge_time = now

        # Case 1: Positive Edge (Consumer turned ON)
        if edge.edge_type == "positive":
            return self._handle_positive_edge(edge, now)

        # Case 2: Negative Edge (Consumer turned OFF)
        if edge.edge_type == "negative":
            self._handle_negative_edge(edge, now)
            return None

        return None

    def _detect_edge(self) -> Optional[StepEdge]:
        """Evaluate sliding window for step changes."""
        buf = self._readings_buffer
        n = len(buf)
        if n < 4:
            return None

        # Baseline level: average of older samples (before the latest 2 samples)
        base_samples = buf[:-2][-4:]  # up to 4 baseline samples before the step
        if not base_samples:
            return None

        base_p1 = sum(s.p1 for s in base_samples) / len(base_samples)
        base_p2 = sum(s.p2 for s in base_samples) / len(base_samples)
        base_p3 = sum(s.p3 for s in base_samples) / len(base_samples)
        base_tot = sum(s.total for s in base_samples) / len(base_samples)

        d1_latest = buf[-1].total - base_tot
        d2_prev = buf[-2].total - base_tot

        # Check if the total step or any phase is above threshold
        max_phase_d1 = max(
            abs(buf[-1].p1 - base_p1),
            abs(buf[-1].p2 - base_p2),
            abs(buf[-1].p3 - base_p3),
        )
        max_phase_d2 = max(
            abs(buf[-2].p1 - base_p1),
            abs(buf[-2].p2 - base_p2),
            abs(buf[-2].p3 - base_p3),
        )

        # Must have significant delta on the latest sample
        if abs(d1_latest) < self.min_step_watts and max_phase_d1 < (self.min_step_watts * 0.7):
            return None

        # To prevent false triggers on 1-sample spikes, previous sample must also be shifted
        if abs(d2_prev) < (self.min_step_watts * 0.75) and max_phase_d2 < (self.min_step_watts * 0.5):
            return None

        # Both samples must have the same step sign (both rising or both falling)
        if (d1_latest * d2_prev) <= 0:
            return None

        # Current level: average of the 2 stable post-step samples
        curr_p1 = (buf[-1].p1 + buf[-2].p1) / 2.0
        curr_p2 = (buf[-1].p2 + buf[-2].p2) / 2.0
        curr_p3 = (buf[-1].p3 + buf[-2].p3) / 2.0
        curr_tot = (buf[-1].total + buf[-2].total) / 2.0

        d_p1 = curr_p1 - base_p1
        d_p2 = curr_p2 - base_p2
        d_p3 = curr_p3 - base_p3
        d_tot = curr_tot - base_tot

        abs_tot = abs(d_tot)
        if abs_tot < self.min_step_watts and max(abs(d_p1), abs(d_p2), abs(d_p3)) < (
            self.min_step_watts * 0.7
        ):
            return None

        # Determine phase pattern
        pattern, symmetry = self._analyze_phase_pattern(d_p1, d_p2, d_p3, abs_tot)
        edge_type = "positive" if d_tot > 0 else "negative"

        return StepEdge(
            edge_id=f"edge_{int(time.time() * 1000)}_{uuid.uuid4().hex[:4]}",
            edge_type=edge_type,
            delta_l1=round(d_p1, 1),
            delta_l2=round(d_p2, 1),
            delta_l3=round(d_p3, 1),
            delta_total=round(d_tot, 1),
            phase_pattern=pattern,
            symmetry_ratio=round(symmetry, 2),
            timestamp=buf[-1].timestamp,
        )

    def _analyze_phase_pattern(
        self, d1: float, d2: float, d3: float, total_abs: float
    ) -> Tuple[str, float]:
        """Classify step into 1-phase, 2-phase, or 3-phase signature."""
        a1, a2, a3 = abs(d1), abs(d2), abs(d3)
        if total_abs <= 0:
            return "unknown", 0.0

        # Fractions of total delta
        f1, f2, f3 = a1 / total_abs, a2 / total_abs, a3 / total_abs

        # Active phase threshold: at least 15% of total step and >= 150W
        active = []
        if f1 >= 0.15 and a1 >= 150:
            active.append(("l1", a1))
        if f2 >= 0.15 and a2 >= 150:
            active.append(("l2", a2))
        if f3 >= 0.15 and a3 >= 150:
            active.append(("l3", a3))

        if len(active) == 3:
            powers = [p for _, p in active]
            symmetry = min(powers) / max(powers)
            pattern = (
                "3_phase_balanced" if symmetry >= 0.65 else "multi_phase_unbalanced"
            )
            return pattern, symmetry

        if len(active) == 2:
            names = sorted([name for name, _ in active])
            powers = [p for _, p in active]
            symmetry = min(powers) / max(powers)
            pattern = f"2_phase_{names[0]}_{names[1]}"
            return pattern, symmetry

        if len(active) == 1:
            return f"1_phase_{active[0][0]}", 1.0

        # Fallback to strongest phase
        max_phase = max([("l1", a1), ("l2", a2), ("l3", a3)], key=lambda x: x[1])
        return f"1_phase_{max_phase[0]}", 1.0

    def _handle_positive_edge(self, edge: StepEdge, now: float) -> PendingEvent:
        """Match positive step against consumer catalog and propose best candidate."""
        ranked = self._rank_candidates(edge)
        best_candidate, confidence = ranked[0]

        iso_str = current_iso_time()
        pending = PendingEvent(
            event_id=edge.edge_id,
            edge=edge,
            proposed_consumer=best_candidate,
            confidence=confidence,
            ranked_candidates=ranked,
            timestamp=now,
            iso_timestamp=iso_str,
            status="pending",
        )

        self.pending_event = pending
        self.recent_events.append(pending.to_dict())
        if len(self.recent_events) > 50:
            self.recent_events.pop(0)

        # Check if eligible for auto-confirmation
        if (
            self.auto_confirm_threshold > 0
            and best_candidate in self.consumers
            and self.consumers[best_candidate].confirmations
            >= self.auto_confirm_threshold
            and confidence >= 90.0
        ):
            _LOGGER.info(
                "Auto-confirming %s for edge %s (confidence: %.1f%%)",
                best_candidate,
                edge.edge_id,
                confidence,
            )
            pending.status = "auto_confirmed"
            self.confirm_event(edge.edge_id, best_candidate, now, iso_str)
            return pending

        _LOGGER.info(
            "Detected positive step: %+.0f W (%s). Proposing: %s (%.1f%% confidence)",
            edge.delta_total,
            edge.phase_pattern,
            best_candidate,
            confidence,
        )
        return pending

    def _rank_candidates(self, edge: StepEdge) -> List[Tuple[str, float]]:
        """Compute matching likelihood scores for all registered consumers."""
        scores: Dict[str, float] = {}
        d_tot = abs(edge.delta_total)
        d1, d2, d3 = abs(edge.delta_l1), abs(edge.delta_l2), abs(edge.delta_l3)

        for cid, consumer in self.consumers.items():
            score = 100.0

            # Penalty if consumer is already active
            if consumer.is_active:
                score -= 40.0

            # 1. Phase Compatibility
            pattern = edge.phase_pattern
            if consumer.phase_type == "3_phase":
                if pattern == "3_phase_balanced":
                    score += 45.0
                elif "2_phase" in pattern:
                    score -= 40.0
                elif "1_phase" in pattern:
                    score -= 90.0

            elif consumer.phase_type == "2_phase":
                if "2_phase" in pattern:
                    score += 45.0
                elif pattern == "3_phase_balanced":
                    score -= 40.0
                elif "1_phase" in pattern:
                    score -= 30.0

            elif consumer.phase_type == "1_phase":
                if "1_phase" in pattern:
                    score += 35.0
                    # Bonus if matching specific learned phase
                    if consumer.active_phase in pattern:
                        score += 30.0
                elif pattern == "3_phase_balanced":
                    score -= 95.0
                elif "2_phase" in pattern:
                    score -= 50.0

            # 2. Power Delta Distance
            expected_tot = consumer.mean_total
            tolerance = max(consumer.std_total, 300.0)
            diff_tot = abs(d_tot - expected_tot)

            # Distance penalty
            tot_penalty = (diff_tot / tolerance) * 45.0
            score -= tot_penalty

            # If multi-phase, evaluate phase distribution distance
            if consumer.phase_type in ("3_phase", "2_phase"):
                exp_l1 = consumer.mean_l1
                exp_l2 = consumer.mean_l2
                exp_l3 = consumer.mean_l3
                phase_diff = (
                    abs(d1 - exp_l1) + abs(d2 - exp_l2) + abs(d3 - exp_l3)
                ) / 3.0
                score -= (phase_diff / tolerance) * 20.0

            # 3. Learning Weight Bonus: Consumers confirmed more times get confidence boost
            if consumer.confirmations > 0:
                score += min(20.0, consumer.confirmations * 2.5)

            scores[cid] = max(1.0, score)

        # Add Unknown Option baseline score
        scores[CONSUMER_UNKNOWN] = 20.0

        # Softmax conversion to probabilities (temperament T=18)
        temperature = 18.0
        max_score = max(scores.values())
        exp_scores = {
            cid: math.exp((s - max_score) / temperature) for cid, s in scores.items()
        }
        sum_exp = sum(exp_scores.values())

        ranked: List[Tuple[str, float]] = []
        for cid, exp_val in exp_scores.items():
            prob = (exp_val / sum_exp) * 100.0
            ranked.append((cid, prob))

        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked

    def _handle_negative_edge(self, edge: StepEdge, now: float) -> None:
        """Match negative step against currently active consumers and turn off."""
        abs_tot = abs(edge.delta_total)
        active_consumers = [c for c in self.consumers.values() if c.is_active]

        if not active_consumers:
            _LOGGER.debug(
                "Negative step of %.0f W detected, but no active consumer is registered",
                abs_tot,
            )
            return

        # Match to the active consumer whose current power is closest to step magnitude
        best_match: Optional[ConsumerProfile] = None
        min_diff = float("inf")

        for c in active_consumers:
            diff = abs(c.current_power - abs_tot)
            # Favor matching phase pattern
            if (
                c.phase_type == "3_phase" and edge.phase_pattern == "3_phase_balanced"
            ) or (c.phase_type == "1_phase" and "1_phase" in edge.phase_pattern):
                diff *= 0.7  # 30% bonus for phase structure match

            if diff < min_diff:
                min_diff = diff
                best_match = c

        # Deactivate if difference is reasonable (e.g. within 50% or 800W)
        if best_match and (
            min_diff <= 800.0 or min_diff / max(1.0, best_match.current_power) <= 0.5
        ):
            _LOGGER.info(
                "Negative step %+.0f W matched to active consumer '%s' (current: %.0f W). Deactivating.",
                edge.delta_total,
                best_match.name,
                best_match.current_power,
            )
            best_match.deactivate(now, current_iso_time())
        else:
            _LOGGER.info(
                "Negative step %+.0f W detected; closest active was '%s' (diff: %.0f W).",
                edge.delta_total,
                best_match.name if best_match else "None",
                min_diff,
            )

    def confirm_event(
        self,
        event_id: Optional[str] = None,
        selected_consumer: str = CONSUMER_UNKNOWN,
        now_ts: Optional[float] = None,
        iso_str: Optional[str] = None,
    ) -> bool:
        """Confirm a detected event with user selection and update learned knowledge."""
        now = now_ts or time.time()
        iso = iso_str or current_iso_time()

        # Find target event
        target_event = self.pending_event
        if target_event is None and self.recent_events:
            for ev in reversed(self.recent_events):
                if event_id is None or ev.get("event_id") == event_id:
                    # reconstruct lightweight pending from recent
                    target_event = PendingEvent(
                        event_id=ev["event_id"],
                        edge=StepEdge(**ev["edge"]),
                        proposed_consumer=ev.get("proposed_consumer", CONSUMER_UNKNOWN),
                        confidence=ev.get("confidence", 0.0),
                        ranked_candidates=[],
                        timestamp=ev.get("timestamp", now),
                        iso_timestamp=ev.get("iso_timestamp", iso),
                        status="pending",
                    )
                    break

        if target_event is None:
            _LOGGER.warning("No pending or matching event found to confirm")
            return False

        edge = target_event.edge

        # Handle Unknown choice
        if selected_consumer in (CONSUMER_UNKNOWN, "unknown", "none"):
            _LOGGER.info(
                "User marked event %s (%+.0f W) as Unknown / Ignore",
                target_event.event_id,
                edge.delta_total,
            )
            self.unknown_events_log.append(
                {
                    "event_id": target_event.event_id,
                    "edge": edge.to_dict(),
                    "timestamp": now,
                    "iso_timestamp": iso,
                }
            )
            if len(self.unknown_events_log) > 50:
                self.unknown_events_log.pop(0)

            if (
                self.pending_event
                and self.pending_event.event_id == target_event.event_id
            ):
                self.pending_event.status = "unknown"
                self.pending_event = None
            return True

        # Handle Confirmed Consumer choice
        if selected_consumer not in self.consumers:
            _LOGGER.warning("Selected consumer '%s' is not registered", selected_consumer)
            return False

        consumer = self.consumers[selected_consumer]

        # Update learned signature
        d_tot = abs(edge.delta_total)
        d1, d2, d3 = abs(edge.delta_l1), abs(edge.delta_l2), abs(edge.delta_l3)
        consumer.update_signature(d1, d2, d3, d_tot)

        # Mark active
        consumer.activate(d1, d2, d3, d_tot, now, iso)

        _LOGGER.info(
            "Confirmed event %s as '%s'. Learned mean is now %.0f W (samples: %d)",
            target_event.event_id,
            consumer.name,
            consumer.mean_total,
            consumer.confirmations,
        )

        if self.pending_event and self.pending_event.event_id == target_event.event_id:
            if self.pending_event.status != "auto_confirmed":
                self.pending_event.status = "confirmed"
            self.pending_event = None

        return True

    def mark_unknown(self, event_id: Optional[str] = None) -> bool:
        """Convenience method to mark current or specified event as unknown."""
        return self.confirm_event(event_id, CONSUMER_UNKNOWN)

    def teach_consumer(
        self,
        consumer_id: str,
        nominal_power: float,
        phase_type: str = "any",
        nominal_l1: float = 0.0,
        nominal_l2: float = 0.0,
        nominal_l3: float = 0.0,
    ) -> None:
        """Manually calibrate or teach an expected power signature."""
        if consumer_id not in self.consumers:
            self.consumers[consumer_id] = ConsumerProfile(
                consumer_id=consumer_id,
                name=consumer_id.replace("_", " ").title(),
                phase_type=phase_type,
                nominal_power=nominal_power,
                nominal_l1=nominal_l1,
                nominal_l2=nominal_l2,
                nominal_l3=nominal_l3,
            )
        consumer = self.consumers[consumer_id]
        consumer.nominal_power = float(nominal_power)
        consumer.mean_total = float(nominal_power)
        consumer.mean_l1 = float(nominal_l1)
        consumer.mean_l2 = float(nominal_l2)
        consumer.mean_l3 = float(nominal_l3)
        consumer.phase_type = phase_type
        consumer.confirmations = max(1, consumer.confirmations)

    def reset_learning(self) -> None:
        """Reset all learned consumer signatures back to default priors."""
        self.consumers.clear()
        self._init_default_consumers()
        self.pending_event = None
        self.recent_events.clear()
        self.unknown_events_log.clear()
        _LOGGER.info("Reset disaggregation learning and signatures to defaults")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize engine state for persistent Home Assistant storage."""
        return {
            "min_step_watts": self.min_step_watts,
            "auto_confirm_threshold": self.auto_confirm_threshold,
            "consumers": {cid: c.to_dict() for cid, c in self.consumers.items()},
            "unknown_events_log": self.unknown_events_log[-20:],
            "recent_events": self.recent_events[-20:],
        }

    def from_dict(self, data: Dict[str, Any]) -> None:
        """Restore engine state from persistent Home Assistant storage."""
        if not data:
            return

        self.min_step_watts = float(
            data.get("min_step_watts", self.min_step_watts)
        )
        self.auto_confirm_threshold = int(
            data.get("auto_confirm_threshold", self.auto_confirm_threshold)
        )

        consumers_data = data.get("consumers", {})
        for cid, cdata in consumers_data.items():
            self.consumers[cid] = ConsumerProfile.from_dict(cdata)

        self.unknown_events_log = data.get("unknown_events_log", [])
        self.recent_events = data.get("recent_events", [])
