#-------------------------------------------------------------------------------
#   gen_java.py
#
#   Generate Java 22+ Panama FFM bindings for Sokol.
#-------------------------------------------------------------------------------
import gen_ir
import gen_util as util
import os, shutil, sys, re

bindings_root = 'sokol-java'
java_root = f'{bindings_root}/sokol'

module_names = {
    'slog_':    'SokolLog',
    'sg_':      'SokolGfx',
    'sapp_':    'SokolApp',
    'stm_':     'SokolTime',
    'saudio_':  'SokolAudio',
    'sgl_':     'SokolGl',
    'sdtx_':    'SokolDebugText',
    'sshape_':  'SokolShape',
    'sglue_':   'SokolGlue',
    'sfetch_':  'SokolFetch',
}

c_source_names = {
    'slog_':    'sokol_log.c',
    'sg_':      'sokol_gfx.c',
    'sapp_':    'sokol_app.c',
    'stm_':     'sokol_time.c',
    'saudio_':  'sokol_audio.c',
    'sgl_':     'sokol_gl.c',
    'sdtx_':    'sokol_debugtext.c',
    'sshape_':  'sokol_shape.c',
    'sglue_':   'sokol_glue.c',
    'sfetch_':  'sokol_fetch.c',
}

ignores = [
    'sdtx_printf',
    'sdtx_vprintf',
    'sg_install_trace_hooks',
    'sg_trace_hooks',
]

# Java primitive type mappings
prim_types = {
    'int':          'int',
    'bool':         'boolean',
    'char':         'byte',
    'int8_t':       'byte',
    'uint8_t':      'byte',
    'int16_t':      'short',
    'uint16_t':     'short',
    'int32_t':      'int',
    'uint32_t':     'int',
    'int64_t':      'long',
    'uint64_t':     'long',
    'float':        'float',
    'double':       'double',
    'uintptr_t':    'long',
    'intptr_t':     'long',
    'size_t':       'long',
}

# Java ValueLayout mappings
value_layouts = {
    'int':          'ValueLayout.JAVA_INT',
    'bool':         'ValueLayout.JAVA_BOOLEAN',
    'char':         'ValueLayout.JAVA_BYTE',
    'int8_t':       'ValueLayout.JAVA_BYTE',
    'uint8_t':      'ValueLayout.JAVA_BYTE',
    'int16_t':      'ValueLayout.JAVA_SHORT',
    'uint16_t':     'ValueLayout.JAVA_SHORT',
    'int32_t':      'ValueLayout.JAVA_INT',
    'uint32_t':     'ValueLayout.JAVA_INT',
    'int64_t':      'ValueLayout.JAVA_LONG',
    'uint64_t':     'ValueLayout.JAVA_LONG',
    'float':        'ValueLayout.JAVA_FLOAT',
    'double':       'ValueLayout.JAVA_DOUBLE',
    'uintptr_t':    'ValueLayout.JAVA_LONG',
    'intptr_t':     'ValueLayout.JAVA_LONG',
    'size_t':       'ValueLayout.JAVA_LONG',
}

struct_types = []
enum_types = []
out_lines = ''

def reset_globals():
    global struct_types
    global enum_types
    global out_lines
    struct_types = []
    enum_types = []
    out_lines = ''

def l(s):
    global out_lines
    out_lines += s + '\n'

def as_java_const_name(s, prefix):
    """Convert PREFIX_SOME_NAME to SOME_NAME"""
    outp = s.upper()
    up_prefix = prefix.upper()
    if outp.startswith(up_prefix):
        outp = outp[len(up_prefix):]
    # Handle leading underscore
    if outp.startswith('_'):
        outp = outp[1:]
    return outp

def as_java_class_name(s, prefix):
    """Convert prefix_some_name to SomeName"""
    outp = s.lower()
    if outp.startswith(prefix):
        outp = outp[len(prefix):]
    # Remove trailing _t if present
    if outp.endswith('_t'):
        outp = outp[:-2]
    # Convert snake_case to PascalCase
    parts = outp.split('_')
    return ''.join(p.capitalize() for p in parts if p)

