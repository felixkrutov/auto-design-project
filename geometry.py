import ifcopenshell
import ifcopenshell.api
import ifcopenshell.guid
import ifcopenshell.geom
import time
import logging

# Попытка импортировать pythonOCC. Если недоступно, будет использоваться упрощенная геометрия.
try:
    from OCC.Core.gp import gp_Pnt, gp_Dir, gp_Ax2
    from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeCone
    OCC_AVAILABLE = True
except ImportError:
    logging.warning("pythonOCC не найдена. Сложная геометрия для силосов будет заменена на простые параллелепипеды.")
    OCC_AVAILABLE = False

# --- НОВЫЕ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ СТИЛЕЙ И ГЕОМЕТРИИ ---

def create_surface_style(f, name, r, g, b, transparency=0.0):
    """
    Создает и возвращает IfcSurfaceStyle с использованием прямого создания сущностей.
    Это более гибко для применения к разным частям одной модели.
    """
    rendering = f.create_entity(
        "IfcSurfaceStyleRendering",
        SurfaceColour=f.createIfcColourRgb(None, r, g, b),
        Transparency=transparency,
    )
    style = f.create_entity(
        "IfcSurfaceStyle", Name=name, Side="BOTH", Styles=[rendering]
    )
    return style

def apply_style_to_representation(f, representation, style):
    """
    Применяет стиль к элементам представления формы (IfcShapeRepresentation).
    """
    if not style or not representation or not representation.Items:
        return
        
    f.create_entity(
        "IfcStyledItem",
        Item=representation.Items[0],
        Styles=[f.create_entity("IfcPresentationStyleAssignment", Styles=[style])],
    )

# --- ОБНОВЛЕННАЯ ФУНКЦИЯ CREATE_ELEMENT ---

