"""Windows acrylic backdrop. Other platforms keep a readable opaque surface."""
import sys


def apply_glass(window, enabled):
    if sys.platform != 'win32' or sys.getwindowsversion().build < 17763:
        return False
    import ctypes
    from ctypes import wintypes
    class Accent(ctypes.Structure):
        _fields_ = [('state', wintypes.DWORD), ('flags', wintypes.DWORD),
                    ('color', wintypes.DWORD), ('animation', wintypes.DWORD)]
    class Composition(ctypes.Structure):
        _fields_ = [('attribute', ctypes.c_int), ('data', ctypes.c_void_p),
                    ('size', ctypes.c_size_t)]
    hwnd = int(window.winId())
    user = ctypes.WinDLL('user32', use_last_error=True)
    fn = user.SetWindowCompositionAttribute
    fn.argtypes = [wintypes.HWND, ctypes.POINTER(Composition)]
    fn.restype = wintypes.BOOL
    # ABGR: dark tint, 65% opacity; the OS blurs the actual desktop.
    accent = Accent(4 if enabled else 0, 0, 0xA61B1716, 0)
    data = Composition(19, ctypes.addressof(accent), ctypes.sizeof(accent))
    result = bool(fn(hwnd, ctypes.byref(data)))
    dwm = ctypes.WinDLL('dwmapi')
    dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD,
                                         ctypes.c_void_p, wintypes.DWORD]
    preference = ctypes.c_int(2)  # DWM_WINDOW_CORNER_PREFERENCE: round (Win11).
    dwm.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(preference), ctypes.sizeof(preference))
    return result and enabled
