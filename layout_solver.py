import pandas as pd
import ifcopenshell
import ifcopenshell.api
from ortools.sat.python import cp_model
import sys

def get_rules_from_google_sheet(sheet_url):
    """Читает правила из опубликованной Google Таблицы."""
    print("1. Читаем правила из Google Таблицы...")
    try:
        csv_export_url = sheet_url.replace('/edit?usp=sharing', '/export?format=csv')
        df = pd.read_csv(csv_export_url)
        print(f"  > Успешно загружено {len(df)} правил.")
        return df
    except Exception as e:
        print(f"  > ОШИБКА: Не удалось загрузить правила. Проверь ссылку. {e}")
        return None

def create_ifc_file(placements, filename="prototype.ifc"):
    """Создает IFC файл с размещенным оборудованием."""
    print(f"3. Создаем IFC файл '{filename}'...")
    f = ifcopenshell.file(schema="IFC4")
    project = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcProject", name="Проект Цеха")
    context = ifcopenshell.api.run("context.add_context", f, context_type="Model")
    body = ifcopenshell.api.run("context.add_context", f, context_type="Model",
                                 context_identifier="Body", target_view="MODEL_VIEW", parent=context)
    ifcopenshell.api.run("unit.assign_unit", f, length={"is_metric": True, "raw": "METRE"})
    site = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcSite", name="Участок")
    ifcopenshell.api.run("aggregate.assign_object", f, relating_object=project, products=[site])
    building = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcBuilding", name="Здание")
    ifcopenshell.api.run("aggregate.assign_object", f, relating_object=site, products=[building])
    storey = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcBuildingStorey", name="Первый этаж")
    ifcopenshell.api.run("aggregate.assign_object", f, relating_object=building, products=[storey])
    
    for item in placements:
        name, x, y, width, depth = item['name'], item['x'], item['y'], item['width'], item['depth']
        height = 1.5
        
        # Создаем элемент и его геометрию (исправлено)
        element = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcBuildingElementProxy", name=name)
        ifcopenshell.api.run("geometry.edit_object_placement", f, product=element, matrix=[[1,0,0,x],[0,1,0,y],[0,0,1,0],[0,0,0,1]])
        representation = ifcopenshell.api.run("geometry.add_representation", f, product=element, context=body, 
                                             representation_identifier='Body', representation_type='SweptSolid')
        
        # Создаем саму коробку (box)
        extrusion_placement = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)))
        rectangle_profile = f.createIfcRectangleProfileDef('AREA', None, width, depth)
        extrusion = f.createIfcExtrudedAreaSolid(rectangle_profile, extrusion_placement, f.createIfcDirection((0.0, 0.0, 1.0)), height)
        
        # Привязываем геометрию к представлению
        ifcopenshell.api.run("geometry.assign_representation", f, representation=representation, items=[extrusion])
        ifcopenshell.api.run("aggregate.assign_object", f, relating_object=storey, products=[element])

    f.write(filename)
    print(f"  > Файл '{filename}' успешно создан!")

def solve_layout(sheet_url):
    """Основная функция: читает правила, решает задачу, создает IFC."""
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
        print("Пример: python layout_solver.py 'https://docs.google.com/...'")
    else:
        google_sheet_url = sys.argv[1]
        solve_layout(google_sheet_url)
