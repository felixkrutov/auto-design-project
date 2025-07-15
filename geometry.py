import ifcopenshell
import ifcopenshell.api
import ifcopenshell.guid
import time

def create_element(f, context, name, placement, w, d, h, style=None):
    owner_history = f.by_type("IfcOwnerHistory")[0]
    
    profile = f.createIfcRectangleProfileDef('AREA', name + "_profile", None, w, d)
    extrusion_placement = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)))
    extrusion_direction = f.createIfcDirection((0.0, 0.0, 1.0))
    extrusion = f.createIfcExtrudedAreaSolid(profile, extrusion_placement, extrusion_direction, h)
    
    shape_rep = f.createIfcShapeRepresentation(context, 'Body', 'SweptSolid', [extrusion])
    product_shape = f.createIfcProductDefinitionShape(None, None, [shape_rep])

    element_type = name.split('_')[0]
    if "Стена" in element_type:
        element = f.createIfcWall(ifcopenshell.guid.new(), owner_history, name, ObjectPlacement=placement, Representation=product_shape)
    elif "Пол" in element_type:
        element = f.createIfcSlab(ifcopenshell.guid.new(), owner_history, name, ObjectPlacement=placement, Representation=product_shape, PredefinedType='FLOOR')
    else:
        element = f.createIfcBuildingElementProxy(ifcopenshell.guid.new(), owner_history, name, ObjectPlacement=placement, Representation=product_shape)

    if style:
        ifcopenshell.api.run("style.assign_style", f, product=element, style=style)
    
    return element

def create_3d_model(project_data: dict, placements: dict, output_filename: str):
    print("\n5. Создание 3D модели (IFC)...")
    
    f = ifcopenshell.file(schema="IFC4")
    
    person = f.createIfcPerson(None, "Automation", None, None, None, None, None, None) 
    
    organization = f.createIfcOrganization(None, "AutoDesign Inc.", None, None, None)
    
    application = f.createIfcApplication(
        organization, 
        "0.7.0",      
        "IfcOpenShell (AutoDesign)", 
        "IfcOpenShell (AutoDesign)"  
    )
    
    current_timestamp = int(time.time()) 
    owner_history = f.createIfcOwnerHistory(
        person,                     
        application,                
        None,                       
        'ADDED',                    
        current_timestamp,          
        None,                       
        None,                       
        current_timestamp           
    )
    
    project = f.createIfcProject(
        ifcopenshell.guid.new(),    
        owner_history,              
        project_data['meta']['project_name'], 
        None,                       
        None,                       
        None,                       
        None,                       
        None,                       
        None                        
    )
    
    context = ifcopenshell.api.run("context.add_context", f, 
                                   context_type="Model", 
                                   target_view="MODEL_VIEW", 
                                   context_identifier="Body")

    length_unit = f.createIfcSIUnit("LENGTHUNIT", None, "METRE")
    unit_assignment = f.createIfcUnitAssignment([length_unit])
    project.UnitsInContext = unit_assignment

    ifcopenshell.api.run("context.assign_context", f, 
                          product_representation=context, 
                          relating_context=project)
    
    site = f.createIfcSite(ifcopenshell.guid.new(), owner_history, "Участок")
    building = f.createIfcBuilding(ifcopenshell.guid.new(), owner_history, "Производственный корпус")
    storey = f.createIfcBuildingStorey(ifcopenshell.guid.new(), owner_history, "Первый этаж")
    ifcopenshell.api.run("aggregate.assign_object", f, relating_object=project, product=site)
    ifcopenshell.api.run("aggregate.assign_object", f, relating_object=site, product=building)
    ifcopenshell.api.run("aggregate.assign_object", f, relating_object=building, product=storey)

    def P(x, y, z):
        return f.createIfcCartesianPoint((float(x), float(y), float(z)))

    print("   - Создание стилей материалов...")
    def create_style(name, r, g, b):
        style = ifcopenshell.api.run("style.add_style", f)
        ifcopenshell.api.run(
            "style.add_surface_style",
            f,
            style=style,
            ifc_class="IfcSurfaceStyleShading",
            attributes={"SurfaceColour": f.createIfcColourRgb(name, r, g, b)},
        )
        return style

    styles_map = {
        "floor_style": create_style("FloorStyle", 0.4, 0.4, 0.8),
        "wall_style": create_style("WallStyle", 0.7, 0.7, 0.7),
        "silos_style": create_style("SilosStyle", 0.8, 0.8, 0.8),
        "mixer_style": create_style("MixerStyle", 0.9, 0.9, 0.6),
        "press_style": create_style("PressStyle", 0.6, 0.9, 0.6),
        "default_style": create_style("DefaultStyle", 0.9, 0.5, 0.5)
    }
    
    all_elements = []
    print("   - Создание архитектуры (пол, стены)...")
    arch_data = project_data.get('architecture', {})
    room_dims = arch_data.get('room_dimensions', {})
    wall_t = arch_data.get('wall_thickness', 0.2)
    w, d, h = room_dims.get('width'), room_dims.get('depth'), room_dims.get('height')

    if all([w, d, h]):
        floor_pos = P(0.0, 0.0, 0.0)
        floor_placement = f.createIfcLocalPlacement(storey.ObjectPlacement, f.createIfcAxis2Placement3D(floor_pos))
        floor = create_element(f, context, "Пол", floor_placement, w, d, -wall_t, style=styles_map["floor_style"])
        all_elements.append(floor)
        
        walls_def = [
            {'name': 'Стена_Юг',    'pos': P(0.0, 0.0, 0.0), 'dims': (w, wall_t, h)},
            {'name': 'Стена_Север',  'pos': P(0.0, d - wall_t, 0.0), 'dims': (w, wall_t, h)},
            {'name': 'Стена_Запад',  'pos': P(0.0, 0.0, 0.0), 'dims': (wall_t, d, h)},
            {'name': 'Стена_Восток', 'pos': P(w - wall_t, 0.0, 0.0), 'dims': (wall_t, d, h)}
        ]
        for w_def in walls_def:
            wall_placement = f.createIfcLocalPlacement(storey.ObjectPlacement, f.createIfcAxis2Placement3D(w_def['pos']))
            wall = create_element(f, context, w_def['name'], wall_placement, *w_def['dims'], style=styles_map["wall_style"])
            all_elements.append(wall)

    print("   - Размещение оборудования...")
    equipment_map = {eq['id']: eq for eq in project_data['equipment']}
    for eq_id, placement in placements.items():
        eq_data = equipment_map.get(eq_id)
        eq_w, eq_d, eq_h = eq_data['footprint']['width'], eq_data['footprint']['depth'], eq_data['height']
        pos = P(float(placement['x']), float(placement['y']), 0.0)
        
        eq_placement = f.createIfcLocalPlacement(storey.ObjectPlacement, f.createIfcAxis2Placement3D(pos))
        
        eq_name_lower = eq_data['name'].lower()
        if "силос" in eq_name_lower: eq_style = styles_map["silos_style"]
        elif "смеситель" in eq_name_lower: eq_style = styles_map["mixer_style"]
        elif "пресс" in eq_name_lower: eq_style = styles_map["press_style"]
        else: eq_style = styles_map["default_style"]

        element = create_element(f, context, eq_data['name'], eq_placement, eq_w, eq_d, eq_h, style=eq_style)
        all_elements.append(element)
        print(f"     - Создан объект: '{eq_data['name']}'")

    if all_elements:
        ifcopenshell.api.run("spatial.assign_container", f, products=all_elements, relating_structure=storey)

    f.write(output_filename)
    print(f"   > Модель успешно сохранена в файл: {output_filename}")
