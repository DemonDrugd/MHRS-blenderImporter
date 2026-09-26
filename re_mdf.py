# -*- coding: utf-8 -*-
"""
RE Engine MDF2 Material Parser & Blender Material Builder
"""

import os
import re
import math
import bpy
try:
    from .re_bitstream import BinaryReader, hash_wide
    from .re_tex import find_matching_texture, load_texture
except ImportError:
    from re_bitstream import BinaryReader, hash_wide
    from re_tex import find_matching_texture, load_texture


class REMaterialInfo:
    def __init__(self, name, mat_hash=0):
        self.name = name
        self.mat_hash = mat_hash
        self.mmtr_path = ""
        self.shader_type = 0
        self.alpha_flag = 0
        self.has_transparency = False
        self.base_color = (1.0, 1.0, 1.0, 1.0)
        self.roughness = 0.5
        self.metallic = 0.0
        self.specular = 0.5
        self.emissive_color = (1.0, 1.0, 1.0, 1.0)
        self.emissive_intensity = 1.0
        self.properties = {}
        self.textures = []  # list of (tex_type, tex_path)


class MDFFile:
    def __init__(self, mdf_path, mdf_ver=3):
        self.path = mdf_path
        self.mdf_ver = mdf_ver
        self.materials = []
        self.parse()

    def parse(self):
        if not os.path.exists(self.path):
            return

        with open(self.path, 'rb') as f:
            data = f.read()

        reader = BinaryReader(data)
        magic = reader.read_uint()  # 'MDF\0' -> 0x46444d
        u1 = reader.read_ushort()
        mat_count = reader.read_ushort()

        for i in range(mat_count):
            if self.mdf_ver > 3:
                header_offs = 0x10 + i * 100
            elif self.mdf_ver > 2:
                header_offs = 0x10 + i * 80
            else:
                header_offs = 0x10 + i * 64

            reader.seek(header_offs)
            mat_name_offs = reader.read_uint64()
            mat_hash = reader.read_int()
            sz_float_str = reader.read_uint()
            float_count = reader.read_uint()
            tex_count = reader.read_uint()

            if self.mdf_ver >= 3:
                reader.seek(8, 1)

            shader_type = reader.read_uint()
            if self.mdf_ver >= 4:
                ukn_sf6 = reader.read_uint()

            alpha_flag = reader.read_uint()

            if self.mdf_ver >= 4:
                reader.seek(8, 1)

            float_hdr_offs = reader.read_uint64()
            tex_hdr_offs = reader.read_uint64()
            if self.mdf_ver >= 3:
                first_mtrl_name_offs = reader.read_uint64()
            float_start_offs = reader.read_uint64()
            mmtr_path_offs = reader.read_uint64()

            mat_name = reader.read_unicode_string_at(mat_name_offs)
            mmtr_path = reader.read_unicode_string_at(mmtr_path_offs) if mmtr_path_offs else ""

            mat_info = REMaterialInfo(mat_name, mat_hash)
            mat_info.mmtr_path = mmtr_path
            mat_info.shader_type = shader_type
            mat_info.alpha_flag = alpha_flag

            # Capcom RE Engine MDF alpha flags:
            # Bit 0 (0x1): Alpha Cutout / Alpha Test
            # Bit 1 (0x2): Alpha Blending / Transparency
            # Bits >= 2 are render flags / depth / two-sided, NOT transparency flags.
            has_trans = bool(alpha_flag & 0x3)
            mat_lower = mat_name.lower()
            mmtr_lower = mmtr_path.lower()
            if any(k in mat_lower for k in ('_alpha', 'alp', 'wing', 'glass', 'hair', 'fur', 'feather', 'trans', 'twoside')):
                has_trans = True
            elif ('_dirt' in mmtr_lower) or ('_decal' in mmtr_lower):
                has_trans = True
            elif (alpha_flag & 0x3) == 0 and any(k in mat_lower for k in ('body', 'tail', 'eye', 'damage', 'rock', 'mud', 'blade', 'jet')):
                has_trans = False
            mat_info.has_transparency = has_trans

            # Read float properties
            for j in range(float_count):
                reader.seek(float_hdr_offs + (j * 0x18))
                dscrptn_offs = reader.read_uint64()
                f_type = reader.read_uint64()
                strct_offs = reader.read_uint()
                num_floats = reader.read_uint()

                param_type = reader.read_unicode_string_at(dscrptn_offs)

                if self.mdf_ver >= 2:
                    reader.seek(float_start_offs + strct_offs)
                else:
                    reader.seek(float_start_offs + num_floats)

                if num_floats == 4:
                    val = (reader.read_float(), reader.read_float(), reader.read_float(), reader.read_float())
                elif num_floats == 1:
                    val = reader.read_float()
                else:
                    val = 0.0

                mat_info.properties[param_type] = val
                if param_type == "BaseColor":
                    mat_info.base_color = val
                elif param_type == "Roughness":
                    mat_info.roughness = val
                elif param_type == "Metallic":
                    mat_info.metallic = val
                elif param_type in ("PrimalySpecularColor", "Specular"):
                    mat_info.specular = val[0] if isinstance(val, (tuple, list)) else val
                elif param_type in ("EMI_ColorParam", "EmissiveColor", "EmissionColor"):
                    mat_info.emissive_color = val
                elif param_type in ("Rim_color", "RimColor"):
                    mat_info.rim_color = val
                elif param_type in ("Emissive_intensity", "EmissionIntensity"):
                    mat_info.emissive_intensity = val if isinstance(val, (int, float)) else val[0]

            # If no explicit emissive_color was found, fallback to rim_color
            if not getattr(mat_info, 'emissive_color', None) and getattr(mat_info, 'rim_color', None):
                mat_info.emissive_color = mat_info.rim_color

            # Read texture headers
            for j in range(tex_count):
                if self.mdf_ver >= 2:
                    reader.seek(tex_hdr_offs + (j * 0x20))
                    t_type_offs = reader.read_uint64()
                    reader.seek(8, 1)
                    t_path_offs = reader.read_uint64()
                else:
                    reader.seek(tex_hdr_offs + (j * 0x18))
                    t_type_offs = reader.read_uint64()
                    reader.seek(8, 1)
                    t_path_offs = reader.read_uint64()

                t_type = reader.read_unicode_string_at(t_type_offs) if t_type_offs else ""
                t_path = reader.read_unicode_string_at(t_path_offs).replace("@", "") if t_path_offs else ""

                if t_type or t_path:
                    mat_info.textures.append((t_type, t_path))

            self.materials.append(mat_info)


