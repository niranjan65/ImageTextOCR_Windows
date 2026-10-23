"""Draggable, always-on-top capture control; all callbacks stay on Tk's thread."""
import ctypes
from ctypes import wintypes
import sys
import tkinter as tk


def desktop_bounds(window):
    """Virtual-screen coordinates include displays left of or above the primary."""
    if sys.platform == 'win32':
        user = ctypes.windll.user32
        return tuple(user.GetSystemMetrics(index) for index in (76,77,78,79))
    return 0,0,window.winfo_screenwidth(),window.winfo_screenheight()


def monitor_bounds(window):
    if sys.platform == 'win32':
        class MonitorInfo(ctypes.Structure):
            _fields_ = [('size',wintypes.DWORD),('monitor',wintypes.RECT),('work',wintypes.RECT),('flags',wintypes.DWORD)]
        user = ctypes.windll.user32
        user.MonitorFromWindow.argtypes,user.MonitorFromWindow.restype = [wintypes.HWND,wintypes.DWORD],wintypes.HANDLE
        user.GetMonitorInfoW.argtypes = [wintypes.HANDLE,ctypes.POINTER(MonitorInfo)]
        info = MonitorInfo()
        info.size = ctypes.sizeof(info)
        handle = user.MonitorFromWindow(window.winfo_id(),2)
        if user.GetMonitorInfoW(handle,ctypes.byref(info)):
            area = info.work
            return area.left,area.top,area.right-area.left,area.bottom-area.top
    return desktop_bounds(window)


def place_window(window,x,y,width,height):
    window.geometry(f'{width}x{height}{x:+d}{y:+d}')
    window.update_idletasks()
    if sys.platform == 'win32':
        # Tk treats negative geometry as edge offsets, so use native coordinates.
        user = ctypes.windll.user32
        user.GetParent.argtypes,user.GetParent.restype = [wintypes.HWND],wintypes.HWND
        user.SetWindowPos.argtypes = [wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT]
        handle = user.GetParent(window.winfo_id()) or window.winfo_id()
        user.SetWindowPos(handle,wintypes.HWND(-1),x,y,width,height,0x0010)


