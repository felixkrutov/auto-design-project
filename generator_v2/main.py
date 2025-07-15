# --- ПОЛНЫЙ КОД ДЛЯ main.py ---
import json
import os
from placement import calculate_placements
from geometry import create_3d_model

def run_generation_pipeline(project_file: str, output_file: str):
    print(f"--- Запуск пайплайна для файла: {project_file} ---")

    try:
        with open(project_file, 'r', encoding='utf-8') as f:
            project_data = json.load(f)
        print("1. Файл задания project.json успешно загружен.")
    except Exception as e:
        print(f"КРИТИЧЕСКАЯ ОШИБКА: {e}")
        return

    print(f"2. Начинаем обработку проекта: '{project_data['meta']['project_name']}'")
    
    final_placements = calculate_placements(project_data)
    
    if not final_placements:
        print("ОШИБКА: Не удалось рассчитать положения. Прерывание.")
        return

    print("\n4. Итоговые координаты:")
    for eq_id, placement in final_placements.items():
        print(f"  - Объект '{eq_id}': X={placement['x']:.2f}, Y={placement['y']:.2f}")

    create_3d_model(project_data, final_placements, output_file)

    print(f"\n--- Пайплайн успешно завершен. Результат в файле: {output_file} ---")

if __name__ == "__main__":
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    input_json_path = os.path.join(SCRIPT_DIR, "project.json")
    output_ifc_path = os.path.join(SCRIPT_DIR, "output_model.ifc")
    run_generation_pipeline(input_json_path, output_ifc_path)