def as_java_method_name(s, prefix):
    """Convert prefix_some_func to someFunc"""
    outp = s.lower()
    if outp.startswith(prefix):
        outp = outp[len(prefix):]
    # Convert snake_case to camelCase
    parts = outp.split('_')
    if len(parts) == 0:
        return outp
    return parts[0] + ''.join(p.capitalize() for p in parts[1:])

def as_java_field_name(s):
    """Convert field names, handling reserved words"""
    reserved = {'class', 'interface', 'return', 'default', 'new', 'static', 'final', 'public', 'private'}
    if s in reserved:
        return s + '_'
    return s

def is_prim_type(s):
    return s in prim_types

def is_struct_type(s):
    return s in struct_types

def is_enum_type(s):
    return s in enum_types

def check_ignore(name):
    return name in ignores

def map_java_type(t, prefix):
    """Map C type to Java type"""
    if t == 'void':
        return 'void'
    # Strip const
    if t.startswith('const '):
        t = t[6:]
    
    # Pointers
    if '*' in t or util.is_func_ptr(t):
        return 'MemorySegment'
    
    # Arrays
    if '[' in t:
        return 'MemorySegment'
    
    # Primitives
    if t in prim_types:
        return prim_types[t]
    
    # Enums (map to int)
    if is_enum_type(t):
        return 'int'
    
    # Structs (by value - use MemorySegment)
    if is_struct_type(t):
        return 'MemorySegment'
    
    # Unknown - assume struct
    return 'MemorySegment'

def map_value_layout(t, prefix):
    """Map C type to Java ValueLayout"""
    if t == 'void':
        return None
    # Strip const
    if t.startswith('const '):
        t = t[6:]
    
    # Pointers
    if '*' in t or util.is_func_ptr(t):
        return 'ValueLayout.ADDRESS'
    
    # Primitives
    if t in value_layouts:
        return value_layouts[t]
    
    # Enums (map to int)
    if is_enum_type(t):
        return 'ValueLayout.JAVA_INT'
    
    # Structs - only use layout if it's in our module (starts with our prefix)
    if is_struct_type(t) and t.startswith(prefix):
        return as_java_class_name(t, prefix) + '_LAYOUT'
    
    # External/unknown structs - use ADDRESS (returned by pointer in FFM)
    return 'ValueLayout.ADDRESS'

def map_carrier_type(t, prefix):
    """Map C type to Java carrier type for MethodHandle"""
    java_type = map_java_type(t, prefix)
    if java_type == 'void':
        return 'void.class'
    elif java_type == 'MemorySegment':
        return 'MemorySegment.class'
    elif java_type == 'boolean':
        return 'boolean.class'
    elif java_type == 'byte':
        return 'byte.class'
    elif java_type == 'short':
        return 'short.class'
    elif java_type == 'int':
        return 'int.class'
    elif java_type == 'long':
        return 'long.class'
    elif java_type == 'float':
        return 'float.class'
    elif java_type == 'double':
        return 'double.class'
    return 'MemorySegment.class'

def gen_enum(decl, prefix):
    """Generate enum as Java interface with int constants"""
    if decl['kind'] == 'enum' and 'name' in decl:
        enum_name = as_java_class_name(decl['name'], prefix)
        l(f'    // Enum: {decl["name"]}')
        l(f'    public interface {enum_name} {{')
        for i, item in enumerate(decl['items']):
            item_name = as_java_const_name(item['name'], prefix)
            # Skip internal markers
            if item_name.startswith('_') or item_name == 'FORCE_U32' or item_name == 'NUM':
                continue
            if 'value' in item:
                l(f'        int {item_name} = {item["value"]};')
            else:
                l(f'        int {item_name} = {i};')
        l('    }')
        l('')
    elif decl['kind'] == 'consts':
        # Anonymous enum - generate as top-level constants
        l('    // Constants')
        for item in decl['items']:
            item_name = as_java_const_name(item['name'], prefix)
            l(f'    public static final int {item_name} = {item["value"]};')
        l('')

