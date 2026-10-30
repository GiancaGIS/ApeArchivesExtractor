// SPDX-License-Identifier: GPL-3.0-only
// Copyright (c) 2026 GiancaGIS
// Run on a private desktop; never register a COM class or modify Explorer.
#include "../ArchiveProperties.h"
#include "../ArchivePropertiesResource.h"
#include <shlobj.h>
#include <commctrl.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

void Require(bool condition, const char* message) { if (!condition) throw std::runtime_error(message); }
using ClassObject = HRESULT (STDAPICALLTYPE*)(REFCLSID, REFIID, void**);
using CanUnload = HRESULT (STDAPICALLTYPE*)();
BOOL CALLBACK AcceptPage(HPROPSHEETPAGE page, LPARAM result) { *reinterpret_cast<HPROPSHEETPAGE*>(result) = page; return TRUE; }
BOOL CALLBACK RejectPage(HPROPSHEETPAGE, LPARAM) { return FALSE; }

IShellExtInit* Initialize(ClassObject getClass, const wchar_t* file) {
    IClassFactory* factory = nullptr;
    Require(SUCCEEDED(getClass(archive_properties::ClassId, IID_PPV_ARGS(&factory))), "COM class factory unavailable");
    IShellExtInit* handler = nullptr;
    const auto created = factory->CreateInstance(nullptr, IID_PPV_ARGS(&handler));
    factory->Release();
    Require(SUCCEEDED(created), "COM handler unavailable");
    IShellItem* item = nullptr;
    Require(SUCCEEDED(SHCreateItemFromParsingName(file, nullptr, IID_PPV_ARGS(&item))), "Shell item unavailable");
    IDataObject* data = nullptr;
    const auto bound = item->BindToHandler(nullptr, BHID_DataObject, IID_PPV_ARGS(&data));
    item->Release();
    Require(SUCCEEDED(bound), "Shell data object unavailable");
    auto status = handler->Initialize(nullptr, data, nullptr);
    data->Release();
    if (FAILED(status)) { handler->Release(); return nullptr; }
    return handler;
}

HPROPSHEETPAGE AddPage(IShellExtInit* handler, bool accept) {
    IShellPropSheetExt* properties = nullptr;
    Require(SUCCEEDED(handler->QueryInterface(IID_PPV_ARGS(&properties))), "Property sheet interface unavailable");
    HPROPSHEETPAGE page = nullptr;
    const auto status = properties->AddPages(accept ? AcceptPage : RejectPage, reinterpret_cast<LPARAM>(&page));
    properties->Release();
    Require(SUCCEEDED(status), "Adding a property page failed");
    return page;
}

HWND Sheet(HPROPSHEETPAGE page) {
    PROPSHEETHEADERW sheet{};
    sheet.dwSize = sizeof(sheet);
    sheet.dwFlags = PSH_MODELESS | PSH_NOAPPLYNOW | PSH_NOCONTEXTHELP;
    sheet.pszCaption = L"Archive property sheet smoke test";
    sheet.nPages = 1;
    sheet.phpage = &page;
    auto window = reinterpret_cast<HWND>(PropertySheetW(&sheet));
    Require(window && window != reinterpret_cast<HWND>(-1), "Property sheet window unavailable");
    return window;
}

