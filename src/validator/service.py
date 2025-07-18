import itertools
from typing import List, Dict

from src.core.models import Project

def validate_collisions(project: Project, placements: Dict[str, Dict[str, float]]) -> List[str]:
    """
    Checks for 2D bounding box collisions between all placed equipment items.

    This function iterates through every unique pair of equipment items, calculates their
    axis-aligned bounding boxes based on the provided placement data and footprint
    dimensions, and checks for any spatial overlap. It does not perform a 3D mesh
    collision check.

    Args:
        project: The validated Pydantic Project object containing all equipment data.
        placements: A dictionary mapping equipment IDs to their calculated
                    placement coordinates (e.g., {'x': 1.0, 'y': 2.5}).

    Returns:
        A list of human-readable strings describing each detected collision.
        Returns an empty list if no collisions are found.
    """
    collision_errors: List[str] = []
    
    # Create a list of dictionaries, where each entry represents an
    # equipment item's bounding box for easier processing.
    equipment_boxes = []
    for eq_item in project.equipment:
        placement = placements.get(eq_item.id)
        # If an equipment item from the project has no placement, skip it.
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
        
    # Iterate through every unique pair of equipment boxes
    if len(equipment_boxes) < 2:
        return []

    for item_a, item_b in itertools.combinations(equipment_boxes, 2):
        # AABB (Axis-Aligned Bounding Box) collision check
        # Two rectangles overlap if they overlap on both the X and Y axes.
        x_overlap = item_a['x1'] < item_b['x2'] and item_a['x2'] > item_b['x1']
        y_overlap = item_a['y1'] < item_b['y2'] and item_a['y2'] > item_b['y1']
        
        if x_overlap and y_overlap:
            error_message = f"Collision detected between: '{item_a['name']}' and '{item_b['name']}'"
            collision_errors.append(error_message)
            
    return collision_errors
