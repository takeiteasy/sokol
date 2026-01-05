# -------------------------------------------------------------------------------
#   Generate C++ RAII wrapper bindings for sokol headers.
#
#   C++ coding style:
#   - Namespaces follow C prefix: sg_, sapp_, etc.
#   - Builder classes use helper::desc<T> base
#   - RAII wrappers use helper::ptr<T>
#   - Method chaining for builder pattern
# -------------------------------------------------------------------------------
import gen_ir
import os, sys

import gen_util as util

module_names = {
    "slog_": "slog",
    "sg_": "sg",
    "sapp_": "sapp",
    "stm_": "stm",
    "saudio_": "saudio",
    "sfetch_": "sfetch",
    "sargs_": "sargs",
    "sglue_": "sglue",
}

# Map prefix to header guard macro
header_guards = {
    "slog_": "SOKOL_LOG_INCLUDED",
    "sg_": "SOKOL_GFX_INCLUDED",
    "sapp_": "SOKOL_APP_INCLUDED",
    "stm_": "SOKOL_TIME_INCLUDED",
    "saudio_": "SOKOL_AUDIO_INCLUDED",
    "sfetch_": "SOKOL_FETCH_INCLUDED",
    "sargs_": "SOKOL_ARGS_INCLUDED",
    "sglue_": "SOKOL_GLUE_INCLUDED",
}

# Map prefix to header filename
header_files = {
    "slog_": "sokol_log.h",
    "sg_": "sokol_gfx.h",
    "sapp_": "sokol_app.h",
    "stm_": "sokol_time.h",
    "saudio_": "sokol_audio.h",
    "sfetch_": "sokol_fetch.h",
    "sargs_": "sokol_args.h",
    "sglue_": "sokol_glue.h",
}

ignores = [
    # Functions to skip
]

# Keyword overrides to avoid C++ conflicts
overrides = {
    "class": "klass",
    "namespace": "name_space",
    "template": "templ",
    "operator": "oper",
}

# Irregular plural forms for array singularization
irregular_plurals = {
    "data": "data",
    "vertices": "vertex",
    "indices": "index",
}

# Backend-specific prefixes to skip (with and without leading underscore)
backend_prefixes = ['_gl_', '_d3d11_', '_mtl_', '_wgpu_', 'gl_', 'd3d11_', 'mtl_', 'wgpu_']

# Canary fields to skip
skip_fields = ['_start_canary', '_end_canary']

# Global state
struct_types = []          # All struct names
enum_types = []            # All enum names
handle_types = {}          # Map handle type to prefix (sg_buffer -> 'buffer')
descriptor_types = {}      # Map descriptor to handle (sg_buffer_desc -> sg_buffer)
out_lines = ""             # Accumulated output


def reset_globals():
    global struct_types, enum_types, handle_types, descriptor_types, out_lines
    struct_types = []
    enum_types = []
    handle_types = {}
    descriptor_types = {}
    out_lines = ""


def l(s=""):
    """Append line to output"""
    global out_lines
    out_lines += s + "\n"


def is_handle_type(struct_decl):
    """Check if struct is a handle type (single 'id' field)"""
    fields = struct_decl.get('fields', [])
    return (len(fields) == 1 and
            fields[0]['name'] == 'id' and
            fields[0]['type'] == 'uint32_t')


def is_descriptor_type(struct_name):
    """Check if struct is a descriptor (*_desc suffix)"""
    return struct_name.endswith('_desc')


def drop_prefix(name, prefix):
    """Remove prefix from name: sg_buffer_desc -> buffer_desc"""
    if name.startswith(prefix):
        return name[len(prefix):]
    return name


def extract_prefix_part(name, prefix):
    """Extract the middle part: sg_buffer_desc with prefix 'sg_' -> 'buffer'"""
    if name.startswith(prefix):
        rest = name[len(prefix):]
        if rest.endswith('_desc'):
            return rest[:-5]  # Remove '_desc' suffix
        return rest
    return name


def singularize(name):
    """Convert plural array field names to singular for method names"""
    if name in irregular_plurals:
        return irregular_plurals[name]
    # Simple heuristic: remove trailing 's'
    if name.endswith('s') and len(name) > 1:
        return name[:-1]
    return name


def should_skip_field(field_name):
    """Check if field should be skipped (canaries, backend-specific)"""
    if field_name in skip_fields:
        return True
    for prefix in backend_prefixes:
        if field_name.startswith(prefix):
            return True
    return False


def check_override(name):
    """Check if name needs to be overridden to avoid C++ keywords"""
    return overrides.get(name, name)


