import pandas as pd
import ifcopenshell
import ifcopenshell.guid
from ortools.sat.python import cp_model
import sys
import json
import time
import os

### ФИНАЛЬНЫЙ КОД, РЕШАЮЩИЙ ПРОБЛЕМУ ПЕРЕСЕЧЕНИЯ УГЛОВ (ГЕОМЕТРИЯ) ###

def get_rules_from_google_sheet(sheet_url):
    """Загружает правила из Google Таблицы."""
    print("Чтение правил из Google Таблицы...")
    try:
        # Убедимся, что URL корректен для экспорта CSV
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
    
    # 1. Основные сущности и иерархия
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
    context = f.createIfcGeometricRepresentationContext(None, "Model", 3, 1.0E-5, 
                                                        f.createIfcAxis2Placement3D(f.createIfcCartesianPoint([0.0, 0.0, 0.0])))
    project.RepresentationContexts = [context]
    
    site = f.createIfcSite(ifcopenshell.guid.new(), owner_history, "Участок", 
                           ObjectPlacement=f.createIfcLocalPlacement(None, 
                                                                    f.createIfcAxis2Placement3D(f.createIfcCartesianPoint([0.0, 0.0, 0.0]))))
    building = f.createIfcBuilding(ifcopenshell.guid.new(), owner_history, task_data['building_name'], 
                                   ObjectPlacement=f.createIfcLocalPlacement(site.ObjectPlacement, 
                                                                             f.createIfcAxis2Placement3D(f.createIfcCartesianPoint([0.0, 0.0, 0.0]))))
    storey = f.createIfcBuildingStorey(ifcopenshell.guid.new(), owner_history, task_data['storey_name'], 
                                     ObjectPlacement=f.createIfcLocalPlacement(building.ObjectPlacement, 
                                                                               f.createIfcAxis2Placement3D(f.createIfcCartesianPoint([0.0, 0.0, 0.0]))))
    storey_placement = storey.ObjectPlacement # Это базовое размещение для всех элементов внутри этажа

    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, None, None, project, [site])
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, None, None, site, [building])
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, None, None, building, [storey])

    print("  > Создание строительных конструкций (пол и стены)...")
    room_dims = task_data['room_dimensions']
    w, d, h = float(room_dims['width']), float(room_dims['depth']), float(room_dims['height'])
    wall_thickness = 0.2
    slab_thickness = 0.2

    # 2. Создаем Пол
    # Пол должен быть расположен под 0.0 уровнем этажа, поэтому Z-координата отрицательная
    floor_placement = f.createIfcLocalPlacement(storey_placement, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint([w/2, d/2, -slab_thickness])))
    floor_profile = f.createIfcRectangleProfileDef('AREA', None, None, w, d) # Профиль пола
    floor_solid = f.createIfcExtrudedAreaSolid(floor_profile, None, f.createIfcDirection([0.0, 0.0, 1.0]), slab_thickness)
    floor_shape = f.createIfcProductDefinitionShape(None, None, [f.createIfcShapeRepresentation(context, 'Body', 'SweptSolid', [floor_solid])])
    floor = f.createIfcSlab(ifcopenshell.guid.new(), owner_history, "Пол", ObjectPlacement=floor_placement, Representation=floor_shape, PredefinedType='FLOOR')
    f.createIfcRelContainedInSpatialStructure(ifcopenshell.guid.new(), owner_history, None, None, [floor], storey)

    # 3. Создаем Стены
    # Важно: IfcRectangleProfileDef создает прямоугольник, центрированный в (0,0) своей локальной системы координат.
    # Поэтому, чтобы x,y в wall_def['x'], wall_def['y'] соответствовали нижней левой точке стены,
    # необходимо сместить точку вставки на половину длины и ширины стены.
    wall_definitions = [
        # Южная стена: от (0,0) до (w, wall_thickness)
        {'name': 'Стена_Юг', 'x': 0.0, 'y': 0.0, 'len': w, 'wid': wall_thickness},
        # Северная стена: от (0, d-wall_thickness) до (w, d)
        {'name': 'Стена_Север', 'x': 0.0, 'y': d - wall_thickness, 'len': w, 'wid': wall_thickness},
        # Западная стена: от (0, wall_thickness) до (wall_thickness, d - wall_thickness)
        {'name': 'Стена_Запад', 'x': 0.0, 'y': wall_thickness, 'len': wall_thickness, 'wid': d - (2 * wall_thickness)},
        # Восточная стена: от (w-wall_thickness, wall_thickness) до (w, d - wall_thickness)
        {'name': 'Стена_Восток', 'x': w - wall_thickness, 'y': wall_thickness, 'len': wall_thickness, 'wid': d - (2 * wall_thickness)},
    ]

    for wall_def in wall_definitions:
        wall_len = float(wall_def['len'])
        wall_wid = float(wall_def['wid'])
        
        # Смещаем точку вставки на половину размеров стены, чтобы она начиналась от (x,y)
        placement_x = float(wall_def['x']) + wall_len / 2
        placement_y = float(wall_def['y']) + wall_wid / 2
        
        placement = f.createIfcLocalPlacement(storey_placement, 
                                             f.createIfcAxis2Placement3D(f.createIfcCartesianPoint([placement_x, placement_y, 0.0])))
        
        profile = f.createIfcRectangleProfileDef('AREA', None, None, wall_len, wall_wid)
        solid = f.createIfcExtrudedAreaSolid(profile, None, f.createIfcDirection([0.0, 0.0, 1.0]), h)
        shape = f.createIfcProductDefinitionShape(None, None, [f.createIfcShapeRepresentation(context, 'Body', 'SweptSolid', [solid])])
        wall = f.createIfcWall(ifcopenshell.guid.new(), owner_history, wall_def['name'], ObjectPlacement=placement, Representation=shape)
        f.createIfcRelContainedInSpatialStructure(ifcopenshell.guid.new(), owner_history, None, None, [wall], storey)

    # 4. Размещение оборудования
    print("  > Размещение оборудования...")
    for item in placements:
        item_width = float(item['width'])
        item_depth = float(item['depth'])
        item_height = float(item['height'])

        # Аналогично стенам, смещаем точку вставки оборудования
        # x, y из решателя OR-Tools - это minX, minY оборудования.
        # Чтобы центрированный профиль начался с этой точки, смещаем его центр.
        element_placement_x = float(item['x']) + item_width / 2
        element_placement_y = float(item['y']) + item_depth / 2

        element_placement = f.createIfcLocalPlacement(
            storey_placement,
            f.createIfcAxis2Placement3D(
                f.createIfcCartesianPoint([element_placement_x, element_placement_y, 0.0])
            ),
        )

        shape = None
        model_path = item.get("model_path")
        if model_path:
            try:
                ext_ifc = ifcopenshell.open(model_path)
                ext_shape = None
                if ext_ifc.by_type("IfcProductDefinitionShape"):
                    ext_shape = ext_ifc.by_type("IfcProductDefinitionShape")[0]
                elif ext_ifc.by_type("IfcShapeRepresentation"):
                    sr = ext_ifc.by_type("IfcShapeRepresentation")[0]
                    ext_shape = f.createIfcProductDefinitionShape(None, None, [f.add(sr)])

                if ext_shape:
                    rep_map = f.createIfcRepresentationMap(
                        f.createIfcAxis2Placement3D(f.createIfcCartesianPoint([0.0, 0.0, 0.0])),
                        f.add(
                            ext_shape.Representations[0]
                            if hasattr(ext_shape, "Representations")
                            else ext_shape
                        ),
                    )
                    transform = f.createIfcCartesianTransformationOperator3D(
                        None,
                        None,
                        None,
                        f.createIfcCartesianPoint([0.0, 0.0, 0.0]),
                    )
                    mapped_item = f.createIfcMappedItem(rep_map, transform)
                    shape = f.createIfcProductDefinitionShape(
                        None,
                        None,
                        [
                            f.createIfcShapeRepresentation(
                                context, "Body", "MappedRepresentation", [mapped_item]
                            )
                        ],
                    )
                    print(
                        f"    - Использована модель '{model_path}' для '{item['name']}'."
                    )
            except Exception as e:
                print(
                    f"    - ПРЕДУПРЕЖДЕНИЕ: Не удалось загрузить модель '{model_path}'. {e}"
                )

        if shape is None:
            profile = f.createIfcRectangleProfileDef('AREA', None, None, item_width, item_depth)
            solid = f.createIfcExtrudedAreaSolid(
                profile, None, f.createIfcDirection([0.0, 0.0, 1.0]), item_height
            )
            shape = f.createIfcProductDefinitionShape(
                None,
                None,
                [f.createIfcShapeRepresentation(context, 'Body', 'SweptSolid', [solid])],
            )
            print(f"    - Использована упрощенная геометрия для '{item['name']}'.")

        # Используем IfcBuildingElementProxy для общего оборудования
        element = f.createIfcBuildingElementProxy(
            ifcopenshell.guid.new(),
            owner_history,
            item['name'],
            ObjectPlacement=element_placement,
            Representation=shape,
        )

        if 'attributes' in item and item['attributes']:
            prop_values = [f.createIfcPropertySingleValue(k, None, f.createIfcLabel(v), None) for k, v in item['attributes'].items()]
            prop_set = f.createIfcPropertySet(ifcopenshell.guid.new(), owner_history, "Параметры", None, prop_values)
            f.createIfcRelDefinesByProperties(ifcopenshell.guid.new(), owner_history, None, None, [element], prop_set)

        f.createIfcRelContainedInSpatialStructure(ifcopenshell.guid.new(), owner_history, None, None, [element], storey)

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
    print(f"  > Количество объектов оборудования в задании: {len(equipment_list)}")
    room_dims = task_data['room_dimensions']
    room_width = room_dims['width']
    room_depth = room_dims['depth']

    model = cp_model.CpModel()
    SCALE = 1000 # Масштабирование для работы с целыми числами в OR-Tools

    wall_thickness = 0.2
    # Определяем внутренние границы комнаты, чтобы оборудование не выходило за стены
    # Эти границы - это внутренние края помещения, куда может быть помещен minX,minY оборудования
    min_x_room_inner = int(wall_thickness * SCALE)
    max_x_room_inner = int((room_width - wall_thickness) * SCALE)
    min_y_room_inner = int(wall_thickness * SCALE)
    max_y_room_inner = int((room_depth - wall_thickness) * SCALE)

    positions = {}
    for item in equipment_list:
        item_name = item['name']
        item_width_scaled = int(item['width'] * SCALE)
        item_depth_scaled = int(item['depth'] * SCALE)

        # Диапазон координат для оборудования должен учитывать его размеры,
        # чтобы оно не выходило за внутренние стены.
        positions[item_name] = {
            'x': model.NewIntVar(min_x_room_inner, max_x_room_inner - item_width_scaled, f"x_{item_name}"),
            'y': model.NewIntVar(min_y_room_inner, max_y_room_inner - item_depth_scaled, f"y_{item_name}")
        }

    # Ограничение "No Overlap" для оборудования
    intervals_x = [model.NewIntervalVar(positions[item['name']]['x'], int(item['width'] * SCALE), positions[item['name']]['x'] + int(item['width'] * SCALE), f"ix_{item['name']}") for item in equipment_list]
    intervals_y = [model.NewIntervalVar(positions[item['name']]['y'], int(item['depth'] * SCALE), positions[item['name']]['y'] + int(item['depth'] * SCALE), f"iy_{item['name']}") for item in equipment_list]
    model.AddNoOverlap2D(intervals_x, intervals_y)

    print("  > Применение пользовательских правил...")
    for _, rule in rules_df.iterrows():
        rule_type = rule['Тип правила']
        obj1_name = rule['Объект1']
        value_str = str(rule['Значение']).strip()

        if rule_type == 'Запретная зона':
            try:
                x_min, y_min, x_max, y_max = map(float, value_str.split(','))
            except Exception:
                print(
                    f"    - ПРЕДУПРЕЖДЕНИЕ: Некорректное значение запретной зоны '{obj1_name}'. Ожидается 'Xmin,Ymin,Xmax,Ymax'."
                )
                continue

            x_min_s = int(x_min * SCALE)
            y_min_s = int(y_min * SCALE)
            x_max_s = int(x_max * SCALE)
            y_max_s = int(y_max * SCALE)

            # Чтобы исключить касание границы, вводим минимальный
            # отступ в одну масштабированную единицу (1 мм при SCALE=1000)

            zone_safe = obj1_name.replace(' ', '_')
            print(
                f"    - ПРАВИЛО: Запретная зона '{obj1_name}' в области [{x_min}, {y_min}] - [{x_max}, {y_max}]."
            )

            for item in equipment_list:
                iname = item['name']
                width_s = int(item['width'] * SCALE)
                depth_s = int(item['depth'] * SCALE)

                left = model.NewBoolVar(f"{iname}_left_of_{zone_safe}")
                right = model.NewBoolVar(f"{iname}_right_of_{zone_safe}")
                below = model.NewBoolVar(f"{iname}_below_{zone_safe}")
                above = model.NewBoolVar(f"{iname}_above_{zone_safe}")

                # Объект строго слева от зоны (без касания)
                model.Add(positions[iname]['x'] + width_s <= x_min_s - 1).OnlyEnforceIf(left)
                model.Add(positions[iname]['x'] + width_s > x_min_s - 1).OnlyEnforceIf(left.Not())

                # Объект строго справа от зоны (без касания)
                model.Add(positions[iname]['x'] >= x_max_s + 1).OnlyEnforceIf(right)
                model.Add(positions[iname]['x'] < x_max_s + 1).OnlyEnforceIf(right.Not())

                # Объект строго ниже зоны (без касания)
                model.Add(positions[iname]['y'] + depth_s <= y_min_s - 1).OnlyEnforceIf(below)
                model.Add(positions[iname]['y'] + depth_s > y_min_s - 1).OnlyEnforceIf(below.Not())

                # Объект строго выше зоны (без касания)
                model.Add(positions[iname]['y'] >= y_max_s + 1).OnlyEnforceIf(above)
                model.Add(positions[iname]['y'] < y_max_s + 1).OnlyEnforceIf(above.Not())

                # Необходимо выполнение хотя бы одного условия - объект не может пересекать зону
                model.Add(left + right + below + above >= 1)
            continue

        if obj1_name not in positions:
            print(
                f"    - ПРЕДУПРЕЖДЕНИЕ: Объект '{obj1_name}' из правил не найден в task.json. Пропускаем правило."
            )
            continue

        value = float(value_str) if value_str else 0.0
        value_scaled = int(value * SCALE)

        if rule_type == 'Мин. расстояние до':
            obj2_name = rule['Объект2']
            if obj2_name not in positions:
                print(f"    - ПРЕДУПРЕЖДЕНИЕ: Объект '{obj2_name}' из правил не найден в task.json. Пропускаем правило.")
                continue

            obj1_data = next(e for e in equipment_list if e['name'] == obj1_name)
            obj2_data = next(e for e in equipment_list if e['name'] == obj2_name)

            # Расстояние между центрами
            # Координаты из решателя (positions[obj_name]['x']) - это minX,minY.
            # Для нахождения центра нужно добавить половину размера.
            center1_x = positions[obj1_name]['x'] + int(obj1_data['width'] * SCALE / 2)
            center1_y = positions[obj1_name]['y'] + int(obj1_data['depth'] * SCALE / 2)
            center2_x = positions[obj2_name]['x'] + int(obj2_data['width'] * SCALE / 2)
            center2_y = positions[obj2_name]['y'] + int(obj2_data['depth'] * SCALE / 2)

            dx = model.NewIntVar(-int(room_width * SCALE), int(room_width * SCALE), f"dx_{obj1_name}_{obj2_name}")
            dy = model.NewIntVar(-int(room_depth * SCALE), int(room_depth * SCALE), f"dy_{obj1_name}_{obj2_name}")
            model.Add(dx == center1_x - center2_x)
            model.Add(dy == center1_y - center2_y)

            # Используем квадрат расстояния, чтобы избежать sqrt (оптимизация для решателя)
            dx2 = model.NewIntVar(0, int(room_width * SCALE)**2, f"dx2_{obj1_name}_{obj2_name}")
            dy2 = model.NewIntVar(0, int(room_depth * SCALE)**2, f"dy2_{obj1_name}_{obj2_name}")
            model.AddMultiplicationEquality(dx2, dx, dx)
            model.AddMultiplicationEquality(dy2, dy, dy)

            dist_sq_scaled = value_scaled**2
            model.Add(dx2 + dy2 >= dist_sq_scaled)
            print(f"    - ПРАВИЛО: Расстояние между '{obj1_name}' и '{obj2_name}' >= {value}м (между центрами).")
        elif rule_type in ['Выровнять по оси X', 'Выровнять по оси Y']:
            obj2_name = rule['Объект2']
            if obj2_name not in positions:
                print(f"    - ПРЕДУПРЕЖДЕНИЕ: Объект '{obj2_name}' из правил не найден в task.json. Пропускаем правило.")
                continue

            obj1_data = next(e for e in equipment_list if e['name'] == obj1_name)
            obj2_data = next(e for e in equipment_list if e['name'] == obj2_name)

            center1_x = positions[obj1_name]['x'] + int(obj1_data['width'] * SCALE / 2)
            center1_y = positions[obj1_name]['y'] + int(obj1_data['depth'] * SCALE / 2)
            center2_x = positions[obj2_name]['x'] + int(obj2_data['width'] * SCALE / 2)
            center2_y = positions[obj2_name]['y'] + int(obj2_data['depth'] * SCALE / 2)

            if rule_type == 'Выровнять по оси X':
                model.Add(center1_x == center2_x)
                axis = 'X'
            else:
                model.Add(center1_y == center2_y)
                axis = 'Y'
            print(f"    - ПРАВИЛО: Выровнять '{obj1_name}' и '{obj2_name}' по оси {axis}.")
        # Здесь можно добавить другие типы правил при необходимости

    print("3. Запуск решателя OR-Tools...")
    solver = cp_model.CpSolver()
    # Установка лимита по времени для больших или сложных задач
    solver.parameters.max_time_in_seconds = 60.0
    status = solver.Solve(model)
    print(f"  > Статус решателя: {solver.StatusName(status)}")

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("  > Решение найдено!")
        final_placements = [{'name': item['name'],
                             'x': solver.Value(positions[item['name']]['x']) / SCALE,
                             'y': solver.Value(positions[item['name']]['y']) / SCALE,
                             'width': item['width'], 'depth': item['depth'], 'height': item['height'],
                             'attributes': item.get('attributes', {})}
                            for item in equipment_list]
        placed_names = [p['name'] for p in final_placements]
        print(f"  > Размещено объектов: {len(final_placements)} из {len(equipment_list)}")
        print("    - " + ", ".join(placed_names))
        create_ifc_file(task_data, final_placements)
    else:
        print("  > ОШИБКА: Не удалось найти решение. Проверьте, не противоречат ли правила друг другу или слишком ли тесное помещение.")
        if status == cp_model.INFEASIBLE:
            print("    > Статус решателя: INFEASIBLE (Неразрешимо). Правила противоречат друг другу или нет места.")
        elif status == cp_model.MODEL_INVALID:
            print("    > Статус решателя: MODEL_INVALID (Модель неверна). Внутренняя ошибка модели CP-SAT.")
        elif status == cp_model.UNKNOWN:
            print("    > Статус решателя: UNKNOWN (Решение не найдено в отведенное время, или возникла другая проблема).")
        else:
            print(f"    > Неизвестный статус решателя: {solver.StatusName(status)}")

    print("--- ПРОЦЕСС ПРОЕКТИРОВАНИЯ ЗАВЕРШЕН ---")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("\nОшибка: Неверное количество аргументов.\nПример запуска: python layout_solver.py <URL_Google_Таблицы> <путь_к_task.json>\n")
    else:
        google_sheet_url = sys.argv[1]
        task_json_path = sys.argv[2]
        solve_layout(google_sheet_url, task_json_path)
