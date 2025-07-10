import ifcopenshell
import pandas as pd
import sys
import math

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

def get_placements_from_ifc(ifc_file_path):
    """Извлекает имена и координаты объектов из IFC файла."""
    print(f"2. Анализируем IFC файл '{ifc_file_path}'...")
    try:
        ifc_file = ifcopenshell.open(ifc_file_path)
        placements = {}
        elements = ifc_file.by_type('IfcBuildingElementProxy')
        
        for element in elements:
            name = element.Name
            if element.ObjectPlacement:
                # Проходим по сложной структуре размещений, чтобы найти глобальные координаты
                placement = element.ObjectPlacement
                while placement.PlacementRelTo:
                    parent_coords = placement.PlacementRelTo.RelativePlacement.Location.Coordinates
                    local_coords = placement.RelativePlacement.Location.Coordinates
                    # Складываем координаты, чтобы получить абсолютные
                    coords = tuple(p + l for p, l in zip(parent_coords, local_coords))
                    placement.RelativePlacement.Location.Coordinates = coords
                    placement = placement.PlacementRelTo
                
                final_coords = placement.RelativePlacement.Location.Coordinates
                placements[name] = {'x': final_coords[0], 'y': final_coords[1]}
        
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
        obj1_name = rule['Объект1']
        rule_type = rule['Тип правила']
        expected_value = float(rule['Значение'])
        
        if obj1_name not in placements:
            print(f"  - [ПРОВАЛ] Объект '{obj1_name}' из правила не найден в IFC файле.")
            all_rules_passed = False
            continue

        obj1_coords = placements[obj1_name]
        
        # Проверка отступов от стен
        if rule_type == 'Мин. отступ от стены X0':
            actual_value = obj1_coords['x']
            if actual_value >= expected_value:
                print(f"  - [OK] '{obj1_name}' отступ от X0: {actual_value:.2f}м >= {expected_value:.2f}м")
            else:
                print(f"  - [ПРОВАЛ] '{obj1_name}' отступ от X0: {actual_value:.2f}м < {expected_value:.2f}м (ОШИБКА)")
                all_rules_passed = False
        
        elif rule_type == 'Мин. отступ от стены Y0':
            actual_value = obj1_coords['y']
            if actual_value >= expected_value:
                print(f"  - [OK] '{obj1_name}' отступ от Y0: {actual_value:.2f}м >= {expected_value:.2f}м")
            else:
                print(f"  - [ПРОВАЛ] '{obj1_name}' отступ от Y0: {actual_value:.2f}м < {expected_value:.2f}м (ОШИБКА)")
                all_rules_passed = False

        # Проверка расстояния между объектами
        elif rule_type == 'Мин. расстояние до':
            obj2_name = rule['Объект2']
            if obj2_name not in placements:
                print(f"  - [ПРОВАЛ] Объект '{obj2_name}' из правила не найден в IFC файле.")
                all_rules_passed = False
                continue
            
            obj2_coords = placements[obj2_name]
            dx = obj1_coords['x'] - obj2_coords['x']
            dy = obj1_coords['y'] - obj2_coords['y']
            actual_distance = math.hypot(dx, dy) # sqrt(dx*dx + dy*dy)
            
            if actual_distance >= expected_value:
                print(f"  - [OK] Расстояние '{obj1_name}'-'{obj2_name}': {actual_distance:.2f}м >= {expected_value:.2f}м")
            else:
                print(f"  - [ПРОВАЛ] Расстояние '{obj1_name}'-'{obj2_name}': {actual_distance:.2f}м < {expected_value:.2f}м (ОШИБКА)")
                all_rules_passed = False
                
    print("\n--- ОТЧЕТ ВАЛИДАЦИИ ---")
    if all_rules_passed:
        print("✅ Поздравляю! Все правила успешно выполнены. Модель корректна.")
    else:
        print("❌ Внимание! В модели найдены отклонения от правил.")
    print("----------------------")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("\nОшибка: Неверное количество аргументов.")
        print("Пример запуска: python validate_ifc.py <URL_Google_Таблицы> <путь_к_prototype.ifc>\n")
    else:
        google_sheet_url = sys.argv[1]
        ifc_file_path = sys.argv[2]
        validate_model(google_sheet_url, ifc_file_path)
