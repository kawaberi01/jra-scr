import binascii
import zlib

samples = {
    "pw01sli00": "AF",
    "pw01skl00999999": "B3",
    "pw01srl10032026020120260627": "35",
    "pw01srl10102026020120260627": "80",
    "pw01srl10022026010520260627": "86",
    "pw01sde1003202602021120260628": "DC",
    "pw01sde1002202601061120260628": "2D",
    "pw01sde1005202603061120260621": "42",
    "pw01sde1009202603061120260621": "6A",
    "pw01sde1005202602121220260531": "E9",
}


def check(name, fn):
    return all(f"{fn(key):02X}" == value for key, value in samples.items())


candidates = {
    "sum": lambda s: sum(s.encode()) & 0xFF,
    "xor": lambda s: _xor(s.encode()),
    "crc32": lambda s: zlib.crc32(s.encode()) & 0xFF,
    "crc_hqx": lambda s: binascii.crc_hqx(s.encode(), 0) & 0xFF,
    "adler32": lambda s: zlib.adler32(s.encode()) & 0xFF,
}


def _xor(data: bytes) -> int:
    value = 0
    for item in data:
        value ^= item
    return value


for name, fn in candidates.items():
    print(name, check(name, fn))
    for key, value in list(samples.items())[:3]:
        print(name, key, value, f"{fn(key):02X}")
