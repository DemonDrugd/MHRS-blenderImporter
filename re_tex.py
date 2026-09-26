# -*- coding: utf-8 -*-
"""
RE Engine Texture (.tex) Converter & Loader for Blender Add-on
"""

import os
import struct
import bpy
try:
    from .re_bitstream import BinaryReader
except ImportError:
    from re_bitstream import BinaryReader

# DXGI Format constants
DXGI_FORMAT_BC1_UNORM = 71
DXGI_FORMAT_BC1_UNORM_SRGB = 72
DXGI_FORMAT_BC2_UNORM = 74
DXGI_FORMAT_BC2_UNORM_SRGB = 75
DXGI_FORMAT_BC3_UNORM = 77
DXGI_FORMAT_BC3_UNORM_SRGB = 78
DXGI_FORMAT_BC4_UNORM = 80
DXGI_FORMAT_BC4_SNORM = 81
DXGI_FORMAT_BC5_UNORM = 83
DXGI_FORMAT_BC5_SNORM = 84
DXGI_FORMAT_B8G8R8A8_UNORM = 87
DXGI_FORMAT_BC6H_UF16 = 95
DXGI_FORMAT_BC6H_SF16 = 96
DXGI_FORMAT_BC7_UNORM = 98
DXGI_FORMAT_BC7_UNORM_SRGB = 99


def parse_tex_file(tex_path):
    """
    Parse a RE Engine .tex.* file.
    Returns:
        dict: {
            'width': int,
            'height': int,
            'format': int,
            'version': int,
            'mip_count': int,
            'num_images': int,
            'mip0_data': bytes
        }
    """
    with open(tex_path, 'rb') as f:
        data = f.read()

    reader = BinaryReader(data)
    magic = reader.read_uint()  # 'TEX\0' -> 0x584554
    version = reader.read_uint()
    width = reader.read_ushort()
    height = reader.read_ushort()
    unk00 = reader.read_ushort()

    if version > 27:
        num_images = reader.read_ubyte()
        one_img_mip_hdr_sz = reader.read_ubyte()
        mip_count = one_img_mip_hdr_sz // 16
        pos = 32 + 8
    else:
        mip_count = reader.read_ubyte()
        num_images = reader.read_ubyte()
        pos = 32

    format_id = reader.read_uint_at(16)
    reader.seek(pos)

    # Read first mip of image 0
    mip0_offset = reader.read_uint64()
    mip0_pitch = reader.read_uint()
    mip0_size = reader.read_uint()

    mip0_bytes = bytes(data[mip0_offset : mip0_offset + mip0_size])

    return {
        'width': width,
        'height': height,
        'format': format_id,
        'version': version,
        'mip_count': mip_count,
        'num_images': num_images,
        'mip0_data': mip0_bytes,
    }


