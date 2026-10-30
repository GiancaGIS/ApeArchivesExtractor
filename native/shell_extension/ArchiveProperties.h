// SPDX-License-Identifier: GPL-3.0-only
// Copyright (c) 2026 GiancaGIS
#pragma once
#include <windows.h>
#include <unknwn.h>

namespace archive_properties {
inline constexpr CLSID ClassId = {
    0xd91d509b, 0x3aab, 0x4938, {0xb9, 0x76, 0x48, 0x91, 0x0a, 0x45, 0x5d, 0x61}};
HRESULT GetClassObject(REFIID iid, void** result, HMODULE module, long* objects);
}
