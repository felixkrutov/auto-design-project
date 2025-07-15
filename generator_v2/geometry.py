import ifcopenshell
import ifcopenshell.api
import ifcopenshell.guid
import time

def create_element(f, context, name, placement, w, d, h):
    """Вспомогательная функция для создания одного элемента (ящика)."""
    profile = f.createIfcRectangleProfileDef('AREA', None, None, w, d)
    extrusion = f.createIfcExtrudedAreaSolid(profile, None, f.createIfcDirection((0.0, 0.0, 1.0)), h)
    shape_rep = f.createIfcShapeRepresentation(context, 'Body', 'SweptSolid', [extrusion])
    product_shape = f.createIfcProductDefinitionShape(None, None, [shape_rep])
    
    # Тип объекта определяем по имени для простоты
    if "Стена" in name:
        element = f.createIfcWall(ifcopenshell.guid.new(), f.by_type("IfcOwnerHistory")[0], name, ObjectPlacement=placement, Representation=product_shape)
    elif "Пол" in name:
        element = f.createIfcSlab(ifcopenshell.guid.new(), f.by_type("IfcOwnerHistory")[0], name, ObjectPlacement=placement, Representation=product_shape, PredefinedType='FLOOR')
    else:
        element = f.createIfcBuildingElementProxy(ifcopenshell.guid.new(), f.by_type("IfcOwnerHistory")[0], name, ObjectPlacement=placement, Representation=product_shape)
    
    return element

def create_3d_model(project_data: dict, placements: dict, output_filename: str):
    print("\n5. Создание 3D модели (IFC)...")
    
    f = ifcopenshell.file(schema="IFC4")
    # ... (стандартная шапка IFC, как и раньше) ...
    owner_history = f.createIfcOwnerHistory(f.createIfcPersonAndOrganization(f.createIfcPerson(), f.createIfcOrganization(Name="AutoDesign")), f.createIfcApplication(f.createIfcOrganization(Name="GeneratorV2"), "2.0", "GeneratorV2", "G2"), CreationDate=int(time.time()))
    project = f.createIfcProject(ifcopenshell.guid.new(), owner_history, project_data['meta']['project_name'])
    context = f.createIfcGeometricRepresentationContext(None, "Model", 3, 1.0E-5, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0))))
    project.RepresentationContexts = [context]
    site = f.createIfcSite(ifcopenshell.guid.new(), owner_history, "Участок")
    building = f.createIfcBuilding(ifcopenshell.guid.new(), owner_history, "Производственный корпус")
    storey = f.createIfcBuildingStorey(ifcopenshell.guid.new(), owner_history, "Первый этаж")
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, None, None, project, [site])
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, None, None, site, [building])
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, None, None, building, [storey])
    
    all_elements = []

    # Создание архитектуры
    print("   - Создание архитектуры (пол, стены)...")
    arch_data = project_data.get('architecture', {})
    room_dims = arch_data.get('room_dimensions', {})
    wall_t = arch_data.get('wall_thickness', 0.2)
    w, d, h = room_dims.get('width'), room_dims.get('depth'), room_dims.get('height')

    if all([w,d,h]):
        # Пол
        floor_placement = f.createIfcLocalPlacement(storey.ObjectPlacement, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0, 0, -wall_t))))
        floor = create_element(f, context, "Пол", floor_placement, w, d, wall_t)
        all_elements.append(floor)
        # Стены
        walls_def = [
            {'name': 'Стена_Юг', 'pos': (0, 0), 'dims': (w, wall_t, h)},
            {'name': 'Стена_Север', 'pos': (0, d - wall_t), 'dims': (w, wall_t, h)},
            {'name': 'Стена_Запад', 'pos': (0, 0), 'dims': (wall_t, d, h)},
            {'name': 'Стена_Восток', 'pos': (w - wall_t, 0), 'dims': (wall_t, d, h)}
        ]
        for w_def in walls_def:
            wall_placement = f.createIfcLocalPlacement(storey.ObjectPlacement, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint(w_def['pos'])))
            wall = create_element(f, context, w_def['name'], wall_placement, *w_def['dims'])
            all_elements.append(wall)

    # Размещение оборудования
    print("   - Размещение оборудования...")
    equipment_map = {eq['id']: eq for eq in project_data['equipment']}
    for eq_id, placement in placements.items():
        eq_data = equipment_map.get(eq_id)
        pos = (placement['x'], placement['y'], 0.0)
        dims = (eq_data['footprint']['width'], eq_data['footprint']['depth'], eq_data['height'])
        
        eq_placement = f.createIfcLocalPlacement(storey.ObjectPlacement, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint(pos)))
        element = create_element(f, context, eq_data['name'], eq_placement, *dims)
        all_elements.append(element)
        print(f"     - Создан объект: '{eq_data['name']}'")

    if all_elements:
        f.createIfcRelContainedInSpatialStructure(ifcopenshell.guid.new(), owner_history, "Содержимое этажа", None, all_elements, storey)

    f.write(output_filename)
    print(f"   > Модель успешно сохранена в файл: {output_filename}")
