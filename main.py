import logging

# Suppress informational messages from ifcopenshell.api, leaving only errors.
# This must be done before importing any project modules that use ifcopenshell.
logging.getLogger('ifcopenshell').setLevel(logging.ERROR)

import json
import os
import sys
from pydantic import ValidationError

from src.core.models import Project
from src.placer.service import calculate_placements
from src.generator.service import create_3d_model

def run_generation_pipeline(project_file: str, output_file: str):
    """
    Executes the full design pipeline: loads data, validates it, calculates placements,
    and generates the final 3D model.
    """
    print(f"--- Starting pipeline for file: {project_file} ---")

    # Step 1: Load raw data from JSON file
    try:
        with open(project_file, 'r', encoding='utf-8') as f:
            project_data = json.load(f)
        print("1. Project data file successfully loaded.")
    except FileNotFoundError:
        print(f"CRITICAL ERROR: Project file '{project_file}' not found.")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"CRITICAL ERROR: Could not parse JSON file. Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"CRITICAL ERROR: An unexpected error occurred while loading data: {e}")
        sys.exit(1)

    # Step 1.5: Validate the raw data using Pydantic models
    try:
        project = Project.parse_obj(project_data)
        print("1.5. Project data successfully validated against the model.")
    except ValidationError as e:
        print(f"CRITICAL ERROR: The project file '{project_file}' has an invalid data structure.")
        print("Validation Details:")
        print(e)
        sys.exit(1)

    # Step 2: Begin processing with validated data
    print(f"2. Processing project: '{project.meta.project_name}'")
    
    # Step 3: Calculate placements using the validated project object
    final_placements = calculate_placements(project)
    
    if not final_placements:
        print("ERROR: Could not calculate placements. Halting generation.")
        return

    # Step 4: Display final coordinates
    print("\n4. Final Coordinates:")
    for eq_id, placement in final_placements.items():
        print(f"  - Item '{eq_id}': X={placement['x']:.2f}, Y={placement['y']:.2f}")

    # Step 5: Create 3D model using the validated project object
    create_3d_model(project, final_placements, output_file)

    print(f"\n--- Pipeline finished successfully. Result saved to: {output_file} ---")

if __name__ == "__main__":
    # Determine the directory where the script is running
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    
    # Default path for the project file
    input_json_path = os.path.join(SCRIPT_DIR, "project.json")
    
    # If a command-line argument is provided, use it as the path to the project file
    if len(sys.argv) > 1:
        input_json_path = sys.argv[1]
        print(f"Using project file from command-line argument: {input_json_path}")

    # Ensure the output directory exists
    output_dir = os.path.join(SCRIPT_DIR, "output")
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Created output directory: {output_dir}")

    # The output filename is based on the input filename
    base_name = os.path.splitext(os.path.basename(input_json_path))[0]
    output_ifc_path = os.path.join(output_dir, f"{base_name}_model.ifc")
    
    run_generation_pipeline(input_json_path, output_ifc_path)
