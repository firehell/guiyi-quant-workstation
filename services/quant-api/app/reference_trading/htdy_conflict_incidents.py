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


NOV03_VERSION = "htdy_conflict_recovery_20261103_v1"
NOV03_INVENTORY_SHA256 = (
    "cc5e1c27d980452a128af5635491c56e4bdf339d461a198c1266d8e500bb1b37"
)
# stream -> (old revision, pending capture, generation, checkpoint batch, OPEN trade or None).
# This incident includes prior retired conflicts; their typed proofs remain mandatory.
NOV03_BINDINGS = {
    "reference-stream:0bd72d58e494ba0c3c76c222141bf9d14282008a4536267a3c1285986efcd8c5": (  # PS
        "6e5d2c5173534a5d9b42560cf69ba205",
        "a7dfcf3ae9504acd909c6d9e6dfad8cf",
        1,
        "978c56908c02437aba050f432b9d8e1c",
        "reference-trade:157bdde3aecf78af3d5dc795b54fa969432f5e8b9c7993ca9e6edacf2ca24271",
    ),
    "reference-stream:19a551ea97b218656ff7b2462e89c6ee44ddb6ccb926b5bed2df6bb13b59fab4": (  # PT
        "4632533036e24d61a0d0155185d07d68",
        "686dc062508a48f3bb92d3abdf1bea00",
        1,
        "e4d2aab0c7294be092d40ca44e92dedc",
        "reference-trade:ba8a0a6afe56abca99771cb1923686fab8da91b465cb5c0c7830c19782ccb8c0",
    ),
    "reference-stream:44eb4c5dceaf0331deded57cb4ba79d522bd575289e121956297a9bca257974a": (  # LC
        "b787f7258238433da7c4196d4f73d797",
        "0941efff063b4321a828e6ba2abe9b45",
        2,
        "9c47c1ebe0d44343a3ff8be472fd32a3",
        None,
    ),
    "reference-stream:82c1f916ee1227a14487491b368afc032cdb2725b30a914b446f257662df7bed": (  # SF
        "f72492cd214846e1b2cf5fd8eb80f0e4",
        "71295157a55e4df3ae16e8250312fada",
        2,
        "b7707b07c2934267aedb0ff4800b34cc",
        None,
    ),
    "reference-stream:8612e3118fbd43cff68b523627dd3d25e08b6cab754ddd29191c686f949ba8de": (  # LH
        "950ad15f8e1b46fc926efa65e50fa091",
        "1df172cff3934cac993c42c82903bd21",
        2,
        "4e91ecd1b0544b6d9d3aafa72c2f7b70",
        None,
    ),
    "reference-stream:8bbca864461c867f504e1306f95a30f161325049ba8b8250cfd89c24888894db": (  # PD
        "066c193085414593b58b81f4b7c3ad86",
        "84fd03be6b404628a8e827b01a49fe7e",
        1,
        "89a6e74f72f24670af7bf12d3a39d704",
        "reference-trade:ae587cc13cc2bb74079536a7dbd0ac4cc10c000a4018379c59ba366d19c2845e",
    ),
    "reference-stream:b3e1ea9d7543f36d175cc1add33d3674810713a2d790e1d960202eb2f12ec8de": (  # SM
        "48c87f42266b4cc3bdf3b81ce7f21234",
        "13d42c85a7684d72a3d30f94299227c6",
        2,
        "339a4b73d8d949d2a8ce1c26ef4537ef",
        "reference-trade:e25227660d775c7bf2579245eb20f083fae26cd118d3a2f09a67779da9cb2f3e",
    ),
    "reference-stream:cde4a953e05421e362a740d1c45f2747eb31ec194d9bc1604b807bc0187c2fb6": (  # PK
        "e302c8a678d4492281eb909939ff7d02",
        "f31c244a5c124d3eb9755d0818e21c98",
        2,
        "9898dc8082bb482a959e223e6a1faa6a",
        None,
    ),
    "reference-stream:d26afc6086a8710138a37002b6b384e3a5a2e93b923069dfa7908cbe356d2e55": (  # CJ
        "2fc5bdeb708d4e16994aafcfd63395ca",
        "42d6d7373b714731aef1591db16f1d5a",
        2,
        "e6df580ad46e489299c5e146e170679a",
        "reference-trade:86839d0c1f0d37c4323e12859e195b5d3d8469b966275f0cdcd2e046e6444201",
    ),
    "reference-stream:d7927893f70ab589aa4857dd7e6b5eb1f24bc90bb1fbb2a8df115bd59652bf9d": (  # JD
        "901c346e15704a6dbd6d9d5b9a8ccc36",
        "4c7e2b98b0924161967b0e2b95262f67",
        2,
        "55943dd01cd54148979e13e076fe29fa",
        None,
    ),
    "reference-stream:e5d425448e95d1a3530ae604649ab96a4332e74d8fabc74b33ab843856855962": (  # AP
        "a91dceff878b4298bdca745b77bb5591",
        "c87985201c3647209777921290f143d1",
        2,
        "9d1272df778f4286b7483f0ad8853498",
        None,
    ),
}
