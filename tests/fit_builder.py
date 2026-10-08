"""Minimal FIT encoder for tests: synthetic 1 Hz `record` messages (timestamp, heart_rate, speed, cadence).

Keeps personal GPS/HR files out of the repo while still exercising the real fitdecode parser and CRC check.
"""
import struct
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Tuple

_CRC_TABLE = [0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
              0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400]
_FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)


def _crc(data: bytes) -> int:
    crc = 0
    for byte in data:
        for nibble in (byte & 0xF, (byte >> 4) & 0xF):
            tmp = _CRC_TABLE[crc & 0xF]
            crc = (crc >> 4) & 0x0FFF
            crc = crc ^ tmp ^ _CRC_TABLE[nibble]
    return crc


Sample = Tuple[int, Optional[int], Optional[float], Optional[int]]   # t (s), hr, speed m/s, cadence (per leg)


def build_fit(samples: Iterable[Sample], start: datetime = datetime(2026, 10, 4, 0, 30, tzinfo=timezone.utc)) -> bytes:
    base = int((start - _FIT_EPOCH).total_seconds())
    body = bytearray()
    # definition: local 0 -> global 20 (record): timestamp uint32, heart_rate uint8, speed uint16 (/1000), cadence uint8
    body += bytes([0x40, 0, 0]) + struct.pack("<HB", 20, 4)
    body += bytes([253, 4, 0x86, 3, 1, 0x02, 6, 2, 0x84, 4, 1, 0x02])
    for t, hr, speed, cad in samples:
        body += bytes([0x00]) + struct.pack(
            "<IBHB", base + t,
            0xFF if hr is None else int(hr),
            0xFFFF if speed is None else int(round(speed * 1000)),
            0xFF if cad is None else int(cad))
    header = struct.pack("<BBHI4s", 14, 0x10, 2093, len(body), b".FIT")
    header += struct.pack("<H", _crc(header))
    data = header + bytes(body)
    return data + struct.pack("<H", _crc(data))


def synthetic_test_run(test_hr: int = 168, warmup_s: int = 900, cool_s: int = 600, cadence: int = 88) -> List[Sample]:
    """15 min warm-up, 30 min test (HR settles at `test_hr` from minute 10), 10 min cool-down."""
    out: List[Sample] = []
    t = 0
    for i in range(warmup_s):
        out.append((t, 130 + i // 120, 2.8, 84)); t += 1
    for i in range(1800):
        hr = test_hr - 6 + int(6 * i / 600) if i < 600 else test_hr
        out.append((t, hr, 3.3, cadence)); t += 1
    for i in range(cool_s):
        out.append((t, 140, 2.6, 82)); t += 1
    return out
