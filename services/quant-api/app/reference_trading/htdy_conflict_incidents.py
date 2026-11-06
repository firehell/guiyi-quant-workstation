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


NOV04_VERSION = "htdy_conflict_recovery_20261104_v1"
NOV04_INVENTORY_SHA256 = (
    "f08607bb8fa823199d05aead9c5dc303bc578b1a482de19faf26ade82c9b7caf"
)
# Owner approved 12 exact conflicts; only SI has an OPEN reference trade.
NOV04_BINDINGS = {
    "reference-stream:0bd72d58e494ba0c3c76c222141bf9d14282008a4536267a3c1285986efcd8c5": (  # PS
        "f7cff51f9434485b9471d0ae12f0f9c4",
        "bde96453adfe44e988a374ad2154d079",
        2,
        "c74dcfa743b649c4a12a387faf6afd37",
        None,
    ),
    "reference-stream:19a551ea97b218656ff7b2462e89c6ee44ddb6ccb926b5bed2df6bb13b59fab4": (  # PT
        "01a8fa7cd6c64faca03d8deec0340ab7",
        "313bfdc1c5624e37bbc6615424d9302f",
        2,
        "f76917a3a3524bb2bca4a7f1ee585c47",
        None,
    ),
    "reference-stream:31c1f7ffe88b05d8142d0fa4ac46ca4d5d977d9604c6deb945a8ffe5389aa7bf": (  # SI
        "b22d5845d1d147a49a48e3c82a98f94e",
        "b28715a408ab4aebb5f1f4344b13495c",
        2,
        "b49b11ef96b14780be0df70c2e08d022",
        "reference-trade:27951c24409b2e4a56d88582cc246249a7eaf43482aa460c75c4efc7ae87b2c7",
    ),
    "reference-stream:44eb4c5dceaf0331deded57cb4ba79d522bd575289e121956297a9bca257974a": (  # LC
        "7172e4bfcfa343cbb993337e969fa9e7",
        "8b867fb09e5f49858f4115f32f551711",
        3,
        "d2038174e50d4173a4bdf65a1379e2e4",
        None,
    ),
    "reference-stream:82c1f916ee1227a14487491b368afc032cdb2725b30a914b446f257662df7bed": (  # SF
        "1f88f949a969488aa6e068744b4c630d",
        "3d444b69113d4b0bbbc4ccf2ccac8a12",
        3,
        "f7a73bc5fc714675b8e54d70af84bdab",
        None,
    ),
    "reference-stream:8612e3118fbd43cff68b523627dd3d25e08b6cab754ddd29191c686f949ba8de": (  # LH
        "4d25e1ea11b242168e689be5b7b10f20",
        "17053c828485475484f7508f3ab7645b",
        3,
        "bdb7ab9c400a4af79f9a62e7adf0ec41",
        None,
    ),
    "reference-stream:8bbca864461c867f504e1306f95a30f161325049ba8b8250cfd89c24888894db": (  # PD
        "2154efee25d04f079a4117728abb9b0e",
        "167f8757a1f94229a3b25f53b39fbab8",
        2,
        "951b50f4ed794c459f1f3e9e8ae38f05",
        None,
    ),
    "reference-stream:b3e1ea9d7543f36d175cc1add33d3674810713a2d790e1d960202eb2f12ec8de": (  # SM
        "b0c3c9cf1a734ea09f75b36804433d4d",
        "ebff12b87d2a4ce6bb2f6c5b90d253da",
        3,
        "f80d4625c8c64c8ca73937efbbc42bd3",
        None,
    ),
    "reference-stream:cde4a953e05421e362a740d1c45f2747eb31ec194d9bc1604b807bc0187c2fb6": (  # PK
        "c7d45bd98f3a4403ac1f5fa3fb61a0a3",
        "ac6915896da9449cb8ef50ef508ab0fe",
        3,
        "639bf97de99340e8a47e259801129b27",
        None,
    ),
    "reference-stream:d26afc6086a8710138a37002b6b384e3a5a2e93b923069dfa7908cbe356d2e55": (  # CJ
        "94d2c48c395c417d8dc4e550d9c65347",
        "d1cdfd374bb64a5c9ee6fe3f7483d056",
        3,
        "374690c4e41c4ffd85a940eb044bba7b",
        None,
    ),
    "reference-stream:d7927893f70ab589aa4857dd7e6b5eb1f24bc90bb1fbb2a8df115bd59652bf9d": (  # JD
        "9e1fcd7549a34a3ca496921181543f72",
        "c49641b50d724609a310353a23e86576",
        3,
        "919281c9cdf0482c960464826804c923",
        None,
    ),
    "reference-stream:e5d425448e95d1a3530ae604649ab96a4332e74d8fabc74b33ab843856855962": (  # AP
        "37e7ae4210544885a3d5684acc5fa1d3",
        "fe3ed087adaa433daa66d2183bfadaef",
        3,
        "f17d03f2dde943a2939d08320d2e1911",
        None,
    ),
}


