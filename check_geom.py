import ifcopenshell
import ifcopenshell.geom
import numpy as np
import sys

IFC_FILE = "prototype.ifc"

print(f"\n--- ЗАПУСК ЧИСТОГО ТЕСТА ГЕОМЕТРИИ ДЛЯ ФАЙЛА '{IFC_FILE}' ---")

try:
    ifc_file = ifcopenshell.open(IFC_FILE)
    print(f"1. Файл '{IFC_FILE}' успешно открыт.")
    
    elements = ifc_file.by_type('IfcBuildingElementProxy')
    if not elements:
        print("ОШИБКА: В файле не найдено ни одного объекта IfcBuildingElementProxy.")
        sys.exit()
        
    element = elements[0]
    print(f"2. Выбран тестовый объект: '{element.Name}' (GUID: {element.GlobalId})")
    
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    print("3. Настройки движка установлены (USE_WORLD_COORDS = True).")
    
    print("4. Вызов ifcopenshell.geom.create_shape...")
    shape = ifcopenshell.geom.create_shape(settings, element)
    
    matrix = np.array(shape.transformation.matrix).reshape((4, 4))
    coords = matrix[:3, 3]
    
    print("\n--- РЕЗУЛЬТАТ ТЕСТА ---")
    print(f"  > Имя объекта: {element.Name}")
    print(f"  > Извлеченные координаты (X, Y, Z): ({coords[0]:.2f}, {coords[1]:.2f}, {coords[2]:.2f})")
    print("-----------------------\n")
    
    if abs(coords[0]) < 1e-6 and abs(coords[1]) < 1e-6:
        print("❌ ВЕРДИКТ: ТЕСТ ПРОВАЛЕН. Геометрический движок возвращает нулевые координаты.")
        print("   Это подтверждает, что проблема в библиотеке ifcopenshell, а не в нашем коде.")
    else:
        print("✅ ВЕРДИКТ: ТЕСТ ПРОЙДЕН. Движок вернул ненулевые координаты.")
        print("   Это означает, что проблема была в сложной логике предыдущих скриптов.")

except Exception as e:
    print(f"\nКРИТИЧЕСКАЯ ОШИБКА ВО ВРЕМЯ ТЕСТА: {e}")
