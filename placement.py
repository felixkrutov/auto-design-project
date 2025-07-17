from ortools.sat.python import cp_model

def get_box_by_id(boxes, target_id):
    """Вспомогательная функция для поиска 'виртуального ящика' по ID."""
    try:
        return next(b for b in boxes if b['id'] == target_id)
    except StopIteration:
        raise ValueError(f"Ошибка в правилах: не найден объект с ID '{target_id}'")

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
        
        positions[item['id']] = {'x': px, 'y': py, 'w': w, 'd': d}
        virtual_boxes.append({'id': item['id'], 'vx': vx, 'vy': vy, 'vw': w, 'vd': d, 'px': px, 'py': py})

    intervals_x = [model.NewIntervalVar(box['vx'], box['vw'], box['vx'] + box['vw'], f"ivx_{box['id']}") for box in virtual_boxes]
    intervals_y = [model.NewIntervalVar(box['vy'], box['vd'], box['vy'] + box['vd'], f"ivy_{box['id']}") for box in virtual_boxes]
    model.AddNoOverlap2D(intervals_x, intervals_y)
    print("  - Добавлено глобальное правило: NoOverlap2D (с учетом зон обслуживания).")
    
    print("  - Применение правил из project.json...")
    connected_pairs = set()

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
            box = get_box_by_id(virtual_boxes, rule.get('target'))
            x1, y1, x2, y2 = params['area']
            print(f"    - Правило PLACE_IN_ZONE для '{box['id']}'")
            model.Add(box['vx'] >= int(x1 * SCALE))
            model.Add(box['vy'] >= int(y1 * SCALE))
            model.Add(box['vx'] + box['vw'] <= int(x2 * SCALE))
            model.Add(box['vy'] + box['vd'] <= int(y2 * SCALE))

        elif rtype == 'ATTACH_TO_WALL':
            box = get_box_by_id(virtual_boxes, rule.get('target'))
            side = params.get('side')
            dist = int(params.get('distance', 0) * SCALE)
            print(f"    - Правило ATTACH_TO_WALL для '{box['id']}' к стене {side}")
            if side == 'Xmin': model.Add(box['vx'] == min_x_room + dist)
            elif side == 'Xmax': model.Add(box['vx'] + box['vw'] == max_x_room - dist)
            elif side == 'Ymin': model.Add(box['vy'] == min_y_room + dist)
            elif side == 'Ymax': model.Add(box['vy'] + box['vd'] == max_y_room - dist)
            
        elif rtype == 'ALIGN':
            t1_id, t2_id = rule.get('target1'), rule.get('target2')
            box1 = get_box_by_id(virtual_boxes, t1_id)
            box2 = get_box_by_id(virtual_boxes, t2_id)
            axis = params.get('axis')
            print(f"    - Правило ALIGN для '{t1_id}' и '{t2_id}' по оси {axis}")
            
            w1 = int(equipment_map[t1_id]['footprint']['width'] * SCALE)
            d1 = int(equipment_map[t1_id]['footprint']['depth'] * SCALE)
            w2 = int(equipment_map[t2_id]['footprint']['width'] * SCALE)
            d2 = int(equipment_map[t2_id]['footprint']['depth'] * SCALE)
            
            center1_x = box1['px'] + w1 // 2
            center1_y = box1['py'] + d1 // 2
            center2_x = box2['px'] + w2 // 2
            center2_y = box2['py'] + d2 // 2
            
            if axis == 'X': model.Add(center1_x == center2_x)
            else: model.Add(center1_y == center2_y)

        elif rtype == 'PLACE_AFTER':
            target_id = rule.get('target')
            anchor_id = params.get('anchor')
            target_box = get_box_by_id(virtual_boxes, target_id)
            anchor_box = get_box_by_id(virtual_boxes, anchor_id)
            direction = params.get('direction', 'Y')
            distance = int(params.get('distance', 0) * SCALE)
            alignment = params.get('alignment', 'none')
            
            # Сохраняем пару связанных объектов для целевой функции
            # Используем tuple(sorted(...)) для создания канонического представления пары
            connected_pairs.add(tuple(sorted((anchor_id, target_id))))

            print(f"    - Жесткое правило PLACE_AFTER: '{target_box['id']}' после '{anchor_box['id']}'")

            anchor_w = int(equipment_map[anchor_box['id']]['footprint']['width'] * SCALE)
            anchor_d = int(equipment_map[anchor_box['id']]['footprint']['depth'] * SCALE)
            target_w = int(equipment_map[target_box['id']]['footprint']['width'] * SCALE)
            target_d = int(equipment_map[target_box['id']]['footprint']['depth'] * SCALE)

            if direction == 'Y':
                model.Add(target_box['py'] == anchor_box['py'] + anchor_d + distance)
            elif direction == 'X':
                model.Add(target_box['px'] == anchor_box['px'] + anchor_w + distance)
            
            if alignment == 'center':
                if direction == 'Y':
                    center_anchor = anchor_box['px'] + anchor_w // 2
                    center_target = target_box['px'] + target_w // 2
                    model.Add(center_target == center_anchor)
                elif direction == 'X':
                    center_anchor = anchor_box['py'] + anchor_d // 2
                    center_target = target_box['py'] + target_d // 2
                    model.Add(center_target == center_anchor)

    # --- Целевая функция: Минимизация взвешенной суммы расстояний ---
    all_distances = []
    all_weights = []

    for i in range(len(virtual_boxes)):
        for j in range(i + 1, len(virtual_boxes)):
            box1 = virtual_boxes[i]
            box2 = virtual_boxes[j]
            id1, id2 = box1['id'], box2['id']

            dist_x = model.NewIntVar(0, max_x_room, f"dist_x_{id1}_{id2}")
            dist_y = model.NewIntVar(0, max_y_room, f"dist_y_{id1}_{id2}")
            
            # Расстояние между центрами виртуальных боксов (включая зоны обслуживания)
            model.AddAbsEquality(dist_x, (box1['vx'] + box1['vw']//2) - (box2['vx'] + box2['vw']//2))
            model.AddAbsEquality(dist_y, (box1['vy'] + box1['vd']//2) - (box2['vy'] + box2['vd']//2))
            
            all_distances.extend([dist_x, dist_y])

            # Определяем вес для этой пары. 
            # OR-Tools работает с целыми числами, поэтому используем 1 и 10 вместо 0.1 и 1.0.
            # Низкий вес (1) для связанных пар, т.к. их расстояние уже задано жестким правилом.
            # Высокий вес (10) для всех остальных, чтобы решатель пытался их сблизить.
            current_pair = tuple(sorted((id1, id2)))
            weight = 1 if current_pair in connected_pairs else 10
            all_weights.extend([weight, weight])

    # Цель - минимизировать сумму произведений расстояний на их веса.
    model.Minimize(sum(dist * weight for dist, weight in zip(all_distances, all_weights)))
    print("  - Добавлена целевая функция: Минимизация взвешенного расстояния между объектами.")

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
