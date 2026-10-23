"""Desktop behavior of the draggable capture button and existing upload flow."""
import gc
from pathlib import Path
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image
from ocr_app import OCRApp
from frappe_client import FrappeClient
from tests_support.frappe_fixture import FrappeFixture
from tests_support.rda_fixture import word_document


class FloatingCaptureTests(unittest.TestCase):
    def setUp(self):
        settings = patch('frappe_settings.save_preferences')
        settings.start()
        self.addCleanup(settings.stop)
        with patch.object(OCRApp, '_load_engine', lambda app: None):
            self.app = OCRApp()
        self.app.engine = object()
        self.server = FrappeFixture()
        self.server.auth_mode = 'api'
        client = FrappeClient('https://skylink.example', api_key=self.server.api_key,
                              api_secret=self.server.api_secret, opener=self.server.opener())
        self.app._on_connected(client, client.test_connection())
        self.app.enter_floating_mode()
        self.app.update()
        self.icon = self.app.floating_icon

    def tearDown(self):
        if hasattr(self, 'app'):
            for task in self.app.tk.splitlist(self.app.tk.call('after', 'info')):
                self.app.after_cancel(task)
            self.app.destroy()
            del self.app
        self.icon = None
        gc.collect()

    def wait_for(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.update()
            if predicate():
                return
            time.sleep(.01)
        self.fail('Floating capture did not reach the expected state')

    def click(self):
        x, y = self.icon.winfo_x()+25, self.icon.winfo_y()+25
        event = SimpleNamespace(x_root=x, y_root=y)
        self.icon._press(event)
        self.icon._release(event)

    def start_capture(self):
        def desktop(**kwargs):
            self.assertEqual(self.icon.state(), 'withdrawn', 'Icon must not enter the captured pixels')
            self.assertEqual(self.app.state(), 'withdrawn')
            return Image.new('RGB', (640, 400), 'white')
        with patch('PIL.ImageGrab.grab', side_effect=desktop):
            self.click()
            self.wait_for(lambda: self.app._capture_overlay is not None)
        return self.app._capture_overlay

    def test_compact_topmost_icon_replaces_dashboard(self):
        self.assertEqual(self.app.state(), 'withdrawn')
        self.assertTrue(self.icon.attributes('-topmost'))
        self.assertLessEqual(self.icon.winfo_width(), 64)
        self.assertLessEqual(self.icon.winfo_height(), 64)
        self.assertNotEqual(self.icon.state(), 'withdrawn')

    def test_drag_moves_icon_without_starting_capture(self):
        before = (self.icon.winfo_x(), self.icon.winfo_y())
        start = SimpleNamespace(x_root=before[0]+20, y_root=before[1]+20)
        end = SimpleNamespace(x_root=start.x_root-85, y_root=start.y_root+45)
        self.icon._press(start)
        self.icon._drag(end)
        self.icon._release(end)
        self.app.update()
        self.assertEqual((self.icon.winfo_x(), self.icon.winfo_y()), (before[0]-85, before[1]+45))
        self.assertFalse(self.app._capturing)
        self.assertEqual(self.server.post_count, 0)

    def test_drag_can_use_negative_monitor_coordinates_and_keeps_icon_reachable(self):
        with patch('floating_capture.desktop_bounds', return_value=(-300,-200,1200,800)):
            self.icon._place(-140,95)
            self.app.update()
            self.assertEqual((self.icon.winfo_x(),self.icon.winfo_y()),(-140,95))
            self.icon._place(5000,5000)
            self.app.update()
            self.assertEqual((self.icon.winfo_x(),self.icon.winfo_y()),(844,544))

    def test_click_excludes_icon_and_cancel_returns_to_same_position(self):
        before = (self.icon.winfo_x(), self.icon.winfo_y())
        overlay = self.start_capture()
        overlay._cancel()
        self.app.update()
        self.assertEqual(self.app.state(), 'withdrawn')
        self.assertNotEqual(self.icon.state(), 'withdrawn')
        self.assertEqual((self.icon.winfo_x(), self.icon.winfo_y()), before)
        self.assertEqual(self.server.post_count, 0)

    def test_floating_capture_automatically_sends_once_without_showing_dashboard(self):
        self.app.auto_send_var.set(False)  # Floating capture always sends, even if dashboard preference was off.
        overlay = self.start_capture()
        document = word_document({'form_id': '0430', 'shipper_name': 'JAMES PARK'})
        with patch('capture_workflow.extract_document', return_value=document):
            overlay._press(SimpleNamespace(x=20, y=20))
            overlay._release(SimpleNamespace(x=300, y=200))
            self.assertTrue(self.app.running)
            self.click()  # Busy clicks cannot overlap the current create.
            self.wait_for(lambda: not self.app.running)
        self.assertEqual(self.server.post_count, 1)
        self.assertEqual(self.app._last_saved.stored['form_id'], '0430')
        self.assertEqual(self.app.state(), 'withdrawn')
        self.assertEqual(self.icon.status_state, 'saved')
        self.assertFalse(self.app._capturing)

    def test_capture_failure_recovers_icon_without_blocking_dialog(self):
        with patch('PIL.ImageGrab.grab', side_effect=OSError('Capture unavailable')), patch('ocr_app.messagebox.showerror') as popup:
            self.click()
            self.wait_for(lambda: not self.app._capturing)
        self.assertFalse(popup.called)
        self.assertNotEqual(self.icon.state(), 'withdrawn')
        self.assertEqual(self.app.state(), 'withdrawn')
        self.assertEqual(self.server.post_count, 0)

    def test_failed_upload_is_visible_on_icon_without_showing_dashboard(self):
        self.server.mode = 'expired'
        overlay = self.start_capture()
        with patch('capture_workflow.extract_document',return_value=word_document({'form_id':'0430'})):
            overlay._press(SimpleNamespace(x=20,y=20))
            overlay._release(SimpleNamespace(x=300,y=200))
            self.wait_for(lambda: not self.app.running)
        self.assertEqual(self.icon.status_state,'error')
        self.assertFalse(self.icon.busy)
        self.assertIn('Authentication failed',self.icon._message)
        self.assertEqual(self.app.state(),'withdrawn')
        self.assertEqual(self.server.post_count,1)

    def test_previous_saved_record_remains_available_after_a_later_capture_fails(self):
        document = word_document({'form_id':'0430'})
        for mode in (None,'expired'):
            self.server.mode = mode
            overlay = self.start_capture()
            with patch('capture_workflow.extract_document',return_value=document):
                overlay._press(SimpleNamespace(x=20,y=20))
                overlay._release(SimpleNamespace(x=300,y=200))
                self.wait_for(lambda: not self.app.running)
        opened = []
        self.assertEqual(self.icon.menu.entrycget('Open Last Saved Record','state'),'normal')
        with patch('ocr_app.webbrowser.open',side_effect=opened.append):
            self.icon.menu.invoke('Open Last Saved Record')
        self.assertEqual(opened,['https://skylink.example/desk/rda-information/new-1'])
        self.assertEqual(self.server.post_count,2)

    def test_tooltip_stays_on_the_icons_monitor_with_negative_coordinates(self):
        with patch('floating_capture.desktop_bounds',return_value=(-1000,0,2000,1000)), patch('floating_capture.monitor_bounds',return_value=(-1000,0,1000,1000),create=True):
            self.icon._place(-400,100)
            self.icon._show_tooltip()
            self.app.update()
            tooltip = self.icon._tooltip
            self.assertLess(tooltip.winfo_x(),0)
            self.assertGreaterEqual(tooltip.winfo_x(),-1000)
            self.assertLessEqual(tooltip.winfo_x()+tooltip.winfo_width(),0)
            self.assertGreater(tooltip.winfo_y(),100)

    def test_unconnected_click_opens_settings_and_does_not_capture(self):
        self.app._frappe_client = None
        self.click()
        self.app.update()
        self.assertIsNotNone(self.app._connection_dialog)
        self.assertTrue(self.app._connection_dialog.winfo_viewable())
        self.assertFalse(self.app._capturing)
        self.assertEqual(self.server.post_count,0)

    def test_engine_failure_appears_on_icon_without_a_hidden_modal_dialog(self):
        self.app.engine = None
        with patch('ocr_app.messagebox.showerror') as popup:
            self.app.result_queue.put(('engine_error','Engine unavailable'))
            self.app._drain_results()
        self.assertFalse(popup.called)
        self.assertEqual(self.icon.status_state,'error')
        self.assertIn('OCR engine not available',self.icon._message)
        self.assertEqual(self.app.state(),'withdrawn')

    def test_capture_file_error_returns_to_icon_without_a_blocking_dialog(self):
        overlay = self.start_capture()
        with patch.object(Image.Image,'save',side_effect=OSError('Disk unavailable')), patch('ocr_app.messagebox.showerror') as popup:
            overlay._press(SimpleNamespace(x=20,y=20))
            overlay._release(SimpleNamespace(x=300,y=200))
            self.app.update()
        self.assertFalse(popup.called)
        self.assertEqual(self.app.state(),'withdrawn')
        self.assertNotEqual(self.icon.state(),'withdrawn')
        self.assertEqual(self.icon.status_state,'error')
        self.assertEqual(self.server.post_count,0)

    def test_dashboard_ocr_error_after_hiding_window_does_not_open_modal(self):
        with patch('ocr_app.messagebox.showerror') as popup:
            self.app.result_queue.put(('ocr_error','OCR failed'))
            self.app._drain_results()
        self.assertFalse(popup.called)
        self.assertEqual(self.icon.status_state,'error')
        self.assertEqual(self.app.state(),'withdrawn')

    def test_right_click_menu_can_open_dashboard_and_return_to_icon(self):
        self.icon.menu.invoke('Show FedEx Window')
        self.app.update()
        self.assertNotEqual(self.app.state(), 'withdrawn')
        self.assertEqual(self.icon.state(), 'withdrawn')
        self.app.floating_btn.invoke()
        self.app.update()
        self.assertEqual(self.app.state(), 'withdrawn')
        self.assertNotEqual(self.icon.state(), 'withdrawn')

    def test_settings_remain_reachable_from_floating_mode(self):
        self.icon.menu.invoke('Connection Settings')
        self.app.update()
        self.assertNotEqual(self.app.state(), 'withdrawn')
        self.assertIsNotNone(self.app._connection_dialog)
        self.assertTrue(self.app._connection_dialog.winfo_viewable())

    def test_exit_menu_destroys_icon_and_cancels_pending_capture(self):
        self.click()
        self.assertIsNotNone(self.app._capture_after)
        self.icon.menu.invoke('Exit')
        self.assertTrue(self.app._closed)
        self.assertIsNone(self.app._capture_after)
        self.assertEqual(self.server.post_count, 0)
        del self.app
