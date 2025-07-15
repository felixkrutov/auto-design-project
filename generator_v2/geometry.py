import cadquery as cq
import ifcopenshell
import ifcopenshell.api
import ifcopenshell.guid
import time

# Эта функция-помощник нужна для старых версий ifcopenshell
def create_ifc_representation(ifc_file, context, shape):
    """Создает IFC представление из геометрии CadQuery."""
    # Экспортируем в формат BREP (текстовый)
    from io import StringIO
    s = StringIO()
    cq.exporters.exportShape(shape, 'BREP', s)
    brep_str = s.getvalue()
    
    # Создаем IFC сущности из BREP
    shape_rep = ifc_file.createIfcShapeRepresentation(
        ContextOfItems=context,
        RepresentationIdentifier='Body',
        RepresentationType='Brep',
        Items=[ifc_file.createIfcManifoldSolidBrep(
            Outer=ifc_file.createIfcClosedShell(
                CfsFaces=[ifc_file.createIfcFace(
                    Bounds=[ifc_file.createIfcFaceOuterBound(
                        Bound=ifc_file.createIfcPolyLoop(
                            Polygon=[ifc_file.createIfcCartesianPoint(p) for p in face]
                        ),
                        Orientation=True
                    )]
                ) for face in []] # Этот способ не работает напрямую, используем BREP
            )
        )]
    )
    # Хитрый способ импорта BREP
    ifcopenshell.api.run("geometry.import_brep", ifc_file, **{"brep": brep_str, "representation": shape_rep})
    return shape_rep


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
        CreationDate=int(time.time())
    )
    project = f.createIfcProject(ifcopenshell.guid.new(), owner_history, project_data['meta']['project_name'])
    context = f.createIfcGeometricRepresentationContext(None, "Model", 3, 1.0E-5, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0))))
    project.RepresentationContexts = [context]
    
    # --- 2. Создание иерархии (Сайт, Здание, Этаж) ---
    site = f.createIfcSite(ifcopenshell.guid.new(), owner_history, "Участок")
    building = f.createIfcBuilding(ifcopenshell.guid.new(), owner_history, "Производственный корпус")
    storey = f.createIfcBuildingStorey(ifcopenshell.guid.new(), owner_history, "Первый этаж")
    
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
        
        result_shape = cq.Workplane("XY").box(w, d, h).val()
        
        # НОВЫЙ СПОСОБ СОЗДАНИЯ ГЕОМЕТРИИ
        from io import StringIO
        s = StringIO()
        cq.exporters.exportShape(result_shape, 'BREP', s)
        shape_rep = f.createIfcShapeRepresentation(context, 'Body', 'Brep', [])
        ifcopenshell.api.run("geometry.import_brep", f, brep=s.getvalue(), representation=shape_rep)
        # КОНЕЦ НОВОГО СПОСОБА
        
        product_shape = f.createIfcProductDefinitionShape(None, None, [shape_rep])

        px = placement['x'] + w / 2
        py = placement['y'] + d / 2
        pz = h / 2
        
        axis = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((px, py, pz)))
        obj_placement = f.createIfcLocalPlacement(storey.ObjectPlacement, axis)

        element = f.createIfcBuildingElementProxy(
            ifcopenshell.guid.new(),
            owner_history,
            equipment_data['name'],
            ObjectPlacement=obj_placement,
            Representation=product_shape
        )
        
        f.createIfcRelContainedInSpatialStructure(ifcopenshell.guid.new(), owner_history, "BuildingStoreyContainer", None, [element], storey)
        print(f"     - Создан объект: '{equipment_data['name']}'")

    # --- 4. Сохранение файла ---
    try:
        f.write(output_filename)
        print(f"   > Модель успешно сохранена в файл: {output_filename}")
    except Exception as e:
        print(f"   > ОШИБКА: Не удалось сохранить IFC файл. {e}")
