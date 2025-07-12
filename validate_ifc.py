import ifcopenshell
import pandas as pd
import sys
import math
import re
import unicodedata

def normalize_name(name: str) -> str:
    """Усиленная нормализация имен для гарантированного соответствия."""
    if not name:
        return ""
    
    name = ''.join(c for c in name if unicodedata.category(c) not in ('Cc', 'Cf', 'Cs', 'Co', 'Cn'))
    name = unicodedata.normalize('NFC', name)
    name = re.sub(r'\s+', ' ', name.strip())
    name = name.replace(' ', '_').lower()
    name = name.encode('ascii', 'ignore').decode('ascii')
    
    return name

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
    Рекурсивно вычисляет абсолютные координаты точки вставки объекта.
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
    Использует надежный метод поиска геометрии для предотвращения ошибок.
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
        
        # 1. Получаем координаты центральной точки вставки
        center_x, center_y, center_z = get_absolute_placement(element.ObjectPlacement)

        # 2. Надежно ищем геометрию, а не предполагаем ее структуру
        width, depth, height = 0, 0, 0
        found_geometry = False
        
        if not element.Representation:
            print(f"  > ПРЕДУПРЕЖДЕНИЕ: У объекта '{name}' отсутствует Representation.")
            continue

        for rep in element.Representation.Representations:
            if rep.RepresentationIdentifier == 'Body' and rep.is_a("IfcShapeRepresentation"):
                for item in rep.Items:
                    if item.is_a("IfcExtrudedAreaSolid"):
                        solid = item
                        profile = solid.SweptArea
                        if profile.is_a("IfcRectangleProfileDef"):
                            width = profile.XDim
                            depth = profile.YDim
                            height = solid.Depth
                            found_geometry = True
                            break
            if found_geometry:
                break
        
        if not found_geometry:
            print(f"  > ПРЕДУПРЕЖДЕНИЕ: Не удалось извлечь размеры для '{name}'. Пропускаем объект.")
            continue

        # 3. Вычисляем координаты нижнего левого угла (minX, minY)
        min_x = center_x - (width / 2)
        min_y = center_y - (depth / 2)

        rotation = 0.0
        if hasattr(element.ObjectPlacement, "RelativePlacement") and element.ObjectPlacement.RelativePlacement.RefDirection:
            dir_ratios = element.ObjectPlacement.RelativePlacement.RefDirection.DirectionRatios
            rotation = math.degrees(math.atan2(dir_ratios[1], dir_ratios[0]))

        placements[name] = {
            'minX': min_x, 'minY': min_y,
            'centerX': center_x, 'centerY': center_y,
            'width': width, 'depth': depth, 'height': height,
            'rotation_deg': rotation
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

    placements_norm = {normalize_name(n): data for n, data in placements.items()}
    passed_rules, failed_rules = 0, 0
    
    for index, rule in rules_df.iterrows():
        rule_type = rule['Тип правила'].strip()
        obj1_name_orig = rule['Объект1'].strip()
        obj2_name_orig = rule.get('Объект2', '').strip()
        value_str = str(rule['Значение']).strip()

        is_rule_passed = None
        actual_value_str = ""
        rule_description = f"Правило #{index+1}: '{rule_type}' для '{obj1_name_orig}'"

        # Правила, которые применяются ко всем объектам (зона/коридор)
        if rule_type == 'Запретная зона':
            try:
                zone_xmin, zone_ymin, zone_xmax, zone_ymax = map(float, value_str.split(','))
            except Exception:
                print(f"  - [ПРЕДУПРЕЖДЕНИЕ] Некорректное значение для '{rule_description}'. Ожидается 'Xmin,Ymin,Xmax,Ymax'.")
                continue
            
            violator = None
            for obj_name, obj in placements.items(): # Итерируем по всем найденным объектам
                obj_xmin, obj_ymin = obj['minX'], obj['minY']
                obj_xmax = obj_xmin + obj['width']
                obj_ymax = obj_ymin + obj['depth']

                if (obj_xmin < zone_xmax and obj_xmax > zone_xmin and
                    obj_ymin < zone_ymax and obj_ymax > zone_ymin):
                    violator = obj_name
                    break
            
            is_rule_passed = violator is None
            actual_value_str = f"объект '{violator}' пересекает зону" if violator else "зона свободна"
        
        elif rule_type == 'Коридор':
            try:
                x1, y1, x2, y2, width = map(float, value_str.split(','))
            except Exception:
                print(f"  - [ПРЕДУПРЕЖДЕНИЕ] Некорректное значение коридора в правиле #{index+1}.")
                continue

            cx_min = min(x1, x2) - width/2
            cx_max = max(x1, x2) + width/2
            cy_min = min(y1, y2) - width/2
            cy_max = max(y1, y2) + width/2

            violator = None
            for n, obj in placements.items(): # Итерируем по всем найденным объектам
                if (obj['minX'] < cx_max and obj['minX'] + obj['width'] > cx_min and
                    obj['minY'] < cy_max and obj['minY'] + obj['depth'] > cy_min):
                    violator = n
                    break

            is_rule_passed = violator is None
            actual_value_str = f"пересекает {violator}" if violator else "коридор свободен"

        # Правила, требующие поиска конкретных объектов
        else:
            obj1_key = normalize_name(obj1_name_orig)
            if obj1_key not in placements_norm:
                print(f"  - [ПРЕДУПРЕЖДЕНИЕ] Объект '{obj1_name_orig}' (нормал. {repr(obj1_key)}) из правила #{index+1} не найден в IFC.")
                continue

            obj1 = placements_norm[obj1_key]

            if rule_type == 'Мин. расстояние до':
                obj2_key = normalize_name(obj2_name_orig)
                value = float(value_str) if value_str else 0.0
                if obj2_key not in placements_norm:
                    print(f"  - [ПРЕДУПРЕЖДЕНИЕ] Объект '{obj2_name_orig}' (нормал. {repr(obj2_key)}) из правила #{index+1} не найден в IFC.")
                    continue

                obj2 = placements_norm[obj2_key]
                distance = math.sqrt((obj1['centerX'] - obj2['centerX'])**2 + (obj1['centerY'] - obj2['centerY'])**2)
                
                is_rule_passed = distance >= value
                rule_description += f" и '{obj2_name_orig}' (>= {value:.2f}м)"
                actual_value_str = f"факт: {distance:.2f}м"

            elif rule_type in ['Выровнять по оси X', 'Выровнять по оси Y']:
                obj2_key = normalize_name(obj2_name_orig)
                if obj2_key not in placements_norm:
                    print(f"  - [ПРЕДУПРЕЖДЕНИЕ] Объект '{obj2_name_orig}' (нормал. {repr(obj2_key)}) из правила #{index+1} не найден в IFC.")
                    continue

                obj2 = placements_norm[obj2_key]

                if rule_type == 'Выровнять по оси X':
                    is_rule_passed = math.isclose(obj1['centerX'], obj2['centerX'], abs_tol=0.001)
                    actual_value_str = f"центры: {obj1['centerX']:.3f}м и {obj2['centerX']:.3f}м"
                else:  # 'Выровнять по оси Y'
                    is_rule_passed = math.isclose(obj1['centerY'], obj2['centerY'], abs_tol=0.001)
                    actual_value_str = f"центры: {obj1['centerY']:.3f}м и {obj2['centerY']:.3f}м"
                rule_description += f" и '{obj2_name_orig}'"

            elif rule_type == 'Технологическая последовательность':
                obj2_key = normalize_name(obj2_name_orig)
                direction = rule.get('Направление', 'Y').strip()
                if obj2_key not in placements_norm:
                    print(f"  - [ПРЕДУПРЕЖДЕНИЕ] Объект '{obj2_name_orig}' (нормал. {repr(obj2_key)}) из правила #{index+1} не найден в IFC.")
                    continue
                obj2 = placements_norm[obj2_key]
                gap = 2.0
                if direction == 'Y':
                    is_rule_passed = obj1['minY'] + obj1['depth'] <= obj2['minY'] - gap + 0.001
                    actual_value_str = f"Y1_end={obj1['minY'] + obj1['depth']:.2f}, Y2_start={obj2['minY']:.2f}"
                else:
                    is_rule_passed = obj1['minX'] + obj1['width'] <= obj2['minX'] - gap + 0.001
                    actual_value_str = f"X1_end={obj1['minX'] + obj1['width']:.2f}, X2_start={obj2['minX']:.2f}"
                rule_description += f" -> '{obj2_name_orig}'"

            elif rule_type == 'Производственная зона':
                try:
                    x_min, y_min, x_max, y_max = map(float, value_str.split(','))
                except Exception:
                    print(f"  - [ПРЕДУПРЕЖДЕНИЕ] Некорректное значение зоны для '{obj1_name_orig}'.")
                    continue

                is_rule_passed = (obj1['minX'] >= x_min - 0.001 and obj1['minY'] >= y_min - 0.001 and
                                   obj1['minX'] + obj1['width'] <= x_max + 0.001 and
                                   obj1['minY'] + obj1['depth'] <= y_max + 0.001)
                actual_value_str = f"границы объекта в зоне [{x_min},{y_min},{x_max},{y_max}]"

            elif rule_type == 'Параллельная линия':
                obj2_key = normalize_name(obj2_name_orig)
                offset = float(value_str) if value_str else 0.0
                if obj2_key not in placements_norm:
                    print(f"  - [ПРЕДУПРЕЖДЕНИЕ] Объект '{obj2_name_orig}' (нормал. {repr(obj2_key)}) из правила #{index+1} не найден в IFC.")
                    continue

                obj2 = placements_norm[obj2_key]
                expected = obj1['centerX'] + offset
                is_rule_passed = math.isclose(obj2['centerX'], expected, abs_tol=0.001)
                actual_value_str = f"X2={obj2['centerX']:.2f}, ожидалось {expected:.2f}"
                rule_description += f" и '{obj2_name_orig}'"

            elif rule_type == 'Ориентация':
                try:
                    expected_angle = float(value_str)
                except Exception:
                    print(f"  - [ПРЕДУПРЕЖДЕНИЕ] Некорректное значение ориентации в правиле #{index+1}.")
                    continue
                actual = obj1.get('rotation_deg', 0.0)
                # Нормализация угла к диапазону -180 до 180, чтобы правильно сравнить
                diff = abs( (actual - expected_angle + 180) % 360 - 180 )
                is_rule_passed = diff <= 0.5 # Допуск 0.5 градуса
                actual_value_str = f"угол {actual:.1f}°"

            elif rule_type == 'Привязка к стене':
                try:
                    side, dist_str = value_str.split(',')
                    dist = float(dist_str)
                except Exception:
                    print(f"  - [ПРЕДУПРЕЖДЕНИЕ] Некорректное значение привязки к стене для '{obj1_name_orig}'.")
                    continue
                
                wall_thickness_val = 0.2 # Жестко заданный, как в layout_solver.py
                
                if side == 'Xmin':
                    expected_x = dist + wall_thickness_val
                    is_rule_passed = math.isclose(obj1['minX'], expected_x, abs_tol=0.001)
                    actual_value_str = f"X_min={obj1['minX']:.3f}м, ожидалось {expected_x:.3f}м"
                elif side == 'Xmax':
                    expected_x = 120.0 - wall_thickness_val - dist - obj1['width'] # room_width - wall - dist - obj_width
                    is_rule_passed = math.isclose(obj1['minX'], expected_x, abs_tol=0.001)
                    actual_value_str = f"X_min={obj1['minX']:.3f}м, ожидалось {expected_x:.3f}м"
                elif side == 'Ymin':
                    expected_y = dist + wall_thickness_val
                    is_rule_passed = math.isclose(obj1['minY'], expected_y, abs_tol=0.001)
                    actual_value_str = f"Y_min={obj1['minY']:.3f}м, ожидалось {expected_y:.3f}м"
                elif side == 'Ymax':
                    expected_y = 80.0 - wall_thickness_val - dist - obj1['depth'] # room_depth - wall - dist - obj_depth
                    is_rule_passed = math.isclose(obj1['minY'], expected_y, abs_tol=0.001)
                    actual_value_str = f"Y_min={obj1['minY']:.3f}м, ожидалось {expected_y:.3f}м"
                else:
                    print(f"  - [ПРЕДУПРЕЖДЕНИЕ] Неизвестная сторона привязки к стене '{side}' для '{obj1_name_orig}'.")
                    continue
                rule_description += f" к стене {side} отступ {dist}м"
            
            elif rule_type == 'Зона обслуживания':
                try:
                    margin = float(value_str)
                except Exception:
                    print(f"  - [ПРЕДУПРЕЖДЕНИЕ] Некорректное значение зоны обслуживания для '{obj1_name_orig}'.")
                    continue
                
                violator = None
                for other_name, other_obj in placements.items():
                    if normalize_name(other_name) == obj1_key:
                        continue # Пропускаем сам объект
                    
                    # Проверяем расстояние от центра obj1 до границ других объектов
                    # Для упрощения пока проверяем, что центры других объектов вне радиуса margin от центра obj1
                    distance_centers = math.sqrt((obj1['centerX'] - other_obj['centerX'])**2 + (obj1['centerY'] - other_obj['centerY'])**2)
                    
                    if distance_centers < margin - 0.001: # Если расстояние меньше требуемого
                        violator = other_name
                        break
                
                is_rule_passed = violator is None
                actual_value_str = f"пересекает {violator}" if violator else "зона обслуживания свободна"
                rule_description += f" радиус {margin}м"

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
        print("\nОшибка: Неверное количество аргументов.\nПример запуска: python validate_ifc.py <URL_Google_Таблицы> <путь_к_prototype.ifc>\n")
    else:
        google_sheet_url = sys.argv[1]
        ifc_file_path = sys.argv[2]
        
        rules = get_rules_from_google_sheet(google_sheet_url)
        if rules is not None:
            placements = extract_placements_from_ifc(ifc_file_path)
            if placements is not None:
                validate_layout(rules, placements)
