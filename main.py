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
from src.validator.service import validate_collisions

def run_generation_pipeline(project_file: str, output_file: str):
    """
    Executes the full design pipeline: loads data, validates it, calculates placements,
    checks for collisions, and generates the final 3D model.
    """
    print(f"--- Starting pipeline for file: {project_file} ---")

    # Step 1: Load and validate project data
    try:
        with open(project_file, 'r', encoding='utf-8') as f:
            project_data = json.load(f)
        print("1. Project data file successfully loaded.")
        
        project = Project.parse_obj(project_data)
        print("1.5. Project data successfully validated against the model.")
    except FileNotFoundError:
        print(f"CRITICAL ERROR: Project file '{project_file}' not found.")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"CRITICAL ERROR: Could not parse JSON file. Error: {e}")
        sys.exit(1)
    except ValidationError as e:
        print(f"CRITICAL ERROR: The project file '{project_file}' has an invalid data structure.")
        print("Validation Details:")
        print(e)
        sys.exit(1)
    except Exception as e:
        print(f"CRITICAL ERROR: An unexpected error occurred: {e}")
        sys.exit(1)

    # Step 2: Begin processing with validated data
    print(f"\n2. Processing project: '{project.meta.project_name}'")
    
    # Step 3: Calculate placements
    final_placements = calculate_placements(project)
    
    if not final_placements:
        print("ERROR: Could not calculate placements. Halting generation.")
        return

    print("\n3. Final Coordinates:")
    for eq_id, placement in final_placements.items():
        print(f"  - Item '{eq_id}': X={placement['x']:.2f}, Y={placement['y']:.2f}")

    # Step 4: Validate the calculated placements for collisions
    print("\n4. Performing collision validation...")
    validation_errors = validate_collisions(project, final_placements)
    # The pipeline continues even if collisions are found.

    # Step 5: Create 3D model
    create_3d_model(project, final_placements, output_file)

    # Step 6: Report final results
    print(f"\n--- Pipeline finished. Model saved to: {output_file} ---")
    print("\n--- Validation Results ---")
    if not validation_errors:
        print("6. Валидация пройдена успешно. Коллизий не обнаружено.")
    else:
        print("6. Валидация выявила ошибки:")
        for error in validation_errors:
            print(f"  - {error}")

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
