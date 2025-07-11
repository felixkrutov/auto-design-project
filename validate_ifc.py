import ifcopenshell
import pandas as pd
import sys
import math

def get_rules_from_google_sheet(sheet_url):
    """
    Загружает и парсит правила из общедоступной Google Таблицы.
    """
    print("1. Чтение правил из Google Таблицы...")
    try:
        csv_export_url = sheet_url.replace('/edit?usp=sharing', '/export?format=csv')
        df = pd.read_csv(csv_export_url).fillna('')
        print(f"  > Успешно загружено {len(df)} правил.")
        return df
    except Exception as e:
        print(f"  > ОШИБКА: Не удалось загрузить правила. {e}")
        return None

def get_absolute_placement(ifc_placement):
    """
    Рекурсивно вычисляет абсолютные координаты точки вставки объекта,
    проходя по всей вложенной иерархии IfcLocalPlacement.
    """
    x, y, z = 0, 0, 0
    if ifc_placement.PlacementRelTo:
        parent_x, parent_y, parent_z = get_absolute_placement(ifc_placement.PlacementRelTo)
        x, y, z = x + parent_x, y + parent_y, z + parent_z

    relative_coords = ifc_placement.RelativePlacement.Location.Coordinates
    x, y, z = x + relative_coords[0], y + relative_coords[1], z + relative_coords[2]
    
    return x, y, z

def extract_placements_from_ifc(ifc_filename):
    """
    Извлекает фактическое положение и размеры объектов из IFC файла.
    Корректно вычисляет координаты нижнего левого угла (minX, minY).
    """
    print(f"2. Анализ IFC файла '{ifc_filename}'...")
    try:
        ifc_file = ifcopenshell.open(ifc_filename)
    except Exception as e:
        print(f"  > ОШИБКА: Не удалось открыть IFC файл. {e}")
        return None

    placements = {}
    elements = ifc_file.by_type("IfcBuildingElementProxy")
    
    for element in elements:
        name = element.Name
        
        # --- ИСПРАВЛЕННАЯ ЛОГИКА ---
        # 1. Извлекаем координаты ЦЕНТРАЛЬНОЙ точки вставки
        center_x, center_y, _ = get_absolute_placement(element.ObjectPlacement)

        # 2. Извлекаем размеры (ширину и глубину)
        width, depth = 0, 0
        try:
            shape = element.Representation.Representations[0]
            solid = shape.Items[0]
            profile = solid.SweptArea
            if isinstance(profile, ifcopenshell.ifcopenshell_wrapper.IfcRectangleProfileDef):
                width, depth = profile.XDim, profile.YDim
            else:
                print(f"  > ПРЕДУПРЕЖДЕНИЕ: Неподдерживаемый тип профиля для '{name}'.")
                continue
        except (AttributeError, IndexError):
            print(f"  > ПРЕДУПРЕЖДЕНИЕ: Не удалось извлечь размеры для '{name}'.")
            continue

        # 3. Вычисляем координаты НИЖНЕГО ЛЕВОГО угла (minX, minY)
        min_x, min_y = center_x - (width / 2), center_y - (depth / 2)

        placements[name] = {
            'x': min_x, 'y': min_y, 'width': width, 'depth': depth
        }
        # --- КОНЕЦ ИСПРАВЛЕННОЙ ЛОГИКИ ---
        
    print(f"  > Найдено и обработано {len(placements)} объектов.")
    return placements

