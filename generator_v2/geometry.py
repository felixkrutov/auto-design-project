import ifcopenshell
import ifcopenshell.api
import ifcopenshell.guid
import time

def create_3d_model(project_data: dict, placements: dict, output_filename: str):
    """
    Создает IFC файл на основе данных проекта и рассчитанных положений.
    Использует только ifcopenshell для максимальной надежности.
    """
    print("\n5. Создание 3D модели (IFC)...")
    
    f = ifcopenshell.file(schema="IFC4")
    owner_history = f.createIfcOwnerHistory(
        OwningUser=f.createIfcPersonAndOrganization(f.createIfcPerson(), f.createIfcOrganization(Name="AutoDesign")),
        OwningApplication=f.createIfcApplication(f.createIfcOrganization(Name="GeneratorV2"), "2.0", "GeneratorV2", "G2"),
        CreationDate=int(time.time())
    )
    project = f.createIfcProject(ifcopenshell.guid.new(), owner_history, project_data['meta']['project_name'])
    context = f.createIfcGeometricRepresentationContext(None, "Model", 3, 1.0E-5, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0))))
    project.RepresentationContexts = [context]
    
    site = f.createIfcSite(ifcopenshell.guid.new(), owner_history, "Участок")
    building = f.createIfcBuilding(ifcopenshell.guid.new(), owner_history, "Производственный корпус")
    storey = f.createIfcBuildingStorey(ifcopenshell.guid.new(), owner_history, "Первый этаж")
    
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, None, None, project, [site])
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, None, None, site, [building])
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, None, None, building, [storey])
    
    print("   - Размещение оборудования...")
    equipment_map = {eq['id']: eq for eq in project_data['equipment']}
    
    for eq_id, placement in placements.items():
        equipment_data = equipment_map.get(eq_id)
        if not equipment_data:
            continue

        w = equipment_data['footprint']['width']
        d = equipment_data['footprint']['depth']
        h = equipment_data['height']
        
        # Положение нижнего левого угла
        x, y = placement['x'], placement['y']
        
        # Создаем геометрию ящика напрямую в IFC
        placement_point = f.createIfcCartesianPoint((x, y, 0.0))
        axis_placement = f.createIfcAxis2Placement3D(placement_point)
        obj_placement = f.createIfcLocalPlacement(storey.ObjectPlacement, axis_placement)

        profile = f.createIfcRectangleProfileDef('AREA', None, None, w, d)
        extrusion = f.createIfcExtrudedAreaSolid(profile, None, f.createIfcDirection((0.0, 0.0, 1.0)), h)

        shape_rep = f.createIfcShapeRepresentation(context, 'Body', 'SweptSolid', [extrusion])
        product_shape = f.createIfcProductDefinitionShape(None, None, [shape_rep])

        element = f.createIfcBuildingElementProxy(
            ifcopenshell.guid.new(),
            owner_history,
            equipment_data['name'],
            ObjectPlacement=obj_placement,
            Representation=product_shape
        )
        
        f.createIfcRelContainedInSpatialStructure(ifcopenshell.guid.new(), owner_history, None, None, [element], storey)
        print(f"     - Создан объект: '{equipment_data['name']}'")

    try:
        f.write(output_filename)
        print(f"   > Модель успешно сохранена в файл: {output_filename}")
    except Exception as e:
        print(f"   > ОШИБКА: Не удалось сохранить IFC файл. {e}")
