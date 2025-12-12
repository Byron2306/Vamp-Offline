"""NWU-format specific parsers and helpers."""

try:  # pragma: no cover - optional dependency convenience import
    from .ta_parser import parse_nwu_ta, PerformanceContract, PerformanceKPA  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    parse_nwu_ta = None
    PerformanceContract = None
    PerformanceKPA = None

from .pa_reader import read_nwu_pa  # noqa: F401
