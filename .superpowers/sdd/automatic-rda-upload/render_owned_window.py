"""Render a development app's own window for local visual verification."""
import ctypes as c
from ctypes import wintypes as w
import sys
from PIL import Image

pid, title_fragment, output = int(sys.argv[1]), sys.argv[2], sys.argv[3]
c.windll.shcore.SetProcessDpiAwareness(2)
u, g = c.windll.user32, c.windll.gdi32
windows = []
callback_type = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
@callback_type
def visit(handle, _):
    process = w.DWORD()
    u.GetWindowThreadProcessId(handle, c.byref(process))
    if process.value == pid:
        title = c.create_unicode_buffer(512)
        u.GetWindowTextW(handle, title, len(title))
        if title_fragment in title.value:
            windows.append((handle, title.value))
    return True
u.EnumWindows(visit, 0)
if not windows:
    raise SystemExit('Requested owned window is not available')
handle, title = windows[0]
u.GetWindowDC.argtypes, u.GetWindowDC.restype = [w.HWND], w.HDC
g.CreateCompatibleDC.argtypes, g.CreateCompatibleDC.restype = [w.HDC], w.HDC
g.CreateCompatibleBitmap.argtypes, g.CreateCompatibleBitmap.restype = [w.HDC,c.c_int,c.c_int], w.HBITMAP
g.SelectObject.argtypes, g.SelectObject.restype = [w.HDC,w.HGDIOBJ], w.HGDIOBJ
u.PrintWindow.argtypes = [w.HWND,w.HDC,w.UINT]
g.GetDIBits.argtypes = [w.HDC,w.HBITMAP,w.UINT,w.UINT,c.c_void_p,c.c_void_p,w.UINT]
g.DeleteObject.argtypes, g.DeleteDC.argtypes = [w.HGDIOBJ], [w.HDC]
u.ReleaseDC.argtypes = [w.HWND,w.HDC]
rect = w.RECT()
u.GetWindowRect(handle, c.byref(rect))
width, height = rect.right-rect.left, rect.bottom-rect.top
hdc = u.GetWindowDC(handle)
mem = g.CreateCompatibleDC(hdc)
bmp = g.CreateCompatibleBitmap(hdc,width,height)
old = g.SelectObject(mem,bmp)
class Header(c.Structure):
    _fields_ = [('size',w.DWORD),('width',w.LONG),('height',w.LONG),('planes',w.WORD),('bits',w.WORD),('compression',w.DWORD),('image_size',w.DWORD),('x',w.LONG),('y',w.LONG),('used',w.DWORD),('important',w.DWORD)]
info = Header(c.sizeof(Header),width,-height,1,32,0,0,0,0,0,0)
pixels = c.create_string_buffer(width*height*4)
try:
    if not u.PrintWindow(handle,mem,2) or not g.GetDIBits(mem,bmp,0,height,pixels,c.byref(info),0):
        raise RuntimeError('App render failed')
    Image.frombuffer('RGB',(width,height),pixels,'raw','BGRX',0,1).save(output)
finally:
    g.SelectObject(mem,old)
    g.DeleteObject(bmp)
    g.DeleteDC(mem)
    u.ReleaseDC(handle,hdc)
print(title)
