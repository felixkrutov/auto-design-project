import pandas as pd
import ifcopenshell
import ifcopenshell.guid
from ortools.sat.python import cp_model
import sys
import time
import json
import math

def get_rules_from_google_sheet(sheet_url):
    print("Чтение правил из Google Таблицы...")
    try:
        csv_export_url = sheet_url.replace('/edit?usp=sharing', '/export?format=csv')
        df = pd.read_csv(csv_export_url).fillna('')
        print(f"  > Успешно загружено {len(df)} правил.")
        return df
    except Exception as e:
        print(f"  > ОШИБКА: Не удалось загрузить правила. {e}")
        return None

def create_ifc_file(task_data, placements, filename="prototype.ifc"):
    print("Создание IFC файла...")
    f = ifcopenshell.file(schema="IFC4")
    
    # Исправленное создание OwnerHistory
    person = f.createIfcPerson(FamilyName="AI System")
    organization = f.createIfcOrganization(Name="AutoDesign Inc.")
    person_org = f.createIfcPersonAndOrganization(person, organization)
    
    application_org = f.createIfcOrganization(Name="AI Assistant")
    application = f.createIfcApplication(application_org, "1.0", "AutoDesign Solver", "ADS")
    
    # Создаем OwnerHistory с минимальными параметрами
    owner_history = f.createIfcOwnerHistory(
        person_org,
        application,
        None,        # ChangeAction
        None,        # CreationDate
        None,        # LastModifyingUser
        None,        # LastModifyingApplication  
        None         # LastModifiedDate
    )
    
    project = f.createIfcProject(ifcopenshell.guid.new(), owner_history, task_data['project_name'])
    context = f.createIfcGeometricRepresentationContext(None, "Model", 3, 1.0E-5, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0))))
    project.RepresentationContexts = [context]
    
    site = f.createIfcSite(ifcopenshell.guid.new(), owner_history, "Участок", ObjectPlacement=f.createIfcLocalPlacement(None, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)))))
    building = f.createIfcBuilding(ifcopenshell.guid.new(), owner_history, task_data['building_name'], ObjectPlacement=f.createIfcLocalPlacement(site.ObjectPlacement, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)))))
    storey = f.createIfcBuildingStorey(ifcopenshell.guid.new(), owner_history, task_data['storey_name'], ObjectPlacement=f.createIfcLocalPlacement(building.ObjectPlacement, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)))))

    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, "ProjectContainer", None, project, [site])
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, "SiteContainer", None, site, [building])
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, "BuildingContainer", None, building, [storey])

    for item in placements:
        element_placement = f.createIfcLocalPlacement(storey.ObjectPlacement, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((float(item['x']), float(item['y']), 0.0))))
        profile = f.createIfcRectangleProfileDef('AREA', None, None, item['width'], item['depth'])
        solid = f.createIfcExtrudedAreaSolid(profile, None, f.createIfcDirection((0.0, 0.0, 1.0)), item['height'])
        shape = f.createIfcProductDefinitionShape(None, None, [f.createIfcShapeRepresentation(context, 'Body', 'SweptSolid', [solid])])
        
        element = f.createIfcBuildingElementProxy(ifcopenshell.guid.new(), owner_history, item['name'], ObjectPlacement=element_placement, Representation=shape)
        
        if 'attributes' in item and item['attributes']:
            prop_values = [f.createIfcPropertySingleValue(k, None, f.createIfcLabel(v), None) for k, v in item['attributes'].items()]
            prop_set = f.createIfcPropertySet(ifcopenshell.guid.new(), owner_history, "Параметры", None, prop_values)
            f.createIfcRelDefinesByProperties(ifcopenshell.guid.new(), owner_history, None, None, [element], prop_set)
        
        f.createIfcRelContainedInSpatialStructure(ifcopenshell.guid.new(), owner_history, "Content", None, [element], storey)
    
    f.write(filename)
    print(f"  > Файл '{filename}' успешно создан!")

