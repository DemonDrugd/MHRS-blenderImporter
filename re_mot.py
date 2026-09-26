# -*- coding: utf-8 -*-
"""
RE Engine MotionList (.motlist.*) Importer & Action Splitter for Blender Add-on
"""

import os
import re
import struct
import math
try:
    import bpy
    import mathutils
except ImportError:
    bpy = None
    mathutils = None

try:
    from .re_bitstream import (
        BinaryReader,
        hash_wide,
        read_packed_bits_vec3,
        convert_bits,
        w_rot,
    )
except ImportError:
    from re_bitstream import (
        BinaryReader,
        hash_wide,
        read_packed_bits_vec3,
        convert_bits,
        w_rot,
    )


class UnpackVec:
    def __init__(self, x=0.0, y=0.0, z=0.0, w=0.0):
        self.x = x
        self.y = y
        self.z = z
        self.w = w


class Unpacks:
    def __init__(self, max_v=None, min_v=None):
        self.max = max_v or UnpackVec()
        self.min = min_v or UnpackVec()


class BoneHeader:
    def __init__(self, name, pos, rot, index, parent_index, bone_hash):
        self.name = name
        self.pos = pos
        self.rot = rot
        self.index = index
        self.parent_index = parent_index
        self.bone_hash = bone_hash


class BoneTrack:
    def __init__(self, flags, key_count, frame_ind_offs, frame_data_offs, unpack_data_offs):
        self.flags = flags
        self.key_count = key_count
        self.frame_ind_offs = frame_ind_offs
        self.frame_data_offs = frame_data_offs
        self.unpack_data_offs = unpack_data_offs