def validate_layout(rules_df, placements):
    """
    Проверяет соответствие фактических размещений заданным правилам.
    """
    print("3. Запуск проверки правил...")
    if not placements:
        print("  > ОШИБКА: Нет данных о размещениях для проверки.")
        return

    passed_rules, failed_rules = 0, 0
    
    for index, rule in rules_df.iterrows():
        rule_type = rule['Тип правила'].strip()
        obj1_name = rule['Объект1'].strip()
        value_str = str(rule['Значение']).strip()

        is_rule_passed = None
        actual_value_str = ""
        rule_description = f"Правило #{index+1}: '{rule_type}' для '{obj1_name}'"

        if rule_type == 'Запретная зона':
            try:
                zone_xmin, zone_ymin, zone_xmax, zone_ymax = map(float, value_str.split(','))
            except Exception:
                print(f"  - [ПРЕДУПРЕЖДЕНИЕ] Некорректное значение для '{rule_description}'. Ожидается 'Xmin,Ymin,Xmax,Ymax'.")
                continue
            
            violator = None
            for obj_name, obj in placements.items():
                obj_xmin, obj_ymin = obj['x'], obj['y']
                obj_xmax, obj_ymax = obj_xmin + obj['width'], obj_ymin + obj['depth']

                if (obj_xmin < zone_xmax and obj_xmax > zone_xmin and
                    obj_ymin < zone_ymax and obj_ymax > zone_ymin):
                    violator = obj_name
                    break
            
            is_rule_passed = violator is None
            actual_value_str = f"объект '{violator}' пересекает зону" if violator else "зона свободна"
        
        else:
            if obj1_name not in placements:
                print(f"  - [ПРЕДУПРЕЖДЕНИЕ] Объект '{obj1_name}' из правила #{index+1} не найден в IFC.")
                continue

            obj1 = placements[obj1_name]
            value = float(value_str) if value_str else 0.0

            if rule_type == 'Мин. расстояние до':
                obj2_name = rule['Объект2'].strip()
                if obj2_name not in placements:
                    print(f"  - [ПРЕДУПРЕЖДЕНИЕ] Объект '{obj2_name}' из правила #{index+1} не найден в IFC.")
                    continue
                
                obj2 = placements[obj2_name]
                center1_x, center1_y = obj1['x'] + obj1['width']/2, obj1['y'] + obj1['depth']/2
                center2_x, center2_y = obj2['x'] + obj2['width']/2, obj2['y'] + obj2['depth']/2
                distance = math.sqrt((center1_x - center2_x)**2 + (center1_y - center2_y)**2)
                
                is_rule_passed = distance >= value
                rule_description += f" и '{obj2_name}' (>= {value:.2f}м)"
                actual_value_str = f"факт: {distance:.2f}м"

            elif rule_type in ['Выровнять по оси X', 'Выровнять по оси Y']:
                obj2_name = rule['Объект2'].strip()
                if obj2_name not in placements:
                    print(f"  - [ПРЕДУПРЕЖДЕНИЕ] Объект '{obj2_name}' из правила #{index+1} не найден в IFC.")
                    continue

                obj2 = placements[obj2_name]
                center1_x, center1_y = obj1['x'] + obj1['width']/2, obj1['y'] + obj1['depth']/2
                center2_x, center2_y = obj2['x'] + obj2['width']/2, obj2['y'] + obj2['depth']/2

                if rule_type == 'Выровнять по оси X':
                    is_rule_passed = math.isclose(center1_x, center2_x, abs_tol=0.001)
                    actual_value_str = f"центры: {center1_x:.3f}м и {center2_x:.3f}м"
                else: # 'Выровнять по оси Y'
                    is_rule_passed = math.isclose(center1_y, center2_y, abs_tol=0.001)
                    actual_value_str = f"центры: {center1_y:.3f}м и {center2_y:.3f}м"
                rule_description += f" и '{obj2_name}'"
            
            else:
                print(f"  - [НЕИЗВЕСТНО] Тип правила '{rule_type}' не поддерживается валидатором.")

        if is_rule_passed is not None:
            if is_rule_passed:
                print(f"  ✔ [ПРОШЛО] {rule_description}. {actual_value_str}")
                passed_rules += 1
            else:
                print(f"  ❌ [ПРОВАЛ] {rule_description}. {actual_value_str}")
                failed_rules += 1

    print("\n--- ВАЛИДАЦИЯ ЗАВЕРШЕНА ---")
    print(f"ИТОГ: Пройдено {passed_rules}, Провалено {failed_rules} из {len(rules_df)} правил.")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("\nОшибка: Неверное количество аргументов.")
        print("Пример запуска: python validate_layout.py <URL_Google_Таблицы> <путь_к_prototype.ifc>\n")
    else:
        google_sheet_url = sys.argv[1]
        ifc_file_path = sys.argv[2]
        
        rules = get_rules_from_google_sheet(google_sheet_url)
        if rules is not None:
            placements = extract_placements_from_ifc(ifc_file_path)
            if placements is not None:
                validate_layout(rules, placements)
