# --- ПОЛНЫЙ И ОКОНЧАТЕЛЬНО ИСПРАВЛЕННЫЙ КОД ДЛЯ geometry.py ---
import ifcopenshell
import ifcopenshell.api
import ifcopenshell.guid
import time

def create_style(f, name, r, g, b):
    """Вспомогательная функция для создания цветового стиля."""
    color = f.createIfcColourRgb(name, r, g, b)
    shading = f.createIfcSurfaceStyleShading(color, 0.0) # 0.0 for transparency
    style = f.createIfcSurfaceStyle(name, 'BOTH', [shading])
    return style

def create_element(f, context, name, placement, w, d, h, style=None):
    """Вспомогательная функция для создания одного элемента (ящика) с применением стиля."""
    profile = f.createIfcRectangleProfileDef('AREA', name + "_profile", None, w, d)
    extrusion_placement = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)))
    extrusion_direction = f.createIfcDirection((0.0, 0.0, 1.0))
    extrusion = f.createIfcExtrudedAreaSolid(profile, extrusion_placement, extrusion_direction, h)
    
    # Применение стиля, если он предоставлен
    if style:
        style_assignment = f.createIfcPresentationStyleAssignment([style])
        styled_item = f.createIfcStyledItem(extrusion, [style_assignment], None)
        shape_rep = f.createIfcShapeRepresentation(context, 'Body', 'StyledByItem', [styled_item])
    else:
        shape_rep = f.createIfcShapeRepresentation(context, 'Body', 'SweptSolid', [extrusion])
        
    product_shape = f.createIfcProductDefinitionShape(None, None, [shape_rep])
    owner_history = f.by_type("IfcOwnerHistory")[0]
    
    element_type = name.split('_')[0]

    if "Стена" in element_type:
        element = f.createIfcWall(ifcopenshell.guid.new(), owner_history, name, ObjectPlacement=placement, Representation=product_shape)
    elif "Пол" in element_type:
        element = f.createIfcSlab(ifcopenshell.guid.new(), owner_history, name, ObjectPlacement=placement, Representation=product_shape, PredefinedType='FLOOR')
    else:
        element = f.createIfcBuildingElementProxy(ifcopenshell.guid.new(), owner_history, name, ObjectPlacement=placement, Representation=product_shape)
    
    return element

def create_3d_model(project_data: dict, placements: dict, output_filename: str):
    print("\n5. Создание 3D модели (IFC)...")
    
    f = ifcopenshell.file(schema="IFC4")
    owner_history = f.createIfcOwnerHistory(f.createIfcPersonAndOrganization(f.createIfcPerson(), f.createIfcOrganization(Name="AutoDesign")), f.createIfcApplication(f.createIfcOrganization(Name="GeneratorV2"), "2.0", "GeneratorV2", "G2"), CreationDate=int(time.time()))
    
    def P(x, y, z):
        return f.createIfcCartesianPoint((float(x), float(y), float(z)))
        
    project = f.createIfcProject(ifcopenshell.guid.new(), owner_history, project_data['meta']['project_name'])
    context = f.createIfcGeometricRepresentationContext(None, "Model", 3, 1.0E-5, f.createIfcAxis2Placement3D(P(0.0, 0.0, 0.0)))
    project.RepresentationContexts = [context]
    site = f.createIfcSite(ifcopenshell.guid.new(), owner_history, "Участок")
    building = f.createIfcBuilding(ifcopenshell.guid.new(), owner_history, "Производственный корпус")
    storey = f.createIfcBuildingStorey(ifcopenshell.guid.new(), owner_history, "Первый этаж")
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, None, None, project, [site])
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, None, None, site, [building])
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, None, None, building, [storey])
    
    # --- Создание стилей (цветов) ---
    print("   - Создание стилей материалов...")
    styles_map = {
        "floor_style": create_style(f, "FloorStyle", 0.4, 0.4, 0.8), # Синий
        "wall_style": create_style(f, "WallStyle", 0.7, 0.7, 0.7),   # Серый
        "silos_style": create_style(f, "SilosStyle", 0.8, 0.8, 0.8), # Светло-серый
        "mixer_style": create_style(f, "MixerStyle", 0.9, 0.9, 0.6), # Бежевый
        "press_style": create_style(f, "PressStyle", 0.6, 0.9, 0.6), # Светло-зеленый
        "default_style": create_style(f, "DefaultStyle", 0.9, 0.5, 0.5) # Красноватый
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
        
        # Выбор стиля на основе имени
        eq_name_lower = eq_data['name'].lower()
        if "силос" in eq_name_lower: eq_style = styles_map["silos_style"]
        elif "смеситель" in eq_name_lower: eq_style = styles_map["mixer_style"]
        elif "пресс" in eq_name_lower: eq_style = styles_map["press_style"]
        else: eq_style = styles_map["default_style"]

        element = create_element(f, context, eq_data['name'], eq_placement, eq_w, eq_d, eq_h, style=eq_style)
        all_elements.append(element)
        print(f"     - Создан объект: '{eq_data['name']}'")

    if all_elements:
        f.createIfcRelContainedInSpatialStructure(ifcopenshell.guid.new(), owner_history, "Содержимое этажа", None, all_elements, storey)

    f.write(output_filename)
    print(f"   > Модель успешно сохранена в файл: {output_filename}")