def read_frame_value(bs, ftype, flags, unpacks, version=528, scale=1.0):
    compression = flags & 0xFF000

    if ftype in ("pos", "scl"):
        s = scale if ftype == "pos" else 1.0
        if compression == 0x00000:
            val = (bs.read_float(), bs.read_float(), bs.read_float())
        elif compression == 0x20000:
            raw = read_packed_bits_vec3(bs.read_ushort(), 5)
            if version <= 65:
                val = (
                    unpacks.max.x * raw[0] + unpacks.min.x,
                    unpacks.max.y * raw[1] + unpacks.min.z,
                    unpacks.max.y * raw[2] + unpacks.min.z,
                )
            else:
                val = (
                    unpacks.max.x * raw[0] + unpacks.max.w,
                    unpacks.max.y * raw[1] + unpacks.min.x,
                    unpacks.max.z * raw[2] + unpacks.min.y,
                )
        elif compression == 0x24000:
            v = unpacks.max.x * convert_bits(bs.read_ushort(), 16) + unpacks.min.x
            val = (v, v, v)
        elif compression == 0x44000:
            v = unpacks.max.x * bs.read_float() + unpacks.min.x
            val = (v, v, v)
        elif compression in (0x40000, 0x30000):
            raw = read_packed_bits_vec3(bs.read_uint(), 10)
            if version <= 65:
                val = (
                    unpacks.max.x * raw[0] + unpacks.min.x,
                    unpacks.max.y * raw[1] + unpacks.min.y,
                    unpacks.max.z * raw[2] + unpacks.min.z,
                )
            else:
                val = (
                    unpacks.max.x * raw[0] + unpacks.max.w,
                    unpacks.max.y * raw[1] + unpacks.min.x,
                    unpacks.max.z * raw[2] + unpacks.min.y,
                )
        elif compression == 0x70000:
            raw = read_packed_bits_vec3(bs.read_uint64(), 21)
            val = (
                unpacks.max.x * raw[0] + unpacks.min.x,
                unpacks.max.y * raw[1] + unpacks.min.y,
                unpacks.max.z * raw[2] + unpacks.min.z,
            )
        elif compression == 0x80000:
            raw = read_packed_bits_vec3(bs.read_uint64(), 21)
            val = (
                unpacks.max.x * raw[0] + unpacks.max.w,
                unpacks.max.y * raw[1] + unpacks.min.x,
                unpacks.max.z * raw[2] + unpacks.min.y,
            )
        elif compression in (0x31000, 0x41000):
            val = (bs.read_float(), unpacks.max.y, unpacks.max.z)
        elif compression in (0x32000, 0x42000):
            val = (unpacks.max.x, bs.read_float(), unpacks.max.z)
        elif compression in (0x33000, 0x43000):
            val = (unpacks.max.x, unpacks.max.y, bs.read_float())
        elif compression == 0x21000:
            val = (unpacks.max.x * convert_bits(bs.read_ushort(), 16) + unpacks.max.y, unpacks.max.z, unpacks.max.w)
        elif compression == 0x22000:
            val = (unpacks.max.y, unpacks.max.x * convert_bits(bs.read_ushort(), 16) + unpacks.max.z, unpacks.max.w)
        elif compression == 0x23000:
            val = (unpacks.max.y, unpacks.max.z, unpacks.max.x * convert_bits(bs.read_ushort(), 16) + unpacks.max.w)
        else:
            val = (0.0, 0.0, 0.0) if ftype == "pos" else (1.0, 1.0, 1.0)
        return (val[0] * s, val[1] * s, val[2] * s)

    elif ftype == "rot":
        # Returns mathutils.Quaternion (w, x, y, z)
        if compression == 0x00000:
            x, y, z, w = bs.read_float(), bs.read_float(), bs.read_float(), bs.read_float()
            return mathutils.Quaternion((w, x, y, z))
        elif compression in (0xB0000, 0xC0000):
            xyz = (bs.read_float(), bs.read_float(), bs.read_float())
            w = w_rot(xyz)
            return mathutils.Quaternion((w, xyz[0], xyz[1], xyz[2]))
        elif compression == 0x20000:
            raw = read_packed_bits_vec3(bs.read_ushort(), 5)
            xyz = (
                unpacks.max.x * raw[0] + unpacks.min.x,
                unpacks.max.y * raw[1] + unpacks.min.y,
                unpacks.max.z * raw[2] + unpacks.min.z,
            )
            w = w_rot(xyz)
            return mathutils.Quaternion((w, xyz[0], xyz[1], xyz[2]))
        elif compression == 0x21000:
            xyz = (unpacks.max.x * convert_bits(bs.read_ushort(), 16) + unpacks.max.y, 0.0, 0.0)
            return mathutils.Quaternion((w_rot(xyz), xyz[0], xyz[1], xyz[2]))
        elif compression == 0x22000:
            xyz = (0.0, unpacks.max.x * convert_bits(bs.read_ushort(), 16) + unpacks.max.y, 0.0)
            return mathutils.Quaternion((w_rot(xyz), xyz[0], xyz[1], xyz[2]))
        elif compression == 0x23000:
            xyz = (0.0, 0.0, unpacks.max.x * convert_bits(bs.read_ushort(), 16) + unpacks.max.y)
            return mathutils.Quaternion((w_rot(xyz), xyz[0], xyz[1], xyz[2]))
        elif compression == 0x30000:
            if version >= 78:
                raw = (convert_bits(bs.read_ubyte(), 8), convert_bits(bs.read_ubyte(), 8), convert_bits(bs.read_ubyte(), 8))
            else:
                raw = read_packed_bits_vec3(bs.read_uint(), 10)
            xyz = (
                unpacks.max.x * raw[0] + unpacks.min.x,
                unpacks.max.y * raw[1] + unpacks.min.y,
                unpacks.max.z * raw[2] + unpacks.min.z,
            )
            return mathutils.Quaternion((w_rot(xyz), xyz[0], xyz[1], xyz[2]))
        elif compression in (0x31000, 0x41000):
            xyz = (bs.read_float(), 0.0, 0.0)
            return mathutils.Quaternion((w_rot(xyz), xyz[0], 0.0, 0.0))
        elif compression in (0x32000, 0x42000):
            xyz = (0.0, bs.read_float(), 0.0)
            return mathutils.Quaternion((w_rot(xyz), 0.0, xyz[1], 0.0))
        elif compression in (0x33000, 0x43000):
            xyz = (0.0, 0.0, bs.read_float())
            return mathutils.Quaternion((w_rot(xyz), 0.0, 0.0, xyz[2]))
        elif compression == 0x40000:
            raw = read_packed_bits_vec3(bs.read_uint(), 10)
            xyz = (
                unpacks.max.x * raw[0] + unpacks.min.x,
                unpacks.max.y * raw[1] + unpacks.min.y,
                unpacks.max.z * raw[2] + unpacks.min.z,
            )
            return mathutils.Quaternion((w_rot(xyz), xyz[0], xyz[1], xyz[2]))
        elif compression == 0x50000 and version <= 65:
            raw = (convert_bits(bs.read_ushort(), 16), convert_bits(bs.read_ushort(), 16), convert_bits(bs.read_ushort(), 16))
            xyz = (
                unpacks.max.x * raw[0] + unpacks.min.x,
                unpacks.max.y * raw[1] + unpacks.min.y,
                unpacks.max.z * raw[2] + unpacks.min.z,
            )
            return mathutils.Quaternion((w_rot(xyz), xyz[0], xyz[1], xyz[2]))
        elif compression == 0x50000:  # 13-bit for version > 65 (Rise / Sunbreak / etc.)
            raw_bytes = [bs.read_ubyte() for _ in range(5)]
            retrieved = (raw_bytes[0] << 32) | (raw_bytes[1] << 24) | (raw_bytes[2] << 16) | (raw_bytes[3] << 8) | raw_bytes[4]
            raw = read_packed_bits_vec3(retrieved, 13)
            xyz = (
                unpacks.max.x * raw[0] + unpacks.min.x,
                unpacks.max.y * raw[1] + unpacks.min.y,
                unpacks.max.z * raw[2] + unpacks.min.z,
            )
            return mathutils.Quaternion((w_rot(xyz), xyz[0], xyz[1], xyz[2]))
        elif compression == 0x60000:
            raw = (convert_bits(bs.read_ushort(), 16), convert_bits(bs.read_ushort(), 16), convert_bits(bs.read_ushort(), 16))
            xyz = (
                unpacks.max.x * raw[0] + unpacks.min.x,
                unpacks.max.y * raw[1] + unpacks.min.y,
                unpacks.max.z * raw[2] + unpacks.min.z,
            )
            return mathutils.Quaternion((w_rot(xyz), xyz[0], xyz[1], xyz[2]))
        elif compression == 0x70000 and version >= 78:  # 18-bit (7 bytes) for version >= 78
            raw_bytes = [bs.read_ubyte() for _ in range(7)]
            retrieved = (
                (raw_bytes[0] << 48)
                | (raw_bytes[1] << 40)
                | (raw_bytes[2] << 32)
                | (raw_bytes[3] << 24)
                | (raw_bytes[4] << 16)
                | (raw_bytes[5] << 8)
                | raw_bytes[6]
            )
            raw = read_packed_bits_vec3(retrieved, 18)
            xyz = (
                unpacks.max.x * raw[0] + unpacks.min.x,
                unpacks.max.y * raw[1] + unpacks.min.y,
                unpacks.max.z * raw[2] + unpacks.min.z,
            )
            return mathutils.Quaternion((w_rot(xyz), xyz[0], xyz[1], xyz[2]))
        elif (compression == 0x70000 and version <= 65) or (compression == 0x80000 and version >= 78):
            raw = read_packed_bits_vec3(bs.read_uint64(), 21)
            xyz = (
                unpacks.max.x * raw[0] + unpacks.min.x,
                unpacks.max.y * raw[1] + unpacks.min.y,
                unpacks.max.z * raw[2] + unpacks.min.z,
            )
            return mathutils.Quaternion((w_rot(xyz), xyz[0], xyz[1], xyz[2]))
        else:
            return mathutils.Quaternion((1.0, 0.0, 0.0, 0.0))