def is_prim_type(type_str):
    """Check if type is a primitive"""
    primitives = [
        'int', 'bool', 'char', 'float', 'double',
        'int8_t', 'uint8_t', 'int16_t', 'uint16_t',
        'int32_t', 'uint32_t', 'int64_t', 'uint64_t',
        'size_t', 'uintptr_t', 'intptr_t'
    ]
    return type_str in primitives


def is_struct_type(type_str):
    """Check if type is a struct"""
    return type_str in struct_types


def is_enum_type(type_str):
    """Check if type is an enum"""
    return type_str in enum_types


def find_struct(struct_name, all_decls):
    """Find struct declaration by name"""
    for decl in all_decls:
        if decl['kind'] == 'struct' and decl['name'] == struct_name:
            return decl
    return None


def pre_parse(inp):
    """First pass: collect all struct and enum names"""
    for decl in inp['decls']:
        if decl['kind'] == 'struct':
            struct_types.append(decl['name'])
        elif decl['kind'] == 'enum':
            enum_types.append(decl['name'])


def prepare():
    """Initialize and write header preamble + helper templates"""
    global out_lines
    print('=== Generating C++ bindings:')

    reset_globals()

    # Write header preamble
    l('// Machine generated C++ wrapper for Sokol library.')
    l('// https://github.com/takeiteasy/sokol.hpp')
    l('//')
    l('// Do not edit manually; regenerate using gen_cpp.py.')
    l('')
    l('#pragma once')
    l('#include <utility>')
    l('#include <memory>')
    l('')

    # Helper templates will be generated after first library analysis
    # (need to know all handle types)


def gen(c_header_path, c_prefix, dep_c_prefixes):
    """Generate bindings for one module"""
    if c_prefix not in module_names:
        print(f'  >> warning: skipping generation for {c_prefix} prefix...')
        return

    module_name = module_names[c_prefix]
    print(f'  {c_header_path} => {module_name}')

    # Generate IR from C header (source_path is used for clang parsing)
    ir = gen_ir.gen(c_header_path, c_header_path, module_name, c_prefix, dep_c_prefixes, with_comments=False)

    # Pre-parse to collect types
    pre_parse(ir)

    # Identify handle and descriptor types
    for decl in ir['decls']:
        if decl['kind'] == 'struct':
            if is_handle_type(decl):
                prefix_part = extract_prefix_part(decl['name'], c_prefix)
                handle_types[decl['name']] = prefix_part
            elif is_descriptor_type(decl['name']):
                # Try to find corresponding handle
                base_name = decl['name'][:-5]  # Remove '_desc'
                if base_name in struct_types:
                    descriptor_types[decl['name']] = base_name

    # Generate code (to be implemented)
    gen_module(ir, c_prefix, dep_c_prefixes)


