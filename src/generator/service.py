import ifcopenshell
import ifcopenshell.api
import ifcopenshell.guid
import ifcopenshell.geom
import time
import logging
from typing import Dict

from src.core.models import Project, EquipmentItem

# Suppress informational messages from ifcopenshell.api, leaving only errors
logging.getLogger('ifcopenshell').setLevel(logging.ERROR)

# Attempt to import pythonOCC. If unavailable, simplified geometry will be used.
try:
    from OCC.Core.gp import gp_Pnt, gp_Dir, gp_Ax2
    from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeCone
    OCC_AVAILABLE = True
except ImportError:
    logging.warning("pythonOCC not found. Complex geometry for silos will be replaced by simple boxes.")
    OCC_AVAILABLE = False

def create_surface_style(f: ifcopenshell.file, name: str, r: float, g: float, b: float, transparency: float = 0.0):
    """
    Creates and returns an IfcSurfaceStyle using direct entity creation.
    """
    rendering = f.create_entity(
        "IfcSurfaceStyleRendering",
        SurfaceColour=f.createIfcColourRgb(None, r, g, b),
        Transparency=transparency,
    )
    style = f.create_entity(
        "IfcSurfaceStyle", Name=name, Side="BOTH", Styles=[rendering]
    )
    return style

def apply_style_to_representation(f: ifcopenshell.file, representation, style):
    """
    Applies a style to the items of a shape representation.
    """
    if not style or not representation or not representation.Items:
        return
        
    f.create_entity(
        "IfcStyledItem",
        Item=representation.Items[0],
        Styles=[f.create_entity("IfcPresentationStyleAssignment", Styles=[style])],
    )

def create_element(f: ifcopenshell.file, context, name: str, placement, w: float, d: float, h: float, style=None):
    """
    Creates an IFC element. If the name contains "silos" and pythonOCC is available,
    it creates complex geometry. Otherwise, it creates a simple extruded box.
    """
    owner_history = f.by_type("IfcOwnerHistory")[0]
    
    if "силос" in name.lower() and OCC_AVAILABLE:
        product = f.createIfcBuildingElementProxy(ifcopenshell.guid.new(), owner_history, name, None, None, placement, None, None)
        
        radius = min(w, d) / 2.0
        cylinder_height = h * 0.8
        cone_height = h * 0.2
        base_platform_height = 0.15

        representations = []
        settings = ifcopenshell.geom.settings()
        settings.set(settings.STRICT_TOLERANCE, True)

        cyl_axis = gp_Ax2(gp_Pnt(0.0, 0.0, cone_height), gp_Dir(0.0, 0.0, 1.0))
        occ_cylinder = BRepPrimAPI_MakeCylinder(cyl_axis, radius, cylinder_height).Shape()
        ifc_cyl_geom = ifcopenshell.geom.create_shape(f, occ_cylinder, settings).geometry
        
        cyl_rep = f.createIfcShapeRepresentation(
            ContextOfItems=context, RepresentationIdentifier="Body", RepresentationType="Brep", Items=ifc_cyl_geom
        )
        silo_body_style = create_surface_style(f, "Silo Body", 0.8, 0.82, 0.84)
        apply_style_to_representation(f, cyl_rep, silo_body_style)
        representations.append(cyl_rep)

        cone_axis = gp_Ax2(gp_Pnt(0.0, 0.0, 0.0), gp_Dir(0.0, 0.0, 1.0))
        occ_cone = BRepPrimAPI_MakeCone(cone_axis, radius, 0.0, cone_height).Shape()
        ifc_cone_geom = ifcopenshell.geom.create_shape(f, occ_cone, settings).geometry

        cone_rep = f.createIfcShapeRepresentation(
            ContextOfItems=context, RepresentationIdentifier="Hopper", RepresentationType="Brep", Items=ifc_cone_geom
        )
        hopper_style = create_surface_style(f, "Silo Hopper", 0.5, 0.5, 0.5)
        apply_style_to_representation(f, cone_rep, hopper_style)
        representations.append(cone_rep)
        
        base_profile = f.createIfcRectangleProfileDef('AREA', "Base_Profile", None, w, d)
        base_pos = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, -base_platform_height)))
        base_extrusion = f.createIfcExtrudedAreaSolid(
            SweptArea=base_profile, 
            Position=base_pos, 
            ExtrudedDirection=f.createIfcDirection((0.0, 0.0, 1.0)), 
            Depth=base_platform_height
        )
        base_rep = f.createIfcShapeRepresentation(
            ContextOfItems=context, RepresentationIdentifier="Base", RepresentationType="SweptSolid", Items=[base_extrusion]
        )
        base_style = create_surface_style(f, "Concrete Base", 0.6, 0.6, 0.6)
        apply_style_to_representation(f, base_rep, base_style)
        representations.append(base_rep)

        product.Representation = f.createIfcProductDefinitionShape(None, None, representations)
        return product

    else:
        profile = f.createIfcRectangleProfileDef('AREA', name + "_profile", None, w, d)
        extrusion_placement = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)))
        extrusion_direction = f.createIfcDirection((0.0, 0.0, 1.0))
        extrusion = f.createIfcExtrudedAreaSolid(profile, extrusion_placement, extrusion_direction, abs(h))
        
        shape_rep = f.createIfcShapeRepresentation(context, 'Body', 'SweptSolid', [extrusion])
        product_shape = f.createIfcProductDefinitionShape(None, None, [shape_rep])

        element_type = name.split('_')[0]
        if "Стена" in element_type:
            element = f.createIfcWall(ifcopenshell.guid.new(), owner_history, name, None, None, placement, product_shape, None)
        elif "Пол" in element_type:
            placement.RelativePlacement.Location.Coordinates = (placement.RelativePlacement.Location.Coordinates[0], placement.RelativePlacement.Location.Coordinates[1], h)
            element = f.createIfcSlab(ifcopenshell.guid.new(), owner_history, name, None, None, placement, product_shape, None, 'FLOOR')
        else:
            element = f.createIfcBuildingElementProxy(ifcopenshell.guid.new(), owner_history, name, None, None, placement, product_shape, None)

        if style:
            apply_style_to_representation(f, shape_rep, style)
        
        return element

