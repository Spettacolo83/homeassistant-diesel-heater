"""Session fuel accounting separate from controller resettable statistics."""

from dataclasses import dataclass


@dataclass
class SessionFuel:
    """Retain a high-water mark and explicit Off/reset boundary across reconnects."""

    minutes: int | None = None
    centilitres: int | None = None
    off_seen: bool = False
    active: bool = False
    was_off: bool = False
    prior_session: tuple[int, int] | None = None
    gap: bool = False

    def observe_status(self, off: bool) -> None:
        """Only a transition into actual Off authorizes a counter reset."""
        if off and not self.was_off and self.active:
            self.off_seen = True
        if not off and self.was_off and self.minutes == 0 and self.centilitres == 0:
            self.off_seen = False
        self.was_off = off

    def observe_connection(self) -> None:
        """An interruption may hide a whole session; never backfill its new baseline."""
        if self.active:
            self.gap = True

    def accept(self, minutes: int, centilitres: int) -> int | None:
        """Return new centilitres; None establishes baseline without backfilling."""
        if not self.active:
            self.minutes, self.centilitres, self.active = minutes, centilitres, True
            self.off_seen = self.was_off
            return None
        assert self.minutes is not None and self.centilitres is not None
        if self.off_seen and minutes == 0 and centilitres == 0:
            self.prior_session = (self.minutes, self.centilitres) if (self.minutes or self.centilitres) else None
            self.minutes, self.centilitres, self.off_seen, self.gap = 0, 0, False, False
            return 0
        if self.prior_session == (minutes, centilitres):
            return 0
        if minutes < self.minutes or centilitres < self.centilitres:
            if self.gap:
                self.prior_session = (self.minutes, self.centilitres)
                self.minutes, self.centilitres, self.gap = minutes, centilitres, False
                self.off_seen = False
                return 0
            if not self.off_seen or self.was_off:
                # A nonzero regression while still Off is not a new session.
                # A delayed/regressive report is not permission to recount fuel.
                return 0
            self.prior_session = (self.minutes, self.centilitres)
            self.minutes, self.centilitres = minutes, centilitres
            self.off_seen = False
            return centilitres
        self.gap = False
        delta = centilitres - self.centilitres
        self.minutes, self.centilitres = minutes, centilitres
        return delta

    def payload(self) -> dict:
        """Save this baseline atomically with the totals it has already updated."""
        return dict(
            minutes=self.minutes,
            centilitres=self.centilitres,
            off_seen=self.off_seen,
            active=self.active,
            was_off=self.was_off,
            prior_session=self.prior_session,
            gap=self.gap,
        )

    @classmethod
    def restore(cls, value) -> "SessionFuel":
        """Reject malformed stored baselines instead of counting history twice."""
        if not isinstance(value, dict) or value.get("active") is not True:
            return cls()
        minutes, fuel = value.get("minutes"), value.get("centilitres")
        if (
            type(minutes) is not int
            or type(fuel) is not int
            or not 0 <= minutes <= 0xFFFFFF
            or not 0 <= fuel <= 65535 * 100 + 255
        ):
            return cls()
        prior = value.get("prior_session")
        if not isinstance(prior, (tuple, list)) or len(prior) != 2 or any(type(v) is not int or v < 0 for v in prior):
            prior = None
        return cls(
            minutes,
            fuel,
            value.get("off_seen") is True,
            True,
            value.get("was_off") is True,
            tuple(prior) if prior else None,
            True,
        )
