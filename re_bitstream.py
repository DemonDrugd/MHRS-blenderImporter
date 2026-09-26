# -*- coding: utf-8 -*-
"""
RE Engine Binary Stream & Utility Functions for Blender Add-on
"""

import struct
import math


def murmur3_hash(key, get_unsigned=False):
    """32-bit MurmurHash3 implementation matching RE Engine hashing."""
    if isinstance(key, str):
        key_bytes = bytearray(key, 'utf-8')
    else:
        key_bytes = bytearray(key)

    seed = 0xFFFFFFFF

    def fmix(h):
        h ^= h >> 16
        h = (h * 0x85EBCA6B) & 0xFFFFFFFF
        h ^= h >> 13
        h = (h * 0xC2B2AE35) & 0xFFFFFFFF
        h ^= h >> 16
        return h

    length = len(key_bytes)
    nblocks = length // 4
    h1 = seed

    c1 = 0xCC9E2D51
    c2 = 0x1B873593

    for block_start in range(0, nblocks * 4, 4):
        k1 = (
            key_bytes[block_start + 3] << 24
            | key_bytes[block_start + 2] << 16
            | key_bytes[block_start + 1] << 8
            | key_bytes[block_start + 0]
        )
        k1 = (c1 * k1) & 0xFFFFFFFF
        k1 = ((k1 << 15) | (k1 >> 17)) & 0xFFFFFFFF
        k1 = (c2 * k1) & 0xFFFFFFFF

        h1 ^= k1
        h1 = ((h1 << 13) | (h1 >> 19)) & 0xFFFFFFFF
        h1 = (h1 * 5 + 0xE6546B64) & 0xFFFFFFFF

    tail_index = nblocks * 4
    k1 = 0
    tail_size = length & 3

    if tail_size >= 3:
        k1 ^= key_bytes[tail_index + 2] << 16
    if tail_size >= 2:
        k1 ^= key_bytes[tail_index + 1] << 8
    if tail_size >= 1:
        k1 ^= key_bytes[tail_index + 0]

    if tail_size > 0:
        k1 = (k1 * c1) & 0xFFFFFFFF
        k1 = ((k1 << 15) | (k1 >> 17)) & 0xFFFFFFFF
        k1 = (c2 * k1) & 0xFFFFFFFF
        h1 ^= k1

    unsigned_val = fmix(h1 ^ length)
    if get_unsigned or (unsigned_val & 0x80000000) == 0:
        return unsigned_val
    else:
        return -((unsigned_val ^ 0xFFFFFFFF) + 1)


def hash_wide(key, get_unsigned=False):
    """RE Engine wide string hash (UTF-16LE characters with null terminator)."""
    key_temp = bytearray()
    for char in key:
        key_temp.extend(ord(char).to_bytes(2, 'little'))
    return murmur3_hash(key_temp, get_unsigned)


def read_packed_bits_vec3(packed_int, num_bits):
    limit = (1 << num_bits) - 1
    if limit == 0:
        return (0.0, 0.0, 0.0)
    x = (packed_int & limit) / limit
    y = ((packed_int >> num_bits) & limit) / limit
    z = ((packed_int >> (num_bits * 2)) & limit) / limit
    return (x, y, z)


def convert_bits(packed_int, num_bits):
    limit = (1 << num_bits) - 1
    return (packed_int / limit) if limit else 0.0


def w_rot(quat3):
    rot_w = 1.0 - (quat3[0] * quat3[0] + quat3[1] * quat3[1] + quat3[2] * quat3[2])
    if rot_w > 0:
        return math.sqrt(rot_w)
    return 0.0


class BinaryReader:
    """Fast binary stream reader for RE Engine files."""

    def __init__(self, data):
        if isinstance(data, (bytes, bytearray, memoryview)):
            self.data = memoryview(data)
        else:
            self.data = memoryview(bytes(data))
        self.pos = 0
        self.size = len(self.data)
        self.bit_pos = 0

    def seek(self, pos, whence=0):
        if whence == 0:
            self.pos = pos
        elif whence == 1:
            self.pos += pos
        elif whence == 2:
            self.pos = self.size + pos
        self.bit_pos = 0

    def tell(self):
        return self.pos

    def get_size(self):
        return self.size

    def read_bytes(self, count):
        val = bytes(self.data[self.pos : self.pos + count])
        self.pos += count
        return val

    def read_uint(self):
        val = struct.unpack_from('<I', self.data, self.pos)[0]
        self.pos += 4
        return val

    def read_int(self):
        val = struct.unpack_from('<i', self.data, self.pos)[0]
        self.pos += 4
        return val

    def read_ushort(self):
        val = struct.unpack_from('<H', self.data, self.pos)[0]
        self.pos += 2
        return val

    def read_short(self):
        val = struct.unpack_from('<h', self.data, self.pos)[0]
        self.pos += 2
        return val

    def read_ubyte(self):
        val = self.data[self.pos]
        self.pos += 1
        return val

    def read_byte(self):
        val = struct.unpack_from('<b', self.data, self.pos)[0]
        self.pos += 1
        return val

    def read_uint64(self):
        val = struct.unpack_from('<Q', self.data, self.pos)[0]
        self.pos += 8
        return val

    def read_int64(self):
        val = struct.unpack_from('<q', self.data, self.pos)[0]
        self.pos += 8
        return val

    def read_float(self):
        val = struct.unpack_from('<f', self.data, self.pos)[0]
        self.pos += 4
        return val

    def read_double(self):
        val = struct.unpack_from('<d', self.data, self.pos)[0]
        self.pos += 8
        return val

    def read_half(self):
        val = struct.unpack_from('<e', self.data, self.pos)[0]
        self.pos += 2
        return val

    def read_string(self):
        """Read a null-terminated ASCII/UTF-8 string."""
        p = self.pos
        while p < self.size and self.data[p] != 0:
            p += 1
        res = bytes(self.data[self.pos : p]).decode('utf-8', errors='ignore')
        self.pos = p + 1
        return res

    def read_unicode_string(self):
        """Read a null-terminated UTF-16LE string."""
        chars = []
        p = self.pos
        while p + 1 < self.size:
            ch = struct.unpack_from('<H', self.data, p)[0]
            if ch == 0:
                p += 2
                break
            chars.append(chr(ch))
            p += 2
        self.pos = p
        return ''.join(chars)

    def read_unicode_string_at(self, offset):
        old_pos = self.pos
        self.seek(offset)
        res = self.read_unicode_string()
        self.seek(old_pos)
        return res

    def read_string_at(self, offset):
        old_pos = self.pos
        self.seek(offset)
        res = self.read_string()
        self.seek(old_pos)
        return res

    def read_uint_at(self, offset):
        return struct.unpack_from('<I', self.data, offset)[0]

    def read_ushort_at(self, offset):
        return struct.unpack_from('<H', self.data, offset)[0]

    def read_uint64_at(self, offset):
        return struct.unpack_from('<Q', self.data, offset)[0]

    def read_short_at(self, offset):
        return struct.unpack_from('<h', self.data, offset)[0]

    def read_byte_at(self, offset):
        return struct.unpack_from('<b', self.data, offset)[0]

    def read_ubyte_at(self, offset):
        return self.data[offset]

    def read_float_at(self, offset):
        return struct.unpack_from('<f', self.data, offset)[0]

    def skip_to_next_16_byte_boundary(self):
        rem = self.pos % 16
        if rem != 0:
            self.pos += 16 - rem
