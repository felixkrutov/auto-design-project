import logging

# Подавляем информационные сообщения от ifcopenshell.api, оставляем только ошибки.
# Это нужно сделать до импорта других модулей проекта, которые используют ifcopenshell.
logging.getLogger('ifcopenshell').setLevel(logging.ERROR)

import json
import os
import sys
from placement import calculate_placements
from geometry import create_3d_model

def run_generation_pipeline(project_file: str, output_file: str):
    """
    Выполняет полный цикл проектирования: загрузка, расчет размещения, генерация 3D модели.
    """
    print(f"--- Запуск пайплайна для файла: {project_file} ---")

    try:
        with open(project_file, 'r', encoding='utf-8') as f:
            project_data = json.load(f)
        print("1. Файл задания project.json успешно загружен.")
    except FileNotFoundError:
        print(f"КРИТИЧЕСКАЯ ОШИБКА: Файл проекта '{project_file}' не найден.")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось прочитать JSON файл. Ошибка: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"КРИТИЧЕСКАЯ ОШИБКА: Произошла непредвиденная ошибка при загрузке данных: {e}")
        sys.exit(1)

    project_name = project_data.get('meta', {}).get('project_name', 'UnnamedProject')
    print(f"2. Начинаем обработку проекта: '{project_name}'")
    
    final_placements = calculate_placements(project_data)
    
    if not final_placements:
        print("ОШИБКА: Не удалось рассчитать положения. Генерация 3D модели прервана.")
        return

    print("\n4. Итоговые координаты:")
    for eq_id, placement in final_placements.items():
        print(f"  - Объект '{eq_id}': X={placement['x']:.2f}, Y={placement['y']:.2f}")

    create_3d_model(project_data, final_placements, output_file)

    print(f"\n--- Пайплайн успешно завершен. Результат в файле: {output_file} ---")

if __name__ == "__main__":
    # Определяем директорию, в которой запущен скрипт
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    
    # Путь к файлу проекта по умолчанию
    input_json_path = os.path.join(SCRIPT_DIR, "project.json")
    
    # Если в командной строке передан аргумент, используем его как путь к файлу проекта
    if len(sys.argv) > 1:
        input_json_path = sys.argv[1]
        print(f"Используется файл проекта из аргумента командной строки: {input_json_path}")

    # Создаем директорию output, если она не существует
    output_dir = os.path.join(SCRIPT_DIR, "output")
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Создана директория для выходных файлов: {output_dir}")

    # Имя выходного файла формируется на основе имени входного файла
    base_name = os.path.splitext(os.path.basename(input_json_path))[0]
    output_ifc_path = os.path.join(output_dir, f"{base_name}_model.ifc")
    
    run_generation_pipeline(input_json_path, output_ifc_path)
