from ortools.sat.python import cp_model
import time

def calculate_placements(project_data: dict) -> dict:
    print("3. Расчет положений оборудования с помощью OR-Tools...")
    
    equipment_list = project_data.get('equipment', [])
    rules = project_data.get('rules', [])
    room_dims = project_data['architecture']['room_dimensions']
    wall_thickness = project_data['architecture']['wall_thickness']
    solver_options = project_data.get('solver_options', {})

    model = cp_model.CpModel()
    SCALE = 100

    min_x_room = int(wall_thickness * SCALE)
    max_x_room = int((room_dims['width'] - wall_thickness) * SCALE)
    min_y_room = int(wall_thickness * SCALE)
    max_y_room = int((room_dims['depth'] - wall_thickness) * SCALE)

    positions = {}
    equipment_map = {item['id']: item for item in equipment_list}

    virtual_boxes = []
    for item in equipment_list:
        m_zone = item.get('maintenance_zone', {})
        w = int((m_zone.get('left', 0) + item['footprint']['width'] + m_zone.get('right', 0)) * SCALE)
        d = int((m_zone.get('back', 0) + item['footprint']['depth'] + m_zone.get('front', 0)) * SCALE)
        x_offset = int(m_zone.get('left', 0) * SCALE)
        y_offset = int(m_zone.get('back', 0) * SCALE)
        vx = model.NewIntVar(min_x_room, max_x_room - w, f"vx_{item['id']}")
        vy = model.NewIntVar(min_y_room, max_y_room - d, f"vy_{item['id']}")
        px = model.NewIntVar(min_x_room, max_x_room, f"x_{item['id']}")
        py = model.NewIntVar(min_y_room, max_y_room, f"y_{item['id']}")
        model.Add(px == vx + x_offset)
        model.Add(py == vy + y_offset)
        positions[item['id']] = {'x': px, 'y': py}
        virtual_boxes.append({'id': item['id'], 'vx': vx, 'vy': vy, 'vw': w, 'vd': d})

    intervals_x = [model.NewIntervalVar(box['vx'], box['vw'], box['vx'] + box['vw'], f"ivx_{box['id']}") for box in virtual_boxes]
    intervals_y = [model.NewIntervalVar(box['vy'], box['vd'], box['vy'] + box['vd'], f"ivy_{box['id']}") for box in virtual_boxes]
    model.AddNoOverlap2D(intervals_x, intervals_y)
    print("  - Добавлено глобальное правило: NoOverlap2D (с учетом зон обслуживания).")

    flow_costs = []
    
    print("  - Применение правил из project.json...")
    for i, rule in enumerate(rules):
        rtype = rule.get('type')
        params = rule.get('params', {})
        
        if rtype == 'AVOID_ZONE':
            x1, y1, x2, y2 = params['area']
            print(f"    - Правило AVOID_ZONE для зоны [{x1},{y1},{x2},{y2}]")
            for box in virtual_boxes:
                is_left = model.NewBoolVar(f"az_left_{i}_{box['id']}")
                is_right = model.NewBoolVar(f"az_right_{i}_{box['id']}")
                is_below = model.NewBoolVar(f"az_below_{i}_{box['id']}")
                is_above = model.NewBoolVar(f"az_above_{i}_{box['id']}")
                model.Add(box['vx'] + box['vw'] <= int(x1 * SCALE)).OnlyEnforceIf(is_left)
                model.Add(box['vx'] >= int(x2 * SCALE)).OnlyEnforceIf(is_right)
                model.Add(box['vy'] + box['vd'] <= int(y1 * SCALE)).OnlyEnforceIf(is_below)
                model.Add(box['vy'] >= int(y2 * SCALE)).OnlyEnforceIf(is_above)
                model.AddBoolOr([is_left, is_right, is_below, is_above])

        elif rtype == 'PLACE_IN_ZONE':
            target_id = rule.get('target')
            x1, y1, x2, y2 = params['area']
            print(f"    - Правило PLACE_IN_ZONE для '{target_id}'")
            box = next(b for b in virtual_boxes if b['id'] == target_id)
            model.Add(box['vx'] >= int(x1 * SCALE))
            model.Add(box['vy'] >= int(y1 * SCALE))
            model.Add(box['vx'] + box['vw'] <= int(x2 * SCALE))
            model.Add(box['vy'] + box['vd'] <= int(y2 * SCALE))

        elif rtype == 'ATTACH_TO_WALL':
            target_id = rule.get('target')
            side = params.get('side')
            dist = int(params.get('distance', 0) * SCALE)
            print(f"    - Правило ATTACH_TO_WALL для '{target_id}' к стене {side}")
            box = next(b for b in virtual_boxes if b['id'] == target_id)
            if side == 'Xmin': model.Add(box['vx'] == min_x_room + dist)
            elif side == 'Xmax': model.Add(box['vx'] + box['vw'] == max_x_room - dist)
            elif side == 'Ymin': model.Add(box['vy'] == min_y_room + dist)
            elif side == 'Ymax': model.Add(box['vy'] + box['vd'] == max_y_room - dist)
            
        elif rtype == 'ALIGN':
            t1, t2 = rule.get('target1'), rule.get('target2')
            axis = params.get('axis')
            print(f"    - Правило ALIGN для '{t1}' и '{t2}' по оси {axis}")
            w1 = int(equipment_map[t1]['footprint']['width'] * SCALE); d1 = int(equipment_map[t1]['footprint']['depth'] * SCALE)
            w2 = int(equipment_map[t2]['footprint']['width'] * SCALE); d2 = int(equipment_map[t2]['footprint']['depth'] * SCALE)
            center1_x = positions[t1]['x'] + w1 // 2; center1_y = positions[t1]['y'] + d1 // 2
            center2_x = positions[t2]['x'] + w2 // 2; center2_y = positions[t2]['y'] + d2 // 2
            if axis == 'X': model.Add(center1_x == center2_x)
            else: model.Add(center1_y == center2_y)

        elif rtype == 'PLACE_AFTER':
            target_id, anchor_id = rule.get('target'), params.get('anchor')
            print(f"    - МЯГКОЕ Правило PLACE_AFTER: '{target_id}' после '{anchor_id}'")
            
            d_anchor = int(equipment_map[anchor_id]['footprint']['depth'] * SCALE)
            penalty_var = model.NewIntVar(0, max_y_room, f"penalty_{target_id}")
            model.Add(penalty_var >= (positions[anchor_id]['y'] + d_anchor) - positions[target_id]['y'])
            flow_costs.append(penalty_var * 10) 

    # --- Целевая функция ---
    flow_penalty = model.NewIntVar(0, 1000 * max_y_room * 10, 'flow_penalty')
    model.Add(flow_penalty == sum(flow_costs))

    distances = []
    for i in range(len(virtual_boxes)):
        for j in range(i + 1, len(virtual_boxes)):
            box1 = virtual_boxes[i]
            box2 = virtual_boxes[j]
            
            dist_x = model.NewIntVar(0, max_x_room, f"dist_x_{i}_{j}")
            dist_y = model.NewIntVar(0, max_y_room, f"dist_y_{i}_{j}")
            model.AddAbsEquality(dist_x, box1['vx'] - box2['vx'])
            model.AddAbsEquality(dist_y, box1['vy'] - box2['vy'])
            distances.append(dist_x)
            distances.append(dist_y)
    
    total_spread = model.NewIntVar(0, 1000 * (max_x_room + max_y_room), 'total_spread')
    model.Add(total_spread == sum(distances))

    FLOW_WEIGHT = 1000 
    model.Minimize(flow_penalty * FLOW_WEIGHT - total_spread)

    print("  - Добавлена сложная целевая функция: (Штраф за поток * ВЕС) - (Общий разброс).")

    # --- Запуск решателя ---
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
                'rotation_deg': 0 
            }
        return final_placements
    else:
        print(f"  > ОШИБКА: Решение не найдено. Статус: {solver.StatusName(status)}")
        return None
