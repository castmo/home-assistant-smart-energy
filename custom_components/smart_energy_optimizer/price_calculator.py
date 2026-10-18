"""Electricity Tariff and Price Calculator.

Calculates true total end-consumer electricity costs including:
- Spot price (Nordpool / Tibber / Entso-e)
- Supplier surcharges and fees (påslag, elcertifikat)
- Swedish Energy Tax (energiskatt)
- Grid transmission fees (Göteborg Energi Elnät high/low load tariffs)
- VAT (moms, typically 25% in Sweden)
"""

from __future__ import annotations

from dataclasses import dataclass
import datetime
import logging
from typing import Any, Dict, Optional, Tuple

_LOGGER = logging.getLogger(__name__)

# Tariff Presets
TARIFF_GOTEBORG_TIDSTARIFF = "goteborg_energi_tidstariff"
TARIFF_GOTEBORG_ENKELTARIFF = "goteborg_energi_enkeltariff"
TARIFF_FLAT = "flat"
TARIFF_CUSTOM = "custom"


@dataclass
class PriceBreakdown:
    """Detailed breakdown of costs for a single kWh."""

    spot_price: float
    surcharge: float
    energy_tax: float
    grid_transmission_fee: float
    vat_amount: float
    total_price: float
    is_high_load: bool
    currency: str = "SEK"


class ElectricityTariffCalculator:
    """Calculates all-in electricity price for any given hour."""

    def __init__(
        self,
        tariff_type: str = TARIFF_GOTEBORG_TIDSTARIFF,
        surcharge: float = 0.05,  # Påslag (e.g. 5 öre = 0.05 SEK/kWh)
        energy_tax: float = 0.445,  # Swedish energiskatt (~44.5 öre/kWh excl moms)
        grid_fee_high_load: float = 0.38,  # Göteborg Energi winter weekday 06:00-22:00
        grid_fee_low_load: float = 0.16,  # Göteborg Energi night/weekend/summer
        vat_percent: float = 25.0,  # Moms 25%
        spot_price_includes_vat: bool = False,
        currency: str = "SEK",
    ) -> None:
        """Initialize tariff calculator."""
        self.tariff_type = tariff_type
        self.surcharge = float(surcharge)
        self.energy_tax = float(energy_tax)
        self.grid_fee_high_load = float(grid_fee_high_load)
        self.grid_fee_low_load = float(grid_fee_low_load)
        self.vat_percent = float(vat_percent)
        self.spot_price_includes_vat = bool(spot_price_includes_vat)
        self.currency = currency

    def is_goteborg_high_load(self, dt: datetime.datetime) -> bool:
        """Check if timestamp falls into Göteborg Energi high-load hours (höglasttid).

        Göteborg Energi rules:
        - Winter period: November 1 to March 31.
        - Weekdays only: Monday to Friday (weekday() < 5).
        - Hours: 06:00 to 22:00 (hour >= 6 and hour < 22).
        - All other hours (nights 22-06, weekends, April-October) are low-load (låglasttid).
        """
        # Winter months: Nov (11), Dec (12), Jan (1), Feb (2), Mar (3)
        is_winter = dt.month in [11, 12, 1, 2, 3]
        is_weekday = dt.weekday() < 5  # Mon-Fri
        is_day_hour = 6 <= dt.hour < 22

        return is_winter and is_weekday and is_day_hour

    def get_grid_transmission_fee(self, dt: datetime.datetime) -> Tuple[float, bool]:
        """Return (grid_fee, is_high_load) based on tariff configuration."""
        if self.tariff_type == TARIFF_GOTEBORG_TIDSTARIFF:
            high_load = self.is_goteborg_high_load(dt)
            fee = self.grid_fee_high_load if high_load else self.grid_fee_low_load
            return fee, high_load
        elif self.tariff_type == TARIFF_GOTEBORG_ENKELTARIFF:
            return self.grid_fee_low_load, False
        elif self.tariff_type == TARIFF_CUSTOM:
            high_load = 6 <= dt.hour < 22 and dt.weekday() < 5
            fee = self.grid_fee_high_load if high_load else self.grid_fee_low_load
            return fee, high_load
        else:  # FLAT
            return self.grid_fee_low_load, False

    def calculate_total_price(
        self,
        raw_spot_price: float,
        dt: Optional[datetime.datetime] = None,
    ) -> PriceBreakdown:
        """Calculate the total end-user price per kWh including all fees, taxes and VAT.

        Formula:
          Total = (Spot_ex_VAT + Surcharge + EnergyTax + GridFee) * (1 + VAT)
        """
        if dt is None:
            dt = datetime.datetime.now()

        grid_fee, is_high_load = self.get_grid_transmission_fee(dt)
        vat_multiplier = 1.0 + (self.vat_percent / 100.0)

        # Base spot price without VAT
        if self.spot_price_includes_vat:
            spot_ex_vat = raw_spot_price / vat_multiplier
        else:
            spot_ex_vat = raw_spot_price

        # Non-VAT subtotal: Spot + Surcharge + Energy Tax + Grid Transmission Fee
        subtotal_ex_vat = spot_ex_vat + self.surcharge + self.energy_tax + grid_fee
        total_price = subtotal_ex_vat * vat_multiplier
        vat_amount = total_price - subtotal_ex_vat

        return PriceBreakdown(
            spot_price=round(spot_ex_vat, 4),
            surcharge=round(self.surcharge, 4),
            energy_tax=round(self.energy_tax, 4),
            grid_transmission_fee=round(grid_fee, 4),
            vat_amount=round(vat_amount, 4),
            total_price=round(total_price, 4),
            is_high_load=is_high_load,
            currency=self.currency,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize configuration to dict."""
        return {
            "tariff_type": self.tariff_type,
            "surcharge": self.surcharge,
            "energy_tax": self.energy_tax,
            "grid_fee_high_load": self.grid_fee_high_load,
            "grid_fee_low_load": self.grid_fee_low_load,
            "vat_percent": self.vat_percent,
            "spot_price_includes_vat": self.spot_price_includes_vat,
            "currency": self.currency,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ElectricityTariffCalculator":
        """Instantiate from dict."""
        return cls(
            tariff_type=data.get("tariff_type", TARIFF_GOTEBORG_TIDSTARIFF),
            surcharge=data.get("surcharge", 0.05),
            energy_tax=data.get("energy_tax", 0.445),
            grid_fee_high_load=data.get("grid_fee_high_load", 0.38),
            grid_fee_low_load=data.get("grid_fee_low_load", 0.16),
            vat_percent=data.get("vat_percent", 25.0),
            spot_price_includes_vat=data.get("spot_price_includes_vat", False),
            currency=data.get("currency", "SEK"),
        )
