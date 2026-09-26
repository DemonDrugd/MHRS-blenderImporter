# -*- coding: utf-8 -*-
"""
MHRS-blenderImporter
--------------------
A Blender add-on for importing .mesh.xx model files, materials (.mdf2.xx),
textures (.tex.xx) and animations (.motlist.xx) from Monster Hunter Rise / Sunbreak
and other Capcom RE Engine / RE Framework games.

Author: DemonDrug
Credits: Based on RE Engine format specifications by alphaZomega & Gh0stblade
License: MIT
"""

bl_info = {
    "name": "MHRS-blenderImporter",
    "author": "DemonDrug",
    "version": (1, 1, 0),
    "blender": (3, 6, 0),
    "location": "File > Import > MHRS Mesh (.mesh.*) / MotionList (.motlist.*)",
    "description": "This is a Blender add-on used for importing .mesh.xx model files and .motlist.xx animation files from Monster Hunter Rise（Sunbreak and other RE framework games).",
    "warning": "",
    "doc_url": "https://github.com/DemonDrug/MHRS-blenderImporter",
    "tracker_url": "https://github.com/DemonDrug/MHRS-blenderImporter/issues",
    "category": "Import-Export",
}

import bpy
from .re_ui import (
    register_ui,
    unregister_ui,
    WM_OT_re_mesh_import_dialog,
    WM_OT_re_motlist_import_dialog,
)


def menu_func_import_mesh(self, context):
    self.layout.operator(
        WM_OT_re_mesh_import_dialog.bl_idname,
        text="MHRS Mesh (.mesh.*)",
        icon='MESH_DATA',
    )


def menu_func_import_motlist(self, context):
    self.layout.operator(
        WM_OT_re_motlist_import_dialog.bl_idname,
        text="MHRS MotionList (.motlist.*)",
        icon='ANIM',
    )


def register():
    register_ui()
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import_mesh)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import_motlist)
    print(f"[{bl_info['name']}] v{'.'.join(map(str, bl_info['version']))} registered successfully.")


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import_mesh)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import_motlist)
    unregister_ui()
    print(f"[{bl_info['name']}] unregistered.")


if __name__ == "__main__":
    register()
