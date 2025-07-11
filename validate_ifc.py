import ifcopenshell
import pandas as pd
import sys
import math

def get_rules_from_google_sheet(sheet_url):
    """Загружает и парсит правила из общедоступной Google Таблицы."""
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
    """Рекурсивно вычисляет абсолютные координаты точки вставки объекта."""
    x, y, z = 0, 0, 0
    if ifc_placement.PlacementRelTo:
        parent_x, parent_y, parent_z = get_absolute_placement(ifc_placement.PlacementRelTo)
        x, y, z = x + parent_x, y + parent_y, z + parent_z
    relative_coords = ifc_placement.RelativePlacement.Location.Coordinates
    x, y, z = x + relative_coords[0], y + relative_coords[1], z + relative_coords[2]
    return x, y, z

def extract_placements_from_ifc(ifc_filename):
    """Извлекает фактическое положение и размеры объектов из IFC файла."""
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
        center_x, center_y, _ = get_absolute_placement(element.ObjectPlacement)
        width, depth, height = 0, 0, 0
        found_geometry = False
        if element.Representation:
            for rep in element.Representation.Representations:
                if rep.RepresentationIdentifier == 'Body' and rep.is_a("IfcShapeRepresentation"):
                    for item in rep.Items:
                        if item.is_a("IfcExtrudedAreaSolid"):
                            solid, profile = item, item.SweptArea
                            if profile.is_a("IfcRectangleProfileDef"):
                                width, depth, height = profile.XDim, profile.YDim, solid.Depth
                                found_geometry = True
                                break
            if found_geometry: break
        if not found_geometry:
            print(f"  > ПРЕДУПРЕЖДЕНИЕ: Не удалось извлечь размеры для '{name}'.")
            continue
        min_x, min_y = center_x - (width / 2), center_y - (depth / 2)
        placements[name] = {
            'minX': min_x, 'minY': min_y, 'maxX': min_x + width, 'maxY': min_y + depth,
            'centerX': center_x, 'centerY': center_y,
            'width': width, 'depth': depth, 'height': height
        }
    print(f"  > Найдено и обработано {len(placements)} объектов.")
    return placements

def validate_layout(rules_df, placements):
    """Проверяет соответствие фактических размещений заданным правилам."""
    print("3. Запуск проверки правил...")
    if not placements:
        print("  > ОШИБКА: Нет данных о размещениях для проверки.")
        return

    passed_rules, failed_rules = 0, 0
    for index, rule in rules_df.iterrows():
        rule_type = rule['Тип правила'].strip()
        obj1_name = rule['Объект1'].strip()
        obj2_name = str(rule['Объект2']).strip()
        value_str = str(rule['Значение']).strip()

        is_rule_passed = None
        actual_value_str = ""
        rule_description = f"Правило #{index+1}: '{rule_type}' для '{obj1_name}'"

        if rule_type == 'Запретная зона':
            try:
                zone_xmin, zone_ymin, zone_xmax, zone_ymax = map(float, value_str.split(','))
                violator = None
                for obj_name, obj in placements.items():
                    if (obj['minX'] < zone_xmax and obj['maxX'] > zone_xmin and
                        obj['minY'] < zone_ymax and obj['maxY'] > zone_ymin):
                        violator = obj_name
                        break
                is_rule_passed = violator is None
                actual_value_str = f"объект '{violator}' пересекает зону" if violator else "зона свободна"
            except Exception:
                print(f"  - [ПРЕДУПРЕЖДЕНИЕ] Некорректное значение для '{rule_description}'.")
                continue
        else:
            if obj1_name not in placements:
                print(f"  - [ПРЕДУПРЕЖДЕНИЕ] Объект '{obj1_name}' из правила #{index+1} не найден в IFC.")
                continue
            obj1 = placements[obj1_name]

            if rule_type == 'Разместить в зоне':
                try:
                    zone_xmin, zone_ymin, zone_xmax, zone_ymax = map(float, value_str.split(','))
                    is_rule_passed = (obj1['minX'] >= zone_xmin and obj1['maxX'] <= zone_xmax and
                                      obj1['minY'] >= zone_ymin and obj1['maxY'] <= zone_ymax)
                    actual_value_str = f"факт: в зоне [{obj1['minX']:.2f},{obj1['minY']:.2f}]-[{obj1['maxX']:.2f},{obj1['maxY']:.2f}]"
                except Exception:
                     print(f"  - [ПРЕДУПРЕЖДЕНИЕ] Некорректное значение для '{rule_description}'.")
                     continue

            elif rule_type == 'Следует за (Y)' or rule_type == 'Следует за (X)':
                if obj2_name not in placements:
                    print(f"  - [ПРЕДУПРЕЖДЕНИЕ] Объект '{obj2_name}' из правила #{index+1} не найден в IFC.")
                    continue
                obj2 = placements[obj2_name]
                gap = float(value_str)
                rule_description += f" и '{obj2_name}' (зазор >={gap}м)"
                if rule_type == 'Следует за (Y)':
                    actual_gap = obj2['minY'] - obj1['maxY']
                    is_rule_passed = actual_gap >= gap
                    actual_value_str = f"факт. зазор: {actual_gap:.2f}м"
                else: # Следует за (X)
                    actual_gap = obj2['minX'] - obj1['maxX']
                    is_rule_passed = actual_gap >= gap
                    actual_value_str = f"факт. зазор: {actual_gap:.2f}м"

            elif rule_type == 'Выровнять по оси X' or rule_type == 'Выровнять по оси Y':
                if obj2_name not in placements:
                    print(f"  - [ПРЕДУПРЕЖДЕНИЕ] Объект '{obj2_name}' из правила #{index+1} не найден в IFC.")
                    continue
                obj2 = placements[obj2_name]
                rule_description += f" и '{obj2_name}'"
                if rule_type == 'Выровнять по оси X':
                    is_rule_passed = math.isclose(obj1['centerX'], obj2['centerX'], abs_tol=0.001)
                    actual_value_str = f"центры X: {obj1['centerX']:.3f}м и {obj2['centerX']:.3f}м"
                else: # Выровнять по оси Y
                    is_rule_passed = math.isclose(obj1['centerY'], obj2['centerY'], abs_tol=0.001)
                    actual_value_str = f"центры Y: {obj1['centerY']:.3f}м и {obj2['centerY']:.3f}м"
            else:
                print(f"  - [НЕИЗВЕСТНО] Тип правила '{rule_type}' не поддерживается.")

        if is_rule_passed is not None:
            if is_rule_passed:
                print(f"  ✔ [ПРОШЛО] {rule_description}. {actual_value_str}")
                passed_rules += 1
            else:
                print(f"  ❌ [ПРОВАЛ] {rule_description}. {actual_value_str}")
                failed_rules += 1

    print("\n--- ВАЛИДАЦИЯ ЗАВЕРШЕНА ---")
    print(f"ИТОГ: Пройдено {passed_rules}, Провалено {failed_rules} из {rules_df.shape[0]} правил.")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("\nОшибка: Неверное количество аргументов.")
        print("Пример запуска: python validate_ifc.py <URL_Google_Таблицы> <путь_к_prototype.ifc>\n")
    else:
        google_sheet_url = sys.argv[1]
        ifc_file_path = sys.argv[2]
        rules = get_rules_from_google_sheet(google_sheet_url)
        if rules is not None:
            placements = extract_placements_from_ifc(ifc_file_path)
            if placements is not None:
                validate_layout(rules, placements)
