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
        df = pd.read_csv(csv_export_url).fillna('') # Заменяем пустые ячейки на пустые строки
        print(f"  > Успешно загружено {len(df)} правил.")
        return df
    except Exception as e:
        print(f"  > ОШИБКА: Не удалось загрузить правила. {e}")
        return None

def create_ifc_file(task_data, placements, filename="prototype.ifc"):
    print("Создание IFC файла...")
    f = ifcopenshell.file(schema="IFC4")
    
    owner_history = f.createIfcOwnerHistory(
        f.createIfcPersonAndOrganization(f.createIfcPerson(FamilyName="AI System"), f.createIfcOrganization(Name="AutoDesign Inc.")),
        f.createIfcApplication(f.createIfcOrganization(Name="AI Assistant"), "1.0", "AutoDesign Solver", "ADS"),
        "ADDED",
        int(time.time())
    )
    
    project = f.createIfcProject(ifcopenshell.guid.new(), owner_history, task_data['project_name'])
    context = f.createIfcGeometricRepresentationContext(None, "Model", 3, 1.0E-5, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0))))
    project.RepresentationContexts = [context]
    
    site_placement = f.createIfcLocalPlacement(None, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0))))
    site = f.createIfcSite(ifcopenshell.guid.new(), owner_history, "Участок", None, None, site_placement)
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, None, None, project, [site])
    
    building_placement = f.createIfcLocalPlacement(site_placement, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0))))
    building = f.createIfcBuilding(ifcopenshell.guid.new(), owner_history, task_data['building_name'], None, None, building_placement)
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, None, None, site, [building])

    storey_placement = f.createIfcLocalPlacement(building_placement, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0))))
    storey = f.createIfcBuildingStorey(ifcopenshell.guid.new(), owner_history, task_data['storey_name'], None, None, storey_placement)
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, None, None, building, [storey])

    for item in placements:
        name, x, y, width, depth, height = item['name'], item['x'], item['y'], item['width'], item['depth'], item['height']
        element_placement = f.createIfcLocalPlacement(storey_placement, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((float(x), float(y), 0.0))))
        profile = f.createIfcRectangleProfileDef('AREA', None, None, width, depth)
        direction = f.createIfcDirection((0.0, 0.0, 1.0))
        solid = f.createIfcExtrudedAreaSolid(profile, None, direction, height)
        shape_representation = f.createIfcShapeRepresentation(context, 'Body', 'SweptSolid', [solid])
        element = f.createIfcBuildingElementProxy(ifcopenshell.guid.new(), owner_history, name, None, None, element_placement)
        element.Representation = f.createIfcProductDefinitionShape(None, None, [shape_representation])
        f.createIfcRelContainedInSpatialStructure(ifcopenshell.guid.new(), owner_history, None, None, [element], storey)
    
    f.write(filename)
    print(f"  > Файл '{filename}' успешно создан!")

def solve_layout(sheet_url, task_file_path):
    print("\n--- НАЧАЛО ПРОЦЕССА ПРОЕКТИРОВАНИЯ ---")
    
    # Шаг 1: Загрузка данных и правил
    try:
        with open(task_file_path, 'r', encoding='utf-8') as f:
            task_data = json.load(f)
        print(f"1. Задание '{task_data['project_name']}' успешно загружено.")
    except Exception as e:
        print(f"  > ОШИБКА: Не удалось прочитать файл задания. {e}"); return

    rules_df = get_rules_from_google_sheet(sheet_url)
    if rules_df is None: return

    # Шаг 2: Настройка модели оптимизации
    print("2. Настройка модели и ограничений...")
    equipment_list = task_data['equipment']
    equipment_map = {item['name']: item for item in equipment_list}
    room_width = task_data['room_dimensions']['width']
    room_depth = task_data['room_dimensions']['depth']
    
    model = cp_model.CpModel()
    
    positions = {item['name']: {'x': model.NewIntVar(0, math.floor(room_width - item['width']), f"x_{item['name']}"), 
                                'y': model.NewIntVar(0, math.floor(room_depth - item['depth']), f"y_{item['name']}")} 
                 for item in equipment_list}
    
    # --- БАЗОВОЕ ПРАВИЛО: НЕ ПЕРЕСЕКАТЬСЯ ---
    intervals_x = [model.NewIntervalVar(positions[item['name']]['x'], int(item['width']), positions[item['name']]['x'] + int(item['width']), f"ix_{item['name']}") for item in equipment_list]
    intervals_y = [model.NewIntervalVar(positions[item['name']]['y'], int(item['depth']), positions[item['name']]['y'] + int(item['depth']), f"iy_{item['name']}") for item in equipment_list]
    model.AddNoOverlap2D(intervals_x, intervals_y)

    # --- НОВЫЙ БЛОК: ПРИМЕНЕНИЕ ПРАВИЛ ИЗ ТАБЛИЦЫ ---
    print("  > Применение пользовательских правил...")
    for _, rule in rules_df.iterrows():
        obj1_name, rule_type, value = rule['Объект1'], rule['Тип правила'], rule['Значение']

        if obj1_name not in positions:
            print(f"    - ПРЕДУПРЕЖДЕНИЕ: Объект '{obj1_name}' из правила не найден в задании.")
            continue

        try:
            # Правила отступа от стен
            if rule_type == 'Мин. отступ от стены X0':
                model.Add(positions[obj1_name]['x'] >= int(value))
                print(f"    - ПРАВИЛО: '{obj1_name}' должен быть на расстоянии >= {value} от стены X0.")
            elif rule_type == 'Мин. отступ от стены Y0':
                model.Add(positions[obj1_name]['y'] >= int(value))
                print(f"    - ПРАВИЛО: '{obj1_name}' должен быть на расстоянии >= {value} от стены Y0.")
            
            # Правила расстояния между объектами
            elif rule_type == 'Мин. расстояние до':
                obj2_name = rule['Объект2']
                if obj2_name not in positions:
                    print(f"    - ПРЕДУПРЕЖДЕНИЕ: Объект '{obj2_name}' из правила не найден.")
                    continue
                
                # Создаем переменные для абсолютных разниц по осям
                dx = model.NewIntVar(0, int(room_width), f"dx_{obj1_name}_{obj2_name}")
                dy = model.NewIntVar(0, int(room_depth), f"dy_{obj1_name}_{obj2_name}")
                model.AddAbsEquality(dx, positions[obj1_name]['x'] - positions[obj2_name]['x'])
                model.AddAbsEquality(dy, positions[obj1_name]['y'] - positions[obj2_name]['y'])
                
                # Условие: квадрат расстояния >= квадрата минимальной дистанции
                # Это стандартный прием, чтобы избежать иррациональных чисел (корней)
                dist_sq = int(value)**2
                model.Add(dx*dx + dy*dy >= dist_sq)
                print(f"    - ПРАВИЛО: Расстояние между '{obj1_name}' и '{obj2_name}' должно быть >= {value}.")

        except (ValueError, TypeError):
             print(f"    - ОШИБКА: Неверное значение '{value}' для правила '{rule_type}' у объекта '{obj1_name}'.")

    # Шаг 3: Решение и создание файла
    print("3. Запуск решателя OR-Tools...")
    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("  > Решение найдено!")
        final_placements = [
            {
                'name': item['name'], 
                'x': solver.Value(positions[item['name']]['x']), 
                'y': solver.Value(positions[item['name']]['y']), 
                'width': item['width'], 
                'depth': item['depth'],
                'height': item['height']
            } 
            for item in equipment_list
        ]
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
