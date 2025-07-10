import pandas as pd
import ifcopenshell
import ifcopenshell.guid
from ortools.sat.python import cp_model
import sys
import json
import time

# --- ФИНАЛЬНЫЙ ИСПРАВЛЕННЫЙ КОД ---

def get_rules_from_google_sheet(sheet_url):
    """Загружает правила из Google Таблицы."""
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
    """Создает IFC файл с оборудованием, полом и стенами."""
    print("Создание IFC файла...")
    f = ifcopenshell.file(schema="IFC4")
    
    # ИСПРАВЛЕНО: Корректный вызов IfcOwnerHistory с именованными аргументами
    owner_history = f.createIfcOwnerHistory(
        OwningUser=f.createIfcPersonAndOrganization(
            f.createIfcPerson(FamilyName="AI System"),
            f.createIfcOrganization(Name="AutoDesign Inc.")
        ),
        OwningApplication=f.createIfcApplication(
            f.createIfcOrganization(Name="AI Assistant"), "1.0", "AutoDesign Solver", "ADS"
        ),
        State='READWRITE',
        ChangeAction='ADDED',
        CreationDate=int(time.time())
    )
    
    project = f.createIfcProject(ifcopenshell.guid.new(), owner_history, task_data['project_name'])
    context = f.createIfcGeometricRepresentationContext(None, "Model", 3, 1.0E-5, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint([0.0, 0.0, 0.0])))
    project.RepresentationContexts = [context]
    
    site = f.createIfcSite(ifcopenshell.guid.new(), owner_history, "Участок", ObjectPlacement=f.createIfcLocalPlacement(None, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint([0.0, 0.0, 0.0]))))
    building = f.createIfcBuilding(ifcopenshell.guid.new(), owner_history, task_data['building_name'], ObjectPlacement=f.createIfcLocalPlacement(site.ObjectPlacement, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint([0.0, 0.0, 0.0]))))
    storey = f.createIfcBuildingStorey(ifcopenshell.guid.new(), owner_history, task_data['storey_name'], ObjectPlacement=f.createIfcLocalPlacement(building.ObjectPlacement, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint([0.0, 0.0, 0.0]))))
    storey_placement = storey.ObjectPlacement

    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, None, None, project, [site])
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, None, None, site, [building])
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, None, None, building, [storey])

    # --- ДОБАВЛЕНИЕ ПОЛА И СТЕН (ЯВНЫЙ И КОРРЕКТНЫЙ МЕТОД) ---
    print("  > Создание строительных конструкций (пол и стены)...")
    room_dims = task_data['room_dimensions']
    w, d, h = room_dims['width'], room_dims['depth'], room_dims['height']
    wall_thickness = 0.2
    slab_thickness = 0.2

    # Создаем Пол
    floor_placement = f.createIfcLocalPlacement(storey_placement, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint([0.0, 0.0, -slab_thickness])))
    floor_profile = f.createIfcRectangleProfileDef('AREA', None, None, float(w), float(d))
    floor_solid = f.createIfcExtrudedAreaSolid(floor_profile, None, f.createIfcDirection([0.0, 0.0, 1.0]), float(slab_thickness))
    floor_shape = f.createIfcProductDefinitionShape(None, None, [f.createIfcShapeRepresentation(context, 'Body', 'SweptSolid', [floor_solid])])
    floor = f.createIfcSlab(ifcopenshell.guid.new(), owner_history, "Пол", ObjectPlacement=floor_placement, Representation=floor_shape, PredefinedType='FLOOR')
    f.createIfcRelContainedInSpatialStructure(ifcopenshell.guid.new(), owner_history, None, None, [floor], storey)

    # Создаем Стены
    wall_definitions = [
        {'name': 'Стена_Низ', 'x': 0.0, 'y': 0.0, 'len': w, 'wid': wall_thickness},
        {'name': 'Стена_Право', 'x': w - wall_thickness, 'y': 0.0, 'len': wall_thickness, 'wid': d},
        {'name': 'Стена_Верх', 'x': 0.0, 'y': d - wall_thickness, 'len': w, 'wid': wall_thickness},
        {'name': 'Стена_Лево', 'x': 0.0, 'y': 0.0, 'len': wall_thickness, 'wid': d},
    ]
    for wall_def in wall_definitions:
        placement = f.createIfcLocalPlacement(storey_placement, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint([float(wall_def['x']), float(wall_def['y']), 0.0])))
        profile = f.createIfcRectangleProfileDef('AREA', None, None, float(wall_def['len']), float(wall_def['wid']))
        solid = f.createIfcExtrudedAreaSolid(profile, None, f.createIfcDirection([0.0, 0.0, 1.0]), float(h))
        shape = f.createIfcProductDefinitionShape(None, None, [f.createIfcShapeRepresentation(context, 'Body', 'SweptSolid', [solid])])
        wall = f.createIfcWall(ifcopenshell.guid.new(), owner_history, wall_def['name'], ObjectPlacement=placement, Representation=shape)
        f.createIfcRelContainedInSpatialStructure(ifcopenshell.guid.new(), owner_history, None, None, [wall], storey)

    # --- РАЗМЕЩЕНИЕ ОБОРУДОВАНИЯ ---
    print("  > Размещение оборудования...")
    for item in placements:
        element_placement = f.createIfcLocalPlacement(storey_placement, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint([float(item['x']), float(item['y']), 0.0])))
        
        profile = f.createIfcRectangleProfileDef('AREA', None, None, float(item['width']), float(item['depth']))
        solid = f.createIfcExtrudedAreaSolid(profile, None, f.createIfcDirection([0.0, 0.0, 1.0]), float(item['height']))
        shape = f.createIfcProductDefinitionShape(None, None, [f.createIfcShapeRepresentation(context, 'Body', 'SweptSolid', [solid])])
        
        element = f.createIfcBuildingElementProxy(ifcopenshell.guid.new(), owner_history, item['name'], ObjectPlacement=element_placement, Representation=shape)
        
        if 'attributes' in item and item['attributes']:
            prop_values = [f.createIfcPropertySingleValue(k, None, f.createIfcLabel(v), None) for k, v in item['attributes'].items()]
            prop_set = f.createIfcPropertySet(ifcopenshell.guid.new(), owner_history, "Параметры", None, prop_values)
            f.createIfcRelDefinesByProperties(ifcopenshell.guid.new(), owner_history, None, None, [element], prop_set)
        
        f.createIfcRelContainedInSpatialStructure(ifcopenshell.guid.new(), owner_history, None, None, [element], storey)
    
    f.write(filename)
    print(f"  > Файл '{filename}' успешно создан!")