def solve_layout(sheet_url, task_file_path):
    print("\n--- НАЧАЛО ПРОЦЕССА ПРОЕКТИРОВАНИЯ ---")
    try:
        with open(task_file_path, 'r', encoding='utf-8') as f:
            task_data = json.load(f)
        print(f"1. Задание '{task_data['project_name']}' успешно загружено.")
    except Exception as e:
        print(f"  > ОШИБКА: Не удалось прочитать файл задания. {e}"); return
    rules_df = get_rules_from_google_sheet(sheet_url)
    if rules_df is None: return
    print("2. Настройка модели и ограничений...")
    equipment_list = task_data['equipment']
    room_width = task_data['room_dimensions']['width']
    room_depth = task_data['room_dimensions']['depth']
    model = cp_model.CpModel()
    SCALE = 1000
    positions = {item['name']: {'x': model.NewIntVar(0, int((room_width - item['width']) * SCALE), f"x_{item['name']}"), 'y': model.NewIntVar(0, int((room_depth - item['depth']) * SCALE), f"y_{item['name']}")} for item in equipment_list}
    intervals_x = [model.NewIntervalVar(positions[item['name']]['x'], int(item['width'] * SCALE), positions[item['name']]['x'] + int(item['width'] * SCALE), f"ix_{item['name']}") for item in equipment_list]
    intervals_y = [model.NewIntervalVar(positions[item['name']]['y'], int(item['depth'] * SCALE), positions[item['name']]['y'] + int(item['depth'] * SCALE), f"iy_{item['name']}") for item in equipment_list]
    model.AddNoOverlap2D(intervals_x, intervals_y)
    print("  > Применение пользовательских правил...")
    for _, rule in rules_df.iterrows():
        obj1_name = rule['Объект1']
        if obj1_name not in positions: continue
        rule_type = rule['Тип правила']
        value = float(rule['Значение'])
        value_scaled = int(value * SCALE)
        if rule_type == 'Мин. отступ от стены X0':
            model.Add(positions[obj1_name]['x'] >= value_scaled)
            print(f"    - ПРАВИЛО: '{obj1_name}' отступ от X0 >= {value}м.")
        elif rule_type == 'Мин. отступ от стены Y0':
            model.Add(positions[obj1_name]['y'] >= value_scaled)
            print(f"    - ПРАВИЛО: '{obj1_name}' отступ от Y0 >= {value}м.")
        elif rule_type == 'Мин. расстояние до':
            obj2_name = rule['Объект2']
            if obj2_name not in positions: continue
            dx = model.NewIntVar(-int(room_width * SCALE), int(room_width * SCALE), f"dx_{obj1_name}_{obj2_name}")
            dy = model.NewIntVar(-int(room_depth * SCALE), int(room_depth * SCALE), f"dy_{obj1_name}_{obj2_name}")
            model.Add(dx == positions[obj1_name]['x'] - positions[obj2_name]['x'])
            model.Add(dy == positions[obj1_name]['y'] - positions[obj2_name]['y'])
            dx2 = model.NewIntVar(0, int(room_width * SCALE)**2, f"dx2_{obj1_name}_{obj2_name}")
            dy2 = model.NewIntVar(0, int(room_depth * SCALE)**2, f"dy2_{obj1_name}_{obj2_name}")
            model.AddMultiplicationEquality(dx2, [dx, dx])
            model.AddMultiplicationEquality(dy2, [dy, dy])
            dist_sq = value_scaled**2
            model.Add(dx2 + dy2 >= dist_sq)
            print(f"    - ПРАВИЛО: Расстояние между '{obj1_name}' и '{obj2_name}' >= {value}м.")
    print("3. Запуск решателя OR-Tools...")
    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("  > Решение найдено!")
        final_placements = [{'name': item['name'], 'x': solver.Value(positions[item['name']]['x']) / SCALE, 'y': solver.Value(positions[item['name']]['y']) / SCALE, 'width': item['width'], 'depth': item['depth'], 'height': item['height'], 'attributes': item.get('attributes', {})} for item in equipment_list]
        create_ifc_file(task_data, final_placements)
    else:
        print("  > ОШИБКА: Не удалось найти решение. Проверьте, не противоречат ли правила друг другу.")
    print("--- ПРОЦЕСС ПРОЕКТИРОВАНИЯ ЗАВЕРШЕН ---")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("\nОшибка: Неверное количество аргументов.")
        print("Пример запуска: python layout_solver.py <URL_Google_Таблицы> <путь_к_task.json>\n")
    else:
        google_sheet_url = sys.argv[1]
        task_json_path = sys.argv[2]
        solve_layout(google_sheet_url, task_json_path)
