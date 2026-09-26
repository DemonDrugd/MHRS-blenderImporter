# -*- coding: utf-8 -*-
"""
RE Engine Mesh (.mesh.*) Importer for Blender Add-on
"""

import os
import re
import struct
import bpy
import mathutils

try:
    from .re_bitstream import BinaryReader, hash_wide
    from .re_mdf import find_mdf_file, MDFFile, create_blender_materials
except ImportError:
    from re_bitstream import BinaryReader, hash_wide
    from re_mdf import find_mdf_file, MDFFile, create_blender_materials


def detect_game_version(mesh_path, reader):
    """
    Detects game version from file extension and header magic.
    Returns: (game_name, mesh_version, mdf_version)
    """
    path_lower = mesh_path.lower()
    raw_ver = reader.read_uint_at(4)

    if raw_ver == 220822879 or '.221108797' in path_lower:
        return ("RE4", 3, 4)
    elif raw_ver == 220705151 or '.230110883' in path_lower:
        return ("SF6", 3, 4)
    elif '.220907984' in path_lower:
        return ("ExoPrimal", 3, 4)
    elif raw_ver == 21061800 or '.2109148288' in path_lower:
        return ("MHRSunbreak", 2, 3)
    elif raw_ver == 2007158797 or '.2008058288' in path_lower:
        return ("MHRise", 2, 3)
    elif raw_ver == 21041600 or '.2109108288' in path_lower or '.220128762' in path_lower:
        return ("RERT", 2, 3)
    elif raw_ver == 2020091500 or '.2101050001' in path_lower:
        return ("RE8", 2, 3)
    elif '.2102020001' in path_lower:
        return ("ReVerse", 2, 3)
    elif '.1902042334' in path_lower:
        return ("RE3", 1, 2)
    elif '.1808282334' in path_lower:
        return ("DMC5", 1, 1)
    elif '.1808312334' in path_lower:
        return ("RE2", 1, 1)
    else:
        return ("MHRSunbreak", 2, 3)


def get_offsets_by_version(ver, game_name=""):
    """Returns key offset locations in mesh file header based on meshVersion."""
    names_offs = 120 if ver < 3 else 144
    nodes_indices_offs = 96 if ver < 3 else 112
    if game_name == "ExoPrimal":
        nodes_indices_offs = 104
        names_offs = 136
    return {
        'numNodes': 18 if ver < 3 else 20,
        'LOD1': 24 if ver < 3 else 32,
        'vBuffHdr': 80 if ver < 3 else 72,
        'bones': 48 if ver < 3 else 104,
        'nodesIndices': nodes_indices_offs,
        'names': names_offs,
    }


