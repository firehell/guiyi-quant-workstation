/* Host-only layout probe. Never loaded into the inspected process. */
#define Py_BUILD_CORE
#include <Python.h>
#include <datetime.h>
#include <stddef.h>
#include <stdio.h>
#include <structmember.h>
#include <internal/pycore_dict.h>
#include <internal/pycore_object.h>
#define FIELD(name, value) printf("\"" name "\":%zu,", (size_t)(value))
int main(void) {
    printf("{");
    FIELD("version", PY_VERSION_HEX);
    FIELD("pointer_size", sizeof(void *));
    FIELD("object_size", sizeof(PyObject));
    printf("\"managed_dict_offset\":%zd,", MANAGED_DICT_OFFSET);
    FIELD("inline_values_flag", Py_TPFLAGS_INLINE_VALUES);
    FIELD("managed_dict_flag", Py_TPFLAGS_MANAGED_DICT);
    FIELD("heap_cached_keys", offsetof(PyHeapTypeObject, ht_cached_keys));
    FIELD("type_dictoffset", offsetof(PyTypeObject, tp_dictoffset));
    FIELD("type_basicsize", offsetof(PyTypeObject, tp_basicsize));
    FIELD("type_dict", offsetof(PyTypeObject, tp_dict));
    FIELD("dict_used", offsetof(PyDictObject, ma_used));
    FIELD("dict_indices", offsetof(PyDictKeysObject, dk_indices));
    FIELD("dict_nentries", offsetof(PyDictKeysObject, dk_nentries));
    FIELD("dict_kind", offsetof(PyDictKeysObject, dk_kind));
    FIELD("dict_index_bytes", offsetof(PyDictKeysObject, dk_log2_index_bytes));
    FIELD("dict_values", offsetof(PyDictValues, values));
    FIELD("unicode_compact_size", sizeof(PyCompactUnicodeObject));
    FIELD("member_definition", offsetof(PyMemberDescrObject, d_member));
    FIELD("member_offset", offsetof(PyMemberDef, offset));
    FIELD("member_type", offsetof(PyMemberDef, type));
    FIELD("member_object_ex", T_OBJECT_EX);
    FIELD("date_data", offsetof(PyDateTime_Date, data));
    printf("\"layout_end\":true}\n");
    return 0;
}
