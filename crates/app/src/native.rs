//! Only this app's HWND is subclassed. No game window, process or memory is accessed.
use crate::AppWindow;
use raw_window_handle::{HasWindowHandle, RawWindowHandle};
use slint::{
    ComponentHandle,
    winit_030::{EventResult, WinitWindowAccessor},
};
use std::{cell::RefCell, ffi::c_void, mem::size_of};
use windows::Win32::{
    Foundation::{HWND, LPARAM, LRESULT, RECT, WPARAM},
    Graphics::{Dwm::*, Gdi::*},
    UI::{
        Controls::MARGINS,
        HiDpi::GetDpiForWindow,
        Shell::{DefSubclassProc, RemoveWindowSubclass, SetWindowSubclass},
        WindowsAndMessaging::*,
    },
};

thread_local! { static UI: RefCell<Option<slint::Weak<AppWindow>>> = const { RefCell::new(None) }; }

pub(crate) fn install(ui: &AppWindow, frames: Option<std::rc::Rc<RefCell<crate::FrameCapture>>>) {
    UI.with(|slot| *slot.borrow_mut() = Some(ui.as_weak()));
    let installed = std::rc::Rc::new(std::cell::Cell::new(false));
    ui.window().on_winit_window_event(move |window, event| {
        if matches!(
            event,
            slint::winit_030::winit::event::WindowEvent::RedrawRequested
        ) && let Some(frames) = &frames
        {
            let mut capture = frames.borrow_mut();
            if capture.frames.len() < 10000 {
                let ms = capture.start.elapsed().as_secs_f64() * 1000.0;
                capture.frames.push(ms);
            }
        }
        window.with_winit_window(|w| {
            if !installed.replace(true)
                && let Ok(handle) = w.window_handle()
                && let RawWindowHandle::Win32(handle) = handle.as_raw()
            {
                // SAFETY: the handle belongs to this event-loop thread and the subclass is
                // removed at WM_NCDESTROY; no pointer to Rust-owned data crosses the ABI.
                unsafe {
                    decorate(HWND(handle.hwnd.get() as *mut c_void));
                }
            }
            UI.with(|slot| {
                if let Some(ui) = slot.borrow().as_ref().and_then(|w| w.upgrade()) {
                    ui.set_is_maximized(w.is_maximized());
                }
            });
        });
        EventResult::Propagate
    });
}

unsafe fn decorate(hwnd: HWND) {
    unsafe {
        let style = GetWindowLongPtrW(hwnd, GWL_STYLE) as u32;
        SetWindowLongPtrW(
            hwnd,
            GWL_STYLE,
            (style
                | WS_THICKFRAME.0
                | WS_CAPTION.0
                | WS_SYSMENU.0
                | WS_MAXIMIZEBOX.0
                | WS_MINIMIZEBOX.0) as isize,
        );
        if !SetWindowSubclass(hwnd, Some(proc), 1, 0).as_bool() {
            return;
        }
        let corner = DWMWCP_ROUND;
        let _ = DwmSetWindowAttribute(
            hwnd,
            DWMWA_WINDOW_CORNER_PREFERENCE,
            &corner as *const _ as _,
            size_of::<DWM_WINDOW_CORNER_PREFERENCE>() as u32,
        );
        let margins = MARGINS {
            cxLeftWidth: 1,
            cxRightWidth: 1,
            cyTopHeight: 1,
            cyBottomHeight: 1,
        };
        let _ = DwmExtendFrameIntoClientArea(hwnd, &margins);
        let _ = SetWindowPos(
            hwnd,
            None,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED,
        );
    }
}

// Physical pixels in, native hit result out. Kept separate so every edge and DPI can be tested.
fn hit(x: i32, y: i32, width: i32, height: i32, scale: f32, maximized: bool) -> u32 {
    let edge = (7.0 * scale).round() as i32;
    if !maximized {
        let left = x < edge;
        let right = x >= width - edge;
        let top = y < edge;
        let bottom = y >= height - edge;
        if top && left {
            return HTTOPLEFT;
        }
        if top && right {
            return HTTOPRIGHT;
        }
        if bottom && left {
            return HTBOTTOMLEFT;
        }
        if bottom && right {
            return HTBOTTOMRIGHT;
        }
        if left {
            return HTLEFT;
        }
        if right {
            return HTRIGHT;
        }
        if top {
            return HTTOP;
        }
        if bottom {
            return HTBOTTOM;
        }
    }
    if y < (36.0 * scale).round() as i32 {
        let button = (46.0 * scale).round() as i32;
        if x >= width - 2 * button && x < width - button {
            return HTMAXBUTTON;
        }
        if x < width - 3 * button {
            return HTCAPTION;
        }
    }
    HTCLIENT
}