def gen_struct_layout(decl, prefix):
    """Generate struct as MemoryLayout"""
    struct_name = as_java_class_name(decl['name'], prefix)
    l(f'    // Struct: {decl["name"]}')
    l(f'    public static final StructLayout {struct_name}_LAYOUT = MemoryLayout.structLayout(')
    
    fields = decl.get('fields', [])
    for i, field in enumerate(fields):
        if 'name' not in field:
            continue
        field_name = as_java_field_name(field['name'])
        field_type = field['type']
        
        # Handle arrays
        if '[' in field_type:
            match = re.match(r'(.+)\[(\d+)\]', field_type)
            if match:
                base_type = match.group(1).strip()
                array_size = int(match.group(2))
                base_layout = map_value_layout(base_type, prefix)
                if base_layout:
                    layout = f'MemoryLayout.sequenceLayout({array_size}, {base_layout}).withName("{field_name}")'
                else:
                    continue
            else:
                continue
        else:
            layout_type = map_value_layout(field_type, prefix)
            if layout_type is None:
                continue
            layout = f'{layout_type}.withName("{field_name}")'
        
        comma = ',' if i < len(fields) - 1 else ''
        l(f'        {layout}{comma}')
    
    l(f'    ).withName("{decl["name"]}");')
    l('')

def gen_func(decl, prefix):
    """Generate function binding"""
    func_name = decl['name']
    if check_ignore(func_name):
        return
    
    java_name = as_java_method_name(func_name, prefix)
    
    # Parse return type
    func_type = decl['type']
    ret_match = re.match(r'(.+?)\s*\(', func_type)
    ret_type = ret_match.group(1).strip() if ret_match else 'void'
    java_ret_type = map_java_type(ret_type, prefix)
    ret_layout = map_value_layout(ret_type, prefix)
    
    # Build parameter list
    params = decl.get('params', [])
    java_params = []
    param_layouts = []
    for param in params:
        param_name = as_java_field_name(param['name'])
        param_type = param['type']
        java_type = map_java_type(param_type, prefix)
        java_params.append(f'{java_type} {param_name}')
        
        layout = map_value_layout(param_type, prefix)
        if layout:
            param_layouts.append(layout)
    
    # Generate MethodHandle field
    l(f'    // Function: {func_name}')
    mh_name = f'{java_name}_MH'
    
    # FunctionDescriptor
    if ret_layout and ret_layout != 'void':
        if param_layouts:
            fd = f'FunctionDescriptor.of({ret_layout}, {", ".join(param_layouts)})'
        else:
            fd = f'FunctionDescriptor.of({ret_layout})'
    else:
        if param_layouts:
            fd = f'FunctionDescriptor.ofVoid({", ".join(param_layouts)})'
        else:
            fd = 'FunctionDescriptor.ofVoid()'
    
    l(f'    private static final MethodHandle {mh_name} = LINKER.downcallHandle(')
    l(f'        LOOKUP.find("{func_name}").orElseThrow(),')
    l(f'        {fd}')
    l('    );')
    
    # Generate wrapper method
    param_str = ', '.join(java_params)
    l(f'    public static {java_ret_type} {java_name}({param_str}) {{')
    l('        try {')
    
    call_args = ', '.join(as_java_field_name(p['name']) for p in params)
    if java_ret_type == 'void':
        if call_args:
            l(f'            {mh_name}.invokeExact({call_args});')
        else:
            l(f'            {mh_name}.invokeExact();')
    else:
        if call_args:
            l(f'            return ({java_ret_type}) {mh_name}.invokeExact({call_args});')
        else:
            l(f'            return ({java_ret_type}) {mh_name}.invokeExact();')
    
    l('        } catch (Throwable e) {')
    l('            throw new RuntimeException(e);')
    l('        }')
    l('    }')
    l('')

