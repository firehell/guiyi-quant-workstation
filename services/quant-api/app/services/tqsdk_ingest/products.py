from dataclasses import dataclass


DEFAULT_CORE_PRODUCTS = [
    "rb",
    "hc",
    "i",
    "j",
    "jm",
    "TA",
    "MA",
    "pp",
    "v",
    "eg",
    "SA",
    "fu",
    "bu",
    "sc",
    "cu",
    "al",
    "m",
    "y",
    "p",
]


@dataclass(frozen=True)
class ProductSpec:
    product: str
    exchange: str
    name: str
    sector: str

    @property
    def contract_code(self) -> str:
        return f"{self.product}.MAIN"

    @property
    def download_symbol(self) -> str:
        return f"KQ.m@{self.exchange}.{self.product}"


PRODUCT_SPECS = {
    "rb": ProductSpec("rb", "SHFE", "螺纹", "black"),
    "hc": ProductSpec("hc", "SHFE", "热卷", "black"),
    "i": ProductSpec("i", "DCE", "铁矿石", "black"),
    "j": ProductSpec("j", "DCE", "焦炭", "black"),
    "jm": ProductSpec("jm", "DCE", "焦煤", "black"),
    "TA": ProductSpec("TA", "CZCE", "PTA", "chemical"),
    "MA": ProductSpec("MA", "CZCE", "甲醇", "chemical"),
    "EG": ProductSpec("eg", "DCE", "乙二醇", "chemical"),
    "l": ProductSpec("l", "DCE", "塑料", "chemical"),
    "pp": ProductSpec("pp", "DCE", "PP", "chemical"),
    "v": ProductSpec("v", "DCE", "PVC", "chemical"),
    "SA": ProductSpec("SA", "CZCE", "纯碱", "chemical"),
    "FG": ProductSpec("FG", "CZCE", "玻璃", "chemical"),
    "sc": ProductSpec("sc", "INE", "原油", "energy"),
    "fu": ProductSpec("fu", "SHFE", "燃油", "energy"),
    "bu": ProductSpec("bu", "SHFE", "沥青", "energy"),
    "pg": ProductSpec("pg", "DCE", "液化气", "energy"),
    "cu": ProductSpec("cu", "SHFE", "沪铜", "metal"),
    "al": ProductSpec("al", "SHFE", "沪铝", "metal"),
    "zn": ProductSpec("zn", "SHFE", "沪锌", "metal"),
    "pb": ProductSpec("pb", "SHFE", "沪铅", "metal"),
    "ni": ProductSpec("ni", "SHFE", "沪镍", "metal"),
    "sn": ProductSpec("sn", "SHFE", "沪锡", "metal"),
    "au": ProductSpec("au", "SHFE", "沪金", "precious_metal"),
    "ag": ProductSpec("ag", "SHFE", "沪银", "precious_metal"),
    "m": ProductSpec("m", "DCE", "豆粕", "agriculture"),
    "y": ProductSpec("y", "DCE", "豆油", "agriculture"),
    "p": ProductSpec("p", "DCE", "棕榈油", "agriculture"),
    "eb": ProductSpec("eb", "DCE", "苯乙烯", "chemical"),
    "PF": ProductSpec("PF", "CZCE", "短纤", "chemical"),
    "UR": ProductSpec("UR", "CZCE", "尿素", "chemical"),
    "lu": ProductSpec("lu", "INE", "低硫燃油", "energy"),
}

_ALIASES = {
    "pp": "pp",
    "l": "l",
    "v": "v",
    "eg": "EG",
    "ta": "TA",
    "ma": "MA",
    "sa": "SA",
    "fg": "FG",
    "pf": "PF",
    "ur": "UR",
}
_PRODUCT_LOOKUP = {key.lower(): value for key, value in PRODUCT_SPECS.items()}
_PRODUCT_LOOKUP.update({alias: PRODUCT_SPECS[target] for alias, target in _ALIASES.items()})


def product_spec(product: str) -> ProductSpec:
    try:
        return _PRODUCT_LOOKUP[product.lower()]
    except KeyError as exc:
        raise ValueError(f"unsupported TqSdk core product: {product}") from exc


def selected_product_specs(products: list[str] | None) -> list[ProductSpec]:
    return [product_spec(item) for item in (products or DEFAULT_CORE_PRODUCTS)]