unsafe extern "system" fn proc(
    hwnd: HWND,
    message: u32,
    wp: WPARAM,
    lp: LPARAM,
    _: usize,
    _: usize,
) -> LRESULT {
    // SAFETY: Win32 supplies message-specific structs for this synchronous callback. Pointers are
    // used only for their documented message and are never stored after the call.
    unsafe {
        match message {
            WM_NCCALCSIZE if wp.0 != 0 => {
                let params = &mut *(lp.0 as *mut NCCALCSIZE_PARAMS);
                if IsZoomed(hwnd).as_bool() {
                    let monitor = MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST);
                    let mut info = MONITORINFO {
                        cbSize: size_of::<MONITORINFO>() as u32,
                        ..Default::default()
                    };
                    if GetMonitorInfoW(monitor, &mut info).as_bool() {
                        params.rgrc[0] = info.rcWork;
                    }
                }
                return LRESULT(0);
            }
            WM_NCHITTEST => {
                let mut rect = RECT::default();
                if GetWindowRect(hwnd, &mut rect).is_ok() {
                    let x = lp.0 as i16 as i32 - rect.left;
                    let y = (lp.0 >> 16) as i16 as i32 - rect.top;
                    return LRESULT(hit(
                        x,
                        y,
                        rect.right - rect.left,
                        rect.bottom - rect.top,
                        GetDpiForWindow(hwnd) as f32 / 96.0,
                        IsZoomed(hwnd).as_bool(),
                    ) as isize);
                }
            }
            WM_NCMOUSEMOVE => {
                UI.with(|slot| {
                    if let Some(ui) = slot.borrow().as_ref().and_then(|w| w.upgrade()) {
                        ui.set_max_hover(wp.0 as u32 == HTMAXBUTTON);
                    }
                });
            }
            WM_MOUSEMOVE | WM_NCMOUSELEAVE => {
                UI.with(|slot| {
                    if let Some(ui) = slot.borrow().as_ref().and_then(|w| w.upgrade()) {
                        ui.set_max_hover(false);
                    }
                });
            }
            WM_NCLBUTTONDOWN if wp.0 as u32 == HTMAXBUTTON => {
                return LRESULT(0);
            }
            WM_NCLBUTTONUP if wp.0 as u32 == HTMAXBUTTON => {
                let command = if IsZoomed(hwnd).as_bool() {
                    SC_RESTORE
                } else {
                    SC_MAXIMIZE
                };
                SendMessageW(hwnd, WM_SYSCOMMAND, Some(WPARAM(command as usize)), None);
                return LRESULT(0);
            }
            WM_NCRBUTTONUP if wp.0 as u32 == HTCAPTION => {
                let menu = GetSystemMenu(hwnd, false);
                if !menu.is_invalid() {
                    let x = lp.0 as i16 as i32;
                    let y = (lp.0 >> 16) as i16 as i32;
                    let command = TrackPopupMenu(
                        menu,
                        TPM_RETURNCMD | TPM_RIGHTBUTTON,
                        x,
                        y,
                        None,
                        hwnd,
                        None,
                    );
                    if command.0 != 0 {
                        SendMessageW(hwnd, WM_SYSCOMMAND, Some(WPARAM(command.0 as usize)), None);
                    }
                }
                return LRESULT(0);
            }
            WM_NCDESTROY => {
                let _ = RemoveWindowSubclass(hwnd, Some(proc), 1);
            }
            _ => {}
        }
        DefSubclassProc(hwnd, message, wp, lp)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn caption_controls_and_all_resize_edges_at_each_dpi() {
        for scale in [1.0, 1.25, 1.5, 2.0] {
            let w = (1200.0 * scale) as i32;
            let h = (800.0 * scale) as i32;
            for (x, y, want) in [
                (1, 1, HTTOPLEFT),
                (w - 1, 1, HTTOPRIGHT),
                (1, h - 1, HTBOTTOMLEFT),
                (w - 1, h - 1, HTBOTTOMRIGHT),
                (1, h / 2, HTLEFT),
                (w - 1, h / 2, HTRIGHT),
                (w / 2, 1, HTTOP),
                (w / 2, h - 1, HTBOTTOM),
            ] {
                assert_eq!(hit(x, y, w, h, scale, false), want);
            }
            assert_eq!(
                hit(w / 2, (20.0 * scale) as i32, w, h, scale, false),
                HTCAPTION
            );
            assert_eq!(
                hit(
                    w - (69.0 * scale) as i32,
                    (20.0 * scale) as i32,
                    w,
                    h,
                    scale,
                    false
                ),
                HTMAXBUTTON
            );
            assert_eq!(
                hit(
                    w - (23.0 * scale) as i32,
                    (20.0 * scale) as i32,
                    w,
                    h,
                    scale,
                    false
                ),
                HTCLIENT
            );
            assert_eq!(hit(1, h / 2, w, h, scale, true), HTCLIENT);
        }
    }
}
