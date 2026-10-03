# ABOUTME: Builds the map prop archives: models, model sets, texture sets, animations, and the per-model tables.
# ABOUTME: The per-model tables (animation lists, material/shape draw lists) follow map_prop_models.order.

subdir('animations')
subdir('models')
subdir('model_sets')
subdir('texture_sets')

prop_tables = custom_target('prop_tables',
    output: [
        'prop_animation_lists.narc',
        'prop_material_shapes.bin',
    ],
    input: [
        files('animations/prop_animation_lists.json'),
        files('models/draw_order_overrides.json'),
        files('models/map_prop_models.order'),
        files('animations/prop_animations.order'),
        map_prop_model_srcs,
    ],
    command: [
        make_prop_tables_py,
        '--nitroarc', nitroarc_exe,
        '--staging', '@PRIVATE_DIR@',
        '--animation-lists-output', '@OUTPUT0@',
        '--material-shapes-output', '@OUTPUT1@',
        '--animation-lists', '@INPUT0@',
        '--draw-order', '@INPUT1@',
        '--models-order', '@INPUT2@',
        '--animations-order', '@INPUT3@',
        map_prop_model_srcs,
    ],
)

nitrofs_files += prop_tables