def gen_helper_templates(prefix, library_handle_types):
    """Generate helper templates (deleter, ptr, desc) for libraries with handles"""
    if not library_handle_types:
        return  # No handles in this library

    l('namespace helper {')

    # Generate deleter template
    l('template <typename T>')
    l('struct deleter {')
    l('    void operator()(T* handle_ptr) const {')
    l('        if (handle_ptr && handle_ptr->id != 0) {')

    # Generate constexpr if chain for each handle type
    first = True
    for handle_name, handle_prefix in library_handle_types.items():
        if_keyword = 'if constexpr' if first else 'else if constexpr'
        l(f'            {if_keyword} (std::is_same_v<T, {handle_name}>)')
        l(f'                {prefix}destroy_{handle_prefix}(*handle_ptr);')
        first = False

    l('        }')
    l('        delete handle_ptr;')
    l('    }')
    l('};')
    l('')

    # Generate ptr template
    l('template <typename T>')
    l('class ptr {')
    l('    using ptr_t = std::unique_ptr<T, deleter<T>>;')
    l('    ptr_t handle_ptr;')
    l('')
    l('public:')
    l('    ptr() : handle_ptr(nullptr) {}')
    l('    ptr(const ptr &other) = delete;')
    l('    ptr &operator=(const ptr &other) = delete;')
    l('    ptr(ptr &&other) noexcept = default;')
    l('    ptr &operator=(ptr &&other) noexcept = default;')
    l('    ptr(const T &h) : handle_ptr(h.id != 0 ? new T(h) : nullptr) {}')
    l('')
    l('    ptr &operator=(const T &h) {')
    l('        if (h.id != 0)')
    l('            handle_ptr = ptr_t(new T(h));')
    l('        else')
    l('            handle_ptr.reset();')
    l('        return *this;')
    l('    }')
    l('')
    l('    operator T() const {')
    l('        return handle_ptr ? *handle_ptr : T{0};')
    l('    }')
    l('')
    l('    T get() const {')
    l('        return handle_ptr ? *handle_ptr : T{0};')
    l('    }')
    l('')
    l('    uint32_t id() const {')
    l('        return handle_ptr ? handle_ptr->id : 0;')
    l('    }')
    l('')

    # Generate state() method with constexpr if chain
    module_prefix = prefix[:-1] if prefix.endswith('_') else prefix  # sg_ -> sg
    if module_prefix == 'sg':  # Only sg has resource states
        l(f'    {prefix}resource_state state() const {{')
        l('        if (!handle_ptr)')
        l(f'            return {prefix.upper()}RESOURCESTATE_INVALID;')

        first = True
        for handle_name, handle_prefix in library_handle_types.items():
            if_keyword = 'if constexpr' if first else 'else if constexpr'
            l(f'        {if_keyword} (std::is_same_v<T, {handle_name}>)')
            l(f'            return {prefix}query_{handle_prefix}_state(*handle_ptr);')
            first = False

        l(f'        return {prefix.upper()}RESOURCESTATE_INVALID;')
        l('    }')
        l('')
        l('    bool is_valid() const {')
        l(f'        return handle_ptr && handle_ptr->id != 0 && state() == {prefix.upper()}RESOURCESTATE_VALID;')
        l('    }')
        l('')

    # Reset and release methods
    l('    // Reset the pointer (release the resource)')
    l('    void reset() {')
    l('        handle_ptr.reset();')
    l('    }')
    l('')
    l('    // Release ownership without destroying the resource')
    l('    T release() {')
    l('        if (handle_ptr) {')
    l('            T result = *handle_ptr;')
    l('            handle_ptr.release(); // Don\'t delete, just release ownership')
    l('            return result;')
    l('        }')
    l('        return T{0};')
    l('    }')
    l('};')
    l('')

    # Generate desc template
    l('template<typename T>')
    l('class desc {')
    l('protected:')
    l('    T desc_ = {};')
    l('    ')
    l('public:')
    l('    desc() = default;')
    l('    ')
    l('    // Conversion operator - allows implicit conversion to the C struct')
    l('    operator const T&() const { return desc_; }')
    l('    operator T&() { return desc_; }')
    l('    ')
    l('    // Explicit pointer access')
    l('    const T* operator&() const { return &desc_; }')
    l('    T* operator&() { return &desc_; }')
    l('    ')
    l('    // Access to underlying descriptor')
    l('    const T& get() const { return desc_; }')
    l('    T& get() { return desc_; }')
    l('};')

    l('} // namespace helper')
    l('')


def gen_builder_class(struct_decl, prefix, all_decls):
    """Generate builder class for a descriptor struct"""
    struct_name = struct_decl['name']
    class_name = drop_prefix(struct_name, prefix)

    l(f'// Builder API for {struct_name}')
    l(f'class {class_name} : public helper::desc<{struct_name}> {{')
    l('public:')
    l(f'    {class_name}() = default;')
    l('')

    # Generate setters for all fields
    for field in struct_decl['fields']:
        if should_skip_field(field['name']):
            continue

        gen_field_setters(class_name, field, prefix, all_decls, path=[])

    # Check if this descriptor has a corresponding handle type
    if struct_name in descriptor_types:
        handle_type = descriptor_types[struct_name]
        handle_prefix = extract_prefix_part(handle_type, prefix)

        l(f'    // Build the resource from this descriptor')
        l(f'    {handle_type} build() const {{')
        l(f'        return {prefix}make_{handle_prefix}(&desc_);')
        l(f'    }}')
        l('')

    l('};')
    l('')


