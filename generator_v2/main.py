import json
from placement import calculate_placements # <-- НОВЫЙ ИМПОРТ

def run_generation_pipeline(project_file: str):
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

    # --- ЭТАП 2: Обработка данных ---
    project_name = project_data.get('meta', {}).get('project_name', 'Без имени')
    equipment_list = project_data.get('equipment', [])
    rules_list = project_data.get('rules', [])
    
    print(f"2. Начинаем обработку проекта: '{project_name}'")
    print(f"   Найдено единиц оборудования: {len(equipment_list)}")
    print(f"   Найдено правил: {len(rules_list)}")
    
    # --- ЭТАП 3: Расчет положений --- # <-- НОВЫЙ ЭТАП
    final_placements = calculate_placements(equipment_list, rules_list)
    
    if final_placements:
         print("\n4. Итоговые координаты:")
         for eq_id, placement in final_placements.items():
             print(f"  - Объект '{eq_id}': X={placement['x']:.2f}, Y={placement['y']:.2f}, Поворот={placement['rotation_deg']}°")

    # --- Следующие этапы будут здесь (генерация 3D) ---

    print("\n--- Пайплайн завершен (пока частично) ---")

if __name__ == "__main__":
    run_generation_pipeline("project.json")
