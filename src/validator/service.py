import itertools
from typing import List, Dict

from src.core.models import Project

def validate_collisions(project: Project, placements: Dict[str, Dict[str, float]]) -> List[str]:
    collision_errors: List[str] = []
    
    equipment_boxes = []
    for eq_item in project.equipment:
        placement = placements.get(eq_item.id)
        if not placement:
            continue
            
        x1 = placement['x']
        y1 = placement['y']
        
        equipment_boxes.append({
            'name': eq_item.name,
            'x1': x1,
            'y1': y1,
            'x2': x1 + eq_item.footprint.width,
            'y2': y1 + eq_item.footprint.depth,
        })
        
    if len(equipment_boxes) < 2:
        return []

    for item_a, item_b in itertools.combinations(equipment_boxes, 2):
        x_overlap = item_a['x1'] < item_b['x2'] and item_a['x2'] > item_b['x1']
        y_overlap = item_a['y1'] < item_b['y2'] and item_a['y2'] > item_b['y1']
        
        if x_overlap and y_overlap:
            error_message = f"Collision detected between: '{item_a['name']}' and '{item_b['name']}'"
            collision_errors.append(error_message)
            
    return collision_errors
