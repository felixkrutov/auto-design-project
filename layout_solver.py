import pandas as pd
import ifcopenshell
import ifcopenshell.guid
from ortools.sat.python import cp_model
import sys
import time

def get_rules_from_google_sheet(sheet_url):
    print("1. Читаем правила из Google Таблицы...")
    try:
        csv_export_url = sheet_url.replace('/edit?usp=sharing', '/export?format=csv')
        df = pd.read_csv(csv_export_url)
        print(f"  > Успешно загружено {len(df)} правил.")
        return df
    except Exception as e:
        print(f"  > ОШИБКА: Не удалось загрузить правила. {e}")
        return None

def create_ifc_file(placements, filename="prototype.ifc"):
    print(f"3. Создаем IFC файл '{filename}'...")
    f = ifcopenshell.file(schema="IFC4")
    
    person = f.createIfcPerson()
    person.FamilyName = "Krutov"
    organization = f.createIfcOrganization()
    organization.Name = "AutoDesign Inc."
    person_and_org = f.createIfcPersonAndOrganization(person, organization)
    
    app_organization = f.createIfcOrganization()
    app_organization.Name = "AI Assistant"
    application = f.createIfcApplication(app_organization, "1.0", "AutoDesign Script", "ADS")
    
    # --- ИСПРАВЛЕННАЯ СТРОКА ---
    # Теперь все аргументы на своих местах
    owner_history = f.createIfcOwnerHistory(
        OwningUser=person_and_org, 
        OwningApplication=application, 
        ChangeAction="ADDED", 
        CreationDate=int(time.time())
    )
    # --- КОНЕЦ ИСПРАВЛЕННОГО БЛОКА ---
    
    project = f.createIfcProject(ifcopenshell.guid.new(), owner_history, "Проект Цеха")
    context = f.createIfcGeometricRepresentationContext(None, "Model", 3, 1.0E-5, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0))))
    f.createIfcRelAssignsToProject(ifcopenshell.guid.new(), owner_history, [project], None, context)
    
    site_placement = f.createIfcLocalPlacement(None, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0))))
    site = f.createIfcSite(ifcopenshell.guid.new(), owner_history, "Участок", None, None, site_placement)
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, None, None, project, [site])
    
    building_placement = f.createIfcLocalPlacement(site_placement, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0))))
    building = f.createIfcBuilding(ifcopenshell.guid.new(), owner_history, "Здание", None, None, building_placement)
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, None, None, site, [building])

    storey_placement = f.createIfcLocalPlacement(building_placement, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0))))
    storey = f.createIfcBuildingStorey(ifcopenshell.guid.new(), owner_history, "Первый этаж", None, None, storey_placement)
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, None, None, building, [storey])

    for item in placements:
        name, x, y, width, depth = item['name'], item['x'], item['y'], item['width'], item['depth']
        height = 1.5

        element_placement = f.createIfcLocalPlacement(storey_placement, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((float(x), float(y), 0.0))))
        element = f.createIfcBuildingElementProxy(ifcopenshell.guid.new(), owner_history, name, None, None, element_placement)
        
        profile = f.createIfcRectangleProfileDef('AREA', None, width, depth)
        direction = f.createIfcDirection((0.0, 0.0, 1.0))
        solid = f.createIfcExtrudedAreaSolid(profile, None, direction, height)
        
        shape_representation = f.createIfcShapeRepresentation(context, 'Body', 'SweptSolid', [solid])
        element.Representation = f.createIfcProductDefinitionShape(None, None, [shape_representation])
        
        f.createIfcRelContainedInSpatialStructure(ifcopenshell.guid.new(), owner_history, None, None, [element], storey)
    
    f.write(filename)
    print(f"  > Файл '{filename}' успешно создан!")

def solve_layout(sheet_url):
    rules_df = get_rules_from_google_sheet(sheet_url)
    if rules_df is None: return

    equipment_list = [
        {'name': 'Станок_ЧПУ', 'width': 2.0, 'depth': 3.0},
        {'name': 'Конвейер', 'width': 1.0, 'depth': 5.0},
        {'name': 'Печь', 'width': 2.0, 'depth': 2.0},
        {'name': 'Стеллаж', 'width': 4.0, 'depth': 1.0}
    ]
    ROOM_SIZE = 20
    print("2. Расставляем оборудование с помощью OR-Tools...")
    model = cp_model.CpModel()
    
    positions = {item['name']: {'x': model.NewIntVar(0, int(ROOM_SIZE - item['width']), f"x_{item['name']}"), 
                                'y': model.NewIntVar(0, int(ROOM_SIZE - item['depth']), f"y_{item['name']}")} 
                 for item in equipment_list}
    
    intervals_x = [model.NewIntervalVar(positions[item['name']]['x'], int(item['width']), positions[item['name']]['x'] + int(item['width']), f"ix_{item['name']}") for item in equipment_list]
    intervals_y = [model.NewIntervalVar(positions[item['name']]['y'], int(item['depth']), positions[item['name']]['y'] + int(item['depth']), f"iy_{item['name']}") for item in equipment_list]
    model.AddNoOverlap2D(intervals_x, intervals_y)
    
    solver = cp_model.CpSolver()
    if solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("  > Решение найдено!")
        final_placements = [{'name': item['name'], 'x': solver.Value(positions[item['name']]['x']), 'y': solver.Value(positions[item['name']]['y']), 'width': item['width'], 'depth': item['depth']} for item in equipment_list]
        create_ifc_file(final_placements)
    else:
        print("  > ОШИБКА: Не удалось найти решение для расстановки.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Ошибка: Укажите URL Google Таблицы как аргумент.")
    else:
        google_sheet_url = sys.argv[1]
        solve_layout(google_sheet_url)