def find_mdf_file(mesh_path, required_mat_names=None):
    """
    Find corresponding .mdf2.* file for a given mesh file.
    Supports:
    1. Exact / strong candidate prefixes in mesh_dir (e.g. ec025_00_bullet.mdf2 for ec025_00_bullet.mesh)
    2. Stripped trailing indices (e.g. em135_safe_rock_00 -> em135_safe_rock.mdf2)
    3. Stripped accessory suffixes (_bullet, _shell, _cartridge, _debris, etc.)
    4. Required material name matching against .mdf2 files in mesh_dir
    5. Parent directory search & sibling directories search (e.g. for debris/shell/bullet in subfolders)
    """
    if not mesh_path:
        return None
    mesh_dir = os.path.dirname(mesh_path)
    base_name = os.path.basename(mesh_path)
    prefix = base_name.split('.mesh')[0]

    def _get_mdf_mat_names(mdf_p):
        try:
            with open(mdf_p, 'rb') as f:
                data = f.read()
            r = BinaryReader(data)
            if r.read_uint() != 0x46444d:
                return []
            count = r.read_ushort_at(6)
            m_names = []
            for i in range(count):
                offs = 0x10 + i * 80
                n_offs = r.read_uint64_at(offs)
                m_names.append(r.read_unicode_string_at(n_offs))
            return m_names
        except Exception:
            return []

    candidates = [
        prefix + '.mdf2',
        prefix + '_mat.mdf2',
        prefix + '_00.mdf2',
        re.sub(r'_\d+$', '', prefix) + '.mdf2',
        re.sub(r'_(bullet|shell|cartridge|debris|debries|sub|part)(\d*)$', '', prefix, flags=re.I) + '.mdf2',
    ]

    # 1. Search in mesh_dir
    if os.path.isdir(mesh_dir):
        files = os.listdir(mesh_dir)
        mdf_files = [f for f in files if '.mdf2' in f.lower()]

        for cand in candidates:
            cand_l = cand.lower()
            for item in mdf_files:
                if item.lower().startswith(cand_l):
                    return os.path.join(mesh_dir, item)

        if required_mat_names and mdf_files:
            for item in mdf_files:
                p = os.path.join(mesh_dir, item)
                mats = _get_mdf_mat_names(p)
                if any(m in mats for m in required_mat_names):
                    return p

        if len(mdf_files) == 1:
            return os.path.join(mesh_dir, mdf_files[0])

    # 2. Search in parent directory and sibling directories
    parent_dir = os.path.dirname(mesh_dir)
    if parent_dir and os.path.isdir(parent_dir):
        p_mdfs = [f for f in os.listdir(parent_dir) if '.mdf2' in f.lower()]
        for cand in candidates:
            cand_l = cand.lower()
            for item in p_mdfs:
                if item.lower().startswith(cand_l):
                    return os.path.join(parent_dir, item)
        if required_mat_names and p_mdfs:
            for item in p_mdfs:
                p = os.path.join(parent_dir, item)
                mats = _get_mdf_mat_names(p)
                if any(m in mats for m in required_mat_names):
                    return p

        # Sibling directories under parent
        try:
            for sib in os.listdir(parent_dir):
                sib_p = os.path.join(parent_dir, sib)
                if os.path.isdir(sib_p) and os.path.abspath(sib_p) != os.path.abspath(mesh_dir):
                    s_mdfs = [f for f in os.listdir(sib_p) if '.mdf2' in f.lower()]
                    for cand in candidates:
                        cand_l = cand.lower()
                        for item in s_mdfs:
                            if item.lower().startswith(cand_l):
                                return os.path.join(sib_p, item)
                    if required_mat_names and s_mdfs:
                        for item in s_mdfs:
                            p = os.path.join(sib_p, item)
                            mats = _get_mdf_mat_names(p)
                            if any(m in mats for m in required_mat_names):
                                return p
        except Exception:
            pass

    return None


