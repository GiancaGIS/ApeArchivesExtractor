// SPDX-License-Identifier: GPL-3.0-only
// Copyright (c) 2026 GiancaGIS

#include <windows.h>
#include <shobjidl.h>
#include <shlwapi.h>
#include <strsafe.h>
#include "ArchiveProperties.h"

#include <algorithm>
#include <cwctype>
#include <new>
#include <string>
#include <vector>

namespace {

HMODULE g_module = nullptr;
long g_lock_count = 0;
long g_object_count = 0;

// Keep these CLSIDs stable: the sparse package manifest references them.
constexpr CLSID CLSID_ApeArchivesExtractorOpen = {
    0x2f4d7b1b, 0x873b, 0x4bbe, {0x87, 0xe3, 0x6e, 0xc9, 0xc9, 0xb8, 0xb2, 0x01}};
constexpr CLSID CLSID_ApeArchivesExtractorExtractHere = {
    0x8b20de33, 0x8d69, 0x47e7, {0x89, 0x07, 0x4f, 0x1f, 0x52, 0x86, 0x38, 0x72}};
constexpr CLSID CLSID_ApeArchivesExtractorOpenAsZip = {
    0xf3b78bd9, 0x1340, 0x402c, {0x98, 0x7c, 0xa5, 0xf1, 0xb9, 0x1d, 0xcb, 0x12}};
constexpr CLSID CLSID_ApeArchivesExtractorCreateArchive = {
    0xa90478d2, 0x61e7, 0x4bde, {0xa4, 0x92, 0x8e, 0x40, 0x2b, 0x89, 0x7a, 0x20}};

enum class CommandKind {
    Open,
    ExtractHere,
    OpenAsZip,
    CreateArchive,
};

struct CommandInfo {
    CommandKind kind;
    const CLSID* clsid;
    const wchar_t* registry_name;
    const wchar_t* title;
    const wchar_t* tooltip;
    const wchar_t* arg;
    bool accepts_multiple;
};

constexpr CommandInfo kCommands[] = {
    {CommandKind::Open, &CLSID_ApeArchivesExtractorOpen, L"ApeArchivesExtractor.Open", L"Apri con ApeArchivesExtractor",
     L"Apre l'archivio con ApeArchivesExtractor", L"", false},
    {CommandKind::ExtractHere, &CLSID_ApeArchivesExtractorExtractHere, L"ApeArchivesExtractor.ExtractHere", L"Estrai qui con ApeArchivesExtractor",
     L"Estrae l'archivio nella cartella corrente", L"--extract-here", false},
    {CommandKind::OpenAsZip, &CLSID_ApeArchivesExtractorOpenAsZip, L"ApeArchivesExtractor.OpenAsZip", L"Apri come archivio ZIP con ApeArchivesExtractor",
     L"Apre il file forzando il backend ZIP", L"--open-as-zip", false},
    {CommandKind::CreateArchive, &CLSID_ApeArchivesExtractorCreateArchive, L"ApeArchivesExtractor.CreateArchive", L"Crea archivio con ApeArchivesExtractor",
     L"Crea un archivio dai file o dalle cartelle selezionati", L"--create-archive", true},
};

bool IsSameClsid(REFCLSID left, REFCLSID right) {
    return IsEqualGUID(left, right) != FALSE;
}

const CommandInfo* FindCommand(REFCLSID clsid) {
    for (const auto& command : kCommands) {
        if (IsSameClsid(clsid, *command.clsid)) {
            return &command;
        }
    }
    return nullptr;
}

std::wstring Quote(const std::wstring& value) {
    return L"\"" + value + L"\"";
}

std::wstring ToLower(std::wstring value) {
    std::transform(value.begin(), value.end(), value.begin(), [](wchar_t ch) {
        return static_cast<wchar_t>(towlower(ch));
    });
    return value;
}

bool HasArchiveExtension(const std::wstring& path) {
    const wchar_t* extension = PathFindExtensionW(path.c_str());
    if (extension == nullptr || *extension == L'\0') {
        return false;
    }
    const std::wstring lower = ToLower(extension);
    if (lower == L".zip" || lower == L".7z" || lower == L".rar" || lower == L".001") {
        return true;
    }
    if (lower.size() == 4 && (lower[1] == L'r' || lower[1] == L'z')) {
        return iswdigit(lower[2]) != 0 && iswdigit(lower[3]) != 0;
    }
    return false;
}

bool IsDirectoryPath(const std::wstring& path) {
    const DWORD attributes = GetFileAttributesW(path.c_str());
    return attributes != INVALID_FILE_ATTRIBUTES && (attributes & FILE_ATTRIBUTE_DIRECTORY) != 0;
}

HRESULT DuplicateString(const wchar_t* value, LPWSTR* result) {
    if (result == nullptr) {
        return E_POINTER;
    }
    return SHStrDupW(value, result);
}

HRESULT GetSelectedPaths(IShellItemArray* items, std::vector<std::wstring>& paths) {
    if (items == nullptr) {
        return E_INVALIDARG;
    }

    DWORD count = 0;
    HRESULT hr = items->GetCount(&count);
    if (FAILED(hr)) {
        return hr;
    }

    paths.clear();
    paths.reserve(count);

    for (DWORD index = 0; index < count; ++index) {
        IShellItem* item = nullptr;
        hr = items->GetItemAt(index, &item);
        if (FAILED(hr)) {
            return hr;
        }

        PWSTR display_name = nullptr;
        hr = item->GetDisplayName(SIGDN_FILESYSPATH, &display_name);
        item->Release();
        if (FAILED(hr)) {
            return hr;
        }

        paths.emplace_back(display_name);
        CoTaskMemFree(display_name);
    }

    return S_OK;
}

bool IsCommandAvailable(const CommandInfo& command, const std::vector<std::wstring>& paths) {
    if (paths.empty()) {
        return false;
    }
    if (!command.accepts_multiple && paths.size() != 1) {
        return false;
    }

    switch (command.kind) {
    case CommandKind::Open:
    case CommandKind::ExtractHere:
        return HasArchiveExtension(paths.front()) && !IsDirectoryPath(paths.front());
    case CommandKind::OpenAsZip:
        return !IsDirectoryPath(paths.front());
    case CommandKind::CreateArchive:
        return true;
    }

    return false;
}

std::wstring GetDllPath() {
    std::wstring path(MAX_PATH, L'\0');
    DWORD length = 0;
    while (true) {
        length = GetModuleFileNameW(g_module, path.data(), static_cast<DWORD>(path.size()));
        if (length == 0) {
            return L"";
        }
        if (length < path.size() - 1) {
            path.resize(length);
            return path;
        }
        path.resize(path.size() * 2);
    }
}

std::wstring GetInstallDirectory() {
    std::wstring path = GetDllPath();
    if (path.empty()) {
        return L"";
    }
    PathRemoveFileSpecW(path.data());
    path.resize(wcslen(path.c_str()));
    return path;
}

HRESULT LaunchApeArchivesExtractor(const CommandInfo& command, const std::vector<std::wstring>& paths) {
    const std::wstring install_dir = GetInstallDirectory();
    if (install_dir.empty()) {
        return HRESULT_FROM_WIN32(GetLastError());
    }

    const std::wstring exe_path = install_dir + L"\\ApeArchivesExtractor.exe";
    DWORD attributes = GetFileAttributesW(exe_path.c_str());
    if (attributes == INVALID_FILE_ATTRIBUTES || (attributes & FILE_ATTRIBUTE_DIRECTORY) != 0) {
        return HRESULT_FROM_WIN32(ERROR_FILE_NOT_FOUND);
    }

    std::wstring command_line = Quote(exe_path);
    if (command.arg[0] != L'\0') {
        command_line += L" ";
        command_line += command.arg;
    }
    for (const auto& path : paths) {
        command_line += L" ";
        command_line += Quote(path);
    }

    std::vector<wchar_t> mutable_command(command_line.begin(), command_line.end());
    mutable_command.push_back(L'\0');

    STARTUPINFOW startup_info = {};
    startup_info.cb = sizeof(startup_info);
    PROCESS_INFORMATION process_info = {};

    if (!CreateProcessW(
            nullptr,
            mutable_command.data(),
            nullptr,
            nullptr,
            FALSE,
            0,
            nullptr,
            install_dir.c_str(),
            &startup_info,
            &process_info)) {
        return HRESULT_FROM_WIN32(GetLastError());
    }

    CloseHandle(process_info.hThread);
    CloseHandle(process_info.hProcess);
    return S_OK;
}

HRESULT WriteRegString(HKEY root, const std::wstring& subkey, const wchar_t* name, const std::wstring& value) {
    HKEY key = nullptr;
    LSTATUS status = RegCreateKeyExW(root, subkey.c_str(), 0, nullptr, 0, KEY_SET_VALUE, nullptr, &key, nullptr);
    if (status != ERROR_SUCCESS) {
        return HRESULT_FROM_WIN32(status);
    }

    status = RegSetValueExW(
        key,
        name,
        0,
        REG_SZ,
        reinterpret_cast<const BYTE*>(value.c_str()),
        static_cast<DWORD>((value.size() + 1) * sizeof(wchar_t)));
    RegCloseKey(key);
    return HRESULT_FROM_WIN32(status);
}

std::wstring GuidToString(REFGUID guid) {
    wchar_t buffer[39] = {};
    StringFromGUID2(guid, buffer, ARRAYSIZE(buffer));
    return buffer;
}

HRESULT RegisterClass(const CommandInfo& command, const std::wstring& dll_path) {
    const std::wstring clsid = GuidToString(*command.clsid);
    const std::wstring clsid_key = L"Software\\Classes\\CLSID\\" + clsid;
    HRESULT hr = WriteRegString(HKEY_CURRENT_USER, clsid_key, nullptr, command.registry_name);
    if (FAILED(hr)) {
        return hr;
    }
    hr = WriteRegString(HKEY_CURRENT_USER, clsid_key + L"\\InprocServer32", nullptr, dll_path);
    if (FAILED(hr)) {
        return hr;
    }
    return WriteRegString(HKEY_CURRENT_USER, clsid_key + L"\\InprocServer32", L"ThreadingModel", L"Apartment");
}

void UnregisterClass(const CommandInfo& command) {
    const std::wstring clsid = GuidToString(*command.clsid);
    const std::wstring clsid_key = L"Software\\Classes\\CLSID\\" + clsid;
    RegDeleteTreeW(HKEY_CURRENT_USER, clsid_key.c_str());
}

class ApeArchivesExtractorExplorerCommand final : public IExplorerCommand {
public:
    explicit ApeArchivesExtractorExplorerCommand(const CommandInfo& command) : command_(command) {
        InterlockedIncrement(&g_object_count);
    }

