import ifcopenshell
import ifcopenshell.api # <-- Импортируем правильный модуль
import pandas as pd
import sys
import math
import numpy as np

def get_rules_from_google_sheet(sheet_url):
    """Читает правила из Google Таблицы."""
    print("1. Читаем правила из Google Таблицы для проверки...")
    try:
        csv_export_url = sheet_url.replace('/edit?usp=sharing', '/export?format=csv')
        df = pd.read_csv(csv_export_url).fillna('')
        print(f"  > Успешно загружено {len(df)} правил.")
        return df
    except Exception as e:
        print(f"  > ОШИБКА: Не удалось загрузить правила. {e}")
        return None

def get_object_placement(ifc_placement, ifc_file):
    """Рекурсивно извлекает и преобразует координаты объекта."""
    if ifc_placement is None:
        return np.identity(4)
    
    if ifc_placement.is_a('IfcLocalPlacement'):
        parent_matrix = get_object_placement(ifc_placement.PlacementRelTo, ifc_file)
        # --- ИСПРАВЛЕНИЕ ЗДЕСЬ: Используем ifcopenshell.api.placement ---
        local_matrix = ifcopenshell.api.run("geometry.get_local_placement", ifc_file, placement=ifc_placement.RelativePlacement)
        return np.dot(parent_matrix, np.array(local_matrix))
    return np.identity(4)

def get_placements_from_ifc(ifc_file_path):
    """Извлекает имена и глобальные координаты объектов из IFC файла."""
    print(f"2. Анализируем IFC файл '{ifc_file_path}'...")
    try:
        ifc_file = ifcopenshell.open(ifc_file_path)
        placements = {}
        elements = ifc_file.by_type('IfcBuildingElementProxy')
        
        for element in elements:
            name = element.Name
            if element.ObjectPlacement:
                matrix = get_object_placement(element.ObjectPlacement, ifc_file)
                coords = matrix[:3, 3]
                placements[name] = {'x': coords[0], 'y': coords[1], 'z': coords[2]}
        
        print(f"  > Найдено {len(placements)} объектов для проверки.")
        return placements
    except Exception as e:
        print(f"  > ОШИБКА: Не удалось прочитать или проанализировать IFC файл. {e}")
        return None

def validate_model(sheet_url, ifc_file_path):
    """Главная функция-валидатор."""
    print("\n--- ЗАПУСК AI-ВАЛИДАТОРА ---")
    rules_df = get_rules_from_google_sheet(sheet_url)
    placements = get_placements_from_ifc(ifc_file_path)
    
    if rules_df is None or placements is None:
        print("--- ВАЛИДАЦИЯ ПРЕРВАНА ИЗ-ЗА ОШИБОК ---")
        return

    print("3. Начинаем проверку правил...")
    all_rules_passed = True
    
    for _, rule in rules_df.iterrows():
        obj1_name, rule_type, expected_value = rule['Объект1'], rule['Тип правила'], float(rule['Значение'])
        
        if obj1_name not in placements:
            print(f"  - [ПРОВАЛ] Объект '{obj1_name}' из правила не найден в IFC файле."); all_rules_passed = False; continue

        obj1_coords = placements[obj1_name]
        
        if rule_type == 'Мин. отступ от стены X0':
            actual_value = obj1_coords['x']
            if actual_value >= expected_value - 1e-6:
                print(f"  - [OK] '{obj1_name}' отступ от X0: {actual_value:.2f}м >= {expected_value:.2f}м")
            else:
                print(f"  - [ПРОВАЛ] '{obj1_name}' отступ от X0: {actual_value:.2f}м < {expected_value:.2f}м (ОШИБКА)"); all_rules_passed = False
        
        elif rule_type == 'Мин. отступ от стены Y0':
            actual_value = obj1_coords['y']
            if actual_value >= expected_value - 1e-6:
                print(f"  - [OK] '{obj1_name}' отступ от Y0: {actual_value:.2f}м >= {expected_value:.2f}м")
            else:
                print(f"  - [ПРОВАЛ] '{obj1_name}' отступ от Y0: {actual_value:.2f}м < {expected_value:.2f}м (ОШИБКА)"); all_rules_passed = False

        elif rule_type == 'Мин. расстояние до':
            obj2_name = rule['Объект2']
            if obj2_name not in placements:
                print(f"  - [ПРОВАЛ] Объект '{obj2_name}' из правила не найден."); all_rules_passed = False; continue
            
            obj2_coords = placements[obj2_name]
            dx, dy = obj1_coords['x'] - obj2_coords['x'], obj1_coords['y'] - obj2_coords['y']
            actual_distance = math.hypot(dx, dy)
            
            if actual_distance >= expected_value - 1e-6:
                print(f"  - [OK] Расстояние '{obj1_name}'-'{obj2_name}': {actual_distance:.2f}м >= {expected_value:.2f}м")
            else:
                print(f"  - [ПРОВАЛ] Расстояние '{obj1_name}'-'{obj2_name}': {actual_distance:.2f}м < {expected_value:.2f}м (ОШИБКА)"); all_rules_passed = False
                
    print("\n--- ОТЧЕТ ВАЛИДАЦИИ ---")
    if all_rules_passed: print("✅ Поздравляю! Все правила успешно выполнены. Модель корректна.")
    else: print("❌ Внимание! В модели найдены отклонения от правил.")
    print("----------------------")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("\nОшибка: Неверное количество аргументов.\nПример запуска: python validate_ifc.py <URL> <файл.ifc>\n")
        sys.exit(1)
        
    try: import numpy
    except ImportError:
        print("\nОшибка: Библиотека numpy не установлена. Выполните: pip install numpy\n"); sys.exit(1)
            
    validate_model(sys.argv[1], sys.argv[2])
