# -*- coding: utf-8 -*-
"""
RE Engine Blender UI & Dialog Operators
Replicating the original Noesis plugin layout and functionality
"""

import os
import json
import bpy
from bpy.props import (
    StringProperty,
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    CollectionProperty,
)
from bpy.types import PropertyGroup, UIList, Operator

try:
    from .re_mesh import REMeshImporter, detect_game_version
    from .re_mot import REMotlist, apply_motion_to_armature
except ImportError:
    from re_mesh import REMeshImporter, detect_game_version
    from re_mot import REMotlist, apply_motion_to_armature


# =========================================================================
# Persistent Directory Storage (Remembers last opened / imported directory)
# =========================================================================

def get_config_path():
    cfg_dir = bpy.utils.user_resource('CONFIG')
    return os.path.join(cfg_dir, "blender_re_mesh_addon.json")


def load_saved_dirs():
    try:
        p = get_config_path()
        if os.path.isfile(p):
            with open(p, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('last_mesh_dir', ''), data.get('last_mot_dir', '')
    except Exception:
        pass
    return '', ''


def save_saved_dirs(mesh_dir=None, mot_dir=None):
    try:
        p = get_config_path()
        data = {}
        if os.path.isfile(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                data = {}
        if mesh_dir and os.path.isdir(mesh_dir):
            data['last_mesh_dir'] = os.path.abspath(mesh_dir)
        if mot_dir and os.path.isdir(mot_dir):
            data['last_mot_dir'] = os.path.abspath(mot_dir)
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


# =========================================================================
# Property Groups for Lists
# =========================================================================

class REFileItem(PropertyGroup):
    name: StringProperty(name="Name")
    full_path: StringProperty(name="Full Path")
    is_dir: BoolProperty(name="Is Directory", default=False)


class REMotionItem(PropertyGroup):
    name: StringProperty(name="Motion Name")
    frame_count: FloatProperty(name="Frames", default=0.0)
    mot_index: IntProperty(name="Motion Index", default=0)
    motlist_path: StringProperty(name="Motlist Path")


def update_mesh_dir(self, context):
    refresh_mesh_file_list(context)
    if self.mesh_current_dir and os.path.isdir(self.mesh_current_dir):
        save_saved_dirs(mesh_dir=self.mesh_current_dir)


def update_mot_dir(self, context):
    refresh_motlist_file_list(context)
    if self.mot_current_dir and os.path.isdir(self.mot_current_dir):
        save_saved_dirs(mot_dir=self.mot_current_dir)


def update_mot_files_idx(self, context):
    refresh_motions_from_selected(context)


class RESettings(PropertyGroup):
    # Mesh Dialog Settings
    mesh_current_dir: StringProperty(
        name="Mesh files from",
        default="",
        update=update_mesh_dir,
    )
    mesh_files: CollectionProperty(type=REFileItem)
    mesh_files_idx: IntProperty(name="Mesh File Index", default=0)

    files_to_load: CollectionProperty(type=REFileItem)
    files_to_load_idx: IntProperty(name="Files to load Index", default=0)

    load_textures: BoolProperty(
        name="Load Textures",
        description="Load standard core PBR textures (BaseColor/ALBD, Normal/NRMR, Alpha/ALP, and Emission/EMI)",
        default=False
    )
    load_all_textures: BoolProperty(
        name="Load All Textures",
        description="Load ALL texture slots defined in MDF (including Damage maps, Masks, SSS, Cavity, etc.) as Shader Image nodes",
        default=False
    )
    enable_emission: BoolProperty(
        name="Enable Emission",
        description="Connect Emission (EMI) texture to Principled BSDF emission. When disabled, emission nodes are kept ready in the shader graph but strength is 0 to preserve authentic base textures",
        default=False
    )
    convert_textures: BoolProperty(name="Convert Textures", default=True)
    collapse_bones: BoolProperty(name="Collapse Bones", default=True)

    game_selection: EnumProperty(
        name="Game",
        items=[
            ("MHRSunbreak", "MH Rise Sunbreak", "Monster Hunter Rise Sunbreak"),
            ("MHRise", "MH Rise", "Monster Hunter Rise"),
            ("RE2", "Resident Evil 2", "Resident Evil 2 Remake"),
            ("RE3", "Resident Evil 3", "Resident Evil 3 Remake"),
            ("RE4", "Resident Evil 4", "Resident Evil 4 Remake"),
            ("RE7", "Resident Evil 7", "Resident Evil 7"),
            ("RE7RT", "Resident Evil 7 RT", "Resident Evil 7 Ray Tracing"),
            ("RE8", "Resident Evil 8", "Resident Evil Village"),
            ("DMC5", "Devil May Cry 5", "Devil May Cry 5"),
            ("SF6", "Street Fighter 6", "Street Fighter 6"),
            ("RERT", "RE 2/3 RT", "Resident Evil 2/3 Ray Tracing"),
            ("ReVerse", "RE ReVerse", "Resident Evil ReVerse"),
            ("ExoPrimal", "ExoPrimal", "ExoPrimal"),
        ],
        default="MHRSunbreak",
    )

    view_selection: EnumProperty(
        name="View",
        items=[
            ("Local", "Local Folder", "Local Folder"),
            ("Extracted", "Extracted Folder", "Extracted Game Folder"),
        ],
        default="Local",
    )

    mesh_scale: FloatProperty(name="Scale", default=100.0, min=0.001, max=10000.0)

    # Motlist Dialog Settings
    mot_current_dir: StringProperty(
        name="Motlist files from",
        default="",
        update=update_mot_dir,
    )
    mot_files: CollectionProperty(type=REFileItem)
    mot_files_idx: IntProperty(name="Mot File Index", default=0, update=update_mot_files_idx)

    motions: CollectionProperty(type=REMotionItem)
    motions_idx: IntProperty(name="Motions Index", default=0)

    motions_to_load: CollectionProperty(type=REMotionItem)
    motions_to_load_idx: IntProperty(name="Motions to load Index", default=0)

    force_center: BoolProperty(name="Force Center", default=False)
    sync_frame_count: BoolProperty(name="Sync by Frame Count", default=True)
    force_merge_all: BoolProperty(name="Force Merge All", default=False)
    enable_creature_vis_control: BoolProperty(
        name="Creature Visibility Control",
        description="Automatically drive dynamic part visibility (wings, beaks, legs, etc.) for endemic life. If unchecked, all mesh parts remain visible without procedural control for manual adjustment in Blender",
        default=True
    )
    mot_scale: FloatProperty(name="Scale", default=100.0, min=0.001, max=10000.0)


# =========================================================================
# Refresh Helpers
# =========================================================================

def refresh_mesh_file_list(context):
    settings = context.scene.re_settings
    settings.mesh_files.clear()
    settings.mesh_files_idx = 0

    current_dir = settings.mesh_current_dir
    if not os.path.isdir(current_dir):
        return

    # Add '..' to go to parent directory
    parent_item = settings.mesh_files.add()
    parent_item.name = ".."
    parent_item.full_path = os.path.dirname(os.path.abspath(current_dir))
    parent_item.is_dir = True

    try:
        entries = sorted(os.listdir(current_dir), key=lambda s: s.lower())
    except Exception:
        return

    # Add directories first
    for e in entries:
        full_p = os.path.join(current_dir, e)
        if os.path.isdir(full_p):
            it = settings.mesh_files.add()
            it.name = e
            it.full_path = full_p
            it.is_dir = True

    # Add mesh files
    mesh_found = False
    for e in entries:
        full_p = os.path.join(current_dir, e)
        if os.path.isfile(full_p) and ('.mesh' in e.lower()):
            it = settings.mesh_files.add()
            it.name = e
            it.full_path = full_p
            it.is_dir = False
            mesh_found = True

    # If no .mesh file exists in current directory but .mdf2 exists, detect sibling base mesh (e.g. ec009_00.mesh for ec009_01)
    if not mesh_found and any('.mdf2' in e.lower() for e in entries):
        parent_dir = os.path.dirname(os.path.abspath(current_dir))
        grandparent_dir = os.path.dirname(parent_dir)
        base_mod_dir = os.path.join(grandparent_dir, '00', 'mod')
        if not os.path.isdir(base_mod_dir):
            base_mod_dir = os.path.join(grandparent_dir, '00')
        if os.path.isdir(base_mod_dir):
            for e in os.listdir(base_mod_dir):
                if '.mesh' in e.lower():
                    variant_name = os.path.basename(parent_dir)
                    it = settings.mesh_files.add()
                    it.name = f"{e} (Variant {variant_name})"
                    it.full_path = os.path.join(base_mod_dir, e)
                    it.is_dir = False


def refresh_motlist_file_list(context):
    settings = context.scene.re_settings
    settings.mot_files.clear()
    settings.mot_files_idx = 0

    current_dir = settings.mot_current_dir
    if not os.path.isdir(current_dir):
        return

    parent_item = settings.mot_files.add()
    parent_item.name = ".."
    parent_item.full_path = os.path.dirname(os.path.abspath(current_dir))
    parent_item.is_dir = True

    try:
        entries = sorted(os.listdir(current_dir), key=lambda s: s.lower())
    except Exception:
        return

    for e in entries:
        full_p = os.path.join(current_dir, e)
        if os.path.isdir(full_p):
            it = settings.mot_files.add()
            it.name = e
            it.full_path = full_p
            it.is_dir = True

    for e in entries:
        full_p = os.path.join(current_dir, e)
        if os.path.isfile(full_p) and ('.motlist' in e.lower()):
            it = settings.mot_files.add()
            it.name = e
            it.full_path = full_p
            it.is_dir = False

    # Automatically load motions for first motlist if available
    refresh_motions_from_selected(context)


def refresh_motions_from_selected(context):
    settings = context.scene.re_settings
    settings.motions.clear()

    if settings.mot_files_idx < 0 or settings.mot_files_idx >= len(settings.mot_files):
        return

    selected = settings.mot_files[settings.mot_files_idx]
    if selected.is_dir or not os.path.isfile(selected.full_path):
        return

    try:
        motlist = REMotlist(selected.full_path)
    except Exception as e:
        print(f"[RE_Plugin] Failed to read motlist {selected.full_path}: {e}")
        return

    # Add [ALL] item first
    all_item = settings.motions.add()
    all_item.name = f"[ALL] - {os.path.basename(selected.full_path).split('.motlist')[0]}"
    all_item.frame_count = 0.0
    all_item.mot_index = -1
    all_item.motlist_path = selected.full_path

    for idx, mot in enumerate(motlist.mots):
        it = settings.motions.add()
        it.name = f"{mot.name} ({int(mot.frame_count)} frames)"
        it.frame_count = mot.frame_count
        it.mot_index = idx
        it.motlist_path = selected.full_path


# =========================================================================
# UI List Renderers
# =========================================================================

class RE_UL_file_list(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        if item.is_dir:
            row.label(text=item.name, icon='FILE_FOLDER')
            op_id = "re_mot.open_dir_item" if active_propname == 'mot_files_idx' else "re_mesh.open_dir_item"
            if item.name == "..":
                op = row.operator(op_id, text="上一级", icon='FILE_PARENT')
            else:
                op = row.operator(op_id, text="打开", icon='FORWARD')
            if op:
                op.index = index
                op.target_path = item.full_path
        else:
            icon_type = 'ACTION' if '.motlist' in item.name.lower() else 'MESH_DATA'
            row.label(text=item.name, icon=icon_type)
            if active_propname == 'mesh_files_idx':
                op = row.operator("re_mesh.add_load_direct", text="", icon='PLUS')
                if op:
                    op.index = index
                    op.target_path = item.full_path


class RE_UL_load_list(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.label(text=item.name, icon='CHECKMARK')


class RE_UL_motion_list(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        if item.mot_index == -1:
            row.label(text=item.name, icon='ACTION')
        else:
            row.label(text=item.name, icon='ANIM')

        if active_propname == 'motions_idx':
            op = row.operator("re_mot.add_motion_direct", text="", icon='PLUS')
            if op:
                op.index = index


# =========================================================================
# Operators for List Interactions & Direct 1-Click Actions
# =========================================================================

class RE_OT_browse_mesh_dir(Operator):
    bl_idname = "re_mesh.browse_dir"
    bl_label = "Browse Folder"
    bl_description = "Browse to select mesh directory"

    directory: StringProperty(name="Directory", subtype='DIR_PATH')

    def invoke(self, context, event):
        settings = context.scene.re_settings
        if settings.mesh_current_dir and os.path.isdir(settings.mesh_current_dir):
            self.directory = settings.mesh_current_dir
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if self.directory and os.path.isdir(self.directory):
            context.scene.re_settings.mesh_current_dir = self.directory
            refresh_mesh_file_list(context)
            save_saved_dirs(mesh_dir=self.directory)
        return {'FINISHED'}


class RE_OT_browse_mot_dir(Operator):
    bl_idname = "re_mot.browse_dir"
    bl_label = "Browse Folder"
    bl_description = "Browse to select motlist directory"

    directory: StringProperty(name="Directory", subtype='DIR_PATH')

    def invoke(self, context, event):
        settings = context.scene.re_settings
        if settings.mot_current_dir and os.path.isdir(settings.mot_current_dir):
            self.directory = settings.mot_current_dir
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if self.directory and os.path.isdir(self.directory):
            context.scene.re_settings.mot_current_dir = self.directory
            refresh_motlist_file_list(context)
            save_saved_dirs(mot_dir=self.directory)
        return {'FINISHED'}


class RE_OT_open_mesh_dir_item(Operator):
    bl_idname = "re_mesh.open_dir_item"
    bl_label = "Open Folder"
    bl_description = "Open this folder or return to parent directory"
    bl_options = {'INTERNAL'}

    index: IntProperty(default=0)
    target_path: StringProperty(default="")

    def execute(self, context):
        settings = context.scene.re_settings
        target = self.target_path
        if not target and 0 <= self.index < len(settings.mesh_files):
            sel = settings.mesh_files[self.index]
            if sel.is_dir:
                target = sel.full_path
        if target and os.path.isdir(target):
            settings.mesh_current_dir = target
            settings.mesh_files_idx = 0
            refresh_mesh_file_list(context)
            save_saved_dirs(mesh_dir=settings.mesh_current_dir)
        return {'FINISHED'}


class RE_OT_add_mesh_load_direct(Operator):
    bl_idname = "re_mesh.add_load_direct"
    bl_label = "Add to Load List"
    bl_description = "Add this mesh file to load list"
    bl_options = {'INTERNAL'}

    index: IntProperty(default=0)
    target_path: StringProperty(default="")

    def execute(self, context):
        settings = context.scene.re_settings
        target = self.target_path
        name = os.path.basename(target) if target else ""
        if not target and 0 <= self.index < len(settings.mesh_files):
            sel = settings.mesh_files[self.index]
            if not sel.is_dir:
                target = sel.full_path
                name = sel.name
        if target and os.path.isfile(target):
            existing = [item.full_path for item in settings.files_to_load]
            if target not in existing:
                it = settings.files_to_load.add()
                it.name = name or os.path.basename(target)
                it.full_path = target
                it.is_dir = False
                settings.files_to_load_idx = len(settings.files_to_load) - 1
        return {'FINISHED'}


class RE_OT_open_mot_dir_item(Operator):
    bl_idname = "re_mot.open_dir_item"
    bl_label = "Open Folder"
    bl_description = "Open this folder or return to parent directory"
    bl_options = {'INTERNAL'}

    index: IntProperty(default=0)
    target_path: StringProperty(default="")

    def execute(self, context):
        settings = context.scene.re_settings
        target = self.target_path
        if not target and 0 <= self.index < len(settings.mot_files):
            sel = settings.mot_files[self.index]
            if sel.is_dir:
                target = sel.full_path
        if target and os.path.isdir(target):
            settings.mot_current_dir = target
            settings.mot_files_idx = 0
            refresh_motlist_file_list(context)
            save_saved_dirs(mot_dir=settings.mot_current_dir)
        return {'FINISHED'}


class RE_OT_add_motion_direct(Operator):
    bl_idname = "re_mot.add_motion_direct"
    bl_label = "Add Motion"
    bl_description = "Add this motion to load list"
    bl_options = {'INTERNAL'}

    index: IntProperty(default=0)

    def execute(self, context):
        settings = context.scene.re_settings
        if 0 <= self.index < len(settings.motions):
            sel = settings.motions[self.index]
            if sel.mot_index == -1:
                # [ALL]
                existing_names = [it.name for it in settings.motions_to_load]
                for m in settings.motions:
                    if m.mot_index != -1 and m.name not in existing_names:
                        it = settings.motions_to_load.add()
                        it.name = m.name
                        it.frame_count = m.frame_count
                        it.mot_index = m.mot_index
                        it.motlist_path = m.motlist_path
                if len(settings.motions_to_load) > 0:
                    settings.motions_to_load_idx = len(settings.motions_to_load) - 1
            else:
                existing_names = [it.name for it in settings.motions_to_load]
                if sel.name not in existing_names:
                    it = settings.motions_to_load.add()
                    it.name = sel.name
                    it.frame_count = sel.frame_count
                    it.mot_index = sel.mot_index
                    it.motlist_path = sel.motlist_path
                    settings.motions_to_load_idx = len(settings.motions_to_load) - 1
        return {'FINISHED'}


class RE_OT_select_mesh_file(Operator):
    bl_idname = "re_mesh.select_file"
    bl_label = "Select File"
    bl_description = "Navigate or add selected file to load list"

    def execute(self, context):
        settings = context.scene.re_settings
        if settings.mesh_files_idx < 0 or settings.mesh_files_idx >= len(settings.mesh_files):
            return {'CANCELLED'}

        sel = settings.mesh_files[settings.mesh_files_idx]
        if sel.is_dir:
            settings.mesh_current_dir = sel.full_path
            settings.mesh_files_idx = 0
            refresh_mesh_file_list(context)
        else:
            # Add to files_to_load if not already present
            existing = [item.full_path for item in settings.files_to_load]
            if sel.full_path not in existing:
                it = settings.files_to_load.add()
                it.name = sel.name
                it.full_path = sel.full_path
                it.is_dir = False
                settings.files_to_load_idx = len(settings.files_to_load) - 1
        return {'FINISHED'}


class RE_OT_remove_mesh_load_item(Operator):
    bl_idname = "re_mesh.remove_load_item"
    bl_label = "Remove"
    bl_description = "Remove selected file from load list"

    def execute(self, context):
        settings = context.scene.re_settings
        idx = settings.files_to_load_idx
        if 0 <= idx < len(settings.files_to_load):
            settings.files_to_load.remove(idx)
            settings.files_to_load_idx = max(0, idx - 1)
        return {'FINISHED'}


class RE_OT_move_mesh_load_item(Operator):
    bl_idname = "re_mesh.move_load_item"
    bl_label = "Move"
    bl_description = "Move file up or down in load list"
    direction: bpy.props.EnumProperty(items=[('UP', "Up", ""), ('DOWN', "Down", "")])

    def execute(self, context):
        settings = context.scene.re_settings
        idx = settings.files_to_load_idx
        load_list = settings.files_to_load
        if self.direction == 'UP' and idx > 0:
            load_list.move(idx, idx - 1)
            settings.files_to_load_idx = idx - 1
        elif self.direction == 'DOWN' and idx < len(load_list) - 1:
            load_list.move(idx, idx + 1)
            settings.files_to_load_idx = idx + 1
        return {'FINISHED'}


class RE_OT_select_mot_file(Operator):
    bl_idname = "re_mot.select_file"
    bl_label = "Select Motlist File"
    bl_description = "Navigate or inspect selected motlist file"

    def execute(self, context):
        settings = context.scene.re_settings
        if settings.mot_files_idx < 0 or settings.mot_files_idx >= len(settings.mot_files):
            return {'CANCELLED'}

        sel = settings.mot_files[settings.mot_files_idx]
        if sel.is_dir:
            settings.mot_current_dir = sel.full_path
            settings.mot_files_idx = 0
            refresh_motlist_file_list(context)
        else:
            refresh_motions_from_selected(context)
        return {'FINISHED'}


class RE_OT_add_motion_to_load(Operator):
    bl_idname = "re_mot.add_motion_to_load"
    bl_label = "Add Motion"
    bl_description = "Add motion to load list"

    def execute(self, context):
        settings = context.scene.re_settings
        if settings.motions_idx < 0 or settings.motions_idx >= len(settings.motions):
            return {'CANCELLED'}

        sel = settings.motions[settings.motions_idx]
        if sel.mot_index == -1:
            # [ALL] selected: Add all individual motions from current motlist
            existing_names = [it.name for it in settings.motions_to_load]
            for m in settings.motions:
                if m.mot_index != -1 and m.name not in existing_names:
                    it = settings.motions_to_load.add()
                    it.name = m.name
                    it.frame_count = m.frame_count
                    it.mot_index = m.mot_index
                    it.motlist_path = m.motlist_path
        else:
            existing_names = [it.name for it in settings.motions_to_load]
            if sel.name not in existing_names:
                it = settings.motions_to_load.add()
                it.name = sel.name
                it.frame_count = sel.frame_count
                it.mot_index = sel.mot_index
                it.motlist_path = sel.motlist_path
                settings.motions_to_load_idx = len(settings.motions_to_load) - 1
        return {'FINISHED'}


class RE_OT_remove_motion_load_item(Operator):
    bl_idname = "re_mot.remove_motion_load_item"
    bl_label = "Remove"
    bl_description = "Remove motion from load list"

    def execute(self, context):
        settings = context.scene.re_settings
        idx = settings.motions_to_load_idx
        if 0 <= idx < len(settings.motions_to_load):
            settings.motions_to_load.remove(idx)
            settings.motions_to_load_idx = max(0, idx - 1)
        return {'FINISHED'}


class RE_OT_move_motion_load_item(Operator):
    bl_idname = "re_mot.move_motion_load_item"
    bl_label = "Move"
    bl_description = "Move motion up or down in load list"
    direction: bpy.props.EnumProperty(items=[('UP', "Up", ""), ('DOWN', "Down", "")])

    def execute(self, context):
        settings = context.scene.re_settings
        idx = settings.motions_to_load_idx
        load_list = settings.motions_to_load
        if self.direction == 'UP' and idx > 0:
            load_list.move(idx, idx - 1)
            settings.motions_to_load_idx = idx - 1
        elif self.direction == 'DOWN' and idx < len(load_list) - 1:
            load_list.move(idx, idx + 1)
            settings.motions_to_load_idx = idx + 1
        return {'FINISHED'}


# =========================================================================
# Main Dialog Operators
# =========================================================================

class WM_OT_re_mesh_import_dialog(Operator):
    """Import RE Engine Model Mesh (.mesh.*) with interactive dialog"""
    bl_idname = "import_scene.re_mesh"
    bl_label = "RE Engine '.mesh' Plugin"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH', default="")

    def invoke(self, context, event):
        settings = context.scene.re_settings

        # If user invoked with a specific filepath (e.g. from file browser)
        if self.filepath and os.path.exists(self.filepath):
            if os.path.isfile(self.filepath):
                settings.mesh_current_dir = os.path.dirname(self.filepath)
                settings.files_to_load.clear()
                it = settings.files_to_load.add()
                it.name = os.path.basename(self.filepath)
                it.full_path = self.filepath
            elif os.path.isdir(self.filepath):
                settings.mesh_current_dir = self.filepath
        else:
            saved_mesh, _ = load_saved_dirs()
            if settings.mesh_current_dir and os.path.isdir(settings.mesh_current_dir):
                pass
            elif saved_mesh and os.path.isdir(saved_mesh):
                settings.mesh_current_dir = saved_mesh
            else:
                settings.mesh_current_dir = os.path.expanduser("~")

        refresh_mesh_file_list(context)
        save_saved_dirs(mesh_dir=settings.mesh_current_dir)
        return context.window_manager.invoke_props_dialog(self, width=620)

    def cancel(self, context):
        settings = context.scene.re_settings
        if settings.mesh_current_dir and os.path.isdir(settings.mesh_current_dir):
            save_saved_dirs(mesh_dir=settings.mesh_current_dir)

    def draw(self, context):
        layout = self.layout
        settings = context.scene.re_settings

        # --- Top Section: Directory & File List ---
        top_box = layout.box()
        col = top_box.column(align=True)
        col.label(text="Mesh files from:")
        row = col.row(align=True)
        row.prop(settings, "mesh_current_dir", text="")
        row.operator("re_mesh.browse_dir", text="", icon='FILE_FOLDER')
        row.operator("re_mesh.select_file", text="Select / Enter", icon='FILE_TICK')

        col.template_list(
            "RE_UL_file_list",
            "mesh_files",
            settings,
            "mesh_files",
            settings,
            "mesh_files_idx",
            rows=6,
        )

        # --- Middle Section: Files to load ---
        mid_box = layout.box()
        col2 = mid_box.column(align=True)
        col2.label(text="Files to load:")

        row_list = col2.row(align=True)
        row_list.template_list(
            "RE_UL_load_list",
            "files_to_load",
            settings,
            "files_to_load",
            settings,
            "files_to_load_idx",
            rows=5,
        )

        col_arrows = row_list.column(align=True)
        op_up = col_arrows.operator("re_mesh.move_load_item", text="", icon='TRIA_UP')
        if op_up:
            op_up.direction = 'UP'
        op_down = col_arrows.operator("re_mesh.move_load_item", text="", icon='TRIA_DOWN')
        if op_down:
            op_down.direction = 'DOWN'
        col_arrows.separator()
        col_arrows.operator("re_mesh.remove_load_item", text="", icon='X')

        # --- Bottom Section: Options (Two Columns replicating original window) ---
        bot_box = layout.box()
        split = bot_box.split(factor=0.55)

        # Left column: checkboxes
        col_left = split.column(align=True)
        row_chk1 = col_left.row(align=True)
        row_chk1.prop(settings, "load_textures")
        row_chk1.prop(settings, "load_all_textures")

        row_chk2 = col_left.row(align=True)
        row_chk2.prop(settings, "convert_textures")
        row_chk2.prop(settings, "enable_emission")

        row_chk3 = col_left.row(align=True)
        row_chk3.prop(settings, "collapse_bones")

        # Right column: dropdowns & scale
        col_right = split.column(align=True)
        col_right.prop(settings, "game_selection")
        col_right.prop(settings, "view_selection")
        col_right.prop(settings, "mesh_scale")

    def execute(self, context):
        settings = context.scene.re_settings
        if settings.mesh_current_dir and os.path.isdir(settings.mesh_current_dir):
            save_saved_dirs(mesh_dir=settings.mesh_current_dir)

        items_to_import = [item.full_path for item in settings.files_to_load if os.path.isfile(item.full_path)]
        if not items_to_import:
            # Fallback to selected file in top list or operator filepath
            if 0 <= settings.mesh_files_idx < len(settings.mesh_files):
                sel = settings.mesh_files[settings.mesh_files_idx]
                if not sel.is_dir and os.path.isfile(sel.full_path):
                    items_to_import.append(sel.full_path)
            elif self.filepath and os.path.isfile(self.filepath):
                items_to_import.append(self.filepath)

        if not items_to_import:
            self.report({'WARNING'}, "No mesh files selected to load.")
            return {'CANCELLED'}

        import_scale = settings.mesh_scale / 100.0  # Normalize: 100.0 scale in dialog = 1.0 standard Blender meter unit

        opts = {
            'scale': import_scale,
            'load_textures': settings.load_textures,
            'load_all_textures': settings.load_all_textures,
            'enable_emission': settings.enable_emission,
            'convert_textures': settings.convert_textures,
            'collapse_bones': settings.collapse_bones,
            'game_name': settings.game_selection,
        }

        success_count = 0
        for f_path in items_to_import:
            try:
                item_opts = dict(opts)
                importer = REMeshImporter(f_path, item_opts)
                importer.execute(context)
                success_count += 1
            except Exception as e:
                self.report({'ERROR'}, f"Failed to import {os.path.basename(f_path)}: {e}")
                print(f"[RE_Plugin] Error importing {f_path}: {e}")

        self.report({'INFO'}, f"Successfully loaded {success_count} mesh files.")
        return {'FINISHED'}


class WM_OT_re_motlist_import_dialog(Operator):
    """Import RE Engine MotionList (.motlist.*) with interactive dialog"""
    bl_idname = "import_scene.re_motlist"
    bl_label = "RE Engine '.motlist' Plugin"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH', default="")

    def invoke(self, context, event):
        settings = context.scene.re_settings

        if self.filepath and os.path.exists(self.filepath):
            if os.path.isfile(self.filepath):
                settings.mot_current_dir = os.path.dirname(self.filepath)
                refresh_motlist_file_list(context)
                for idx, it in enumerate(settings.mot_files):
                    if it.full_path == self.filepath:
                        settings.mot_files_idx = idx
                        break
                refresh_motions_from_selected(context)
            elif os.path.isdir(self.filepath):
                settings.mot_current_dir = self.filepath
                refresh_motlist_file_list(context)
        else:
            _, saved_mot = load_saved_dirs()
            if settings.mot_current_dir and os.path.isdir(settings.mot_current_dir):
                pass
            elif saved_mot and os.path.isdir(saved_mot):
                settings.mot_current_dir = saved_mot
            else:
                settings.mot_current_dir = os.path.expanduser("~")
            refresh_motlist_file_list(context)

        save_saved_dirs(mot_dir=settings.mot_current_dir)
        return context.window_manager.invoke_props_dialog(self, width=620)

    def cancel(self, context):
        settings = context.scene.re_settings
        if settings.mot_current_dir and os.path.isdir(settings.mot_current_dir):
            save_saved_dirs(mot_dir=settings.mot_current_dir)

    def draw(self, context):
        layout = self.layout
        settings = context.scene.re_settings

        # Top: Motlist Files
        top_box = layout.box()
        col = top_box.column(align=True)
        col.label(text="Motlist files from:")
        row = col.row(align=True)
        row.prop(settings, "mot_current_dir", text="")
        row.operator("re_mot.browse_dir", text="", icon='FILE_FOLDER')
        row.operator("re_mot.select_file", text="Select / Enter", icon='FILE_TICK')

        col.template_list(
            "RE_UL_file_list",
            "mot_files",
            settings,
            "mot_files",
            settings,
            "mot_files_idx",
            rows=4,
        )

        # Middle: Motions in selected file
        mid_box = layout.box()
        col2 = mid_box.column(align=True)
        col2.label(text="Motions:")

        row_mots = col2.row(align=True)
        row_mots.template_list(
            "RE_UL_motion_list",
            "motions",
            settings,
            "motions",
            settings,
            "motions_idx",
            rows=6,
        )
        col_add = row_mots.column(align=True)
        col_add.operator("re_mot.add_motion_to_load", text="Add", icon='PLUS')

        # Middle Bottom: Motions to load
        mid2_box = layout.box()
        col3 = mid2_box.column(align=True)
        col3.label(text="Motions to load:")

        row_load = col3.row(align=True)
        row_load.template_list(
            "RE_UL_motion_list",
            "motions_to_load",
            settings,
            "motions_to_load",
            settings,
            "motions_to_load_idx",
            rows=4,
        )
        col_arrows = row_load.column(align=True)
        op_up = col_arrows.operator("re_mot.move_motion_load_item", text="", icon='TRIA_UP')
        if op_up:
            op_up.direction = 'UP'
        op_down = col_arrows.operator("re_mot.move_motion_load_item", text="", icon='TRIA_DOWN')
        if op_down:
            op_down.direction = 'DOWN'
        col_arrows.separator()
        col_arrows.operator("re_mot.remove_motion_load_item", text="", icon='X')

        # Bottom: Options
        bot_box = layout.box()
        split = bot_box.split(factor=0.55)

        col_left = split.column(align=True)
        col_left.prop(settings, "force_center")
        col_left.prop(settings, "sync_frame_count")
        col_left.prop(settings, "force_merge_all")
        col_left.prop(settings, "enable_creature_vis_control")

        col_right = split.column(align=True)
        col_right.prop(settings, "game_selection")
        col_right.prop(settings, "view_selection")
        col_right.prop(settings, "mot_scale")

    def execute(self, context):
        settings = context.scene.re_settings
        if settings.mot_current_dir and os.path.isdir(settings.mot_current_dir):
            save_saved_dirs(mot_dir=settings.mot_current_dir)

        # Find active or existing Armature object
        arm_obj = context.active_object if (context.active_object and context.active_object.type == 'ARMATURE') else None
        if not arm_obj:
            for obj in context.scene.objects:
                if obj.type == 'ARMATURE':
                    arm_obj = obj
                    break

        if not arm_obj:
            self.report({'ERROR'}, "No Armature found in scene to apply animations to. Please import or select a mesh armature first.")
            return {'CANCELLED'}

        # Determine which motions to load
        load_items = list(settings.motions_to_load)
        if not load_items and 0 <= settings.motions_idx < len(settings.motions):
            load_items = [settings.motions[settings.motions_idx]]

        import_scale = settings.mot_scale / 100.0
        loaded_motlists = {}
        created_actions = []

        if not load_items and self.filepath and os.path.isfile(self.filepath):
            motlist = REMotlist(self.filepath)
            for mot in motlist.mots:
                act = apply_motion_to_armature(
                    arm_obj,
                    mot,
                    scale=import_scale,
                    force_center=settings.force_center,
                    enable_vis_control=settings.enable_creature_vis_control,
                )
                if act:
                    created_actions.append(act)
            self.report({'INFO'}, f"Successfully created {len(created_actions)} animation actions on {arm_obj.name}.")
            return {'FINISHED'}

        if not load_items:
            self.report({'WARNING'}, "No motions selected to load.")
            return {'CANCELLED'}

        first_action = None
        for item in load_items:
            m_path = item.motlist_path
            if not m_path or not os.path.isfile(m_path):
                continue

            if m_path not in loaded_motlists:
                loaded_motlists[m_path] = REMotlist(m_path)
            motlist_obj = loaded_motlists[m_path]

            target_mots = []
            if item.mot_index == -1:
                target_mots = motlist_obj.mots
            elif 0 <= item.mot_index < len(motlist_obj.mots):
                target_mots = [motlist_obj.mots[item.mot_index]]

            for m in target_mots:
                try:
                    act = apply_motion_to_armature(
                        arm_obj,
                        m,
                        scale=import_scale,
                        force_center=settings.force_center,
                        enable_vis_control=settings.enable_creature_vis_control,
                    )
                    if act:
                        act.use_fake_user = True
                        created_actions.append(act)
                        if first_action is None:
                            first_action = act
                except Exception as e:
                    print(f"[RE_Plugin] Failed to bake motion {m.name}: {e}")

        # Keep the first action active so user can preview the primary animation immediately
        if first_action and arm_obj and arm_obj.animation_data:
            arm_obj.animation_data.action = first_action

        self.report({'INFO'}, f"Successfully created {len(created_actions)} animation actions on {arm_obj.name}.")
        return {'FINISHED'}


# =========================================================================
# Registration
# =========================================================================

classes = (
    REFileItem,
    REMotionItem,
    RESettings,
    RE_UL_file_list,
    RE_UL_load_list,
    RE_UL_motion_list,
    RE_OT_browse_mesh_dir,
    RE_OT_browse_mot_dir,
    RE_OT_open_mesh_dir_item,
    RE_OT_add_mesh_load_direct,
    RE_OT_open_mot_dir_item,
    RE_OT_add_motion_direct,
    RE_OT_select_mesh_file,
    RE_OT_remove_mesh_load_item,
    RE_OT_move_mesh_load_item,
    RE_OT_select_mot_file,
    RE_OT_add_motion_to_load,
    RE_OT_remove_motion_load_item,
    RE_OT_move_motion_load_item,
    WM_OT_re_mesh_import_dialog,
    WM_OT_re_motlist_import_dialog,
)


def register_ui():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.re_settings = bpy.props.PointerProperty(type=RESettings)


def unregister_ui():
    if hasattr(bpy.types.Scene, 're_settings'):
        try:
            del bpy.types.Scene.re_settings
        except Exception:
            pass
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