class FloatingCaptureIcon(tk.Toplevel):
    SIZE = 56

    def __init__(self, master, on_capture, on_open, on_settings, on_saved, on_quit):
        super().__init__(master)
        self.withdraw()
        self.title('FedEx Capture')
        self.overrideredirect(True)
        self.attributes('-topmost', True)
        self.configure(bg='#ff00ff')
        if sys.platform == 'win32':
            self.attributes('-transparentcolor', '#ff00ff')
        self.on_capture = on_capture
        self.busy = False
        self.status_state = 'ready'
        self._message = 'FedEx: click to capture, drag to move, right-click for options'
        self._press_point = None
        self._dragged = False
        self._tooltip = None
        self._tooltip_after = None
        self.canvas = tk.Canvas(self, width=self.SIZE, height=self.SIZE, bg='#ff00ff', highlightthickness=0, cursor='hand2')
        self.canvas.pack()
        self.canvas.create_oval(2,2,54,54,fill='#4d148c',outline='#ff6600',width=3,tags='ring')
        self.canvas.create_rectangle(14,21,42,39,fill='white',outline='white',width=2)
        self.canvas.create_rectangle(19,17,29,22,fill='white',outline='white')
        self.canvas.create_oval(23,24,35,36,fill='#4d148c',outline='#4d148c')
        self.canvas.create_oval(26,27,32,33,fill='#ff6600',outline='#ff6600')
        self.canvas.create_oval(40,6,50,16,fill='#ff6600',outline='white',tags='indicator')
        self.canvas.bind('<ButtonPress-1>',self._press)
        self.canvas.bind('<B1-Motion>',self._drag)
        self.canvas.bind('<ButtonRelease-1>',self._release)
        self.canvas.bind('<Button-3>',self._menu)
        self.canvas.bind('<Enter>',self._schedule_tooltip)
        self.canvas.bind('<Leave>',self._hide_tooltip)
        self.menu = tk.Menu(self,tearoff=False)
        self.menu.add_command(label='Show FedEx Window',command=on_open)
        self.menu.add_command(label='Connection Settings',command=on_settings)
        self.menu.add_command(label='Open Last Saved Record',command=on_saved,state='disabled')
        self.menu.add_separator()
        self.menu.add_command(label='Exit',command=on_quit)
        self._position = (max(0, self.winfo_screenwidth()-self.SIZE-24), 100)
        self.geometry(f'{self.SIZE}x{self.SIZE}+{self._position[0]}+{self._position[1]}')

    def _place(self, x, y):
        left,top,width,height = desktop_bounds(self)
        x = max(left, min(round(x), left+width-self.SIZE))
        y = max(top, min(round(y), top+height-self.SIZE))
        self._position = (x,y)
        place_window(self,x,y,self.SIZE,self.SIZE)

    def show(self):
        self.deiconify()
        self._place(*self._position)
        self.lift()

    def hide(self):
        self._hide_tooltip()
        self.withdraw()

    def _press(self,event):
        self._hide_tooltip()
        self._press_point = (event.x_root,event.y_root)
        self._start_position = self._position
        self._dragged = False

    def _drag(self,event):
        if self._press_point is None:
            return
        dx,dy = event.x_root-self._press_point[0],event.y_root-self._press_point[1]
        if max(abs(dx),abs(dy)) >= 6:
            self._dragged = True
        if self._dragged:
            self._place(self._start_position[0]+dx,self._start_position[1]+dy)

    def _release(self,event):
        if self._press_point is None:
            return
        self._drag(event)
        clicked = not self._dragged
        self._press_point = None
        if clicked and not self.busy:
            self.on_capture()

    def set_status(self,message,state='ready',busy=False,can_open_record=False):
        self._message,self.status_state,self.busy = message,state,busy
        color = {'ready':'#ff6600','busy':'#ffc857','saved':'#2ecc71','error':'#ef4444'}.get(state,'#ff6600')
        self.canvas.itemconfigure('indicator',fill=color)
        self.canvas.itemconfigure('ring',outline=color)
        self.menu.entryconfigure('Open Last Saved Record',state='normal' if can_open_record else 'disabled')
        if self._tooltip is not None:
            self._tooltip_label.configure(text=self._message)

    def _menu(self,event):
        self._hide_tooltip()
        try:
            self.menu.tk_popup(event.x_root,event.y_root)
        finally:
            try:
                self.menu.grab_release()
            except tk.TclError:
                pass  # Exit can destroy the menu while its native popup is open.

    def _schedule_tooltip(self,_event=None):
        self._hide_tooltip()
        self._tooltip_after = self.after(500,self._show_tooltip)

    def _show_tooltip(self):
        self._tooltip_after = None
        self._tooltip = tk.Toplevel(self)
        self._tooltip.overrideredirect(True)
        self._tooltip.attributes('-topmost',True)
        self._tooltip_label = tk.Label(self._tooltip,text=self._message,bg='#17263c',fg='white',padx=10,pady=7,
                                       font=('Segoe UI',9),wraplength=280,justify='left')
        self._tooltip_label.pack()
        self._tooltip.update_idletasks()
        left,top,width,height = monitor_bounds(self)
        tip_width,tip_height = self._tooltip.winfo_reqwidth(),self._tooltip.winfo_reqheight()
        x = max(left,min(self.winfo_rootx()-tip_width+self.SIZE,left+width-tip_width))
        y = max(top,min(self.winfo_rooty()+self.SIZE+4,top+height-tip_height))
        place_window(self._tooltip,x,y,tip_width,tip_height)

    def _hide_tooltip(self,_event=None):
        if self._tooltip_after is not None:
            self.after_cancel(self._tooltip_after)
            self._tooltip_after = None
        if self._tooltip is not None:
            self._tooltip.destroy()
            self._tooltip = None

    def destroy(self):
        self._hide_tooltip()
        super().destroy()
