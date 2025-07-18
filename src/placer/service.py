from ortools.sat.python import cp_model
from typing import Dict, List

from src.core.models import Project, EquipmentItem

def get_box_by_id(boxes: List[Dict], target_id: str) -> Dict:
    """Helper function to find a 'virtual box' by its ID within the solver's internal list."""
    try:
        return next(b for b in boxes if b['id'] == target_id)
    except StopIteration:
        raise ValueError(f"Rule error: Could not find an object with ID '{target_id}'")

def calculate_placements(project: Project) -> Dict[str, Dict[str, float]]:
    """
    Calculates the optimal 2D placements for equipment using the OR-Tools CP-SAT solver,
    based on the validated project data model.
    """
    print("3. Calculating equipment placements with OR-Tools...")
    
    model = cp_model.CpModel()
    SCALE = 100
    PENALTY_COST = 10000 # Large penalty for violating a soft constraint

    # Safely access data from the Pydantic model
    room_dims = project.architecture.room_dimensions
    wall_thickness = project.architecture.wall_thickness
    
    time_limit = 30.0
    if project.solver_options:
        time_limit = project.solver_options.time_limit_sec

    min_x_room = int(wall_thickness * SCALE)
    max_x_room = int((room_dims.width - wall_thickness) * SCALE)
    min_y_room = int(wall_thickness * SCALE)
    max_y_room = int((room_dims.depth - wall_thickness) * SCALE)

    positions = {}
    virtual_boxes = []
    # Create a direct mapping from ID to EquipmentItem for quick lookups
    equipment_map: Dict[str, EquipmentItem] = {item.id: item for item in project.equipment}

    for item in project.equipment:
        # Use maintenance_zone if it exists, otherwise default values are 0
        m_zone_left = item.maintenance_zone.left if item.maintenance_zone else 0.0
        m_zone_right = item.maintenance_zone.right if item.maintenance_zone else 0.0
        m_zone_back = item.maintenance_zone.back if item.maintenance_zone else 0.0
        m_zone_front = item.maintenance_zone.front if item.maintenance_zone else 0.0

        w = int((m_zone_left + item.footprint.width + m_zone_right) * SCALE)
        d = int((m_zone_back + item.footprint.depth + m_zone_front) * SCALE)
        
        x_offset = int(m_zone_left * SCALE)
        y_offset = int(m_zone_back * SCALE)

        vx = model.NewIntVar(min_x_room, max_x_room - w, f"vx_{item.id}")
        vy = model.NewIntVar(min_y_room, max_y_room - d, f"vy_{item.id}")
        
        px = model.NewIntVar(min_x_room, max_x_room, f"x_{item.id}")
        py = model.NewIntVar(min_y_room, max_y_room, f"y_{item.id}")
        
        model.Add(px == vx + x_offset)
        model.Add(py == vy + y_offset)
        
        positions[item.id] = {'x': px, 'y': py, 'w': w, 'd': d}
        virtual_boxes.append({'id': item.id, 'vx': vx, 'vy': vy, 'vw': w, 'vd': d, 'px': px, 'py': py})

    intervals_x = [model.NewIntervalVar(box['vx'], box['vw'], box['vx'] + box['vw'], f"ivx_{box['id']}") for box in virtual_boxes]
    intervals_y = [model.NewIntervalVar(box['vy'], box['vd'], box['vy'] + box['vd'], f"ivy_{box['id']}") for box in virtual_boxes]
    model.AddNoOverlap2D(intervals_x, intervals_y)
    print("  - Added global rule: NoOverlap2D (including maintenance zones).")
    
    print("  - Applying rules from project data...")
    connected_pairs = set()
    alignment_penalties = []

    for i, rule in enumerate(project.rules):
        rtype = rule.type
        params = rule.params
        
        if rtype == 'AVOID_ZONE':
            x1, y1, x2, y2 = params['area']
            print(f"    - Rule AVOID_ZONE for area [{x1},{y1},{x2},{y2}]")
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
            box = get_box_by_id(virtual_boxes, params['target'])
            x1, y1, x2, y2 = params['area']
            print(f"    - Rule PLACE_IN_ZONE for '{box['id']}'")
            model.Add(box['vx'] >= int(x1 * SCALE))
            model.Add(box['vy'] >= int(y1 * SCALE))
            model.Add(box['vx'] + box['vw'] <= int(x2 * SCALE))
            model.Add(box['vy'] + box['vd'] <= int(y2 * SCALE))

        elif rtype == 'ATTACH_TO_WALL':
            box = get_box_by_id(virtual_boxes, params['target'])
            side = params['side']
            dist = int(params.get('distance', 0) * SCALE)
            print(f"    - Rule ATTACH_TO_WALL for '{box['id']}' to wall {side}")
            if side == 'Xmin': model.Add(box['vx'] == min_x_room + dist)
            elif side == 'Xmax': model.Add(box['vx'] + box['vw'] == max_x_room - dist)
            elif side == 'Ymin': model.Add(box['vy'] == min_y_room + dist)
            elif side == 'Ymax': model.Add(box['vy'] + box['vd'] == max_y_room - dist)
            
        elif rtype == 'ALIGN':
            t1_id, t2_id = params['target1'], params['target2']
            box1 = get_box_by_id(virtual_boxes, t1_id)
            box2 = get_box_by_id(virtual_boxes, t2_id)
            axis = params['axis']
            print(f"    - Hard rule ALIGN for '{t1_id}' and '{t2_id}' on axis {axis}")
            
            w1 = int(equipment_map[t1_id].footprint.width * SCALE)
            d1 = int(equipment_map[t1_id].footprint.depth * SCALE)
            w2 = int(equipment_map[t2_id].footprint.width * SCALE)
            d2 = int(equipment_map[t2_id].footprint.depth * SCALE)
            
            center1_x = box1['px'] + w1 // 2
            center1_y = box1['py'] + d1 // 2
            center2_x = box2['px'] + w2 // 2
            center2_y = box2['py'] + d2 // 2
            
            if axis == 'X': model.Add(center1_x == center2_x)
            else: model.Add(center1_y == center2_y)

        elif rtype == 'PLACE_AFTER':
            target_id, anchor_id = params['target'], params['anchor']
            target_box = get_box_by_id(virtual_boxes, target_id)
            anchor_box = get_box_by_id(virtual_boxes, anchor_id)
            direction = params.get('direction', 'Y')
            distance = int(params.get('distance', 0) * SCALE)
            alignment = params.get('alignment', 'center')

            connected_pairs.add(tuple(sorted((anchor_id, target_id))))
            print(f"    - Rule PLACE_AFTER: '{target_id}' after '{anchor_id}', alignment: {alignment} (soft)")

            anchor_w = int(equipment_map[anchor_id].footprint.width * SCALE)
            anchor_d = int(equipment_map[anchor_id].footprint.depth * SCALE)
            target_w = int(equipment_map[target_id].footprint.width * SCALE)
            target_d = int(equipment_map[target_id].footprint.depth * SCALE)

            if direction == 'Y': model.Add(target_box['py'] == anchor_box['py'] + anchor_d + distance)
            elif direction == 'X': model.Add(target_box['px'] == anchor_box['px'] + anchor_w + distance)
            
            if alignment == 'center':
                is_aligned = model.NewBoolVar(f"align_{anchor_id}_{target_id}")
                if direction == 'Y':
                    model.Add(target_box['px'] + target_w // 2 == anchor_box['px'] + anchor_w // 2).OnlyEnforceIf(is_aligned)
                elif direction == 'X':
                    model.Add(target_box['py'] + target_d // 2 == anchor_box['py'] + anchor_d // 2).OnlyEnforceIf(is_aligned)
                alignment_penalties.append(PENALTY_COST * is_aligned.Not())

    all_distances, all_weights = [], []
    for i in range(len(virtual_boxes)):
        for j in range(i + 1, len(virtual_boxes)):
            b1, b2 = virtual_boxes[i], virtual_boxes[j]
            id1, id2 = b1['id'], b2['id']

            dist_x = model.NewIntVar(0, max_x_room, f"dist_x_{id1}_{id2}")
            dist_y = model.NewIntVar(0, max_y_room, f"dist_y_{id1}_{id2}")
            
            model.AddAbsEquality(dist_x, (b1['vx'] + b1['vw']//2) - (b2['vx'] + b2['vw']//2))
            model.AddAbsEquality(dist_y, (b1['vy'] + b1['vd']//2) - (b2['vy'] + b2['vd']//2))
            all_distances.extend([dist_x, dist_y])

            weight = 1 if tuple(sorted((id1, id2))) in connected_pairs else 10
            all_weights.extend([weight, weight])
    
    weighted_distance_sum = sum(dist * weight for dist, weight in zip(all_distances, all_weights))
    total_penalty = sum(alignment_penalties)
    
    model.Minimize(weighted_distance_sum + total_penalty)
    print("  - Added objective function: Minimize weighted distance and non-alignment penalties.")

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    status = solver.Solve(model)

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("  > Solution found!")
        final_placements = {}
        for item in project.equipment:
            item_id = item.id
            final_placements[item_id] = {
                'x': solver.Value(positions[item_id]['x']) / SCALE,
                'y': solver.Value(positions[item_id]['y']) / SCALE,
                'rotation_deg': 0 
            }
        return final_placements
    else:
        print(f"  > ERROR: Solution not found. Status: {solver.StatusName(status)}")
        return None