class REMot:
    def __init__(self, raw_data, mot_address, motlist_parent):
        self.address = mot_address
        self.motlist = motlist_parent
        self.bs = BinaryReader(raw_data[mot_address:])
        bs = self.bs

        self.version = bs.read_uint()
        bs.seek(12)
        self.mot_size = bs.read_uint()
        self.offs_to_bone_hdr_offs = bs.read_uint64()
        self.bone_hdr_offset = 0
        self.bone_clip_hdr_offset = bs.read_uint64()

        bs.seek(8, 1)
        if self.version >= 456:
            bs.seek(8, 1)
            clip_file_offs = bs.read_uint64()
            jmap_offs = bs.read_uint64()
            ex_data_offs = bs.read_uint64()
            bs.seek(16, 1)
        else:
            jmap_offs = bs.read_uint64()
            clip_file_offs = bs.read_uint64()
            bs.seek(16, 1)
            ex_data_offs = bs.read_uint64()

        name_offs = bs.read_uint64()
        self.name = bs.read_unicode_string_at(name_offs)
        self.frame_count = bs.read_float()
        self.blending = bs.read_float()
        self.ukn0 = bs.read_float()
        self.ukn1 = bs.read_float()
        self.bone_count = bs.read_short()
        self.bone_clip_count = bs.read_short()
        if self.bone_clip_count < 0:
            self.bone_clip_count &= 0xFFFF
        self.clip_count = bs.read_byte()
        self.ukn_count = bs.read_byte()
        self.frame_rate = bs.read_short()

        self.bone_headers = []

    def read_bone_headers(self):
        if self.offs_to_bone_hdr_offs:
            self.bs.seek(self.offs_to_bone_hdr_offs)
            bone_hdr_offs = self.bs.read_uint64()
            count = self.bs.read_uint64()
            if bone_hdr_offs and count > 0:
                for i in range(count):
                    self.bs.seek(bone_hdr_offs + 80 * i)
                    b_name_offs = self.bs.read_uint64()
                    b_name = self.bs.read_unicode_string_at(b_name_offs)
                    p_offs = self.bs.read_uint64()
                    p_idx = int((p_offs - bone_hdr_offs) // 80) if p_offs else -1
                    self.bs.seek(16, 1)
                    tx, ty, tz, tw = struct.unpack_from('<4f', self.bs.data, self.bs.tell())
                    self.bs.seek(16, 1)
                    qx, qy, qz, qw = struct.unpack_from('<4f', self.bs.data, self.bs.tell())
                    self.bs.seek(16, 1)
                    idx = self.bs.read_uint()
                    b_hash = self.bs.read_uint()
                    self.bone_headers.append(BoneHeader(b_name, (tx, ty, tz), (qw, qx, qy, qz), idx, p_idx, b_hash))
                return True
        return False

    def parse_animation_tracks(self, scale=1.0, force_center=False):
        """
        Parses all bone tracks and keyframes for this motion.
        Returns: dict mapping bone_hash -> {
            'pos': [(frame, (x, y, z)), ...],
            'rot': [(frame, mathutils.Quaternion), ...],
            'scl': [(frame, (x, y, z)), ...]
        }
        """
        bs = self.bs
        clip_count = self.bone_clip_count
        bn_clip_sz = 12

        motion_data = {}

        for i in range(clip_count):
            bs.seek(self.bone_clip_hdr_offset + bn_clip_sz * i)
            b_idx = bs.read_ushort()
            track_flags = bs.read_ushort()
            bone_hash = bs.read_uint()
            track_hdr_offs = bs.read_uint()

            tracks = {}
            bs.seek(track_hdr_offs)
            for t_idx, t_name in enumerate(["pos", "rot", "scl"]):
                if track_flags & (1 << t_idx):
                    flags = bs.read_uint()
                    key_count = bs.read_uint()
                    frame_ind_offs = bs.read_uint()
                    frame_data_offs = bs.read_uint()
                    unpack_data_offs = bs.read_uint()
                    tracks[t_name] = BoneTrack(flags, key_count, frame_ind_offs, frame_data_offs, unpack_data_offs)

            bone_keys = {"pos": [], "rot": [], "scl": []}

            for t_name in ["pos", "rot", "scl"]:
                track = tracks.get(t_name)
                if not track or track.key_count == 0:
                    continue

                if force_center and t_name == "pos" and (i == 0 or b_idx == 0):
                    continue

                # Read frame times
                key_comp = track.flags >> 20
                bs.seek(track.frame_ind_offs)
                key_times = []
                for k in range(track.key_count):
                    if not track.frame_ind_offs:
                        key_times.append(0.0)
                    elif key_comp == 5:
                        key_times.append(float(bs.read_uint()))
                    elif key_comp == 2:
                        key_times.append(float(bs.read_ubyte()))
                    else:
                        key_times.append(float(bs.read_ushort()))

                # Read unpacks
                if track.unpack_data_offs:
                    bs.seek(track.unpack_data_offs)
                    max_raw = struct.unpack_from('<4f', bs.data, bs.tell())
                    bs.seek(16, 1)
                    min_raw = struct.unpack_from('<4f', bs.data, bs.tell())
                    unpacks = Unpacks(UnpackVec(*max_raw), UnpackVec(*min_raw))
                else:
                    unpacks = Unpacks()

                # Read frame values
                bs.seek(track.frame_data_offs)
                for f_idx in range(track.key_count):
                    f_time = key_times[f_idx]
                    f_val = read_frame_value(bs, t_name, track.flags, unpacks, version=self.version, scale=scale)
                    bone_keys[t_name].append((f_time, f_val))

            motion_data[bone_hash] = bone_keys

        return motion_data

    def parse_vis_tracks(self):
        """
        Parses all visibility/part-cycling tracks (e.g. WingVis, LegVis, LegsVis, BeakVis) from this motion.
        Returns: dict mapping track_name -> list of (frame_time, target_group_id)
        """
        if not hasattr(self.motlist, 'raw_data'):
            return {}

        bs_data = self.motlist.raw_data
        mot_base = self.address

        if len(bs_data) < mot_base + 64:
            return {}

        if self.version >= 456:
            jmap_offs = struct.unpack_from('<Q', bs_data, mot_base + 48)[0]
        else:
            jmap_offs = struct.unpack_from('<Q', bs_data, mot_base + 32)[0]

        if not jmap_offs or mot_base + jmap_offs + 64 > len(bs_data):
            return {}

        vis_tracks = {}

        for j_idx in range(1, 16):
            ptr_offs = mot_base + jmap_offs + j_idx * 8
            if ptr_offs + 8 > len(bs_data):
                break
            clip_rel = struct.unpack_from('<Q', bs_data, ptr_offs)[0]
            if not clip_rel or clip_rel > len(bs_data):
                continue
            clip_abs = mot_base + clip_rel
            if clip_abs + 48 > len(bs_data):
                continue

            if bs_data[clip_abs:clip_abs+4] != b'CLIP':
                continue

            magic, ver, end_frame, num_tracks, ukn, num_keys = struct.unpack_from('<4sIfIII', bs_data, clip_abs)
            if num_keys == 0:
                continue

            keys_rel = struct.unpack_from('<Q', bs_data, clip_abs + 40)[0]
            name_rel = struct.unpack_from('<Q', bs_data, clip_abs + 48)[0]

            name_abs = mot_base + name_rel
            if name_abs >= len(bs_data):
                continue

            track_name_raw = bs_data[name_abs:name_abs+64].split(b'\x00')[0]
            track_name = track_name_raw.decode('ascii', errors='ignore')
            t_lower = track_name.lower()
            if not any(k in t_lower for k in ['vis', 'disp', 'state', 'group', 'pose', 'switch', 'frame', 'mesh', 'part', 'trigger', 'se_', 'sound']):
                continue

            keys_abs = mot_base + keys_rel
            if keys_abs + num_keys * 32 > len(bs_data):
                continue

            keyframes = []
            for k in range(num_keys):
                k_offs = keys_abs + k * 32
                frame = struct.unpack_from('<f', bs_data, k_offs)[0]
                val_int = struct.unpack_from('<i', bs_data, k_offs + 16)[0]

                if 0.0 <= frame <= 10000.0:
                    keyframes.append((round(frame, 2), val_int))

            if keyframes:
                keyframes.sort(key=lambda x: x[0])
                vis_tracks[track_name] = keyframes

        return vis_tracks


class REMotlist:
    def __init__(self, filepath):
        self.filepath = filepath
        self.name = os.path.basename(filepath)
        self.mots = []
        self.bone_headers = []
        self.raw_data = b''
        self.parse()

    def parse(self):
        with open(self.filepath, 'rb') as f:
            raw_data = f.read()
        self.raw_data = raw_data

        bs = BinaryReader(raw_data)
        self.version = bs.read_int()
        pointers_offset = bs.read_uint64_at(16)
        num_offsets = bs.read_uint_at(48)
        name_offs = bs.read_uint64_at(32)
        if name_offs:
            self.name = bs.read_unicode_string_at(name_offs)

        pointers = []
        for i in range(num_offsets):
            mot_address = bs.read_uint64_at(pointers_offset + i * 8)
            if mot_address and mot_address not in pointers:
                if bs.read_uint_at(mot_address + 4) == 544501613:  # 'mot\0'
                    pointers.append(mot_address)
                    mot = REMot(raw_data, mot_address, self)
                    self.mots.append(mot)

        # Find shared bone headers
        for mot in self.mots:
            if mot.read_bone_headers():
                self.bone_headers = mot.bone_headers
                break


def get_action_fcurves(action):
    """
    Returns all fcurves from an Action across both legacy (Blender <= 4.x)
    and layered/slotted (Blender >= 5.x) Action systems.
    """
    if not action:
        return []
    if hasattr(action, 'fcurves'):
        return list(action.fcurves)
    fcurves = []
    if hasattr(action, 'layers'):
        for l in action.layers:
            for s in l.strips:
                for cb in s.channelbags:
                    fcurves.extend(cb.fcurves)
    return fcurves


def _mesh_span_x(mesh_objs):
    if not mesh_objs:
        return 0.0
    all_xs = []
    for m in mesh_objs:
        if m.data and m.data.vertices:
            all_xs.extend([v.co.x for v in m.data.vertices])
    if not all_xs:
        return 0.0
    return max(all_xs) - min(all_xs)


def find_creature_fsm(motlist_path):
    """
    Finds the motfsm2 control file associated with this creature's motion.
    E.g. for .../ec051/00/mot/ec051_00_00.motlist.528, searches parent dirs for .../ec051/fsm/*.motfsm2.*
    """
    if not motlist_path or not os.path.exists(motlist_path):
        return None
    curr = os.path.dirname(os.path.abspath(motlist_path))
    for _ in range(4):
        fsm_dir = os.path.join(curr, 'fsm')
        if os.path.isdir(fsm_dir):
            for f in os.listdir(fsm_dir):
                if 'motfsm' in f.lower() or 'fsm' in f.lower():
                    return os.path.join(fsm_dir, f)
        parent = os.path.dirname(curr)
        if parent == curr:
            break
        curr = parent
    return None


def parse_motfsm2(fsm_path):
    """
    Parses state and action names from an RE Engine .motfsm2 control file.
    Returns: dict with 'version' and 'states' list.
    """
    if not fsm_path or not os.path.exists(fsm_path):
        return None
    try:
        with open(fsm_path, 'rb') as f:
            data = f.read()
        if len(data) < 64:
            return None
        ver, magic = struct.unpack_from('<I4s', data, 0)
        if magic != b'mfs2':
            return None
        raw_strs = re.findall(b'(?:[\x20-\x7e]\x00){3,}', data)
        states = []
        for s_bytes in raw_strs:
            name = s_bytes.decode('utf-16le', errors='ignore').strip()
            if name and name not in states and len(name) >= 3 and not name.startswith('#'):
                states.append(name)
        return {'version': ver, 'states': states}
    except Exception as e:
        print(f"[RE Mot] Warning: Failed to parse FSM {fsm_path}: {e}")
        return None


def get_model_parts(mesh_by_gid, arm_obj=None):
    """
    Partitions submesh groups (0 < gid < 100) into distinct anatomical parts.
    Returns: list of dicts with keys:
        'prop_name': str,       # Armature property name, e.g. 'vis_0', 'vis_1', 'vis_10'
        'gids': list of int,    # Group IDs belonging to this part, e.g. [1, 2] or [3, 4]
        'default_gid': int,     # Rest / default visible group ID
        'is_wings': bool,       # True if this part represents flapping wings (insects / non-skeletal)
        'is_skeletal_bird': bool # True if creature has skeletal wing bones
    """
    valid_gids = sorted([gid for gid in mesh_by_gid if 0 < gid < 100])
    if not valid_gids:
        return []

    # Detect if this creature has skeletal wing bones (e.g. ec018, ec030, ec031, ec032, ec033, ec051)
    has_wing_bones = False
    if arm_obj and hasattr(arm_obj, 'data') and hasattr(arm_obj.data, 'bones'):
        wing_bone_count = sum(1 for b in arm_obj.data.bones if 'wing' in b.name.lower())
        has_wing_bones = (wing_bone_count >= 2)

    d0_gids = [g for g in valid_gids if g < 10]
    parts = []

    if has_wing_bones:
        # Skeletal Bird (ec018, ec030, ec031, ec032, ec033, ec051, etc.):
        # In birds, Group 1 is Spread Wings (Flight) and Group 2 is Folded Wings (Ground/Rest).
        # Group 10/11 is Beak (10 Closed Beak, 11 Open Beak).
        # Group 12+ are independent accessories (e.g. leaf held in ec033's beak).
        # Group 20/21 is Feet (20 Ground Standing, 21 Air Tucked).
        # Their wings flap via bone animation, NOT by rapid multi-frame mesh cycling!
        if d0_gids:
            wing_gids = [g for g in d0_gids if g > 0]
            def_gid = 2 if 2 in wing_gids else (wing_gids[0] if wing_gids else 0)
            parts.append({
                'prop_name': 'vis_0',
                'gids': wing_gids if wing_gids else d0_gids,
                'default_gid': def_gid,
                'is_wings': False,
                'is_skeletal_bird': True
            })

        other_decades = sorted(list(set(g // 10 for g in valid_gids if g >= 10)))
        for d in other_decades:
            g_list = sorted([g for g in valid_gids if g // 10 == d])
            if d == 1:
                # Decade 1 (Beak decade):
                # Standard beak pair is strictly [10, 11] (10 Closed, 11 Open)
                if 10 in g_list and 11 in g_list:
                    parts.append({
                        'prop_name': 'vis_1',
                        'gids': [10, 11],
                        'default_gid': 10,
                        'is_wings': False,
                        'is_skeletal_bird': True,
                        'is_beak': True,
                    })
                elif 10 in g_list:
                    # Single beak without open mouth mesh (e.g. ec033)
                    parts.append({
                        'prop_name': 'vis_1',
                        'gids': [10],
                        'default_gid': 10,
                        'is_wings': False,
                        'is_skeletal_bird': True,
                        'is_beak': False,
                    })
                # Any other groups in decade 1 (like 12: leaf held in ec033's beak) are accessories!
                # They must NOT be toggled by beak drivers!
                for extra_g in g_list:
                    if extra_g not in (10, 11):
                        parts.append({
                            'prop_name': f'vis_{extra_g}',
                            'gids': [extra_g],
                            'default_gid': extra_g,
                            'is_wings': False,
                            'is_skeletal_bird': True,
                            'is_accessory': True,
                        })
            elif d == 2:
                # Decade 2 (Feet decade):
                # 20 = Standing, 21 = Air Tucked
                def_gid = 20 if 20 in g_list else g_list[0]
                parts.append({
                    'prop_name': 'vis_2',
                    'gids': g_list,
                    'default_gid': def_gid,
                    'is_wings': False,
                    'is_skeletal_bird': True,
                    'is_feet': True,
                })
            else:
                parts.append({
                    'prop_name': f'vis_{d}',
                    'gids': g_list,
                    'default_gid': g_list[0],
                    'is_wings': False,
                    'is_skeletal_bird': True,
                })

        return parts

    # Check if decade 0 has multiple distinct anatomical parts (e.g. ec009 where 1,2=wings and 3,4=head crest)
    if set(d0_gids) == {1, 2, 3, 4}:
        w1 = _mesh_span_x(mesh_by_gid.get(1, []))
        w3 = _mesh_span_x(mesh_by_gid.get(3, []))
        ratio = (w1 + 1e-4) / (w3 + 1e-4)
        if ratio > 3.0 or ratio < 0.33:
            # 1, 2 is Part A (Wings), 3, 4 is Part B (Head Crest)
            parts.append({
                'prop_name': 'vis_0',
                'gids': [1, 2],
                'default_gid': 1,
                'is_wings': True
            })
            parts.append({
                'prop_name': 'vis_1',
                'gids': [3, 4],
                'default_gid': 3,
                'is_wings': False
            })
        else:
            parts.append({
                'prop_name': 'vis_0',
                'gids': [1, 2, 3, 4],
                'default_gid': 1,
                'is_wings': True
            })
    elif d0_gids:
        sub_names = [m.name.lower() for g in d0_gids for m in mesh_by_gid.get(g, [])]
        is_wings = any(any(k in sn for k in ['wing', 'chou', 'mushi', 'fly', 'feather', 'twoside']) for sn in sub_names)
        if len(d0_gids) >= 4:
            is_wings = True
        parts.append({
            'prop_name': 'vis_0',
            'gids': d0_gids,
            'default_gid': d0_gids[0],
            'is_wings': is_wings
        })

    other_decades = sorted(list(set(g // 10 for g in valid_gids if g >= 10)))
    for d in other_decades:
        g_list = [g for g in valid_gids if g // 10 == d]
        sub_names = [m.name.lower() for g in g_list for m in mesh_by_gid.get(g, [])]
        is_wings = any(any(k in sn for k in ['wing', 'chou', 'mushi', 'fly', 'feather', 'twoside']) for sn in sub_names)
        if len(g_list) >= 3:
            is_wings = True
        parts.append({
            'prop_name': f'vis_{d}',
            'gids': g_list,
            'default_gid': g_list[0],
            'is_wings': is_wings
        })

    return parts


def setup_mesh_visibility_drivers(arm_obj, child_meshes):
    """
    Sets up Blender drivers on child meshes for multi-frame environment creature parts.
    Drives hide_viewport, hide_render, and scale based on custom properties on the Armature.
    """
    if not arm_obj or not child_meshes or not bpy:
        return

    mesh_by_gid = {}
    for m_obj in child_meshes:
        m = re.search(r'_Group_(\d+)_', m_obj.name)
        if m:
            gid = int(m.group(1))
            mesh_by_gid.setdefault(gid, []).append(m_obj)

    parts = get_model_parts(mesh_by_gid, arm_obj)

    for p in parts:
        prop_name = p['prop_name']
        default_gid = p['default_gid']

        if prop_name not in arm_obj:
            arm_obj[prop_name] = float(default_gid)

        for gid in p['gids']:
            for m_obj in mesh_by_gid.get(gid, []):
                # Clear any lingering action on child mesh so drivers have full control
                if m_obj.animation_data and m_obj.animation_data.action:
                    m_obj.animation_data.action = None

                # Make sure Outliner eye is open
                m_obj.hide_set(False)

                # 1. Drive hide_viewport and hide_render
                for attr in ['hide_viewport', 'hide_render']:
                    m_obj.driver_remove(attr)
                    fcurve = m_obj.driver_add(attr)
                    drv = fcurve.driver
                    drv.type = 'SCRIPTED'
                    while drv.variables:
                        drv.variables.remove(drv.variables[0])
                    var = drv.variables.new()
                    var.name = 'vis'
                    var.type = 'SINGLE_PROP'
                    var.targets[0].id = arm_obj
                    var.targets[0].data_path = f'["{prop_name}"]'
                    drv.expression = f'vis != {gid}.0'

                # 2. Drive scale to 0.0 when hidden to guarantee real-time viewport redraw in all Blender versions
                for s_idx in [0, 1, 2]:
                    m_obj.driver_remove('scale', s_idx)
                    fcurve = m_obj.driver_add('scale', s_idx)
                    drv = fcurve.driver
                    drv.type = 'SCRIPTED'
                    while drv.variables:
                        drv.variables.remove(drv.variables[0])
                    var = drv.variables.new()
                    var.name = 'vis'
                    var.type = 'SINGLE_PROP'
                    var.targets[0].id = arm_obj
                    var.targets[0].data_path = f'["{prop_name}"]'
                    drv.expression = f'1.0 if vis == {gid}.0 else 0.0'

    if arm_obj:
        arm_obj.update_tag()
    if bpy.context and hasattr(bpy.context, 'view_layer') and bpy.context.view_layer:
        try:
            bpy.context.view_layer.update()
        except Exception:
            pass



def apply_motion_to_armature(arm_obj, mot, scale=1.0, force_center=False, enable_vis_control=True):
    """
    Bakes a REMot into a new Blender Action on the given Armature.
    - enable_vis_control: If True, automatically creates visibility drivers and keyframes
      multi-frame polygon states for creatures (wings, feet, beak, etc.).
      If False, all polygon meshes remain normally visible without automated drivers,
      allowing the user to manually control or adjust them in Blender.
    """
    if not arm_obj or arm_obj.type != 'ARMATURE':
        return None

    action_name = mot.name
    # Create or replace Action
    action = bpy.data.actions.get(action_name)
    if not action:
        action = bpy.data.actions.new(name=action_name)
    else:
        # Clear existing fcurves to ensure clean bake without stale keys
        action.fcurves.clear()

    if not arm_obj.animation_data:
        arm_obj.animation_data_create()
    arm_obj.animation_data.action = action

    # Discover and read creature FSM control file if present
    motlist_path = mot.motlist.filepath if hasattr(mot, 'motlist') and mot.motlist else None
    fsm_path = find_creature_fsm(motlist_path)
    if fsm_path:
        fsm_info = parse_motfsm2(fsm_path)
        if fsm_info:
            print(f"[RE Mot] Referenced FSM control file: {os.path.basename(fsm_path)} ({len(fsm_info['states'])} states)")

    # Map bone hashes to pose bones
    bone_hash_map = {}
    for pb in arm_obj.pose.bones:
        b_hash = hash_wide(pb.name, get_unsigned=True)
        bone_hash_map[b_hash] = pb

    motion_tracks = mot.parse_animation_tracks(scale=scale, force_center=force_center)

    for b_hash, keys in motion_tracks.items():
        pb = bone_hash_map.get(b_hash)
        if not pb:
            continue

        pb.rotation_mode = 'QUATERNION'

        # Compute rest transform L_rest in parent bone space
        b = arm_obj.data.bones[pb.name]
        if b.parent:
            L_rest = b.parent.matrix_local.inverted() @ b.matrix_local
        else:
            L_rest = b.matrix_local

        T_rest = L_rest.to_translation()
        R_rest = L_rest.to_quaternion()
        R_rest_inv = R_rest.inverted()

        # Insert Rotation Keyframes (delta rotation from rest)
        # Enforce quaternion antipodal hemisphere continuity to prevent 180-degree flipping during interpolation
        prev_delta_q = None
        for frame_time, quat in keys['rot']:
            delta_q = R_rest_inv @ quat
            if prev_delta_q is not None and prev_delta_q.dot(delta_q) < 0.0:
                delta_q = -delta_q
            prev_delta_q = delta_q
            pb.rotation_quaternion = delta_q
            pb.keyframe_insert(data_path='rotation_quaternion', frame=frame_time)

        # Insert Translation Keyframes (delta translation from rest in bone rest frame)
        for frame_time, pos in keys['pos']:
            pb.location = R_rest_inv @ (mathutils.Vector(pos) - T_rest)
            pb.keyframe_insert(data_path='location', frame=frame_time)

        # Insert Scale Keyframes
        for frame_time, scl in keys['scl']:
            pb.scale = mathutils.Vector(scl)
            pb.keyframe_insert(data_path='scale', frame=frame_time)

    # Apply Visibility / Multi-frame Part Animation via Armature Property Drivers
    child_meshes = [c for c in arm_obj.children if c.type == 'MESH'] if arm_obj else []

    if not enable_vis_control:
        # User opted out of programmatic creature visibility control.
        # Ensure all polygon parts are normally visible and unconstrained by drivers
        # so the user can freely inspect, toggle, and keyframe them manually in Blender.
        for m_obj in child_meshes:
            if m_obj.animation_data:
                for d in list(m_obj.animation_data.drivers):
                    if d.data_path in ('hide_viewport', 'hide_render'):
                        m_obj.animation_data.drivers.remove(d)
            m_obj.hide_viewport = False
            m_obj.hide_render = False
        return action

    vis_tracks = mot.parse_vis_tracks()

    mesh_by_gid = {}
    for m_obj in child_meshes:
        m = re.search(r'_Group_(\d+)_', m_obj.name)
        if m:
            gid = int(m.group(1))
            mesh_by_gid.setdefault(gid, []).append(m_obj)

    active_decades = set(gid // 10 for gid in mesh_by_gid if 0 < gid < 100)

    # Ensure drivers are set up on child meshes
    if child_meshes and active_decades:
        setup_mesh_visibility_drivers(arm_obj, child_meshes)

    parts = get_model_parts(mesh_by_gid, arm_obj)

    # If child meshes are not yet imported, deduce fallback parts from vis_tracks
    if not parts and vis_tracks:
        seen_gids = set()
        for track_name, kfs in vis_tracks.items():
            for _, target_gid in kfs:
                if target_gid > 0 and target_gid not in seen_gids:
                    seen_gids.add(target_gid)
                    parts.append({
                        'prop_name': f'vis_{target_gid // 10}',
                        'gids': [target_gid],
                        'default_gid': target_gid,
                        'is_wings': False
                    })

    end_frame = float(mot.frame_count) if mot.frame_count > 0 else 0.0

    if parts and action:
        for part_info in parts:
            prop_name = part_info['prop_name']
            data_path = f'["{prop_name}"]'
            gids = part_info['gids']
            default_gid = part_info['default_gid']
            is_wings = part_info['is_wings']
            n_poses = len(gids)

            if arm_obj and prop_name not in arm_obj:
                arm_obj[prop_name] = float(default_gid)

            # Match explicit CLIP keyframes whose target_gid falls in this part
            part_kfs = []
            if vis_tracks:
                for track_name, kfs in vis_tracks.items():
                    for f_time, target_gid in kfs:
                        if target_gid in gids:
                            part_kfs.append((f_time, target_gid))

            if part_kfs:
                # 1. Authentic explicit CLIP track keyframes found in motion file!
                sorted_kfs = sorted(part_kfs, key=lambda x: x[0])
                bake_kfs = list(sorted_kfs)
                if bake_kfs[0][0] > 0.0:
                    bake_kfs.insert(0, (0.0, bake_kfs[0][1]))
                if end_frame > 0.0 and bake_kfs[-1][0] < end_frame:
                    bake_kfs.append((end_frame, bake_kfs[-1][1]))

                for f_time, gid_val in bake_kfs:
                    arm_obj[prop_name] = float(gid_val)
                    arm_obj.keyframe_insert(data_path=data_path, frame=f_time)
            elif part_info.get('is_skeletal_bird'):
                # 2. Skeletal Bird (ec018, ec030, ec031, ec032, ec033, ec051):
                # Dynamically evaluate flight wings, feet posture, and beak opening independently!
                # Wing opening and feet tucking are NOT forcibly bound (e.g. bird can stand with wings open)!
                mot_lower = mot.name.lower()

                # A. Dynamic wing posture timeline from wing bone tracks (vis_0: 1 spread, 2 folded)
                wing_pb = (arm_obj.pose.bones.get('R_Wing_01') or 
                           arm_obj.pose.bones.get('L_Wing_01') or 
                           arm_obj.pose.bones.get('R_Wing_00') or 
                           arm_obj.pose.bones.get('L_Wing_00'))
                wing_rot_keys = []
                if wing_pb:
                    w_hash = hash_wide(wing_pb.name, get_unsigned=True)
                    wing_rot_keys = motion_tracks.get(w_hash, {}).get('rot', [])

                wing_timeline = []
                if wing_rot_keys:
                    last_st = None
                    for f_time, q in wing_rot_keys:
                        st = 'OPEN' if abs(q.w) >= 0.82 else 'FOLDED'
                        if st != last_st:
                            wing_timeline.append((f_time, st))
                            last_st = st
                else:
                    is_flight = any(k in mot_lower for k in ['fly', 'hover', 'glide', 'soar', 'dive', 'air'])
                    wing_timeline = [(0.0, 'OPEN' if is_flight else 'FOLDED')]

                if wing_timeline and wing_timeline[0][0] > 0.0:
                    wing_timeline.insert(0, (0.0, wing_timeline[0][1]))
                if end_frame > 0.0 and wing_timeline and wing_timeline[-1][0] < end_frame:
                    wing_timeline.append((end_frame, wing_timeline[-1][1]))

                # B. Dynamic feet posture timeline (vis_2: 20 standing, 21 tucked): NOT bound to wings!
                # A bird can stand on ground (vis_2 = 20) with wings spread open (vis_0 = 1)!
                cog_pb = arm_obj.pose.bones.get('Cog') or arm_obj.pose.bones.get('Root')
                cog_pos_keys = []
                if cog_pb:
                    c_hash = hash_wide(cog_pb.name, get_unsigned=True)
                    cog_pos_keys = motion_tracks.get(c_hash, {}).get('pos', [])

                leg_pb = arm_obj.pose.bones.get('R_Leg_00') or arm_obj.pose.bones.get('L_Leg_00')
                leg_rot_keys = []
                if leg_pb:
                    l_hash = hash_wide(leg_pb.name, get_unsigned=True)
                    leg_rot_keys = motion_tracks.get(l_hash, {}).get('rot', [])

                feet_timeline = []
                if cog_pos_keys and any(pos_val[1] > 0.15 for _, pos_val in cog_pos_keys):
                    last_st = None
                    for f_time, pos_val in cog_pos_keys:
                        st = 'STANDING' if pos_val[1] >= 0.20 else 'TUCKED'
                        if st != last_st:
                            feet_timeline.append((f_time, st))
                            last_st = st
                elif leg_rot_keys:
                    last_st = None
                    for f_time, q in leg_rot_keys:
                        st = 'STANDING' if q.x >= 0.22 else 'TUCKED'
                        if st != last_st:
                            feet_timeline.append((f_time, st))
                            last_st = st
                else:
                    is_flight = any(k in mot_lower for k in ['fly', 'hover', 'glide', 'soar', 'dive', 'air'])
                    feet_timeline = [(0.0, 'TUCKED' if is_flight else 'STANDING')]

                if feet_timeline and feet_timeline[0][0] > 0.0:
                    feet_timeline.insert(0, (0.0, feet_timeline[0][1]))
                if end_frame > 0.0 and feet_timeline and feet_timeline[-1][0] < end_frame:
                    feet_timeline.append((end_frame, feet_timeline[-1][1]))

                # Set posture based on part
                if prop_name == 'vis_0':
                    # Wing posture: 1 = Flight spread wings, 0 or 2 = Ground folded wings
                    folded_gid = 0.0 if (0 in gids) else (2.0 if (2 in gids) else float(default_gid))
                    spread_gid = 1.0 if (1 in gids) else float(default_gid)
                    for f_time, st in wing_timeline:
                        val = spread_gid if st == 'OPEN' else folded_gid
                        arm_obj[prop_name] = val
                        arm_obj.keyframe_insert(data_path=data_path, frame=f_time)

                elif prop_name == 'vis_2' or part_info.get('is_feet'):
                    # Feet posture: 21 = Air tucked feet, 20 = Ground standing feet
                    standing_gid = 20.0 if (20 in gids) else float(default_gid)
                    tucked_gid = 21.0 if (21 in gids) else float(default_gid)
                    for f_time, st in feet_timeline:
                        val = tucked_gid if st == 'TUCKED' else standing_gid
                        arm_obj[prop_name] = val
                        arm_obj.keyframe_insert(data_path=data_path, frame=f_time)

                elif prop_name == 'vis_1' or part_info.get('is_beak'):
                    # Beak/Mouth posture: Group 10 = Closed, Group 11 = Open
                    if not part_info.get('is_beak') or len(gids) <= 1 or 11 not in gids:
                        arm_obj[prop_name] = float(default_gid)
                        arm_obj.keyframe_insert(data_path=data_path, frame=0.0)
                        if end_frame > 0.0:
                            arm_obj.keyframe_insert(data_path=data_path, frame=end_frame)
                        continue

                    closed_gid = float(default_gid)
                    open_gid = 11.0 if (11 in gids) else (float(gids[1]) if len(gids) > 1 else float(default_gid + 1.0))
                    open_frames = set()

                    # 1) Explicit CLIP parts track (e.g. _PartsNo in ec018_00_020)
                    if vis_tracks:
                        for t_name, kfs in vis_tracks.items():
                            tl = t_name.lower()
                            if 'part' in tl or 'beak' in tl or 'mouth' in tl:
                                for ft, val in kfs:
                                    if val == 1 or val == 11 or val == int(open_gid):
                                        open_frames.add(int(ft))

                        # 2) Explicit vocal/call trigger pairs (e.g. ec051 singing/chirping in ec051_00_043/044/045)
                        CALL_START_TRIGS = {0xed930459, 3985835097, -309132199}
                        CALL_END_TRIGS = {0x6c64f9ab, 1818556843}
                        trigs = vis_tracks.get('_TriggerId', [])
                        for i_t, (ft, val) in enumerate(trigs):
                            uval = val & 0xFFFFFFFF
                            if val in CALL_START_TRIGS or uval in CALL_START_TRIGS:
                                end_t = min(ft + 12.0, end_frame)
                                for j in range(i_t + 1, len(trigs)):
                                    nxt_f, nxt_val = trigs[j]
                                    if nxt_val in CALL_END_TRIGS or (nxt_val & 0xFFFFFFFF) in CALL_END_TRIGS:
                                        end_t = nxt_f
                                        break
                                for f in range(int(ft), int(end_t) + 1):
                                    open_frames.add(f)

                    # Group into contiguous intervals
                    intervals = []
                    sorted_frames = sorted(list(open_frames))
                    if sorted_frames:
                        start = sorted_frames[0]
                        prev = start
                        for f in sorted_frames[1:]:
                            if f <= prev + 2:
                                prev = f
                            else:
                                intervals.append((start, prev))
                                start = f
                                prev = f
                        intervals.append((start, prev))

                    # Keyframe transitions (default closed)
                    arm_obj[prop_name] = closed_gid
                    arm_obj.keyframe_insert(data_path=data_path, frame=0.0)
                    for st, en in intervals:
                        if st <= 0:
                            st = 1
                        if en < st:
                            continue
                        arm_obj[prop_name] = closed_gid
                        arm_obj.keyframe_insert(data_path=data_path, frame=float(st - 1))
                        arm_obj[prop_name] = open_gid
                        arm_obj.keyframe_insert(data_path=data_path, frame=float(st))
                        arm_obj.keyframe_insert(data_path=data_path, frame=float(en))
                        if en < end_frame:
                            arm_obj[prop_name] = closed_gid
                            arm_obj.keyframe_insert(data_path=data_path, frame=float(en + 1))
                    if end_frame > 0.0:
                        arm_obj[prop_name] = closed_gid
                        arm_obj.keyframe_insert(data_path=data_path, frame=float(end_frame))

                else:
                    hold_gid = float(default_gid)
                    arm_obj[prop_name] = hold_gid
                    arm_obj.keyframe_insert(data_path=data_path, frame=0.0)
                    if end_frame > 0.0:
                        arm_obj.keyframe_insert(data_path=data_path, frame=end_frame)
            else:
                # 3. Non-skeletal creature (insects, frogs, wirebugs) without explicit CLIP track:
                mot_lower = mot.name.lower()
                is_frozen = any(k in mot_lower for k in ['dead', 'sleep', 'down', 'stun', 'paralyze', 'freeze', 'stop'])
                is_flight_motion = any(k in mot_lower for k in ['loop', 'fly', 'hover', 'glide', 'move', 'act', 'run'])

                if is_wings and not is_frozen and is_flight_motion:
                    # Flapping wings!
                    # For 2-pose wings (like ec009 [1, 2], ec008 [1, 2]): flap between gids[0] and gids[1]!
                    # For >= 3 pose wings (like ec006 [1..5], ec020 [1..5]): cycle 1 -> 2 -> ... -> N -> 1!
                    step = max(2.0, round(11.0 / n_poses)) if n_poses >= 3 else 3.0
                    period = step * (n_poses if n_poses >= 3 else 2)
                    synth_keys = []
                    t = 0.0
                    max_t = end_frame if end_frame > 0.0 else 60.0
                    cycle_gids = gids if n_poses >= 3 else [gids[0], gids[1]]
                    while t <= max_t:
                        for p_idx, gid_val in enumerate(cycle_gids):
                            kf_t = t + p_idx * step
                            if kf_t <= max_t:
                                synth_keys.append((round(kf_t, 2), gid_val))
                        t += period
                    if not synth_keys or synth_keys[-1][0] < max_t:
                        synth_keys.append((max_t, cycle_gids[0]))

                    for f_time, gid_val in synth_keys:
                        arm_obj[prop_name] = float(gid_val)
                        arm_obj.keyframe_insert(data_path=data_path, frame=f_time)

                elif n_poses == 2 and not is_wings:
                    # 2-pose non-wing part (e.g. ec009 Head Crest [3, 4], or frills/shells):
                    # In active flight / loop: hold primary active pose (e.g. Group 3 for extended crest)!
                    # In rest / sleep / down: hold resting pose (e.g. Group 4 for folded crest)!
                    suffix = re.sub(r'^(?:[a-zA-Z]+\d+)_\d+_', '', mot_lower)
                    rest_kw = ['001', '008', '028', 'wait', 'rest', 'idle', 'land', 'sleep', 'down', 'dead']
                    is_rest = any(kw in suffix for kw in rest_kw) or is_frozen
                    hold_gid = float(gids[1] if is_rest and len(gids) > 1 else gids[0])

                    arm_obj[prop_name] = hold_gid
                    arm_obj.keyframe_insert(data_path=data_path, frame=0.0)
                    if end_frame > 0.0:
                        arm_obj.keyframe_insert(data_path=data_path, frame=end_frame)

                elif n_poses == 2 and is_wings and not is_flight_motion:
                    # 2-pose wings in non-flight motion: hold folded wings
                    hold_gid = float(gids[0])
                    arm_obj[prop_name] = hold_gid
                    arm_obj.keyframe_insert(data_path=data_path, frame=0.0)
                    if end_frame > 0.0:
                        arm_obj.keyframe_insert(data_path=data_path, frame=end_frame)

                else:
                    # Single pose or static part: hold default rest pose
                    hold_gid = float(default_gid)
                    arm_obj[prop_name] = hold_gid
                    arm_obj.keyframe_insert(data_path=data_path, frame=0.0)
                    if end_frame > 0.0:
                        arm_obj.keyframe_insert(data_path=data_path, frame=end_frame)

        # Ensure CONSTANT interpolation across all Blender versions (3.x, 4.x, 5.x)
        for fc in get_action_fcurves(action):
            if 'vis_' in fc.data_path:
                for kp in fc.keyframe_points:
                    kp.interpolation = 'CONSTANT'


    # Set scene frame range
    if mot.frame_count > 0:
        bpy.context.scene.frame_start = 0
        bpy.context.scene.frame_end = int(mot.frame_count)

    if arm_obj:
        arm_obj.update_tag()
    if bpy.context and hasattr(bpy.context, 'view_layer') and bpy.context.view_layer:
        try:
            bpy.context.view_layer.update()
        except Exception:
            pass

    return action
