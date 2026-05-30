"""Time-to-offer instrumentation (U13, R15) — the orchestrator-side helper.

Time-to-offer is the primary product metric for BOTH the seller and buyer
variants: the elapsed wall-clock time from a lead being created to an offer
being drafted. Rails owns the durable record (``OfferMetric``); this module is
the orchestrator-side mirror that computes the same duration so the metric can
be emitted into the structured log/trace alongside an offer-drafted event.

Design constraints that keep it testable:

* PURE LOGIC. The computation NEVER calls :func:`time.time` /
  :func:`datetime.now` itself — both timestamps are passed in. That makes every
  duration deterministic and lets tests assert exact values. A run records a
  metric only when there genuinely is an offer-drafted moment; an escalated or
  abandoned flow simply never calls :meth:`TimeToOffer.record`, so it can raise
  no false completion.
* SIDE-TAGGED. Every record carries ``side`` ("seller" | "buyer") so the two
  variants aggregate independently, matching the Rails per-side dashboard panel.
* STRUCTURED. :meth:`TimeToOffer.as_log` projects a record onto a flat,
  JSON-friendly dict ready for structured logging.

stdlib-only, no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

SIDE_SELLER = "seller"
SIDE_BUYER = "buyer"
SIDES = (SIDE_SELLER, SIDE_BUYER)


def _as_epoch_seconds(ts: float | datetime) -> float:
    """Coerce a timestamp to epoch seconds.

    Accepts either a raw epoch ``float``/``int`` or a timezone-aware (or naive,
    assumed UTC) :class:`datetime`, so callers can pass whichever they already
    hold without forcing a conversion at the call site.
    """
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.timestamp()
    return float(ts)


@dataclass(frozen=True)
class TimeToOfferRecord:
    """A single computed time-to-offer measurement.

    :param side: ``"seller"`` or ``"buyer"`` — the flow variant.
    :param seconds_to_offer: elapsed seconds from lead-created to offer-drafted
        (always ``>= 0``).
    :param lead_created: source epoch-seconds timestamp the duration started at.
    :param offer_drafted: source epoch-seconds timestamp the duration ended at.
    """

    side: str
    seconds_to_offer: float
    lead_created: float
    offer_drafted: float

    def as_log(self) -> dict[str, object]:
        """Project the record onto a flat dict for structured logging."""
        return {
            "metric": "time_to_offer",
            "side": self.side,
            "seconds_to_offer": self.seconds_to_offer,
            "lead_created": self.lead_created,
            "offer_drafted": self.offer_drafted,
        }


class TimeToOffer:
    """A hermetic recorder for time-to-offer measurements.

    Holds an in-memory list of :class:`TimeToOfferRecord` so a run (or a test)
    can record several offers and then read per-side and aggregate summaries.
    It performs no I/O and never reads the clock — callers supply timestamps.
    """

    def __init__(self) -> None:
        self._records: list[TimeToOfferRecord] = []

    @staticmethod
    def compute(
        side: str,
        lead_created: float | datetime,
        offer_drafted: float | datetime,
    ) -> TimeToOfferRecord:
        """Compute a side-tagged time-to-offer record from two timestamps.

        :param side: ``"seller"`` or ``"buyer"``.
        :param lead_created: when the lead was created (epoch seconds or datetime).
        :param offer_drafted: when the offer was drafted (epoch seconds or datetime).
        :raises ValueError: if ``side`` is unknown or the offer predates the lead
            (a negative duration is never a valid completion).
        """
        if side not in SIDES:
            raise ValueError(f"unknown side {side!r}; expected one of {SIDES}")

        start = _as_epoch_seconds(lead_created)
        end = _as_epoch_seconds(offer_drafted)
        seconds = end - start
        if seconds < 0:
            raise ValueError(
                "offer_drafted precedes lead_created; time-to-offer cannot be negative"
            )

        return TimeToOfferRecord(
            side=side,
            seconds_to_offer=seconds,
            lead_created=start,
            offer_drafted=end,
        )

    def record(
        self,
        side: str,
        lead_created: float | datetime,
        offer_drafted: float | datetime,
    ) -> TimeToOfferRecord:
        """Compute a record and retain it. Call this only on a real draft."""
        record = self.compute(side, lead_created, offer_drafted)
        self._records.append(record)
        return record

    @property
    def records(self) -> tuple[TimeToOfferRecord, ...]:
        """An immutable view of the recorded measurements, in insertion order."""
        return tuple(self._records)

    def count(self, side: str | None = None) -> int:
        """Number of records, optionally restricted to one ``side``."""
        return len(self._for(side))

    def average_seconds(self, side: str | None = None) -> float | None:
        """Mean time-to-offer, optionally per ``side``; ``None`` if empty."""
        records = self._for(side)
        if not records:
            return None
        return sum(r.seconds_to_offer for r in records) / len(records)

    def summary(self) -> dict[str, dict[str, object]]:
        """Per-side and aggregate stats, mirroring the Rails dashboard panel."""
        sides = {
            side: {
                "count": self.count(side),
                "average_seconds": self.average_seconds(side),
            }
            for side in SIDES
        }
        sides["all"] = {
            "count": self.count(),
            "average_seconds": self.average_seconds(),
        }
        return sides

    def _for(self, side: str | None) -> list[TimeToOfferRecord]:
        if side is None:
            return self._records
        return [r for r in self._records if r.side == side]
