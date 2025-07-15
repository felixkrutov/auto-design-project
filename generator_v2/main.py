import json
import os  # <-- НОВЫЙ ИМПОРТ
from placement import calculate_placements
from geometry import create_3d_model

def run_generation_pipeline(project_file: str, output_file: str):
    """Главный пайплайн генерации завода."""
    print(f"--- Запуск пайплайна для файла: {project_file} ---")

    # --- ЭТАП 1: Загрузка данных ---
    try:
        with open(project_file, 'r', encoding='utf-8') as f:
            project_data = json.load(f)
        print("1. Файл задания project.json успешно загружен.")
    except Exception as e:
        print(f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось загрузить или прочитать файл. {e}")
        return

    # ... (остальной код остается без изменений) ...
    project_name = project_data.get('meta', {}).get('project_name', 'Без имени')
    equipment_list = project_data.get('equipment', [])
    rules_list = project_data.get('rules', [])
    
    print(f"2. Начинаем обработку проекта: '{project_name}'")
    print(f"   Найдено единиц оборудования: {len(equipment_list)}")
    print(f"   Найдено правил: {len(rules_list)}")
    
    final_placements = calculate_placements(equipment_list, rules_list)
    
    if not final_placements:
        print("ОШИБКА: Не удалось рассчитать положения. Прерывание.")
        return

    print("\n4. Итоговые координаты:")
    for eq_id, placement in final_placements.items():
        print(f"  - Объект '{eq_id}': X={placement['x']:.2f}, Y={placement['y']:.2f}, Поворот={placement['rotation_deg']}°")

    create_3d_model(project_data, final_placements, output_file)

    print(f"\n--- Пайплайн успешно завершен. Результат в файле: {output_file} ---")

if __name__ == "__main__":
    # --- НОВЫЙ БЛОК ДЛЯ ОПРЕДЕЛЕНИЯ ПУТЕЙ ---
    # Определяем абсолютный путь к папке, где лежит main.py
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    
    # Составляем полные пути к файлам
    input_json_path = os.path.join(SCRIPT_DIR, "project.json")
    output_ifc_path = os.path.join(SCRIPT_DIR, "output_model.ifc")
    
    run_generation_pipeline(input_json_path, output_ifc_path)
