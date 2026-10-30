// SPDX-License-Identifier: GPL-3.0-only
// Copyright (c) 2026 GiancaGIS
#include "ArchiveProperties.h"
#include "ArchivePropertiesResource.h"
#include <shlobj.h>
#include <shellapi.h>
#include <commctrl.h>
#include <algorithm>
#include <atomic>
#include <cwctype>
#include <memory>
#include <mutex>
#include <new>
#include <string>
#include <vector>

namespace archive_properties {
namespace {
constexpr UINT_PTR kPollTimer = 1;
constexpr size_t kMaxReport = 128 * 1024;
constexpr ULONGLONG kTimeoutMs = 30'000;

bool Italian() { return PRIMARYLANGID(GetUserDefaultUILanguage()) == LANG_ITALIAN; }
const wchar_t* Text(const wchar_t* it, const wchar_t* en) { return Italian() ? it : en; }

class Handle {
public:
    explicit Handle(HANDLE handle = nullptr) : value(handle) {}
    ~Handle() { if (value && value != INVALID_HANDLE_VALUE) CloseHandle(value); }
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;
    HANDLE value;
};

std::wstring ModuleDirectory(HMODULE module) {
    std::wstring path(32768, L'\0');
    DWORD count = GetModuleFileNameW(module, path.data(), static_cast<DWORD>(path.size()));
    if (!count || count >= path.size()) return L"";
    path.resize(count);
    const size_t slash = path.find_last_of(L"\\/");
    return slash == std::wstring::npos ? L"" : path.substr(0, slash);
}

bool Supported(const std::wstring& path) {
    auto name = path;
    std::transform(name.begin(), name.end(), name.begin(), [](wchar_t c) { return static_cast<wchar_t>(towlower(c)); });
    for (const auto suffix : {L".zip", L".7z", L".rar", L".tar.gz"}) {
        const size_t length = wcslen(suffix);
        if (name.size() >= length && name.compare(name.size()-length, length, suffix) == 0) return true;
    }
    const size_t dot = name.find_last_of(L'.');
    if (dot == std::wstring::npos) return false;
    auto extension = name.substr(dot+1);
    if (extension.size() >= 3 && std::all_of(extension.begin(), extension.end(), [](wchar_t c) { return c >= L'0' && c <= L'9'; })) return true;
    return extension.size() == 3 && (extension[0] == L'r' || extension[0] == L'z') &&
        iswdigit(extension[1]) && iswdigit(extension[2]);
}

struct PageData {
    PageData(std::wstring file, HMODULE instance, long* count)
        : path(std::move(file)), module(instance), objects(count), cancel(CreateEventW(nullptr, TRUE, FALSE, nullptr)) {
        InterlockedIncrement(objects);
    }
    ~PageData() { InterlockedDecrement(objects); }
    void AddRef() { InterlockedIncrement(&refs); }
    void Release() { if (InterlockedDecrement(&refs) == 0) delete this; }
    long refs = 1;
    std::wstring path;
    HMODULE module;
    long* objects;
    Handle cancel;
    std::mutex mutex;
    std::wstring report;
    std::atomic<bool> complete{false};
};

std::wstring Decode(const std::string& bytes) {
    int count = MultiByteToWideChar(CP_UTF8, 0, bytes.data(), static_cast<int>(bytes.size()), nullptr, 0);
    std::wstring text(static_cast<size_t>(count), L'\0');
    if (count) MultiByteToWideChar(CP_UTF8, 0, bytes.data(), static_cast<int>(bytes.size()), text.data(), count);
    std::wstring result;
    result.reserve(text.size());
    for (size_t index = 0; index < text.size(); ++index) {
        if (text[index] == L'\n' && (index == 0 || text[index-1] != L'\r')) result += L'\r';
        result += text[index] == L'\0' ? L' ' : text[index];
    }
    return result;
}

std::wstring Inspect(PageData& data) {
    if (WaitForSingleObject(data.cancel.value, 0) == WAIT_OBJECT_0) return L"";
    const auto directory = ModuleDirectory(data.module);
    const auto exe = directory + L"\\ape-arch.exe";
    std::wstring command = L"\"" + exe + L"\" info --language " + (Italian() ? L"it" : L"en") + L" -- \"" + data.path + L"\"";
    SECURITY_ATTRIBUTES security{sizeof(security), nullptr, TRUE};
    HANDLE readRaw = nullptr, writeRaw = nullptr;
    if (!CreatePipe(&readRaw, &writeRaw, &security, 0)) return Text(L"Impossibile avviare l'analisi.", L"Unable to start inspection.");
    Handle read(readRaw), write(writeRaw);
    if (!SetHandleInformation(read.value, HANDLE_FLAG_INHERIT, 0)) return L"Pipe setup failed.";
    Handle input(CreateFileW(L"NUL", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, &security, OPEN_EXISTING, 0, nullptr));
    if (input.value == INVALID_HANDLE_VALUE) return L"Input setup failed.";
    Handle job(CreateJobObjectW(nullptr, nullptr));
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_PROCESS_MEMORY;
    limits.ProcessMemoryLimit = 512 * 1024 * 1024;
    if (!job.value || !SetInformationJobObject(job.value, JobObjectExtendedLimitInformation, &limits, sizeof(limits))) return L"Process limits unavailable.";

    SIZE_T attributeSize = 0;
    InitializeProcThreadAttributeList(nullptr, 1, 0, &attributeSize);
    std::vector<BYTE> attributes(attributeSize);
    auto attributeList = reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(attributes.data());
    if (!InitializeProcThreadAttributeList(attributeList, 1, 0, &attributeSize)) return L"Process setup failed.";
    struct AttributeCleanup { LPPROC_THREAD_ATTRIBUTE_LIST list; ~AttributeCleanup() { DeleteProcThreadAttributeList(list); } } cleanup{attributeList};
    HANDLE inherited[] = {write.value, input.value};
    if (!UpdateProcThreadAttribute(attributeList, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST, inherited, sizeof(inherited), nullptr, nullptr)) return L"Handle isolation failed.";
    STARTUPINFOEXW startup{};
    startup.StartupInfo.cb = sizeof(startup);
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
    startup.StartupInfo.hStdInput = input.value;
    startup.StartupInfo.hStdOutput = startup.StartupInfo.hStdError = write.value;
    startup.lpAttributeList = attributeList;
    PROCESS_INFORMATION process{};
    if (!CreateProcessW(exe.c_str(), command.data(), nullptr, nullptr, TRUE,
        CREATE_NO_WINDOW | CREATE_SUSPENDED | EXTENDED_STARTUPINFO_PRESENT, nullptr, directory.c_str(), &startup.StartupInfo, &process)) {
        return Text(L"ape-arch.exe non disponibile. Reinstallare ApeArchivesExtractor.", L"ape-arch.exe is unavailable. Reinstall ApeArchivesExtractor.");
    }
    Handle processHandle(process.hProcess), threadHandle(process.hThread);
    CloseHandle(write.value); write.value = nullptr;
    if (!AssignProcessToJobObject(job.value, process.hProcess)) {
        TerminateProcess(process.hProcess, 1);
        return L"Unable to isolate the inspection process.";
    }
    if (ResumeThread(process.hThread) == static_cast<DWORD>(-1)) return L"Unable to start the inspection process.";
    const auto started = GetTickCount64();
    std::string output;
    bool exited = false;
    for (;;) {
        if (WaitForSingleObject(data.cancel.value, 0) == WAIT_OBJECT_0) return L"";
        if (GetTickCount64() - started >= kTimeoutMs) {
            return Text(L"Analisi interrotta dopo 30 secondi. Aprire l'archivio nell'applicazione per ulteriori dettagli.",
                        L"Inspection stopped after 30 seconds. Open the archive in the application for more details.");
        }
        DWORD available = 0;
        if (!PeekNamedPipe(read.value, nullptr, 0, nullptr, &available, nullptr)) break;
        if (available) {
            char buffer[4096];
            DWORD received = 0;
            if (!ReadFile(read.value, buffer, (std::min)(available, static_cast<DWORD>(sizeof(buffer))), &received, nullptr)) break;
            output.append(buffer, received);
            if (output.size() > kMaxReport) return Text(L"Risultato troppo grande.", L"Inspection output exceeded its limit.");
        } else if (exited) {
            break;
        } else {
            exited = WaitForSingleObject(process.hProcess, 25) == WAIT_OBJECT_0;
        }
    }
    if (output.empty()) return Text(L"Informazioni non disponibili: archivio non leggibile o limite di risorse raggiunto.",
                                   L"Information unavailable: the archive could not be read or a resource limit was reached.");
    return Decode(output);
}

struct WorkerStart { PageData* data; HMODULE pin; };
DWORD WINAPI InspectWorker(void* raw) {
    HMODULE pin = nullptr;
    {
        std::unique_ptr<WorkerStart> start(static_cast<WorkerStart*>(raw));
        pin = start->pin;
        PageData* data = start->data;
        try {
            auto report = Inspect(*data);
            std::lock_guard<std::mutex> guard(data->mutex);
            data->report = std::move(report);
        } catch (...) {
            // Never let an archive/backend failure unwind into Explorer.
        }
        data->complete.store(true, std::memory_order_release);
        data->Release();
    }
    FreeLibraryAndExitThread(pin, 0);
}

bool StartWorker(PageData* data) {
    HMODULE pin = nullptr;
    if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS,
        reinterpret_cast<LPCWSTR>(&InspectWorker), &pin)) return false;
    auto start = new (std::nothrow) WorkerStart{data, pin};
    if (!start) { FreeLibrary(pin); return false; }
    data->AddRef();
    HANDLE thread = CreateThread(nullptr, 0, InspectWorker, start, 0, nullptr);
    if (!thread) { data->Release(); delete start; FreeLibrary(pin); return false; }
    CloseHandle(thread);
    return true;
}

