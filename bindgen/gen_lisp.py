#-------------------------------------------------------------------------------
#   gen_lisp.py
#
#   Generate Common Lisp bindings.
#-------------------------------------------------------------------------------
import gen_ir
import os, shutil, sys, re

import gen_util as util

module_names = {
    'slog_':    'sokol-log',
    'sg_':      'sokol-gfx',
    'sapp_':    'sokol-app',
    'stm_':     'sokol-time',
    'saudio_':  'sokol-audio',
    'sgl_':     'sokol-gl',
    'sdtx_':    'sokol-debugtext',
    'sshape_':  'sokol-shape',
    'sglue_':   'sokol-glue',
    'sfetch_':  'sokol-fetch',
    'sargs_':   'sokol-args',
}

c_source_paths = {
    'slog_':    'src/c/sokol_log.c',
    'sg_':      'src/c/sokol_gfx.c',
    'sapp_':    'src/c/sokol_app.c',
    'stm_':     'src/c/sokol_time.c',
    'saudio_':  'src/c/sokol_audio.c',
    'sgl_':     'src/c/sokol_gl.c',
    'sdtx_':    'src/c/sokol_debugtext.c',
    'sshape_':  'src/c/sokol_shape.c',
    'sglue_':   'src/c/sokol_glue.c',
    'sfetch_':  'src/c/sokol_fetch.c',
    'sargs_':   'src/c/sokol_args.c',
}

ignores = [
    'sdtx_printf',
    'sdtx_vprintf',
]