def gen_field_setters(class_name, field, prefix, all_decls, path=[]):
    """Recursively generate setter methods for a field"""
    field_name = check_override(field['name'])
    field_type = field['type']

    # Build method name from path (singularize array elements)
    if path:
        path_parts = []
        for segment, is_array in path:
            path_parts.append(singularize(segment) if is_array else segment)
        method_name = '_'.join(path_parts + [field_name])
    else:
        method_name = field_name

    # Build field access path
    field_access = 'desc_'
    for segment, is_array in path:
        if is_array:
            field_access += f'.{segment}[index]'
        else:
            field_access += f'.{segment}'
    field_access += f'.{field_name}'

    # Case 1: Array type
    if util.is_1d_array_type(field_type):
        elem_type = util.extract_array_type(field_type)

        # Array of struct - recurse into struct fields
        if is_struct_type(elem_type):
            elem_struct = find_struct(elem_type, all_decls)
            if elem_struct:
                for elem_field in elem_struct['fields']:
                    if should_skip_field(elem_field['name']):
                        continue
                    gen_field_setters(class_name, elem_field, prefix, all_decls,
                                    path + [(field_name, True)])
        else:
            # Array of primitives/enums - indexed setter
            singular_name = singularize(field_name)
            if path:
                method_name = '_'.join([p[0] for p in path] + [singular_name])
            else:
                method_name = singular_name

            # Rebuild field access for array
            field_access = 'desc_'
            for segment, is_array in path:
                if is_array:
                    field_access += f'.{segment}[index]'
                else:
                    field_access += f'.{segment}'
            field_access += f'.{field_name}[index]'

            # Determine C++ type
            if is_prim_type(elem_type):
                cpp_type = elem_type
            elif is_enum_type(elem_type):
                cpp_type = elem_type
            elif is_struct_type(elem_type):
                cpp_type = f'const {elem_type}&'
            else:
                cpp_type = elem_type

            l(f'    {class_name}& {method_name}(int index, {cpp_type} value) {{')
            l(f'        {field_access} = value;')
            l(f'        return *this;')
            l(f'    }}')
            l('')

    # Case 2: Nested struct - recurse into its fields
    elif is_struct_type(field_type):
        nested_struct = find_struct(field_type, all_decls)
        if nested_struct:
            for nested_field in nested_struct['fields']:
                if should_skip_field(nested_field['name']):
                    continue
                gen_field_setters(class_name, nested_field, prefix, all_decls,
                                path + [(field_name, False)])

    # Case 3: Simple field (primitive, enum, handle, pointer)
    else:
        # Determine C++ type
        if is_prim_type(field_type):
            cpp_type = field_type
        elif is_enum_type(field_type):
            cpp_type = field_type
        elif is_struct_type(field_type):
            cpp_type = f'const {field_type}&'
        elif util.is_func_ptr(field_type):
            cpp_type = field_type
        elif util.is_string_ptr(field_type):
            cpp_type = 'const char*'
        elif util.is_const_void_ptr(field_type):
            cpp_type = 'const void*'
        elif util.is_void_ptr(field_type):
            cpp_type = 'void*'
        elif field_type.startswith('const ') and field_type.endswith(' *'):
            # const pointer to struct
            cpp_type = field_type
        elif field_type.endswith(' *'):
            # pointer to struct
            cpp_type = field_type
        else:
            # Default: use as-is
            cpp_type = f'const {field_type}&'

        # Check if we have an array in the path - if so, add index parameter
        has_array_in_path = any(is_array for _, is_array in path)
        if has_array_in_path:
            l(f'    {class_name}& {method_name}(int index, {cpp_type} value) {{')
        else:
            l(f'    {class_name}& {method_name}({cpp_type} value) {{')
        l(f'        {field_access} = value;')
        l(f'        return *this;')
        l(f'    }}')
        l('')


def gen_module(ir, prefix, dep_prefixes):
    """Generate C++ code for a module"""
    module_name = module_names[prefix]
    MODULE_NAME = module_name.upper()
    guard_name = header_guards[prefix]
    header_file = header_files[prefix]

    # Conditional include
    l(f'#ifndef {guard_name}')
    l(f'#if __has_include("{header_file}")')
    l(f'#include "{header_file}"')
    l(f'#elif __has_include("sokol/{header_file}")')
    l(f'#include "sokol/{header_file}"')
    l('#else')
    l(f'#warning "Cannot find {header_file}, disabling!"')
    l(f'#define SOKOL_NO_{MODULE_NAME}')
    l('#endif')
    l('#endif')
    l('')

    # Namespace
    l(f'#ifndef SOKOL_NO_{MODULE_NAME}')
    l(f'namespace {module_name} {{')

    # Collect handle types for this library
    library_handle_types = {k: v for k, v in handle_types.items() if k.startswith(prefix)}

    # Generate helper templates if this library has handles
    if library_handle_types:
        gen_helper_templates(prefix, library_handle_types)

    # Generate RAII type aliases for handles
    if library_handle_types:
        l('// RAII wrapper type aliases')
        for handle_name, handle_prefix in library_handle_types.items():
            alias_name = drop_prefix(handle_name, prefix)
            l(f'using {alias_name} = helper::ptr<{handle_name}>;')
        l('')

    # Generate builder classes for descriptors
    for decl in ir['decls']:
        if decl['kind'] == 'struct' and is_descriptor_type(decl['name']):
            gen_builder_class(decl, prefix, ir['decls'])

    # TODO: Generate function wrappers

    l(f'}} // namespace {module_name}')
    l(f'#endif // SOKOL_NO_{MODULE_NAME}')
    l('')


def finalize(output_path):
    """Write accumulated output to file"""
    print(f'  Writing output to {output_path}')

    with open(output_path, 'w', newline='\n') as f:
        f.write(out_lines)
