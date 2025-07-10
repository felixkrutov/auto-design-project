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
    Рекурсивно вычисляет абсолютные координаты объекта,
    проходя по всей вложенной иерархии IfcLocalPlacement.
    """
    x, y, z = 0, 0, 0
    if ifc_placement.PlacementRelTo:
        # Рекурсивно получаем координаты родительского элемента
        parent_x, parent_y, parent_z = get_absolute_placement(ifc_placement.PlacementRelTo)
        x += parent_x
        y += parent_y
        z += parent_z

    # Добавляем смещение текущего элемента
    relative_coords = ifc_placement.RelativePlacement.Location.Coordinates
    x += relative_coords[0]
    y += relative_coords[1]
    z += relative_coords[2]
    
    return x, y, z

def extract_placements_from_ifc(ifc_filename):
    """
    Извлекает фактическое положение и размеры объектов из IFC файла,
    напрямую читая данные о размещении (без ifcopenshell.geom).
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
        
        # Извлечение координат через иерархию размещений
        abs_x, abs_y, _ = get_absolute_placement(element.ObjectPlacement)

        # Извлечение размеров из геометрии
        width, depth = 0, 0
        try:
            shape = element.Representation.Representations[0]
            solid = shape.Items[0]
            profile = solid.SweptArea
            width = profile.XDim
            depth = profile.YDim
        except (AttributeError, IndexError):
            print(f"  > ПРЕДУПРЕЖДЕНИЕ: Не удалось извлечь размеры для '{name}'.")
            continue

        placements[name] = {
            'x': abs_x,
            'y': abs_y,
            'width': width,
            'depth': depth
        }
        
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

    total_rules = len(rules_df)
    passed_rules = 0
    
    for index, rule in rules_df.iterrows():
        rule_type = rule['Тип правила']
        obj1_name = rule['Объект1']
        value_str = str(rule['Значение']).strip()

        # Для правил, связанных с конкретным объектом, проверяем его наличие
        if rule_type != 'Запретная зона' and obj1_name not in placements:
            print(f"  - [ПРЕДУПРЕЖДЕНИЕ] Объект '{obj1_name}' из правила не найден в IFC файле.")
            continue

        check_passed = False
        actual_value_str = ""

        if rule_type == 'Запретная зона':
            try:
                zone_xmin, zone_ymin, zone_xmax, zone_ymax = map(float, value_str.split(','))
            except Exception:
                print(f"  - [ПРЕДУПРЕЖДЕНИЕ] Некорректное значение запретной зоны '{obj1_name}'. Ожидается 'Xmin,Ymin,Xmax,Ymax'.")
                continue

            violation_found = False
            for obj_name, obj in placements.items():
                obj_xmin, obj_ymin = obj['x'], obj['y']
                obj_xmax = obj_xmin + obj['width']
                obj_ymax = obj_ymin + obj['depth']

                if (obj_xmin < zone_xmax and obj_xmax > zone_xmin and
                        obj_ymin < zone_ymax and obj_ymax > zone_ymin):
                    print(f"  ❌ [ПРОВАЛ] Правило #{index+1}: Объект '{obj_name}' пересекает запретную зону '{obj1_name}'.")
                    violation_found = True

            if not violation_found:
                passed_rules += 1
                print(f"  ✔ [ПРОШЛО] Правило #{index+1}: Запретная зона '{obj1_name}' свободна.")
            continue

        obj1 = placements[obj1_name]
        value = float(value_str) if value_str else 0.0

        if rule_type == 'Мин. отступ от стены X0':
            check_passed = obj1['x'] >= value
            actual_value_str = f"факт: {obj1['x']:.2f}м"
            
        elif rule_type == 'Мин. отступ от стены Y0':
            check_passed = obj1['y'] >= value
            actual_value_str = f"факт: {obj1['y']:.2f}м"

        elif rule_type == 'Мин. расстояние до':
            obj2_name = rule['Объект2']
            if obj2_name not in placements:
                print(f"  - [ПРЕДУПРЕЖДЕНИЕ] Объект '{obj2_name}' из правила не найден в IFC файле.")
                continue
            
            obj2 = placements[obj2_name]
            # Расстояние между центрами объектов
            center1_x, center1_y = obj1['x'] + obj1['width']/2, obj1['y'] + obj1['depth']/2
            center2_x, center2_y = obj2['x'] + obj2['width']/2, obj2['y'] + obj2['depth']/2
            
            distance = math.sqrt((center1_x - center2_x)**2 + (center1_y - center2_y)**2)
            check_passed = distance >= value
            actual_value_str = f"факт: {distance:.2f}м"
        
        else:
            print(f"  - [НЕИЗВЕСТНО] Правило типа '{rule_type}' не поддерживается валидатором.")
            continue

        if check_passed:
            passed_rules += 1
            print(f"  ✔ [ПРОШЛО] Правило #{index+1}: '{rule_type}' для '{obj1_name}' (>= {value}м). {actual_value_str}")
        else:
            print(f"  ❌ [ПРОВАЛ] Правило #{index+1}: '{rule_type}' для '{obj1_name}' (>= {value}м). {actual_value_str}")

    print("\n--- ВАЛИДАЦИЯ ЗАВЕРШЕНА ---")
    print(f"ИТОГ: Пройдено {passed_rules} из {total_rules} правил.")


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