void Layout(HWND window) {
    RECT bounds{}, units{8, 8, 14, 14};
    GetClientRect(window, &bounds);
    MapDialogRect(window, &units);
    const int x = units.left, y = units.top, height = units.bottom;
    const int width = (std::max)(1L, bounds.right - 2*x);
    MoveWindow(GetDlgItem(window, IDC_ARCHIVE_STATUS), x, y, width, 2*y, TRUE);
    MoveWindow(GetDlgItem(window, IDC_ARCHIVE_REPORT), x, 4*y, width,
        (std::max)(1L, bounds.bottom - 6*y - height), TRUE);
    const int half = (width-x)/2;
    MoveWindow(GetDlgItem(window, IDC_ARCHIVE_OPEN), x, bounds.bottom-y-height, half, height, TRUE);
    MoveWindow(GetDlgItem(window, IDC_ARCHIVE_COPY), 2*x+half, bounds.bottom-y-height, width-half-x, height, TRUE);
}

void CopyReport(HWND window) {
    HWND edit = GetDlgItem(window, IDC_ARCHIVE_REPORT);
    const int count = GetWindowTextLengthW(edit);
    HGLOBAL memory = GlobalAlloc(GMEM_MOVEABLE, (static_cast<size_t>(count)+1)*sizeof(wchar_t));
    if (!memory) return;
    auto buffer = static_cast<wchar_t*>(GlobalLock(memory));
    if (!buffer) { GlobalFree(memory); return; }
    GetWindowTextW(edit, buffer, count+1);
    GlobalUnlock(memory);
    if (OpenClipboard(window)) {
        EmptyClipboard();
        if (SetClipboardData(CF_UNICODETEXT, memory)) memory = nullptr;
        CloseClipboard();
    }
    if (memory) GlobalFree(memory);
}

