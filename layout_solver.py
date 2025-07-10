import pandas as pd
import ifcopenshell
import ifcopenshell.guid
from ortools.sat.python import cp_model
import sys
import json
import time

### ИСПРАВЛЕННЫЙ КОД С КОРРЕКТНОЙ ГЕОМЕТРИЕЙ СТЕН И РАЗМЕЩЕНИЕМ ОБОРУДОВАНИЯ ###

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
    
    owner_history = f.createIfcOwnerHistory(
        OwningUser=f.createIfcPersonAndOrganization(
            f.createIfcPerson(FamilyName="AI System"),
            f.createIfcOrganization(Name="AutoDesign Inc.")
        ),
        OwningApplication=f.createIfcApplication(
            f.createIfcOrganization(Name="AI Assistant"), "1.0", "AutoDesign Solver", "ADS"
        ),
        State='READWRITE', ChangeAction='ADDED', CreationDate=int(time.time())
    )
    
    project = f.createIfcProject(ifcopenshell.guid.new(), owner_history, task_data['project_name'])
    context = f.createIfcGeometricRepresentationContext(
        None, "Model", 3, 1.0E-5, 
        f.createIfcAxis2Placement3D(f.createIfcCartesianPoint([0.0, 0.0, 0.0]))
    )
    project.RepresentationContexts = [context]
    
    site = f.createIfcSite(
        ifcopenshell.guid.new(), owner_history, "Участок", 
        ObjectPlacement=f.createIfcLocalPlacement(
            None, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint([0.0, 0.0, 0.0]))
        )
    )
    building = f.createIfcBuilding(
        ifcopenshell.guid.new(), owner_history, task_data['building_name'], 
        ObjectPlacement=f.createIfcLocalPlacement(
            site.ObjectPlacement, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint([0.0, 0.0, 0.0]))
        )
    )
    storey = f.createIfcBuildingStorey(
        ifcopenshell.guid.new(), owner_history, task_data['storey_name'], 
        ObjectPlacement=f.createIfcLocalPlacement(
            building.ObjectPlacement, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint([0.0, 0.0, 0.0]))
        )
    )
    storey_placement = storey.ObjectPlacement

    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, None, None, project, [site])
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, None, None, site, [building])
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, None, None, building, [storey])

    print("  > Создание строительных конструкций (пол и стены)...")
    room_dims = task_data['room_dimensions']
    w, d, h = room_dims['width'], room_dims['depth'], room_dims['height']
    wall_thickness = 0.2
    slab_thickness = 0.2

    # Создаем пол (базовая плита)
    floor_placement = f.createIfcLocalPlacement(
        storey_placement, 
        f.createIfcAxis2Placement3D(f.createIfcCartesianPoint([0.0, 0.0, -slab_thickness]))
    )
    floor_profile = f.createIfcRectangleProfileDef('AREA', None, None, float(w), float(d))
    floor_solid = f.createIfcExtrudedAreaSolid(
        floor_profile, None, f.createIfcDirection([0.0, 0.0, 1.0]), float(slab_thickness)
    )
    floor_shape = f.createIfcProductDefinitionShape(
        None, None, [f.createIfcShapeRepresentation(context, 'Body', 'SweptSolid', [floor_solid])]
    )
    floor = f.createIfcSlab(
        ifcopenshell.guid.new(), owner_history, "Пол", 
        ObjectPlacement=floor_placement, Representation=floor_shape, PredefinedType='FLOOR'
    )
    f.createIfcRelContainedInSpatialStructure(
        ifcopenshell.guid.new(), owner_history, None, None, [floor], storey
    )

    # ИСПРАВЛЕННАЯ ЛОГИКА СОЗДАНИЯ СТЕН
    # Создаем стены как замкнутый контур без пересечений
    wall_definitions = [
        # Южная стена (Y=0): от (0,0) до (W,0)
        {
            'name': 'Стена_Юг',
            'start_point': [0.0, 0.0, 0.0],
            'end_point': [w, 0.0, 0.0],
            'thickness': wall_thickness,
            'direction': [1.0, 0.0, 0.0]  # направление длины стены
        },
        # Восточная стена (X=W): от (W,0) до (W,D)
        {
            'name': 'Стена_Восток',
            'start_point': [w, 0.0, 0.0],
            'end_point': [w, d, 0.0],
            'thickness': wall_thickness,
            'direction': [0.0, 1.0, 0.0]
        },
        # Северная стена (Y=D): от (W,D) до (0,D)
        {
            'name': 'Стена_Север',
            'start_point': [w, d, 0.0],
            'end_point': [0.0, d, 0.0],
            'thickness': wall_thickness,
            'direction': [-1.0, 0.0, 0.0]
        },
        # Западная стена (X=0): от (0,D) до (0,0)
        {
            'name': 'Стена_Запад',
            'start_point': [0.0, d, 0.0],
            'end_point': [0.0, 0.0, 0.0],
            'thickness': wall_thickness,
            'direction': [0.0, -1.0, 0.0]
        }
    ]

    for wall_def in wall_definitions:
        # Вычисляем длину стены
        start = wall_def['start_point']
        end = wall_def['end_point']
        length = ((end[0] - start[0])**2 + (end[1] - start[1])**2)**0.5
        
        # Позиционируем стену по центру между начальной и конечной точками
        center_x = (start[0] + end[0]) / 2
        center_y = (start[1] + end[1]) / 2
        
        # Создаем размещение стены
        wall_placement = f.createIfcLocalPlacement(
            storey_placement,
            f.createIfcAxis2Placement3D(
                f.createIfcCartesianPoint([center_x, center_y, 0.0]),
                f.createIfcDirection([0.0, 0.0, 1.0]),  # ось Z
                f.createIfcDirection(wall_def['direction'])  # направление стены
            )
        )
        
        # Создаем профиль стены (прямоугольник)
        wall_profile = f.createIfcRectangleProfileDef(
            'AREA', None, None, float(length), float(wall_def['thickness'])
        )
        
        # Выдавливаем профиль по высоте
        wall_solid = f.createIfcExtrudedAreaSolid(
            wall_profile, None, f.createIfcDirection([0.0, 0.0, 1.0]), float(h)
        )
        
        # Создаем представление стены
        wall_shape = f.createIfcProductDefinitionShape(
            None, None, [f.createIfcShapeRepresentation(context, 'Body', 'SweptSolid', [wall_solid])]
        )
        
        # Создаем стену
        wall = f.createIfcWall(
            ifcopenshell.guid.new(), owner_history, wall_def['name'],
            ObjectPlacement=wall_placement, Representation=wall_shape
        )
        
        # Добавляем стену в пространственную структуру
        f.createIfcRelContainedInSpatialStructure(
            ifcopenshell.guid.new(), owner_history, None, None, [wall], storey
        )

    print("  > Размещение оборудования...")
    for item in placements:
        # Создаем размещение для каждого элемента оборудования
        element_placement = f.createIfcLocalPlacement(
            storey_placement,
            f.createIfcAxis2Placement3D(f.createIfcCartesianPoint([float(item['x']), float(item['y']), 0.0]))
        )
        
        # Создаем профиль оборудования
        profile = f.createIfcRectangleProfileDef(
            'AREA', None, None, float(item['width']), float(item['depth'])
        )
        
        # Выдавливаем профиль по высоте
        solid = f.createIfcExtrudedAreaSolid(
            profile, None, f.createIfcDirection([0.0, 0.0, 1.0]), float(item['height'])
        )
        
        # Создаем представление оборудования
        shape = f.createIfcProductDefinitionShape(
            None, None, [f.createIfcShapeRepresentation(context, 'Body', 'SweptSolid', [solid])]
        )
        
        # Создаем элемент оборудования
        element = f.createIfcBuildingElementProxy(
            ifcopenshell.guid.new(), owner_history, item['name'],
            ObjectPlacement=element_placement, Representation=shape
        )

        # Добавляем атрибуты, если они есть
        if 'attributes' in item and item['attributes']:
            prop_values = [
                f.createIfcPropertySingleValue(k, None, f.createIfcLabel(str(v)), None) 
                for k, v in item['attributes'].items()
            ]
            prop_set = f.createIfcPropertySet(
                ifcopenshell.guid.new(), owner_history, "Параметры", None, prop_values
            )
            f.createIfcRelDefinesByProperties(
                ifcopenshell.guid.new(), owner_history, None, None, [element], prop_set
            )

        # Добавляем оборудование в пространственную структуру
        f.createIfcRelContainedInSpatialStructure(
            ifcopenshell.guid.new(), owner_history, None, None, [element], storey
        )

    f.write(filename)
    print(f"  > Файл '{filename}' успешно создан!")