def gen_module(ir, c_prefix):
    """Generate Java class for a module"""
    class_name = module_names[c_prefix]
    prefix = ir['prefix']
    
    # First pass: collect types
    for decl in ir['decls']:
        if decl['kind'] == 'struct':
            struct_types.append(decl['name'])
        elif decl['kind'] == 'enum' and 'name' in decl:
            enum_types.append(decl['name'])
    
    # Generate class
    l('// Auto-generated Java Panama bindings for Sokol')
    l('// DO NOT EDIT - generated by gen_java.py')
    l('')
    l('package sokol;')
    l('')
    l('import java.lang.foreign.*;')
    l('import java.lang.invoke.MethodHandle;')
    l('import java.nio.file.Path;')
    l('')
    l(f'public final class {class_name} {{')
    l('')
    l('    private static final Linker LINKER = Linker.nativeLinker();')
    l('    private static final SymbolLookup LOOKUP;')
    l('')
    l('    static {')
    l('        String libName = System.mapLibraryName("sokol");')
    l('        SymbolLookup lookup = null;')
    l('        ')
    l('        // Try java.library.path first')
    l('        String libPath = System.getProperty("java.library.path", "");')
    l('        for (String dir : libPath.split(System.getProperty("path.separator"))) {')
    l('            if (!dir.isEmpty()) {')
    l('                Path path = Path.of(dir, libName);')
    l('                if (path.toFile().exists()) {')
    l('                    try {')
    l('                        lookup = SymbolLookup.libraryLookup(path, Arena.global());')
    l('                        break;')
    l('                    } catch (Exception e) { /* try next */ }')
    l('                }')
    l('            }')
    l('        }')
    l('        ')
    l('        // Fall back to system library lookup')
    l('        if (lookup == null) {')
    l('            lookup = SymbolLookup.libraryLookup(libName, Arena.global());')
    l('        }')
    l('        LOOKUP = lookup;')
    l('    }')
    l('')
    l(f'    private {class_name}() {{}}')
    l('')
    
    # Generate enums and constants
    for decl in ir['decls']:
        if decl.get('is_dep', False):
            continue
        if decl['kind'] == 'enum' or decl['kind'] == 'consts':
            gen_enum(decl, prefix)
    
    # Generate struct layouts
    for decl in ir['decls']:
        if decl.get('is_dep', False):
            continue
        if decl['kind'] == 'struct':
            gen_struct_layout(decl, prefix)
    
    # Generate functions
    for decl in ir['decls']:
        if decl.get('is_dep', False):
            continue
        if decl['kind'] == 'func':
            gen_func(decl, prefix)
    
    l('}')

def prepare():
    print('=== Generating Java Panama bindings:')
    if not os.path.isdir(java_root):
        os.makedirs(java_root)

def gen(c_header_path, c_prefix, dep_prefixes):
    if c_prefix not in module_names:
        print(f'  >> warning: skipping generation for {c_prefix} prefix...')
        return
    
    reset_globals()
    
    module_name = module_names[c_prefix]
    print(f'  {c_header_path} => {module_name}.java')
    
    # Use header path as source for clang parsing (like gen_lisp.py)
    actual_source = c_header_path
    
    # Special handling for sokol_glue - needs sokol_gfx.h included first
    if c_prefix == 'sglue_':
        wrapper_path = '/tmp/sokol_glue_wrapper.h'
        gfx_path = os.path.abspath(os.path.join(os.path.dirname(c_header_path), 'sokol_gfx.h'))
        glue_path = os.path.abspath(c_header_path)
        with open(wrapper_path, 'w') as f:
            f.write(f'#include "{gfx_path}"\n')
            f.write(f'#include "{glue_path}"\n')
        actual_source = wrapper_path
    
    # Generate IR
    ir = gen_ir.gen(c_header_path, actual_source, module_name, c_prefix, dep_prefixes, with_comments=True)
    
    # Generate Java class
    gen_module(ir, c_prefix)
    
    # Write output
    output_path = f'{java_root}/{module_name}.java'
    with open(output_path, 'w') as f:
        f.write(out_lines)

# Standalone execution for testing
if __name__ == '__main__':
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    tasks = [
        [ '../sokol_log.h',   'slog_',   [] ],
        [ '../sokol_time.h',  'stm_',    [] ],
        [ '../sokol_audio.h', 'saudio_', [] ],
        [ '../sokol_gfx.h',   'sg_',     [] ],
        [ '../sokol_app.h',   'sapp_',   [] ],
        [ '../sokol_glue.h',  'sglue_',  ['sg_'] ],
    ]
    
    prepare()
    for task in tasks:
        [c_header_path, main_prefix, dep_prefixes] = task
        gen(c_header_path, main_prefix, dep_prefixes)
    
    print('Done!')
