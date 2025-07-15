## ПОЛНЫЙ КОД ДЛЯ geometry.py
import ifcopenshell
import ifcopenshell.api
import ifcopenshell.guid
import time

def create_element(f, context, name, placement, w, d, h):
    """Вспомогательная функция для создания одного элемента (ящика)."""
    # Профиль создается с центром в (0,0), поэтому смещаем его на -w/2, -d/2
    profile_placement = f.createIfcAxis2Placement2D(f.createIfcCartesianPoint((-w / 2, -d / 2)))
    profile = f.createIfcRectangleProfileDef('AREA', name + "_profile", profile_placement, w, d)
    
    # Положение и направление вытягивания
    extrusion_placement = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)))
    extrusion_direction = f.createIfcDirection((0.0, 0.0, 1.0))
    
    # Создаем тело
    extrusion = f.createIfcExtrudedAreaSolid(profile, extrusion_placement, extrusion_direction, h)
    
    shape_rep = f.createIfcShapeRepresentation(context, 'Body', 'SweptSolid', [extrusion])
    product_shape = f.createIfcProductDefinitionShape(None, None, [shape_rep])
    
    owner_history = f.by_type("IfcOwnerHistory")[0]
    
    # Определяем тип элемента для IFC
    if "Стена" in name:
        element = f.createIfcWall(ifcopenshell.guid.new(), owner_history, name, ObjectPlacement=placement, Representation=product_shape)
    elif "Пол" in name:
        element = f.createIfcSlab(ifcopenshell.guid.new(), owner_history, name, ObjectPlacement=placement, Representation=product_shape, PredefinedType='FLOOR')
    else:
        element = f.createIfcBuildingElementProxy(ifcopenshell.guid.new(), owner_history, name, ObjectPlacement=placement, Representation=product_shape)
    
    return element

def create_3d_model(project_data: dict, placements: dict, output_filename: str):
    print("\n5. Создание 3D модели (IFC)...")
    
    f = ifcopenshell.file(schema="IFC4")
    owner_history = f.createIfcOwnerHistory(f.createIfcPersonAndOrganization(f.createIfcPerson(), f.createIfcOrganization(Name="AutoDesign")), f.createIfcApplication(f.createIfcOrganization(Name="GeneratorV2"), "2.0", "GeneratorV2", "G2"), CreationDate=int(time.time()))
    
    # Обертка для создания точек, которая нравится ifcopenshell
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
    
    all_elements = []

    print("   - Создание архитектуры (пол, стены)...")
    arch_data = project_data.get('architecture', {})
    room_dims = arch_data.get('room_dimensions', {})
    wall_t = arch_data.get('wall_thickness', 0.2)
    w, d, h = room_dims.get('width'), room_dims.get('depth'), room_dims.get('height')

    if all([w, d, h]):
        # Пол: центр в центре комнаты, на нулевой отметке
        floor_pos = P(w / 2, d / 2, 0.0)
        floor_placement = f.createIfcLocalPlacement(storey.ObjectPlacement, f.createIfcAxis2Placement3D(floor_pos))
        floor = create_element(f, context, "Пол", floor_placement, w, d, -wall_t) # Пол идет вниз
        all_elements.append(floor)
        
        # Стены: вычисляем центральные точки для каждой
        walls_def = [
            {'name': 'Стена_Юг',    'pos': P(w / 2, 0,       h / 2), 'dims': (w, wall_t, h)},
            {'name': 'Стена_Север',  'pos': P(w / 2, d,       h / 2), 'dims': (w, wall_t, h)},
            {'name': 'Стена_Запад',  'pos': P(0,     d / 2,   h / 2), 'dims': (wall_t, d, h)},
            {'name': 'Стена_Восток', 'pos': P(w,     d / 2,   h / 2), 'dims': (wall_t, d, h)}
        ]
        for w_def in walls_def:
            wall_placement = f.createIfcLocalPlacement(storey.ObjectPlacement, f.createIfcAxis2Placement3D(w_def['pos']))
            wall = create_element(f, context, w_def['name'], wall_placement, *w_def['dims'])
            all_elements.append(wall)

    print("   - Размещение оборудования...")
    equipment_map = {eq['id']: eq for eq in project_data['equipment']}
    for eq_id, placement in placements.items():
        eq_data = equipment_map.get(eq_id)
        eq_w = eq_data['footprint']['width']
        eq_d = eq_data['footprint']['depth']
        eq_h = eq_data['height']
        
        # Вычисляем ЦЕНТР оборудования. Координаты от решателя - это левый нижний угол.
        pos = P(float(placement['x']) + eq_w / 2, float(placement['y']) + eq_d / 2, eq_h / 2)
        
        eq_placement = f.createIfcLocalPlacement(storey.ObjectPlacement, f.createIfcAxis2Placement3D(pos))
        element = create_element(f, context, eq_data['name'], eq_placement, eq_w, eq_d, eq_h)
        all_elements.append(element)
        print(f"     - Создан объект: '{eq_data['name']}'")

    if all_elements:
        f.createIfcRelContainedInSpatialStructure(ifcopenshell.guid.new(), owner_history, "Содержимое этажа", None, all_elements, storey)

    f.write(output_filename)
    print(f"   > Модель успешно сохранена в файл: {output_filename}")