def create_element(f, context, name, placement, w, d, h, style=None):
    """
    Создает IFC-элемент. 
    Если имя содержит "Силос" и pythonOCC доступен, создает сложную геометрию.
    В противном случае создает простую экструдированную форму (параллелепипед).
    """
    owner_history = f.by_type("IfcOwnerHistory")[0]
    
    # Логика для создания сложной геометрии Силоса
    if "силос" in name.lower() and OCC_AVAILABLE:
        product = f.createIfcBuildingElementProxy(ifcopenshell.guid.new(), owner_history, name, None, None, placement, None, None)
        
        # Параметры геометрии
        radius = min(w, d) / 2.0
        cylinder_height = h * 0.8
        cone_height = h * 0.2
        base_platform_height = 0.15 # Небольшая бетонная база

        representations = []
        settings = ifcopenshell.geom.settings()
        settings.set(settings.STRICT_TOLERANCE, True)

        # 1. Тело силоса (цилиндр)
        # Цилиндр размещается над конусом и платформой
        cyl_axis = gp_Ax2(gp_Pnt(0.0, 0.0, cone_height), gp_Dir(0.0, 0.0, 1.0))
        occ_cylinder = BRepPrimAPI_MakeCylinder(cyl_axis, radius, cylinder_height).Shape()
        ifc_cyl_geom = ifcopenshell.geom.create_shape(f, occ_cylinder, settings).geometry
        
        cyl_rep = f.createIfcShapeRepresentation(
            ContextOfItems=context, RepresentationIdentifier="Body", RepresentationType="Brep", Items=ifc_cyl_geom
        )
        silo_body_style = create_surface_style(f, "Silo Body", 0.8, 0.82, 0.84)
        apply_style_to_representation(f, cyl_rep, silo_body_style)
        representations.append(cyl_rep)

        # 2. Бункер силоса (конус)
        cone_axis = gp_Ax2(gp_Pnt(0.0, 0.0, 0.0), gp_Dir(0.0, 0.0, 1.0))
        occ_cone = BRepPrimAPI_MakeCone(cone_axis, radius, 0.0, cone_height).Shape()
        ifc_cone_geom = ifcopenshell.geom.create_shape(f, occ_cone, settings).geometry

        cone_rep = f.createIfcShapeRepresentation(
            ContextOfItems=context, RepresentationIdentifier="Hopper", RepresentationType="Brep", Items=ifc_cone_geom
        )
        hopper_style = create_surface_style(f, "Silo Hopper", 0.5, 0.5, 0.5)
        apply_style_to_representation(f, cone_rep, hopper_style)
        representations.append(cone_rep)
        
        # 3. Базовая платформа (экструзия)
        # Платформа находится под конусом, от -base_platform_height до 0
        base_profile = f.createIfcRectangleProfileDef('AREA', "Base_Profile", None, w, d)
        # Позиционируем профиль ниже нуля, чтобы экструзия шла вверх до нуля
        base_pos = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, -base_platform_height)))
        base_extrusion = f.createIfcExtrudedAreaSolid(
            SweptArea=base_profile, 
            Position=base_pos, 
            ExtrudedDirection=f.createIfcDirection((0.0, 0.0, 1.0)), 
            Depth=base_platform_height
        )
        base_rep = f.createIfcShapeRepresentation(
            ContextOfItems=context, RepresentationIdentifier="Base", RepresentationType="SweptSolid", Items=[base_extrusion]
        )
        base_style = create_surface_style(f, "Concrete Base", 0.6, 0.6, 0.6)
        apply_style_to_representation(f, base_rep, base_style)
        representations.append(base_rep)

        # Собираем все представления в один продукт
        product.Representation = f.createIfcProductDefinitionShape(None, None, representations)
        return product

    # Резервная логика для другого оборудования или если pythonOCC недоступен
    else:
        profile = f.createIfcRectangleProfileDef('AREA', name + "_profile", None, w, d)
        extrusion_placement = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)))
        extrusion_direction = f.createIfcDirection((0.0, 0.0, 1.0))
        extrusion = f.createIfcExtrudedAreaSolid(profile, extrusion_placement, extrusion_direction, h)
        
        shape_rep = f.createIfcShapeRepresentation(context, 'Body', 'SweptSolid', [extrusion])
        product_shape = f.createIfcProductDefinitionShape(None, None, [shape_rep])

        element_type = name.split('_')[0]
        if "Стена" in element_type:
            element = f.createIfcWall(ifcopenshell.guid.new(), owner_history, name, None, None, placement, product_shape, None)
        elif "Пол" in element_type:
            element = f.createIfcSlab(ifcopenshell.guid.new(), owner_history, name, None, None, placement, product_shape, None, 'FLOOR')
        else:
            element = f.createIfcBuildingElementProxy(ifcopenshell.guid.new(), owner_history, name, None, None, placement, product_shape, None)

        if style:
            # Применяем стиль ко всему элементу
            apply_style_to_representation(f, shape_rep, style)
        
        return element