class REMeshImporter:
    def __init__(self, filepath, options=None):
        self.filepath = filepath
        self.mesh_dir = os.path.dirname(filepath)
        self.options = options or {}
        self.scale = float(self.options.get('scale', 1.0))
        self.load_textures = bool(self.options.get('load_textures', True))
        self.load_all_textures = bool(self.options.get('load_all_textures', False))
        self.convert_textures = bool(self.options.get('convert_textures', True))
        self.enable_emission = bool(self.options.get('enable_emission', False))
        self.import_all_lods = bool(self.options.get('import_all_lods', False))
        self.collapse_bones = bool(self.options.get('collapse_bones', True))

    def execute(self, context):
        with open(self.filepath, 'rb') as f:
            data = f.read()

        reader = BinaryReader(data)
        magic = reader.read_uint()
        if magic != 0x4853454D:  # 'MESH'
            raise ValueError(f"Invalid MESH magic: 0x{magic:X}")

        game_name, mesh_ver, mdf_ver = detect_game_version(self.filepath, reader)
        if self.options.get('game_name'):
            game_name = self.options['game_name']
            if game_name in ("MHRSunbreak", "MHRise", "RE8", "ReVerse", "RERT"):
                mesh_ver, mdf_ver = 2, 3
            elif game_name in ("SF6", "RE4", "ExoPrimal"):
                mesh_ver, mdf_ver = 3, 4
            else:
                mesh_ver, mdf_ver = 1, 1

        offs_dict = get_offsets_by_version(mesh_ver, game_name)
        num_nodes = reader.read_uint_at(offs_dict['numNodes'])
        lod1_offs = reader.read_uint64_at(offs_dict['LOD1'])
        vbuff_hdr_offs = reader.read_uint64_at(offs_dict['vBuffHdr'])
        bones_offs = reader.read_uint64_at(offs_dict['bones'])
        nodes_indices_offs = reader.read_uint64_at(offs_dict['nodesIndices'])
        names_offs = reader.read_uint64_at(offs_dict['names'])

        # Read strings
        names = []
        for i in range(num_nodes):
            o = reader.read_uint64_at(names_offs + i * 8)
            names.append(reader.read_string_at(o))

        # Extract required material names from mesh header for accurate MDF matching
        mat_count = reader.read_ubyte_at(lod1_offs + 1) if lod1_offs else 0
        mat_indices = [reader.read_ushort_at(nodes_indices_offs + i * 2) for i in range(mat_count)]
        required_mat_names = [names[idx] for idx in mat_indices if idx < len(names)]

        # Read Materials via MDF2
        mdf_path = self.options.get('custom_mdf_path') or find_mdf_file(self.filepath, required_mat_names=required_mat_names)
        blender_mats = {}
        extra_variant_mats = []
        if mdf_path:
            mdf_file = MDFFile(mdf_path, mdf_ver=mdf_ver)
            blender_mats = create_blender_materials(
                mdf_file,
                self.mesh_dir,
                load_textures=self.load_textures,
                load_all_textures=self.load_all_textures,
                convert_textures=self.convert_textures,
                enable_emission=self.enable_emission,
            )

            # Auto-generate color variants for Spiribird (ec009)
            if 'ec009' in self.filepath.lower():
                parent_ec = os.path.abspath(self.filepath)
                while parent_ec and os.path.basename(parent_ec).lower() not in ('ec009', ''):
                    parent_ec = os.path.dirname(parent_ec)
                variants = [
                    ('00', 'Red'),
                    ('01', 'Orange'),
                    ('02', 'Green'),
                    ('03', 'Yellow'),
                    ('08', 'Rainbow'),
                ]
                for v_folder, v_label in variants:
                    v_mdf = os.path.join(parent_ec, v_folder, 'mod', f'ec009_{v_folder}.mdf2.23')
                    if os.path.exists(v_mdf):
                        v_file = MDFFile(v_mdf, mdf_ver=mdf_ver)
                        for m_info in v_file.materials:
                            m_info.name = f"{m_info.name}_{v_folder}_{v_label}"
                        v_created = create_blender_materials(
                            v_file,
                            self.mesh_dir,
                            load_textures=self.load_textures,
                            load_all_textures=False,
                            convert_textures=self.convert_textures,
                            enable_emission=self.enable_emission,
                        )
                        for vm in v_created.values():
                            if vm not in extra_variant_mats and vm not in blender_mats.values():
                                extra_variant_mats.append(vm)

        # Read Bones & Create Armature
        base_name = os.path.basename(self.filepath).split('.mesh')[0]
        arm_obj = None
        bone_names = []
        bone_remap_table = []

        if bones_offs:
            bone_count = reader.read_uint_at(bones_offs)
            bone_map_count = reader.read_uint_at(bones_offs + 4)
            hierarchy_offs = reader.read_uint64_at(bones_offs + 16)
            local_offs = reader.read_uint64_at(bones_offs + 24)
            global_offs = reader.read_uint64_at(bones_offs + 32)

            bone_parents = [reader.read_short_at(hierarchy_offs + i * 16 + 2) for i in range(bone_count)]

            remap_start = bones_offs + 16 + 32
            bone_remap_table = [reader.read_short_at(remap_start + i * 2) for i in range(bone_map_count)]

            # Material count from LOD1
            mat_count = reader.read_ubyte_at(lod1_offs + 1) if lod1_offs else 0

            for i in range(bone_count):
                idx = mat_count + i
                b_name = names[idx] if idx < len(names) else f"Bone_{i:03d}"
                bone_names.append(b_name)

            # Create Blender Armature
            arm_data = bpy.data.armatures.new(f"{base_name}_Armature")
            arm_obj = bpy.data.objects.new(f"{base_name}_Armature", arm_data)
            context.collection.objects.link(arm_obj)
            context.view_layer.objects.active = arm_obj
            bpy.ops.object.mode_set(mode='EDIT')

            edit_bones = []
            for i, b_name in enumerate(bone_names):
                eb = arm_data.edit_bones.new(b_name)
                edit_bones.append(eb)

            for i, eb in enumerate(edit_bones):
                p_idx = bone_parents[i]
                if p_idx != -1 and p_idx < bone_count:
                    eb.parent = edit_bones[p_idx]

                floats = struct.unpack_from('<16f', data, global_offs + i * 64)
                # Row-Major in RE Engine -> Transpose to Column-Major in Blender
                mat = mathutils.Matrix([
                    [floats[0], floats[4], floats[8], floats[12] * self.scale],
                    [floats[1], floats[5], floats[9], floats[13] * self.scale],
                    [floats[2], floats[6], floats[10], floats[14] * self.scale],
                    [floats[3], floats[7], floats[11], floats[15]],
                ])
                eb.head = mat.to_translation()
                col1 = mat.col[1].to_3d()
                length = 0.05 * self.scale
                if col1.length > 1e-4:
                    eb.tail = eb.head + col1.normalized() * length
                else:
                    eb.tail = eb.head + mathutils.Vector((0, length, 0))
                eb.matrix = mat

            bpy.ops.object.mode_set(mode='OBJECT')

        # Read Vertex Buffer Headers
        reader.seek(vbuff_hdr_offs)
        vert_elem_hdr_offs = reader.read_uint64()
        vert_buff_offs = reader.read_uint64()

        if mesh_ver >= 3:
            ukn_vb = reader.read_uint64()
            vert_buff_sz = reader.read_uint()
            face_buff_rel = reader.read_uint()
            face_buff_offs = face_buff_rel + vert_buff_offs
        else:
            face_buff_offs = reader.read_uint64()
            if game_name in ("RERT", "RE7RT", "MHRSunbreak"):
                ukn64 = reader.read_uint64()
            vert_buff_sz = reader.read_uint()
            face_buff_sz = reader.read_uint()

        vert_elem_count_a = reader.read_ushort()
        vert_elem_count_b = reader.read_ushort()

        vert_elems = []
        pos_idx = norm_idx = uv_idx = uv2_idx = weight_idx = color_idx = -1
        reader.seek(vert_elem_hdr_offs)
        for i in range(vert_elem_count_b):
            v_type = reader.read_ushort()
            stride = reader.read_ushort()
            v_offs = reader.read_uint()
            vert_elems.append((v_type, stride, v_offs))
            if v_type == 0 and pos_idx == -1: pos_idx = i
            elif v_type == 1 and norm_idx == -1: norm_idx = i
            elif v_type == 2 and uv_idx == -1: uv_idx = i
            elif v_type == 3 and uv2_idx == -1: uv2_idx = i
            elif v_type == 4 and weight_idx == -1: weight_idx = i
            elif v_type == 5 and color_idx == -1: color_idx = i

        # Read LODs and Submeshes
        lod_count = reader.read_ubyte_at(lod1_offs)
        mat_count = reader.read_ubyte_at(lod1_offs + 1)
        offset_info = [reader.read_uint64_at(lod1_offs + 64 + i * 8) for i in range(lod_count)]

        # Material indices & Name Remap
        mat_indices = [reader.read_ushort_at(nodes_indices_offs + i * 2) for i in range(mat_count)]
        name_remap = [reader.read_ushort_at(nodes_indices_offs + i * 2) for i in range(num_nodes)]

        # Create Collection for this model
        col = bpy.data.collections.new(base_name)
        context.scene.collection.children.link(col)
        if arm_obj:
            context.collection.objects.unlink(arm_obj)
            col.objects.link(arm_obj)

        created_mesh_objs = []
        max_lods = lod_count if self.import_all_lods else 1

        for lod_i in range(max_lods):
            lod_offset = offset_info[lod_i]
            num_main_meshes = reader.read_ubyte_at(lod_offset)
            sub_offsets_p = reader.read_uint64_at(lod_offset + 8)
            main_mesh_offsets = [reader.read_uint64_at(sub_offsets_p + j * 8) for j in range(num_main_meshes)]

            num_verts_lod = 0
            for main_j, main_offs in enumerate(main_mesh_offsets):
                group_id, num_sub = struct.unpack_from('<BB', data, main_offs)
                num_verts, num_faces = struct.unpack_from('<II', data, main_offs + 8)
                sub_offs = main_offs + 16

                sub_data = []
                for k in range(num_sub):
                    if mesh_ver >= 2:
                        mat_id, sub_id, f_count, f_before, v_before = struct.unpack_from('<HHIII', data, sub_offs + k * 24)
                    else:
                        mat_id, sub_id, f_count, f_before, v_before = struct.unpack_from('<HHIII', data, sub_offs + k * 16)
                    sub_data.append((mat_id, sub_id, f_count, f_before, v_before))

                for k, (mat_id, sub_id, f_count, f_before, v_before) in enumerate(sub_data):
                    if k + 1 < len(sub_data):
                        v_count = sub_data[k + 1][4] - v_before
                    else:
                        v_count = num_verts - (v_before - num_verts_lod)

                    if v_count <= 0 or f_count <= 0:
                        continue

                    # Group-based naming (matches Noesis convention: LOD_1_Group_X_Sub_Y)
                    part_tag = ""
                    if group_id >= 200:
                        part_tag = "_Damage"
                    elif group_id >= 100:
                        part_tag = "_Intact"

                    sub_mesh_name = f"LOD_{lod_i+1}_Group_{group_id}{part_tag}_Sub_{k+1}"
                    # Find Material
                    mat_name = ""
                    if mat_id < len(mat_indices):
                        m_name_idx = mat_indices[mat_id]
                        if m_name_idx < len(names):
                            mat_name = names[m_name_idx]
                    if mat_name:
                        sub_mesh_name += f"__{mat_name}"

                    # Read Vertices
                    pos_stride = vert_elems[pos_idx][1]
                    pos_start = vert_buff_offs + vert_elems[pos_idx][2] + v_before * pos_stride
                    vertices = []
                    for v in range(v_count):
                        px, py, pz = struct.unpack_from('<3f', data, pos_start + v * pos_stride)
                        vertices.append((px * self.scale, py * self.scale, pz * self.scale))

                    # Read Faces
                    idx_bytes = data[face_buff_offs + f_before * 2 : face_buff_offs + (f_before + f_count) * 2]
                    raw_indices = struct.unpack(f'<{f_count}H', idx_bytes)
                    faces = [(raw_indices[f_i], raw_indices[f_i+1], raw_indices[f_i+2]) for f_i in range(0, f_count, 3)]

                    # Create Blender Mesh
                    b_mesh = bpy.data.meshes.new(sub_mesh_name)
                    b_mesh.from_pydata(vertices, [], faces)

                    # Read Normals
                    if norm_idx != -1:
                        norm_stride = vert_elems[norm_idx][1]
                        norm_start = vert_buff_offs + vert_elems[norm_idx][2] + v_before * norm_stride
                        normals = []
                        for v in range(v_count):
                            nb = struct.unpack_from('<4b', data, norm_start + v * norm_stride)
                            nx = nb[0] / 127.0
                            ny = nb[1] / 127.0
                            nz = nb[2] / 127.0
                            normals.append((nx, ny, nz))
                        try:
                            b_mesh.normals_split_custom_set_from_vertices(normals)
                        except Exception:
                            pass

                    # Read UVs
                    if uv_idx != -1:
                        uv_stride = vert_elems[uv_idx][1]
                        uv_start = vert_buff_offs + vert_elems[uv_idx][2] + v_before * uv_stride
                        uv_layer = b_mesh.uv_layers.new(name="UVMap")
                        for poly in b_mesh.polygons:
                            for loop_idx in poly.loop_indices:
                                vert_idx = b_mesh.loops[loop_idx].vertex_index
                                u, v = struct.unpack_from('<2e', data, uv_start + vert_idx * uv_stride)
                                # RE Engine DirectX UV: invert V for Blender
                                uv_layer.data[loop_idx].uv = (u, 1.0 - v)

                    b_mesh.update()

                    # Create Object
                    m_obj = bpy.data.objects.new(sub_mesh_name, b_mesh)
                    col.objects.link(m_obj)
                    created_mesh_objs.append(m_obj)

                    # Assign Material
                    target_mat = blender_mats.get(mat_name) or bpy.data.materials.get(mat_name)
                    if not target_mat and mat_name:
                        target_mat = bpy.data.materials.new(name=mat_name)
                        target_mat.use_nodes = True
                        blender_mats[mat_name] = target_mat
                    if target_mat:
                        b_mesh.materials.append(target_mat)
                    for vm in extra_variant_mats:
                        if vm != target_mat and vm.name not in b_mesh.materials:
                            b_mesh.materials.append(vm)

                    # Skinning / Vertex Weights
                    if arm_obj and weight_idx != -1 and bone_remap_table:
                        wt_stride = vert_elems[weight_idx][1]
                        wt_start = vert_buff_offs + vert_elems[weight_idx][2] + v_before * wt_stride

                        # Create vertex groups for bones
                        group_map = {}
                        for remap_i in set(bone_remap_table):
                            if remap_i < len(bone_names):
                                b_name = bone_names[remap_i]
                                vg = m_obj.vertex_groups.get(b_name)
                                if not vg:
                                    vg = m_obj.vertex_groups.new(name=b_name)
                                group_map[remap_i] = vg

                        for v in range(v_count):
                            bone_ids = struct.unpack_from('<8B', data, wt_start + v * wt_stride)
                            weights = struct.unpack_from('<8B', data, wt_start + v * wt_stride + 8)
                            for b_slot, w_raw in zip(bone_ids, weights):
                                if w_raw > 0 and b_slot < len(bone_remap_table):
                                    real_b_idx = bone_remap_table[b_slot]
                                    vg = group_map.get(real_b_idx)
                                    if vg:
                                        vg.add([v], w_raw / 255.0, 'REPLACE')

                        # Add Armature Modifier
                        arm_mod = m_obj.modifiers.new(name="Armature", type='ARMATURE')
                        arm_mod.object = arm_obj
                        m_obj.parent = arm_obj

                    # If part is a broken / damaged variant (Group >= 200 in RE Engine),
                    # hide it by default with standard viewport hide so the user can easily toggle
                    # it on/off with the Eye icon in the Outliner or with Alt+H.
                    if group_id >= 200:
                        m_obj.hide_set(True)
                    elif ('environmentcreature' in self.filepath.lower() or re.search(r'ec\d{3}', self.filepath.lower())):
                        # For environment creatures with multi-state frame meshes (e.g. butterfly wings 1..5, frog legs 1..3, bird wings/crest),
                        # default secondary frames to hidden via hide_viewport/hide_render so Outliner Eye remains open for animation.
                        if group_id not in (0, 1, 3, 10, 20, 30):
                            m_obj.hide_viewport = True
                            m_obj.hide_render = True
                            m_obj.hide_set(False)

                num_verts_lod += num_verts

        # Setup environment creature multi-frame visibility drivers if Armature is present
        if arm_obj and created_mesh_objs:
            try:
                from .re_mot import setup_mesh_visibility_drivers
            except ImportError:
                from re_mot import setup_mesh_visibility_drivers
            setup_mesh_visibility_drivers(arm_obj, created_mesh_objs)

        print(f"[RE_Plugin] Successfully imported {len(created_mesh_objs)} meshes from {self.filepath}")
        return {'FINISHED'}
