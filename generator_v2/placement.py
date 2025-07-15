def calculate_placements(equipment_list: list, rules: list) -> dict:
    """
    Вычисляет финальное положение (координаты, поворот) для каждого объекта.
    Возвращает словарь, где ключ - id объекта, а значение - его положение.
    """
    print("3. Расчет положений оборудования...")
    
    placements = {} # Здесь будем хранить результат: { "id": {"x":, "y":, "rot":} }
    equipment_map = {eq['id']: eq for eq in equipment_list}

    # Сначала обрабатываем простые правила, чтобы знать положение "якорей"
    rules.sort(key=lambda r: 0 if r['type'] == 'PLACE_AT' else 1)

    for rule in rules:
        rule_type = rule.get('type')
        target_id = rule.get('target')
        params = rule.get('params', {})

        if target_id not in equipment_map:
            print(f"  > ПРЕДУПРЕЖДЕНИЕ: Объект '{target_id}' из правила не найден в списке оборудования.")
            continue

        if rule_type == 'PLACE_AT':
            pos = params.get('position', [0, 0])
            rot = params.get('rotation_deg', 0)
            placements[target_id] = {'x': pos[0], 'y': pos[1], 'rotation_deg': rot}
            print(f"  - Правило PLACE_AT для '{target_id}': позиция [{pos[0]}, {pos[1]}]")

        elif rule_type == 'PLACE_AFTER':
            anchor_id = params.get('anchor')
            if not anchor_id or anchor_id not in placements:
                print(f"  > ОШИБКА: Якорь '{anchor_id}' для правила PLACE_AFTER еще не размещен. Проверьте порядок правил.")
                continue

            anchor_placement = placements[anchor_id]
            anchor_equipment = equipment_map[anchor_id]
            target_equipment = equipment_map[target_id]
            
            direction = params.get('direction', 'Y')
            distance = params.get('distance', 1.0)
            alignment = params.get('alignment', 'center')

            # Координаты центра якоря
            anchor_cx = anchor_placement['x'] + anchor_equipment['footprint']['width'] / 2
            anchor_cy = anchor_placement['y'] + anchor_equipment['footprint']['depth'] / 2
            
            # Рассчитываем положение нового объекта
            new_x, new_y = 0, 0
            if direction == 'Y':
                new_y = anchor_placement['y'] + anchor_equipment['footprint']['depth'] + distance
                if alignment == 'center':
                    new_x = anchor_cx - (target_equipment['footprint']['width'] / 2)
                # TODO: Добавить другие типы выравнивания (left, right)
            elif direction == 'X':
                new_x = anchor_placement['x'] + anchor_equipment['footprint']['width'] + distance
                if alignment == 'center':
                    new_y = anchor_cy - (target_equipment['footprint']['depth'] / 2)
                # TODO: Добавить другие типы выравнивания (top, bottom)

            rot = params.get('rotation_deg', 0)
            placements[target_id] = {'x': new_x, 'y': new_y, 'rotation_deg': rot}
            print(f"  - Правило PLACE_AFTER для '{target_id}': позиция [{new_x:.2f}, {new_y:.2f}]")

    print("   Расчет положений завершен.")
    return placements