# CFFI type mappings
prim_types = {
    'int':          ':int',
    'bool':         ':bool',
    'char':         ':char',
    'int8_t':       ':int8',
    'uint8_t':      ':uint8',
    'int16_t':      ':int16',
    'uint16_t':     ':uint16',
    'int32_t':      ':int32',
    'uint32_t':     ':uint32',
    'int64_t':      ':int64',
    'uint64_t':     ':uint64',
    'float':        ':float',
    'double':       ':double',
    'uintptr_t':    ':uintptr',
    'intptr_t':     ':intptr',
    'size_t':       ':size',
    'void':         ':void',
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

def as_lisp_name(s, prefix):
    s = s.replace('_', '-')
    return s

def as_lisp_type_name(s, prefix):
    if s.endswith('_t'):
        s = s[:-2]
    return as_lisp_name(s, prefix)

def is_prim_type(s):
    return s in prim_types

def is_struct_type(s):
    return s in struct_types

def is_enum_type(s):
    return s in enum_types

def check_struct_type(s, prefix):
    if s.startswith(prefix):
        struct_types.append(s)

def check_enum_type(s, prefix):
    if s.startswith(prefix):
        enum_types.append(s)

def type_default_value(s):
    if is_prim_type(s):
        if s in ['float', 'double']:
            return '0.0'
        elif s == 'bool':
            return 'nil'
        else:
            return '0'
    else:
        return 'null'

def get_type_module_prefix(t):
    for prefix in module_names.keys():
        if t.startswith(prefix):
            return prefix
    return None

def qualify_type_name(t, current_prefix):
    type_prefix = get_type_module_prefix(t)

    # If type is from a different module, qualify it
    if type_prefix and type_prefix != current_prefix:
        module_name = module_names[type_prefix]
        lisp_name = as_lisp_type_name(t, type_prefix)
        return f'{module_name}:{lisp_name}'
    else:
        # Same module or no prefix - use unqualified name
        return as_lisp_type_name(t, current_prefix)

def map_type(t, prefix):
    if t == 'void':
        return ':void'
    if t.startswith('const '):
        t = t[6:]
    if '(*' in t or '(' in t and ')' in t and '*' in t:
        return ':pointer'
    if '*' in t:
        base_type = t.replace('*', '').strip()
        if base_type == 'void':
            return ':pointer'
        elif base_type == 'char':
            # char* is usually a string
            return ':string'
        else:
            # Pointer to other types
            mapped_base = map_type(base_type, prefix)
            return f'(:pointer {mapped_base})'
    if '[' in t:
        match = re.match(r'(.+)\[(\d+)\]', t)
        if match:
            base_type = match.group(1).strip()
            array_size = match.group(2)
            mapped_base = map_type(base_type, prefix)
            # Return as a symbol to avoid comma issues
            return f'{mapped_base}-array-{array_size}'
    if t in prim_types:
        return prim_types[t]
    if is_enum_type(t):
        return ':int'

    if is_struct_type(t):
        qualified_name = qualify_type_name(t, prefix)
        # Struct by value
        return f'(:struct {qualified_name})'

    # Unknown type - assume it's a struct type
    qualified_name = qualify_type_name(t, prefix)
    return f'(:struct {qualified_name})'

def gen_struct(decl, prefix):
    struct_name = as_lisp_type_name(decl['name'], prefix)
    l(f'(cffi:defcstruct {struct_name}')

    if 'comment' in decl:
        l(f'  ;; {decl["name"]}')

    for field in decl['fields']:
        if 'name' in field:
            field_name = as_lisp_name(field['name'], prefix)
            field_type_str = field['type']

            if '[' in field_type_str:
                match = re.match(r'(.+)\[(\d+)\]', field_type_str)
                if match:
                    base_type = match.group(1).strip()
                    array_size = match.group(2)
                    mapped_base = map_type(base_type, prefix)
                    # Use proper CFFI array syntax without commas
                    l(f'  ({field_name} {mapped_base} :count {array_size})')
                else:
                    field_type = map_type(field_type_str, prefix)
                    l(f'  ({field_name} {field_type})')
            else:
                field_type = map_type(field_type_str, prefix)
                # If field type is an enum, use the base integer type
                if is_enum_type(field_type_str):
                    field_type = ':int'
                l(f'  ({field_name} {field_type})')
        else:
            # Anonymous field (usually padding or embedded struct)
            field_type = map_type(field['type'], prefix)
            l(f'  (:anonymous {field_type})')

    l(')')
    l('')

def gen_enum(decl, prefix):
    if decl['kind'] == 'enum':
        # Named enum
        enum_name = as_lisp_type_name(decl['name'], prefix)
        l(f'(cffi:defcenum {enum_name}')

        for item in decl['items']:
            item_name = as_lisp_name(item['name'], prefix)
            if 'value' in item:
                # Use proper keyword syntax
                l(f'  (:{item_name} {item["value"]})')
            else:
                l(f'  :{item_name}')

        l(')')
    else:
        # Anonymous enum - generate constants
        l(';; Constants')
        for item in decl['items']:
            item_name = as_lisp_name(item['name'], prefix)
            value = item['value']
            # Constants with + prefix - use cl:defconstant, not cffi:defconstant
            l(f'(cl:defconstant +{item_name}+ {value})')

    l('')

def gen_func(decl, prefix):
    func_name = decl['name']

    if func_name in ignores:
        return

    lisp_name = as_lisp_name(func_name, prefix)

    # Parse return type from function signature
    # Function type format: "return_type (param_types)"
    func_type = decl['type']
    return_type_match = re.match(r'(.+?)\s*\(', func_type)
    if return_type_match:
        return_type_str = return_type_match.group(1).strip()
        return_type = map_type(return_type_str, prefix)
    else:
        return_type = ':void'

    # Generate function
    l(f'(cffi:defcfun ("{func_name}" {lisp_name}) {return_type}')

    # Add comment if available
    if 'comment' in decl:
        l(f'  ;; {func_name}')

    # Generate parameters
    for param in decl['params']:
        param_name = as_lisp_name(param['name'], prefix)
        param_type = map_type(param['type'], prefix)
        l(f'  ({param_name} {param_type})')

    l(')')
    l('')

def gen_module_header(module_name, prefix, header_comment, all_symbols):
    l(';;;; Auto-generated CFFI bindings for Sokol')
    l(';;;; DO NOT EDIT - generated by gen_lisp.py')
    l('')
    l(f'(defpackage :{module_name}')
    l('  (:use :cl :cffi)')
    l(f'  (:nicknames :{prefix.rstrip("_").replace("_", "-")})')
    l('  (:export')
    # Export all symbols (without : prefix - that's for keywords, not symbols)
    for sym in sorted(all_symbols):
        l(f'   {sym}')
    l('   ))')
    l('')
    l(f'(in-package :{module_name})')
    l('')

    # Add original header comment if available
    if header_comment:
        lines = header_comment.strip().split('\n')
        l(';;;; Original header documentation:')
        for line in lines:
            l(f';;;; {line}')
        l('')

def gen_module(ir, c_source_path):
    """Generate bindings for a single module."""
    module_name = module_names[ir['prefix']]
    prefix = ir['prefix']
    all_symbols = []

    # First pass: collect ALL struct and enum types (including dependencies)
    # This MUST happen before we generate any code that references these types
    for decl in ir['decls']:
        if decl['kind'] == 'struct':
            check_struct_type(decl['name'], prefix)
        elif decl['kind'] == 'enum' and 'name' in decl:
            check_enum_type(decl['name'], prefix)

    # Second pass: collect symbols to export (only non-dependencies)
    for decl in ir['decls']:
        if decl.get('is_dep', False):
            continue  # Don't export dependency symbols

        if decl['kind'] == 'struct':
            all_symbols.append(as_lisp_type_name(decl['name'], prefix))
        elif decl['kind'] == 'enum':
            if 'name' in decl:
                all_symbols.append(as_lisp_type_name(decl['name'], prefix))
            # Consts
            for item in decl.get('items', []):
                all_symbols.append('+' + as_lisp_name(item['name'], prefix) + '+')
        elif decl['kind'] == 'func':
            all_symbols.append(as_lisp_name(decl['name'], prefix))

    # Generate header with all symbols
    gen_module_header(module_name, prefix, ir.get('comment', ''), all_symbols)

    # Third pass: generate declarations (skip dependencies)
    l(';; Enums and Constants')
    l('')
    for decl in ir['decls']:
        if decl.get('is_dep', False):
            continue
        if decl['kind'] == 'enum' or decl['kind'] == 'consts':
            gen_enum(decl, prefix)

    l(';; Structs')
    l('')
    for decl in ir['decls']:
        if decl.get('is_dep', False):
            continue
        if decl['kind'] == 'struct':
            gen_struct(decl, prefix)

    l(';; Functions')
    l('')
    for decl in ir['decls']:
        if decl.get('is_dep', False):
            continue
        if decl['kind'] == 'func':
            gen_func(decl, prefix)

def prepare():
    if not os.path.isdir('src'):
        os.makedirs('src/c')

def gen(c_header_path, main_prefix, dep_prefixes):
    reset_globals()

    module_name = module_names[main_prefix]
    c_source_path = c_source_paths[main_prefix]

    print(f'  {c_header_path} => {module_name}.lisp')

    # Special handling for sokol_glue - needs sokol_gfx.h included first
    actual_source = c_header_path
    if main_prefix == 'sglue_':
        # Create a temporary wrapper header with absolute paths
        import os as os_module
        wrapper_path = '/tmp/sokol_glue_wrapper.h'
        gfx_path = os_module.path.abspath('../sokol_gfx.h')
        glue_path = os_module.path.abspath(c_header_path)
        with open(wrapper_path, 'w') as f:
            f.write(f'#include "{gfx_path}"\n')
            f.write(f'#include "{glue_path}"\n')
        actual_source = wrapper_path

    # Generate IR
    ir = gen_ir.gen(c_header_path, actual_source, module_name, main_prefix, dep_prefixes, with_comments=True)

    # Generate Lisp bindings
    gen_module(ir, c_source_path)

    # Write output file
    output_path = f'src/{module_name}.lisp'
    with open(output_path, 'w') as f:
        f.write(out_lines)

    # Generate C source file
    gen_c_source(c_header_path, c_source_path, main_prefix)

def gen_c_source(header_path, output_path, prefix):
    header_name = os.path.basename(header_path)

    # Determine implementation macro name
    impl_macro = header_name.upper().replace('.H', '_IMPL').replace('.', '_')

    # Special handling for sokol_glue - needs sokol_gfx.h included first (but not implemented)
    if prefix == 'sglue_':
        content = f'''// Auto-generated C source for {header_name}
// Compile this file and link with your Common Lisp application
// Note: This file should be compiled together with sokol_gfx.c or sokol_app.c

#include "../../sokol/sokol_gfx.h"
#define {impl_macro}
#include "../../sokol/{header_name}"
'''
    else:
        content = f'''// Auto-generated C source for {header_name}
// Compile this file and link with your Common Lisp application

#define {impl_macro}
#include "../../sokol/{header_name}"
'''

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        f.write(content)
