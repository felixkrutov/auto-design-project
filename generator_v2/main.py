import json

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
    
    print(f"2. Начинаем обработку проекта: '{project_name}'")
    print(f"   Найдено единиц оборудования: {len(equipment_list)}")
    for item in equipment_list:
        print(f"     - ID: {item.get('id', 'N/A')}, Имя: {item.get('name', 'N/A')}")

    # --- Следующие этапы будут здесь ---

    print("--- Пайплайн завершен (пока частично) ---")

if __name__ == "__main__":
    # Важно! При запуске из корня проекта, путь должен быть полный
    run_generation_pipeline("generator_v2/project.json")