def solve_layout(sheet_url, task_file_path):
    print("\n--- НАЧАЛО ПРОЦЕССА ПРОЕКТИРОВАНИЯ ---")
    
    # Загружаем задание
    try:
        with open(task_file_path, 'r', encoding='utf-8') as f:
            task_data = json.load(f)
        print(f"1. Задание '{task_data['project_name']}' успешно загружено.")
    except Exception as e:
        print(f"  > ОШИБКА: Не удалось прочитать файл задания. {e}")
        return

    # Загружаем правила
    rules_df = get_rules_from_google_sheet(sheet_url)
    if rules_df is None:
        return

    print("2. Настройка модели и ограничений...")
    equipment_list = task_data['equipment']
    room_dims = task_data['room_dimensions']
    room_width = room_dims['width']
    room_depth = room_dims['depth']

    # Создаем модель оптимизации
    model = cp_model.CpModel()
    SCALE = 1000  # Масштабирование для работы с целыми числами

    # Определяем границы размещения с учетом толщины стен
    wall_thickness = 0.2
    min_x = int(wall_thickness * SCALE)
    max_x = int((room_width - wall_thickness) * SCALE)
    min_y = int(wall_thickness * SCALE)
    max_y = int((room_depth - wall_thickness) * SCALE)

    # Создаем переменные для позиций оборудования
    positions = {}
    intervals_x = []
    intervals_y = []
    
    for item in equipment_list:
        item_width_scaled = int(item['width'] * SCALE)
        item_depth_scaled = int(item['depth'] * SCALE)

        # Переменные для координат левого нижнего угла
        x_var = model.NewIntVar(min_x, max_x - item_width_scaled, f"x_{item['name']}")
        y_var = model.NewIntVar(min_y, max_y - item_depth_scaled, f"y_{item['name']}")
        
        positions[item['name']] = {'x': x_var, 'y': y_var}

        # Создаем интервалы для проверки пересечений
        interval_x = model.NewIntervalVar(
            x_var, item_width_scaled, x_var + item_width_scaled, f"ix_{item['name']}"
        )
        interval_y = model.NewIntervalVar(
            y_var, item_depth_scaled, y_var + item_depth_scaled, f"iy_{item['name']}"
        )
        
        intervals_x.append(interval_x)
        intervals_y.append(interval_y)

    # Добавляем ограничение на отсутствие пересечений
    model.AddNoOverlap2D(intervals_x, intervals_y)

    print("  > Применение пользовательских правил...")
    # Применяем правила из Google Таблицы
    for _, rule in rules_df.iterrows():
        obj1_name = rule['Объект1']
        if obj1_name not in positions:
            continue

        rule_type = rule['Тип правила']
        value = float(rule['Значение'])
        value_scaled = int(value * SCALE)

        if rule_type == 'Мин. расстояние до':
            obj2_name = rule['Объект2']
            if obj2_name not in positions:
                continue

            # Находим данные об объектах
            obj1_data = next((e for e in equipment_list if e['name'] == obj1_name), None)
            obj2_data = next((e for e in equipment_list if e['name'] == obj2_name), None)
            
            if obj1_data is None or obj2_data is None:
                continue

            # Вычисляем центры объектов
            center1_x = positions[obj1_name]['x'] + int(obj1_data['width'] * SCALE / 2)
            center1_y = positions[obj1_name]['y'] + int(obj1_data['depth'] * SCALE / 2)
            center2_x = positions[obj2_name]['x'] + int(obj2_data['width'] * SCALE / 2)
            center2_y = positions[obj2_name]['y'] + int(obj2_data['depth'] * SCALE / 2)

            # Создаем переменные для расстояния
            max_coord = max(int(room_width * SCALE), int(room_depth * SCALE))
            dx = model.NewIntVar(-max_coord, max_coord, f"dx_{obj1_name}_{obj2_name}")
            dy = model.NewIntVar(-max_coord, max_coord, f"dy_{obj1_name}_{obj2_name}")
            
            model.Add(dx == center1_x - center2_x)
            model.Add(dy == center1_y - center2_y)

            # Ограничение на минимальное расстояние (используем манхэттенское расстояние для упрощения)
            abs_dx = model.NewIntVar(0, max_coord, f"abs_dx_{obj1_name}_{obj2_name}")
            abs_dy = model.NewIntVar(0, max_coord, f"abs_dy_{obj1_name}_{obj2_name}")
            
            model.AddAbsEquality(abs_dx, dx)
            model.AddAbsEquality(abs_dy, dy)
            
            # Минимальное расстояние (используем L1 норму для упрощения)
            model.Add(abs_dx + abs_dy >= value_scaled)
            
            print(f"    - ПРАВИЛО: Расстояние между '{obj1_name}' и '{obj2_name}' >= {value}м.")

    print("3. Запуск решателя OR-Tools...")
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 60.0  # Ограничиваем время решения
    status = solver.Solve(model)

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("  > Решение найдено!")
        
        # Формируем результат
        final_placements = []
        for item in equipment_list:
            x_coord = solver.Value(positions[item['name']]['x']) / SCALE
            y_coord = solver.Value(positions[item['name']]['y']) / SCALE
            
            placement = {
                'name': item['name'],
                'x': x_coord,
                'y': y_coord,
                'width': item['width'],
                'depth': item['depth'],
                'height': item['height'],
                'attributes': item.get('attributes', {})
            }
            final_placements.append(placement)
            print(f"    - {item['name']}: x={x_coord:.2f}, y={y_coord:.2f}")
        
        # Создаем IFC файл
        create_ifc_file(task_data, final_placements)
        
    else:
        print("  > ОШИБКА: Не удалось найти решение.")
        print("  > Проверьте, не противоречат ли правила друг другу или размеры помещения.")

    print("--- ПРОЦЕСС ПРОЕКТИРОВАНИЯ ЗАВЕРШЕН ---")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("\nОшибка: Неверное количество аргументов.")
        print("Пример запуска: python layout_solver.py <URL_Google_Таблицы> <путь_к_task.json>\n")
    else:
        google_sheet_url = sys.argv[1]
        task_json_path = sys.argv[2]
        solve_layout(google_sheet_url, task_json_path)