def convert_tex_to_dds(tex_path, output_path=None):
    """
    Converts a RE Engine .tex.* file to a standard DirectDraw Surface (.dds) file.
    """
    tex_info = parse_tex_file(tex_path)
    width = tex_info['width']
    height = tex_info['height']
    dxgi_fmt = tex_info['format']
    raw_bytes = tex_info['mip0_data']

    if output_path is None:
        base, _ = os.path.splitext(tex_path)
        if base.lower().endswith('.tex'):
            base = base[:-4]
        output_path = base + '.dds'

    dds_header = bytearray(128)
    dds_header[0:4] = b'DDS '

    # dwSize=124, dwFlags=0x1007 (CAPS | HEIGHT | WIDTH | PIXELFORMAT)
    # dwPitchOrLinearSize = len(raw_bytes)
    struct.pack_into('<IIIIII', dds_header, 4, 124, 0x1007, height, width, len(raw_bytes), 0)
    struct.pack_into('<I', dds_header, 28, 1)  # 1 mip map

    # DDS_PIXELFORMAT (size 32)
    # dwFlags = 0x4 (DDPF_FOURCC)
    struct.pack_into('<II', dds_header, 76, 32, 0x4)
    struct.pack_into('<I', dds_header, 108, 0x1000)  # caps: DDSCAPS_TEXTURE

    # Blender 3.6 and older DDS readers only support legacy FourCC codes (DXT1, DXT3, DXT5, ATI1, ATI2)
    # and fail with "unknown file-format" if a DX10 header is attached to standard BC1-BC5 formats.
    use_dx10 = False
    if dxgi_fmt in (70, 71, 72):
        dds_header[84:88] = b'DXT1'
    elif dxgi_fmt in (73, 74, 75):
        dds_header[84:88] = b'DXT3'
    elif dxgi_fmt in (76, 77, 78):
        dds_header[84:88] = b'DXT5'
    elif dxgi_fmt in (79, 80, 81):
        dds_header[84:88] = b'ATI1'
    elif dxgi_fmt in (82, 83, 84):
        dds_header[84:88] = b'ATI2'
    else:
        dds_header[84:88] = b'DX10'
        use_dx10 = True

    with open(output_path, 'wb') as f:
        f.write(dds_header)
        if use_dx10:
            # Blender 3.6 DDS loader does not recognize DXGI_FORMAT_BC7_UNORM_SRGB (99)
            # or DXGI_FORMAT_R8G8B8A8_UNORM_SRGB (29) in DX10 header, but fully supports
            # DXGI_FORMAT_BC7_UNORM (98) and DXGI_FORMAT_R8G8B8A8_UNORM (28).
            # The compressed data stream is 100% identical. Remap for universal Blender 3.6 compatibility!
            dx10_fmt = 98 if dxgi_fmt == 99 else (28 if dxgi_fmt == 29 else dxgi_fmt)
            dx10_hdr = struct.pack('<IIIII', dx10_fmt, 3, 0, 1, 0)
            f.write(dx10_hdr)
        f.write(raw_bytes)

    return output_path


def find_matching_texture(tex_rel_path, search_dirs):
    """
    Search for a texture file matching the relative path specified in MDF.
    """
    # Normalize path separators
    clean_rel = tex_rel_path.replace('\\', '/').strip('/')
    tex_name = os.path.basename(clean_rel)
    base_name = tex_name
    if base_name.lower().endswith('.tex'):
        base_name = base_name[:-4]

    # Search candidates in search_dirs
    for s_dir in search_dirs:
        if not s_dir or not os.path.exists(s_dir):
            continue

        # 1. Direct subpath check
        direct_path = os.path.join(s_dir, clean_rel)
        if os.path.isfile(direct_path):
            return direct_path

        # 2. Check direct_path with extensions (prioritizing .tex over .dds)
        d_dir = os.path.dirname(direct_path)
        if os.path.isdir(d_dir):
            d_base = os.path.basename(direct_path)
            cand_files = [f for f in os.listdir(d_dir) if f.startswith(d_base)]
            # Prioritize .tex source file
            tex_cands = [f for f in cand_files if '.tex' in f.lower()]
            if tex_cands:
                return os.path.join(d_dir, tex_cands[0])
            if cand_files:
                return os.path.join(d_dir, cand_files[0])

        # 3. Check if clean_rel starts with directory name of s_dir (e.g. s_dir is huntingMachine and clean_rel is huntingMachine/textures/...)
        s_basename = os.path.basename(s_dir.rstrip('/\\')).lower()
        if '/' in clean_rel:
            first_part, rest_part = clean_rel.split('/', 1)
            if first_part.lower() == s_basename:
                sub_path = os.path.join(s_dir, rest_part)
                sub_dir = os.path.dirname(sub_path)
                if os.path.isdir(sub_dir):
                    sub_base = os.path.basename(sub_path)
                    sub_cands = [f for f in os.listdir(sub_dir) if f.startswith(sub_base)]
                    tex_sub_cands = [f for f in sub_cands if '.tex' in f.lower()]
                    if tex_sub_cands:
                        return os.path.join(sub_dir, tex_sub_cands[0])
                    if sub_cands:
                        return os.path.join(sub_dir, sub_cands[0])

        # 4. Check inside a 'textures' subdirectory within s_dir
        tex_sub = os.path.join(s_dir, 'textures')
        if os.path.isdir(tex_sub):
            try:
                tex_matches = []
                other_matches = []
                for item in os.listdir(tex_sub):
                    item_lower = item.lower()
                    if item_lower.startswith(base_name.lower() + '.') or item_lower.startswith(base_name.lower() + '_'):
                        full_p = os.path.join(tex_sub, item)
                        if os.path.isfile(full_p):
                            if '.tex' in item_lower:
                                tex_matches.append(full_p)
                            elif '.dds' in item_lower:
                                other_matches.append(full_p)
                if tex_matches:
                    return tex_matches[0]
                if other_matches:
                    return other_matches[0]
            except Exception:
                pass

        # 5. Check directly inside s_dir matching base_name
        try:
            tex_matches = []
            other_matches = []
            for item in os.listdir(s_dir):
                item_lower = item.lower()
                if item_lower.startswith(base_name.lower() + '.') or item_lower.startswith(base_name.lower() + '_'):
                    full_p = os.path.join(s_dir, item)
                    if os.path.isfile(full_p):
                        if '.tex' in item_lower:
                            tex_matches.append(full_p)
                        elif '.dds' in item_lower:
                            other_matches.append(full_p)
            if tex_matches:
                return tex_matches[0]
            if other_matches:
                return other_matches[0]
        except Exception:
            pass

    return None