INT_PTR CALLBACK PageProc(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
    auto data = reinterpret_cast<PageData*>(GetWindowLongPtrW(window, DWLP_USER));
    try {
        switch (message) {
        case WM_INITDIALOG: {
            data = reinterpret_cast<PageData*>(reinterpret_cast<PROPSHEETPAGEW*>(lparam)->lParam);
            SetWindowLongPtrW(window, DWLP_USER, reinterpret_cast<LONG_PTR>(data));
            SetDlgItemTextW(window, IDC_ARCHIVE_STATUS, Text(L"Lettura delle informazioni dell'archivio...", L"Reading archive information..."));
            SetDlgItemTextW(window, IDC_ARCHIVE_REPORT, data->path.c_str());
            SetDlgItemTextW(window, IDC_ARCHIVE_OPEN, Text(L"Apri archivio", L"Open archive"));
            SetDlgItemTextW(window, IDC_ARCHIVE_COPY, Text(L"Copia informazioni", L"Copy information"));
            SendDlgItemMessageW(window, IDC_ARCHIVE_REPORT, EM_SETLIMITTEXT, kMaxReport, 0);
            EnableWindow(GetDlgItem(window, IDC_ARCHIVE_COPY), FALSE);
            Layout(window);
            if (!SetTimer(window, kPollTimer, 100, nullptr) || !StartWorker(data)) {
                KillTimer(window, kPollTimer);
                SetDlgItemTextW(window, IDC_ARCHIVE_STATUS, Text(L"Analisi non disponibile.", L"Inspection unavailable."));
            }
            return TRUE;
        }
        case WM_SIZE: Layout(window); break;
        case WM_TIMER:
            if (data && wparam == kPollTimer && data->complete.load(std::memory_order_acquire)) {
                std::lock_guard<std::mutex> guard(data->mutex);
                SetDlgItemTextW(window, IDC_ARCHIVE_REPORT, data->report.empty()
                    ? Text(L"Informazioni non disponibili.", L"Information unavailable.") : data->report.c_str());
                SetDlgItemTextW(window, IDC_ARCHIVE_STATUS, Text(L"Informazioni archivio - sola lettura", L"Archive information - read only"));
                EnableWindow(GetDlgItem(window, IDC_ARCHIVE_COPY), TRUE);
                KillTimer(window, kPollTimer);
            }
            break;
        case WM_COMMAND:
            if (LOWORD(wparam) == IDC_ARCHIVE_COPY) CopyReport(window);
            if (LOWORD(wparam) == IDC_ARCHIVE_OPEN && data) {
                const auto directory = ModuleDirectory(data->module);
                const auto exe = directory + L"\\ApeArchivesExtractor.exe";
                const auto argument = L"\"" + data->path + L"\"";
                ShellExecuteW(window, L"open", exe.c_str(), argument.c_str(), directory.c_str(), SW_SHOWNORMAL);
            }
            break;
        case WM_DESTROY:
            KillTimer(window, kPollTimer);
            if (data) SetEvent(data->cancel.value);
            SetWindowLongPtrW(window, DWLP_USER, 0);
            break;
        }
    } catch (...) {
        SetDlgItemTextW(window, IDC_ARCHIVE_STATUS, Text(L"Informazioni non disponibili.", L"Information unavailable."));
    }
    return FALSE;
}