def find_game_root(path):
    """
    Walks up the directory tree to find the root extracted game directory (e.g. STM, natives, or game root).
    """
    if not path:
        return None
    cur = os.path.abspath(path)
    if os.path.isfile(cur):
        cur = os.path.dirname(cur)

    while True:
        base = os.path.basename(cur).lower()
        if base in ('stm', 'natives', 'streaming', 're_chunk_000'):
            return cur

        try:
            subdirs = {d.lower() for d in os.listdir(cur) if os.path.isdir(os.path.join(cur, d))}
            if 'stm' in subdirs:
                return os.path.join(cur, 'stm')
            if ({'enemy', 'huntingmachine', 'environmentcreature', 'weapon', 'mastermaterial', 'stage', 'player', 'item', 'vfx', 'system', 'ui'} & subdirs):
                return cur
        except Exception:
            pass

        parent = os.path.dirname(cur)
        if not parent or parent == cur:
            break
        cur = parent

    return None


def create_blender_materials(mdf_file, mesh_dir, root_game_dir=None, load_textures=True, load_all_textures=False, convert_textures=True, enable_emission=False):
    """
    Creates Blender materials for all materials in MDF file.
    Returns a dict mapping mat_name -> bpy.types.Material.
    - load_textures: Loads core PBR textures (BaseColor/ALBD, Normal/NRMR, Alpha/ALP, Emission/EMI).
    - load_all_textures: Additionally loads ALL auxiliary texture slots (Damage, Mask, SSS, Cavity, etc.)
                         as labeled Image Texture nodes for modding/advanced shading.
    - enable_emission: If True, sets Emission Strength > 0 for standard models. If False, keeps emission
                       nodes wired in graph but sets Strength to 0 (except glowing creatures like Spiribirds)
                       to prevent blowout / yellowing of base textures.
    """
    blender_mats = {}
    search_dirs = [mesh_dir]

    # Add sibling directories of mesh_dir (e.g. if mesh is in bullet00/ or shell/ and textures are in mod/ or vice versa)
    parent_d = os.path.dirname(os.path.abspath(mesh_dir))
    if parent_d and os.path.isdir(parent_d):
        try:
            for sib in os.listdir(parent_d):
                sib_p = os.path.join(parent_d, sib)
                if os.path.isdir(sib_p) and sib_p not in search_dirs:
                    search_dirs.append(sib_p)
        except Exception:
            pass

    # 1. Walk up all parent directories from mesh_dir
    cur = os.path.abspath(mesh_dir)
    parents = []
    while True:
        parent = os.path.dirname(cur)
        if not parent or parent == cur:
            break
        parents.append(parent)
        cur = parent

    # 2. Check for dedicated 'textures' folders in parent hierarchy (e.g. huntingMachine/textures)
    for p in [mesh_dir] + parents:
        for t_sub in ('textures', 'Textures', 'texture', 'Texture'):
            candidate = os.path.join(p, t_sub)
            if os.path.isdir(candidate) and candidate not in search_dirs:
                search_dirs.append(candidate)

    # 3. Game Root (STM or extracted directory)
    detected_root = root_game_dir or find_game_root(mesh_dir)
    if detected_root and os.path.isdir(detected_root):
        if detected_root not in search_dirs:
            search_dirs.append(detected_root)
        for sub_r in ('stm', 'STM', 'streaming', 'Streaming'):
            sub_p = os.path.join(detected_root, sub_r)
            if os.path.isdir(sub_p) and sub_p not in search_dirs:
                search_dirs.append(sub_p)

    # 4. Add all parents to search_dirs
    for p in parents:
        if p not in search_dirs:
            search_dirs.append(p)

    should_load_textures = load_textures or load_all_textures

    for mat_info in mdf_file.materials:
        mat_name = mat_info.name
        is_damage_mat = (
            'damage' in mat_name.lower() or
            mat_name.lower().endswith('_d') or
            '_d_' in mat_name.lower()
        )
        # Reuse existing or create new material
        mat = bpy.data.materials.get(mat_name)
        if not mat:
            mat = bpy.data.materials.new(name=mat_name)

        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        # Create Core Nodes
        out_node = nodes.new(type='ShaderNodeOutputMaterial')
        out_node.location = (400, 0)

        bsdf_node = nodes.new(type='ShaderNodeBsdfPrincipled')
        bsdf_node.location = (0, 0)
        links.new(bsdf_node.outputs['BSDF'], out_node.inputs['Surface'])

        # Set default values from MDF
        if 'Roughness' in bsdf_node.inputs:
            bsdf_node.inputs['Roughness'].default_value = float(mat_info.roughness)
        if 'Metallic' in bsdf_node.inputs:
            bsdf_node.inputs['Metallic'].default_value = float(mat_info.metallic)
        if 'Base Color' in bsdf_node.inputs and isinstance(mat_info.base_color, (tuple, list)):
            bsdf_node.inputs['Base Color'].default_value = (
                float(mat_info.base_color[0]),
                float(mat_info.base_color[1]),
                float(mat_info.base_color[2]),
                1.0,
            )

        if not should_load_textures:
            blender_mats[mat_name] = mat
            continue

        # Load Textures
        tex_x = -400
        damage_diffuse_img = None
        damage_diffuse_entry = None
        regular_diffuse_img = None
        regular_diffuse_entry = None

        damage_normal_img = None
        damage_normal_entry = None
        regular_normal_img = None
        regular_normal_entry = None

        damage_alpha_img = None
        regular_alpha_img = None

        damage_emission_img = None
        regular_emission_img = None

        other_textures = []

        for t_type, t_path in mat_info.textures:
            found_path = find_matching_texture(t_path, search_dirs)
            if not found_path:
                continue

            base_tex_name = os.path.basename(t_path)
            t_lower = (t_type + ' ' + base_tex_name).lower()
            img = load_texture(found_path, convert_textures=convert_textures)
            if not img:
                continue

            # Check if this specific texture is a damage-state variant texture
            is_damage_tex = 'damage' in base_tex_name.lower() or 'damage' in t_path.lower()

            # Classify texture type
            if ('dielectric' in t_lower or 'albd' in t_lower or 'albm' in t_lower or 'basecolor' in t_lower or 'base' in t_lower):
                if is_damage_tex:
                    if not damage_diffuse_img:
                        damage_diffuse_img = img
                        damage_diffuse_entry = (t_type, img, base_tex_name)
                    else:
                        other_textures.append((t_type, img, base_tex_name))
                else:
                    if not regular_diffuse_img:
                        regular_diffuse_img = img
                        regular_diffuse_entry = (t_type, img, base_tex_name)
                    else:
                        other_textures.append((t_type, img, base_tex_name))
            elif ('normal' in t_lower or 'nrmr' in t_lower or 'nrm' in t_lower or 'nrrt' in t_lower):
                if is_damage_tex:
                    if not damage_normal_img:
                        damage_normal_img = img
                        damage_normal_entry = (t_type, img, base_tex_name)
                    else:
                        other_textures.append((t_type, img, base_tex_name))
                else:
                    if not regular_normal_img:
                        regular_normal_img = img
                        regular_normal_entry = (t_type, img, base_tex_name)
                    else:
                        other_textures.append((t_type, img, base_tex_name))
            elif ('alpha' in t_lower or 'alp' in t_lower or ('msk' in t_lower and mat_info.has_transparency)):
                # In RE Engine, Damage_ALP is an in-game dynamic damage blend mask, never opacity/transparency.
                # NullMSK / NullWhite / NullBlack are dummy placeholder textures, not model alpha cutout textures.
                # Opaque body materials should never map alpha/msk textures to transparency.
                if not is_damage_tex and 'null' not in t_lower and mat_info.has_transparency:
                    if not regular_alpha_img:
                        regular_alpha_img = img
                    else:
                        other_textures.append((t_type, img, base_tex_name))
                else:
                    other_textures.append((t_type, img, base_tex_name))
            elif ('emi' in t_lower or 'emissive' in t_lower):
                if is_damage_tex:
                    if not damage_emission_img:
                        damage_emission_img = img
                    else:
                        other_textures.append((t_type, img, base_tex_name))
                else:
                    if not regular_emission_img:
                        regular_emission_img = img
                    else:
                        other_textures.append((t_type, img, base_tex_name))
            else:
                other_textures.append((t_type, img, base_tex_name))

        # Select primary textures based on whether this material is for a damage/breakable part
        aux_textures = list(other_textures)
        if is_damage_mat:
            # Damage / breakable part materials prioritize textures with the damage suffix
            diffuse_img = damage_diffuse_img or regular_diffuse_img
            normal_img = damage_normal_img or regular_normal_img
            emission_img = damage_emission_img or regular_emission_img
            alpha_img = damage_alpha_img or regular_alpha_img

            if regular_diffuse_entry and regular_diffuse_entry[1] != diffuse_img:
                aux_textures.append(regular_diffuse_entry)
            if regular_normal_entry and regular_normal_entry[1] != normal_img:
                aux_textures.append(regular_normal_entry)
        else:
            # Regular intact materials prioritize standard textures
            diffuse_img = regular_diffuse_img or damage_diffuse_img
            normal_img = regular_normal_img or damage_normal_img
            emission_img = regular_emission_img or damage_emission_img
            alpha_img = regular_alpha_img or damage_alpha_img

            if damage_diffuse_entry and damage_diffuse_entry[1] != diffuse_img:
                aux_textures.append(damage_diffuse_entry)
            if damage_normal_entry and damage_normal_entry[1] != normal_img:
                aux_textures.append(damage_normal_entry)

        # Identify creature type and emission properties
        tint_color = getattr(mat_info, 'emissive_color', (1.0, 1.0, 1.0, 1.0))
        is_spiribird = any('ec009' in p.lower() for p in [mesh_dir, mat_info.name, getattr(mdf_file, 'path', '')])

        # 1. Connect Diffuse (Base Color)
        if diffuse_img:
            diff_node = nodes.new(type='ShaderNodeTexImage')
            diff_node.image = diffuse_img
            diff_node.label = "Base Color (ALBD)"
            diff_node.location = (tex_x, 150)
            diff_out = diff_node.outputs['Color']

            # For Spiribirds (ec009), diffuse map is grayscale; tint Base Color with emissive color
            if is_spiribird and tint_color and (tint_color[0] < 0.95 or tint_color[1] < 0.95 or tint_color[2] < 0.95):
                try:
                    mix_c = nodes.new(type='ShaderNodeMix')
                    mix_c.data_type = 'RGBA'
                    mix_c.blend_type = 'MULTIPLY'
                    mix_c.label = "Spiribird Base Tint"
                    mix_c.location = (tex_x + 200, 150)
                    mix_c.inputs[0].default_value = 1.0
                    a_s = [s for s in mix_c.inputs if s.type == 'RGBA'][0]
                    b_s = [s for s in mix_c.inputs if s.type == 'RGBA'][1]
                    out_s = [s for s in mix_c.outputs if s.type == 'RGBA'][0]
                    links.new(diff_out, a_s)
                    b_s.default_value = (float(tint_color[0]), float(tint_color[1]), float(tint_color[2]), 1.0)
                    diff_out = out_s
                except Exception:
                    try:
                        mix_c = nodes.new(type='ShaderNodeMixRGB')
                        mix_c.blend_type = 'MULTIPLY'
                        mix_c.label = "Spiribird Base Tint"
                        mix_c.location = (tex_x + 200, 150)
                        mix_c.inputs['Fac'].default_value = 1.0
                        links.new(diff_out, mix_c.inputs['Color1'])
                        mix_c.inputs['Color2'].default_value = (float(tint_color[0]), float(tint_color[1]), float(tint_color[2]), 1.0)
                        diff_out = mix_c.outputs['Color']
                    except Exception:
                        pass

            links.new(diff_out, bsdf_node.inputs['Base Color'])

        # 2. Connect Normal & Roughness (NRMR)
        if normal_img:
            nrm_node = nodes.new(type='ShaderNodeTexImage')
            nrm_node.image = normal_img
            nrm_node.label = "Normal / Roughness (NRMR)"
            if hasattr(normal_img, 'colorspace_settings'):
                normal_img.colorspace_settings.name = 'Non-Color'
            nrm_node.location = (tex_x, -150)

            nrm_map_node = nodes.new(type='ShaderNodeNormalMap')
            nrm_map_node.location = (tex_x + 220, -150)

            links.new(nrm_node.outputs['Color'], nrm_map_node.inputs['Color'])
            links.new(nrm_map_node.outputs['Normal'], bsdf_node.inputs['Normal'])

            # In RE Engine, NRMR alpha channel is Roughness!
            if 'Roughness' in bsdf_node.inputs:
                links.new(nrm_node.outputs['Alpha'], bsdf_node.inputs['Roughness'])

        # 3. Connect Alpha (ONLY when a dedicated ALP/Alpha texture is found; ALBD is strictly color-only;
        # 3. Connect Alpha (ONLY when material has transparency enabled; opaque body remains Alpha = 1.0).
        next_y = -450
        if mat_info.has_transparency and alpha_img and 'Alpha' in bsdf_node.inputs and not is_damage_mat:
            alp_node = nodes.new(type='ShaderNodeTexImage')
            alp_node.image = alpha_img
            alp_node.label = "Alpha Cutout (ALP)"
            if hasattr(alpha_img, 'colorspace_settings'):
                alpha_img.colorspace_settings.name = 'Non-Color'
            alp_node.location = (tex_x, next_y)
            next_y -= 300
            # For MSK4 textures, transparency/cutout is stored in the Alpha channel!
            # For grayscale ALP maps (where Alpha socket is constant 1.0), use the Color socket.
            use_alpha_socket = 'msk' in getattr(alpha_img, 'name', '').lower() or 'msk' in getattr(alpha_img, 'filepath', '').lower()
            out_sock = alp_node.outputs['Alpha'] if (use_alpha_socket and 'Alpha' in alp_node.outputs) else alp_node.outputs['Color']
            links.new(out_sock, bsdf_node.inputs['Alpha'])
            try:
                mat.blend_method = 'HASHED'
                mat.shadow_method = 'HASHED'
            except Exception:
                pass
        else:
            # Opaque material or Damage material: ensure material is strictly opaque and Alpha = 1.0
            if 'Alpha' in bsdf_node.inputs:
                bsdf_node.inputs['Alpha'].default_value = 1.0
            try:
                mat.blend_method = 'OPAQUE'
                mat.shadow_method = 'OPAQUE'
            except Exception:
                pass

        # 4. Connect Emission (EMI)
        if emission_img:
            emi_node = nodes.new(type='ShaderNodeTexImage')
            emi_node.image = emission_img
            emi_node.label = "Emission (EMI)"
            emi_node.location = (tex_x, next_y)
            next_y -= 300

            # Determine if emission color tinting is needed (e.g. Spiribird ec009 Red, Orange, Green, Yellow)
            emi_out_sock = emi_node.outputs['Color']

            # Apply tinting if color param is not pure white
            if tint_color and (tint_color[0] < 0.95 or tint_color[1] < 0.95 or tint_color[2] < 0.95):
                try:
                    mix_node = nodes.new(type='ShaderNodeMix')
                    mix_node.data_type = 'RGBA'
                    mix_node.blend_type = 'MULTIPLY'
                    mix_node.label = "EMI Color Tint"
                    mix_node.location = (tex_x + 220, next_y + 300)
                    mix_node.inputs[0].default_value = 1.0  # Factor
                    a_sock = [s for s in mix_node.inputs if s.type == 'RGBA'][0]
                    b_sock = [s for s in mix_node.inputs if s.type == 'RGBA'][1]
                    out_sock = [s for s in mix_node.outputs if s.type == 'RGBA'][0]
                    links.new(emi_node.outputs['Color'], a_sock)
                    b_sock.default_value = (float(tint_color[0]), float(tint_color[1]), float(tint_color[2]), 1.0)
                    emi_out_sock = out_sock
                except Exception:
                    try:
                        mix_node = nodes.new(type='ShaderNodeMixRGB')
                        mix_node.blend_type = 'MULTIPLY'
                        mix_node.label = "EMI Color Tint"
                        mix_node.location = (tex_x + 220, next_y + 300)
                        mix_node.inputs['Fac'].default_value = 1.0
                        links.new(emi_node.outputs['Color'], mix_node.inputs['Color1'])
                        mix_node.inputs['Color2'].default_value = (float(tint_color[0]), float(tint_color[1]), float(tint_color[2]), 1.0)
                        emi_out_sock = mix_node.outputs['Color']
                    except Exception:
                        pass

            # Connect to Emission Color (Blender 4.0+) or Emission (Blender 3.x)
            emi_input = bsdf_node.inputs.get('Emission Color') or bsdf_node.inputs.get('Emission')
            if emi_input:
                links.new(emi_out_sock, emi_input)

            # Control strength: clamp/compress high HDR emission intensities (e.g. 8.0, 12.0)
            # to prevent blinding whiteout in Blender Principled BSDF while maintaining vivid color.
            raw_intensity = float(mat_info.emissive_intensity or 1.0)
            if raw_intensity > 2.5:
                clamped_intensity = 2.0 + math.log10(1.0 + (raw_intensity - 2.0) * 0.25) * 1.5
            else:
                clamped_intensity = max(0.5, raw_intensity)

            if 'Emission Strength' in bsdf_node.inputs:
                if is_spiribird:
                    bsdf_node.inputs['Emission Strength'].default_value = float(clamped_intensity)
                elif enable_emission:
                    bsdf_node.inputs['Emission Strength'].default_value = float(clamped_intensity)
                else:
                    bsdf_node.inputs['Emission Strength'].default_value = 0.0

        # 5. Load All Textures: create organized nodes for all auxiliary slots (Masks, Damage, SSS, etc.)
        if load_all_textures and aux_textures:
            aux_x = -750
            aux_y = 300
            for slot_type, aux_img, filename in aux_textures:
                aux_node = nodes.new(type='ShaderNodeTexImage')
                aux_node.image = aux_img
                aux_node.label = f"{slot_type}: {filename}"
                aux_node.location = (aux_x, aux_y)
                aux_y -= 280
                slot_lower = (slot_type + ' ' + filename).lower()
                if any(k in slot_lower for k in ('nrm', 'msk', 'alpha', 'alp', 'cmm', 'rough', 'wnd', 'mask')):
                    if hasattr(aux_img, 'colorspace_settings'):
                        aux_img.colorspace_settings.name = 'Non-Color'

        blender_mats[mat_name] = mat

    return blender_mats