void Pump() {
    MSG message{};
    while (PeekMessageW(&message, nullptr, 0, 0, PM_REMOVE)) {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
    Sleep(10);
}

void WaitUnloaded(CanUnload canUnload) {
    auto deadline = GetTickCount64() + 5000;
    while (canUnload() != S_OK && GetTickCount64() < deadline) Pump();
    Require(canUnload() == S_OK, "Page or worker leaked a DLL reference");
}

void Screenshot(HWND window, const wchar_t* filename) {
    RECT bounds{};
    GetWindowRect(window, &bounds);
    const int width = bounds.right-bounds.left, height = bounds.bottom-bounds.top;
    BITMAPINFO info{};
    info.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    info.bmiHeader.biWidth = width;
    info.bmiHeader.biHeight = -height;
    info.bmiHeader.biPlanes = 1;
    info.bmiHeader.biBitCount = 32;
    HDC dc = CreateCompatibleDC(nullptr);
    void* bits = nullptr;
    HBITMAP bitmap = CreateDIBSection(dc, &info, DIB_RGB_COLORS, &bits, nullptr, 0);
    Require(bitmap && bits, "Screenshot allocation failed");
    auto previous = SelectObject(dc, bitmap);
    PrintWindow(window, dc, 0);
    BITMAPFILEHEADER header{};
    header.bfType = 0x4d42;
    header.bfOffBits = sizeof(header) + sizeof(BITMAPINFOHEADER);
    header.bfSize = header.bfOffBits + width*height*4;
    std::ofstream output(std::filesystem::path(filename), std::ios::binary);
    output.write(reinterpret_cast<const char*>(&header), sizeof(header));
    output.write(reinterpret_cast<const char*>(&info.bmiHeader), sizeof(info.bmiHeader));
    output.write(static_cast<const char*>(bits), static_cast<std::streamsize>(width)*height*4);
    SelectObject(dc, previous);
    DeleteObject(bitmap);
    DeleteDC(dc);
}

int wmain(int argc, wchar_t** argv) {
    if (argc < 3) { std::cerr << "Usage: ArchivePropertiesSmoke DLL fixture.zip [screenshot.bmp]\n"; return 2; }
    try {
        const auto desktopName = L"ApeArchivePropertiesTest-" + std::to_wstring(GetCurrentProcessId());
        HDESK desktop = CreateDesktopW(desktopName.c_str(), nullptr, nullptr, 0, GENERIC_ALL, nullptr);
        Require(desktop && SetThreadDesktop(desktop), "Private test desktop unavailable");
        Require(SUCCEEDED(CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED)), "COM initialization failed");
        INITCOMMONCONTROLSEX common{sizeof(common), ICC_WIN95_CLASSES};
        InitCommonControlsEx(&common);
        HMODULE module = LoadLibraryExW(argv[1], nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
        Require(module != nullptr, "Native extension did not load");
        auto getClass = reinterpret_cast<ClassObject>(GetProcAddress(module, "DllGetClassObject"));
        auto canUnload = reinterpret_cast<CanUnload>(GetProcAddress(module, "DllCanUnloadNow"));
        Require(getClass && canUnload && canUnload() == S_OK, "COM exports or initial lifetime invalid");

        auto handler = Initialize(getClass, argv[2]);
        Require(handler != nullptr, "ZIP was not accepted");
        Require(canUnload() == S_FALSE, "Live COM object must pin the DLL");
        Require(!AddPage(handler, false), "Rejected page should not be retained");
        auto page = AddPage(handler, true);
        Require(page != nullptr, "Property page unavailable");
        handler->Release();
        Require(canUnload() == S_FALSE, "Page must outlive the released COM handler");
        HWND sheet = Sheet(page);
        auto deadline = GetTickCount64() + 40000;
        std::wstring report;
        while (GetTickCount64() < deadline) {
            Pump();
            HWND current = PropSheet_GetCurrentPageHwnd(sheet);
            HWND edit = GetDlgItem(current, IDC_ARCHIVE_REPORT);
            int size = GetWindowTextLengthW(edit);
            report.assign(static_cast<size_t>(size)+1, L'\0');
            GetWindowTextW(edit, report.data(), size+1);
            if (report.find(L"Metadata only") != std::wstring::npos || report.find(L"Solo metadati") != std::wstring::npos) break;
        }
        Require(report.find(L"ZIP") != std::wstring::npos, "ZIP metadata was not rendered");
        Require(report.find(L"Files: 1") != std::wstring::npos || report.find(L"File contenuti: 1") != std::wstring::npos,
                "The native page did not show the archive member count");
        if (argc > 3) Screenshot(sheet, argv[3]);
        DestroyWindow(sheet);
        WaitUnloaded(canUnload);

        // Close another page immediately: cancel its process and release its
        // page/worker references without touching a destroyed HWND.
        handler = Initialize(getClass, argv[2]);
        page = AddPage(handler, true);
        handler->Release();
        sheet = Sheet(page);
        DestroyWindow(sheet);
        WaitUnloaded(canUnload);

        auto plain = std::filesystem::path(argv[2]).parent_path() / L"non-archive.txt";
        { std::ofstream file(plain); file << "plain text"; }
        Require(Initialize(getClass, plain.c_str()) == nullptr, "A plain file received an archive tab");
        WaitUnloaded(canUnload);
        FreeLibrary(module);
        CoUninitialize();
        // Do not switch to this desktop; it is private to the test process.
        std::cout << "Native property sheet: COM, metadata, rejection, cancellation and lifetime passed.\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