def create_3d_model(project_data: dict, placements: dict, output_filename: str):
    print("\n5. Создание 3D модели (IFC)...")
    
    f = ifcopenshell.file(schema="IFC4")
    
    person = f.createIfcPerson(None, "Automation", None, None, None, None, None, None) 
    organization = f.createIfcOrganization(None, "AutoDesign Inc.", None, None, None)
    application = f.createIfcApplication(organization, "0.8.0", "AI Factory Designer", "IfcOpenShell")
    
    current_timestamp = int(time.time()) 
    owner_history = f.createIfcOwnerHistory(person, application, None, 'ADDED', current_timestamp, None, None, current_timestamp)
    
    project = f.createIfcProject(ifcopenshell.guid.new(), owner_history, project_data['meta']['project_name'])
    
    context = ifcopenshell.api.run("context.add_context", f, 
                                   context_type="Model", 
                                   target_view="MODEL_VIEW", 
                                   context_identifier="Body")

    ifcopenshell.api.run("unit.assign_unit", f)
    project.RepresentationContexts = [context]
    
    site = f.createIfcSite(ifcopenshell.guid.new(), owner_history, "Участок")
    building = f.createIfcBuilding(ifcopenshell.guid.new(), owner_history, "Производственный корпус")
    storey = f.createIfcBuildingStorey(ifcopenshell.guid.new(), owner_history, "Первый этаж")
    ifcopenshell.api.run("aggregate.assign_object", f, relating_object=project, products=[site])
    ifcopenshell.api.run("aggregate.assign_object", f, relating_object=site, products=[building])
    ifcopenshell.api.run("aggregate.assign_object", f, relating_object=building, products=[storey])

    def P(x, y, z):
        return f.createIfcCartesianPoint((float(x), float(y), float(z)))

    print("   - Создание стилей материалов...")
    # Используем новую, более гибкую функцию создания стилей
    styles_map = {
        "floor_style": create_surface_style(f, "FloorStyle", 0.4, 0.4, 0.8),
        "wall_style": create_surface_style(f, "WallStyle", 0.7, 0.7, 0.7),
        "mixer_style": create_surface_style(f, "MixerStyle", 0.9, 0.9, 0.6),
        "press_style": create_surface_style(f, "PressStyle", 0.6, 0.9, 0.6),
        "default_style": create_surface_style(f, "DefaultStyle", 0.9, 0.5, 0.5)
        # Стиль для силоса больше не нужен здесь, т.к. он создается внутри create_element
    }
    
    all_elements = []
    print("   - Создание архитектуры (пол, стены)...")
    arch_data = project_data.get('architecture', {})
    room_dims = arch_data.get('room_dimensions', {})
    wall_t = arch_data.get('wall_thickness', 0.2)
    w, d, h = room_dims.get('width'), room_dims.get('depth'), room_dims.get('height')

    if all([w, d, h]):
        floor_pos = P(0.0, 0.0, 0.0)
        floor_placement = f.createIfcLocalPlacement(storey.ObjectPlacement, f.createIfcAxis2Placement3D(floor_pos))
        floor = create_element(f, context, "Пол", floor_placement, w, d, -wall_t, style=styles_map["floor_style"])
        all_elements.append(floor)
        
        walls_def = [
            {'name': 'Стена_Юг', 'pos': P(0.0, 0.0, 0.0), 'dims': (w, wall_t, h)},
            {'name': 'Стена_Север', 'pos': P(0.0, d - wall_t, 0.0), 'dims': (w, wall_t, h)},
            {'name': 'Стена_Запад', 'pos': P(0.0, 0.0, 0.0), 'dims': (wall_t, d, h)},
            {'name': 'Стена_Восток', 'pos': P(w - wall_t, 0.0, 0.0), 'dims': (wall_t, d, h)}
        ]
        for w_def in walls_def:
            wall_placement = f.createIfcLocalPlacement(storey.ObjectPlacement, f.createIfcAxis2Placement3D(w_def['pos']))
            wall = create_element(f, context, w_def['name'], wall_placement, *w_def['dims'], style=styles_map["wall_style"])
            all_elements.append(wall)

    print("   - Размещение оборудования...")
    equipment_map = {eq['id']: eq for eq in project_data['equipment']}
    for eq_id, placement in placements.items():
        eq_data = equipment_map.get(eq_id)
        if not eq_data: continue

        eq_w, eq_d, eq_h = eq_data['footprint']['width'], eq_data['footprint']['depth'], eq_data['height']
        # Размещение оборудования на уровне чистого пола (Z=0)
        pos = P(float(placement['x']), float(placement['y']), 0.0)
        
        eq_placement = f.createIfcLocalPlacement(storey.ObjectPlacement, f.createIfcAxis2Placement3D(pos))
        
        eq_style = None
        eq_name_lower = eq_data['name'].lower()
        if "силос" not in eq_name_lower: # Для силосов стили назначаются внутри create_element
            if "смеситель" in eq_name_lower: eq_style = styles_map["mixer_style"]
            elif "пресс" in eq_name_lower: eq_style = styles_map["press_style"]
            else: eq_style = styles_map["default_style"]

        element = create_element(f, context, eq_data['name'], eq_placement, eq_w, eq_d, eq_h, style=eq_style)
        all_elements.append(element)
        print(f"     - Создан объект: '{eq_data['name']}'")

    if all_elements:
        ifcopenshell.api.run("spatial.assign_container", f, products=all_elements, relating_structure=storey)

    f.write(output_filename)
    print(f"   > Модель успешно сохранена в файл: {output_filename}")