UINT CALLBACK PageCallback(HWND, UINT message, LPPROPSHEETPAGEW page) {
    auto data = reinterpret_cast<PageData*>(page->lParam);
    if (message == PSPCB_ADDREF) data->AddRef();
    if (message == PSPCB_RELEASE) data->Release();
    return 1;
}

class Handler final : public IShellExtInit, public IShellPropSheetExt {
public:
    Handler(HMODULE module, long* objects) : module_(module), objects_(objects) { InterlockedIncrement(objects_); }
    ~Handler() { InterlockedDecrement(objects_); }
    IFACEMETHODIMP QueryInterface(REFIID iid, void** result) override {
        if (!result) return E_POINTER;
        *result = nullptr;
        if (IsEqualIID(iid, IID_IUnknown) || IsEqualIID(iid, IID_IShellExtInit)) *result = static_cast<IShellExtInit*>(this);
        else if (IsEqualIID(iid, IID_IShellPropSheetExt)) *result = static_cast<IShellPropSheetExt*>(this);
        else return E_NOINTERFACE;
        AddRef(); return S_OK;
    }
    IFACEMETHODIMP_(ULONG) AddRef() override { return InterlockedIncrement(&refs_); }
    IFACEMETHODIMP_(ULONG) Release() override { auto count = InterlockedDecrement(&refs_); if (!count) delete this; return count; }
    IFACEMETHODIMP Initialize(PCIDLIST_ABSOLUTE, IDataObject* object, HKEY) override {
        path_.clear();
        if (!object) return E_INVALIDARG;
        FORMATETC format{CF_HDROP, nullptr, DVASPECT_CONTENT, -1, TYMED_HGLOBAL};
        STGMEDIUM medium{};
        HRESULT status = object->GetData(&format, &medium);
        if (FAILED(status)) return status;
        try {
            auto drop = reinterpret_cast<HDROP>(medium.hGlobal);
            if (DragQueryFileW(drop, 0xffffffff, nullptr, 0) == 1) {
                UINT length = DragQueryFileW(drop, 0, nullptr, 0);
                if (length && length < 32768) {
                    std::wstring candidate(static_cast<size_t>(length)+1, L'\0');
                    DragQueryFileW(drop, 0, candidate.data(), length+1);
                    candidate.resize(length);
                    const DWORD attributes = GetFileAttributesW(candidate.c_str());
                    if (attributes != INVALID_FILE_ATTRIBUTES && !(attributes & FILE_ATTRIBUTE_DIRECTORY) && Supported(candidate)) path_ = std::move(candidate);
                }
            }
        } catch (...) { status = E_OUTOFMEMORY; }
        ReleaseStgMedium(&medium);
        return FAILED(status) ? status : (path_.empty() ? E_INVALIDARG : S_OK);
    }
    IFACEMETHODIMP AddPages(LPFNADDPROPSHEETPAGE add, LPARAM parameter) override {
        if (!add || path_.empty()) return E_INVALIDARG;
        try {
            auto data = new PageData(path_, module_, objects_);
            if (!data->cancel.value) { data->Release(); return E_OUTOFMEMORY; }
            PROPSHEETPAGEW page{};
            page.dwSize = sizeof(page);
            page.dwFlags = PSP_USECALLBACK | PSP_USETITLE;
            page.hInstance = module_;
            page.pszTemplate = MAKEINTRESOURCEW(IDD_ARCHIVE_PROPERTIES);
            page.pszTitle = Text(L"Archivio APE", L"APE archive");
            page.pfnDlgProc = PageProc;
            page.pfnCallback = PageCallback;
            page.lParam = reinterpret_cast<LPARAM>(data);
            HPROPSHEETPAGE handle = CreatePropertySheetPageW(&page);
            data->Release();
            if (!handle) return E_FAIL;
            if (!add(handle, parameter)) DestroyPropertySheetPage(handle);
            return S_OK;
        } catch (...) { return E_OUTOFMEMORY; }
    }
    IFACEMETHODIMP ReplacePage(UINT, LPFNADDPROPSHEETPAGE, LPARAM) override { return E_NOTIMPL; }
private:
    long refs_ = 1;
    HMODULE module_;
    long* objects_;
    std::wstring path_;
};

