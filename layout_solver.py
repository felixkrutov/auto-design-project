import pandas as pd
import ifcopenshell
import ifcopenshell.guid
from ortools.sat.python import cp_model
import sys
import json
import time
import os
import math

def normalize_name(name: str) -> str:
    """Normalize equipment names for consistent matching."""
    return name.strip().replace(' ', '_').lower()

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

    # Основные сущности и иерархия
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
    storey_placement = storey.ObjectPlacement

    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, None, None, project, [site])
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, None, None, site, [building])
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, None, None, building, [storey])

    print("  > Создание строительных конструкций (пол и стены)...")
    room_dims = task_data['room_dimensions']
    w, d, h = float(room_dims['width']), float(room_dims['depth']), float(room_dims['height'])
    wall_thickness = 0.2
    slab_thickness = 0.2

    # Создаем Пол
    floor_placement = f.createIfcLocalPlacement(storey_placement, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint([w/2, d/2, -slab_thickness])))
    floor_profile = f.createIfcRectangleProfileDef('AREA', None, None, w, d)
    floor_solid = f.createIfcExtrudedAreaSolid(floor_profile, None, f.createIfcDirection([0.0, 0.0, 1.0]), slab_thickness)
    floor_shape = f.createIfcProductDefinitionShape(None, None, [f.createIfcShapeRepresentation(context, 'Body', 'SweptSolid', [floor_solid])])
    floor = f.createIfcSlab(ifcopenshell.guid.new(), owner_history, "Пол", ObjectPlacement=floor_placement, Representation=floor_shape, PredefinedType='FLOOR')
    f.createIfcRelContainedInSpatialStructure(ifcopenshell.guid.new(), owner_history, None, None, [floor], storey)

    # Создаем Стены
    wall_definitions = [
        {'name': 'Стена_Юг', 'x': 0.0, 'y': 0.0, 'len': w, 'wid': wall_thickness},
        {'name': 'Стена_Север', 'x': 0.0, 'y': d - wall_thickness, 'len': w, 'wid': wall_thickness},
        {'name': 'Стена_Запад', 'x': 0.0, 'y': wall_thickness, 'len': wall_thickness, 'wid': d - (2 * wall_thickness)},
        {'name': 'Стена_Восток', 'x': w - wall_thickness, 'y': wall_thickness, 'len': wall_thickness, 'wid': d - (2 * wall_thickness)},
    ]

    for wall_def in wall_definitions:
        wall_len = float(wall_def['len'])
        wall_wid = float(wall_def['wid'])

        placement_x = float(wall_def['x']) + wall_len / 2
        placement_y = float(wall_def['y']) + wall_wid / 2

        placement = f.createIfcLocalPlacement(storey_placement,
                                             f.createIfcAxis2Placement3D(f.createIfcCartesianPoint([placement_x, placement_y, 0.0])))

        profile = f.createIfcRectangleProfileDef('AREA', None, None, wall_len, wall_wid)
        solid = f.createIfcExtrudedAreaSolid(profile, None, f.createIfcDirection([0.0, 0.0, 1.0]), h)
        shape = f.createIfcProductDefinitionShape(None, None, [f.createIfcShapeRepresentation(context, 'Body', 'SweptSolid', [solid])])
        wall = f.createIfcWall(ifcopenshell.guid.new(), owner_history, wall_def['name'], ObjectPlacement=placement, Representation=shape)
        f.createIfcRelContainedInSpatialStructure(ifcopenshell.guid.new(), owner_history, None, None, [wall], storey)

    # Размещение оборудования
    print("  > Размещение оборудования...")
    for item in placements:
        item_width = float(item['width'])
        item_depth = float(item['depth'])
        item_height = float(item['height'])

        element_placement_x = float(item['x']) + item_width / 2
        element_placement_y = float(item['y']) + item_depth / 2

        rot_deg = float(item.get('rotation_deg', 0.0))
        rot_rad = math.radians(rot_deg)

        element_placement = f.createIfcLocalPlacement(
            storey_placement,
            f.createIfcAxis2Placement3D(
                f.createIfcCartesianPoint([element_placement_x, element_placement_y, 0.0]),
                f.createIfcDirection([0.0, 0.0, 1.0]),
                f.createIfcDirection([math.cos(rot_rad), math.sin(rot_rad), 0.0]),
            ),
        )

        shape = None
        model_path = item.get("model_path")
        if not model_path:
            candidate1 = os.path.join("models", f"{item['name']}.ifc")
            candidate2 = os.path.join("models", f"{item['name'].replace(' ', '_')}.ifc")
            if os.path.exists(candidate1):
                model_path = candidate1
            elif os.path.exists(candidate2):
                model_path = candidate2

        if model_path and os.path.exists(model_path):
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
                    print(f"    - Использована модель '{model_path}' для '{item['name']}'.")
            except Exception as e:
                print(f"    - ПРЕДУПРЕЖДЕНИЕ: Не удалось загрузить модель '{model_path}'. {e}")

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
        print(f"  > ОШИБКА: Не удалось прочитать файл задания. {e}")
        return

    rules_df = get_rules_from_google_sheet(sheet_url)
    if rules_df is None:
        return

    print("2. Настройка модели и ограничений...")
    equipment_list = task_data['equipment']
    print(f"  > Количество объектов оборудования в задании: {len(equipment_list)}")
    room_dims = task_data['room_dimensions']
    room_width = room_dims['width']
    room_depth = room_dims['depth']

    model = cp_model.CpModel()
    SCALE = 1000  # Масштабирование для работы с целыми числами
    ZONE_MARGIN = 1  # 1 мм для строгого исключения из запретных зон

    wall_thickness = 0.2
    min_x_room_inner = int(wall_thickness * SCALE)
    max_x_room_inner = int((room_width - wall_thickness) * SCALE)
    min_y_room_inner = int(wall_thickness * SCALE)
    max_y_room_inner = int((room_depth - wall_thickness) * SCALE)

    positions = {}
    equipment_by_name = {}

    for item in equipment_list:
        key = normalize_name(item['name'])
        equipment_by_name[key] = item
    
    for item in equipment_list:
        key = normalize_name(item['name'])
        item_width_scaled = int(item['width'] * SCALE)
        item_depth_scaled = int(item['depth'] * SCALE)

        positions[key] = {
            'x': model.NewIntVar(min_x_room_inner, max_x_room_inner - item_width_scaled, f"x_{key}"),
            'y': model.NewIntVar(min_y_room_inner, max_y_room_inner - item_depth_scaled, f"y_{key}")
        }

    # Ограничение "No Overlap" для оборудования
    intervals_x = [
        model.NewIntervalVar(
            positions[normalize_name(item['name'])]['x'],
            int(item['width'] * SCALE),
            positions[normalize_name(item['name'])]['x'] + int(item['width'] * SCALE),
            f"ix_{normalize_name(item['name'])}"
        )
        for item in equipment_list
    ]
    intervals_y = [
        model.NewIntervalVar(
            positions[normalize_name(item['name'])]['y'],
            int(item['depth'] * SCALE),
            positions[normalize_name(item['name'])]['y'] + int(item['depth'] * SCALE),
            f"iy_{normalize_name(item['name'])}"
        )
        for item in equipment_list
    ]
    model.AddNoOverlap2D(intervals_x, intervals_y)

    print("  > Применение пользовательских правил...")
    applied_rules = []
    flow_pairs = []
    group_rules = []
    for _, rule in rules_df.iterrows():
        rule_type = rule['Тип правила']
        obj1_name = rule['Объект1']
        obj1_key = normalize_name(obj1_name)
        value_str = str(rule['Значение']).strip()

        if rule_type == 'Запретная зона':
            try:
                x_min, y_min, x_max, y_max = map(float, value_str.split(','))
            except Exception:
                print(f"    - ПРЕДУПРЕЖДЕНИЕ: Некорректное значение запретной зоны '{obj1_name}'. Ожидается 'Xmin,Ymin,Xmax,Ymax'.")
                continue

            x_min_s = int(round(x_min * SCALE))
            y_min_s = int(round(y_min * SCALE))
            x_max_s = int(round(x_max * SCALE))
            y_max_s = int(round(y_max * SCALE))

            zone_safe = obj1_name.replace(' ', '_')
            print(f"    - ПРАВИЛО: Запретная зона '{obj1_name}' в области [{x_min}, {y_min}] - [{x_max}, {y_max}].")
            applied_rules.append(f"Запретная зона {obj1_name} [{x_min},{y_min},{x_max},{y_max}]")

            for item in equipment_list:
                iname = normalize_name(item['name'])

                width_s = int(item['width'] * SCALE)
                depth_s = int(item['depth'] * SCALE)

                left = model.NewBoolVar(f"{iname}_left_of_{zone_safe}")
                right = model.NewBoolVar(f"{iname}_right_of_{zone_safe}")
                below = model.NewBoolVar(f"{iname}_below_{zone_safe}")
                above = model.NewBoolVar(f"{iname}_above_{zone_safe}")

                model.Add(positions[iname]['x'] + width_s <= x_min_s - ZONE_MARGIN).OnlyEnforceIf(left)
                model.Add(positions[iname]['x'] >= x_max_s + ZONE_MARGIN).OnlyEnforceIf(right)
                model.Add(positions[iname]['y'] + depth_s <= y_min_s - ZONE_MARGIN).OnlyEnforceIf(below)
                model.Add(positions[iname]['y'] >= y_max_s + ZONE_MARGIN).OnlyEnforceIf(above)

                model.AddBoolOr([left, right, below, above])
            continue

        # НОВЫЕ ТИПЫ ПРАВИЛ ДЛЯ РЕАЛИСТИЧНОГО ЗАВОДА
        
        if rule_type == 'Технологическая последовательность':
            # Объект1 должен быть перед Объект2 в направлении потока
            obj2_name = rule['Объект2']
            obj2_key = normalize_name(obj2_name)
            obj2_key = normalize_name(obj2_name)
            obj2_key = normalize_name(obj2_name)
            direction = rule.get('Направление', 'Y').strip()  # по умолчанию поток по Y
            
            if obj1_key not in positions or obj2_key not in positions:
                print(f"    - ПРЕДУПРЕЖДЕНИЕ: Один из объектов '{obj1_name}' или '{obj2_name}' не найден.")
                continue

            obj1_data = equipment_by_name[obj1_key]
            obj2_data = equipment_by_name[obj2_key]

            if direction == 'Y':
                # obj1 должен быть "ниже" obj2 по Y (меньшая Y координата)
                # Учитываем размеры объектов для корректного расчета
                obj1_end_y = positions[obj1_key]['y'] + int(obj1_data['depth'] * SCALE)
                obj2_start_y = positions[obj2_key]['y']
                model.Add(obj1_end_y + int(2.0 * SCALE) <= obj2_start_y)  # минимум 2м между объектами
            else:  # direction == 'X'
                # obj1 должен быть "левее" obj2 по X
                obj1_end_x = positions[obj1_key]['x'] + int(obj1_data['width'] * SCALE)
                obj2_start_x = positions[obj2_key]['x']
                model.Add(obj1_end_x + int(2.0 * SCALE) <= obj2_start_x)

            print(f"    - ПРАВИЛО: Технологическая последовательность '{obj1_name}' -> '{obj2_name}' по оси {direction}.")
            applied_rules.append(f"Техпоследовательность {obj1_name}->{obj2_name} {direction}")
            flow_pairs.append((obj1_key, obj2_key))

        elif rule_type == 'Производственная зона':
            # Ограничивает объект определенной зоной
            try:
                x_min, y_min, x_max, y_max = map(float, value_str.split(','))
            except Exception:
                print(f"    - ПРЕДУПРЕЖДЕНИЕ: Некорректное значение зоны для '{obj1_name}'. Ожидается 'Xmin,Ymin,Xmax,Ymax'.")
                continue

            if obj1_key not in positions:
                print(f"    - ПРЕДУПРЕЖДЕНИЕ: Объект '{obj1_name}' не найден.")
                continue

            obj_data = equipment_by_name[obj1_key]
            x_min_s = int(x_min * SCALE)
            y_min_s = int(y_min * SCALE)
            x_max_s = int(x_max * SCALE)
            y_max_s = int(y_max * SCALE)
            
            # Объект должен полностью помещаться в зону
            model.Add(positions[obj1_key]['x'] >= x_min_s)
            model.Add(positions[obj1_key]['y'] >= y_min_s)
            model.Add(positions[obj1_key]['x'] + int(obj_data['width'] * SCALE) <= x_max_s)
            model.Add(positions[obj1_key]['y'] + int(obj_data['depth'] * SCALE) <= y_max_s)

            print(f"    - ПРАВИЛО: Объект '{obj1_name}' ограничен зоной [{x_min}, {y_min}] - [{x_max}, {y_max}].")
            applied_rules.append(f"Производственная зона для {obj1_name} [{x_min},{y_min},{x_max},{y_max}]")

        elif rule_type == 'Параллельная линия':
            # Объекты должны быть на одной линии (выровнены) с определенным смещением
            obj2_name = rule['Объект2']
            offset = float(value_str) if value_str else 0.0
            
            if obj1_key not in positions or obj2_key not in positions:
                print(f"    - ПРЕДУПРЕЖДЕНИЕ: Один из объектов '{obj1_name}' или '{obj2_name}' не найден.")
                continue

            obj1_data = equipment_by_name[obj1_key]
            obj2_data = equipment_by_name[obj2_key]

            # Центры объектов по X должны быть смещены на offset
            center1_x = positions[obj1_key]['x'] + int(obj1_data['width'] * SCALE / 2)
            center2_x = positions[obj2_key]['x'] + int(obj2_data['width'] * SCALE / 2)
            
            model.Add(center2_x == center1_x + int(offset * SCALE))

            print(f"    - ПРАВИЛО: Параллельная линия '{obj1_name}' и '{obj2_name}' со смещением {offset}м.")
            applied_rules.append(f"Параллельная линия {obj1_name}-{obj2_name} offset {offset}")

        elif rule_type == 'Коридор':
            # Обеспечивает свободный коридор между точками
            try:
                x1, y1, x2, y2, width = map(float, value_str.split(','))
            except Exception:
                print(f"    - ПРЕДУПРЕЖДЕНИЕ: Некорректное значение коридора. Ожидается 'X1,Y1,X2,Y2,Ширина'.")
                continue

            # Создаем запретную зону в виде прямоугольника коридора
            corridor_x_min = min(x1, x2) - width/2
            corridor_x_max = max(x1, x2) + width/2
            corridor_y_min = min(y1, y2) - width/2
            corridor_y_max = max(y1, y2) + width/2

            corridor_x_min_s = int(corridor_x_min * SCALE)
            corridor_x_max_s = int(corridor_x_max * SCALE)
            corridor_y_min_s = int(corridor_y_min * SCALE)
            corridor_y_max_s = int(corridor_y_max * SCALE)

            print(f"    - ПРАВИЛО: Коридор от ({x1}, {y1}) до ({x2}, {y2}) шириной {width}м.")
            applied_rules.append(f"Коридор ({x1},{y1})->({x2},{y2}) width {width}")

            for item in equipment_list:
                iname = normalize_name(item['name'])
                width_s = int(item['width'] * SCALE)
                depth_s = int(item['depth'] * SCALE)

                left = model.NewBoolVar(f"{iname}_left_of_corridor")
                right = model.NewBoolVar(f"{iname}_right_of_corridor")
                below = model.NewBoolVar(f"{iname}_below_corridor")
                above = model.NewBoolVar(f"{iname}_above_corridor")

                model.Add(positions[iname]['x'] + width_s <= corridor_x_min_s - ZONE_MARGIN).OnlyEnforceIf(left)
                model.Add(positions[iname]['x'] >= corridor_x_max_s + ZONE_MARGIN).OnlyEnforceIf(right)
                model.Add(positions[iname]['y'] + depth_s <= corridor_y_min_s - ZONE_MARGIN).OnlyEnforceIf(below)
                model.Add(positions[iname]['y'] >= corridor_y_max_s + ZONE_MARGIN).OnlyEnforceIf(above)

                model.AddBoolOr([left, right, below, above])

        elif rule_type == 'Привязка к стене':
            # Значение: сторона,отступ
            if obj1_key not in positions:
                print(f"    - ПРЕДУПРЕЖДЕНИЕ: Объект '{obj1_name}' не найден.")
                continue
            try:
                side, dist = value_str.split(',')
                dist = float(dist)
            except Exception:
                print(f"    - ПРЕДУПРЕЖДЕНИЕ: Некорректное значение привязки к стене для '{obj1_name}'.")
                continue
            pos = positions[obj1_key]
            obj_data = equipment_by_name[obj1_key]
            if side == 'Xmin':
                model.Add(pos['x'] == int((dist + wall_thickness) * SCALE))
            elif side == 'Xmax':
                model.Add(pos['x'] + int(obj_data['width'] * SCALE) == int((room_width - wall_thickness - dist) * SCALE))
            elif side == 'Ymin':
                model.Add(pos['y'] == int((dist + wall_thickness) * SCALE))
            elif side == 'Ymax':
                model.Add(pos['y'] + int(obj_data['depth'] * SCALE) == int((room_depth - wall_thickness - dist) * SCALE))
            print(f"    - ПРАВИЛО: Привязка '{obj1_name}' к стене {side} с отступом {dist}м.")
            applied_rules.append(f"Привязка {obj1_name} {side} {dist}")

        elif rule_type == 'Зона обслуживания':
            if obj1_key not in positions:
                print(f"    - ПРЕДУПРЕЖДЕНИЕ: Объект '{obj1_name}' не найден.")
                continue
            try:
                margin = float(value_str)
            except Exception:
                print(f"    - ПРЕДУПРЕЖДЕНИЕ: Некорректное значение зоны обслуживания для '{obj1_name}'.")
                continue
            obj1_data = equipment_by_name[obj1_key]
            for other in equipment_list:
                other_key = normalize_name(other['name'])
                if other_key == obj1_key:
                    continue
                obj2_data = equipment_by_name[other_key]
                center1_x = positions[obj1_key]['x'] + int(obj1_data['width'] * SCALE / 2)
                center1_y = positions[obj1_key]['y'] + int(obj1_data['depth'] * SCALE / 2)
                center2_x = positions[other_key]['x'] + int(obj2_data['width'] * SCALE / 2)
                center2_y = positions[other_key]['y'] + int(obj2_data['depth'] * SCALE / 2)
                dx = model.NewIntVar(-int(room_width * SCALE), int(room_width * SCALE), f"svc_dx_{obj1_key}_{other_key}")
                dy = model.NewIntVar(-int(room_depth * SCALE), int(room_depth * SCALE), f"svc_dy_{obj1_key}_{other_key}")
                model.Add(dx == center1_x - center2_x)
                model.Add(dy == center1_y - center2_y)
                dx2 = model.NewIntVar(0, int(room_width * SCALE) ** 2, f"svc_dx2_{obj1_key}_{other_key}")
                dy2 = model.NewIntVar(0, int(room_depth * SCALE) ** 2, f"svc_dy2_{obj1_key}_{other_key}")
                model.AddMultiplicationEquality(dx2, dx, dx)
                model.AddMultiplicationEquality(dy2, dy, dy)
                min_sq = int((margin * SCALE) ** 2)
                model.Add(dx2 + dy2 >= min_sq)
            applied_rules.append(f"Зона обслуживания {obj1_name} {margin}")

        elif rule_type == 'Компактная группировка':
            # value: name1;name2;name3
            group_raw = [s.strip() for s in value_str.split(';') if s.strip()]
            group_keys = [normalize_name(s) for s in group_raw]
            if obj1_name.strip():
                group_keys.append(obj1_key)
            missing = [g for g in group_keys if g not in positions]
            if missing:
                print(f"    - ПРЕДУПРЕЖДЕНИЕ: Объекты {missing} не найдены для группировки.")
                continue
            group_rules.append(group_keys)
            print(f"    - ПРАВИЛО: Компактная группировка {group_raw}.")
            applied_rules.append(f"Группировка {';'.join(group_raw)}")

        elif rule_type == 'Ориентация':
            if obj1_key not in equipment_by_name:
                print(f"    - ПРЕДУПРЕЖДЕНИЕ: Объект '{obj1_name}' не найден.")
                continue
            try:
                angle = float(value_str)
            except Exception:
                print(f"    - ПРЕДУПРЕЖДЕНИЕ: Некорректное значение ориентации для '{obj1_name}'.")
                continue
            equipment_by_name[obj1_key]['rotation_deg'] = angle
            print(f"    - ПРАВИЛО: Ориентация '{obj1_name}' = {angle}°")
            applied_rules.append(f"Ориентация {obj1_name} {angle}")

        # СТАНДАРТНЫЕ ПРАВИЛА (сохраняем старые)
        elif rule_type == 'Мин. расстояние до':
            obj2_name = rule['Объект2']
            obj2_key = normalize_name(obj2_name)
            if obj1_key not in positions or obj2_key not in positions:
                print(f"    - ПРЕДУПРЕЖДЕНИЕ: Один из объектов '{obj1_name}' или '{obj2_name}' не найден.")
                continue

            obj1_data = equipment_by_name[obj1_key]
            obj2_data = equipment_by_name[obj2_key]
            value = float(value_str) if value_str else 0.0
            value_scaled = int(value * SCALE)

            center1_x = positions[obj1_key]['x'] + int(obj1_data['width'] * SCALE / 2)
            center1_y = positions[obj1_key]['y'] + int(obj1_data['depth'] * SCALE / 2)
            center2_x = positions[obj2_key]['x'] + int(obj2_data['width'] * SCALE / 2)
            center2_y = positions[obj2_key]['y'] + int(obj2_data['depth'] * SCALE / 2)

            dx = model.NewIntVar(-int(room_width * SCALE), int(room_width * SCALE), f"dx_{obj1_key}_{obj2_key}")
            dy = model.NewIntVar(-int(room_depth * SCALE), int(room_depth * SCALE), f"dy_{obj1_key}_{obj2_key}")
            model.Add(dx == center1_x - center2_x)
            model.Add(dy == center1_y - center2_y)

            dx2 = model.NewIntVar(0, int(room_width * SCALE) ** 2, f"dx2_{obj1_key}_{obj2_key}")
            dy2 = model.NewIntVar(0, int(room_depth * SCALE) ** 2, f"dy2_{obj1_key}_{obj2_key}")
            model.AddMultiplicationEquality(dx2, dx, dx)
            model.AddMultiplicationEquality(dy2, dy, dy)

            dist_sq_scaled = value_scaled**2
            model.Add(dx2 + dy2 >= dist_sq_scaled)
            print(f"    - ПРАВИЛО: Расстояние между '{obj1_name}' и '{obj2_name}' >= {value}м.")
            applied_rules.append(f"Мин. расстояние {obj1_name}-{obj2_name} {value}")

        elif rule_type in ['Выровнять по оси X', 'Выровнять по оси Y']:
            obj2_name = rule['Объект2']
            if obj1_key not in positions or obj2_key not in positions:
                print(f"    - ПРЕДУПРЕЖДЕНИЕ: Один из объектов '{obj1_name}' или '{obj2_name}' не найден.")
                continue

            obj1_data = equipment_by_name[obj1_key]
            obj2_data = equipment_by_name[obj2_key]

            center1_x = positions[obj1_key]['x'] + int(obj1_data['width'] * SCALE / 2)
            center1_y = positions[obj1_key]['y'] + int(obj1_data['depth'] * SCALE / 2)
            center2_x = positions[obj2_key]['x'] + int(obj2_data['width'] * SCALE / 2)
            center2_y = positions[obj2_key]['y'] + int(obj2_data['depth'] * SCALE / 2)

            if rule_type == 'Выровнять по оси X':
                model.Add(center1_x == center2_x)
                axis = 'X'
            else:
                model.Add(center1_y == center2_y)
                axis = 'Y'
            print(f"    - ПРАВИЛО: Выровнять '{obj1_name}' и '{obj2_name}' по оси {axis}.")
            applied_rules.append(f"Выровнять {obj1_name}-{obj2_name} axis {axis}")

    # ЦЕЛЕВАЯ ФУНКЦИЯ ДЛЯ ОПТИМИЗАЦИИ КОМПАКТНОСТИ
    print("  > Добавление целевой функции для компактности...")
    
    # Минимизируем общий разброс объектов (делаем планировку более компактной)
    total_x_spread = model.NewIntVar(0, int(room_width * SCALE), "total_x_spread")
    total_y_spread = model.NewIntVar(0, int(room_depth * SCALE), "total_y_spread")
    
    if equipment_list:
        # Находим минимальные и максимальные координаты всех объектов
        min_x_all = model.NewIntVar(min_x_room_inner, max_x_room_inner, "min_x_all")
        max_x_all = model.NewIntVar(min_x_room_inner, max_x_room_inner, "max_x_all")
        min_y_all = model.NewIntVar(min_y_room_inner, max_y_room_inner, "min_y_all")
        max_y_all = model.NewIntVar(min_y_room_inner, max_y_room_inner, "max_y_all")

        # Минимальная X координата среди всех объектов
        for item in equipment_list:
            key = normalize_name(item['name'])
            model.Add(min_x_all <= positions[key]['x'])

        # Максимальная X координата среди всех объектов
        for item in equipment_list:
            key = normalize_name(item['name'])
            model.Add(max_x_all >= positions[key]['x'] + int(item['width'] * SCALE))

        # Минимальная Y координата среди всех объектов
        for item in equipment_list:
            key = normalize_name(item['name'])
            model.Add(min_y_all <= positions[key]['y'])

        # Максимальная Y координата среди всех объектов
        for item in equipment_list:
            key = normalize_name(item['name'])
            model.Add(max_y_all >= positions[key]['y'] + int(item['depth'] * SCALE))

        model.Add(total_x_spread == max_x_all - min_x_all)
        model.Add(total_y_spread == max_y_all - min_y_all)
    else:
        model.Add(total_x_spread == 0)
        model.Add(total_y_spread == 0)

    flow_terms = []
    for a, b in flow_pairs:
        a_data = equipment_by_name[a]
        b_data = equipment_by_name[b]
        a_cx = positions[a]['x'] + int(a_data['width'] * SCALE / 2)
        a_cy = positions[a]['y'] + int(a_data['depth'] * SCALE / 2)
        b_cx = positions[b]['x'] + int(b_data['width'] * SCALE / 2)
        b_cy = positions[b]['y'] + int(b_data['depth'] * SCALE / 2)
        dx = model.NewIntVar(0, int(room_width * SCALE), f"flow_dx_{a}_{b}")
        dy = model.NewIntVar(0, int(room_depth * SCALE), f"flow_dy_{a}_{b}")
        model.AddAbsEquality(dx, a_cx - b_cx)
        model.AddAbsEquality(dy, a_cy - b_cy)
        dist = model.NewIntVar(0, int(room_width * SCALE + room_depth * SCALE), f"flow_dist_{a}_{b}")
        model.Add(dist == dx + dy)
        flow_terms.append(dist)

    group_terms = []
    for g in group_rules:
        if len(g) < 2:
            continue
        for i in range(len(g)):
            for j in range(i + 1, len(g)):
                a = g[i]
                b = g[j]
                a_data = equipment_by_name[a]
                b_data = equipment_by_name[b]
                a_cx = positions[a]['x'] + int(a_data['width'] * SCALE / 2)
                a_cy = positions[a]['y'] + int(a_data['depth'] * SCALE / 2)
                b_cx = positions[b]['x'] + int(b_data['width'] * SCALE / 2)
                b_cy = positions[b]['y'] + int(b_data['depth'] * SCALE / 2)
                dx = model.NewIntVar(0, int(room_width * SCALE), f"grp_dx_{a}_{b}")
                dy = model.NewIntVar(0, int(room_depth * SCALE), f"grp_dy_{a}_{b}")
                model.AddAbsEquality(dx, a_cx - b_cx)
                model.AddAbsEquality(dy, a_cy - b_cy)
                dist = model.NewIntVar(0, int(room_width * SCALE + room_depth * SCALE), f"grp_dist_{a}_{b}")
                model.Add(dist == dx + dy)
                group_terms.append(dist)

    model.Minimize(total_x_spread + total_y_spread + sum(flow_terms) + sum(group_terms))

    print("3. Запуск решателя OR-Tools...")
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 60.0
    status = solver.Solve(model)
    print(f"  > Статус решателя: {solver.StatusName(status)}")

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("  > Решение найдено!")
        final_placements = []
        for item in equipment_list:
            key = normalize_name(item['name'])
            updated_rot = equipment_by_name.get(key, {}).get('rotation_deg', item.get('rotation_deg', 0.0))
            item['rotation_deg'] = updated_rot
            final_placements.append({
                'name': item['name'],
                'x': solver.Value(positions[key]['x']) / SCALE,
                'y': solver.Value(positions[key]['y']) / SCALE,
                'width': item['width'],
                'depth': item['depth'],
                'height': item['height'],
                'rotation_deg': updated_rot,
                'model_path': item.get('model_path'),
                'attributes': item.get('attributes', {})
            })

        placed_names = [p['name'] for p in final_placements]
        print(f"  > Размещено объектов: {len(final_placements)} из {len(equipment_list)}")
        print("    - " + ", ".join(placed_names))
        create_ifc_file(task_data, final_placements)
    else:
        print("  > ОШИБКА: Не удалось найти решение. Проверьте, не противоречат ли правила друг другу или слишком ли тесное помещение.")
        if applied_rules:
            print("    > Возможно, конфликтуют следующие правила:")
            for r in applied_rules:
                print(f"      - {r}")
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