def solve_layout(sheet_url, task_file_path):
    """Основная функция: читает данные, решает задачу и создает IFC."""
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
    room_dims = task_data['room_dimensions']
    room_width = room_dims['width']
    room_depth = room_dims['depth']
    
    model = cp_model.CpModel()
    SCALE = 1000

    wall_thickness = 0.2
    min_x = int(wall_thickness * SCALE)
    max_x = int((room_width - wall_thickness) * SCALE)
    min_y = int(wall_thickness * SCALE)
    max_y = int((room_depth - wall_thickness) * SCALE)

    positions = {}
    for item in equipment_list:
        item_width_scaled = int(item['width'] * SCALE)
        item_depth_scaled = int(item['depth'] * SCALE)
        
        positions[item['name']] = {
            'x': model.NewIntVar(min_x, max_x - item_width_scaled, f"x_{item['name']}"),
            'y': model.NewIntVar(min_y, max_y - item_depth_scaled, f"y_{item['name']}")
        }

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
            model.Add(positions[obj1_name]['x'] >= min_x + value_scaled)
            print(f"    - ПРАВИЛО: '{obj1_name}' отступ от стены X0 >= {value}м.")
        elif rule_type == 'Мин. отступ от стены Y0':
            model.Add(positions[obj1_name]['y'] >= min_y + value_scaled)
            print(f"    - ПРАВИЛО: '{obj1_name}' отступ от стены Y0 >= {value}м.")
        elif rule_type == 'Мин. расстояние до':
            obj2_name = rule['Объект2']
            if obj2_name not in positions: continue
            
            obj1_data = next(e for e in equipment_list if e['name'] == obj1_name)
            obj2_data = next(e for e in equipment_list if e['name'] == obj2_name)
            
            center1_x = positions[obj1_name]['x'] + int(obj1_data['width'] * SCALE / 2)
            center1_y = positions[obj1_name]['y'] + int(obj1_data['depth'] * SCALE / 2)
            center2_x = positions[obj2_name]['x'] + int(obj2_data['width'] * SCALE / 2)
            center2_y = positions[obj2_name]['y'] + int(obj2_data['depth'] * SCALE / 2)

            dx = model.NewIntVar(-int(room_width * SCALE), int(room_width * SCALE), f"dx_{obj1_name}_{obj2_name}")
            dy = model.NewIntVar(-int(room_depth * SCALE), int(room_depth * SCALE), f"dy_{obj1_name}_{obj2_name}")
            model.Add(dx == center1_x - center2_x)
            model.Add(dy == center1_y - center2_y)
            
            dx2 = model.NewIntVar(0, int(room_width * SCALE)**2, f"dx2_{obj1_name}_{obj2_name}")
            dy2 = model.NewIntVar(0, int(room_depth * SCALE)**2, f"dy2_{obj1_name}_{obj2_name}")
            model.AddMultiplicationEquality(dx2, dx, dx)
            model.AddMultiplicationEquality(dy2, dy, dy)
            
            dist_sq = value_scaled**2
            model.Add(dx2 + dy2 >= dist_sq)
            print(f"    - ПРАВИЛО: Расстояние между '{obj1_name}' и '{obj2_name}' >= {value}м.")

    print("3. Запуск решателя OR-Tools...")
    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("  > Решение найдено!")
        final_placements = [{'name': item['name'], 
                             'x': solver.Value(positions[item['name']]['x']) / SCALE, 
                             'y': solver.Value(positions[item['name']]['y']) / SCALE, 
                             'width': item['width'], 'depth': item['depth'], 'height': item['height'], 
                             'attributes': item.get('attributes', {})} 
                            for item in equipment_list]
        create_ifc_file(task_data, final_placements)
    else:
        print("  > ОШИБКА: Не удалось найти решение. Проверьте, не противоречат ли правила друг другу.")
    
    print("--- ПРОЦЕСС ПРОЕКТИРОВАНИЯ ЗАВЕРШЕН ---")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("\nОшибка: Неверное количество аргументов.\nПример запуска: python layout_solver.py <URL_Google_Таблицы> <путь_к_task.json>\n")
    else:
        google_sheet_url = sys.argv[1]
        task_json_path = sys.argv[2]
        solve_layout(google_sheet_url, task_json_path)