def create_3d_model(project: Project, placements: Dict[str, Dict[str, float]], output_filename: str):
    """
    Generates the final IFC 3D model from the validated project data and calculated placements.
    """
    print("\n5. Creating 3D model (IFC)...")
    
    f = ifcopenshell.file(schema="IFC4")
    
    owner_history = f.createIfcOwnerHistory(f.createIfcPersonAndOrganization(), f.createIfcApplication(), None, 'ADDED', int(time.time()))
    ifc_project = f.createIfcProject(ifcopenshell.guid.new(), owner_history, project.meta.project_name)
    
    context = ifcopenshell.api.run("context.add_context", f, context_type="Model", target_view="MODEL_VIEW", context_identifier="Body")
    ifcopenshell.api.run("unit.assign_unit", f)
    ifc_project.RepresentationContexts = [context]
    
    site = f.createIfcSite(ifcopenshell.guid.new(), owner_history, "Site")
    building = f.createIfcBuilding(ifcopenshell.guid.new(), owner_history, "Factory Building")
    storey = f.createIfcBuildingStorey(ifcopenshell.guid.new(), owner_history, "Ground Floor")
    ifcopenshell.api.run("aggregate.assign_object", f, relating_object=ifc_project, products=[site])
    ifcopenshell.api.run("aggregate.assign_object", f, relating_object=site, products=[building])
    ifcopenshell.api.run("aggregate.assign_object", f, relating_object=building, products=[storey])

    def P(x, y, z): return f.createIfcCartesianPoint((float(x), float(y), float(z)))

    print("   - Creating material styles...")
    styles_map = {
        "floor_style": create_surface_style(f, "FloorStyle", 0.4, 0.4, 0.45, transparency=0.0),
        "wall_style": create_surface_style(f, "WallStyle", 0.75, 0.75, 0.75, transparency=0.0),
        "roof_style": create_surface_style(f, "RoofStyle", 0.2, 0.6, 0.3, transparency=0.0),
        "mixer_style": create_surface_style(f, "MixerStyle", 0.9, 0.9, 0.6),
        "press_style": create_surface_style(f, "PressStyle", 0.6, 0.9, 0.6),
        "default_style": create_surface_style(f, "DefaultStyle", 0.9, 0.5, 0.5)
    }
    
    all_elements = []
    print("   - Creating architecture (floor, walls, roof)...")
    
    # Access architecture data safely from the Pydantic model
    arch = project.architecture
    room = arch.room_dimensions
    wall_t = max(0.5, arch.wall_thickness)
    slab_t = 0.2
    w, d, h = room.width, room.depth, room.height

    floor_placement = f.createIfcLocalPlacement(storey.ObjectPlacement, f.createIfcAxis2Placement3D(P(0.0, 0.0, 0.0)))
    floor = create_element(f, context, "Пол", floor_placement, w, d, -slab_t, style=styles_map["floor_style"])
    all_elements.append(floor)
    
    walls_def = [
        {'name': 'Стена_Юг', 'pos': P(0.0, 0.0, 0.0), 'dims': (w, wall_t, h)},
        {'name': 'Стена_Север', 'pos': P(0.0, d - wall_t, 0.0), 'dims': (w, wall_t, h)},
        {'name': 'Стена_Запад', 'pos': P(0.0, 0.0, 0.0), 'dims': (wall_t, d, h)},
        {'name': 'Стена_Восток', 'pos': P(w - wall_t, 0.0, 0.0), 'dims': (wall_t, d, h)}
    ]
    for w_def in walls_def:
        wall_placement = f.createIfcLocalPlacement(storey.ObjectPlacement, f.createIfcAxis2Placement3D(w_def['pos']))
        wall = create_element(f, context, w_def['name'], wall_placement, *w_def['dims'], style=styles_map["wall_style"])
        all_elements.append(wall)

    print("     - Creating roof...")
    gable_height = w / 4.0
    
    profile_points = [P(0.0, 0.0, 0.0), P(w, 0.0, 0.0), P(w / 2.0, 0.0, gable_height)]
    polyline = f.createIfcPolyline(profile_points)
    closed_profile = f.createIfcArbitraryClosedProfileDef("AREA", "Roof_Profile", polyline)
    
    extrusion_dir = f.createIfcDirection((0.0, 1.0, 0.0))
    roof_extrusion = f.createIfcExtrudedAreaSolid(closed_profile, None, extrusion_dir, d)
    
    roof_placement_3d = f.createIfcAxis2Placement3D(P(0.0, 0.0, h))
    roof_placement = f.createIfcLocalPlacement(building.ObjectPlacement, roof_placement_3d)
    
    shape_rep = f.createIfcShapeRepresentation(context, "Body", "SweptSolid", [roof_extrusion])
    apply_style_to_representation(f, shape_rep, styles_map["roof_style"])
    product_shape = f.createIfcProductDefinitionShape(None, None, [shape_rep])
    
    roof = f.createIfcRoof(ifcopenshell.guid.new(), owner_history, "Крыша", None, None, roof_placement, product_shape, "GABLE_ROOF")
    ifcopenshell.api.run("aggregate.assign_object", f, relating_object=building, products=[roof])

    print("   - Placing equipment...")
    # Create a mapping from equipment ID to the EquipmentItem object for easy lookup
    equipment_map: Dict[str, EquipmentItem] = {eq.id: eq for eq in project.equipment}
    
    for eq_id, placement in placements.items():
        eq_data = equipment_map.get(eq_id)
        if not eq_data: continue

        # Access equipment data safely from the Pydantic model
        eq_w = eq_data.footprint.width
        eq_d = eq_data.footprint.depth
        eq_h = eq_data.height
        pos = P(placement['x'], placement['y'], 0.0)
        
        eq_placement = f.createIfcLocalPlacement(storey.ObjectPlacement, f.createIfcAxis2Placement3D(pos))
        
        eq_style = None
        eq_name_lower = eq_data.name.lower()
        if "силос" not in eq_name_lower:
            if "смеситель" in eq_name_lower: eq_style = styles_map["mixer_style"]
            elif "пресс" in eq_name_lower: eq_style = styles_map["press_style"]
            else: eq_style = styles_map["default_style"]

        element = create_element(f, context, eq_data.name, eq_placement, eq_w, eq_d, eq_h, style=eq_style)
        all_elements.append(element)
        print(f"     - Created object: '{eq_data.name}'")

    if all_elements:
        ifcopenshell.api.run("spatial.assign_container", f, products=all_elements, relating_structure=storey)

    f.write(output_filename)
    print(f"   > Model successfully saved to file: {output_filename}")
