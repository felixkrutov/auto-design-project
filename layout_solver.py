import pandas as pd
import ifcopenshell
import ifcopenshell.guid
from ortools.sat.python import cp_model
import sys
import json
import time
import os
import math
import re
import unicodedata
import hashlib

def normalize_name(name: str) -> str:
    """Normalizes equipment names and produces deterministic ASCII identifiers.

    In the original implementation Cyrillic characters were stripped which
    resulted in different items mapping to the same ``__`` name.  The updated
    algorithm transliterates characters to Latin, removes unsupported symbols
    and appends a short hash of the original string to guarantee uniqueness.
    """

    if not name:
        return ""

    # Remove control characters and normalize unicode representation
    name_clean = ''.join(
        c for c in name if unicodedata.category(c) not in ('Cc', 'Cf', 'Cs', 'Co', 'Cn')
    )
    name_clean = unicodedata.normalize('NFC', name_clean)
    name_clean = re.sub(r'\s+', ' ', name_clean.strip())

    # Simple transliteration for Cyrillic -> Latin characters
    cyr_map = {
        'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E', 'Ё': 'E',
        'Ж': 'Zh', 'З': 'Z', 'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L', 'М': 'M',
        'Н': 'N', 'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U',
        'Ф': 'F', 'Х': 'Kh', 'Ц': 'Ts', 'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Shch',
        'Ы': 'Y', 'Э': 'E', 'Ю': 'Yu', 'Я': 'Ya',
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
        'ы': 'y', 'э': 'e', 'ю': 'yu', 'я': 'ya', 'ь': '', 'ъ': ''
    }
    transliterated = ''.join(cyr_map.get(ch, ch) for ch in name_clean)

    transliterated = transliterated.replace(' ', '_').lower()
    transliterated = re.sub(r'[^a-z0-9_]+', '', transliterated)

    # Add short hash to keep identifier unique even if transliteration collides
    digest = hashlib.sha1(name.encode('utf-8')).hexdigest()[:6]
    if transliterated:
        return f"{transliterated}_{digest}"
    return digest

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
    SOFT_PENALTY_WEIGHT = 100  # Коэффициент штрафов за мягкие ограничения

    wall_thickness = 0.2
    min_x_room_inner = int(wall_thickness * SCALE)
    max_x_room_inner = int((room_width - wall_thickness) * SCALE)
    min_y_room_inner = int(wall_thickness * SCALE)
    max_y_room_inner = int((room_depth - wall_thickness) * SCALE)

    positions = {}
    equipment_by_name = {}

    # УСИЛЕННАЯ ДИАГНОСТИКА И НОРМАЛИЗАЦИЯ: Создание словарей с отладочными выводами
    print("  > ДИАГНОСТИКА: Создание словарей оборудования и нормализация имен из task.json...")
    for item in equipment_list:
        original_name = item['name']
        key = normalize_name(original_name)
        equipment_by_name[key] = item
        positions[key] = {
            'x': model.NewIntVar(min_x_room_inner, max_x_room_inner - int(item['width'] * SCALE), f"x_{key}"),
            'y': model.NewIntVar(min_y_room_inner, max_y_room_inner - int(item['depth'] * SCALE), f"y_{key}")
        }
        print(f"    - Оригинальное имя: {repr(original_name)} -> Нормализованное: {repr(key)}")
    
    print(f"  > DEBUG: Normalized names from task.json: {[repr(key) for key in equipment_by_name.keys()]}")

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
    # Списки мягких штрафов для целевой функции
    seq_penalties = []
    zone_penalties = []
    corridor_penalties = []
    
    for _, rule in rules_df.iterrows():
        rule_type = rule['Тип правила'].strip()
        obj1_name_orig = rule['Объект1'].strip()
        obj2_name_orig = rule.get('Объект2', '').strip()
        value_str = str(rule['Значение']).strip()

        # УСИЛЕННАЯ ДИАГНОСТИКА: Отладка правил
        obj1_key = normalize_name(obj1_name_orig)
        obj2_key = normalize_name(obj2_name_orig)
        
        print(f"  > DEBUG: Rule '{rule_type}': obj1_orig={repr(obj1_name_orig)} -> obj1_norm={repr(obj1_key)}")
        if obj2_name_orig:
            print(f"    obj2_orig={repr(obj2_name_orig)} -> obj2_norm={repr(obj2_key)}")

        # СПЕЦИАЛЬНАЯ ОБРАБОТКА ДЛЯ ПРАВИЛ БЕЗ ПОИСКА ОБЪЕКТОВ (Зоны/Коридоры применяются ко ВСЕМ объектам)
        if rule_type == 'Запретная зона':
            try:
                x_min, y_min, x_max, y_max = map(float, value_str.split(','))
            except Exception:
                print(f"    - ПРЕДУПРЕЖДЕНИЕ: Некорректное значение запретной зоны '{obj1_name_orig}'. Ожидается 'Xmin,Ymin,Xmax,Ymax'.")
                continue

            x_min_s = int(round(x_min * SCALE))
            y_min_s = int(round(y_min * SCALE))
            x_max_s = int(round(x_max * SCALE))
            y_max_s = int(round(y_max * SCALE))

            zone_safe_name = obj1_name_orig.replace(' ', '_') # Используем оригинальное имя для читаемости в логах
            print(f"    - ПРАВИЛО: Запретная зона '{obj1_name_orig}' в области [{x_min}, {y_min}] - [{x_max}, {y_max}].")
            applied_rules.append(f"Запретная зона {obj1_name_orig} [{x_min},{y_min},{x_max},{y_max}]")

            for item in equipment_list: # Применяем ко ВСЕМ объектам оборудования
                iname = normalize_name(item['name'])
                width_s = int(item['width'] * SCALE)
                depth_s = int(item['depth'] * SCALE)

                left = model.NewBoolVar(f"{iname}_left_of_{zone_safe_name}")
                right = model.NewBoolVar(f"{iname}_right_of_{zone_safe_name}")
                below = model.NewBoolVar(f"{iname}_below_{zone_safe_name}")
                above = model.NewBoolVar(f"{iname}_above_{zone_safe_name}")

                model.Add(positions[iname]['x'] + width_s <= x_min_s - ZONE_MARGIN).OnlyEnforceIf(left)
                model.Add(positions[iname]['x'] >= x_max_s + ZONE_MARGIN).OnlyEnforceIf(right)
                model.Add(positions[iname]['y'] + depth_s <= y_min_s - ZONE_MARGIN).OnlyEnforceIf(below)
                model.Add(positions[iname]['y'] >= y_max_s + ZONE_MARGIN).OnlyEnforceIf(above)

                model.AddBoolOr([left, right, below, above])
            continue # Переходим к следующему правилу, так как эта зона обработана

        elif rule_type == 'Коридор':
            try:
                x1, y1, x2, y2, width = map(float, value_str.split(','))
            except Exception:
                print(f"    - ПРЕДУПРЕЖДЕНИЕ: Некорректное значение коридора для '{obj1_name_orig}'. Ожидается 'X1,Y1,X2,Y2,Ширина'.")
                continue

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

            for item in equipment_list:  # Применяем ко ВСЕМ объектам оборудования
                iname = normalize_name(item['name'])
                width_s = int(item['width'] * SCALE)
                depth_s = int(item['depth'] * SCALE)

                left = model.NewBoolVar(f"{iname}_left_of_corridor")
                right = model.NewBoolVar(f"{iname}_right_of_corridor")
                below = model.NewBoolVar(f"{iname}_below_corridor")
                above = model.NewBoolVar(f"{iname}_above_corridor")
                viol = model.NewBoolVar(f"{iname}_corridor_violation")

                model.Add(positions[iname]['x'] + width_s <= corridor_x_min_s - ZONE_MARGIN).OnlyEnforceIf(left)
                model.Add(positions[iname]['x'] >= corridor_x_max_s + ZONE_MARGIN).OnlyEnforceIf(right)
                model.Add(positions[iname]['y'] + depth_s <= corridor_y_min_s - ZONE_MARGIN).OnlyEnforceIf(below)
                model.Add(positions[iname]['y'] >= corridor_y_max_s + ZONE_MARGIN).OnlyEnforceIf(above)

                # Если объект пересекает коридор, переменная viol будет равна 1
                model.AddBoolOr([left, right, below, above, viol])
                corridor_penalties.append(viol)
            continue # Переходим к следующему правилу, так как этот коридор обработан

        # ОБРАБОТКА ПРАВИЛ, ТРЕБУЮЩИХ ПОИСКА КОНКРЕТНЫХ ОБЪЕКТОВ
        if obj1_key not in positions:
            print(f"    - ПРЕДУПРЕЖДЕНИЕ: Объект '{obj1_name_orig}' (нормал. {repr(obj1_key)}) из правила не найден в task.json. Пропускаем правило.")
            print(f"      Доступные нормализованные объекты: {list(positions.keys())}")
            continue

        obj1_data = equipment_by_name[obj1_key] # Получаем данные объекта по нормализованному ключу

        if rule_type == 'Технологическая последовательность':
            if obj2_key not in positions:
                print(f"    - ПРЕДУПРЕЖДЕНИЕ: Объект '{obj2_name_orig}' (нормал. {repr(obj2_key)}) из правила не найден в task.json. Пропускаем правило.")
                print(f"      Доступные нормализованные объекты: {list(positions.keys())}")
                continue

            obj2_data = equipment_by_name[obj2_key]
            direction = rule.get('Направление', 'Y').strip() # по умолчанию поток по Y

            if direction == 'Y':
                obj1_end_y = positions[obj1_key]['y'] + int(obj1_data['depth'] * SCALE)
                obj2_start_y = positions[obj2_key]['y']
                viol = model.NewIntVar(0, int(room_depth * SCALE), f"seq_viol_{obj1_key}_{obj2_key}")
                model.Add(viol >= obj1_end_y + int(2.0 * SCALE) - obj2_start_y)
                seq_penalties.append(viol)
            else: # direction == 'X'
                obj1_end_x = positions[obj1_key]['x'] + int(obj1_data['width'] * SCALE)
                obj2_start_x = positions[obj2_key]['x']
                viol = model.NewIntVar(0, int(room_width * SCALE), f"seq_viol_{obj1_key}_{obj2_key}")
                model.Add(viol >= obj1_end_x + int(2.0 * SCALE) - obj2_start_x)
                seq_penalties.append(viol)

            print(f"    - ПРАВИЛО: Технологическая последовательность '{obj1_name_orig}' -> '{obj2_name_orig}' по оси {direction}.")
            applied_rules.append(f"Техпоследовательность {obj1_name_orig}->{obj2_name_orig} {direction}")
            flow_pairs.append((obj1_key, obj2_key))

        elif rule_type == 'Производственная зона':
            try:
                x_min, y_min, x_max, y_max = map(float, value_str.split(','))
            except Exception:
                print(f"    - ПРЕДУПРЕЖДЕНИЕ: Некорректное значение зоны для '{obj1_name_orig}'. Ожидается 'Xmin,Ymin,Xmax,Ymax'.")
                continue

            x_min_s = int(x_min * SCALE)
            y_min_s = int(y_min * SCALE)
            x_max_s = int(x_max * SCALE)
            y_max_s = int(y_max * SCALE)
            
            width_s = int(obj1_data['width'] * SCALE)
            depth_s = int(obj1_data['depth'] * SCALE)

            # Нарушение рассчитывается как выход за границы зоны
            viol_left = model.NewIntVar(0, int(room_width * SCALE), f"zone_left_{obj1_key}")
            viol_bottom = model.NewIntVar(0, int(room_depth * SCALE), f"zone_bottom_{obj1_key}")
            viol_right = model.NewIntVar(0, int(room_width * SCALE), f"zone_right_{obj1_key}")
            viol_top = model.NewIntVar(0, int(room_depth * SCALE), f"zone_top_{obj1_key}")

            model.Add(viol_left >= x_min_s - positions[obj1_key]['x'])
            model.Add(viol_bottom >= y_min_s - positions[obj1_key]['y'])
            model.Add(viol_right >= positions[obj1_key]['x'] + width_s - x_max_s)
            model.Add(viol_top >= positions[obj1_key]['y'] + depth_s - y_max_s)
            zone_penalty = model.NewIntVar(0, int(max(room_width, room_depth) * SCALE * 4), f"zone_penalty_{obj1_key}")
            model.Add(zone_penalty == viol_left + viol_bottom + viol_right + viol_top)
            zone_penalties.append(zone_penalty)

            print(f"    - ПРАВИЛО: Объект '{obj1_name_orig}' ограничен зоной [{x_min}, {y_min}] - [{x_max}, {y_max}].")
            applied_rules.append(f"Производственная зона для {obj1_name_orig} [{x_min},{y_min},{x_max},{y_max}]")

        elif rule_type == 'Параллельная линия':
            if obj2_key not in positions:
                print(f"    - ПРЕДУПРЕЖДЕНИЕ: Объект '{obj2_name_orig}' (нормал. {repr(obj2_key)}) из правила не найден в task.json. Пропускаем правило.")
                print(f"      Доступные нормализованные объекты: {list(positions.keys())}")
                continue

            offset = float(value_str) if value_str else 0.0
            obj2_data = equipment_by_name[obj2_key]

            center1_x = positions[obj1_key]['x'] + int(obj1_data['width'] * SCALE / 2)
            center2_x = positions[obj2_key]['x'] + int(obj2_data['width'] * SCALE / 2)
            
            model.Add(center2_x == center1_x + int(offset * SCALE))

            print(f"    - ПРАВИЛО: Параллельная линия '{obj1_name_orig}' и '{obj2_name_orig}' со смещением {offset}м.")
            applied_rules.append(f"Параллельная линия {obj1_name_orig}-{obj2_name_orig} offset {offset}")

        elif rule_type == 'Привязка к стене':
            try:
                side, dist = value_str.split(',')
                dist = float(dist)
            except Exception:
                print(f"    - ПРЕДУПРЕЖДЕНИЕ: Некорректное значение привязки к стене для '{obj1_name_orig}'.")
                continue
            
            pos = positions[obj1_key]
            
            if side == 'Xmin':
                model.Add(pos['x'] == int((dist + wall_thickness) * SCALE))
            elif side == 'Xmax':
                model.Add(pos['x'] + int(obj1_data['width'] * SCALE) == int((room_width - wall_thickness - dist) * SCALE))
            elif side == 'Ymin':
                model.Add(pos['y'] == int((dist + wall_thickness) * SCALE))
            elif side == 'Ymax':
                model.Add(pos['y'] + int(obj1_data['depth'] * SCALE) == int((room_depth - wall_thickness - dist) * SCALE))
            
            print(f"    - ПРАВИЛО: Привязка '{obj1_name_orig}' к стене {side} с отступом {dist}м.")
            applied_rules.append(f"Привязка {obj1_name_orig} {side} {dist}")

        elif rule_type == 'Зона обслуживания':
            try:
                margin = float(value_str)
            except Exception:
                print(f"    - ПРЕДУПРЕЖДЕНИЕ: Некорректное значение зоны обслуживания для '{obj1_name_orig}'.")
                continue
            
            for other_item in equipment_list: # Применяем ко ВСЕМ ДРУГИМ объектам оборудования
                other_key = normalize_name(other_item['name'])
                if other_key == obj1_key:
                    continue # Пропускаем сам объект

                other_data = equipment_by_name[other_key]
                center1_x = positions[obj1_key]['x'] + int(obj1_data['width'] * SCALE / 2)
                center1_y = positions[obj1_key]['y'] + int(obj1_data['depth'] * SCALE / 2)
                center2_x = positions[other_key]['x'] + int(other_data['width'] * SCALE / 2)
                center2_y = positions[other_key]['y'] + int(other_data['depth'] * SCALE / 2)
                
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
            applied_rules.append(f"Зона обслуживания {obj1_name_orig} {margin}")

        elif rule_type == 'Компактная группировка':
            group_raw = [s.strip() for s in value_str.split(';') if s.strip()]
            group_keys = [normalize_name(s) for s in group_raw]
            if obj1_name_orig.strip():  # Если obj1_name также указан для группы
                group_keys.append(obj1_key)

            missing = [g for g in group_keys if g not in positions]
            if missing:
                print(f"    - ПРЕДУПРЕЖДЕНИЕ: Объекты {missing} не найдены для группировки.")
                print(f"      Доступные нормализованные объекты: {list(positions.keys())}")
                continue
            group_rules.append(group_keys)
            print(f"    - ПРАВИЛО: Компактная группировка {group_raw}.")
            applied_rules.append(f"Группировка {';'.join(group_raw)}")

        elif rule_type == 'Ориентация':
            try:
                angle = float(value_str)
            except Exception:
                print(f"    - ПРЕДУПРЕЖДЕНИЕ: Некорректное значение ориентации для '{obj1_name_orig}'.")
                continue
            equipment_by_name[obj1_key]['rotation_deg'] = angle
            print(f"    - ПРАВИЛО: Ориентация '{obj1_name_orig}' = {angle}°")
            applied_rules.append(f"Ориентация {obj1_name_orig} {angle}")

        elif rule_type == 'Мин. расстояние до':
            if obj2_key not in positions:
                print(f"    - ПРЕДУПРЕЖДЕНИЕ: Объект '{obj2_name_orig}' (нормал. {repr(obj2_key)}) из правила не найден в task.json. Пропускаем правило.")
                print(f"      Доступные нормализованные объекты: {list(positions.keys())}")
                continue

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
            print(f"    - ПРАВИЛО: Расстояние между '{obj1_name_orig}' и '{obj2_name_orig}' >= {value}м.")
            applied_rules.append(f"Мин. расстояние {obj1_name_orig}-{obj2_name_orig} {value}")

        elif rule_type in ['Выровнять по оси X', 'Выровнять по оси Y']:
            if obj2_key not in positions:
                print(f"    - ПРЕДУПРЕЖДЕНИЕ: Объект '{obj2_name_orig}' (нормал. {repr(obj2_key)}) из правила не найден в task.json. Пропускаем правило.")
                print(f"      Доступные нормализованные объекты: {list(positions.keys())}")
                continue

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
            print(f"    - ПРАВИЛО: Выровнять '{obj1_name_orig}' и '{obj2_name_orig}' по оси {axis}.")
            applied_rules.append(f"Выровнять {obj1_name_orig}-{obj2_name_orig} axis {axis}")

        else:
            print(f"    - [НЕИЗВЕСТНО] Тип правила '{rule_type}' не поддерживается решателем.")


    # ЦЕЛЕВАЯ ФУНКЦИЯ ДЛЯ ОПТИМИЗАЦИИ КОМПАКТНОСТИ, ПОТОКА И ГРУППИРОВКИ
    print("  > Добавление целевой функции для компактности, потока и группировки...")
    
    total_x_spread = model.NewIntVar(0, int(room_width * SCALE), "total_x_spread")
    total_y_spread = model.NewIntVar(0, int(room_depth * SCALE), "total_y_spread")
    
    if equipment_list:
        min_x_all = model.NewIntVar(min_x_room_inner, max_x_room_inner, "min_x_all")
        max_x_all = model.NewIntVar(min_x_room_inner, max_x_room_inner, "max_x_all")
        min_y_all = model.NewIntVar(min_y_room_inner, max_y_room_inner, "min_y_all")
        max_y_all = model.NewIntVar(min_y_room_inner, max_y_room_inner, "min_y_all")

        for item in equipment_list:
            key = normalize_name(item['name'])
            model.Add(min_x_all <= positions[key]['x'])
            model.Add(max_x_all >= positions[key]['x'] + int(item['width'] * SCALE))
            model.Add(min_y_all <= positions[key]['y'])
            model.Add(max_y_all >= positions[key]['y'] + int(item['depth'] * SCALE))

        model.Add(total_x_spread == max_x_all - min_x_all)
        model.Add(total_y_spread == max_y_all - min_y_all)
    else:
        model.Add(total_x_spread == 0)
        model.Add(total_y_spread == 0)

    flow_cost = sum(model.NewIntVar(0, int(room_width * SCALE + room_depth * SCALE), f"flow_cost_{a}_{b}") for a, b in flow_pairs)
    for a, b in flow_pairs:
        a_data = equipment_by_name[a]
        b_data = equipment_by_name[b]
        a_cx = positions[a]['x'] + int(a_data['width'] * SCALE / 2)
        a_cy = positions[a]['y'] + int(a_data['depth'] * SCALE / 2)
        b_cx = positions[b]['x'] + int(b_data['width'] * SCALE / 2)
        b_cy = positions[b]['y'] + int(b_data['depth'] * SCALE / 2)
        dx_abs = model.NewIntVar(0, int(room_width * SCALE), f"flow_dx_abs_{a}_{b}")
        dy_abs = model.NewIntVar(0, int(room_depth * SCALE), f"flow_dy_abs_{a}_{b}")
        model.AddAbsEquality(dx_abs, a_cx - b_cx)
        model.AddAbsEquality(dy_abs, a_cy - b_cy)
        model.Add(flow_cost >= dx_abs + dy_abs) # Минимизируем сумму абсолютных отклонений

    group_cost = sum(model.NewIntVar(0, int(room_width * SCALE + room_depth * SCALE), f"group_cost_{g_idx}_{i}_{j}") 
                     for g_idx, g in enumerate(group_rules) for i in range(len(g)) for j in range(i + 1, len(g)))
    for g_idx, g in enumerate(group_rules):
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
                dx_abs = model.NewIntVar(0, int(room_width * SCALE), f"grp_dx_abs_{a}_{b}")
                dy_abs = model.NewIntVar(0, int(room_depth * SCALE), f"grp_dy_abs_{a}_{b}")
                model.AddAbsEquality(dx_abs, a_cx - b_cx)
                model.AddAbsEquality(dy_abs, a_cy - b_cy)
                model.Add(group_cost >= dx_abs + dy_abs) # Минимизируем сумму абсолютных отклонений

    soft_penalty = sum(seq_penalties) + sum(zone_penalties) + sum(corridor_penalties) * int(max(room_width, room_depth) * SCALE)
    model.Minimize(total_x_spread + total_y_spread + flow_cost + group_cost + SOFT_PENALTY_WEIGHT * soft_penalty) # Общая целевая функция

    print("3. Запуск решателя OR-Tools...")
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 300.0  # Даем решателю до 5 минут на поиск решения
    solver.parameters.num_workers = os.cpu_count() or 1 # Используем все ядра CPU
    solver.parameters.log_search_progress = True # Включим логирование прогресса для отладки
    
    status = solver.Solve(model)
    print(f"  > Статус решателя: {solver.StatusName(status)}")

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("  > Решение найдено!")
        final_placements = []
        for item in equipment_list:
            key = normalize_name(item['name'])
            # Проверяем, было ли размещено данное оборудование (если solver.Value() не выдает ошибки)
            if key in positions and hasattr(solver, 'Value'): # Проверяем наличие 'Value' на solver
                try:
                    updated_rot = equipment_by_name[key].get('rotation_deg', item.get('rotation_deg', 0.0))
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
                except Exception as e:
                    print(f"    - ПРЕДУПРЕЖДЕНИЕ: Не удалось получить значение для объекта '{item['name']}' из решателя: {e}")
                    # В случае ошибки, возможно, объект не был размещен. Пропустим его или используем дефолтные значения.
                    pass
            else:
                print(f"    - ПРЕДУПРЕЖДЕНИЕ: Объект '{item['name']}' не был включен в решение решателя (не найдена позиция).")
                # Если объект не был размещен, его не будет в final_placements
                pass

        placed_names = [p['name'] for p in final_placements]
        print(f"  > Размещено объектов: {len(placed_names)} из {len(equipment_list)}")
        print("    - " + ", ".join(placed_names))
        
        # Только если есть размещенные объекты, создаем IFC файл
        if final_placements:
            create_ifc_file(task_data, final_placements)
        else:
            print("  > ВНИМАНИЕ: Нет размещенных объектов для создания IFC файла.")
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