NOV05_VERSION = "htdy_conflict_recovery_20261105_v1"
NOV05_INVENTORY_SHA256 = "89d759414d2206ddf6af239101441edb06079f2228594a8c090727c87304ffc4"
# Exact owner-approved RS/UR originals; both streams are FLAT.
NOV05_BINDINGS = {
    "reference-stream:21149875d0b154b6efa0647e3ad271453cc1d15dc7419087469e2b9fd62b0493": (  # UR
        'b766aba6ebf848a0866e25735fd94cdd',
        'f72b376f19a044b6823bc6ea16e185c0',
        2,
        '48f410d71e0d419eb5f6b163d9562381',
        None,
    ),
    "reference-stream:c1f54db610d1a9f74fb524c617d1826f1101239b28c62174ce55db8f2fd6be0e": (  # RS
        'aafc44f2048f4fafbddf8ddbc41db651',
        '06f31180580843c1a5fb280fdaf8b445',
        1,
        'cc2ae5337490420eb24d1dee34a75327',
        None,
    ),
}


NOV06_VERSION = "htdy_conflict_recovery_20261106_v1"
NOV06_INVENTORY_SHA256 = "0edfab2eefb2042ae33fba864caf2934eb7e897feb8ed2a4fd5c3172f466dada"
# Owner-approved 11 exact originals; only PD/PS have OPEN reference trades.
NOV06_BINDINGS = {
    'reference-stream:0bd72d58e494ba0c3c76c222141bf9d14282008a4536267a3c1285986efcd8c5': (  # PS
        '06456a4dd3014d1a890b25af0c667cbd',
        '47e99652891f4e06b77c25d42bc9c75b',
        3,
        '68c0edd53adb4e6bbfe1a193a2c9c50e',
        'reference-trade:d2e4049110325d8a71c31f946c1733f23799220b3dbdfe902135c1698ca6fb15',
    ),
    'reference-stream:21149875d0b154b6efa0647e3ad271453cc1d15dc7419087469e2b9fd62b0493': (  # UR
        'bd07ae50a1f343f4912552bf4509e396',
        'def7312e8b4f408b85c55ec0729ae11b',
        3,
        '9a13a16aac66487d85ce43311e60305d',
        None,
    ),
    'reference-stream:44eb4c5dceaf0331deded57cb4ba79d522bd575289e121956297a9bca257974a': (  # LC
        '535570f0e1b54db78afd73a1c29eacfe',
        'bc49d6e94fb141d8bd81fbb50d4017f1',
        4,
        'ed38dcc77bf14cd4a7b774c763a556a3',
        None,
    ),
    'reference-stream:82c1f916ee1227a14487491b368afc032cdb2725b30a914b446f257662df7bed': (  # SF
        '4392d143c92e47c0af7769bcc095dd6e',
        '7c4a2be22be7469888bb67fde28a21a7',
        4,
        '3768191c14234e05baa3a2b5150b47a4',
        None,
    ),
    'reference-stream:8612e3118fbd43cff68b523627dd3d25e08b6cab754ddd29191c686f949ba8de': (  # LH
        'd4f1aa0989984b60b7f45a1dbe89bc96',
        '952dd107208a43ce974ecfd7016ce3be',
        4,
        '18f665c2ce604480850dd98f3269783d',
        None,
    ),
    'reference-stream:8bbca864461c867f504e1306f95a30f161325049ba8b8250cfd89c24888894db': (  # PD
        '95adf0b227c54804bcc2a2cbb4aa28a3',
        '5e0222aa13374d1bb680bbde4cdc5ced',
        3,
        'd6cbe3fdfd064bb4a93cfc235973276f',
        'reference-trade:ea8dc626663dcbddac4c02e805f69f182c49d97a5a53743ae38aec6ab9e41bfc',
    ),
    'reference-stream:b3e1ea9d7543f36d175cc1add33d3674810713a2d790e1d960202eb2f12ec8de': (  # SM
        'db4c9efaee894e2f8db542dc747813a7',
        'fdfc96f343fe467299fc9a2731ed3b85',
        4,
        '3854ff6dd67e4c1da864e63e11c22886',
        None,
    ),
    'reference-stream:cde4a953e05421e362a740d1c45f2747eb31ec194d9bc1604b807bc0187c2fb6': (  # PK
        'cb2b89d40b10424aa6b814dc9de537c3',
        'afa3e89564644d4594efd62b12f3f787',
        4,
        'a777d8c251604db08560b0407d951669',
        None,
    ),
    'reference-stream:d26afc6086a8710138a37002b6b384e3a5a2e93b923069dfa7908cbe356d2e55': (  # CJ
        '257f2289eb964df3a1796369661ae8f1',
        '1d2c646fa0544f2eb21ea85ebcf88609',
        4,
        '0c1cf8c3b0bb4bd79183185f053c5c38',
        None,
    ),
    'reference-stream:d7927893f70ab589aa4857dd7e6b5eb1f24bc90bb1fbb2a8df115bd59652bf9d': (  # JD
        '9f07154c259d4d29b112a73833da27a2',
        '19c0d061c9c1460db94ec47300d26ccf',
        4,
        'cf72e6139b304bec87e6977f118251cb',
        None,
    ),
    'reference-stream:e5d425448e95d1a3530ae604649ab96a4332e74d8fabc74b33ab843856855962': (  # AP
        'b09a2a3d8b1a403e8300ef876016f4a8',
        'a01b7c3aaf994e3db654daa99b8abfeb',
        4,
        '6f94e208aa5c4645bcb0ac1a3b595ce1',
        None,
    ),
}
