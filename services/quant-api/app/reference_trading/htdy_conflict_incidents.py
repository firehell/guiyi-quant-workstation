"""Frozen, owner-selected maintenance incidents, not a configurable recovery scope."""

ORIGINAL_VERSION = "htdy_conflict_recovery_v1"
OCT31_VERSION = "htdy_conflict_recovery_20261031_v1"
OCT31_INVENTORY_SHA256 = (
    "b52df9f680afaea1a974bfc11c7d79b96a1f837f6813977ca7645bbf37bd8788"
)
# stream -> (old revision, immutable pending capture); all are activation generation 1.
OCT31_BINDINGS = {
    "reference-stream:80b1aee3af7f7521f1fa5e1ebc39943671d4ad9d467be255965e98c658566f63": (
        "2cc241947b5f45c493f5fe170f548a38",
        "14419d1ad93a4b0fa1f63f2309f038ba",
    ),
    "reference-stream:24343f93994de564e5bf0c5d278af130b3090228e6589680a21e5c784b8e4f8d": (
        "a999540f6f28420e8836beb8b35ca053",
        "50b10e609b61456a8f940ef19536b311",
    ),
    "reference-stream:a354a714c3d391886db69b3839b5d64815f985950598f1d236dea1d08b108aed": (
        "e31f277677524f0880433e818b3a4667",
        "260f950990764450b4d3bf8a3849325a",
    ),
}
OCT31_OPEN_STREAM = (
    "reference-stream:24343f93994de564e5bf0c5d278af130b3090228e6589680a21e5c784b8e4f8d"
)