def load_texture(tex_file_path, convert_textures=True):
    """
    Loads texture into Blender's bpy.data.images.
    If the file is .tex.*, converts it to .dds first.
    """
    if not tex_file_path or not os.path.exists(tex_file_path):
        return None

    load_path = tex_file_path
    ext = os.path.splitext(tex_file_path)[1].lower()

    if '.tex' in os.path.basename(tex_file_path).lower():
        if convert_textures:
            try:
                dds_path = os.path.splitext(tex_file_path)[0]
                if dds_path.lower().endswith('.tex'):
                    dds_path = dds_path[:-4]
                dds_path += '.dds'

                reconvert = False
                if not os.path.exists(dds_path) or os.path.getmtime(dds_path) < os.path.getmtime(tex_file_path):
                    reconvert = True
                else:
                    # Check if existing DDS needs patching or re-conversion for Blender 3.6
                    try:
                        with open(dds_path, 'rb') as f_chk:
                            hdr = f_chk.read(148)
                            if len(hdr) >= 148 and hdr[84:88] == b'DX10':
                                dxgi = struct.unpack_from('<I', hdr, 128)[0]
                                if dxgi == 99 or dxgi == 29:
                                    # Instantly patch DX10 format to 98 (BC7_UNORM) or 28 (R8G8B8A8_UNORM)
                                    with open(dds_path, 'r+b') as f_patch:
                                        f_patch.seek(128)
                                        f_patch.write(struct.pack('<I', 98 if dxgi == 99 else 28))
                                elif dxgi in (70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84):
                                    reconvert = True
                    except Exception:
                        pass

                if reconvert:
                    convert_tex_to_dds(tex_file_path, dds_path)
                load_path = dds_path
            except Exception as e:
                print(f"[RE_Plugin] Failed to convert texture {tex_file_path}: {e}")
                return None
        else:
            return None
    elif ext == '.dds':
        # If passed an existing DDS directly, check if it needs re-conversion or patching
        needs_fix = False
        try:
            with open(load_path, 'rb') as f_chk:
                hdr = f_chk.read(148)
                if len(hdr) >= 148 and hdr[84:88] == b'DX10':
                    dxgi = struct.unpack_from('<I', hdr, 128)[0]
                    if dxgi == 99 or dxgi == 29:
                        with open(load_path, 'r+b') as f_patch:
                            f_patch.seek(128)
                            f_patch.write(struct.pack('<I', 98 if dxgi == 99 else 28))
                    elif dxgi in (70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84):
                        needs_fix = True
        except Exception:
            pass

        if needs_fix and convert_textures:
            d = os.path.dirname(load_path)
            b = os.path.splitext(os.path.basename(load_path))[0]
            try:
                for f in os.listdir(d):
                    if f.startswith(b) and '.tex' in f.lower():
                        convert_tex_to_dds(os.path.join(d, f), load_path)
                        break
            except Exception:
                pass

    # Load in Blender
    try:
        img_name = os.path.basename(load_path)
        existing = bpy.data.images.get(img_name)
        if existing and existing.filepath == load_path and existing.size[0] > 0:
            return existing
        if existing:
            bpy.data.images.remove(existing)
        img = bpy.data.images.load(load_path)
        return img
    except Exception as e:
        print(f"[RE_Plugin] Failed to load image {load_path} into Blender: {e}")
        return None