    ~ApeArchivesExtractorExplorerCommand() {
        InterlockedDecrement(&g_object_count);
    }

    IFACEMETHODIMP QueryInterface(REFIID riid, void** object) override {
        if (object == nullptr) {
            return E_POINTER;
        }
        *object = nullptr;
        if (IsEqualIID(riid, IID_IUnknown) || IsEqualIID(riid, IID_IExplorerCommand)) {
            *object = static_cast<IExplorerCommand*>(this);
            AddRef();
            return S_OK;
        }
        return E_NOINTERFACE;
    }

    IFACEMETHODIMP_(ULONG) AddRef() override {
        return static_cast<ULONG>(InterlockedIncrement(&ref_count_));
    }

    IFACEMETHODIMP_(ULONG) Release() override {
        const ULONG count = static_cast<ULONG>(InterlockedDecrement(&ref_count_));
        if (count == 0) {
            delete this;
        }
        return count;
    }

    IFACEMETHODIMP GetTitle(IShellItemArray*, LPWSTR* title) override {
        return DuplicateString(command_.title, title);
    }

    IFACEMETHODIMP GetIcon(IShellItemArray*, LPWSTR* icon) override {
        const std::wstring install_dir = GetInstallDirectory();
        if (install_dir.empty()) {
            return DuplicateString(L"", icon);
        }
        const std::wstring icon_path = install_dir + L"\\_internal\\apearchivesextractor\\assets\\apearchivesextractor_app.ico";
        return DuplicateString(icon_path.c_str(), icon);
    }

