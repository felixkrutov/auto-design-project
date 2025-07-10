import pandas as pd
import ifcopenshell
import ifcopenshell.guid
from ortools.sat.python import cp_model
import sys
import json

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ СОЗДАНИЯ КОНСТРУКЦИЙ ---

def create_ifc_entity(f, entity_class, name, placement, shape, owner_history, storey, predefined_type=None):
    """Универсальная функция для создания IFC сущностей (Стена, Плита)."""
    args = {
        "GlobalId": ifcopenshell.guid.new(),
        "OwnerHistory": owner_history,
        "Name": name,
        "ObjectPlacement": placement,
        "Representation": shape,
    }
    if predefined_type:
        args["PredefinedType"] = predefined_type
        
    entity = f.create_entity(entity_class, **args)
    f.createIfcRelContainedInSpatialStructure(ifcopenshell.guid.new(), owner_history, "Content", None, [entity], storey)
    return entity

def create_box_shape(f, context, x, y, z, length, width, height):
    """Создает геометрию в виде параллелепипеда (box) и ее размещение."""
    placement = f.createIfcLocalPlacement(
        None,
        f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((x, y, z)))
    )
    profile = f.createIfcRectangleProfileDef('AREA', None, None, length, width)
    solid = f.createIfcExtrudedAreaSolid(profile, None, f.createIfcDirection((0.0, 0.0, 1.0)), height)
    shape = f.createIfcProductDefinitionShape(None, None, [f.createIfcShapeRepresentation(context, 'Body', 'SweptSolid', [solid])])
    return placement, shape

# --- ОСНОВНЫЕ ФУНКЦИИ ---

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
    
    # Стандартный заголовок и иерархия проекта
    person = f.createIfcPerson(FamilyName="AI System")
    organization = f.createIfcOrganization(Name="AutoDesign Inc.")
    person_org = f.createIfcPersonAndOrganization(person, organization)
    application_org = f.createIfcOrganization(Name="AI Assistant")
    application = f.createIfcApplication(application_org, "1.0", "AutoDesign Solver", "ADS")
    owner_history = f.createIfcOwnerHistory(person_org, application, None, None, None, None, None)
    
    project = f.createIfcProject(ifcopenshell.guid.new(), owner_history, task_data['project_name'])
    context = f.createIfcGeometricRepresentationContext(None, "Model", 3, 1.0E-5, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0))))
    project.RepresentationContexts = [context]
    
    site = f.createIfcSite(ifcopenshell.guid.new(), owner_history, "Участок", ObjectPlacement=f.createIfcLocalPlacement(None, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)))))
    building = f.createIfcBuilding(ifcopenshell.guid.new(), owner_history, task_data['building_name'], ObjectPlacement=f.createIfcLocalPlacement(site.ObjectPlacement, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)))))
    storey = f.createIfcBuildingStorey(ifcopenshell.guid.new(), owner_history, task_data['storey_name'], ObjectPlacement=f.createIfcLocalPlacement(building.ObjectPlacement, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)))))

    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, "ProjectContainer", None, project, [site])
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, "SiteContainer", None, site, [building])
    f.createIfcRelAggregates(ifcopenshell.guid.new(), owner_history, "BuildingContainer", None, building, [storey])

    # --- ДОБАВЛЕНИЕ ПОЛА И СТЕН ---
    print("  > Создание строительных конструкций (пол и стены)...")
    room_dims = task_data['room_dimensions']
    w, d, h = room_dims['width'], room_dims['depth'], room_dims['height']
    wall_thickness = 0.2  # Толщина стен 200мм
    slab_thickness = 0.2  # Толщина пола 200мм

    # Создаем пол
    slab_placement, slab_shape = create_box_shape(f, context, 0, 0, -slab_thickness, w, d, slab_thickness)
    create_ifc_entity(f, "IfcSlab", "Пол", slab_placement, slab_shape, owner_history, storey, "FLOOR")

    # Создаем 4 стены по периметру
    # Стена 1 (низ)
    wall1_p, wall1_s = create_box_shape(f, context, 0, 0, 0, w, wall_thickness, h)
    create_ifc_entity(f, "IfcWall", "Стена", wall1_p, wall1_s, owner_history, storey)
    # Стена 2 (право)
    wall2_p, wall2_s = create_box_shape(f, context, w - wall_thickness, 0, 0, wall_thickness, d, h)
    create_ifc_entity(f, "IfcWall", "Стена", wall2_p, wall2_s, owner_history, storey)
    # Стена 3 (верх)
    wall3_p, wall3_s = create_box_shape(f, context, 0, d - wall_thickness, 0, w, wall_thickness, h)
    create_ifc_entity(f, "IfcWall", "Стена", wall3_p, wall3_s, owner_history, storey)
    # Стена 4 (лево)
    wall4_p, wall4_s = create_box_shape(f, context, 0, 0, 0, wall_thickness, d, h)
    create_ifc_entity(f, "IfcWall", "Стена", wall4_p, wall4_s, owner_history, storey)
    
    # --- РАЗМЕЩЕНИЕ ОБОРУДОВАНИЯ ---
    print("  > Размещение оборудования...")
    for item in placements:
        # Размещаем оборудование относительно этажа
        element_placement = f.createIfcLocalPlacement(storey.ObjectPlacement, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((float(item['x']), float(item['y']), 0.0))))
        
        # Создаем геометрию оборудования
        profile = f.createIfcRectangleProfileDef('AREA', None, None, item['width'], item['depth'])
        solid = f.createIfcExtrudedAreaSolid(profile, None, f.createIfcDirection((0.0, 0.0, 1.0)), item['height'])
        shape = f.createIfcProductDefinitionShape(None, None, [f.createIfcShapeRepresentation(context, 'Body', 'SweptSolid', [solid])])
        
        # Создаем сам элемент оборудования
        element = f.createIfcBuildingElementProxy(ifcopenshell.guid.new(), owner_history, item['name'], ObjectPlacement=element_placement, Representation=shape)
        
        # Добавляем атрибуты
        if 'attributes' in item and item['attributes']:
            prop_values = [f.createIfcPropertySingleValue(k, None, f.createIfcLabel(v), None) for k, v in item['attributes'].items()]
            prop_set = f.createIfcPropertySet(ifcopenshell.guid.new(), owner_history, "Параметры", None, prop_values)
            f.createIfcRelDefinesByProperties(ifcopenshell.guid.new(), owner_history, None, None, [element], prop_set)
        
        # Связываем оборудование с этажом
        f.createIfcRelContainedInSpatialStructure(ifcopenshell.guid.new(), owner_history, "Content", None, [element], storey)
    
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
    room_width = task_data['room_dimensions']['width']
    room_depth = task_data['room_dimensions']['depth']
    model = cp_model.CpModel()
    SCALE = 1000  # Работаем в "миллиметрах" для точности

    # Создаем переменные для координат
    positions = {item['name']: {'x': model.NewIntVar(0, int((room_width - item['width']) * SCALE), f"x_{item['name']}"), 
                                'y': model.NewIntVar(0, int((room_depth - item['depth']) * SCALE), f"y_{item['name']}")} 
                 for item in equipment_list}

    # Ограничение непересечения
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
