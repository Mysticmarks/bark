from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np


@dataclass
class ControlEvent:
    """Fine-grained control signal for steering generation.

    Attributes:
        token: Identifier or symbol representing the control directive.
        timecode_s: Optional timestamp (in seconds) where the event should apply.
        metadata: Arbitrary metadata for downstream routing, e.g., intensity.
    """

    token: str
    timecode_s: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ModalityBundle:
    """Container for omnimodal inputs and routing hints.

    This dataclass standardizes optional inputs so that callers can pass text,
    audio, image, or control signals together with routing priorities. The core
    audio generation path still relies on text, but the bundle keeps additional
    context available for future fusion modules.
    """

    text: Optional[str] = None
    reference_audio: Optional[np.ndarray] = None
    image: Optional[np.ndarray] = None
    control_events: Optional[Sequence[ControlEvent]] = None
    routing_priorities: Dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.control_events is not None:
            self.control_events = tuple(self.control_events)

    @property
    def active_modalities(self) -> List[str]:
        return [
            name
            for name, value in (
                ("text", self.text),
                ("reference_audio", self.reference_audio),
                ("image", self.image),
                ("control_events", self.control_events),
            )
            if value is not None
        ]

    def normalized_priorities(self) -> Dict[str, float]:
        """Return routing priorities that cover all active modalities.

        Missing priorities default to zero, making it explicit when a modality
        is intentionally ignored by downstream consumers.
        """

        priorities: Dict[str, float] = {k: 0.0 for k in self.active_modalities}
        priorities.update(self.routing_priorities)
        return priorities

    def copy_with_updates(
        self,
        *,
        control_events: Optional[Iterable[ControlEvent]] = None,
        routing_priorities: Optional[Dict[str, float]] = None,
    ) -> "ModalityBundle":
        return ModalityBundle(
            text=self.text,
            reference_audio=self.reference_audio,
            image=self.image,
            control_events=tuple(control_events) if control_events is not None else self.control_events,
            routing_priorities=routing_priorities or self.routing_priorities,
        )