    IFACEMETHODIMP GetToolTip(IShellItemArray*, LPWSTR* tooltip) override {
        return DuplicateString(command_.tooltip, tooltip);
    }

    IFACEMETHODIMP GetCanonicalName(GUID* guid) override {
        if (guid == nullptr) {
            return E_POINTER;
        }
        *guid = *command_.clsid;
        return S_OK;
    }

    IFACEMETHODIMP GetState(IShellItemArray* items, BOOL, EXPCMDSTATE* state) override {
        if (state == nullptr) {
            return E_POINTER;
        }

        std::vector<std::wstring> paths;
        const HRESULT hr = GetSelectedPaths(items, paths);
        if (FAILED(hr) || !IsCommandAvailable(command_, paths)) {
            *state = ECS_HIDDEN;
            return S_OK;
        }

        *state = ECS_ENABLED;
        return S_OK;
    }

    IFACEMETHODIMP Invoke(IShellItemArray* items, IBindCtx*) override {
        std::vector<std::wstring> paths;
        HRESULT hr = GetSelectedPaths(items, paths);
        if (FAILED(hr)) {
            return hr;
        }
        if (!IsCommandAvailable(command_, paths)) {
            return E_INVALIDARG;
        }
        return LaunchApeArchivesExtractor(command_, paths);
    }

