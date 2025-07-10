import pandas as pd
import ifcopenshell
import ifcopenshell.guid
from ortools.sat.python import cp_model
import sys
import time
import json

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

def create_ifc_file(task_data, placements, filename="prototype.ifc"):
    print(f"3. Создаем IFC файл '{filename}'...")
    f = ifcopenshell.file(schema="IFC4")
    
    # --- Метаданные проекта ---
    owner_history = f.createIfcOwnerHistory(
        f.createIfcPersonAndOrganization(f.createIfcPerson(FamilyName="AI System"), f.createIfcOrganization(Name="AutoDesign Inc.")),
        f.createIfcApplication(f.createIfcOrganization(Name="AI Assistant"), "1.0", "AutoDesign Solver", "ADS"),
        "ADDED",
        int(time.time())
    )
    
    project = f.createIfcProject(ifcopenshell.guid.new(), owner_history, task_data['project_name'])
    context = f.createIfcGeometricRepresentationContext(None, "Model", 3, 1.0E-5, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0))))
    project.RepresentationContexts = [context]
    
    # --- Структура здания ---
    site_placement = f.createIfcLocalPlacement(None, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0))))
    site = f.createIfcSite(ifcopenshell.guid.new(), owner_history, "Участок", None, None, site_placement)
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, None, None, project, [site])
    
    building_placement = f.createIfcLocalPlacement(site_placement, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0))))
    building = f.createIfcBuilding(ifcopenshell.guid.new(), owner_history, task_data['building_name'], None, None, building_placement)
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, None, None, site, [building])

    storey_placement = f.createIfcLocalPlacement(building_placement, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0))))
    storey = f.createIfcBuildingStorey(ifcopenshell.guid.new(), owner_history, task_data['storey_name'], None, None, storey_placement)
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, None, None, building, [storey])

    # --- Создание оборудования ---
    for item in placements:
        name, x, y, width, depth, height = item['name'], item['x'], item['y'], item['width'], item['depth'], item['height']

        element_placement = f.createIfcLocalPlacement(storey_placement, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((float(x), float(y), 0.0))))
        
        # Создаем тело объекта
        profile = f.createIfcRectangleProfileDef('AREA', None, None, width, depth)
        direction = f.createIfcDirection((0.0, 0.0, 1.0))
        solid = f.createIfcExtrudedAreaSolid(profile, None, direction, height)
        shape_representation = f.createIfcShapeRepresentation(context, 'Body', 'SweptSolid', [solid])
        
        # Создаем сам объект и привязываем к нему тело
        element = f.createIfcBuildingElementProxy(ifcopenshell.guid.new(), owner_history, name, None, None, element_placement)
        element.Representation = f.createIfcProductDefinitionShape(None, None, [shape_representation])
        
        # Помещаем объект на этаж
        f.createIfcRelContainedInSpatialStructure(ifcopenshell.guid.new(), owner_history, None, None, [element], storey)
    
    f.write(filename)
    print(f"  > Файл '{filename}' успешно создан!")

def solve_layout(sheet_url, task_file_path):
    # --- Шаг 1: Загрузка данных из JSON ---
    print(f"1. Читаем задание из файла '{task_file_path}'...")
    try:
        with open(task_file_path, 'r', encoding='utf-8') as f:
            task_data = json.load(f)
    except Exception as e:
        print(f"  > ОШИБКА: Не удалось прочитать файл задания. {e}")
        return

    # --- Шаг 2: Загрузка правил (пока не используются, но оставляем) ---
    rules_df = get_rules_from_google_sheet(sheet_url)
    if rules_df is None: return

    # --- Шаг 3: Настройка и решение оптимизационной задачи ---
    print("2. Расставляем оборудование с помощью OR-Tools...")
    equipment_list = task_data['equipment']
    room_width = task_data['room_dimensions']['width']
    room_depth = task_data['room_dimensions']['depth']
    
    model = cp_model.CpModel()
    
    positions = {item['name']: {'x': model.NewIntVar(0, int(room_width - item['width']), f"x_{item['name']}"), 
                                'y': model.NewIntVar(0, int(room_depth - item['depth']), f"y_{item['name']}")} 
                 for item in equipment_list}
    
    intervals_x = [model.NewIntervalVar(positions[item['name']]['x'], int(item['width']), positions[item['name']]['x'] + int(item['width']), f"ix_{item['name']}") for item in equipment_list]
    intervals_y = [model.NewIntervalVar(positions[item['name']]['y'], int(item['depth']), positions[item['name']]['y'] + int(item['depth']), f"iy_{item['name']}") for item in equipment_list]
    model.AddNoOverlap2D(intervals_x, intervals_y)
    
    solver = cp_model.CpSolver()
    if solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("  > Решение найдено!")
        final_placements = [
            {
                'name': item['name'], 
                'x': solver.Value(positions[item['name']]['x']), 
                'y': solver.Value(positions[item['name']]['y']), 
                'width': item['width'], 
                'depth': item['depth'],
                'height': item['height'] # Добавляем высоту
            } 
            for item in equipment_list
        ]
        create_ifc_file(task_data, final_placements)
    else:
        print("  > ОШИБКА: Не удалось найти решение для расстановки.")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("\nОшибка: Неверное количество аргументов.")
        print("Пример запуска: python layout_solver.py <URL_Google_Таблицы> <путь_к_task.json>\n")
    else:
        google_sheet_url = sys.argv[1]
        task_json_path = sys.argv[2]
        solve_layout(google_sheet_url, task_json_path)
