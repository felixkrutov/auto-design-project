import cadquery as cq
import ifcopenshell
import ifcopenshell.api
import ifcopenshell.guid
import time

def create_3d_model(project_data: dict, placements: dict, output_filename: str):
    """
    Создает IFC файл на основе данных проекта и рассчитанных положений.
    """
    print("\n5. Создание 3D модели (IFC)...")
    
    # --- 1. Инициализация IFC файла ---
    f = ifcopenshell.file(schema="IFC4")
    owner_history = f.createIfcOwnerHistory(
        OwningUser=f.createIfcPersonAndOrganization(f.createIfcPerson(), f.createIfcOrganization(Name="AutoDesign")),
        OwningApplication=f.createIfcApplication(f.createIfcOrganization(Name="GeneratorV2"), "2.0", "GeneratorV2", "G2"),
        State='READWRITE', ChangeAction='ADDED', CreationDate=int(time.time())
    )
    project = f.createIfcProject(ifcopenshell.guid.new(), owner_history, project_data['meta']['project_name'])
    context = f.createIfcGeometricRepresentationContext(None, "Model", 3, 1.0E-5, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0))))
    project.RepresentationContexts = [context]
    
    # --- 2. Создание иерархии (Сайт, Здание, Этаж) ---
    site = f.createIfcSite(ifcopenshell.guid.new(), owner_history, "Участок")
    building = f.createIfcBuilding(ifcopenshell.guid.new(), owner_history, "Производственный корпус")
    storey = f.createIfcBuildingStorey(ifcopenshell.guid.new(), owner_history, "Первый этаж", ElementComposition="ELEMENT")
    
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, "ProjectContainer", None, project, [site])
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, "SiteContainer", None, site, [building])
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, "BuildingContainer", None, building, [storey])
    
    # --- 3. Создание оборудования ---
    print("   - Размещение оборудования...")
    equipment_map = {eq['id']: eq for eq in project_data['equipment']}
    
    for eq_id, placement in placements.items():
        equipment_data = equipment_map.get(eq_id)
        if not equipment_data:
            continue

        # Создаем геометрию с помощью CadQuery
        w = equipment_data['footprint']['width']
        d = equipment_data['footprint']['depth']
        h = equipment_data['height']
        
        # CadQuery создает ящик с центром в (0,0,0)
        result = cq.Workplane("XY").box(w, d, h)
        
        # Экспортируем геометрию в формат, понятный ifcopenshell
        brep_data = ifcopenshell.util.shape.get_brep(result.val())
        body = f.createIfcPolygonalFaceSet(
            Coordinates=f.createIfcCartesianPointList3D([f.createIfcCartesianPoint(p) for p in brep_data["verts"]]),
            Faces=[f.createIfcClosedShell([f.createIfcFace([f.createIfcFaceOuterBound(f.createIfcPolyLoop(
                [f.createIfcCartesianPoint(p) for p in brep_data["verts"][i:i+4]]
            ))]) for i in range(0, len(brep_data["verts"]), 4)])],
        )
        
        shape_rep = f.createIfcShapeRepresentation(context, "Body", "Brep", [body])
        product_shape = f.createIfcProductDefinitionShape(None, None, [shape_rep])

        # Создаем положение объекта в мире
        # Важно: CadQuery создает объекты с центром в (0,0,0), а мы хотим, чтобы наш X,Y был левым нижним углом.
        # Поэтому смещаем центр объекта на (width/2, depth/2, height/2)
        px = placement['x'] + w / 2
        py = placement['y'] + d / 2
        pz = h / 2
        
        axis = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((px, py, pz)))
        obj_placement = f.createIfcLocalPlacement(storey.ObjectPlacement, axis)

        # Создаем сам объект в IFC
        element = f.createIfcBuildingElementProxy(
            ifcopenshell.guid.new(),
            owner_history,
            equipment_data['name'],
            ObjectPlacement=obj_placement,
            Representation=product_shape
        )
        
        # Привязываем объект к этажу
        f.createIfcRelContainedInSpatialStructure(ifcopenshell.guid.new(), owner_history, "BuildingStoreyContainer", None, [element], storey)
        print(f"     - Создан объект: '{equipment_data['name']}'")

    # --- 4. Сохранение файла ---
    try:
        f.write(output_filename)
        print(f"   > Модель успешно сохранена в файл: {output_filename}")
    except Exception as e:
        print(f"   > ОШИБКА: Не удалось сохранить IFC файл. {e}")
