from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field

class Meta(BaseModel):
    """
    Metadata for the project, including its name and the schema version.
    """
    project_name: str = Field(..., description="The user-defined name for the factory project.")
    schema_version: str = Field(..., description="The version of the project schema.")


class RoomDimensions(BaseModel):
    """
    Defines the internal, usable dimensions of the room where equipment will be placed.
    """
    width: float = Field(..., gt=0, description="The total internal width of the room (X-axis).")
    depth: float = Field(..., gt=0, description="The total internal depth of the room (Y-axis).")
    height: float = Field(..., gt=0, description="The total internal height of the room (Z-axis).")


class RoofConfig(BaseModel):
    """
    Defines the configuration for the building's roof, including its type and dimensions.
    """
    type: Literal["FLAT", "GABLE"] = Field(..., description="The structural type of the roof.")
    height: Optional[float] = Field(default=None, gt=0, description="The height of the roof's peak, used for GABLE type.")
    thickness: Optional[float] = Field(default=None, gt=0, description="The thickness of the roof slab, used for FLAT type.")


class Architecture(BaseModel):
    """
    Architectural parameters of the factory space, including room size, wall thickness, and roof configuration.
    """
    room_dimensions: RoomDimensions = Field(..., description="The internal dimensions of the room.")
    wall_thickness: float = Field(..., ge=0, description="The thickness of the surrounding walls.")
    roof: Optional[RoofConfig] = Field(default=None, description="Optional configuration for the building's roof.")


class Footprint(BaseModel):
    """
    The base area (width and depth) occupied by an equipment item on the floor.
    """
    width: float = Field(..., gt=0, description="The width of the equipment's base (X-axis).")
    depth: float = Field(..., gt=0, description="The depth of the equipment's base (Y-axis).")


class MaintenanceZone(BaseModel):
    """
    Optional maintenance clearances around an equipment item. These zones are added to the
    footprint to create a larger virtual box for the placement solver.
    """
    front: float = Field(default=0.0, ge=0, description="Additional clearance at the front of the equipment.")
    back: float = Field(default=0.0, ge=0, description="Additional clearance at the back of the equipment.")
    left: float = Field(default=0.0, ge=0, description="Additional clearance on the left side of the equipment.")
    right: float = Field(default=0.0, ge=0, description="Additional clearance on the right side of the equipment.")


class EquipmentItem(BaseModel):
    """
    A single piece of equipment to be placed in the factory. It includes physical
    dimensions and optional maintenance requirements.
    """
    id: str = Field(..., description="A unique identifier for the equipment item (e.g., 'silos-01').")
    name: str = Field(..., description="A human-readable name for the equipment (e.g., 'Силос для сырья').")
    footprint: Footprint = Field(..., description="The physical footprint of the equipment.")
    height: float = Field(..., gt=0, description="The total height of the equipment.")
    maintenance_zone: Optional[MaintenanceZone] = Field(default=None, description="Optional maintenance zones around the equipment.")


class Rule(BaseModel):
    """
    A placement rule or constraint for the solver. The structure of 'params'
    is dependent on the 'type' of the rule.
    """
    type: str = Field(..., description="The type of the rule (e.g., 'PLACE_AFTER', 'ALIGN').")
    params: Dict[str, Any] = Field(..., description="A dictionary of parameters specific to the rule type.")
    comment: Optional[str] = Field(default=None, description="An optional human-readable comment about the rule's purpose.")


class SolverOptions(BaseModel):
    """
    Optional configuration for the placement optimization solver.
    """
    time_limit_sec: Optional[float] = Field(default=30.0, gt=0, description="Time limit in seconds for the solver to find a solution.")


class Project(BaseModel):
    """
    The root model representing the entire factory design project. It serves as the
    single source of truth for all data loaded from the project.json file.
    """
    meta: Meta = Field(..., description="Project metadata.")
    architecture: Architecture = Field(..., description="Architectural details of the building.")
    equipment: List[EquipmentItem] = Field(..., description="A list of all equipment items to be placed.")
    rules: List[Rule] = Field(..., description="A list of placement rules and constraints for the solver.")
    solver_options: Optional[SolverOptions] = Field(default=None, description="Optional settings for the solver.")