class Factory final : public IClassFactory {
public:
    Factory(HMODULE module, long* objects) : module_(module), objects_(objects) { InterlockedIncrement(objects_); }
    ~Factory() { InterlockedDecrement(objects_); }
    IFACEMETHODIMP QueryInterface(REFIID iid, void** result) override {
        if (!result) return E_POINTER;
        *result = nullptr;
        if (!IsEqualIID(iid, IID_IUnknown) && !IsEqualIID(iid, IID_IClassFactory)) return E_NOINTERFACE;
        *result = static_cast<IClassFactory*>(this); AddRef(); return S_OK;
    }
    IFACEMETHODIMP_(ULONG) AddRef() override { return InterlockedIncrement(&refs_); }
    IFACEMETHODIMP_(ULONG) Release() override { auto count = InterlockedDecrement(&refs_); if (!count) delete this; return count; }
    IFACEMETHODIMP CreateInstance(IUnknown* outer, REFIID iid, void** result) override {
        if (!result) return E_POINTER;
        *result = nullptr;
        if (outer) return CLASS_E_NOAGGREGATION;
        auto handler = new (std::nothrow) Handler(module_, objects_);
        if (!handler) return E_OUTOFMEMORY;
        HRESULT status = handler->QueryInterface(iid, result);
        handler->Release(); return status;
    }
    IFACEMETHODIMP LockServer(BOOL lock) override {
        if (lock) InterlockedIncrement(objects_); else InterlockedDecrement(objects_);
        return S_OK;
    }
private:
    long refs_ = 1;
    HMODULE module_;
    long* objects_;
};
}  // namespace

HRESULT GetClassObject(REFIID iid, void** result, HMODULE module, long* objects) {
    auto factory = new (std::nothrow) Factory(module, objects);
    if (!factory) return E_OUTOFMEMORY;
    HRESULT status = factory->QueryInterface(iid, result);
    factory->Release(); return status;
}
}  // namespace archive_properties
