from ortools.sat.python import cp_model
import time

def calculate_placements(project_data: dict) -> dict:
    """
    Вычисляет положения оборудования с помощью решателя CP-SAT.
    """
    print("3. Расчет положений оборудования с помощью OR-Tools...")
    
    equipment_list = project_data.get('equipment', [])
    rules = project_data.get('rules', [])
    room_dims = project_data.get('architecture', {}).get('room_dimensions', {})
    wall_thickness = project_data.get('architecture', {}).get('wall_thickness', 0.2)
    solver_options = project_data.get('solver_options', {})

    if not all([equipment_list, room_dims]):
        print("  > ОШИБКА: Отсутствуют данные об оборудовании или размерах помещения.")
        return None

    model = cp_model.CpModel()
    SCALE = 100 # Увеличим масштаб для большей точности

    # Внутренние границы помещения
    min_x = int(wall_thickness * SCALE)
    max_x = int((room_dims['width'] - wall_thickness) * SCALE)
    min_y = int(wall_thickness * SCALE)
    max_y = int((room_dims['depth'] - wall_thickness) * SCALE)

    positions = {}
    equipment_map = {item['id']: item for item in equipment_list}

    # Создаем переменные для каждого объекта
    for item in equipment_list:
        w = int(item['footprint']['width'] * SCALE)
        d = int(item['footprint']['depth'] * SCALE)
        positions[item['id']] = {
            'x': model.NewIntVar(min_x, max_x - w, f"x_{item['id']}"),
            'y': model.NewIntVar(min_y, max_y - d, f"y_{item['id']}")
        }

    # Правило "Не пересекаться"
    if solver_options.get('no_overlap', True):
        intervals_x = []
        intervals_y = []
        for item in equipment_list:
            item_id = item['id']
            w = int(item['footprint']['width'] * SCALE)
            d = int(item['footprint']['depth'] * SCALE)
            intervals_x.append(model.NewIntervalVar(
                positions[item_id]['x'], w, positions[item_id]['x'] + w, f"ix_{item_id}"
            ))
            intervals_y.append(model.NewIntervalVar(
                positions[item_id]['y'], d, positions[item_id]['y'] + d, f"iy_{item_id}"
            ))
        model.AddNoOverlap2D(intervals_x, intervals_y)
        print("  - Добавлено правило: NoOverlap2D.")

    # Применение правил
    for rule in rules:
        rtype = rule.get('type')
        params = rule.get('params', {})
        
        # ... (Здесь будет длинный блок if/elif для каждого типа правила) ...

    # Целевая функция: минимизировать общую занимаемую площадь (для компактности)
    if equipment_list:
        all_x_ends = [positions[item['id']]['x'] + int(item['footprint']['width'] * SCALE) for item in equipment_list]
        all_y_ends = [positions[item['id']]['y'] + int(item['footprint']['depth'] * SCALE) for item in equipment_list]
        
        min_x_var = model.NewIntVar(min_x, max_x, 'min_x_all')
        max_x_var = model.NewIntVar(min_x, max_x, 'max_x_all')
        min_y_var = model.NewIntVar(min_y, max_y, 'min_y_all')
        max_y_var = model.NewIntVar(min_y, max_y, 'max_y_all')

        model.AddMinEquality(min_x_var, [positions[item['id']]['x'] for item in equipment_list])
        model.AddMaxEquality(max_x_var, all_x_ends)
        model.AddMinEquality(min_y_var, [positions[item['id']]['y'] for item in equipment_list])
        model.AddMaxEquality(max_y_var, all_y_ends)

        span_x = model.NewIntVar(0, max_x, 'span_x')
        span_y = model.NewIntVar(0, max_y, 'span_y')
        model.Add(span_x == max_x_var - min_x_var)
        model.Add(span_y == max_y_var - min_y_var)
        
        model.Minimize(span_x + span_y)
        print("  - Добавлена целевая функция: Минимизация общей площади.")

    # Запуск решателя
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(solver_options.get('time_limit_sec', 30.0))
    status = solver.Solve(model)

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("  > Решение найдено!")
        final_placements = {}
        for item in equipment_list:
            item_id = item['id']
            final_placements[item_id] = {
                'x': solver.Value(positions[item_id]['x']) / SCALE,
                'y': solver.Value(positions[item_id]['y']) / SCALE,
                'rotation_deg': 0 # TODO: Добавить обработку поворотов
            }
        return final_placements
    else:
        print(f"  > ОШИБКА: Решение не найдено. Статус: {solver.StatusName(status)}")
        return None