    IFACEMETHODIMP GetFlags(EXPCMDFLAGS* flags) override {
        if (flags == nullptr) {
            return E_POINTER;
        }
        *flags = ECF_DEFAULT;
        return S_OK;
    }

    IFACEMETHODIMP EnumSubCommands(IEnumExplorerCommand** enum_commands) override {
        if (enum_commands == nullptr) {
            return E_POINTER;
        }
        *enum_commands = nullptr;
        return E_NOTIMPL;
    }

private:
    long ref_count_ = 1;
    const CommandInfo& command_;
};

class ClassFactory final : public IClassFactory {
public:
    explicit ClassFactory(const CommandInfo& command) : command_(command) {
        InterlockedIncrement(&g_object_count);
    }

    ~ClassFactory() {
        InterlockedDecrement(&g_object_count);
    }

    IFACEMETHODIMP QueryInterface(REFIID riid, void** object) override {
        if (object == nullptr) {
            return E_POINTER;
        }
        *object = nullptr;
        if (IsEqualIID(riid, IID_IUnknown) || IsEqualIID(riid, IID_IClassFactory)) {
            *object = static_cast<IClassFactory*>(this);
            AddRef();
            return S_OK;
        }
        return E_NOINTERFACE;
    }

    IFACEMETHODIMP_(ULONG) AddRef() override {
        return static_cast<ULONG>(InterlockedIncrement(&ref_count_));
    }

    IFACEMETHODIMP_(ULONG) Release() override {
        const ULONG count = static_cast<ULONG>(InterlockedDecrement(&ref_count_));
        if (count == 0) {
            delete this;
        }
        return count;
    }

    IFACEMETHODIMP CreateInstance(IUnknown* outer, REFIID riid, void** object) override {
        if (object == nullptr) {
            return E_POINTER;
        }
        *object = nullptr;
        if (outer != nullptr) {
            return CLASS_E_NOAGGREGATION;
        }

        ApeArchivesExtractorExplorerCommand* command = new (std::nothrow) ApeArchivesExtractorExplorerCommand(command_);
        if (command == nullptr) {
            return E_OUTOFMEMORY;
        }

        const HRESULT hr = command->QueryInterface(riid, object);
        command->Release();
        return hr;
    }

    IFACEMETHODIMP LockServer(BOOL lock) override {
        if (lock) {
            InterlockedIncrement(&g_lock_count);
        } else {
            InterlockedDecrement(&g_lock_count);
        }
        return S_OK;
    }

private:
    long ref_count_ = 1;
    const CommandInfo& command_;
};

}  // namespace

extern "C" BOOL APIENTRY DllMain(HMODULE module, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        g_module = module;
        DisableThreadLibraryCalls(module);
    }
    return TRUE;
}

STDAPI DllCanUnloadNow() {
    return (InterlockedCompareExchange(&g_object_count, 0, 0) == 0 &&
            InterlockedCompareExchange(&g_lock_count, 0, 0) == 0) ? S_OK : S_FALSE;
}

STDAPI DllGetClassObject(REFCLSID clsid, REFIID riid, void** object) {
    if (object == nullptr) {
        return E_POINTER;
    }
    *object = nullptr;

    if (IsEqualGUID(clsid, archive_properties::ClassId)) {
        return archive_properties::GetClassObject(riid, object, g_module, &g_object_count);
    }
    const CommandInfo* command = FindCommand(clsid);
    if (command == nullptr) {
        return CLASS_E_CLASSNOTAVAILABLE;
    }

    ClassFactory* factory = new (std::nothrow) ClassFactory(*command);
    if (factory == nullptr) {
        return E_OUTOFMEMORY;
    }

    const HRESULT hr = factory->QueryInterface(riid, object);
    factory->Release();
    return hr;
}

STDAPI DllRegisterServer() {
    const std::wstring dll_path = GetDllPath();
    if (dll_path.empty()) {
        return HRESULT_FROM_WIN32(GetLastError());
    }

    for (const auto& command : kCommands) {
        const HRESULT hr = RegisterClass(command, dll_path);
        if (FAILED(hr)) {
            return hr;
        }
    }
    return S_OK;
}

STDAPI DllUnregisterServer() {
    for (const auto& command : kCommands) {
        UnregisterClass(command);
    }
    return S_OK;
}
