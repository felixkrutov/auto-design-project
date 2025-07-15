# --- ПОЛНЫЙ И ОКОНЧАТЕЛЬНО ИСПРАВЛЕННЫЙ КОД ДЛЯ geometry.py ---
import ifcopenshell
import ifcopenshell.api
import ifcopenshell.guid
import time

def create_style(f, name, r, g, b):
    """Вспомогательная функция для создания цветового стиля."""
    color = f.createIfcColourRgb(name, r, g, b)
    shading = f.createIfcSurfaceStyleShading(color, 0.0)
    style = f.createIfcSurfaceStyle(name, 'BOTH', [shading])
    return style

def create_element(f, context, name, placement, w, d, h, style=None):
    """Вспомогательная функция для создания одного элемента с применением стиля через API."""
    # 1. Создаем геометрию
    profile = f.createIfcRectangleProfileDef('AREA', name + "_profile", None, w, d)
    extrusion_placement = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)))
    extrusion_direction = f.createIfcDirection((0.0, 0.0, 1.0))
    extrusion = f.createIfcExtrudedAreaSolid(profile, extrusion_placement, extrusion_direction, h)
    
    # 2. Создаем представление
    shape_rep = f.createIfcShapeRepresentation(context, 'Body', 'SweptSolid', [extrusion])
    product_shape = f.createIfcProductDefinitionShape(None, None, [shape_rep])
    owner_history = f.by_type("IfcOwnerHistory")[0]
    
    # 3. Создаем сам продукт (элемент)
    element_type = name.split('_')[0]
    if "Стена" in element_type:
        element = f.createIfcWall(ifcopenshell.guid.new(), owner_history, name, ObjectPlacement=placement, Representation=product_shape)
    elif "Пол" in element_type:
        element = f.createIfcSlab(ifcopenshell.guid.new(), owner_history, name, ObjectPlacement=placement, Representation=product_shape, PredefinedType='FLOOR')
    else:
        element = f.createIfcBuildingElementProxy(ifcopenshell.guid.new(), owner_history, name, ObjectPlacement=placement, Representation=product_shape)

    # 4. Применяем стиль к готовому элементу с помощью корректного API вызова
    if style:
        ifcopenshell.api.run("style.assign_style", f, product=element, style=style)
    
    return element

def create_3d_model(project_data: dict, placements: dict, output_filename: str):
    print("\n5. Создание 3D модели (IFC)...")
    
    f = ifcopenshell.file(schema="IFC4")
    # Инициализация API для файла
    ifcopenshell.api.run("project.create_file", f)
    owner_history = f.by_type("IfcOwnerHistory")[0]
    
    def P(x, y, z):
        return f.createIfcCartesianPoint((float(x), float(y), float(z)))
        
    project = f.by_type("IfcProject")[0]
    project.Name = project_data['meta']['project_name']
    
    context = f.by_type("IfcGeometricRepresentationContext")[0]
    site = f.createIfcSite(ifcopenshell.guid.new(), owner_history, "Участок")
    building = f.createIfcBuilding(ifcopenshell.guid.new(), owner_history, "Производственный корпус")
    storey = f.createIfcBuildingStorey(ifcopenshell.guid.new(), owner_history, "Первый этаж")

    ifcopenshell.api.run("aggregate.assign_object", f, product=site, relating_object=project)
    ifcopenshell.api.run("aggregate.assign_object", f, product=building, relating_object=site)
    ifcopenshell.api.run("aggregate.assign_object", f, product=storey, relating_object=building)
    
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
